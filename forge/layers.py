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


def face_depths(task, stem: str, min_frac: float = 0.0008, steps: int = 240, hull_mesh=None) -> list[dict]:
    """Flat faces of one axis view with the depth at which each sits.

    `hull_mesh` (the silhouette body, facts frame) rules out impossible depths: a point with
    nothing of the hull between it and the isometric camera would be in plain sight, so if the
    isometric view does not show the face there, the face is not at that depth. Without this an
    open cavity is ambiguous (its floor, slid up to the rim, also lines up with drawn edges)."""
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
    # Patches of one flat shade in the isometric view. A face slid to its true depth covers the
    # whole of every patch it lands on (the patch IS the visible part of that face); at a wrong
    # depth it covers only a piece of a larger patch.
    iso32 = iso.astype(np.int32)
    key = (iso32[..., 0] // 8) * 4096 + (iso32[..., 1] // 8) * 64 + iso32[..., 2] // 8
    flat = iso_part & ~ndimage.binary_dilation(iso_stroke, iterations=1)
    keys, counts = np.unique(key[flat], return_counts=True)
    pid = np.zeros(key.shape, np.int32)
    patch_area, patch_key = [0], [-1]
    for kk in keys[np.argsort(-counts)][:16]:
        lab, m = ndimage.label(flat & (key == kk))
        pid[lab > 0] = lab[lab > 0] + len(patch_area) - 1
        patch_area += list(np.bincount(lab.ravel())[1:])
        patch_key += [int(kk)] * m
    patch_area, patch_key = np.array(patch_area, float), np.array(patch_key)
    foreshorten = abs(float(cam.f @ icam.f)) * (icam.scale / cam.scale) ** 2
    vox = None
    if hull_mesh is not None:
        from .geometry import voxelize

        pitch = float(max(size)) / 96
        grid = np.maximum(np.ceil(size / pitch).astype(int), 1)
        vox = voxelize(hull_mesh, np.zeros(3), pitch, grid)
        march = np.linspace(1.5 * pitch, float(np.linalg.norm(size)), 96)[None, :, None] * (-icam.f)[None, None, :]
        centres = (np.stack(np.meshgrid(*[np.arange(g) for g in grid], indexing="ij"), axis=-1).reshape(-1, 3) + 0.5) * pitch
        vpx = np.clip(np.floor(cam.to_px(centres)).astype(int), 0, img.shape[0] - 1)
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

        if vox is not None:
            # We see this face along its own view direction, so the column in front of it is
            # empty whatever its depth: only the hull OUTSIDE that column can hide it.
            column = ndimage.binary_dilation(region, iterations=2)[vpx[:, 1], vpx[:, 0]].reshape(grid)
            occluder = vox & ~column
        uni, edg, con = np.zeros(steps), np.zeros(steps), np.zeros(steps)
        per_sample = len(ys) / len(inner) * foreshorten      # iso pixels one sample stands for
        for j, t in enumerate(ts):
            px, ok = project(inner, t)
            hit = pid[px[ok, 1], px[ok, 0]]
            hit = hit[hit > 0]
            if len(hit) < 0.2 * len(inner):
                continue
            n_hit = np.bincount(hit, minlength=len(patch_area))
            whole = n_hit * np.minimum(1.0, n_hit * per_sample / np.maximum(patch_area, 1.0))
            main = patch_key[int(whole.argmax())]             # the shade of the patch covered most completely
            possible = True
            if vox is not None:
                # Samples with nothing of the hull between them and the isometric camera are in
                # plain sight. They must all show one shade, and that shade is this face's.
                sub = inner[:300]
                pts = sub[:, :1] * cam.r + sub[:, 1:] * cam.u + (near + t) * cam.f
                cells = np.floor((pts[:, None, :] + march) / pitch).astype(int)
                inside = ((cells >= 0) & (cells < grid)).all(axis=2)
                cells = np.clip(cells, 0, grid - 1)
                blocked = (occluder[cells[..., 0], cells[..., 1], cells[..., 2]] & inside).any(axis=1)
                if (~blocked).sum() >= 0.15 * len(sub):
                    spx = np.clip(np.floor(icam.to_px(pts[~blocked])).astype(int), 0, iso.shape[0] - 1)
                    shades = patch_key[pid[spx[:, 1], spx[:, 0]]]
                    vals, cnt = np.unique(shades[shades >= 0], return_counts=True)
                    if len(vals) == 0 or cnt.max() < 0.8 * len(shades):
                        possible = False      # in plain sight, yet the view shows something else there
                    else:
                        main = vals[int(cnt.argmax())]
            if not possible:
                continue
            sel = (patch_key == main) & (n_hit > 0)
            if not sel.any():
                continue
            contain = np.minimum(1.0, n_hit[sel] * per_sample / np.maximum(patch_area[sel], 1.0))
            uni[j] = float((n_hit[sel] * contain).sum()) / len(inner)        # covered, and whole patches
            con[j] = float((n_hit[sel] * contain).sum() / max(n_hit[sel].sum(), 1))
            px, ok = project(border, t)
            edg[j] = iso_edge[px[ok, 1], px[ok, 0]].sum() / len(border)
        score = uni * (0.5 + 0.5 * edg)
        j = int(np.argmax(score))
        out.append({"mask": region, "depth": float(ts[j]), "contain": float(con[j]), "uniform": float(uni[j]), "edge": float(edg[j]),
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
    hull_mesh = shape_to_mesh(shape)
    for stem in ISO_FOR:
        faces = face_depths(task, stem, hull_mesh=hull_mesh)
        if not faces:
            continue
        cam = Camera(stem, size, faces[0]["mask"].shape[0])
        corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]) @ cam.f
        near, extent = corners.min(), np.ptp(corners)
        # a floor seen past a near wall is mostly hidden: low coverage is fine as long as the
        # patches it does cover are covered whole and the plain-sight test (hull_mesh) passed
        sure = [f for f in faces if f["contain"] >= 0.8 and f["uniform"] >= 0.15 and f["edge"] >= 0.25]
        part_px = int((_rgb(next(v for v in task.views if v.stem == stem)).min(axis=2) < 235).sum()) or 1
        for f in sure:
            if f["depth"] < min_depth_frac * max(size) or f["score"] < 1.5 * f["score0"]:
                continue
            if f["mask"].sum() < 0.004 * part_px:
                continue        # small or half-hidden regions match by accident; only clear cases cut
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
                # Extruded toward the camera, not along the normal: we SEE this face from there, so the
                # space on the line of sight in front of it is empty for certain.
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
                       f"(covers {f['uniform']:.2f}, whole patches {f['contain']:.2f}, edge {f['edge']:.2f}): "
                       + (f"cut, volume x{new.Volume() / vol_target:.3f}" if ok and vol_target else "kept" if ok else "rejected"))
        if ok:
            shape, base_iou = new, max(base_iou, iou)
    return cq.Workplane("XY").newObject([shape])


# --- faces that bores start from -------------------------------------------------------------
#
# A bore in the facts has an exact midpoint, axis and length, so both of its ends are known
# points, and a bore starts on a face that is normal to its axis. If a view shows the bore's
# rim at one of those ends, the flat region around the rim is that face, and everything in
# front of it is empty. This needs no depth search: the plane is exact. It works in the
# isometric views too, which is the only place a face on a tilted bank (a V-block) is seen.

ALL_VIEWS = ("view_0_front", "view_1_back", "view_2_left", "view_3_right", "view_4_top", "view_5_bottom",
             "view_6_iso_front_right_top", "view_7_iso_back_left_bottom")


def _in_plane_basis(n: np.ndarray):
    a = np.cross(n, [1.0, 0.0, 0.0])
    if np.linalg.norm(a) < 0.3:
        a = np.cross(n, [0.0, 1.0, 0.0])
    a /= np.linalg.norm(a)
    return a, np.cross(n, a)


def mouth_faces(task, min_rim: float = 0.55) -> list[dict]:
    """Faces found around visible bore mouths: [{"stem", "normal" (outward), "point", "mask", ...}]."""
    from .compile import bores

    size = box_size(task.facts)
    by = {v.stem: v for v in task.views}
    segs = bores(task)
    out, seen = [], set()
    cache = {}
    for stem in ALL_VIEWS:
        if stem not in by:
            continue
        img = _rgb(by[stem])
        cam = Camera(stem, size, img.shape[0])
        part = img.min(axis=2) < 235
        stroke = img.max(axis=2) < STROKE
        edge = ndimage.binary_dilation(stroke, iterations=1)
        labels, _ = ndimage.label(part & ~edge)
        cache[stem] = (img, cam, part, edge, labels)
    ang = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    for seg in segs:
        d = np.array(seg["dir"])
        for sign in (1.0, -1.0):
            n_out = sign * d
            mouth = np.array(seg["centre"]) + n_out * seg["length"] / 2
            a, b = _in_plane_basis(n_out)
            for stem, (img, cam, part, edge, labels) in cache.items():
                facing = -float(n_out @ cam.f)
                if facing < 0.5:           # the face must look at this camera reasonably squarely
                    continue
                if "iso" in stem and np.abs(n_out).max() > 0.99:
                    continue               # an axis-aligned face is read from its own axis view

                rim = mouth + seg["radius"] * (np.cos(ang)[:, None] * a + np.sin(ang)[:, None] * b)
                px = np.floor(cam.to_px(rim)).astype(int)
                if (px < 2).any() or (px >= img.shape[0] - 2).any():
                    continue
                if edge[px[:, 1], px[:, 0]].mean() < min_rim:
                    continue               # no rim drawn here: this end is not a visible mouth
                ring = mouth + (seg["radius"] + 3.5 / cam.scale + 0.12 * seg["radius"]) * (
                    np.cos(ang)[:, None] * a + np.sin(ang)[:, None] * b)
                rp = np.floor(cam.to_px(ring)).astype(int)
                rp = rp[(rp >= 0).all(axis=1) & (rp < img.shape[0]).all(axis=1)]
                # the face = the patch of one shade around the rim (neighbouring faces differ in shade,
                # so this holds even where a thin stroke lets a plain flood fill leak)
                ref = np.median(img[rp[:, 1], rp[:, 0]], axis=0)
                same = (np.abs(img - ref).max(axis=2) <= 12) & part & ~edge
                comp, _ = ndimage.label(same)
                lab = comp[rp[:, 1], rp[:, 0]]
                lab = lab[lab > 0]
                if len(lab) < 20:
                    continue
                k = int(np.bincount(lab).argmax())
                if (lab == k).mean() < 0.5:
                    continue
                region = comp == k
                plane = round(float(n_out @ mouth), 1)
                key = (stem, int(np.flatnonzero(region.ravel())[0]), tuple(np.round(n_out, 2)), plane)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"stem": stem, "cam": cam, "normal": n_out, "point": mouth, "mask": region,
                            "facing": facing, "area_px": int(region.sum()), "radius": seg["radius"]})
    return out


def carve_mouth_faces(body, task, log: list | None = None, t_end: float | None = None, max_cuts: int = 24):
    """Remove the material a silhouette body has in front of the faces its bores start from.
    Each cut is kept only if the part stays valid, no silhouette changes and the volume does not
    fall below the facts' volume. Returns the carved body (a cq.Workplane)."""
    import time

    import cadquery as cq

    from .compile import _largest_solid, bores
    from .geometry import shape_to_mesh
    from .vision import mask_polygons, shape_score, target_masks

    size = box_size(task.facts)
    reach = float(np.linalg.norm(size)) + 2.0
    vol_target = float(task.facts.get("volume_mm3") or 0.0)
    shape = body.val() if hasattr(body, "val") else body
    masks = target_masks(task)
    base_iou = shape_score(shape_to_mesh(shape), task, masks)["mean"]
    segs = bores(task)
    faces = mouth_faces(task)
    # one cut per (plane, view region); squarest view first, then the largest region
    faces.sort(key=lambda f: (-round(f["facing"], 1), -f["area_px"]))
    done = set()
    n_cut = 0
    for f in faces:
        if n_cut >= max_cuts or (t_end is not None and time.monotonic() > t_end):
            break
        cam, n_out, point = f["cam"], f["normal"], f["point"]
        plane_key = (tuple(np.round(n_out, 2)), round(float(n_out @ point), 1))
        grown = ndimage.binary_dilation(f["mask"], iterations=2)
        carve = grown.copy()
        # openings inside the face that are bores starting on this same plane belong to the cut
        holes, n_holes = ndimage.label(ndimage.binary_fill_holes(grown) & ~grown)
        for seg in segs:
            for sign in (1.0, -1.0):
                m = np.array(seg["centre"]) + sign * np.array(seg["dir"]) * seg["length"] / 2
                if abs(float(n_out @ m) - float(n_out @ point)) > 0.02 * max(size) or abs(float(n_out @ seg["dir"])) < 0.99:
                    continue
                x, y = np.floor(cam.to_px(m[None, :])[0]).astype(int)
                if 0 <= x < carve.shape[1] and 0 <= y < carve.shape[0] and holes[y, x]:
                    carve |= holes == holes[y, x]
        tag = (plane_key, f["stem"], int(np.flatnonzero(f["mask"].ravel())[0]))
        if tag in done:
            continue
        done.add(tag)
        try:
            tools = []
            denom = float(n_out @ cam.f)
            for poly in mask_polygons(carve, 0.7):
                def lift(ring_px):
                    ab = cam.plane_mm(ring_px)
                    base = ab[:, :1] * cam.r + ab[:, 1:] * cam.u            # on the camera plane through the origin
                    s = (float(n_out @ point) - base @ n_out) / denom       # slide along the view ray onto the face plane
                    return base + s[:, None] * cam.f
                outer = cq.Wire.makePolygon([cq.Vector(*p) for p in lift(poly["outer"])], close=True)
                inners = [cq.Wire.makePolygon([cq.Vector(*p) for p in lift(h)], close=True) for h in poly["holes"]]
                # Extruded toward the camera, not along the normal: we SEE this face from there, so the
                # space on the line of sight in front of it is empty for certain.
                tools.append(cq.Solid.extrudeLinear(cq.Face.makeFromWires(outer, inners), cq.Vector(*(-cam.f * reach))))
            new = _largest_solid(shape.cut(*tools))
            removed = shape.Volume() - new.Volume()
            ok = new.isValid() and removed > 2e-4 * shape.Volume()     # a sliver is not worth a silhouette check
            why = "nothing in front of it" if not ok else ""
            if ok and vol_target and new.Volume() < 0.985 * vol_target:
                ok, why = False, f"volume would fall to x{new.Volume() / vol_target:.2f}"
            if ok:
                iou = shape_score(shape_to_mesh(new), task, masks)["mean"]
                if iou < base_iou - 0.003:
                    ok, why = False, f"changes a silhouette ({base_iou:.3f} -> {iou:.3f})"
        except Exception as exc:
            ok, why = False, f"failed ({type(exc).__name__})"
        if log is not None:
            log.append(f"face around a {2 * f['radius']:.1f} mm bore, normal ({n_out[0]:.2f}, {n_out[1]:.2f}, {n_out[2]:.2f}), "
                       f"seen in {f['stem'][5:]}: "
                       + (f"cut {removed:.0f} mm^3, volume x{new.Volume() / vol_target:.3f}" if ok and vol_target else why or "cut"))
        if ok:
            shape, base_iou, n_cut = new, max(base_iou, iou), n_cut + 1
    return cq.Workplane("XY").newObject([shape])


# --- patterns that repeat around an axis ------------------------------------------------------
#
# A turned part with fins or grooves around its axis has a perfect disc as its axis view and a
# plain profile from the side, so no outline shows the grooves. The axis view does: its strokes
# repeat n times around the centre, and between the fins it looks down onto a flat face.
#   1. n = the largest count for which the stroke drawing maps onto itself when turned by 360/n
#   2. the flat faces seen between the fins (depth from face_depths) are copied to all n positions
#      and the space above them is removed: we look straight down onto them
#   3. optionally the same openings, shrunk toward the axis as the profile narrows, are removed
#      higher up (a groove that runs up a cone); kept only if the line drawing of the part then
#      matches the strokes of the views better (vision.edge_score)

AXIS_VIEW = {"Z": "view_4_top", "Y": "view_0_front", "X": "view_2_left"}


def rotation_order(task, stem: str, n_max: int = 48, need: float = 0.5) -> int:
    """How many times the stroke drawing of an axis view repeats around the image centre (1 = not at all)."""
    view = next((v for v in task.views if v.stem == stem), None)
    if view is None:
        return 1
    img = _rgb(view)
    part = img.min(axis=2) < 235
    stroke = (img.max(axis=2) < STROKE) & ndimage.binary_erosion(part, iterations=6)    # inner strokes only
    if stroke.sum() < 200:
        return 1
    near = ndimage.binary_dilation(stroke, iterations=3)
    ys, xs = np.nonzero(stroke)
    mid = img.shape[0] / 2
    dx, dy = xs + 0.5 - mid, ys + 0.5 - mid
    keep = np.hypot(dx, dy) > 0.15 * img.shape[0] / 2
    dx, dy = dx[keep], dy[keep]
    def match(angle):
        x = np.clip((mid + dx * np.cos(angle) - dy * np.sin(angle)).astype(int), 0, img.shape[1] - 1)
        y = np.clip((mid + dx * np.sin(angle) + dy * np.cos(angle)).astype(int), 0, img.shape[0] - 1)
        return float(near[y, x].mean())

    # concentric circles map onto themselves at any angle: that is no pattern
    scores = {n: match(2 * np.pi / n) for n in range(3, n_max + 1)}
    generic = float(np.median(list(scores.values())))
    n = max(scores, key=scores.get)
    return n if scores[n] >= max(need, generic + 0.2) else 1


def carve_radial(body, task, log: list | None = None, taper: bool = True):
    """Grooves around the axis of a turned body (see above). Returns the carved cq.Workplane, or
    `body` unchanged if the part is not turned or shows no repeating pattern."""
    import cadquery as cq

    from .compile import _largest_solid, revolve_axis
    from .geometry import brep_genus, shape_to_mesh
    from .vision import edge_score, mask_polygons, shape_score, target_masks

    axis = revolve_axis(task)
    if axis is None:
        return body
    stem = AXIS_VIEW[axis]
    n = rotation_order(task, stem)
    if n < 3:
        return body
    size = box_size(task.facts)
    k = "XYZ".index(axis)
    shape = body.val() if hasattr(body, "val") else body
    mesh = shape_to_mesh(shape)
    faces = [f for f in face_depths(task, stem, hull_mesh=mesh)
             if f["contain"] >= 0.8 and f["uniform"] >= 0.15 and f["edge"] >= 0.25 and f["depth"] > 0.02 * size[k]]
    if not faces:
        return body
    cam = Camera(stem, size, faces[0]["mask"].shape[0])
    # the deepest level seen between the fins, and every opening at that level, copied n times
    ds = np.array([f["depth"] for f in faces])
    votes = [(np.abs(ds - d) < 0.02 * size[k]).sum() for d in ds]      # the level most faces agree on
    depth = float(np.median(ds[np.abs(ds - ds[int(np.argmax(votes))]) < 0.02 * size[k]]))
    seed = np.zeros_like(faces[0]["mask"])
    for f in faces:
        if abs(f["depth"] - depth) < 0.02 * size[k]:
            seed |= f["mask"]          # not grown: neighbouring openings must stay separate pieces
    opening = np.zeros_like(seed)
    for i in range(n):
        opening |= ndimage.rotate(seed.astype(np.uint8), 360.0 * i / n, reshape=False, order=0) > 0
    part = _rgb(next(v for v in task.views if v.stem == stem)).min(axis=2) < 235
    opening &= part
    polys = []
    mid = opening.shape[0] / 2
    for poly in mask_polygons(opening, 0.7):
        # each opening as a plain triangle: its innermost point and its two outermost corners.
        # A pixel-traced outline has hundreds of corners and makes every cut very slow.
        p = poly["outer"]
        d = p + 0.5 - mid
        rad, ang = np.hypot(d[:, 0], d[:, 1]), np.arctan2(d[:, 1], d[:, 0])
        apex = int(rad.argmin())
        rel = (ang - ang[apex] + np.pi) % (2 * np.pi) - np.pi
        outer = rad > 0.9 * rad.max()
        if outer.sum() < 2 or np.ptp(rel[outer]) < 1e-3 or np.ptp(rel) > np.pi / 2:
            continue
        idx = np.flatnonzero(outer)
        polys.append(p[[apex, idx[rel[outer].argmin()], idx[rel[outer].argmax()]]])
    if len(polys) < n // 2:
        return body
    corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]) @ cam.f
    near = corners.min()
    centre = size / 2
    level0 = (near + depth) * cam.f[k]              # coordinate along the axis of the faces we look down on
    toward = -cam.f[k]                              # +1 if the camera sits at the high end of the axis
    far_end = size[k] if toward > 0 else 0.0

    def ring3(px, level, scale=1.0, grow=1.0, inner=1.0):
        ab = cam.plane_mm(px)
        pts = ab[:, :1] * cam.r + ab[:, 1:] * cam.u
        pts[:, k] = 0.0
        rel = pts - centre * (np.arange(3) != k)
        rad = np.linalg.norm(rel, axis=1, keepdims=True)
        rel = rel * scale * np.where(rad > 0.9 * rad.max(), grow, 1.0)   # outer corners pushed out so the cut clears the rim
        rel = rel * np.where(rad > 0.9 * rad.max(), 1.0, inner)          # the apex pulled toward the axis: a deeper groove
        pts = rel + centre * (np.arange(3) != k)
        pts[:, k] = level
        return [cq.Vector(*p) for p in pts]

    masks = target_masks(task)
    vol_target = float(task.facts.get("volume_mm3") or 0.0)
    g0 = brep_genus(shape)

    def accept(new, base_edge, what):
        if not new.isValid() or new.Volume() > 0.9995 * shape.Volume():
            return None
        if vol_target and new.Volume() < 0.985 * vol_target:
            return None
        m = shape_to_mesh(new)
        if brep_genus(new) != g0 or shape_score(m, task, masks)["mean"] < base_sil - 0.003:
            return None
        e = edge_score(m, task)["all"]
        if log is not None:
            log.append(f"{what}: volume x{new.Volume() / vol_target if vol_target else 0:.2f}, edge score {base_edge:.3f} -> {e:.3f}")
        return e if e > base_edge + 0.002 else None

    base_sil = shape_score(mesh, task, masks)["mean"]
    edge = edge_score(mesh, task)["all"]
    # 2. straight down onto the faces between the fins
    try:
        tools = [cq.Solid.extrudeLinear(cq.Face.makeFromWires(cq.Wire.makePolygon(ring3(p, level0, grow=1.15), close=True)),
                                        cq.Vector(*(np.eye(3)[k] * (far_end - level0 + toward)))) for p in polys]
        new = _largest_solid(shape.cut(*tools))
        e = accept(new, edge, f"{n}-fold pattern, {len(polys)} openings straight along {axis}")
        if e is not None:
            shape, edge = new, e
    except Exception as exc:
        if log is not None:
            log.append(f"radial straight cut failed: {type(exc).__name__}")
    # 3. the same openings shrinking with the profile: try a few end heights, keep the best
    if taper:
        verts = np.asarray(shape_to_mesh(body.val() if hasattr(body, "val") else body).vertices)
        rad = np.linalg.norm((verts - centre)[:, np.arange(3) != k], axis=1)

        def radius_at(level):
            sel = np.abs(verts[:, k] - level) < 0.03 * size[k]
            return float(rad[sel].max()) if sel.any() else 0.0

        r0 = radius_at(level0 + toward * 0.03 * size[k])
        best = None
        for frac in (0.6, 0.8, 1.0):
            level1 = level0 + frac * (far_end - level0)
            r1 = radius_at(level1)
            if r0 <= 0 or r1 <= 0 or r1 >= r0:
                continue
            try:
                tools = []
                for p in polys:
                    w0 = cq.Wire.makePolygon(ring3(p, level0, 1.0, 1.15), close=True)
                    w1 = cq.Wire.makePolygon(ring3(p, level1, r1 / r0, 1.15), close=True)
                    tools.append(cq.Solid.makeLoft([w0, w1], True))
                new = _largest_solid(shape.cut(*tools))
                e = accept(new, edge, f"{n}-fold grooves narrowing to {frac:.0%} of the way along {axis}")
            except Exception as exc:
                if log is not None:
                    log.append(f"radial tapered cut failed: {type(exc).__name__}: {str(exc)[:60]}")
                continue
            if e is not None and (best is None or e > best[0]):
                best = (e, new)
        if best:
            edge, shape = best
    return cq.Workplane("XY").newObject([shape])
