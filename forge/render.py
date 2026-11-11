"""Renders a part in the organisers' eight orthographic views.

Same cameras and file names as the task inputs, so our render of view k can be
laid next to their view k. Point-splat rendering: no GPU, no display.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .geometry import sample_surface

# file stem -> (direction the camera looks along, camera up vector). From the task README:
# front looks along +Y (X right, Z up), top looks along -Z (X right, Y up), and so on.
VIEWS = {
    "view_0_front": ((0, 1, 0), (0, 0, 1)),
    "view_1_back": ((0, -1, 0), (0, 0, 1)),
    "view_2_left": ((1, 0, 0), (0, 0, 1)),
    "view_3_right": ((-1, 0, 0), (0, 0, 1)),
    "view_4_top": ((0, 0, -1), (0, 1, 0)),
    "view_5_bottom": ((0, 0, 1), (0, -1, 0)),
    "view_6_iso_front_right_top": ((-1, 1, -1), (0, 0, 1)),
    "view_7_iso_back_left_bottom": ((1, -1, 1), (0, 0, 1)),
}
LIGHT = np.array([0.35, -0.5, 0.8])
COLOR = (200, 150, 95)


def _basis(look, up):
    f = np.asarray(look, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, np.asarray(up, float))
    r /= np.linalg.norm(r)
    return r, np.cross(r, f), f


def render_view(mesh, look, up, size: int = 384, n_pts: int = 250_000, color=COLOR) -> np.ndarray:
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


def render_views(mesh, out_dir: str | Path, size: int = 1024) -> list[Path]:
    """Write the eight views as images/view_*.png-style files. Used to build our own cases."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for stem, (look, up) in VIEWS.items():
        path = out_dir / f"{stem}.png"
        Image.fromarray(render_view(mesh, look, up, size)).save(path)
        paths.append(path)
    return paths


def contact_sheet(images: list, labels: list[str], out_path: str | Path, tile: int = 384) -> Path:
    """4x2 sheet from eight images (paths or arrays), labelled. One image for the model to read."""
    sheet = Image.new("RGB", (tile * 4, tile * 2), "white")
    for i, (img, label) in enumerate(zip(images, labels)):
        im = Image.open(img).convert("RGB") if isinstance(img, (str, Path)) else Image.fromarray(img)
        im = im.resize((tile, tile))
        ImageDraw.Draw(im).text((6, 4), label, fill=(0, 0, 0))
        sheet.paste(im, ((i % 4) * tile, (i // 4) * tile))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def render_sheet(mesh, out_path: str | Path, tile: int = 384) -> Path:
    """Our part in all eight views on one sheet, in the same order as the task's views."""
    imgs = [render_view(mesh, look, up, tile) for look, up in VIEWS.values()]
    return contact_sheet(imgs, [s.split("_", 2)[2] for s in VIEWS], out_path, tile)
