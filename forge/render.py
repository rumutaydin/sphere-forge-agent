"""Dependency-light renderer: shaded point splats with a z-buffer.

Good enough for a vision model to judge shape, and it never needs a GPU or a
display. Views are orthographic so dimensions can be read off them.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .geometry import sample_surface

# name -> (direction the camera looks along, camera up vector)
VIEWS = {
    "iso": ((-1.0, 1.0, -0.8), (0, 0, 1)),
    "front (looking +Y)": ((0, 1, 0), (0, 0, 1)),
    "top (looking -Z)": ((0, 0, -1), (0, 1, 0)),
    "right (looking -X)": ((-1, 0, 0), (0, 0, 1)),
}
LIGHT = np.array([0.35, -0.5, 0.8])


def _basis(look, up):
    f = np.asarray(look, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, np.asarray(up, float))
    r /= np.linalg.norm(r)
    return r, np.cross(r, f), f


def render_view(mesh, look, up, size: int = 320, n_pts: int = 250_000, color=(110, 150, 215)):
    pts, nrm = sample_surface(mesh, n_pts, seed=0)
    r, u, f = _basis(look, up)
    centre = mesh.bounds.mean(axis=0)
    radius = float(np.linalg.norm(mesh.extents)) / 2 or 1.0
    rel = pts - centre
    px = ((rel @ r) / radius * 0.46 + 0.5) * (size - 1)
    py = (0.5 - (rel @ u) / radius * 0.46) * (size - 1)
    depth = rel @ f

    # Two-sided lambert shading plus a little depth cue.
    shade = 0.3 + 0.7 * np.abs(nrm @ (LIGHT / np.linalg.norm(LIGHT)))
    shade *= 1.0 - 0.25 * (depth - depth.min()) / (np.ptp(depth) or 1.0)

    # 2x2 splats so neighbouring samples overlap and far surfaces do not show through.
    off = np.array([(0, 0), (1, 0), (0, 1), (1, 1)])
    xi = np.clip(np.floor(px).astype(int)[:, None] + off[:, 0], 0, size - 1).ravel()
    yi = np.clip(np.floor(py).astype(int)[:, None] + off[:, 1], 0, size - 1).ravel()
    depth4, shade4 = np.repeat(depth, 4), np.repeat(shade, 4)
    order = np.argsort(-depth4)  # far first, so the nearest point is written last
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    img[yi[order], xi[order]] = (shade4[order, None] * np.array(color)).astype(np.uint8)
    return img


def render_grid(mesh, out_path: str | Path, size: int = 320, color=(110, 150, 215)) -> Path:
    """2x2 contact sheet (iso, front, top, right) with labels and bbox size."""
    tiles = []
    for name, (look, up) in VIEWS.items():
        tile = Image.fromarray(render_view(mesh, look, up, size, color=color))
        ImageDraw.Draw(tile).text((6, 4), name, fill=(0, 0, 0))
        tiles.append(tile)
    sheet = Image.new("RGB", (size * 2, size * 2 + 18), "white")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 2) * size, (i // 2) * size))
    ex = mesh.extents
    ImageDraw.Draw(sheet).text(
        (6, size * 2 + 3), f"bbox size  X {ex[0]:.2f}   Y {ex[1]:.2f}   Z {ex[2]:.2f}", fill=(0, 0, 0)
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
