"""TRACK C. Stage 5: the judge. One place decides which solid is the part's file.

Tiers, highest first (docs/PLAN.md, Architecture v6). A higher tier always wins; the
estimate only ranks parts inside the body and hull tiers.

    exact   a whole-part program that passes the gate of forge/stages/exact.py
            (strict; or the relaxed rule when FORGE_EXACT_RELAX=1). Among several: the most faithful.
    body    a model body or cut list. It beats the hull only under the old rules: outer
            dimensions not worse, edges inside the outline not worse (veto), estimate higher
            by a margin. Among several: the higher estimate.
    hull    the no-model part of pass 1 (forge.compile), already published before the model runs.
    box     the bounding-box solid; only when nothing else exists.

Every exact program is judged under BOTH the strict and the relaxed rule, whichever is
active, and the verdicts go into the summary: one run shows what each rule would have chosen.

`select()` below is the old answer-free pick among candidates, kept for its test.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..geometry import load_mesh
from ..score import pairwise_iou
from ..types import Candidate, Task

TIERS = ("box", "hull", "body", "exact")      # lowest to highest


def score_of(check: dict) -> float:
    """What bodies and hulls are ranked by: the leaderboard estimate when the views allowed one."""
    return float(check.get("estimate", check.get("self_score", 0.0))) if check else 0.0


class Judge:
    """Holds the best part of one task so far and publishes it whenever it changes.
    Thread-safe: generators offer their candidates as they finish."""

    def __init__(self, task: Task, floor: dict | None, publish: Path | None = None,
                 margin: float = 0.02, edge_veto: float = 0.015):
        self.task, self.floor, self.publish, self.margin, self.edge_veto = task, floor, publish, margin, edge_veto
        self.lock = threading.Lock()
        # the best of the hull and body tiers, by today's rules
        self.base = {"tier": "hull" if floor else None, "score": score_of(floor["check"]) if floor else -1.0,
                     "step": floor["step"] if floor else None, "chosen": floor["name"] if floor else None,
                     "check": floor["check"] if floor else {}, "code": None}
        self.exact: dict | None = None        # the exact program chosen under the active rule
        self.verdicts: list[dict] = []        # one per exact program, both rules

    @property
    def best(self) -> dict:
        return self.exact or self.base

    def _publish(self, step) -> None:
        if self.publish:
            from ..compile import publish_file

            publish_file(step, self.publish)

    # --- tier: body ------------------------------------------------------------------------------
    def offer_body(self, cand: Candidate) -> bool:
        """A model body or cut list against the hull (or the body chosen before it)."""
        floor = self.floor
        if not cand.usable or (floor and not cand.check):
            return False
        if floor and cand.check.get("dimensions", 1.0) < floor["check"].get("dimensions", 1.0) - 0.01:
            cand.log.append("not offered: outer dimensions worse than the no-model part's")
            return False     # dimensions are 20% of the score and the no-model part has them exact
        if floor and floor["check"].get("edge_all") is not None and score_of(cand.check) > self.base["score"]:
            # Edges inside the outline: on the leaderboard, model results that lowered this
            # were the ones that lost points (scripts/calibrate_edges.py).
            from ..vision import edge_score

            try:
                cand.check["edge_all"] = edge_score(cand.result.step_path, self.task)["all"]
            except Exception:
                cand.check["edge_all"] = None
            if cand.check["edge_all"] is not None and cand.check["edge_all"] < floor["check"]["edge_all"] - self.edge_veto:
                cand.log.append(f"not offered: its edges match the views worse than the no-model part's "
                                f"({cand.check['edge_all']:.3f} against {floor['check']['edge_all']:.3f})")
                return False
        with self.lock:
            # A model result must beat the no-model part by a clear margin: the estimate cannot
            # see inside the outline, and on the leaderboard small estimated gains were noise
            # (part 2: +0.017 estimated, -0.005 scored).
            bar = self.base["score"] + (self.margin if self.base["tier"] == "hull" else 1e-9)
            if not (score_of(cand.check) > bar or self.base["step"] is None):
                return False
            self.base = {"tier": "body", "score": score_of(cand.check), "step": str(cand.result.step_path),
                         "chosen": f"model {'cuts' if cand.idx >= 100 else 'body'} {cand.idx % 100}",
                         "check": cand.check, "code": cand.code}
            if self.exact is None:          # an exact program that passed the gate is never replaced by a body
                self._publish(cand.result.step_path)
            return True

    # --- tier: exact -----------------------------------------------------------------------------
    def offer_exact(self, cand: Candidate) -> bool:
        """A whole-part program: judged under both rules, chosen under the active one."""
        from . import exact

        name = f"exact program {cand.idx % 100}"
        entry = {"candidate": name, "usable": cand.usable, "strict": {"admit": False, "why": ["no measured result"]},
                 "relaxed": {"admit": False, "why": ["no measured result"]}}
        if cand.usable and cand.check and "gate" in cand.check:
            for rule, relax in (("strict", False), ("relaxed", True)):
                why = exact.verdict(cand.check, self.floor, relax)
                entry[rule] = {"admit": not why, "why": why}
            entry.update(exact.numbers(cand.check["exact"]), rounds=cand.check.get("rounds", []))
            cand.log.append(f"exact verdict: strict {'ADMIT' if entry['strict']['admit'] else 'refuse'}, "
                            f"relaxed {'ADMIT' if entry['relaxed']['admit'] else 'refuse'} "
                            f"(volume x{entry.get('volume_ratio') or 0:.3f}, worst view {entry.get('iou_min') or 0:.3f}, "
                            f"mean {entry.get('iou_mean') or 0:.3f}, fidelity {entry.get('fidelity') or 0:.3f})")
        with self.lock:
            self.verdicts.append(entry)
            if not exact.accept(cand, self.exact or {}, self.floor):
                return False
            self.exact = {"tier": "exact", "score": score_of(cand.check), "step": str(cand.result.step_path),
                          "chosen": name, "check": cand.check, "code": cand.code, "exact": True}
            self._publish(cand.result.step_path)
            return True

    # --- tier: box -------------------------------------------------------------------------------
    def offer_box(self, step) -> None:
        """The bounding-box solid: only when no tier above produced anything."""
        with self.lock:
            if self.best["step"] is None and step:
                self.base.update(tier="box", step=str(step), chosen="fallback box")

    # --- for the summary -------------------------------------------------------------------------
    def would_choose(self, relax: bool) -> str | None:
        """What this task's file would be under the strict (False) or relaxed (True) rule."""
        rule = "relaxed" if relax else "strict"
        ok = [v for v in self.verdicts if v[rule]["admit"]]
        return max(ok, key=lambda v: v.get("fidelity") or 0.0)["candidate"] if ok else self.base["chosen"]

    def report(self) -> dict:
        from . import exact

        return {"source": self.best["tier"], "rule": "relaxed" if exact.relax_on() else "strict",
                "would_choose": {"strict": self.would_choose(False), "relaxed": self.would_choose(True)},
                "below_exact": {"source": self.base["tier"], "chosen": self.base["chosen"], "estimate": round(self.base["score"], 4)},
                "exact_verdicts": self.verdicts}


def source_of(chosen: str | None) -> str:
    """The tier of a `chosen` name, for tables: exact | body | hull | box."""
    c = chosen or ""
    return "exact" if c.startswith("exact") else "body" if c.startswith("model") else "box" if "box" in c or not c else "hull"


def select(cands: list[Candidate]) -> Candidate | None:
    usable = [c for c in cands if c.usable]
    if not usable:
        return None
    if any(c.check for c in usable):
        return max(usable, key=lambda c: (c.check.get("estimate", c.self_score), c.approved))
    if len(usable) <= 2:
        return max(usable, key=lambda c: c.approved)
    agreement = pairwise_iou([load_mesh(c.result.step_path) for c in usable]).mean(axis=1)
    return usable[int(agreement.argmax())]
