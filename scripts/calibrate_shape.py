"""Does the silhouette score rank parts the way the leaderboard does?

bench/calibration/ holds STEP files with a leaderboard score each. Shape points =
leaderboard - 0.2 * dimensions - 0.2 * holes (both exact from facts.json). Compares the
rank correlation of shape points with (a) silhouette IoU, (b) volume ratio, (c) area ratio.

    uv run python scripts/calibrate_shape.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forge.cases import load_tasks  # noqa: E402
from forge.facts import self_check  # noqa: E402
from forge.vision import shape_score  # noqa: E402


def measure_step(path):
    import cadquery as cq
    from forge.backends._cq_runner import measure
    from forge.geometry import genus, shape_to_mesh

    vals = cq.importers.importStep(str(path)).vals()
    shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    info = measure(shape)
    mesh = shape_to_mesh(shape)
    info["genus"] = genus(mesh)
    return info, mesh


def main():
    tasks = {t.name: t for t in load_tasks(ROOT / "artifacts/inputs")}
    rows = []
    for folder in sorted((ROOT / "bench/calibration").iterdir()):
        scores = json.loads((folder / "scores.json").read_text())["cases"]
        for name, s in scores.items():
            if folder.name != "1111-boxes" and s.get("self_score") is None:
                continue  # the same box again
            task = tasks[name]
            info, mesh = measure_step(folder / f"{name}.stp")
            chk = self_check(info, task.facts)
            sh = shape_score(mesh, task)
            shape_pts = s["leaderboard"] - 0.2 * chk["dimensions"] - 0.2 * chk["holes"]
            rows.append(dict(set=folder.name, case=name, lb=s["leaderboard"], shape_pts=shape_pts,
                             iou=sh["mean"], vol=min(chk["volume_ratio"], 1 / chk["volume_ratio"]),
                             area=min(chk["area_ratio"], 1 / chk["area_ratio"]),
                             dims=chk["dimensions"], holes=chk["holes"]))
            r = rows[-1]
            print(f"{r['set'][:12]:12s} {name[-1]}  lb {r['lb']:.3f}  shape_pts {shape_pts:.3f}  iou {r['iou']:.3f}  "
                  f"vol {r['vol']:.3f}  area {r['area']:.3f}  dims {r['dims']:.2f} holes {r['holes']:.2f}", flush=True)
    y = np.array([r["shape_pts"] for r in rows])
    for key in ("iou", "vol", "area"):
        x = np.array([r[key] for r in rows])
        print(f"spearman(shape points, {key:4s}) = {spearmanr(x, y)[0]:.3f}   pearson = {np.corrcoef(x, y)[0, 1]:.3f}")
    (ROOT / "bench/calibration/shape_calibration.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
