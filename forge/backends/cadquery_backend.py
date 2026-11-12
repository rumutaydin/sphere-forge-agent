from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .base import CadBackend, ExecResult

GUIDE = """\
You write CadQuery 2.x (Python, OpenCASCADE kernel). Rules for every program:
- `import cadquery as cq`; assign the final solid to a variable named `result`.
- No file I/O, no show_object, no printing. Pure geometry.
- Put every dimension in a named variable at the top, then build from those.
- Millimetres. Use the frame of the brief and the views: the minimum corner of the part's
  bounding box sits at the origin, so every coordinate in the brief can be used as written.
- Position features with explicit coordinates (`.translate`, `.pushPoints`, `.center`)
  rather than face selectors when you can; selectors like ">Z" break silently after
  fillets or when several faces tie.
- Prefer explicit boolean ops: build a tool solid, then `.cut()` / `.union()` it.
- Workplane normals: "XY" -> +Z, "XZ" -> -Y, "YZ" -> +X. `.box()` is centred by default;
  `.circle().extrude(h)` grows along the workplane normal starting at the plane.
- Apply fillets/chamfers last, and keep their radius below half the smallest adjacent
  edge. If a fillet fails, shrink it or drop it: a valid part without a fillet beats
  a crash.
- revolve: sketch the half-profile on "XZ" and `.revolve(360, (0,0,0), (0,1,0))`
  (axis points are in the sketch's local coords; local Y of "XZ" is world Z).
- sweep: `cq.Workplane("XY").circle(r).sweep(path)` where path is a Workplane wire
  starting at the profile centre and leaving it along the profile normal.
- loft: `.rect(a,b).workplane(offset=h).circle(r).loft(combine=True)`.
- polar patterns: `.polarArray(radius, startAngle, 360, count)` then `.circle(r).extrude(h)`.
- The result must be ONE valid solid. Parts that only touch along an edge will not
  fuse; overlap them slightly.
"""


class CadQueryBackend(CadBackend):
    name = "cadquery"
    language = "python"
    guide = GUIDE

    def box_code(self, x: float, y: float, z: float) -> str:
        return f"import cadquery as cq\nresult = cq.Workplane('XY').box({x}, {y}, {z}, centered=False)\n"

    def execute(self, code: str, out_dir: Path, timeout: float = 90, env: dict | None = None) -> ExecResult:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        code_path = out_dir / "part.py"
        code_path.write_text(code)
        runner = Path(__file__).with_name("_cq_runner.py")
        try:
            proc = subprocess.run(
                [sys.executable, str(runner), str(code_path), str(out_dir)],
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, **(env or {})},
            )
        except subprocess.TimeoutExpired:
            return ExecResult(False, f"timed out after {timeout:.0f}s (geometry too heavy?)")
        if proc.returncode != 0:
            return ExecResult(False, proc.stderr.strip()[-2500:] or "unknown failure")
        measure = json.loads((out_dir / "measure.json").read_text())
        res = ExecResult(True, "", out_dir / "part.step", measure)
        if not measure["valid"]:
            res.error = "kernel reports the shape is not a valid solid"
        elif measure["solids"] > 1:
            res.error = f"result is {measure['solids']} disconnected solids, expected one"
        return res
