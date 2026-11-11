"""Run the agent over a folder of tasks, the way the organisers run our image.

    python scripts/main.py --input_dir <inputs> --output_dir <outputs>

Rules this file enforces:
  - one <task>.stp per task, STEP only, written to output_dir (work files go to /tmp)
  - a file exists for every task from the first minute: a bounding-box solid is
    written before any model call and replaced when a real part is ready
  - the whole run stays inside the wall-clock budget (1 hour limit; default 50 min)
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import get_backend
from .cases import load_tasks
from .pipeline import Agent
from .types import Task


def make_agent(llm=None) -> Agent:
    from .llm import LLM, OpenAICompatLLM

    if llm is None:
        try:
            llm = OpenAICompatLLM()
        except Exception as exc:  # no endpoint configured: every task gets its fallback box
            print(f"WARNING: no model endpoint ({type(exc).__name__}: {exc}); writing fallback boxes only")
            llm = LLM()
    return Agent(
        llm,
        get_backend(os.environ.get("FORGE_BACKEND", "cadquery")),
        n_candidates=int(os.environ.get("FORGE_CANDIDATES", "3")),
        rounds=int(os.environ.get("FORGE_ROUNDS", "2")),
    )


def run_all(input_dir: Path, output_dir: Path, agent: Agent | None = None, only: list[str] | None = None,
            work_dir: Path | None = None) -> list[dict]:
    budget = float(os.environ.get("FORGE_BUDGET_S", "3000"))
    deadline = time.monotonic() + budget
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir or tempfile.mkdtemp(prefix="forge-"))
    agent = agent or make_agent()
    tasks = load_tasks(input_dir, only)

    for task in tasks:  # the floor first, so a later crash or timeout never leaves a gap
        box = agent.fallback(task, work / task.name)
        if box:
            shutil.copyfile(box, output_dir / f"{task.name}.stp")

    def one(task: Task) -> dict:
        summary = agent.solve(task, work / task.name, deadline=deadline - 60)
        if summary["step"]:
            shutil.copyfile(summary["step"], output_dir / f"{task.name}.stp")
        print(f"{task.name}: {summary['chosen']}  self-score "
              f"{summary['self_check'].get('self_score', 0):.3f}", flush=True)
        return summary

    with ThreadPoolExecutor(int(os.environ.get("FORGE_WORKERS", "3"))) as pool:
        summaries = list(pool.map(one, tasks))
    print(f"done in {budget - (deadline - time.monotonic()):.0f}s, work files in {work}")
    return summaries
