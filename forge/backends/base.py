"""The seam between the agent and whatever CAD engine the hackathon provides.

To support a new engine, subclass CadBackend: describe the language to the
model in `guide`, and turn a program into a STEP/STL file in `execute`.
Nothing else in the codebase knows which engine is in use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecResult:
    ok: bool
    error: str = ""                 # traceback tail or validity problem, fed back to the model
    step_path: Path | None = None
    stl_path: Path | None = None
    measure: dict = field(default_factory=dict)  # kernel measurements, see describe()


class CadBackend:
    name: str = "base"
    language: str = "python"        # fence label the model should use
    guide: str = ""                 # API cheat sheet + conventions, goes in the system prompt

    def execute(self, code: str, out_dir: Path, timeout: float = 90) -> ExecResult:
        raise NotImplementedError


def describe(measure: dict) -> str:
    """Kernel measurements as text. Numbers are the feedback models use best."""
    if not measure:
        return "(no measurements)"
    lines = [
        f"valid solid: {measure.get('valid')}   solids: {measure.get('solids')}",
        "bbox min  ({:.3f}, {:.3f}, {:.3f})".format(*measure["bbox_min"]),
        "bbox max  ({:.3f}, {:.3f}, {:.3f})".format(*measure["bbox_max"]),
        "bbox size ({:.3f}, {:.3f}, {:.3f})".format(*measure["bbox_size"]),
        f"volume {measure['volume']:.3f}   surface area {measure['area']:.3f}",
        "centre of mass ({:.3f}, {:.3f}, {:.3f})".format(*measure["com"]),
        "faces by type: " + ", ".join(f"{k} x{v}" for k, v in sorted(measure["faces"].items())),
    ]
    cyls = measure.get("cylinders", [])
    if cyls:
        lines.append("cylindrical faces (radius, axis direction, point on axis):")
        for c in cyls[:24]:
            lines.append(
                "  r={:.3f}  dir=({:.2f}, {:.2f}, {:.2f})  at=({:.2f}, {:.2f}, {:.2f})".format(
                    c["r"], *c["dir"], *c["at"]
                )
            )
        if len(cyls) > 24:
            lines.append(f"  ... and {len(cyls) - 24} more")
    return "\n".join(lines)
