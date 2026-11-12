"""File one approach's nine STEP parts with their local numbers, ready to submit later.

    uv run python scripts/save_approach.py <name> <outputs_dir> ["one line: what this is"]
    uv run python scripts/save_approach.py --stage <name>      copy that approach into artifacts/outputs

Writes bench/approaches/<name>/test_case_<n>.stp and scores.json. The numbers are local:
dimensions and holes are exact (facts.json); "estimate" is the rough leaderboard estimate
from the silhouettes and the volume (forge.compile.estimate). After a submission, add
"leaderboard" to scores.json by hand.
"""
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(args):
    step, name = args
    import cadquery as cq

    from forge.cases import load_tasks
    from forge.compile import measure_body

    task = load_tasks(ROOT / "artifacts/inputs", [name + "$"])[0]
    shape = cq.importers.importStep(step).val()
    solids = shape.Solids()
    m = measure_body(cq.Workplane("XY").newObject([solids[0] if len(solids) == 1 else shape]), task)
    if m is None:
        return name, {"valid": False, "estimate": 0.0}
    c = m["check"]
    return name, {"valid": True, "estimate": round(c["estimate"], 4), "self_score": round(c["self_score"], 4),
                  "dimensions": round(c["dimensions"], 3), "holes": round(c["holes"], 3),
                  "volume_ratio": round(c["volume_ratio"], 3), "area_ratio": round(c["area_ratio"], 3),
                  "silhouette_iou": round(c["silhouette_iou"], 4)}


if __name__ == "__main__":
    if sys.argv[1] == "--stage":
        src = ROOT / "bench/approaches" / sys.argv[2]
        for f in sorted(src.glob("*.stp")):
            shutil.copyfile(f, ROOT / "artifacts/outputs" / f.name)
        print(f"artifacts/outputs now holds approach {sys.argv[2]}")
        sys.exit(0)
    name, src = sys.argv[1], Path(sys.argv[2])
    what = sys.argv[3] if len(sys.argv) > 3 else ""
    dst = ROOT / "bench/approaches" / name
    dst.mkdir(parents=True, exist_ok=True)
    files = sorted(src.glob("test_case_*.stp"))
    for f in files:
        shutil.copyfile(f, dst / f.name)
    with ProcessPoolExecutor(5) as pool:
        cases = dict(pool.map(check, [(str(dst / f.name), f.stem) for f in files]))
    n = max(len(cases), 1)
    out = {"what": what, "n_cases": len(cases), "leaderboard": None,
           "mean_estimate": round(sum(c["estimate"] for c in cases.values()) / n, 4),
           "holes_right": sum(1 for c in cases.values() if c.get("holes") == 1.0),
           "cases": dict(sorted(cases.items()))}
    (dst / "scores.json").write_text(json.dumps(out, indent=1))
    print(f"{name}: mean estimate {out['mean_estimate']:.3f}, holes right on {out['holes_right']} of {len(cases)}")
    for k, c in out["cases"].items():
        print(f"  {k}: est {c['estimate']:.3f} dims {c.get('dimensions')} holes {c.get('holes')} vol x{c.get('volume_ratio')} sil {c.get('silhouette_iou')}")
