"""The orchestrator: wires the stages together and nothing else.

    pass 1 (forge.compile, no model)   silhouette body + bores from the facts -> written at once
    pass 2 (this file, the model)      [ body program -> finished by code -> repair ] x N -> select

The file in the output folder is always the best part known so far: a box first, then the
no-model part, then any candidate whose estimate is higher. Nothing waits for the end of
a part, so a timeout or a dead endpoint cannot lose one. Stage logic lives in
forge/stages/ and forge/compile.py. Keep this file thin.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import CadBackend
from .compile import publish_file
from .llm import LLM
from .stages.build import floor_note, generate, run_with_repair
from .stages.understand import task_content
from .stages.verify import critique
from .types import Candidate, Task


def score_of(check: dict) -> float:
    """What candidates are ranked by: the leaderboard estimate when the views allowed one."""
    return float(check.get("estimate", check.get("self_score", 0.0))) if check else 0.0


class Agent:
    def __init__(self, llm: LLM, backend: CadBackend, n_candidates: int = 2, repairs: int = 2, rounds: int = 0):
        self.llm, self.backend = llm, backend
        self.n_candidates, self.repairs, self.rounds = n_candidates, repairs, rounds

    def fallback(self, task: Task, out_dir: Path) -> Path | None:
        """Bounding-box solid from the facts. Needs no model."""
        box = task.facts.get("bounding_box_mm")
        if not box:
            return None
        res = self.backend.execute(self.backend.box_code(box["x"], box["y"], box["z"]), out_dir / "fallback")
        return res.step_path if res.ok else None

    def solve(self, task: Task, out_dir: Path, deadline: float | None = None,
              publish: Path | None = None, floor: dict | None = None) -> dict:
        """Model pass for one task. `floor` is the best no-model row from forge.compile (or None);
        `publish` is the output file, overwritten whenever a candidate beats the best so far.
        Returns a summary; summary["step"] is the best STEP file known (or None)."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        best = {"score": score_of(floor["check"]) if floor else -1.0, "step": floor["step"] if floor else None,
                "chosen": floor["name"] if floor else None, "check": floor["check"] if floor else {}, "code": None}
        hull = out_dir / "pass1" / "hull.step"
        hull = hull if hull.is_file() else None
        cands: list[Candidate] = []
        error = None

        def offer(cand: Candidate) -> None:
            if not cand.usable or (floor and not cand.check):
                return
            with lock:
                if score_of(cand.check) > best["score"] + 1e-9 or best["step"] is None:
                    best.update(score=score_of(cand.check), step=str(cand.result.step_path),
                                chosen=f"model candidate {cand.idx}", check=cand.check, code=cand.code)
                    if publish:
                        publish_file(cand.result.step_path, publish)

        def work(i: int) -> Candidate:
            cand = Candidate(i, "", out_dir / f"cand{i}")
            try:
                cand.code = generate(self.llm, self.backend, blocks, note, deadline)
                if cand.code:
                    run_with_repair(self.llm, self.backend, cand, task, blocks, self.repairs, hull, deadline)
                    offer(cand)
                    if self.rounds and (deadline is None or time.monotonic() < deadline - 60):
                        critique(self.llm, self.backend, cand, task, self.rounds, self.repairs, hull, deadline)
                        offer(cand)
                else:
                    cand.log.append("no program in the reply")
            except Exception as exc:  # one failed call ends this candidate only
                cand.log.append(f"failed: {type(exc).__name__}: {exc}")
            return cand

        try:
            blocks = task_content(task)
            note = floor_note(floor, task.facts)
            with ThreadPoolExecutor(max(self.n_candidates, 1)) as pool:
                cands = list(pool.map(work, range(self.n_candidates)))
        except Exception as exc:  # a dead endpoint must not cost us what we already have
            error = f"{type(exc).__name__}: {exc}"

        if best["step"] is None:
            box = self.fallback(task, out_dir)
            best.update(step=str(box) if box else None, chosen="fallback box" if box else None)
        if best["code"]:
            (out_dir / "final.py").write_text(best["code"])
        summary = {
            "task": task.name, "step": best["step"], "chosen": best["chosen"], "self_check": best["check"],
            "error": error,
            "candidates": [{"idx": c.idx, "usable": c.usable, "approved": c.approved,
                            "score": score_of(c.check), "log": c.log} for c in cands],
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
        return summary
