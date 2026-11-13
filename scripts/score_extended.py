"""Score a folder of outputs for the extended set against the REAL facts and views.

    uv run python scripts/score_extended.py <outputs_dir> [--scoring runs/extended/scoring]
                                            [--summary <work>/run_summary.json] [--tag a-v6-extended]

<outputs_dir> holds test_case_<n>.stp (as written by scripts/main.py on the inputs of
scripts/prep_extended.py). The source of each part (exact | body | hull | box) is read from the
run's run_summary.json: given with --summary, or found beside or inside <outputs_dir>
(run_summary.json, work/run_summary.json, ../work/run_summary.json); without it the column is "?".

The number is the LOCAL ESTIMATE (forge.compile.estimate: dimensions and holes exact against the
facts, volume ratio and silhouette match standing in for volume and surface). There are no answer
files for these parts, so it is a stand-in, not a leaderboard prediction. A missing or invalid
file counts 0. Measuring is done by scripts/rescore.py.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def one(args):
    name, scoring, step = args
    from rescore import real_tasks, score_step

    task = real_tasks(scoring, [name + "$"])[0]
    has_facts = (Path(scoring) / name / "facts.json").is_file()
    return name, (score_step(step, task) if has_facts else None), has_facts


def find_summary(outputs: Path, given: str | None) -> dict:
    for f in ([Path(given)] if given else [outputs / "run_summary.json", outputs / "work" / "run_summary.json",
                                           outputs.parent / "work" / "run_summary.json", outputs.parent / "run_summary.json"]):
        try:
            return json.loads(f.read_text()).get("parts", {})
        except Exception:
            continue
    return {}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("outputs")
    ap.add_argument("--scoring", default=str(ROOT / "runs/extended/scoring"))
    ap.add_argument("--summary")
    ap.add_argument("--tag", help="save to results/<time>-<tag>.json")
    a = ap.parse_args()
    outputs, scoring = Path(a.outputs), Path(a.scoring)
    if not scoring.is_dir():
        raise SystemExit(f"{scoring} not found: run scripts/prep_extended.py first")
    try:
        ids = json.loads((scoring.parent / "map.json").read_text())
    except Exception:
        ids = {}
    order = lambda n: (0, int(n.rsplit("_", 1)[-1])) if n.rsplit("_", 1)[-1].isdigit() else (1, 0)
    names = sorted((d.name for d in scoring.iterdir() if d.is_dir()), key=order)
    parts = find_summary(outputs, a.summary)
    with ProcessPoolExecutor(5) as pool:
        checks = list(pool.map(one, [(n, str(scoring), str(outputs / f"{n}.stp")) for n in names]))
    rows, by_source = {}, {}
    print(f"{'task':13s} {'part':34s} {'source':6s} {'dims':>5s} {'holes':>5s} {'volume':>7s} {'outline':>7s} {'estimate':>8s}  strict/relaxed would choose")
    for name, c, has_facts in checks:
        p = parts.get(name, {})
        source = p.get("source", "?")
        w = p.get("would_choose") or {}
        note = f"{w.get('strict')} / {w.get('relaxed')}" if w and w.get("strict") != w.get("relaxed") else ""
        if not has_facts:
            print(f"{name:13s} {ids.get(name, '')[:34]:34s} {source:6s}  no real facts: not scored")
            continue
        est = c["estimate"] if c else 0.0
        rows[name] = {"part": ids.get(name), "source": source, "valid": c is not None, "estimate": round(est, 4),
                      **({k: round(float(c[k]), 4) for k in ("self_score", "dimensions", "holes", "volume_ratio", "silhouette_iou")} if c else {})}
        by_source.setdefault(source, []).append(est)
        print(f"{name:13s} {ids.get(name, '')[:34]:34s} {source:6s} "
              + (f"{c['dimensions']:5.2f} {c['holes']:5.2f} x{c['volume_ratio']:6.3f} {c['silhouette_iou']:7.3f} {est:8.3f}" if c
                 else f"{'no valid solid':>36s}") + (f"  {note}" if note else ""))
    n = max(len(rows), 1)
    mean = sum(r["estimate"] for r in rows.values()) / n
    print(f"MEAN local estimate (real facts, {len(rows)} parts, missing = 0): {mean:.4f}")
    for source in ("exact", "body", "hull", "box", "?"):
        if source in by_source:
            v = by_source[source]
            print(f"  {source:6s} {len(v):2d} parts, mean {sum(v) / len(v):.4f}")
    result = {"outputs": str(outputs), "n_cases": len(rows), "mean_estimate": mean, "mean_self_score": sum(r.get("self_score", 0.0) for r in rows.values()) / n, "mean_score": None,
              "by_source": {s: {"n": len(v), "mean_estimate": sum(v) / len(v)} for s, v in by_source.items()}, "cases": rows}
    if a.tag:
        (ROOT / "results" / f"{time.strftime('%m%d-%H%M')}-{a.tag}.json").write_text(json.dumps(result, indent=1))
