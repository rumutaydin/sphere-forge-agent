"""TRACK C. The exact-program path: the model writes the WHOLE part, code measures it, the model revises.

The body path (forge/stages/build.py) lets the model place a few plain solids and then trims
them with the pixel hull. That caps a part at what an outline can show. Here the model writes
one complete parametric CadQuery program for the part of the brief (bores, patterns, rounds);
nothing is trimmed and nothing is scaled: the result is only moved so that its bounding-box
minimum corner sits on the origin. After each run the model gets an objective report computed
by code, and may send a revised program.

    ask()              one complete program from brief, facts and views
    finish()           called at the end of the program, in the subprocess: move to the origin,
                       optionally drill the listed bores, compare the outline with the eight views
    make_report()      bbox per axis, volume, through-holes, silhouette IoU per view and where it differs
    gate()             the strict acceptance test; [] means the part may replace the current one
    fidelity()         one number to rank programs by
    run_exact()        the loop: program -> run -> report -> revised program, best version kept
    verdict()          may this candidate stand in for the no-model part: strict rule, relaxed rule
    accept()           may this candidate replace the best part so far? (called by forge/stages/select.py)

The report and the gate use only what a brief can give: bounding box, volume, through-hole
count, the bore list, and the silhouettes. Surface area and face counts are shown to the model
when the facts happen to have them and are never required.

Settings: FORGE_EXACT (0, programs per part; read in forge/pipeline.py), FORGE_EXACT_ROUNDS (3),
FORGE_EXACT_THINKING (medium: off | on | low | medium | high), FORGE_EXACT_MAX_TOKENS (16000),
FORGE_EXACT_IOU (0.965, worst-view bar of the gate; scripts/calibrate_exact.py), FORGE_EXACT_VOL (0.04),
FORGE_EXACT_RELAX (0; see dominates()), FORGE_EXACT_RUN_S (240, one program run), FORGE_EXACT_CALL_S (600, one model call; FORGE_LLM_TIMEOUT_S must not be lower).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from ..backends import CadBackend
from ..llm import LLM, text_block
from ..types import Candidate, Task
from .build import extract_code

EXACT_MARK = "# --- finished by forge (exact path): moved to the origin, measured against the views ---"
VIEW_OK = 0.97          # a view below this is described to the model
SHORT = {"view_0_front": "front", "view_1_back": "back", "view_2_left": "left", "view_3_right": "right",
         "view_4_top": "top", "view_5_bottom": "bottom", "view_6_iso_front_right_top": "isometric (front right top)",
         "view_7_iso_back_left_bottom": "isometric (back left bottom)"}

CHEAT_SHEET = '''\
import math
import cadquery as cq
from forge.library import box, cylinder, cone, prism, revolve, polar, union, cut, common   # optional helpers

# 1. BLOCKS. cq's box() is CENTRED on the origin unless you say centered=False.
plate = cq.Workplane("XY").box(80, 50, 8, centered=False)          # spans x 0..80, y 0..50, z 0..8
block = box((10, 10, 8), (30, 40, 20))                             # helper: two opposite WORLD corners

# 2. ROUND BARS in any direction: the helper takes the two end points of the axis and a DIAMETER.
boss = cylinder((40, 25, 8), (40, 25, 30), 20)                     # dia 20, z 8..30, axis at x=40 y=25
taper = cone((60, 25, 8), (60, 25, 20), 12, 6)                     # dia 12 at the bottom, dia 6 at the top
# raw CadQuery: a sketch is extruded along the plane's normal, starting AT the plane.
stud = cq.Workplane("XY").workplane(offset=8).center(70, 40).circle(3).extrude(12)   # z 8..20 at x=70 y=40

# 3. PLANES. Normals: "XY" -> +Z, "YZ" -> +X, "XZ" -> MINUS Y. Sketch coordinates are local:
#    on "XZ" they are (world x, world z), on "YZ" they are (world y, world z).
rib = cq.Workplane("XZ", origin=(0, 50, 0)).polyline([(0, 8), (10, 8), (0, 30)]).close().extrude(6)   # y 44..50
lug = cq.Workplane("YZ", origin=(80, 0, 0)).center(25, 4).rect(20, 4).extrude(10)   # x 80..90, y 15..35, z 2..6
# safer: prism(axis, outline in the other two WORLD coordinates, lo, hi along the axis)
web = prism("Y", [(70, 8), (80, 8), (80, 30)], 0, 6)               # (x, z) outline, y 0..6

# 4. JOIN. Pieces must overlap or share a face to become one solid.
body = plate.union(block).union(boss).union(taper).union(stud).union(rib).union(lug).union(web)

# 5. HOLES at world positions: cut a cylinder that sticks out of the material on the open side(s).
body = body.cut(cylinder((40, 25, -1), (40, 25, 31), 10))          # dia 10 through bore along Z
body = body.cut(cylinder((9, 25, 14), (31, 25, 14), 5))            # dia 5 cross hole along X through the block
corners = [(8, 8), (72, 8), (8, 42), (72, 42)]                     # several holes along Z at once
body = body.cut(cq.Workplane("XY").pushPoints(corners).circle(3).extrude(8))                       # 4 x dia 6, z 0..8
body = body.cut(cq.Workplane("XY").workplane(offset=5).pushPoints(corners).circle(5.5).extrude(3))  # counterbore dia 11, z 5..8
# a blind hole is the same cut with the cylinder ending inside the material.

# 6. RADIAL PATTERNS about an axis: a loop with sin/cos, or polar() for any solid.
cx, cy, n, pitch_dia = 40, 25, 6, 15
for k in range(n):
    ang = math.radians(360 / n * k)                                # first one on +X, counter-clockwise seen from +Z
    x, y = cx + pitch_dia / 2 * math.cos(ang), cy + pitch_dia / 2 * math.sin(ang)
    body = body.cut(cylinder((x, y, 26), (x, y, 31), 1.5))
slot = box((cx + 6, cy - 1, 27), (cx + 11, cy + 1, 31))            # one radial slot on +X ...
body = cut(body, polar(slot, "Z", (cx, cy, 0), 4))                 # ... cut four times around the axis
ring = cq.Workplane("XY").workplane(offset=7).center(cx, cy).polarArray(16, 0, 360, 8).circle(1).extrude(1)
body = body.cut(ring)                                              # raw: polarArray(radius, start angle, 360, count)

# 7. TURNED SHAPES. revolve(axis, point on the axis, [(radius, position along the axis), ...]) closes onto the axis.
hub = revolve("Z", (120, 25, 0), [(20, 0), (20, 10), (12, 10), (8, 40)])
# raw, with a rounded rim in the profile: sketch on "XZ" (local x = radius, local y = height), turn about local Y.
cap = (cq.Workplane("XZ").moveTo(0, 0).lineTo(15, 0).radiusArc((20, 5), -5).lineTo(20, 10).lineTo(0, 10).close()
       .revolve(360, (0, 0, 0), (0, 1, 0)).translate((120, 25, 40)))   # built on the origin, then moved
# a tapered wedge or groove cutter: loft between two outlines on parallel planes.
wedge = (cq.Workplane("XY").polyline([(0, -4), (10, 0), (0, 4)]).close()
         .workplane(offset=30).polyline([(0, -2), (5, 0), (0, 2)]).close().loft())
wedge = wedge.rotate((0, 0, 0), (0, 0, 1), 45).translate((100, 60, 0))   # turn about an axis, then place

# 8. ROUNDS AND CHAMFERS: last, edges picked by a box in WORLD coordinates, each in its own try/except.
try:
    body = body.edges("|Z").edges(cq.selectors.BoxSelector((-1, -1, -1), (81, 51, 9))).fillet(4)   # the plate's four upright edges
except Exception:
    pass                                                           # a part without the round beats a crash
try:
    hub = hub.edges(cq.selectors.BoxSelector((99, 4, 9), (141, 46, 11))).chamfer(1)   # the circular edges at z = 10
except Exception:
    pass

result = body.union(hub.translate((-60, 0, 0))).union(cap.translate((-60, 0, 0)))
'''

EXACT_SYSTEM = """\
You are a mechanical engineer who models a part EXACTLY as one CadQuery 2 program. You get the
design brief (it carries the dimensions), numbers measured from the real part, and eight views.
Your program is run and measured by code; you will be shown the measurements and may revise.
The part is scored on volume overlap, surface match, bounding-box dimensions and the number of
through-holes, so every feature of the brief counts: masses, pockets, bores, counterbores,
slots, patterns, rounds and chamfers.

Reply with a short plan (at most twelve lines: the base solid, the features in order, any
dimension the brief does not give and the value you chose for it), then exactly ONE ```python
code block with the complete program.

Rules for the program:
- `import cadquery as cq`; you may also use the helpers of forge.library shown below.
- Millimetres. World frame of the brief and the views: the MINIMUM corner of the part's bounding
  box is at the origin, so the part spans 0..X, 0..Y, 0..Z of the envelope and the positions in
  the brief can be used as written. Never mirror the part and never scale it to fit.
- Every dimension is a named variable at the top of the program, with a comment saying where it
  comes from (brief, measured numbers, or read from a named view). Build from the variables.
- Model everything the brief lists. Counts and positions of repeated features come from the brief;
  what it does not give (a count, a depth) you read from the views and check against the volume.
- Rounds and chamfers go last, each in its own try/except, so a failed one does not lose the part.
- The last line assigns `result`: ONE valid solid. No file output, no show_object.
- Before you answer, add up the volume of what you built and compare it with the target volume.

CadQuery in this frame, every line of this sheet is tested:

```python
{sheet}```

Helper functions (world coordinates, each returns a cq.Workplane with one solid; they mix freely
with raw CadQuery: `.union()`, `.cut()`, `.translate()`, `.rotate()` all work on them):

{catalogue}

The measurements you will get back: size per axis, volume, through-hole count, and for each of
the eight views how well your outline matches, with the places (in mm) where you have material
the view does not show, or lack material it shows."""

FIRST_ASK = ("Write the complete program for this part. Use the frame of the brief (minimum corner of the "
             "bounding box at the origin).")


# --- in the subprocess: finish the program's result and compare it with the views ---------------

def _mini_task(ctx: dict) -> Task:
    return Task(name=ctx.get("name", "task"), description="", views=[Path(v) for v in ctx.get("views", [])],
                facts=ctx.get("facts") or {})


def finish(result, ctx_path: str, holes: str = "none", report_path: str | None = None):
    """Called by the last line of an exact program. Moves the solid so that its bounding-box
    minimum corner is at the origin (a translation; never a scale, never a mirror), optionally
    drills the listed bores until the through-hole count matches (holes="fit"), and writes the
    outline comparison with the eight views to `report_path`."""
    import cadquery as cq

    from ..compile import _largest_solid, cut_holes_to_genus
    from ..geometry import shape_to_mesh

    ctx = json.loads(Path(ctx_path).read_text())
    task = _mini_task(ctx)
    shape = result
    if isinstance(shape, cq.Workplane):
        vals = [v for v in shape.vals() if isinstance(v, cq.Shape)]
        if not vals:
            raise RuntimeError("`result` holds no solid")
        shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    if isinstance(shape, cq.Compound) and len(shape.Solids()) == 1:
        shape = shape.Solids()[0]
    bb = shape.BoundingBox()
    raw = {"min": [bb.xmin, bb.ymin, bb.zmin], "max": [bb.xmax, bb.ymax, bb.zmax]}
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    if holes == "fit" and task.facts.get("cylindrical_holes_and_bores") and task.facts.get("bounding_box_mm"):
        drilled = cut_holes_to_genus(cq.Workplane("XY").newObject([shape]), task)[0].val()
        drilled = _largest_solid(drilled)
        if drilled.isValid():
            shape = drilled
    if report_path:
        out = {"raw_bbox": raw, "iou": {}, "diffs": {}}
        if task.views and task.facts.get("bounding_box_mm") and len(shape.Solids()) == 1:
            out.update(silhouette_report(shape_to_mesh(shape), task))
        Path(report_path).write_text(json.dumps(out))
    return cq.Workplane("XY").newObject([shape])


def _axis_names(cam):
    """For an axis view: ((letter, sign), (letter, sign)) of the picture's horizontal and vertical."""
    out = []
    for v in (cam.r, cam.u):
        k = int(np.argmax(np.abs(v)))
        if abs(abs(v[k]) - 1.0) > 1e-6:
            return None
        out.append(("xyz"[k], 1.0 if v[k] > 0 else -1.0))
    return out


def _regions(mask: np.ndarray, cam, min_px: float, top: int = 3) -> list[str]:
    """The largest connected patches of `mask`, each as a range in mm (axis views) or a place in the picture."""
    from scipy import ndimage

    mask = ndimage.binary_opening(mask, iterations=1)       # one-pixel slivers along the outline are not a finding
    labels, n = ndimage.label(mask)
    if not n:
        return []
    areas = ndimage.sum(mask, labels, range(1, n + 1))
    names = _axis_names(cam)
    out = []
    for k in np.argsort(-areas)[:top]:
        if areas[k] < min_px:
            break
        ys, xs = np.nonzero(labels == k + 1)
        corners = cam.plane_mm(np.array([[xs.min() - 0.5, ys.max() + 0.5], [xs.max() + 0.5, ys.min() - 0.5]], float))
        area_mm2 = areas[k] / cam.scale ** 2
        if names:
            spans = []
            for j, (letter, sign) in enumerate(names):
                lo, hi = sorted((sign * corners[0][j], sign * corners[1][j]))
                spans.append(f"{letter} {lo:.1f}..{hi:.1f}")
            out.append(f"{spans[0]}, {spans[1]} mm ({area_mm2:.0f} mm^2)")
        else:
            cx, cy = xs.mean() / mask.shape[1], ys.mean() / mask.shape[0]
            where = ("upper" if cy < 0.4 else "lower" if cy > 0.6 else "middle") + " " + \
                    ("left" if cx < 0.4 else "right" if cx > 0.6 else "centre")
            out.append(f"{where} of the picture ({area_mm2:.0f} mm^2)")
    return out


def silhouette_report(mesh, task: Task) -> dict:
    """{"iou": {stem: value}, "diffs": {stem: {"extra": [...], "missing": [...], "extra_pct", "missing_pct"}}}.
    `extra` is material our part shows outside the view's outline, `missing` the reverse; the
    percentages are of the view's own outline area."""
    from ..vision import Camera, box_size, iou, project_mask, target_masks

    size = box_size(task.facts)
    ious, diffs = {}, {}
    for stem, target in target_masks(task).items():
        cam = Camera(stem, size, target.shape[0])
        ours = project_mask(mesh, cam)
        ious[stem] = iou(target, ours)
        area = max(int(target.sum()), 1)
        extra, missing = ours & ~target, target & ~ours
        min_px = max(40.0, 0.002 * area)
        diffs[stem] = {"extra": _regions(extra, cam, min_px), "missing": _regions(missing, cam, min_px),
                       "extra_pct": 100.0 * float(extra.sum()) / area, "missing_pct": 100.0 * float(missing.sum()) / area}
    return {"iou": ious, "diffs": diffs}


def measure_shape(shape, task: Task) -> dict:
    """The report of a shape we already hold (calibration and tests; the pipeline measures in the
    subprocess). The shape is moved to the origin first."""
    import cadquery as cq

    from ..backends._cq_runner import measure
    from ..geometry import genus, shape_to_mesh

    shape = shape.val() if isinstance(shape, cq.Workplane) else shape
    bb = shape.BoundingBox()
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    info = measure(shape)
    mesh = shape_to_mesh(shape)
    info["genus"] = genus(mesh)
    info["bbox_size"] = [float(e) for e in mesh.extents]
    sil = silhouette_report(mesh, task) if task.views and task.facts.get("bounding_box_mm") else {}
    return make_report(info, sil, task.facts)


# --- the report, the gate, the rank (pure code) ----------------------------------------------------

def make_report(measure: dict, sil: dict, facts: dict) -> dict:
    """Everything the gate and the model are told, from kernel measurements and the outline comparison."""
    box = facts.get("bounding_box_mm") or {}
    target = [float(box.get(k, 0.0)) for k in "xyz"]
    built = [float(v) for v in measure.get("bbox_size", [0, 0, 0])]
    rep = {
        "valid": bool(measure.get("valid")) and measure.get("solids") == 1,
        "solids": measure.get("solids"),
        "bbox": built, "bbox_target": target,
        "bbox_err": [(b - t) / t if t else 0.0 for b, t in zip(built, target)],
        "volume": float(measure.get("volume", 0.0)),
        "volume_ratio": float(measure["volume"]) / float(facts["volume_mm3"]) if facts.get("volume_mm3") else None,
        "genus": measure.get("genus"),
        "genus_target": int(facts["through_holes_genus"]) if facts.get("through_holes_genus") is not None else None,
        "iou": dict(sil.get("iou") or {}), "diffs": dict(sil.get("diffs") or {}),
        "raw_bbox": sil.get("raw_bbox"),
    }
    vals = list(rep["iou"].values())
    rep["iou_min"] = min(vals) if vals else None
    rep["iou_mean"] = float(np.mean(vals)) if vals else None
    if facts.get("surface_area_mm2"):                       # shown to the model only; hidden parts have none
        rep["area_ratio"] = float(measure.get("area", 0.0)) / float(facts["surface_area_mm2"])
    if facts.get("face_types"):
        rep["faces"], rep["faces_target"] = measure.get("faces"), facts["face_types"]
    return rep


def iou_bar() -> float:
    return float(os.environ.get("FORGE_EXACT_IOU", "0.965"))


def gate(rep: dict, bar: float | None = None, vol_tol: float | None = None) -> list[str]:
    """Why this part may NOT replace the current one; an empty list means it may. Strict on
    purpose: a part that fails keeps the no-model part, so the path can only lose where this
    test is wrong."""
    bar = iou_bar() if bar is None else bar
    vol_tol = float(os.environ.get("FORGE_EXACT_VOL", "0.04")) if vol_tol is None else vol_tol
    why = []
    if not rep.get("valid"):
        why.append("not one valid solid")
    if not any(rep.get("bbox_target") or []):
        why.append("no target size")
    for axis, err in zip("XYZ", rep.get("bbox_err") or []):
        if abs(err) > 0.01:
            why.append(f"{axis} size {err:+.1%}")
    if rep.get("genus_target") is not None and rep.get("genus") != rep["genus_target"]:
        why.append(f"through-holes {rep.get('genus')} against {rep['genus_target']}")
    if rep.get("volume_ratio") is None:
        why.append("no target volume")
    elif abs(rep["volume_ratio"] - 1.0) > vol_tol:
        why.append(f"volume x{rep['volume_ratio']:.3f}")
    if rep.get("iou_min") is None:
        why.append("no views to compare with")
    elif rep["iou_min"] < bar:
        worst = min(rep["iou"], key=rep["iou"].get)
        why.append(f"outline of the {SHORT.get(worst, worst)} view matches {rep['iou_min']:.3f} < {bar:.3f}")
    return why


def fidelity(rep: dict) -> float:
    """One number in 0..1 to rank programs by: the score's own weights, with the outline match
    (mean and worst view) standing in for the surface term."""
    if not rep.get("valid"):
        return 0.0
    errs = [abs(e) for e in rep.get("bbox_err") or [1.0]]
    dims = float(np.mean([max(0.0, 1.0 - e / 0.05) for e in errs]))      # 5% off on an axis is worth nothing
    holes = 1.0
    if rep.get("genus_target") is not None:
        g, t = rep.get("genus"), rep["genus_target"]
        holes = 1.0 if g == t else max(0.0, 1.0 - abs((g if g is not None else 0) - t) / max(t, 1)) * 0.8
    v = rep.get("volume_ratio")
    vol = min(v, 1.0 / v) if v and v > 0 else 0.0
    sil = 0.5 * (rep.get("iou_mean") or 0.0) + 0.5 * (rep.get("iou_min") or 0.0)
    return 0.2 * dims + 0.2 * holes + 0.3 * vol + 0.3 * sil


def volume_only(rep: dict) -> bool:
    """Fails the gate on volume alone and matches every outline at 0.98 or better: the only
    kind of failure the relaxed rule (FORGE_EXACT_RELAX=1) may admit."""
    why = gate(rep)
    return bool(why) and all(w.startswith("volume") for w in why) and (rep.get("iou_min") or 0.0) >= max(iou_bar(), 0.98)


def rank(rep: dict) -> tuple:
    """Which version of a program to keep: one that passes the gate, then one the relaxed rule
    could admit, then the most faithful."""
    return (not gate(rep), volume_only(rep), fidelity(rep))


def numbers(rep: dict) -> dict:
    """The numbers the gate looks at, for logs and the run summary."""
    r4 = lambda v: None if v is None else round(float(v), 4)
    return {"fidelity": r4(fidelity(rep)), "bbox_err": [r4(e) for e in rep.get("bbox_err") or []],
            "genus": rep.get("genus"), "genus_target": rep.get("genus_target"), "volume_ratio": r4(rep.get("volume_ratio")),
            "iou_min": r4(rep.get("iou_min")), "iou_mean": r4(rep.get("iou_mean"))}


def report_text(rep: dict) -> str:
    """The report as the model reads it."""
    lines = ["MEASURED BY CODE (exact):"]
    if not rep.get("valid"):
        lines.append(f"- NOT one valid solid ({rep.get('solids')} solids): pieces must overlap to fuse")
    for axis, b, t, e in zip("XYZ", rep["bbox"], rep["bbox_target"], rep["bbox_err"]):
        lines.append(f"- size {axis}: {b:.2f} mm, target {t:.2f} mm" + ("  ok" if abs(e) <= 0.005 else f"  WRONG ({e:+.1%})"))
    raw = rep.get("raw_bbox")
    if raw and any(abs(v) > 0.05 for v in raw["min"]):
        lines.append("- your solid's minimum corner was at ({:.2f}, {:.2f}, {:.2f}), not at the origin; it was moved there "
                     "for the comparison. Check for a centred box or a sketch placed about the origin.".format(*raw["min"]))
    v = rep.get("volume_ratio")
    if v is not None:
        target = rep["volume"] / v if v else 0.0
        if abs(v - 1) <= 0.015:
            lines.append(f"- volume: {rep['volume']:.0f} mm^3, target {target:.0f}  ok (x{v:.3f})")
        elif v > 1:
            lines.append(f"- volume: {rep['volume']:.0f} mm^3, target {target:.0f}: x{v:.3f}, {rep['volume'] - target:.0f} mm^3 TOO MUCH "
                         "material (a pocket, bore, groove or hollow is missing or too shallow, or a wall is too thick)")
        else:
            lines.append(f"- volume: {rep['volume']:.0f} mm^3, target {target:.0f}: x{v:.3f}, {target - rep['volume']:.0f} mm^3 MISSING "
                         "(a mass is left out, a wall is too thin or a cut too deep)")
    if rep.get("genus_target") is not None:
        ok = rep.get("genus") == rep["genus_target"]
        lines.append(f"- through-holes: {rep.get('genus')}, target {rep['genus_target']}" + ("  ok" if ok else
                     "  WRONG (a hole that should pass through ends in material, or a blind one breaks through)"))
    if rep.get("area_ratio") is not None:
        lines.append(f"- surface area: x{rep['area_ratio']:.3f} of the target's")
    if rep.get("faces_target"):
        mine = ", ".join(f"{k} {n}" for k, n in sorted((rep.get("faces") or {}).items()))
        want = ", ".join(f"{k} {n}" for k, n in sorted(rep["faces_target"].items()))
        lines.append(f"- faces by type: yours {mine}; target {want}")
    if rep.get("iou"):
        lines.append("OUTLINE against each view (1.000 = identical):")
        for stem, val in rep["iou"].items():
            name = SHORT.get(stem, stem)
            if val >= VIEW_OK:
                lines.append(f"- {name}: {val:.3f}  ok")
                continue
            d = rep["diffs"].get(stem, {})
            lines.append(f"- {name}: {val:.3f}  DIFFERS")
            if d.get("extra"):
                lines.append(f"    you have material the view does not show ({d.get('extra_pct', 0):.1f}% of the outline): " + "; ".join(d["extra"]))
            if d.get("missing"):
                lines.append(f"    you lack material the view shows ({d.get('missing_pct', 0):.1f}% of the outline): " + "; ".join(d["missing"]))
    return "\n".join(lines)


def clean(rep: dict) -> bool:
    """Nothing left worth a revision."""
    return (not gate(rep) and rep["iou_min"] >= VIEW_OK and abs(rep["volume_ratio"] - 1.0) <= 0.015)


# --- the loop --------------------------------------------------------------------------------------

def system_prompt() -> str:
    from .build import helper_catalogue

    return EXACT_SYSTEM.format(sheet=CHEAT_SHEET, catalogue=helper_catalogue())


def _left(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def ask(llm: LLM, content: list[dict], deadline: float | None = None) -> str:
    """One complete program. Thinking and the reply limit are set for this path only."""
    thinking = os.environ.get("FORGE_EXACT_THINKING", "medium").strip().lower()
    max_tokens = int(os.environ.get("FORGE_EXACT_MAX_TOKENS", "16000"))
    for _ in range(2):          # an empty or code-less reply must not cost the candidate
        left = _left(deadline)
        if left is not None and left < 30:
            return ""
        cap = float(os.environ.get("FORGE_EXACT_CALL_S", "600"))
        limit = cap if left is None else min(cap, left / 2)     # the client retries once: both tries must end before the deadline
        try:
            reply = llm.complete(system_prompt(), content, timeout=limit, thinking=thinking, max_tokens=max_tokens)
        except TypeError:       # an LLM without the per-call switches
            reply = llm.complete(system_prompt(), content, timeout=limit)
        code = extract_code(reply)
        if code:
            return code.split(EXACT_MARK)[0].rstrip()
        content = content + [text_block("Your previous reply contained no code block. Reply with the complete program in one code block.")]
    return ""


def execute(backend: CadBackend, task: Task, code: str, out_dir: Path, holes: str = "none"):
    """Run one program with the finishing lines. Returns (ExecResult, report or None)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, rep_path = out_dir / "ctx.json", out_dir / "outline.json"
    ctx.write_text(json.dumps({"name": task.name, "facts": task.facts, "views": [str(v) for v in task.views]}))
    full = (f"{code.split(EXACT_MARK)[0].rstrip()}\n\n{EXACT_MARK}\n"
            "from forge.stages.exact import finish as _finish_exact\n"
            f"result = _finish_exact(result, {str(ctx)!r}, holes={holes!r}, report_path={str(rep_path)!r})\n")
    res = backend.execute(full, out_dir, timeout=float(os.environ.get("FORGE_EXACT_RUN_S", "240")))
    if not res.ok:
        return res, None
    try:
        sil = json.loads(rep_path.read_text())
    except Exception:
        sil = {}
    return res, make_report(res.measure, sil, task.facts)


def check_of(res, rep: dict, facts: dict) -> dict:
    """The candidate's check in the shape the rest of the pipeline reads, plus the exact report."""
    from ..compile import estimate
    from ..facts import self_check

    check = self_check(res.measure, facts) if facts.get("bounding_box_mm") else {}
    if check:
        check["silhouette_iou"] = rep.get("iou_mean") or 0.0
        check["estimate"] = estimate(check, {"mean": check["silhouette_iou"]})
    check.update(exact=rep, fidelity=fidelity(rep), gate=gate(rep))
    return check


def run_exact(llm: LLM, backend: CadBackend, cand: Candidate, task: Task, task_blocks: list[dict],
              rounds: int | None = None, deadline: float | None = None, note: str = "") -> None:
    """program -> run -> report -> revised program, up to `rounds` revisions. The candidate ends
    up holding the best version by fidelity (cand.check["gate"] == [] if it may be offered)."""
    rounds = int(os.environ.get("FORGE_EXACT_ROUNDS", "3")) if rounds is None else rounds
    if not task.facts.get("bounding_box_mm"):
        cand.log.append("exact: no target size, not run")
        return
    has_bores = bool(task.facts.get("cylindrical_holes_and_bores"))
    code = ask(llm, task_blocks + ([text_block(note)] if note else []) + [text_block(FIRST_ASK)], deadline)
    kept = None          # (rank, code, result, report)
    history = []         # one line of numbers per round, for the run summary
    res = None
    for r in range(rounds + 1):
        if not code:
            cand.log.append("exact: no program in the reply")
            break
        res, rep = execute(backend, task, code, cand.dir / f"round{r}")
        ran = rep is not None
        if ran:
            best = (rank(rep), code, res, rep)
            if has_bores and rep["valid"] and rep.get("genus_target") is not None and rep.get("genus") != rep["genus_target"]:
                # the hole count is off: let code drill the listed bores and keep the better of the two
                res2, rep2 = execute(backend, task, code, cand.dir / f"round{r}_bores", holes="fit")
                if rep2 is not None and rank(rep2) > best[0]:
                    best = (rank(rep2), code, res2, rep2)
            if kept is None or best[0] > kept[0]:
                kept = best
            why = gate(best[3])
            history.append({"round": r, **numbers(best[3]), "strict": why, "volume_only": volume_only(best[3])})
            cand.log.append(f"exact round {r}: fidelity {fidelity(best[3]):.3f}, volume x{best[3].get('volume_ratio') or 0:.3f}, "
                            f"worst view {best[3].get('iou_min') or 0:.3f}, " + ("passes" if not why else "fails: " + "; ".join(why))
                            + ("" if not why else "; relaxed rule: " + ("eligible (volume only, all views >= 0.98)"
                                                                        if volume_only(best[3]) else "not eligible")))
            if clean(best[3]):
                break
            what = ("Your program ran. This is what code measured on its result:\n\n" + report_text(rep) + "\n\n"
                    "Find the cause of every WRONG and DIFFERS line in your program (a dimension, a position, a missing or "
                    "extra feature, a count), correct it, and keep what is already right.")
        else:
            cand.log.append(f"exact round {r}: error: {res.error.splitlines()[-1] if res.error else '?'}")
            what = ("Your program failed:\n" + (res.error or "unknown failure")[-1800:] + "\n\n"
                    "Fix the cause and keep the intended geometry. If a round or chamfer fails, put it in try/except.")
        left = _left(deadline)
        if r == rounds or (left is not None and left < 90):
            break
        try:
            code = ask(llm, task_blocks + [text_block(f"YOUR PROGRAM (version {r + 1}):\n```python\n{code}\n```\n\n{what}\n\n"
                                                      "Reply with the complete corrected program in one code block.")], deadline)
        except Exception as exc:
            cand.log.append(f"exact: revision call failed: {type(exc).__name__}")
            break
    if kept:
        _, cand.code, cand.result, rep = kept
        cand.check = check_of(cand.result, rep, task.facts)
        cand.check["rounds"] = history
    elif res is not None:
        cand.result, cand.check = res, {}


# --- may it replace the best part so far? -------------------------------------------------------------

def floor_report(floor: dict | None) -> dict | None:
    """The no-model part in the terms of the gate, from what forge.compile recorded for it."""
    if not floor or not floor.get("check"):
        return None
    c, per = floor["check"], (floor.get("shape") or {}).get("iou_per_view") or {}
    dims_ok = c.get("dimensions", 0.0) >= 0.99
    return {"valid": True, "bbox_target": [1, 1, 1], "bbox_err": [0.0 if dims_ok else 0.05] * 3,
            "volume_ratio": c.get("volume_ratio"), "genus": 0 if c.get("holes", 0.0) >= 1.0 else -1, "genus_target": 0,
            "iou": per, "iou_min": min(per.values()) if per else None,
            "iou_mean": float(np.mean(list(per.values()))) if per else None}


def relax_on() -> bool:
    return os.environ.get("FORGE_EXACT_RELAX", "0").strip().lower() in ("1", "on", "yes", "true")


def dominates(check: dict, floor: dict | None, relax: bool | None = None) -> bool:
    """FORGE_EXACT_RELAX=1 (off by default): a second way in for a program that fails the gate on
    volume ALONE. It must match every outline at 0.98 or better and be clearly nearer the target
    volume than the no-model part, with outlines no worse: then it is at least as good on every
    number we can measure. For parts whose stated volume no solid consistent with brief and views
    reaches (practice part 6), where the strict gate can never open."""
    if not (relax_on() if relax is None else relax) or not floor:
        return False
    rep, base = check.get("exact") or {}, floor_report(floor)
    if not base or not all(w.startswith("volume") for w in check.get("gate") or ["-"]):
        return False
    sym = lambda v: min(v, 1.0 / v) if v and v > 0 else 0.0
    return ((rep.get("iou_min") or 0.0) >= max(iou_bar(), 0.98)
            and sym(rep.get("volume_ratio")) >= sym(base.get("volume_ratio")) + 0.05
            and (rep.get("iou_mean") or 0.0) >= (base.get("iou_mean") or 1.0) - 0.01)


def verdict(check: dict, floor: dict | None, relax: bool) -> list[str]:
    """Why this exact program may NOT stand in for the no-model part, under the strict rule
    (relax=False) or the relaxed one (relax=True); [] means it may. It does not read
    FORGE_EXACT_RELAX, so one run can log what each rule would have decided."""
    if not check or "gate" not in check:
        return ["no measured result"]
    why = []
    if check["gate"] and not dominates(check, floor, relax=relax):
        why += list(check["gate"])
        if relax:
            why.append("relaxed rule: needs a volume-only failure, all views >= 0.98 and a volume clearly nearer than the no-model part's")
    if floor and check.get("dimensions", 1.0) < floor["check"].get("dimensions", 1.0) - 0.01:
        why.append("outer dimensions worse than the no-model part's")
    rep = floor_report(floor)
    if rep and not gate(rep) and fidelity(rep) >= check["fidelity"]:
        why.append(f"the no-model part passes the same test with fidelity {fidelity(rep):.3f}")
    return why


def accept(cand: Candidate, best: dict, floor: dict | None, relax: bool | None = None) -> bool:
    """An exact program replaces the current part only if it passes the gate, its outer dimensions
    are not worse than the no-model part's, and it is more faithful than what it replaces: than
    the exact program chosen before it, or than a no-model part that itself passes the gate."""
    if not cand.usable or not cand.check or "gate" not in cand.check:
        return False
    why = verdict(cand.check, floor, relax_on() if relax is None else relax)
    if why:
        cand.log += [f"exact: not offered, {w}" for w in why if w not in cand.check["gate"] and not w.startswith("relaxed rule")]
        return False
    if best.get("exact"):
        return cand.check["fidelity"] > (best.get("check") or {}).get("fidelity", 0.0)
    return True
