"""Shared data contract between the three tracks.

Everything that crosses a stage boundary is defined here. Changing this file
changes every track's code, so it needs a PR that all three people approve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .backends.base import ExecResult


@dataclass
class Task:
    """One problem as the organisers hand it to us."""
    prompt: str | None = None       # text description, may be vague
    image: Path | None = None       # picture of the target, may be the only input
    base_code: str | None = None    # existing program to edit (iterative tasks), unused so far


@dataclass
class Spec:
    """Track B's output and Track C's input: the modelling brief.

    `text` is what the code generator reads. The optional fields let later
    stages check their work with numbers; fill them when you can extract them.
    """
    text: str
    envelope: tuple[float, float, float] | None = None  # expected bbox size (X, Y, Z)
    notes: dict = field(default_factory=dict)            # anything else worth passing on


@dataclass
class Candidate:
    """One attempt at the part, carried through build -> verify -> select."""
    idx: int
    code: str
    dir: Path
    result: ExecResult | None = None
    approved: bool = False
    log: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.result and self.result.ok)
