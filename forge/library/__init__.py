"""TRACK C. The knowledge base: verified parametric generators for standard parts.

Some shapes are defined by a standard or a formula rather than by a description
(involute gears, threads, fastener heads). A language model derives them badly
and differently every time. Here we write each one once, test it, and let the
model call it by name.

To add a part: write the function in a module in this package, give it a
docstring whose first line states the call and what it returns, and add it to
HELPERS. The docstrings are pasted into the model's prompt by catalogue().
"""
from __future__ import annotations

from .gears import spur_gear

HELPERS = [spur_gear]


def catalogue() -> str:
    lines = []
    for fn in HELPERS:
        doc = (fn.__doc__ or "").strip()
        lines.append(f"from forge.library import {fn.__name__}\n{doc}")
    return "\n\n".join(lines) if lines else "(none yet)"
