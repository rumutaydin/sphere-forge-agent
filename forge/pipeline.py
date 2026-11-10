"""The orchestrator: wires the stages together and nothing else.

    Task -> understand -> [ build -> repair -> verify ] x N -> select -> part

Stage logic lives in forge/stages/. Keep this file thin so the tracks never
need to edit it at the same time.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import CadBackend
from .llm import LLM
from .stages.build import generate, run_with_repair
from .stages.select import select
from .stages.understand import make_spec, task_content
from .stages.verify import critique
from .types import Candidate, Task


class Agent:
    def __init__(self, llm: LLM, backend: CadBackend, n_candidates: int = 3,
                 repairs: int = 3, rounds: int = 2, effort: str = "high"):
        self.llm, self.backend = llm, backend
        self.n_candidates, self.repairs, self.rounds, self.effort = n_candidates, repairs, rounds, effort

    def solve(self, task: Task, out_dir: Path) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        blocks = task_content(task)
        spec = make_spec(self.llm, task, self.effort)
        (out_dir / "spec.md").write_text(spec.text)

        def work(i: int) -> Candidate:
            cand = Candidate(i, generate(self.llm, self.backend, blocks, spec, self.effort), out_dir / f"cand{i}")
            if cand.code:
                run_with_repair(self.llm, self.backend, cand, blocks, self.repairs, self.effort)
                critique(self.llm, self.backend, cand, blocks, self.rounds, self.repairs, self.effort)
            return cand

        with ThreadPoolExecutor(self.n_candidates) as pool:
            cands = list(pool.map(work, range(self.n_candidates)))
        best = select(cands)
        summary = {
            "chosen": best.idx if best else None,
            "step": str(best.result.step_path) if best else None,
            "stl": str(best.result.stl_path) if best else None,
            "candidates": [{"idx": c.idx, "usable": c.usable, "approved": c.approved, "log": c.log} for c in cands],
        }
        if best:
            (out_dir / "final.py").write_text(best.code)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
        return summary
