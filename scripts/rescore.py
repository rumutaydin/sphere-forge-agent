"""Score the chosen part of compile runs against the REAL facts.json, whatever facts built them.

    uv run python scripts/rescore.py runs/p0-real runs/p0-brief [--inputs artifacts/inputs]

For comparing a run made with FORGE_IGNORE_FACTS=1 (facts from the brief) with a normal run:
both are measured with the same real facts and views. Columns per run: chosen source, dimensions,
holes, volume ratio, estimate (the rough leaderboard estimate; a stand-in, not a prediction).
A run folder holds <task>/compile.json (scripts/compile_all.py) or <task>.stp files.
`real_tasks` and `score_step` are also used by scripts/score_extended.py.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def chosen(run: Path, name: str):
    try:
        row = json.loads((run / name / "compile.json").read_text())[0]
        return row["name"], Path(row["step"])
    except Exception:
        stp = run / f"{name}.stp"
        return ("file", stp) if stp.is_file() else (None, None)


def real_tasks(inputs, only=None):
    """The tasks of `inputs` with the facts of their facts.json, whatever the environment says."""
    os.environ.pop("FORGE_IGNORE_FACTS", None)
    os.environ.pop("FORGE_FACTS_DIR", None)
    from forge.cases import load_tasks

    return load_tasks(inputs, only)


def score_step(step, task) -> dict | None:
    """The check of one STEP file against a task's facts and views (dimensions, holes, volume_ratio,
    silhouette_iou, estimate, ...), or None if the file is missing or not one valid solid."""
    import cadquery as cq

    from forge.compile import measure_body

    if step is None or not Path(step).is_file():
        return None
    try:
        m = measure_body(cq.importers.importStep(str(step)), task)
    except Exception as exc:
        print(f"{task.name} {step}: {type(exc).__name__}: {exc}", flush=True)
        return None
    return m["check"] if m else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--inputs", default=str(ROOT / "artifacts/inputs"))
    a = ap.parse_args()
    tasks = real_tasks(a.inputs)
    table, means = [], {r: [] for r in a.runs}
    for task in tasks:
        cells = []
        for r in a.runs:
            name, step = chosen(Path(r), task.name)
            c = score_step(step, task)
            if c is None:
                cells.append(f"{'-':>22s}  no valid solid" + " " * 21)
                means[r].append(0.0)
                continue
            cells.append(f"{name[:22]:>22s} d {c['dimensions']:.2f} h {c['holes']:.2f} v x{c['volume_ratio']:.3f} est {c['estimate']:.3f}")
            means[r].append(c["estimate"])
        print(f"{task.name:12s} | " + " | ".join(cells), flush=True)
    print("mean estimate (real facts): " + "   ".join(f"{r}: {sum(v) / max(len(v), 1):.4f}" for r, v in means.items()))
