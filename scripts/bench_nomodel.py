"""True local score of the no-model builder on our own reference parts (they have answers).

Renders each bench answer as eight silhouette images with the organisers' framing, builds
the part from those views and the facts with forge.compile, and scores it against the
answer with forge.score. The bench facts carry no bore inventory, so this measures the
silhouette bodies only (holes come from daylight in the views).

    uv run python scripts/bench_nomodel.py [--tag c-hull-bench]
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
    import numpy as np
    from PIL import Image

    from forge.cases import load_tasks
    from forge.compile import compile_part
    from forge.geometry import load_mesh
    from forge.render import VIEWS
    from forge.score import score
    from forge.vision import Camera, box_size, project_mask

    case = Path(case_dir)
    task = load_tasks(case.parent, [case.name])[0]
    mesh = load_mesh(task.answer)
    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    views = []
    for stem in VIEWS:
        mask = project_mask(mesh, Camera(stem, box_size(task.facts), 1024))
        rgb = np.full(mask.shape + (3,), 255, np.uint8)
        rgb[mask] = (186, 146, 95)
        Image.fromarray(rgb).save(tmp / f"{stem}.png")
        views.append(tmp / f"{stem}.png")
    task.views = views
    rows = compile_part(task, tmp / "out")
    best = rows[0]
    box = next(r for r in rows if r["name"].startswith("box"))
    return case.name, best["name"], best["estimate"], score(best["step"], mesh), score(box["step"], mesh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag")
    a = ap.parse_args()
    cases = sorted(str(d) for d in (ROOT / "bench/cases").iterdir() if (d / "answer.step").is_file())
    with ProcessPoolExecutor(6) as pool:
        results = list(pool.map(one, cases))
    out = {}
    for name, chosen, est, s, b in results:
        out[name] = {"chosen": chosen, "estimate": est, "self_score": 0.0, **s, "box_score": b["score"]}
        print(f"{name:18s} {chosen:14s} est {est:.3f}  score {s['score']:.3f} (vol {s['volume']:.2f} surf {s['surface']:.2f} "
              f"dims {s['dimensions']:.2f} holes {s['holes']:.2f})   box {b['score']:.3f}")
    n = len(out)
    res = {"inputs": "bench/cases (silhouettes rendered from answers)", "n_cases": n,
           "mean_score": sum(c["score"] for c in out.values()) / n,
           "mean_box_score": sum(c["box_score"] for c in out.values()) / n,
           "mean_self_score": 0.0, "mean_estimate": sum(c["estimate"] for c in out.values()) / n, "cases": out}
    print(f"MEAN local score {res['mean_score']:.3f}   box {res['mean_box_score']:.3f}   est {res['mean_estimate']:.3f}")
    if a.tag:
        (ROOT / "results" / f"{time.strftime('%m%d-%H%M')}-{a.tag}.json").write_text(json.dumps(res, indent=1))
