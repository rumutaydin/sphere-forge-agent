"""TRACK B. Depth of flat faces from the views: what a silhouette cannot show.

A silhouette body is too full wherever the real part steps back: a recessed face, a pocket
floor, a lower level next to a boss. The views do show those faces. In an axis view the
outline strokes cut the part into regions; a region of flat colour is a plane facing the
camera. Its depth is found by sliding it along the view direction and projecting it into
the isometric view that sees the same faces: at the true depth the region lands on one
uniformly shaded patch and its border lands on drawn edges.

    face_depths(task, stem)   [{"mask", "depth", "uniform", "edge", "area_mm2"}] for one axis view
    carve_layers(body, task)  cut each confidently placed face down to its depth; returns (body, log)
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage

from .render import VIEWS
from .vision import Camera, box_size

ISO_FOR = {"view_0_front": "view_6_iso_front_right_top", "view_3_right": "view_6_iso_front_right_top",
           "view_4_top": "view_6_iso_front_right_top", "view_1_back": "view_7_iso_back_left_bottom",
           "view_2_left": "view_7_iso_back_left_bottom", "view_5_bottom": "view_7_iso_back_left_bottom"}
STROKE = 70      # a drawn edge: brightest channel below this (the darkest shaded face is about 83)


def _rgb(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(np.int16)


def face_depths(task, stem: str, min_frac: float = 0.0008, steps: int = 240) -> list[dict]:
    by = {v.stem: v for v in task.views}
    if stem not in by or ISO_FOR[stem] not in by:
        return []
    size = box_size(task.facts)
    img, iso = _rgb(by[stem]), _rgb(by[ISO_FOR[stem]])
    cam, icam = Camera(stem, size, img.shape[0]), Camera(ISO_FOR[stem], size, iso.shape[0])
    part = img.min(axis=2) < 235
    stroke = img.max(axis=2) < STROKE
    labels, n = ndimage.label(part & ~ndimage.binary_dilation(stroke, iterations=1))
    areas = np.bincount(labels.ravel())
    iso_part = iso.min(axis=2) < 235
    iso_stroke = iso.max(axis=2) < STROKE
    iso_edge = ndimage.binary_dilation(iso_stroke | (iso_part ^ ndimage.binary_erosion(iso_part)), iterations=2)
    corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]) @ cam.f
    near, far = corners.min(), corners.max()
    ts = np.linspace(0.0, far - near, steps)
    rng = np.random.default_rng(0)
    out = []
    for k in range(1, n + 1):
        if areas[k] < min_frac * part.sum():
            continue
        region = labels == k
        cols = img[region]
        if np.abs(cols - np.median(cols, axis=0)).max(axis=1).mean() > 8.0:
            continue                      # shaded: a curved or slanted face, not a plane facing the camera
        ys, xs = np.nonzero(ndimage.binary_erosion(region, iterations=2))
        if len(ys) < 30:
            continue
        pick = rng.choice(len(ys), min(len(ys), 3000), replace=False)
        inner = cam.plane_mm(np.stack([xs[pick], ys[pick]], axis=1).astype(float))
        by_, bx_ = np.nonzero(region & ~ndimage.binary_erosion(region))
        pick = rng.choice(len(by_), min(len(by_), 1500), replace=False)
        border = cam.plane_mm(np.stack([bx_[pick], by_[pick]], axis=1).astype(float))

        def project(ab, t):
            pts = ab[:, :1] * cam.r + ab[:, 1:] * cam.u + (near + t) * cam.f
            px = np.floor(icam.to_px(pts)).astype(int)
            ok = (px[:, 0] >= 0) & (px[:, 0] < iso.shape[1]) & (px[:, 1] >= 0) & (px[:, 1] < iso.shape[0])
            return px, ok

        uni, edg = np.zeros(steps), np.zeros(steps)
        for j, t in enumerate(ts):
            px, ok = project(inner, t)
            c = iso[px[ok, 1], px[ok, 0]]
            good = iso_part[px[ok, 1], px[ok, 0]] & ~iso_stroke[px[ok, 1], px[ok, 0]]
            if good.sum() < 0.3 * len(inner):
                continue
            med = np.median(c[good], axis=0)
            uni[j] = (np.abs(c - med).max(axis=1) <= 10)[good].sum() / len(inner)
            px, ok = project(border, t)
            edg[j] = iso_edge[px[ok, 1], px[ok, 0]].sum() / len(border)
        score = uni * (0.25 + 0.75 * edg)
        j = int(np.argmax(score))
        out.append({"mask": region, "depth": float(ts[j]), "uniform": float(uni[j]), "edge": float(edg[j]),
                    "score": float(score[j]), "score0": float(score[0]),
                    "area_mm2": float(areas[k] / cam.scale ** 2), "stem": stem})
    return out


def carve_layers(body, task, min_depth_frac: float = 0.004, log: list | None = None, max_cuts: int = 40,
                 t_end: float | None = None):
    """Cut every confidently placed recessed face of the six axis views into `body` (a silhouette
    body in the facts frame). A cut is kept only if the part stays one solid, its volume does not
    fall below the facts' volume, and no view's silhouette changes. Returns the carved body."""
    import time

    import cadquery as cq

    from .compile import _largest_solid, _ring_wire
    from .geometry import shape_to_mesh
    from .vision import mask_polygons, shape_score, target_masks

    size = box_size(task.facts)
    vol_target = float(task.facts.get("volume_mm3") or 0.0)
    shape = body.val() if hasattr(body, "val") else body
    masks = target_masks(task)
    base_iou = shape_score(shape_to_mesh(shape), task, masks)["mean"]
    cuts = []
    for stem in ISO_FOR:
        faces = face_depths(task, stem)
        if not faces:
            continue
        cam = Camera(stem, size, faces[0]["mask"].shape[0])
        corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]) @ cam.f
        near, extent = corners.min(), np.ptp(corners)
        sure = [f for f in faces if f["uniform"] >= 0.7 and f["edge"] >= 0.45]
        for f in sure:
            if f["depth"] < min_depth_frac * max(size) or f["score"] < 1.25 * f["score0"]:
                continue
            grown = ndimage.binary_dilation(f["mask"], iterations=2)
            carve = ndimage.binary_fill_holes(grown)
            for g in sure:      # islands that stand prouder than this face stay
                if g is not f and g["depth"] < f["depth"] - 0.01 * extent and (g["mask"] & carve).any():
                    carve &= ~ndimage.binary_dilation(g["mask"], iterations=1)
            cuts.append({"stem": stem, "cam": cam, "near": near, "mask": carve, "depth": f["depth"],
                         "volume": f["depth"] * carve.sum() / cam.scale ** 2, "face": f})
    cuts.sort(key=lambda c: -c["volume"])
    for c in cuts[:max_cuts]:
        if t_end is not None and time.monotonic() > t_end:
            break
        cam = c["cam"]
        try:
            tools = []
            for poly in mask_polygons(c["mask"], 0.7):
                outer = _ring_wire(cam.plane_mm(poly["outer"]), cam, c["near"] - 1.0)
                inners = [_ring_wire(cam.plane_mm(h), cam, c["near"] - 1.0) for h in poly["holes"]]
                tools.append(cq.Solid.extrudeLinear(cq.Face.makeFromWires(outer, inners),
                                                    cq.Vector(*(cam.f * (c["depth"] + 1.0)))))
            new = _largest_solid(shape.cut(*tools))
            ok = new.isValid() and (not vol_target or new.Volume() >= 0.985 * vol_target)
            iou = shape_score(shape_to_mesh(new), task, masks)["mean"] if ok else 0.0
            ok = ok and iou >= base_iou - 0.003
        except Exception as exc:
            ok, iou, new = False, 0.0, None
            if log is not None:
                log.append(f"{c['stem']}: cut failed ({type(exc).__name__})")
        if log is not None:
            f = c["face"]
            log.append(f"{c['stem'][5:]} face {f['area_mm2']:.0f} mm2 at depth {c['depth']:.2f} mm "
                       f"(uniform {f['uniform']:.2f}, edge {f['edge']:.2f}): "
                       + (f"cut, volume x{new.Volume() / vol_target:.3f}" if ok and vol_target else "kept" if ok else "rejected"))
        if ok:
            shape, base_iou = new, max(base_iou, iou)
    return cq.Workplane("XY").newObject([shape])
