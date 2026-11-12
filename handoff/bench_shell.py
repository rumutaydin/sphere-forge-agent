"""True local score with and without the hull-shell sources, through the real compile_part.

For each bench part with an answer: organiser-style views of the answer, compile_part, then
score (a) the top row (shells allowed) and (b) the top row that is not a shell (= FORGE_SHELL=off).
    uv run python <this> [case ...]
"""
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(os.environ.get("FORGE_REPO", ".")).resolve()
sys.path.insert(0, str(ROOT))


def one(case_dir):
    import cadquery as cq

    from forge.cases import load_tasks
    from forge.compile import compile_part
    from forge.geometry import shape_to_mesh
    from forge.render import render_organiser_views
    from forge.score import score
    from forge.vision import box_size

    t0 = time.time()
    case = Path(case_dir)
    task = load_tasks(case.parent, [case.name + "$"])[0]
    shape = cq.importers.importStep(str(task.answer)).val()
    bb = shape.BoundingBox()
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    answer = shape_to_mesh(shape)
    tmp = Path(tempfile.mkdtemp(prefix="shellbench-"))
    task.views = render_organiser_views(shape, tmp / "views", box_size(task.facts))
    rows = compile_part(task, tmp / "out")
    on = rows[0]
    off = next(r for r in rows if not r["name"].startswith("hull-shell"))
    s_on = score(on["step"], answer)["score"]
    s_off = s_on if off is on else score(off["step"], answer)["score"]
    shells = [(r["name"], round(r["estimate"], 3), round(r["check"]["volume_ratio"], 2), round(r["check"].get("area_ratio", 0), 2))
              for r in rows if r["name"].startswith("hull-shell")]
    return {"case": case.name, "off": (off["name"], round(off["estimate"], 3), round(s_off, 3)),
            "on": (on["name"], round(on["estimate"], 3), round(s_on, 3)), "shells": shells,
            "secs": round(time.time() - t0)}


if __name__ == "__main__":
    cases = sorted(p for p in (ROOT / "bench/cases").iterdir() if (p / "answer.step").exists() or list(p.glob("answer*")))
    if sys.argv[1:]:
        cases = [c for c in cases if c.name in sys.argv[1:]]
    res = []
    with ProcessPoolExecutor(int(os.environ.get("W", "6"))) as ex:
        for r in ex.map(one, map(str, cases)):
            res.append(r)
            print(json.dumps(r), flush=True)
    d = [r["on"][2] - r["off"][2] for r in res]
    print(f"mean off {sum(r['off'][2] for r in res)/len(res):.4f}  on {sum(r['on'][2] for r in res)/len(res):.4f}  "
          f"changed {sum(1 for x in d if abs(x) > 1e-4)} of {len(res)}")
