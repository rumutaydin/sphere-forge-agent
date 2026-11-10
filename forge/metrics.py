"""Geometric similarity between a predicted part and a target part.

We do not yet know which metric or which alignment the organisers use, so every
metric is reported under several alignment modes. On the day, pick the mode
that reproduces the organisers' numbers and optimise against that one.

Alignment modes
  raw     compare in absolute coordinates (position, orientation, size all count)
  center  move both bbox centres to the origin (position is free)
  unit    center + scale each to unit longest side (position and size are free)
  rot24   unit + best of the 24 axis-aligned rotations (also orientation-free)
  icp     center + rigid ICP fit (position and small rotations are free)
"""
from __future__ import annotations

import itertools

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .geometry import load_mesh, sample_surface, voxelize

MODES = ("raw", "center", "unit", "rot24", "icp")


def _rotations24() -> list[np.ndarray]:
    mats = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            m[range(3), perm] = signs
            if np.linalg.det(m) > 0:
                mats.append(m)
    return mats


ROT24 = _rotations24()
DENSE = 8  # dense-sample multiplier for nearest-neighbour queries


def _icp(pred, gt, iters: int = 40) -> np.ndarray:
    """Rigid point-to-point ICP (Kabsch updates). Returns a 4x4 transform for pred."""
    src, _ = sample_surface(pred, 4000, seed=0)
    dst, _ = sample_surface(gt, 60_000, seed=1)
    tree = cKDTree(dst)
    total = np.eye(4)
    cur = src.copy()
    for _ in range(iters):
        nn = dst[tree.query(cur)[1]]
        mc, mn = cur.mean(axis=0), nn.mean(axis=0)
        u, _, vt = np.linalg.svd((cur - mc).T @ (nn - mn))
        d = np.sign(np.linalg.det(vt.T @ u.T))
        rot = vt.T @ np.diag([1, 1, d]) @ u.T
        step = np.eye(4)
        step[:3, :3] = rot
        step[:3, 3] = mn - rot @ mc
        cur = cur @ rot.T + step[:3, 3]
        total = step @ total
        if np.allclose(step, np.eye(4), atol=1e-7):
            break
    return total


def _transformed(mesh: trimesh.Trimesh, rot=None, shift=None, scale=1.0) -> trimesh.Trimesh:
    v = np.asarray(mesh.vertices, dtype=float)
    if shift is not None:
        v = v + shift
    v = v * scale
    if rot is not None:
        v = v @ np.asarray(rot).T
    return trimesh.Trimesh(vertices=v, faces=mesh.faces, process=False)


def _center(mesh):
    return _transformed(mesh, shift=-mesh.bounds.mean(axis=0))


def _unit(mesh):
    ext = float(mesh.extents.max()) or 1.0
    return _transformed(mesh, shift=-mesh.bounds.mean(axis=0), scale=1.0 / ext)


def iou(pred: trimesh.Trimesh, gt: trimesh.Trimesh, res: int = 64) -> float:
    """Volumetric IoU on a shared grid covering both shapes."""
    lo = np.minimum(pred.bounds[0], gt.bounds[0])
    hi = np.maximum(pred.bounds[1], gt.bounds[1])
    pitch = float((hi - lo).max()) / res or 1.0
    shape = np.maximum(np.ceil((hi - lo) / pitch).astype(int), 1)
    a = voxelize(pred, lo, pitch, shape)
    b = voxelize(gt, lo, pitch, shape)
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def surface_metrics(pred, gt, n_pts: int = 8192, f1_tol: float = 0.01) -> dict:
    """Chamfer / F1 / Hausdorff-95, all in units of the target's bbox diagonal."""
    diag = float(np.linalg.norm(gt.extents)) or 1.0
    # Query points against a much denser sample of the other surface, so that
    # identical shapes score ~0 instead of the point-spacing noise floor.
    p, _ = sample_surface(pred, n_pts, seed=0)
    g, _ = sample_surface(gt, n_pts, seed=1)
    p_dense, _ = sample_surface(pred, n_pts * DENSE, seed=2)
    g_dense, _ = sample_surface(gt, n_pts * DENSE, seed=3)
    d_pg = cKDTree(g_dense).query(p)[0] / diag  # pred -> target: penalises extra material
    d_gp = cKDTree(p_dense).query(g)[0] / diag  # target -> pred: penalises missing material
    precision = float((d_pg < f1_tol).mean())
    recall = float((d_gp < f1_tol).mean())
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "chamfer": float(d_pg.mean() + d_gp.mean()),
        "f1": f1,
        "precision": precision,
        "recall": recall,
        "hausdorff95": float(max(np.percentile(d_pg, 95), np.percentile(d_gp, 95))),
    }


def align(pred, gt, mode: str, res: int = 64):
    if mode == "raw":
        return pred, gt
    if mode == "center":
        return _center(pred), _center(gt)
    if mode == "unit":
        return _unit(pred), _unit(gt)
    if mode == "rot24":
        p, g = _unit(pred), _unit(gt)
        coarse = min(res, 32)
        best = max(ROT24, key=lambda r: iou(_transformed(p, rot=r), g, coarse))
        return _center(_transformed(p, rot=best)), g
    if mode == "icp":
        p, g = _center(pred), _center(gt)
        out = p.copy()
        out.apply_transform(_icp(p, g))
        return out, g
    raise ValueError(f"unknown mode {mode}")


def compare(pred, gt, modes=MODES, res: int = 64, n_pts: int = 8192) -> dict:
    """Full report: {mode: {iou, chamfer, f1, ...}} plus pose-independent ratios."""
    if not isinstance(pred, trimesh.Trimesh):
        pred = load_mesh(pred)
    if not isinstance(gt, trimesh.Trimesh):
        gt = load_mesh(gt)
    report: dict = {}
    for mode in modes:
        p, g = align(pred, gt, mode, res)
        report[mode] = {"iou": iou(p, g, res), **surface_metrics(p, g, n_pts)}
    gv = abs(float(gt.volume)) or 1.0
    report["ratios"] = {
        "volume": abs(float(pred.volume)) / gv,
        "extents_sorted": (np.sort(pred.extents) / np.maximum(np.sort(gt.extents), 1e-12)).tolist(),
    }
    return report


def pairwise_iou(meshes, mode: str = "raw", res: int = 48) -> np.ndarray:
    """Symmetric IoU matrix between candidate shapes (used for consensus selection)."""
    n = len(meshes)
    out = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            p, g = align(meshes[i], meshes[j], mode, res)
            out[i, j] = out[j, i] = iou(p, g, res)
    return out
