"""Build every practice part with no model and print what each body source scores.

    uv run python scripts/compile_all.py [-o runs/compile] [--only 1 7] [--tag c-hull]
Self-score parts are exact (dimensions, holes); "est" is the rough leaderboard estimate.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def one(args):
    name, inputs, out = args
    from forge.cases import load_tasks
    from forge.compile import compile_part

    task = load_tasks(inputs, [name])[0]
    t0 = time.time()
    rows = compile_part(task, Path(out) / task.name)
    return task.name, rows, time.time() - t0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default=str(ROOT / "artifacts/inputs"))
    ap.add_argument("-o", "--out", default="runs/compile")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tag")
    a = ap.parse_args()
    from forge.cases import load_tasks

    names = [t.name for t in load_tasks(a.inputs, a.only)]
    t0 = time.time()
    with ProcessPoolExecutor(5) as pool:
        results = list(pool.map(one, [(n + "$" if False else n, a.inputs, a.out) for n in names]))
    cases = {}
    for name, rows, secs in results:
        print(f"== {name}  ({secs:.0f}s)")
        for r in rows:
            c, s = r["check"], r["shape"]
            print(f"   {r['name']:26s} est {r['estimate']:.3f}  dims {c['dimensions']:.2f} holes {c['holes']:.2f} "
                  f"vol x{c['volume_ratio']:.3f} area x{c['area_ratio']:.3f} sil {s['mean']:.3f}")
        if rows:
            b = rows[0]
            cases[name] = {"chosen": b["name"], "estimate": b["estimate"], "self_score": b["check"]["self_score"],
                           "dimensions": b["check"]["dimensions"], "holes": b["check"]["holes"],
                           "volume_ratio": b["check"]["volume_ratio"], "area_ratio": b["check"]["area_ratio"],
                           "silhouette_iou": b["shape"]["mean"], "seconds": secs}
    n = max(len(cases), 1)
    result = {"inputs": a.inputs, "n_cases": len(cases), "wall_clock_s": time.time() - t0,
              "mean_estimate": sum(c["estimate"] for c in cases.values()) / n,
              "mean_self_score": sum(c["self_score"] for c in cases.values()) / n, "mean_score": None, "cases": cases}
    print(f"MEAN est {result['mean_estimate']:.3f}  self {result['mean_self_score']:.3f}  wall {result['wall_clock_s']:.0f}s")
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "scores.json").write_text(json.dumps(result, indent=1))
    if a.tag:
        (ROOT / "results" / f"{time.strftime('%m%d-%H%M')}-{a.tag}.json").write_text(json.dumps(result, indent=1))
