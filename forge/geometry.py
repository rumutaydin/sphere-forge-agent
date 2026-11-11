"""Mesh loading, surface sampling and solid voxelization.

The only file format in this project is STEP. Scoring and rendering work on a
triangle mesh tessellated from it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Tessellate a STEP file (.step or .stp). STEP is the only format we handle."""
    import cadquery as cq

    path = Path(path)
    if path.suffix.lower() not in (".step", ".stp"):
        raise ValueError(f"{path.name}: only STEP files are supported")

    vals = cq.importers.importStep(str(path)).vals()
    if not vals:
        raise ValueError(f"empty STEP file {path}")
    shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    return shape_to_mesh(shape)


def shape_to_mesh(shape, rel_tol: float = 5e-4) -> trimesh.Trimesh:
    """Tessellate a CadQuery/OCP shape. Tolerance is relative to the bbox diagonal."""
    bb = shape.BoundingBox()
    diag = float(np.linalg.norm([bb.xlen, bb.ylen, bb.zlen])) or 1.0
    verts, tris = shape.tessellate(diag * rel_tol, 0.2)
    mesh = trimesh.Trimesh(
        vertices=np.array([v.toTuple() for v in verts], dtype=float),
        faces=np.array(tris, dtype=np.int64),
        process=True,
    )
    if len(mesh.faces) == 0:
        raise ValueError("tessellation produced no triangles")
    return mesh


def genus(mesh: trimesh.Trimesh) -> int:
    """Number of through-holes, from the Euler characteristic of the closed surface.

    V - E + F = 2 * (bodies - genus). Needs a watertight mesh; returns -1 if it is not.
    """
    if not mesh.is_watertight:
        return -1
    return int(round(mesh.body_count - mesh.euler_number / 2))


def sample_surface(mesh: trimesh.Trimesh, n: int, seed: int = 0):
    """Area-uniform surface samples and their face normals."""
    pts, fid = trimesh.sample.sample_surface(mesh, n, seed=seed)
    return np.asarray(pts), np.asarray(mesh.face_normals[fid])


def voxelize(mesh: trimesh.Trimesh, origin, pitch: float, shape) -> np.ndarray:
    """Solid occupancy grid by parity counting along z-columns.

    Cell (i, j, k) has its centre at origin + (i+.5, j+.5, k+.5) * pitch. A cell
    is inside when an odd number of surface crossings lie below its centre in
    its column. Exact for watertight meshes, degrades gracefully otherwise.
    """
    nx, ny, nz = (int(s) for s in shape)
    origin = np.asarray(origin, dtype=float)
    # Tiny irrational-ish shift so columns never run exactly along mesh edges.
    ox = origin[0] + pitch * 3.7e-4
    oy = origin[1] + pitch * 7.1e-4
    toggle = np.zeros((nx, ny, nz + 1), dtype=np.int32)

    tris = np.asarray(mesh.triangles, dtype=float)
    lo = tris[:, :, :2].min(axis=1)
    hi = tris[:, :, :2].max(axis=1)
    i0 = np.ceil((lo - (ox, oy)) / pitch - 0.5).astype(np.int64)
    i1 = np.floor((hi - (ox, oy)) / pitch - 0.5).astype(np.int64)
    i0 = np.maximum(i0, 0)
    i1 = np.minimum(i1, (nx - 1, ny - 1))
    span = np.maximum(i1 - i0 + 1, 0)
    count = span[:, 0] * span[:, 1]

    order = np.flatnonzero(count > 0)
    budget, start = 4_000_000, 0
    while start < len(order):
        # Take triangles until the candidate (triangle, column) pairs fill the budget.
        csum = np.cumsum(count[order[start:]])
        stop = start + max(1, int(np.searchsorted(csum, budget, side="right")))
        sel = order[start:stop]
        start = stop

        c = count[sel]
        tid = np.repeat(sel, c)
        local = np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)
        ix = i0[tid, 0] + local // span[tid, 1]
        iy = i0[tid, 1] + local % span[tid, 1]
        px = ox + (ix + 0.5) * pitch
        py = oy + (iy + 0.5) * pitch

        a, b, cc = tris[tid, 0], tris[tid, 1], tris[tid, 2]
        det = (b[:, 1] - cc[:, 1]) * (a[:, 0] - cc[:, 0]) + (cc[:, 0] - b[:, 0]) * (a[:, 1] - cc[:, 1])
        ok = np.abs(det) > 1e-18
        det = np.where(ok, det, 1.0)
        w0 = ((b[:, 1] - cc[:, 1]) * (px - cc[:, 0]) + (cc[:, 0] - b[:, 0]) * (py - cc[:, 1])) / det
        w1 = ((cc[:, 1] - a[:, 1]) * (px - cc[:, 0]) + (a[:, 0] - cc[:, 0]) * (py - cc[:, 1])) / det
        w2 = 1.0 - w0 - w1
        hit = ok & (w0 >= 0) & (w1 >= 0) & (w2 >= 0)

        z = (w0 * a[:, 2] + w1 * b[:, 2] + w2 * cc[:, 2])[hit]
        k = np.clip(np.ceil((z - origin[2]) / pitch - 0.5).astype(np.int64), 0, nz)
        np.add.at(toggle, (ix[hit], iy[hit], k), 1)

    return (np.cumsum(toggle, axis=2)[:, :, :nz] % 2).astype(bool)
