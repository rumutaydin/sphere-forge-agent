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
from .stages.carve import apply_cuts, propose_cuts
from .stages.understand import task_content
from .stages.verify import critique
from .types import Candidate, Task


def score_of(check: dict) -> float:
    """What candidates are ranked by: the leaderboard estimate when the views allowed one."""
    if not check:
        return 0.0
    import os

    gap = min(abs(check.get("area_ratio", 1.0) - 1.0), 1.0) if "estimate" in check else 0.0
    return float(check.get("estimate", check.get("self_score", 0.0))) - float(os.environ.get("FORGE_AREA_W", "0.25")) * gap


class Agent:
    def __init__(self, llm: LLM, backend: CadBackend, n_candidates: int = 2, repairs: int = 2, rounds: int = 0,
                 n_carve: int = 0, margin: float = 0.02, edge_veto: float = 0.015):
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
            if floor and cand.check.get("dimensions", 1.0) < floor["check"].get("dimensions", 1.0) - 0.01:
                cand.log.append("not offered: outer dimensions worse than the no-model part's")
                return      # dimensions are 20% of the score and the no-model part has them exact
            if floor and floor["check"].get("edge_all") is not None and score_of(cand.check) > best["score"]:
                # Edges inside the outline: on the leaderboard, model results that lowered this
                # were the ones that lost points (scripts/calibrate_edges.py).
                from .vision import edge_score

                try:
                    cand.check["edge_all"] = edge_score(cand.result.step_path, task)["all"]
                except Exception:
                    cand.check["edge_all"] = None
                if cand.check["edge_all"] is not None and cand.check["edge_all"] < floor["check"]["edge_all"] - self.edge_veto:
                    cand.log.append(f"not offered: its edges match the views worse than the no-model part's "
                                    f"({cand.check['edge_all']:.3f} against {floor['check']['edge_all']:.3f})")
                    return
            with lock:
                # A model result must beat the no-model part by a clear margin: the estimate cannot
                # see inside the outline, and on the leaderboard small estimated gains were noise
                # (part 2: +0.017 estimated, -0.005 scored).
                bar = best["score"] + (self.margin if best["code"] is None and floor else 1e-9)
                if score_of(cand.check) > bar or best["step"] is None:
                    best.update(score=score_of(cand.check), step=str(cand.result.step_path),
                                chosen=f"model {'cuts' if cand.idx >= 100 else 'body'} {cand.idx % 100}", check=cand.check, code=cand.code)
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
            n_carve = self.n_carve if floor and floor["check"].get("volume_ratio", 1.0) > 1.04 and task.dir else 0
            with ThreadPoolExecutor(max(self.n_candidates + n_carve, 1)) as pool:
                jobs = [pool.submit(work, i) for i in range(self.n_candidates)]
                jobs += [pool.submit(carve, 100 + i) for i in range(n_carve)]
                cands = [j.result() for j in jobs]
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
