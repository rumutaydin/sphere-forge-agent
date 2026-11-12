"""TRACK B. What the eight views say about the shape, measured, with no model.

The organisers render every view orthographically, fit the projected *bounding box* of
the part into the image with a fixed margin, and centre it. The bounding box is in
facts.json, so every pixel of every view (the two isometric ones included) maps to
millimetres in the facts frame (origin at the minimum corner of the bounding box).

    target_masks(task)            the part's silhouette in each view
    project_mask(mesh, cam, ...)  our part's silhouette in the same pixels
    shape_score(step, task)       per-view IoU of the two, and the mean
    outlines_mm(task, stem)       silhouette polygons in mm, for building solids
    diff_sheet(step, task, path)  red = missing, blue = extra, eight views on one sheet
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .render import VIEWS, _basis

MARGIN_PX = 19.5          # measured on the practice views: the box spans pixels 19..1004 of 1024
AXIS_VIEWS = ("view_0_front", "view_2_left", "view_4_top")   # one of each mirror pair


class Camera:
    """Pixel <-> mm for one view of a part whose bounding box is `size` (mm, min corner at 0)."""

    def __init__(self, stem: str, size, image_px: int = 1024):
        look, up = VIEWS[stem]
        self.stem, self.px = stem, image_px
        self.r, self.u, self.f = _basis(look, up)
        size = np.asarray(size, float)
        corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])])
        a, b = corners @ self.r, corners @ self.u
        self.c_r, self.c_u = (a.min() + a.max()) / 2, (b.min() + b.max()) / 2
        self.w_mm, self.h_mm = np.ptp(a), np.ptp(b)
        self.scale = (image_px - 1 - 2 * MARGIN_PX) / max(self.w_mm, self.h_mm)   # px per mm
        self.mid = (image_px - 1) / 2

    def to_px(self, pts_mm: np.ndarray) -> np.ndarray:
        """(n, 3) mm in the facts frame -> (n, 2) pixel (x, y)."""
        x = self.mid + ((pts_mm @ self.r) - self.c_r) * self.scale
        y = self.mid - ((pts_mm @ self.u) - self.c_u) * self.scale
        return np.stack([x, y], axis=1)

    def plane_mm(self, xy_px: np.ndarray) -> np.ndarray:
        """(n, 2) pixels -> (n, 2) coordinates (along r, along u) in mm."""
        a = (xy_px[:, 0] - self.mid) / self.scale + self.c_r
        b = (self.mid - xy_px[:, 1]) / self.scale + self.c_u
        return np.stack([a, b], axis=1)


def box_size(facts: dict) -> np.ndarray:
    b = facts["bounding_box_mm"]
    return np.array([b["x"], b["y"], b["z"]], float)


def image_mask(path: str | Path) -> np.ndarray:
    """Part against the white background. Tan fill and black strokes are both part."""
    rgb = np.asarray(Image.open(path).convert("RGB"))
    return rgb.min(axis=2) < 235


def target_masks(task) -> dict[str, np.ndarray]:
    return {v.stem: image_mask(v) for v in task.views if v.stem in VIEWS}


def project_mask(mesh, cam: Camera, origin=None) -> np.ndarray:
    """Silhouette of a triangle mesh in `cam`'s pixels. `origin` is the mesh's bbox min corner
    (default: its own), which is placed on the facts frame's origin."""
    origin = mesh.bounds[0] if origin is None else np.asarray(origin, float)
    pts = cam.to_px(np.asarray(mesh.vertices) - origin)
    img = Image.new("1", (cam.px, cam.px), 0)
    draw = ImageDraw.Draw(img)
    tri = pts[np.asarray(mesh.faces)]
    for t in tri:
        draw.polygon([tuple(t[0]), tuple(t[1]), tuple(t[2])], fill=1, outline=1)
    return np.asarray(img, bool)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def shape_score(step_or_mesh, task, masks: dict | None = None) -> dict:
    """{"iou_per_view": {stem: iou}, "mean": float, "worst": stem}. Needs task.views and task.facts."""
    from .geometry import load_mesh

    mesh = step_or_mesh if hasattr(step_or_mesh, "faces") else load_mesh(step_or_mesh)
    masks = masks or target_masks(task)
    size = box_size(task.facts)
    per = {}
    for stem, target in masks.items():
        cam = Camera(stem, size, target.shape[0])
        per[stem] = iou(target, project_mask(mesh, cam))
    if not per:
        return {"iou_per_view": {}, "mean": 0.0, "worst": None}
    return {"iou_per_view": per, "mean": float(np.mean(list(per.values()))), "worst": min(per, key=per.get)}


# --- outlines in millimetres -------------------------------------------------------

def _simplify(poly: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker on a closed polygon (first point not repeated)."""
    n = len(poly)
    if n < 8:
        return poly
    far = int(np.argmax(((poly - poly[0]) ** 2).sum(axis=1)))
    keep = np.zeros(n, bool)
    keep[[0, far]] = True
    stack = [(0, far), (far, n)]
    while stack:
        i, j = stack.pop()
        a, b = poly[i], poly[j % n]
        if j - i < 2:
            continue
        seg = b - a
        length = np.hypot(*seg) or 1e-12
        mid = poly[i + 1:j]
        dist = np.abs(seg[0] * (mid[:, 1] - a[1]) - seg[1] * (mid[:, 0] - a[0])) / length
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return poly[keep]


def _area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def mask_polygons(mask: np.ndarray, tol_px: float = 0.6, min_area_px: float = 30.0) -> list[dict]:
    """Outer contours with their holes, in pixel coordinates: [{"outer": (n,2), "holes": [(m,2), ...]}]."""
    from contourpy import contour_generator

    z = np.pad(mask.astype(float), 1)
    gen = contour_generator(z=z, fill_type="OuterOffset")
    pts_list, offs_list = gen.filled(0.5, 2.0)
    out = []
    for pts, offs in zip(pts_list, offs_list):
        rings = [pts[offs[i]:offs[i + 1] - 1] - 1.0 for i in range(len(offs) - 1)]   # undo the pad; drop the closing point
        rings = [_simplify(r, tol_px) for r in rings]
        rings = [r for r in rings if len(r) >= 3 and abs(_area(r)) >= min_area_px]
        if not rings or abs(_area(rings[0])) < min_area_px:
            continue
        out.append({"outer": rings[0], "holes": rings[1:]})
    return sorted(out, key=lambda p: -abs(_area(p["outer"])))


def outlines_mm(task, stem: str, tol_px: float = 0.6, mask: np.ndarray | None = None):
    """(camera, polygons) for one view; polygon rings are (n, 2) arrays of (along r, along u) in mm."""
    view = next(v for v in task.views if v.stem == stem)
    mask = image_mask(view) if mask is None else mask
    cam = Camera(stem, box_size(task.facts), mask.shape[0])
    polys = []
    for p in mask_polygons(mask, tol_px):
        polys.append({"outer": cam.plane_mm(p["outer"]), "holes": [cam.plane_mm(h) for h in p["holes"]]})
    return cam, polys


# --- pictures for a critic ----------------------------------------------------------

def diff_sheet(step_or_mesh, task, out_path: str | Path, tile: int = 384) -> Path:
    """Eight views on one sheet: grey = agrees, red = target has material we lack, blue = we have extra."""
    from .geometry import load_mesh

    mesh = step_or_mesh if hasattr(step_or_mesh, "faces") else load_mesh(step_or_mesh)
    size = box_size(task.facts)
    sheet = Image.new("RGB", (tile * 4, tile * 2), "white")
    for i, (stem, target) in enumerate(target_masks(task).items()):
        ours = project_mask(mesh, Camera(stem, size, target.shape[0]))
        rgb = np.full(target.shape + (3,), 255, np.uint8)
        rgb[target & ours] = (170, 170, 170)
        rgb[target & ~ours] = (220, 40, 40)
        rgb[~target & ours] = (40, 80, 220)
        im = Image.fromarray(rgb).resize((tile, tile))
        ImageDraw.Draw(im).text((6, 4), f"{stem.split('_', 2)[2]}  IoU {iou(target, ours):.2f}", fill=(0, 0, 0))
        sheet.paste(im, ((i % 4) * tile, (i // 4) * tile))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
