"""Does the edge score rank variants of a part the way the leaderboard does?

bench/approaches/<name>/ holds nine STEP files per submission and, in scores.json, the
leaderboard value of each part. For every part this computes the edge score of every
distinct file and compares, within the part, how the leaderboard orders the variants with
how (a) our estimate and (b) the edge score order them.

    uv run python scripts/calibrate_edges.py          # writes bench/calibration/edge_calibration.json
"""
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def one(name: str):
    from forge.cases import load_tasks
    from forge.geometry import load_mesh
    from forge.vision import edge_score

    task = load_tasks(ROOT / "artifacts/inputs", [name + "$"])[0]
    rows, seen = [], {}
    for d in sorted((ROOT / "bench/approaches").iterdir()):
        f, sc = d / f"{name}.stp", d / "scores.json"
        if not f.is_file() or not sc.is_file():
            continue
        case = json.loads(sc.read_text())["cases"].get(name, {})
        if case.get("leaderboard") is None:
            continue
        digest = hashlib.md5(f.read_bytes()).hexdigest()
        if digest not in seen:
            seen[digest] = edge_score(load_mesh(f), task)
        e = seen[digest]
        rows.append({"approach": d.name, "case": name, "leaderboard": case["leaderboard"], "estimate": case["estimate"],
                     "volume_ratio": case.get("volume_ratio"), "silhouette_iou": case.get("silhouette_iou"),
                     "holes": case.get("holes"), "dimensions": case.get("dimensions"),
                     "edge_all": e["all"], "edge_inner": e["inner"], "file": digest[:8]})
    return rows


if __name__ == "__main__":
    # the two 11 Nov sets carry their per-part leaderboard values in bench/calibration
    for a, c in (("00-boxes", "1111-boxes"), ("00-qwen-picked", "1111-qwen-picked")):
        p = ROOT / "bench/approaches" / a / "scores.json"
        s, cal = json.loads(p.read_text()), json.loads((ROOT / "bench/calibration" / c / "scores.json").read_text())["cases"]
        for k, v in cal.items():
            s["cases"][k]["leaderboard"] = v["leaderboard"]
        p.write_text(json.dumps(s, indent=1))
    names = [f"test_case_{i}" for i in range(1, 10)]
    with ProcessPoolExecutor(5) as pool:
        rows = [r for part in pool.map(one, names) for r in part]
    (ROOT / "bench/calibration/edge_calibration.json").write_text(json.dumps(rows, indent=1))
    print(f"{len(rows)} scored files, {len({(r['case'], r['file']) for r in rows})} distinct")
    keys = ("estimate", "edge_all", "edge_inner")
    print("\nwithin each part: rank correlation with the leaderboard (distinct files only)")
    acc = {k: [] for k in keys}
    for name in names:
        part = {r["file"]: r for r in rows if r["case"] == name}.values()
        lb = [r["leaderboard"] for r in part]
        if len(part) < 3 or len(set(lb)) < 2:
            continue
        line = f"  {name[-1]}  n={len(part)}"
        for k in keys:
            rho = spearmanr([r[k] for r in part], lb)[0]
            acc[k].append(rho)
            line += f"   {k} {rho:+.2f}"
        print(line)
    print("  mean " + "   ".join(f"{k} {np.nanmean(v):+.2f}" for k, v in acc.items()))
    # the same without the boxes, which every measure ranks last: the hard cases only
    acc = {k: [] for k in keys}
    for name in names:
        part = [r for r in {r["file"]: r for r in rows if r["case"] == name}.values() if r["approach"] != "00-boxes"]
        lb = [r["leaderboard"] for r in part]
        if len(part) < 3 or len(set(lb)) < 2:
            continue
        for k in keys:
            acc[k].append(spearmanr([r[k] for r in part], lb)[0])
    print("without boxes: mean " + "   ".join(f"{k} {np.nanmean(v):+.2f} (n={len(v)})" for k, v in acc.items()))
