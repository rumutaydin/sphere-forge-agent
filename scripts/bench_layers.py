"""True local score of the depth-reading ideas on our reference parts, drawn in the organisers' style.

For each bench part: render the answer as eight shaded, stroked views (forge.render.
render_organiser_style), build the hull from them, then carve with forge.layers.carve_layers,
and score hull and carved body against the answer.

    uv run python scripts/bench_layers.py [--only 06_enclosure 08_elbow] [--tag b-layers]
"""
import argparse
import json
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def one(case_dir: str):
    import cadquery as cq

    from forge.cases import load_tasks
    from forge.compile import AXIS_VIEWS, ISO_VIEWS, hull_body
    from forge.geometry import shape_to_mesh
    from forge.layers import carve_layers
    from forge.render import render_organiser_views
    from forge.score import score
    from forge.vision import box_size

    case = Path(case_dir)
    task = load_tasks(case.parent, [case.name + "$"])[0]
    shape = cq.importers.importStep(str(task.answer)).val()
    bb = shape.BoundingBox()
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    answer = shape_to_mesh(shape)
    task.views = render_organiser_views(shape, Path(tempfile.mkdtemp(prefix="bench-")), box_size(task.facts))
    hull = hull_body(task, AXIS_VIEWS + ISO_VIEWS)
    log: list[str] = []
    carved = carve_layers(hull, task, log=log)
    s0, s1 = score(shape_to_mesh(hull.val()), answer), score(shape_to_mesh(carved.val()), answer)
    return case.name, s0, s1, hull.val().Volume() / shape.Volume(), carved.val().Volume() / shape.Volume(), log


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tag")
    a = ap.parse_args()
    cases = sorted(str(d) for d in (ROOT / "bench/cases").iterdir()
                   if (d / "answer.step").is_file() and (not a.only or d.name in a.only))
    with ProcessPoolExecutor(6) as pool:
        results = list(pool.map(one, cases))
    out = {}
    for name, s0, s1, v0, v1, log in results:
        out[name] = {"hull": s0["score"], "score": s1["score"], "self_score": 0.0, "volume_hull": v0, "volume_carved": v1}
        print(f"{name:18s} hull {s0['score']:.3f} (vol x{v0:.2f})  ->  carved {s1['score']:.3f} (vol x{v1:.2f})   "
              f"[{sum(' cut' in l for l in log)} cuts kept of {len(log)}]")
    n = len(out)
    res = {"inputs": "bench/cases (organiser-style renders of the answers)", "n_cases": n, "mean_self_score": 0.0,
           "mean_score": sum(c["score"] for c in out.values()) / n, "mean_hull": sum(c["hull"] for c in out.values()) / n,
           "cases": out}
    print(f"MEAN local score: hull {res['mean_hull']:.3f} -> carved {res['mean_score']:.3f}")
    if a.tag:
        (ROOT / "results" / f"{time.strftime('%m%d-%H%M')}-{a.tag}.json").write_text(json.dumps(res, indent=1))
