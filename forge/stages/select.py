"""TRACK C. Stage 5: choose one candidate without knowing the answer.

Independent attempts that agree with each other are more likely right than an
outlier, so we take the IoU medoid: the candidate with the highest mean overlap
with all the others. Critic approval breaks ties.
"""
from __future__ import annotations

import numpy as np

from ..geometry import load_mesh
from ..metrics import pairwise_iou
from ..types import Candidate


def select(cands: list[Candidate]) -> Candidate | None:
    usable = [c for c in cands if c.usable]
    if len(usable) <= 2:
        return max(usable, key=lambda c: c.approved, default=None)
    agreement = pairwise_iou([load_mesh(c.result.stl_path) for c in usable]).mean(axis=1)
    scores = agreement + 0.02 * np.array([c.approved for c in usable])
    return usable[int(np.argmax(scores))]
