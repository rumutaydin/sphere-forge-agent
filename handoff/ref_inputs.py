"""Make an organiser-style inputs folder from bench/cases (views drawn like the organisers').
    uv run python handoff/ref_inputs.py runs/refin [case ...]"""
import shutil, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def one(args):
    case, out = map(Path, args)
    import cadquery as cq
    from forge.render import render_organiser_views
    from forge.vision import box_size
    import json
    d = out / case.name
    (d / "images").mkdir(parents=True, exist_ok=True)
    for f in ("description.md", "facts.json"):
        shutil.copy(case / f, d / f)
    shape = cq.importers.importStep(str(case / "answer.step")).val()
    bb = shape.BoundingBox()
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    render_organiser_views(shape, d / "images", box_size(json.loads((case / "facts.json").read_text())))
    return case.name

if __name__ == "__main__":
    out = Path(sys.argv[1])
    cases = [p for p in sorted((ROOT / "bench/cases").iterdir()) if (p / "answer.step").exists()]
    if sys.argv[2:]:
        cases = [c for c in cases if c.name in sys.argv[2:]]
    with ProcessPoolExecutor(8) as ex:
        for n in ex.map(one, [(str(c), str(out)) for c in cases]):
            print(n)
