"""TRACK C. The model names empty space; code removes it, one cut at a time, and checks each.

The no-model part from forge.compile contains the true part but is too full wherever the
real part is hollow or pocketed, because no outline shows that. Here the model is not
asked for a program. It is asked for a short JSON list of simple regions (boxes,
cylinders, optionally repeated around an axis) that are empty in the real part. Each is
cut from the current part and kept only if the part stays one valid solid, the
through-hole count does not move away from the facts, no view's silhouette changes, and
the volume does not fall below the facts' volume. So a wrong guess costs nothing that we
can measure, and a right one moves the volume toward the target.

    propose_cuts(llm, task, floor, work)   -> list of cut dicts (may be empty)
    apply_cuts(step, cuts, task, out_dir)  -> ExecResult (runs in a subprocess)
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

from ..backends.base import ExecResult
from ..llm import LLM, image_block, text_block
from ..types import Task
from .understand import task_content

CARVE_SYSTEM = """\
You are a mechanical engineer comparing a rough CAD model with the real part.

You get the design brief, facts measured from the real part, the real part's eight
orthographic views, and one sheet with eight views of the CURRENT MODEL. The current model
was built from the outlines of the views, so its outer silhouette is already right in
every view and every bore listed in the facts is already cut. It is still TOO FULL: it
has material where the real part has pockets, recesses, hollow interiors, gaps between
fins or ribs, or lower levels that no outline shows.

List the regions of EMPTY SPACE that should be removed from the current model. Use the
frame of the brief: millimetres, origin at the minimum corner of the bounding box.
Reply with one JSON object and nothing else:

{"cuts": [
  {"why": "pocket in the top face", "shape": "box", "min": [x, y, z], "max": [x, y, z]},
  {"why": "hollow interior", "shape": "cylinder", "centre": [x, y, z], "axis": "Z", "diameter": d, "length": l},
  {"why": "gap between fins", "shape": "box", "min": [...], "max": [...],
   "repeat": {"axis": "Z", "through": [x, y, z], "count": 12}}
]}

Rules:
- "centre" of a cylinder is the midpoint of its axis; "axis" is "X", "Y", "Z" or a vector [ax, ay, az].
- "repeat" copies the region `count` times, evenly, around the line through `through` along `axis`.
- A region may stick out of the part; only the overlap is removed. Make a pocket that is open
  to a face start outside that face.
- Never list a bore that is in the facts: those are already cut.
- At most 12 entries, the largest volumes first. The volumes should add up to roughly the
  excess volume stated below. Give numbers only, no expressions."""


def propose_cuts(llm: LLM, task: Task, floor: dict, work: Path, timeout: float | None = None) -> list[dict]:
    from ..geometry import load_mesh
    from ..render import render_sheet

    sheet = render_sheet(load_mesh(floor["step"]), Path(work) / "current_views.png")
    check = floor["check"]
    excess = (check.get("volume_ratio", 1.0) - 1.0) * float(task.facts.get("volume_mm3", 0.0))
    ask = task_content(task) + [
        text_block("CURRENT MODEL, eight views in the same order (front, back, left, right, top, bottom, two isometric):"),
        image_block(sheet, max_side=1536),
        text_block(f"The current model has volume x{check.get('volume_ratio', 1.0):.2f} of the real part: "
                   f"about {excess:.0f} mm^3 too much. Surface area x{check.get('area_ratio', 1.0):.2f}."),
    ]
    reply = llm.complete(CARVE_SYSTEM, ask, timeout=timeout)
    (Path(work) / "carve_reply.txt").write_text(reply)
    return parse_cuts(reply)


def parse_cuts(reply: str) -> list[dict]:
    """The entries of the "cuts" list, one object at a time, so a reply cut off by the token
    limit still yields every complete entry."""
    start = reply.find("[", reply.find('"cuts"'))
    if '"cuts"' not in reply or start < 0:
        return []
    cuts, depth, begin = [], 0, None
    for i in range(start, len(reply)):
        ch = reply[i]
        if ch == "{":
            if depth == 0:
                begin = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and begin is not None:
                try:
                    obj = json.loads(reply[begin:i + 1])
                    if isinstance(obj, dict):
                        cuts.append(obj)
                except Exception:
                    pass
        elif ch == "]" and depth == 0:
            break
    return cuts[:16]


def apply_cuts(step: str | Path, cuts: list[dict], task: Task, out_dir: Path, timeout: float = 400) -> ExecResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cuts.json").write_text(json.dumps(cuts, indent=1))
    try:
        proc = subprocess.run([sys.executable, "-m", "forge.stages.carve", str(step), str(out_dir / "cuts.json"),
                               str(task.dir), str(out_dir)], capture_output=True, text=True, timeout=timeout,
                              cwd=Path(__file__).resolve().parents[2])
    except subprocess.TimeoutExpired:
        proc = None
    if not (out_dir / "measure.json").is_file():        # even a timeout leaves the cuts accepted so far
        return ExecResult(False, (proc.stderr.strip()[-1500:] if proc else "timed out") or "no cut applied")
    return ExecResult(True, "", out_dir / "part.step", json.loads((out_dir / "measure.json").read_text()))


# --- subprocess side -------------------------------------------------------------------

def _tool(cut: dict):
    import cadquery as cq

    from ..compile import parse_axis

    if cut.get("shape") == "box":
        lo, hi = [float(v) for v in cut["min"]], [float(v) for v in cut["max"]]
        lo, hi = [min(a, b) for a, b in zip(lo, hi)], [max(a, b) for a, b in zip(lo, hi)]
        if min(h - l for l, h in zip(lo, hi)) <= 0:
            return None
        solid = cq.Solid.makeBox(*[h - l for l, h in zip(lo, hi)], cq.Vector(*lo))
    elif cut.get("shape") == "cylinder":
        axis = parse_axis(cut.get("axis", "Z"))
        d, length = float(cut["diameter"]), float(cut["length"])
        if not axis or d <= 0 or length <= 0:
            return None
        c = [float(v) for v in cut["centre"]]
        start = [ci - ai * length / 2 for ci, ai in zip(c, axis)]
        solid = cq.Solid.makeCylinder(d / 2, length, cq.Vector(*start), cq.Vector(*axis))
    else:
        return None
    rep = cut.get("repeat")
    if isinstance(rep, dict) and int(rep.get("count", 1)) > 1:
        axis = parse_axis(rep.get("axis", "Z"))
        p = [float(v) for v in rep.get("through", [0, 0, 0])]
        n = min(int(rep["count"]), 72)
        if axis:
            end = [pi + ai for pi, ai in zip(p, axis)]
            copies = [solid.rotate(cq.Vector(*p), cq.Vector(*end), 360.0 * k / n) for k in range(n)]
            return copies
    return [solid]


def main() -> int:
    import cadquery as cq

    from ..backends._cq_runner import measure
    from ..cases import load_tasks
    from ..compile import _largest_solid, estimate
    from ..facts import self_check
    from ..geometry import genus, shape_to_mesh
    from ..vision import shape_score, target_masks

    step, cuts_file, task_dir, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    task = load_tasks(task_dir.parent, [task_dir.name + "$"])[0]
    cuts = json.loads(Path(cuts_file).read_text())
    shape = cq.importers.importStep(step).val()
    if len(shape.Solids()) == 1:
        shape = shape.Solids()[0]
    masks = target_masks(task)
    vol_target = float(task.facts.get("volume_mm3") or 0.0)
    g_target = int(task.facts.get("through_holes_genus", 0))

    def look(s):
        mesh = shape_to_mesh(s)
        return mesh, genus(mesh), shape_score(mesh, task, masks)["mean"]

    mesh, g, iou = look(shape)
    log, kept = [], 0

    def save():
        info = measure(shape)
        info["genus"] = g
        info["bbox_size"] = [float(e) for e in mesh.extents]
        info["check"] = self_check(info, task.facts)
        info["check"]["silhouette_iou"] = iou
        info["check"]["estimate"] = estimate(info["check"], {"mean": iou})
        info["carve_log"] = log
        cq.exporters.export(shape, str(out_dir / "part.step"))
        (out_dir / "measure.json").write_text(json.dumps(info))

    for cut in cuts:
        why = str(cut.get("why", cut.get("shape", "?")))[:60]
        try:
            tools = _tool(cut)
            if not tools:
                log.append(f"{why}: not understood")
                continue
            new = _largest_solid(shape.cut(*tools))
            removed = shape.Volume() - new.Volume()
            if not new.isValid() or removed <= 1e-6 * shape.Volume():
                log.append(f"{why}: removes nothing")
                continue
            if vol_target and new.Volume() < 0.98 * vol_target:
                log.append(f"{why}: rejected, volume would fall to x{new.Volume() / vol_target:.2f}")
                continue
            mesh2, g2, iou2 = look(new)
            if g2 < 0 or abs(g2 - g_target) > abs(g - g_target):
                log.append(f"{why}: rejected, through-holes {g} -> {g2} (target {g_target})")
                continue
            if iou2 < iou - 0.002:
                log.append(f"{why}: rejected, changes a silhouette ({iou:.3f} -> {iou2:.3f})")
                continue
            shape, mesh, g, iou, kept = new, mesh2, g2, max(iou, iou2), kept + 1
            log.append(f"{why}: cut {removed:.0f} mm^3, volume now x{shape.Volume() / vol_target if vol_target else 0:.3f}")
            save()
        except Exception as exc:
            log.append(f"{why}: failed ({type(exc).__name__}: {str(exc)[:80]})")
    (out_dir / "carve_log.json").write_text(json.dumps(log, indent=1))
    if kept:
        save()
    return 0 if kept else 1


if __name__ == "__main__":
    sys.exit(main())
