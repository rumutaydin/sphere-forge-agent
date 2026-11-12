"""True score of an outputs folder against bench/cases answers.
    uv run python handoff/score_outputs.py runs/<run>/outputs"""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def one(p):
    import cadquery as cq
    from forge.geometry import shape_to_mesh
    from forge.score import score
    p = Path(p)
    shape = cq.importers.importStep(str(ROOT / "bench/cases" / p.stem / "answer.step")).val()
    bb = shape.BoundingBox()
    ans = shape_to_mesh(shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin)))
    s = score(str(p), ans)
    return p.stem, {k: round(v, 3) for k, v in s.items()}

if __name__ == "__main__":
    files = sorted(Path(sys.argv[1]).glob("*.stp"))
    with ProcessPoolExecutor(8) as ex:
        res = dict(ex.map(one, map(str, files)))
    for k, v in res.items():
        print(f"{k:18s} {v['score']:.3f}  vol {v['volume']:.2f} surf {v['surface']:.2f} dims {v['dimensions']:.2f} holes {v['holes']:.2f}")
    print(f"MEAN {sum(v['score'] for v in res.values())/len(res):.4f}  n={len(res)}")
    Path(sys.argv[1], "true_scores.json").write_text(json.dumps(res, indent=1))
