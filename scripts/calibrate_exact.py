"""Calibration of the exact-program gate (forge/stages/exact.py: gate), no model.

The gate must let an exact part through and stop everything else. Tested on:
  - bench/cases/*/answer.step against organiser-style renders of themselves   -> must PASS
  - the visual hull of the same renders                                        -> must FAIL where its volume is wrong
  - damaged answers: stretched 5% along X (a test shape, never an output); and, for parts whose
    program we have (bench/parts), a feature removed, a groove filled, a wall or bore changed -> must FAIL
  - the nine practice outputs on main (no-model hulls and model bodies) against the real views  -> listed

    uv run python scripts/calibrate_exact.py [--only 03_flange]
"""
import argparse
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (case, label, text in bench/parts/<case>.py, replacement)
DAMAGE = [
    ("03_flange", "bolt holes removed", "result = body.cut(bore).cut(bolts)", "result = body.cut(bore)"),
    ("03_flange", "hub 30 -> 24 high", ".circle(20).extrude(30))", ".circle(20).extrude(24)).union(cq.Workplane('XY').circle(11).extrude(30))"),
    ("11_heat_sink", "one groove filled", "    result = result.union(fin)",
     "    result = result.union(fin)\nresult = result.union(cq.Workplane('XY').box(8, 60, 21, centered=(True, True, False)).translate((-4, 0, 4)))"),
    ("11_heat_sink", "two fins removed", "for i in range(8):", "for i in (0, 1, 2, 5, 6, 7):"),
    ("06_enclosure", "wall 3 -> 5", ".shell(-3)", ".shell(-5)"),
    ("06_enclosure", "not hollowed", ".faces(\">Z\").shell(-3)", ""),
    ("10_pillow_block", "bore 25 -> 18", ".circle(12.5)", ".circle(9)"),
    ("10_pillow_block", "mount holes removed", "result = base.union(upright).cut(bore).cut(mounts)", "result = base.union(upright).cut(bore)"),
    ("07_u_channel", "slot 25 -> 20 deep", "workplane(offset=5).box(120, 30, 25", "workplane(offset=10).box(120, 30, 20"),
    ("09_wheel", "5 holes -> 4", "polarArray(26, 0, 360, 5)", "polarArray(26, 0, 360, 4)"),
    ("09_wheel", "holes on radius 26 -> 22", "polarArray(26, 0, 360, 5)", "polarArray(22, 0, 360, 5)"),
    ("02_l_bracket", None, None, None),
]


def row(label, rep):
    from forge.stages.exact import fidelity, gate

    why = gate(rep)
    return {"what": label, "volume": rep.get("volume_ratio"), "holes": f"{rep.get('genus')}/{rep.get('genus_target')}",
            "bbox_err": max(abs(e) for e in rep["bbox_err"]), "iou_min": rep.get("iou_min"), "iou_mean": rep.get("iou_mean"),
            "fidelity": fidelity(rep), "pass": not why, "why": "; ".join(why)}


def stretched(shape, k=1.05):
    """The shape stretched along X: a damaged test shape for the gate, never an output."""
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform
    from OCP.gp import gp_GTrsf

    t = gp_GTrsf()
    t.SetValue(1, 1, k)
    return cq.Shape.cast(BRepBuilderAPI_GTransform(shape.wrapped, t, True).Shape())


def bench_case(case_dir: str):
    import cadquery as cq
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    from forge.cases import load_tasks
    from forge.compile import AXIS_VIEWS, ISO_VIEWS, hull_body
    from forge.render import render_organiser_views
    from forge.stages.exact import measure_shape
    from forge.vision import box_size

    case = Path(case_dir)
    task = load_tasks(case.parent, [case.name + "$"])[0]
    shape = cq.importers.importStep(str(task.answer)).val()
    bb = shape.BoundingBox()
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    task.views = render_organiser_views(shape, Path(tempfile.mkdtemp(prefix="gate-")), box_size(task.facts))
    for v in task.views:        # the organisers' outline stroke lies one pixel OUTSIDE the true edge; ours is drawn inside
        rgb = np.asarray(Image.open(v).convert("RGB")).copy()
        part = rgb.min(axis=2) < 235
        rgb[ndimage.binary_dilation(part) & ~part] = (20, 16, 12)
        Image.fromarray(rgb).save(v)
    rows = [row("answer", measure_shape(shape, task))]
    try:
        rows.append(row("hull of the views", measure_shape(hull_body(task, AXIS_VIEWS + ISO_VIEWS), task)))
    except Exception as exc:
        rows.append({"what": "hull of the views", "error": str(exc)[:80]})
    if case.name != "12_loft_adapter":      # the kernel's validity check crashes on the stretched loft surface
        rows.append(row("answer stretched 5% in X", measure_shape(stretched(shape), task)))
    src = (ROOT / "bench/parts" / f"{case.name}.py").read_text()
    for name, label, old, new in DAMAGE:
        if name != case.name or not label:
            continue
        assert old in src, (name, label)
        ns: dict = {}
        exec(src.replace(old, new), ns)
        rows.append(row(label, measure_shape(ns["result"], task)))
    return case.name, rows


def practice_case(n: int):
    import cadquery as cq

    from forge.cases import load_tasks
    from forge.stages.exact import measure_shape

    task = load_tasks(ROOT / "artifacts/inputs", [f"test_case_{n}$"])[0]
    shape = cq.importers.importStep(str(ROOT / f"artifacts/outputs/test_case_{n}.stp")).val()
    return f"practice {n}", [row("our output on main", measure_shape(shape, task))]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    cases = sorted(str(d) for d in (ROOT / "bench/cases").iterdir()
                   if (d / "answer.step").is_file() and (not a.only or d.name in a.only))
    with ProcessPoolExecutor(6) as pool:
        jobs = [pool.submit(bench_case, c) for c in cases]
        if not a.only:
            jobs += [pool.submit(practice_case, n) for n in range(1, 10)]
        results = [j.result() for j in jobs]
    print(f"{'case':16s} {'what':28s} {'volume':>7s} {'holes':>6s} {'bbox':>6s} {'IoU min':>8s} {'mean':>6s} {'fid':>6s}  gate")
    for name, rows in results:
        for r in rows:
            if "error" in r:
                print(f"{name:16s} {r['what']:28s} error: {r['error']}")
                continue
            print(f"{name:16s} {r['what']:28s} {r['volume']:7.3f} {r['holes']:>6s} {r['bbox_err']:6.3f} {r['iou_min']:8.4f} "
                  f"{r['iou_mean']:6.4f} {r['fidelity']:6.3f}  {'PASS' if r['pass'] else 'fail: ' + r['why']}")
