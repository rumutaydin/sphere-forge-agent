"""Run the agent over a folder of tasks, the way the organisers run our image.

    python scripts/main.py --input_dir <inputs> --output_dir <outputs>

Rules this file enforces:
  - one <task>.stp per task, STEP only, written to output_dir (work files go to /tmp)
  - a file exists for every task from the first minute: a bounding-box solid first,
    replaced by the no-model part (pass 1), replaced by a model candidate only if better
  - the whole run stays inside the wall-clock budget (1 hour limit; default 50 min)

Settings (environment): FORGE_BUDGET_S (3000), FORGE_PASS1_S (600, per part), FORGE_WORKERS (9),
FORGE_CANDIDATES (2), FORGE_CARVE (0), FORGE_ROUNDS (0), FORGE_FACES (on), FORGE_DEPTH (on), FORGE_RADIAL (on),
FORGE_MODEL_MARGIN (0.02), FORGE_EDGE_VETO (0.015), FORGE_MODEL_PASS (on), FORGE_SKIP_ABOVE (0.90).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import get_backend
from .cases import load_tasks
from .compile import publish_file
from .pipeline import Agent, score_of
from .types import Task


def make_agent(llm=None) -> Agent:
    from .llm import LLM, OpenAICompatLLM

    if llm is None:
        try:
            if os.environ.get("FORGE_MODEL_PASS", "on").lower() in ("off", "0", "no", "false"):
                raise RuntimeError("FORGE_MODEL_PASS=off")
            llm = OpenAICompatLLM()
        except Exception as exc:  # no endpoint configured: every task keeps its no-model part
            print(f"NOTE: no model pass ({type(exc).__name__}: {exc})", flush=True)
            llm = LLM()
    return Agent(
        llm,
        get_backend(os.environ.get("FORGE_BACKEND", "cadquery")),
        n_candidates=int(os.environ.get("FORGE_CANDIDATES", "2")),
        repairs=int(os.environ.get("FORGE_REPAIRS", "2")),
        rounds=int(os.environ.get("FORGE_ROUNDS", "0")),
        n_carve=int(os.environ.get("FORGE_CARVE", "0")),
        margin=float(os.environ.get("FORGE_MODEL_MARGIN", "0.02")),
        edge_veto=float(os.environ.get("FORGE_EDGE_VETO", "0.015")),
        vlm=_vision_llm(),
    )


def _vision_llm():
    """A second endpoint for a vision model (FORGE_VISION_BASE_URL / _API_KEY / _MODEL), or None."""
    model = os.environ.get("FORGE_VISION_MODEL", "").strip()
    if not model:
        return None
    from .llm import OpenAICompatLLM

    return OpenAICompatLLM(model=model, base_url=os.environ.get("FORGE_VISION_BASE_URL") or None,
                           api_key=os.environ.get("FORGE_VISION_API_KEY") or None)


def pass1(task: Task, work: Path, out_file: Path, budget_s: float) -> dict | None:
    """The no-model part, built in its own process so a kernel hang cannot stall the run.
    The process overwrites `out_file` itself each time it finds a better part."""
    out = work / "pass1"
    if task.dir is None or not task.facts.get("bounding_box_mm"):
        return None
    try:
        proc = subprocess.run([sys.executable, "-m", "forge.compile", str(task.dir), str(out), str(out_file), str(budget_s * 0.8)],
                              cwd=Path(__file__).resolve().parents[1], timeout=budget_s, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"{task.name}: pass 1 ended with code {proc.returncode}; keeping what it had. "
                  f"{(proc.stderr or '').strip()[-300:]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"{task.name}: pass 1 stopped at {budget_s:.0f}s; keeping what it had", flush=True)
    try:
        rows = json.loads((out / "compile.json").read_text())
    except Exception:
        return None
    return rows[0] if rows else None


def run_all(input_dir: Path, output_dir: Path, agent: Agent | None = None, only: list[str] | None = None,
            work_dir: Path | None = None) -> list[dict]:
    t0 = time.monotonic()
    budget = float(os.environ.get("FORGE_BUDGET_S", "3000"))
    deadline = t0 + budget
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir or tempfile.mkdtemp(prefix="forge-"))
    agent = agent or make_agent()
    tasks = load_tasks(input_dir, only)
    workers = int(os.environ.get("FORGE_WORKERS", "9"))
    out_file = {t.name: output_dir / f"{t.name}.stp" for t in tasks}

    for task in tasks:  # the floor first, so a later crash or timeout never leaves a gap
        box = agent.fallback(task, work / task.name)
        if box:
            publish_file(box, out_file[task.name])

    # pass 1: no model. Seconds to a few minutes per part, all parts at once.
    p1_budget = min(float(os.environ.get("FORGE_PASS1_S", "600")), max(budget - 120, 30))
    with ThreadPoolExecutor(min(workers, os.cpu_count() or 4)) as pool:
        floors = dict(zip([t.name for t in tasks],
                          pool.map(lambda t: pass1(t, work / t.name, out_file[t.name], p1_budget), tasks)))
    for task in tasks:
        f = floors[task.name]
        print(f"{task.name}: pass 1 {f['name'] if f else 'nothing'}  estimate {score_of(f['check']) if f else 0:.3f}", flush=True)
    print(f"pass 1 done at {time.monotonic() - t0:.0f}s", flush=True)

    # pass 2: the model, worst parts first; a part that is already good is left alone.
    skip_above = float(os.environ.get("FORGE_SKIP_ABOVE", "0.90"))
    has_model = type(agent.llm).__name__ != "LLM"

    def one(task: Task) -> dict:
        floor = floors[task.name]
        if not has_model or (floor and score_of(floor["check"]) >= skip_above) or time.monotonic() > deadline - 120:
            return {"task": task.name, "step": floor["step"] if floor else str(out_file[task.name]),
                    "chosen": floor["name"] if floor else "fallback box", "self_check": floor["check"] if floor else {},
                    "error": None, "candidates": []}
        summary = agent.solve(task, work / task.name, deadline=deadline - 60, publish=out_file[task.name], floor=floor)
        print(f"{task.name}: {summary['chosen']}  estimate {score_of(summary['self_check']):.3f}", flush=True)
        return summary

    order = sorted(tasks, key=lambda t: score_of(floors[t.name]["check"]) if floors[t.name] else -1.0)
    with ThreadPoolExecutor(workers) as pool:
        by_name = {s["task"]: s for s in pool.map(one, order)}
    print(f"done in {time.monotonic() - t0:.0f}s, work files in {work}", flush=True)
    return [by_name[t.name] for t in tasks]
