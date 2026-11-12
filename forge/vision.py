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

MARGIN_PX = 19.5          # fitted on the practice views (1024 px): the bounding box is fitted into 985 px
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
        margin = MARGIN_PX * image_px / 1024
        self.scale = (image_px - 2 * margin) / max(self.w_mm, self.h_mm)   # px per mm
        self.mid = image_px / 2          # pixel-edge coordinates: pixel i covers [i, i + 1)

    def to_px(self, pts_mm: np.ndarray) -> np.ndarray:
        """(n, 3) mm in the facts frame -> (n, 2) pixel (x, y), pixel-edge coordinates."""
        x = self.mid + ((pts_mm @ self.r) - self.c_r) * self.scale
        y = self.mid - ((pts_mm @ self.u) - self.c_u) * self.scale
        return np.stack([x, y], axis=1)

    def plane_mm(self, xy_px: np.ndarray) -> np.ndarray:
        """(n, 2) pixel-centre coordinates (pixel i is at i) -> (n, 2) coordinates (along r, along u) in mm."""
        a = (xy_px[:, 0] + 0.5 - self.mid) / self.scale + self.c_r
        b = (self.mid - xy_px[:, 1] - 0.5) / self.scale + self.c_u
        return np.stack([a, b], axis=1)


def box_size(facts: dict) -> np.ndarray:
    b = facts["bounding_box_mm"]
    return np.array([b["x"], b["y"], b["z"]], float)


def image_mask(path: str | Path) -> np.ndarray:
    """Part against the white background. Tan fill and black strokes are both part. The outline
    stroke lies about one pixel outside the true edge, so the mask is eroded by one pixel
    (measured on a part we know exactly: IoU 0.985 without, 0.997 with)."""
    from scipy import ndimage

    rgb = np.asarray(Image.open(path).convert("RGB"))
    return ndimage.binary_erosion(rgb.min(axis=2) < 235, iterations=1)


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


# --- edges inside the outline ---------------------------------------------------------------
#
# A silhouette says nothing about a groove, a pocket or a step that lies inside the outline.
# The views do: every sharp edge and every occluding contour is drawn as a black stroke. We
# draw the same lines for our own part (where the surface normal turns sharply or the depth
# jumps) and compare the two line drawings.

STROKE_MAX = 70        # a drawn stroke: brightest channel below this (darkest shaded face is about 83)


def target_strokes(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).max(axis=2) < STROKE_MAX


def zbuffer(tri_px: np.ndarray, tri_depth: np.ndarray, size: int):
    """Orthographic depth buffer. tri_px: (n, 3, 2) pixel-edge coordinates of each triangle's
    corners, tri_depth: (n, 3) their depth along the view direction. Returns (depth, face index)
    per pixel; face index is -1 where nothing is drawn. Exact per pixel centre, all in numpy."""
    lo = np.ceil(tri_px.min(axis=1) - 0.5).astype(np.int64)
    hi = np.floor(tri_px.max(axis=1) - 0.5).astype(np.int64)
    lo, hi = np.maximum(lo, 0), np.minimum(hi, size - 1)
    span = np.maximum(hi - lo + 1, 0)
    count = span[:, 0] * span[:, 1]
    order = np.flatnonzero(count > 0)
    zbuf = np.full(size * size, np.inf)
    hits = []
    start, budget = 0, 3_000_000
    while start < len(order):
        csum = np.cumsum(count[order[start:]])
        stop = start + max(1, int(np.searchsorted(csum, budget, side="right")))
        sel = order[start:stop]
        start = stop
        c = count[sel]
        tid = np.repeat(sel, c)
        local = np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)
        ix = lo[tid, 0] + local // span[tid, 1]
        iy = lo[tid, 1] + local % span[tid, 1]
        x, y = ix + 0.5, iy + 0.5
        a, b, cc = tri_px[tid, 0], tri_px[tid, 1], tri_px[tid, 2]
        det = (b[:, 1] - cc[:, 1]) * (a[:, 0] - cc[:, 0]) + (cc[:, 0] - b[:, 0]) * (a[:, 1] - cc[:, 1])
        ok = np.abs(det) > 1e-12
        det = np.where(ok, det, 1.0)
        w0 = ((b[:, 1] - cc[:, 1]) * (x - cc[:, 0]) + (cc[:, 0] - b[:, 0]) * (y - cc[:, 1])) / det
        w1 = ((cc[:, 1] - a[:, 1]) * (x - cc[:, 0]) + (a[:, 0] - cc[:, 0]) * (y - cc[:, 1])) / det
        w2 = 1.0 - w0 - w1
        hit = ok & (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        z = (w0 * tri_depth[tid, 0] + w1 * tri_depth[tid, 1] + w2 * tri_depth[tid, 2])[hit]
        pix = (iy[hit] * size + ix[hit])
        np.minimum.at(zbuf, pix, z)
        hits.append((pix, z, tid[hit]))
    fid = np.full(size * size, -1, np.int64)
    for pix, z, tid in hits:
        front = z <= zbuf[pix] + 1e-9
        fid[pix[front]] = tid[front]
    return zbuf.reshape(size, size), fid.reshape(size, size)


def render_edges(mesh, cam: Camera, origin=None, crease_deg: float = 28.0, depth_jump: float = 0.012):
    """(edges, mask) of a mesh in `cam`'s pixels: an edge is where neighbouring pixels differ in
    surface normal by more than `crease_deg`, or in depth by more than `depth_jump` of the part
    size, or where the part meets the background."""
    origin = mesh.bounds[0] if origin is None else np.asarray(origin, float)
    tri = (np.asarray(mesh.vertices) - origin)[np.asarray(mesh.faces)]
    normals = np.asarray(mesh.face_normals)
    dep, fid = zbuffer(cam.to_px(tri.reshape(-1, 3)).reshape(-1, 3, 2), tri @ cam.f, cam.px)
    mask = fid >= 0
    nrm = np.zeros(mask.shape + (3,))
    nrm[mask] = normals[fid[mask]]
    dep = np.where(mask, dep, 0.0)
    cos_min = float(np.cos(np.radians(crease_deg)))
    jump = depth_jump * float(np.linalg.norm(mesh.extents))
    edges = np.zeros(mask.shape, bool)
    for ax in (0, 1):
        a = [slice(None), slice(None)]
        b = [slice(None), slice(None)]
        a[ax], b[ax] = slice(1, None), slice(None, -1)
        a, b = tuple(a), tuple(b)
        both = mask[a] & mask[b]
        dot = (nrm[a] * nrm[b]).sum(axis=2)
        e = (mask[a] ^ mask[b]) | (both & ((dot < cos_min) | (np.abs(dep[a] - dep[b]) > jump)))
        edges[a] |= e
    return edges, mask


def edge_score(step_or_mesh, task, tol_px: float = 3.0, inside_px: int = 5, views=None) -> dict:
    """How well the line drawing of our part matches the strokes of the views.

    Per view an F-score: the share of the target's strokes that have one of our edges within
    `tol_px`, and the share of our edges that have a target stroke within `tol_px`. "inner"
    counts only lines at least `inside_px` inside the outline, which is the part a silhouette
    cannot check. Returns {"all": mean, "inner": mean, "per_view": {stem: (all, inner)}}."""
    from scipy import ndimage

    from .geometry import load_mesh

    mesh = step_or_mesh if hasattr(step_or_mesh, "faces") else load_mesh(step_or_mesh)
    size = box_size(task.facts)
    per = {}
    for view in task.views:
        if view.stem not in VIEWS or (views is not None and view.stem not in views):
            continue
        target = target_strokes(view)
        cam = Camera(view.stem, size, target.shape[0])
        ours, our_mask = render_edges(mesh, cam)
        t_mask = image_mask(view)
        d_t = ndimage.distance_transform_edt(~target)
        d_o = ndimage.distance_transform_edt(~ours)

        def f(sel_t, sel_o):
            n_t, n_o = sel_t.sum(), sel_o.sum()
            if n_t == 0 and n_o == 0:
                return 1.0
            recall = float((d_o[sel_t] <= tol_px).mean()) if n_t else 1.0
            precision = float((d_t[sel_o] <= tol_px).mean()) if n_o else 1.0
            return 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        in_t = ndimage.binary_erosion(t_mask, iterations=inside_px)
        in_o = ndimage.binary_erosion(our_mask, iterations=inside_px)
        per[view.stem] = (f(target, ours), f(target & in_t, ours & in_o))
    if not per:
        return {"all": 0.0, "inner": 0.0, "per_view": {}}
    return {"all": float(np.mean([v[0] for v in per.values()])),
            "inner": float(np.mean([v[1] for v in per.values()])), "per_view": per}
