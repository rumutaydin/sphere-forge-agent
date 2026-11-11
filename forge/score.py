"""Our reconstruction of the organisers' scorer.

    score = 0.30 * volume + 0.30 * surface + 0.20 * dimensions + 0.20 * holes

Their scorer is not published. This follows the kickoff slides:
  - rigid alignment first (rotation + translation; no scaling, no mirroring)
  - volume:     volumetric IoU
  - surface:    surface match "checked at 0.5-10 % of part size"
  - dimensions: "2 % off loses 10 %; 20 % off loses all"  ->  1 - error / 0.20 per axis
  - holes:      through-holes "counted exactly from CAD topology"  ->  genus
Details we had to guess are marked GUESS. scripts/calibrate_score.py compares the
result with the medians on their slide; trust the leaderboard over this file.
"""
from __future__ import annotations

import itertools

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .geometry import genus, load_mesh, sample_surface, voxelize

WEIGHTS = {"volume": 0.30, "surface": 0.30, "dimensions": 0.20, "holes": 0.20}
SURFACE_TOLERANCES = (0.005, 0.01, 0.02, 0.05, 0.10)  # GUESS: which steps between 0.5 % and 10 %


def _proper_rotations() -> list[np.ndarray]:
    mats = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            m[range(3), perm] = signs
            if np.linalg.det(m) > 0:  # determinant +1 only: mirroring is not allowed
                mats.append(m)
    return mats


ROT24 = _proper_rotations()


def _icp(src: np.ndarray, tree: cKDTree, dst: np.ndarray, iters: int):
    """Point-to-point ICP with Kabsch updates. Returns (4x4 transform, mean residual)."""
    total, cur = np.eye(4), src.copy()
    for _ in range(iters):
        nn = dst[tree.query(cur)[1]]
        mc, mn = cur.mean(axis=0), nn.mean(axis=0)
        u, _, vt = np.linalg.svd((cur - mc).T @ (nn - mn))
        d = np.sign(np.linalg.det(vt.T @ u.T))
        rot = vt.T @ np.diag([1, 1, d]) @ u.T
        step = np.eye(4)
        step[:3, :3], step[:3, 3] = rot, mn - rot @ mc
        cur = cur @ rot.T + step[:3, 3]
        total = step @ total
    return total, float(tree.query(cur)[0].mean())


def align(pred: trimesh.Trimesh, target: trimesh.Trimesh) -> trimesh.Trimesh:
    """Best rigid fit of pred onto target: 24 axis-aligned starts, each refined by ICP."""
    src, _ = sample_surface(pred, 1500, seed=0)
    dst, _ = sample_surface(target, 30_000, seed=1)
    tree = cKDTree(dst)
    centre_s, centre_d = src.mean(axis=0), dst.mean(axis=0)
    best, best_err = np.eye(4), np.inf
    for rot in ROT24:
        start = np.eye(4)
        start[:3, :3], start[:3, 3] = rot, centre_d - rot @ centre_s
        fit, err = _icp(src @ rot.T + start[:3, 3], tree, dst, iters=12)
        if err < best_err:
            best, best_err = fit @ start, err
    src_fine, _ = sample_surface(pred, 5000, seed=2)
    moved = src_fine @ best[:3, :3].T + best[:3, 3]
    fit, _ = _icp(moved, tree, dst, iters=30)
    out = pred.copy()
    out.apply_transform(fit @ best)
    return out


def volume_iou(pred: trimesh.Trimesh, target: trimesh.Trimesh, res: int = 64) -> float:
    lo = np.minimum(pred.bounds[0], target.bounds[0])
    hi = np.maximum(pred.bounds[1], target.bounds[1])
    pitch = float((hi - lo).max()) / res or 1.0
    shape = np.maximum(np.ceil((hi - lo) / pitch).astype(int), 1)
    a, b = voxelize(pred, lo, pitch, shape), voxelize(target, lo, pitch, shape)
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def surface_match(pred, target, n_pts: int = 8192) -> float:
    """Mean F-score over the tolerances, each a fraction of the target's bbox diagonal."""
    size = float(np.linalg.norm(target.extents)) or 1.0  # GUESS: "part size" = bbox diagonal
    p, _ = sample_surface(pred, n_pts, seed=0)
    t, _ = sample_surface(target, n_pts, seed=1)
    p_dense, _ = sample_surface(pred, n_pts * 8, seed=2)
    t_dense, _ = sample_surface(target, n_pts * 8, seed=3)
    d_pt = cKDTree(t_dense).query(p)[0] / size
    d_tp = cKDTree(p_dense).query(t)[0] / size
    scores = []
    for tol in SURFACE_TOLERANCES:
        precision, recall = float((d_pt < tol).mean()), float((d_tp < tol).mean())
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return float(np.mean(scores))


def dimension_score(extents, target_extents) -> float:
    """Per axis 1 - relative error / 0.20, floored at 0, averaged. Axes matched by size."""
    a, b = np.sort(np.asarray(extents, float)), np.sort(np.asarray(target_extents, float))
    err = np.abs(a - b) / np.maximum(b, 1e-9)
    return float(np.clip(1.0 - err / 0.20, 0.0, 1.0).mean())


def hole_score(n: int, n_target: int) -> float:
    """GUESS: partial credit min/max (their slide shows "6 of 10 holes" on a 0.56 part)."""
    if n < 0 or n_target < 0:
        return 0.0
    if n == n_target:
        return 1.0
    return min(n, n_target) / max(n, n_target)


def score(pred, target, res: int = 64) -> dict:
    """Full score of a predicted STEP file (or mesh) against the target's."""
    if not isinstance(pred, trimesh.Trimesh):
        pred = load_mesh(pred)
    if not isinstance(target, trimesh.Trimesh):
        target = load_mesh(target)
    holes = hole_score(genus(pred), genus(target))
    moved = align(pred, target)
    parts = {
        "volume": volume_iou(moved, target, res),
        "surface": surface_match(moved, target),
        "dimensions": dimension_score(moved.extents, target.extents),
        "holes": holes,
    }
    return {"score": sum(WEIGHTS[k] * v for k, v in parts.items()), **parts}


def pairwise_iou(meshes, res: int = 48) -> np.ndarray:
    """IoU between candidates built in the same frame (no alignment needed)."""
    n = len(meshes)
    out = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            out[i, j] = out[j, i] = volume_iou(meshes[i], meshes[j], res)
    return out
