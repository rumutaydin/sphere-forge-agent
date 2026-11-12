"""TRACK C. Stage 5: choose one candidate without the answer file.

With facts.json we can rank candidates by how well they match the target's
measured bounding box, hole count, volume and surface area (the self-score).
Without facts we fall back to consensus: the candidate that overlaps most with
the others.
"""
from __future__ import annotations

from ..geometry import load_mesh
from ..score import pairwise_iou
from ..types import Candidate


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
