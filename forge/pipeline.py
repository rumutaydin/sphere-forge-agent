"""The orchestrator: wires the stages together and nothing else.

    pass 1 (forge.compile, no model)   silhouette body + bores from the facts -> written at once (tier: hull)
    pass 2 (this file, the model)      generators, each a complete solid, none trims another:
                                       [ exact program -> measured -> revised ] x FORGE_EXACT   (tier: exact)
                                       [ body program -> finished by code -> repair ] x N       (tier: body)
    the judge (forge/stages/select.py) exact passing the gate > body by margin and veto > hull > box

The file in the output folder is always the best part known so far: a box first, then the
no-model part, then whatever the judge admits. Nothing waits for the end of a part, so a
timeout or a dead endpoint cannot lose one. Stage logic lives in forge/stages/ and
forge/compile.py. Keep this file thin.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import CadBackend
from .llm import LLM
from .stages import exact
from .stages.build import floor_note, generate, run_with_repair
from .stages.carve import apply_cuts, propose_cuts
from .stages.select import Judge, score_of  # noqa: F401  (score_of is imported from here by forge/run.py)
from .stages.understand import task_content
from .stages.verify import critique
from .types import Candidate, Task


class Agent:
    def __init__(self, llm: LLM, backend: CadBackend, n_candidates: int = 2, repairs: int = 2, rounds: int = 0,
                 n_carve: int = 0, margin: float = 0.02, edge_veto: float = 0.015, n_exact: int | None = None):
        self.n_exact = int(os.environ.get("FORGE_EXACT", "0")) if n_exact is None else n_exact
        self.llm, self.backend, self.n_carve, self.margin, self.edge_veto = llm, backend, n_carve, margin, edge_veto
        self.n_candidates, self.repairs, self.rounds = n_candidates, repairs, rounds

    def fallback(self, task: Task, out_dir: Path) -> Path | None:
        """Bounding-box solid from the facts. Needs no model."""
        box = task.facts.get("bounding_box_mm")
        if not box:
            return None
        res = self.backend.execute(self.backend.box_code(box["x"], box["y"], box["z"]), out_dir / "fallback")
        return res.step_path if res.ok else None

    def solve(self, task: Task, out_dir: Path, deadline: float | None = None,
              publish: Path | None = None, floor: dict | None = None, bodies: bool = True) -> dict:
        """Model pass for one task. `floor` is the best no-model row from forge.compile (or None);
        `publish` is the output file, overwritten whenever the judge admits a better part.
        `bodies=False` runs the exact programs only (a part whose no-model estimate is already high).
        Returns a summary; summary["step"] is the best STEP file known (or None)."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        judge = Judge(task, floor, publish, self.margin, self.edge_veto)
        offer = judge.offer_body
        hull = out_dir / "pass1" / "hull.step"
        hull = hull if hull.is_file() else None
        cands: list[Candidate] = []
        error = None

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

        def exact_work(i: int) -> Candidate:
            """The model writes the whole part and revises it against measurements (forge/stages/exact.py)."""
            cand = Candidate(i, "", out_dir / f"exact{i % 100}")
            try:
                exact.run_exact(self.llm, self.backend, cand, task, blocks, deadline=deadline, note=note)
            except Exception as exc:
                cand.log.append(f"failed: {type(exc).__name__}: {exc}")
            try:
                judge.offer_exact(cand)     # also when the run failed: the verdict of every program is logged
            except Exception as exc:
                cand.log.append(f"judge failed: {type(exc).__name__}: {exc}")
            return cand

        def carve(i: int) -> Candidate:
            """The model names empty regions; code cuts and checks each (forge/stages/carve.py)."""
            cand = Candidate(i, "", out_dir / f"carve{i}")
            try:
                cuts = propose_cuts(self.llm, task, floor, cand.dir,
                                    timeout=None if deadline is None else deadline - time.monotonic())
                cand.code = json.dumps(cuts, indent=1)
                if cuts:
                    cand.result = apply_cuts(floor["step"], cuts, task, cand.dir)
                    cand.check = cand.result.measure.get("check", {}) if cand.result.ok else {}
                    cand.log += cand.result.measure.get("carve_log", []) if cand.result.ok else [cand.result.error[-200:]]
                    offer(cand)
                else:
                    cand.log.append("no cuts in the reply")
            except Exception as exc:
                cand.log.append(f"failed: {type(exc).__name__}: {exc}")
            return cand

        try:
            blocks = task_content(task)
            note = floor_note(floor, task.facts)
            n_bodies = self.n_candidates if bodies else 0
            n_carve = self.n_carve if bodies and floor and floor["check"].get("volume_ratio", 1.0) > 1.04 and task.dir else 0
            with ThreadPoolExecutor(max(n_bodies + n_carve + self.n_exact, 1)) as pool:
                jobs = [pool.submit(work, i) for i in range(n_bodies)]
                jobs += [pool.submit(exact_work, 200 + i) for i in range(self.n_exact)]
                jobs += [pool.submit(carve, 100 + i) for i in range(n_carve)]
                cands = [j.result() for j in jobs]
        except Exception as exc:  # a dead endpoint must not cost us what we already have
            error = f"{type(exc).__name__}: {exc}"

        if judge.best["step"] is None:
            judge.offer_box(self.fallback(task, out_dir))
        best = judge.best
        if best["code"]:
            (out_dir / "final.py").write_text(best["code"])
        summary = {
            "task": task.name, "step": best["step"], "chosen": best["chosen"], "self_check": best["check"],
            "error": error, **judge.report(),
            "candidates": [{"idx": c.idx, "usable": c.usable, "approved": c.approved,
                            "score": score_of(c.check), "log": c.log} for c in cands],
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
        return summary
