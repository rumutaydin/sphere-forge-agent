"""What does a geometric similarity score actually punish?

Takes every benchmark target, damages it in a controlled way, and scores the
damaged copy against the original under each alignment mode. The table tells
you which mistakes are cheap and which are fatal for a given metric.
"""
from __future__ import annotations

import numpy as np
import trimesh

from .bench import cases
from .geometry import load_mesh
from .metrics import MODES, align, iou, surface_metrics


def _rot_z(deg: float) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(np.radians(deg), [0, 0, 1])


def perturbations(mesh: trimesh.Trimesh) -> dict[str, trimesh.Trimesh]:
    diag = float(np.linalg.norm(mesh.extents))
    centre = mesh.bounds.mean(axis=0)

    def moved(matrix):
        m = mesh.copy()
        m.apply_translation(-centre)
        m.apply_transform(matrix)
        m.apply_translation(centre)
        return m

    def scaled(factors):
        m = mesh.copy()
        m.apply_translation(-centre)
        m.vertices = m.vertices * np.asarray(factors)
        m.apply_translation(centre)
        return m

    shifted = mesh.copy()
    shifted.apply_translation([0.05 * diag, 0, 0])
    box = trimesh.creation.box(extents=mesh.extents)
    box.apply_translation(centre)
    return {
        "shift 5% of diagonal": shifted,
        "rotate 5 deg about Z": moved(_rot_z(5)),
        "rotate 90 deg about Z": moved(_rot_z(90)),
        "wrong up axis (Y up)": moved(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])),
        "all dims +5%": scaled([1.05] * 3),
        "all dims +20%": scaled([1.2] * 3),
        "one dim +10%": scaled([1.1, 1, 1]),
        "one dim +30%": scaled([1.3, 1, 1]),
        "convex hull (no holes/pockets)": mesh.convex_hull,
        "bounding box only": box,
    }


def run(res: int = 48, n_pts: int = 4096, only: list[str] | None = None) -> dict:
    table: dict[str, dict[str, list[float]]] = {}
    for case in cases(only):
        gt = load_mesh(case.target)
        for name, bad in perturbations(gt).items():
            row = table.setdefault(name, {})
            for mode in MODES:
                p, g = align(bad, gt, mode, res)
                row.setdefault(f"iou/{mode}", []).append(iou(p, g, res))
                if mode in ("raw", "unit"):
                    row.setdefault(f"f1/{mode}", []).append(surface_metrics(p, g, n_pts)["f1"])
    return {name: {k: float(np.mean(v)) for k, v in row.items()} for name, row in table.items()}


def format_table(result: dict) -> str:
    cols = list(next(iter(result.values())))
    head = f"{'damage':32s}" + "".join(f"{c:>11s}" for c in cols)
    lines = [head, "-" * len(head)]
    for name, row in result.items():
        lines.append(f"{name:32s}" + "".join(f"{row[c]:11.2f}" for c in cols))
    return "\n".join(lines)
