"""Run the agent over a folder of tasks, the way the organisers run our image.

    python scripts/main.py --input_dir <inputs> --output_dir <outputs>

The run's summary (which tier each part's file came from, and for every exact program the
verdict under the strict and the relaxed rule) is printed and written to <work>/run_summary.json;
the output folder holds STEP files only.

Rules this file enforces:
  - one <task>.stp per task, STEP only, written to output_dir (work files go to /tmp)
  - a file exists for every task from the first minute: a bounding-box solid first,
    replaced by the no-model part (pass 1), replaced by a model candidate only if better
  - the whole run stays inside the wall-clock budget (1 hour limit; default 50 min)

Settings (environment): FORGE_BUDGET_S (3000), FORGE_PASS1_S (600, per part), FORGE_WORKERS (9),
FORGE_CANDIDATES (2), FORGE_CARVE (0), FORGE_ROUNDS (0), FORGE_FACES (on), FORGE_DEPTH (on), FORGE_RADIAL (on),
FORGE_MODEL_MARGIN (0.02), FORGE_EDGE_VETO (0.015), FORGE_MODEL_PASS (on),
FORGE_SKIP_ABOVE (0.90: no model BODIES for a part whose no-model estimate is at least this; exact programs run on every part),
FORGE_EXACT (0, whole-part programs per part) and FORGE_EXACT_* (forge/stages/exact.py),
FORGE_IGNORE_FACTS (0; 1 = build from the brief even where facts.json exists), FORGE_BRIEF_LLM (0; 1 = one
extra text call per task without facts.json to find bores the parser missed, FORGE_BRIEF_LLM_S (60) each).
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
from .cases import load_tasks, settle_brief_facts
from .compile import publish_file
from .pipeline import Agent, score_of
from .stages.select import source_of
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
        rounds=int(os.environ.get("FORGE_ROUNDS", "0")),
        n_carve=int(os.environ.get("FORGE_CARVE", "0")),
        margin=float(os.environ.get("FORGE_MODEL_MARGIN", "0.02")),
        edge_veto=float(os.environ.get("FORGE_EDGE_VETO", "0.015")),
    )


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
    os.environ.pop("FORGE_FACTS_DIR", None)      # an earlier run's rebuilt facts are not this run's
    tasks = load_tasks(input_dir, only)
    workers = int(os.environ.get("FORGE_WORKERS", "9"))
    out_file = {t.name: output_dir / f"{t.name}.stp" for t in tasks}

    for task in tasks:  # the floor first, so a later crash or timeout never leaves a gap
        box = agent.fallback(task, work / task.name)
        if box:
            publish_file(box, out_file[task.name])
    settle_brief_facts(tasks, work / "_facts", agent.llm)    # tasks without facts.json: facts from the brief

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
    if type(agent.llm).__name__ == "OpenAICompatLLM":      # a real endpoint (not the tests' scripted one)
        wait_for_endpoint(min(float(os.environ.get("FORGE_ENDPOINT_WAIT_S", "300")), max(deadline - time.monotonic() - 600, 0)))

    def one(task: Task) -> dict:
        floor = floors[task.name]
        # The estimate of the no-model part is not the leaderboard (part 2: 0.944 there), so a good
        # estimate spares a part the model bodies only; exact programs are tried on every part.
        bodies = not (floor and score_of(floor["check"]) >= skip_above)
        if not has_model or not (bodies or agent.n_exact) or time.monotonic() > deadline - 120:
            return {"task": task.name, "step": floor["step"] if floor else str(out_file[task.name]),
                    "chosen": floor["name"] if floor else "fallback box", "self_check": floor["check"] if floor else {},
                    "error": None, "candidates": []}
        summary = agent.solve(task, work / task.name, deadline=deadline - 60, publish=out_file[task.name], floor=floor,
                              bodies=bodies)
        print(f"{task.name}: {summary['chosen']}  estimate {score_of(summary['self_check']):.3f}", flush=True)
        return summary

    order = sorted(tasks, key=lambda t: score_of(floors[t.name]["check"]) if floors[t.name] else -1.0)
    with ThreadPoolExecutor(workers) as pool:
        by_name = {s["task"]: s for s in pool.map(one, order)}
    summaries = [by_name[t.name] for t in tasks]
    write_run_summary(summaries, floors, work, time.monotonic() - t0)
    print(f"done in {time.monotonic() - t0:.0f}s, work files in {work}", flush=True)
    return summaries


def endpoint_up() -> tuple[bool, str]:
    """GET OPENAI_BASE_URL/models with the key: (answers, what happened)."""
    import urllib.request

    url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200, f"{url}: HTTP {r.status}"
    except Exception as exc:
        return False, f"{url}: {type(exc).__name__}: {exc}"


def wait_for_endpoint(max_s: float) -> bool:
    """Right before the model pass: make sure the endpoint answers, waiting up to `max_s`.
    If it never does, the run goes on (pass-1 files are written) with a loud line. Never raises."""
    t0 = time.monotonic()
    while True:
        ok, what = endpoint_up()
        if ok:
            print(f"endpoint check: {what}", flush=True)
            return True
        spent = time.monotonic() - t0
        if spent >= max_s:
            print(f"!!!!! ENDPOINT DOWN before the model pass ({what}); waited {spent:.0f}s. "
                  f"Going on: model calls will retry, else every part keeps its pass-1 file. !!!!!", flush=True)
            return False
        print(f"endpoint check: not answering ({what}); retrying, {spent:.0f}s of {max_s:.0f}s", flush=True)
        time.sleep(15)


def write_run_summary(summaries: list[dict], floors: dict, work: Path, seconds: float) -> None:
    """Per part: the tier its file came from and, for every exact program, the verdict under the
    strict and the relaxed rule with the numbers. Printed, and kept in <work>/run_summary.json. Never raises."""
    try:
        parts = {}
        for s in summaries:
            f = floors.get(s["task"])
            s.setdefault("source", source_of(s.get("chosen")))
            parts[s["task"]] = {
                "source": s["source"], "chosen": s.get("chosen"), "estimate": round(score_of(s.get("self_check") or {}), 4),
                "hull": {"name": f["name"], "estimate": round(score_of(f["check"]), 4)} if f else None,
                "rule": s.get("rule"), "would_choose": s.get("would_choose"), "below_exact": s.get("below_exact"),
                "exact_verdicts": s.get("exact_verdicts", []), "error": s.get("error")}
            print(f"{s['task']}: source {s['source']} ({s.get('chosen')})", flush=True)
            for v in s.get("exact_verdicts", []):
                print(f"   {v['candidate']}: strict {'ADMIT' if v['strict']['admit'] else 'refuse'}, "
                      f"relaxed {'ADMIT' if v['relaxed']['admit'] else 'refuse'}; volume x{v.get('volume_ratio') or 0:.3f}, "
                      f"holes {v.get('genus')}/{v.get('genus_target')}, worst view {v.get('iou_min') or 0:.3f}, "
                      f"mean {v.get('iou_mean') or 0:.3f}"
                      + ("" if v["strict"]["admit"] else "; strict: " + "; ".join(v["strict"]["why"][:4])), flush=True)
            w = s.get("would_choose")
            if w and w["strict"] != w["relaxed"]:
                print(f"   the rules differ: strict -> {w['strict']}, relaxed -> {w['relaxed']}", flush=True)
        count = lambda key: {t: sum(1 for p in parts.values() if key(p) == t) for t in ("exact", "body", "hull", "box")}
        out = {"seconds": round(seconds), "by_source": count(lambda p: p["source"]),
               "by_source_if_strict": count(lambda p: source_of((p["would_choose"] or {}).get("strict", p["chosen"]))),
               "by_source_if_relaxed": count(lambda p: source_of((p["would_choose"] or {}).get("relaxed", p["chosen"]))),
               "parts": parts}
        print(f"sources: {out['by_source']}; strict rule would give {out['by_source_if_strict']}, "
              f"relaxed {out['by_source_if_relaxed']}", flush=True)
        (work / "run_summary.json").write_text(json.dumps(out, indent=1))
    except Exception as exc:
        print(f"NOTE: run summary not written ({type(exc).__name__}: {exc})", flush=True)
