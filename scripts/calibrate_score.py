"""Compare our reconstructed scorer with the medians on the organisers' kickoff slide.

    uv run python scripts/calibrate_score.py

Damages each reference part the way their slide describes and prints our median
next to theirs. If a row is far off, forge/score.py guessed a detail wrong.
"""
import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge.cases import BENCH, load_tasks  # noqa: E402
from forge.geometry import load_mesh  # noqa: E402
from forge.score import score  # noqa: E402

THEIRS = {"exact part, any pose": 1.00, "2 % too large": 0.90, "5 % too long": 0.88,
          "10 % too large": 0.62, "convex hull": 0.51, "bounding box": 0.32}


def variants(mesh: trimesh.Trimesh) -> dict[str, trimesh.Trimesh]:
    def scaled(f):
        m = mesh.copy()
        m.vertices = m.vertices * np.asarray(f)
        return m

    posed = mesh.copy()
    posed.apply_transform(trimesh.transformations.rotation_matrix(1.1, [0.3, 1.0, 0.5], point=[5, -3, 2]))
    posed.apply_translation([40, -25, 10])
    longest = np.eye(3)[int(np.argmax(mesh.extents))]
    box = trimesh.creation.box(extents=mesh.extents)
    box.apply_translation(mesh.bounds.mean(axis=0))
    return {"exact part, any pose": posed, "2 % too large": scaled([1.02] * 3),
            "5 % too long": scaled(1 + 0.05 * longest), "10 % too large": scaled([1.10] * 3),
            "convex hull": mesh.convex_hull, "bounding box": box}


if __name__ == "__main__":
    rows: dict[str, list[float]] = {k: [] for k in THEIRS}
    for task in load_tasks(BENCH / "cases"):
        target = load_mesh(task.answer)
        for name, bad in variants(target).items():
            rows[name].append(score(bad, target)["score"])
    print(f"{'damage':24s}{'ours':>8s}{'theirs':>8s}")
    for name, vals in rows.items():
        print(f"{name:24s}{np.median(vals):8.2f}{THEIRS[name]:8.2f}")
