"""Shared data contract between the tracks.

Everything that crosses a stage boundary is defined here. Changing this file
changes every track's code, so it needs a PR that everyone approves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .backends.base import ExecResult


@dataclass
class Task:
    """One part, exactly as the organisers hand it over (artifacts/inputs/test_case_<n>/)."""
    name: str                                   # test_case_<n>; the output is <name>.stp
    description: str                            # description.md: the design brief, dimensions in mm
    views: list[Path] = field(default_factory=list)   # 8 orthographic views, 1024 px, sorted
    context: Path | None = None                 # part highlighted in its assembly; often absent
    facts: dict = field(default_factory=dict)   # facts.json: bbox, volume, area, hole inventory
    answer: Path | None = None                  # target STEP; only our own reference cases have one
    dir: Path | None = None                     # the task's input folder (description.md, facts.json, images/)


@dataclass
class Candidate:
    """One attempt at the part, carried through build -> verify -> select."""
    idx: int
    code: str
    dir: Path
    result: ExecResult | None = None
    check: dict = field(default_factory=dict)   # forge.facts.self_check of the latest result
    approved: bool = False
    log: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.result and self.result.ok)

    @property
    def self_score(self) -> float:
        return float(self.check.get("self_score", 0.0))
