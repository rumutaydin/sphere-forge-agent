"""The orchestrator: wires the stages together and nothing else.

    Task -> plan -> [ build -> repair -> verify ] x N -> select -> <name>.step

A box of the target's bounding box is the floor: if nothing builds, that is
what we hand in, because a missing file scores 0 and a box scores about 0.3.
Stage logic lives in forge/stages/. Keep this file thin.
"""
from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import CadBackend
from .llm import LLM
from .stages.build import generate, run_with_repair
from .stages.select import select
from .stages.understand import make_plan, task_content
from .stages.verify import critique
from .types import Candidate, Task


class Agent:
    def __init__(self, llm: LLM, backend: CadBackend, n_candidates: int = 3, repairs: int = 3, rounds: int = 2):
        self.llm, self.backend = llm, backend
        self.n_candidates, self.repairs, self.rounds = n_candidates, repairs, rounds

    def fallback(self, task: Task, out_dir: Path) -> Path | None:
        """Bounding-box solid from the facts. Needs no model."""
        box = task.facts.get("bounding_box_mm")
        if not box:
            return None
        res = self.backend.execute(self.backend.box_code(box["x"], box["y"], box["z"]), out_dir / "fallback")
        return res.step_path if res.ok else None

    def solve(self, task: Task, out_dir: Path, deadline: float | None = None) -> dict:
        """Returns a summary; summary["step"] is the STEP file to hand in (or None)."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        def time_left() -> bool:
            return deadline is None or time.monotonic() < deadline

        cands: list[Candidate] = []
        try:
            blocks = task_content(task)
            plan = make_plan(self.llm, task)
            (out_dir / "plan.md").write_text(plan)

            def work(i: int) -> Candidate:
                cand = Candidate(i, generate(self.llm, self.backend, blocks, plan), out_dir / f"cand{i}")
                if cand.code:
                    run_with_repair(self.llm, self.backend, cand, task, blocks, self.repairs if time_left() else 0)
                    if time_left():
                        critique(self.llm, self.backend, cand, task, self.rounds, self.repairs)
                return cand

            with ThreadPoolExecutor(self.n_candidates) as pool:
                cands = list(pool.map(work, range(self.n_candidates)))
            error = None
        except Exception as exc:  # a dead endpoint must not cost us the fallback
            error = f"{type(exc).__name__}: {exc}"

        best = select(cands)
        final = out_dir / f"{task.name}.step"
        if best:
            shutil.copyfile(best.result.step_path, final)
            (out_dir / "final.py").write_text(best.code)
        else:
            box = self.fallback(task, out_dir)
            final = shutil.copyfile(box, final) if box else None
        summary = {
            "task": task.name,
            "step": str(final) if final else None,
            "chosen": best.idx if best else "fallback box" if final else None,
            "self_check": best.check if best else {},
            "error": error,
            "candidates": [{"idx": c.idx, "usable": c.usable, "approved": c.approved,
                            "self_score": c.self_score, "log": c.log} for c in cands],
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
        return summary
