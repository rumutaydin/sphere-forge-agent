"""TRACK C. Parts built by plain code from facts.json and the views. No model.

    cut_facts_holes(body, facts)      every bore listed in the facts, cut exactly
    hull_body(task, ...)              visual hull: silhouette prisms intersected (B-rep)
    revolve_body(task)                lathe hull, for parts that are bodies of revolution
    body_sources(task)                [(name, cq.Workplane)], holes NOT yet cut
    compile_part(task, out_dir)       all sources x hole variants, measured; returns them ranked

Every body is in the facts frame: millimetres, bounding-box minimum corner at the origin.
All silhouette bodies contain the true part (they can only be too large), so the true
volume in the facts says how much they overfill.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

from .vision import AXIS_VIEWS, Camera, box_size, image_mask, mask_polygons

AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
ISO_VIEWS = ("view_6_iso_front_right_top", "view_7_iso_back_left_bottom")
RAW_BBOX = None
MIRROR = {"view_0_front": "view_1_back", "view_2_left": "view_3_right", "view_4_top": "view_5_bottom"}


# --- bores from the facts ---------------------------------------------------------------

def parse_axis(axis) -> tuple[float, float, float] | None:
    """'X' / 'Y' / 'Z', or a vector written as '(-0.00, 0.71, 0.71)'. Returns a unit vector."""
    if isinstance(axis, str) and axis.strip().upper() in AXES:
        return AXES[axis.strip().upper()]
    nums = list(axis) if isinstance(axis, (list, tuple)) else \
        [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", str(axis))]
    if len(nums) != 3:
        return None
    norm = math.sqrt(sum(n * n for n in nums))
    if norm < 1e-9:
        return None
    v = [n / norm for n in nums]
    for i in range(3):          # the facts round a 45 degree axis to 0.71; snap back to exact
        for j in range(i + 1, 3):
            if abs(abs(v[i]) - abs(v[j])) < 0.02 and abs(abs(v[i]) - math.sqrt(0.5)) < 0.02:
                v[i] = math.copysign(math.sqrt(0.5), v[i])
                v[j] = math.copysign(math.sqrt(0.5), v[j])
    return (v[0], v[1], v[2])


def _exit_distance(point, direction, size) -> float:
    best = math.inf
    for p, d, s in zip(point, direction, size):
        if d > 1e-9:
            best = min(best, (s - p) / d)
        elif d < -1e-9:
            best = min(best, -p / d)
    return max(best, 0.0)


def hole_segments(holes: list[dict], size, extend: bool = False) -> list[dict]:
    """One {start, dir, length, radius} per listed bore. A centre in the facts is the bore's midpoint.

    extend=True also opens each bore to the outside through its nearer end, the way a drill
    entered. Use it when the body lacks the pocket the bore starts from (a hull always does),
    so the bore is not left as a closed void.
    """
    out = []
    for group in holes or []:
        direction = parse_axis(group.get("axis"))
        diameter = group.get("diameter")
        lengths = group.get("lengths") or []
        centres = group.get("centres") or []
        if not direction or not diameter or not lengths or not centres:
            continue
        for i, centre in enumerate(centres):
            length = float(lengths[i]) if len(lengths) == len(centres) else float(max(lengths))
            lo, hi = -length / 2, length / 2
            if extend:
                ahead = _exit_distance(centre, direction, size)
                behind = _exit_distance(centre, [-d for d in direction], size)
                pad = 0.02 * max(size) + 1.0
                if ahead <= behind:
                    hi = max(hi, ahead + pad)
                else:
                    lo = min(lo, -(behind + pad))
            # An end that stops within a hair of the bounding box (rounding in the facts) must go
            # through it: otherwise a membrane of 0.005 mm closes the bore and the hole is not counted.
            snap = 0.002 * max(size) + 0.05
            pad = 0.02 * max(size) + 1.0
            if _exit_distance(centre, direction, size) - hi < snap:
                hi = max(hi, _exit_distance(centre, direction, size) + pad)
            if _exit_distance(centre, [-d for d in direction], size) + lo < snap:
                lo = min(lo, -(_exit_distance(centre, [-d for d in direction], size) + pad))
            start = [c + lo * d for c, d in zip(centre, direction)]
            out.append({"start": start, "dir": direction, "length": hi - lo, "radius": diameter / 2})
    return out


def cut_facts_holes(body, facts: dict, extend: bool = False):
    """Cut every bore in facts["cylindrical_holes_and_bores"] into `body` (facts frame). Idempotent."""
    import cadquery as cq

    shape = body.val() if isinstance(body, cq.Workplane) else body
    segs = hole_segments(facts.get("cylindrical_holes_and_bores") or [], box_size(facts), extend)
    if segs:
        tools = [cq.Solid.makeCylinder(s["radius"], s["length"], cq.Vector(*s["start"]), cq.Vector(*s["dir"]))
                 for s in segs]
        shape = shape.cut(*tools)
    return cq.Workplane("XY").newObject([_largest_solid(shape)])


def _bore_extent(seg: dict, mode: str, size) -> tuple[float, float]:
    """(lo, hi) along the bore axis from its midpoint. listed: as in the facts; open: the nearer
    end drilled out of the box; through: both ends out of the box."""
    lo, hi = -seg["length"] / 2, seg["length"] / 2
    ahead = _exit_distance(seg["centre"], seg["dir"], size)
    behind = _exit_distance(seg["centre"], [-d for d in seg["dir"]], size)
    pad = 0.02 * max(size) + 1.0
    snap = 0.002 * max(size) + 0.05
    if mode == "through" or (mode == "open" and ahead <= behind) or ahead - hi < snap:
        hi = max(hi, ahead + pad)
    if mode == "through" or (mode == "open" and ahead > behind) or behind + lo < snap:
        lo = min(lo, -(behind + pad))
    return lo, hi


def bores(task) -> list[dict]:
    """Every listed bore: centre (midpoint), dir, length, radius, and `visible`: its axis view shows
    daylight through it (an opening at least as wide as the bore), so it is certainly a through-hole."""
    from scipy import ndimage

    facts, size = task.facts, box_size(task.facts)
    out = []
    groups_seen: list[int] = []
    for group in facts.get("cylindrical_holes_and_bores") or []:
        direction, diameter = parse_axis(group.get("axis")), group.get("diameter")
        lengths, centres = group.get("lengths") or [], group.get("centres") or []
        if not direction or not diameter or not lengths or not centres:
            continue
        for i, centre in enumerate(centres):
            length = float(lengths[i]) if len(lengths) == len(centres) else float(max(lengths))
            out.append({"centre": [float(c) for c in centre], "dir": direction, "length": length,
                        "radius": diameter / 2, "visible": False, "group": len(groups_seen)})
        groups_seen.append(1)
    by_stem = {v.stem: v for v in task.views}
    for stem in AXIS_VIEWS:
        if stem not in by_stem:
            continue
        mask = pair_mask(task, stem)
        cam = Camera(stem, size, mask.shape[0])
        labels, _ = ndimage.label(ndimage.binary_fill_holes(mask) & ~mask)
        areas = np.bincount(labels.ravel())
        for seg in out:
            if abs(float(np.dot(seg["dir"], cam.f))) < 0.999:
                continue
            x, y = cam.to_px(np.array([seg["centre"]]))[0]
            xi, yi = int(np.clip(x, 0, mask.shape[1] - 1)), int(np.clip(y, 0, mask.shape[0] - 1))
            k = labels[yi, xi]
            if k and seg["radius"] * cam.scale <= math.sqrt(areas[k] / math.pi) + 2.5:
                seg["visible"] = True
    return out


def _crossings(segs: list[dict], size) -> list[int]:
    """How many other bores each bore's axis passes through (drilled fully through the box)."""
    def ends(s):
        lo, hi = _bore_extent(s, "through", size)
        c, d = np.array(s["centre"]), np.array(s["dir"])
        return c + lo * d, c + hi * d

    def seg_dist(p1, q1, p2, q2):
        best = math.inf
        for t in np.linspace(0, 1, 41):
            a = p1 + t * (q1 - p1)
            d2 = q2 - p2
            u = np.clip(np.dot(a - p2, d2) / max(np.dot(d2, d2), 1e-12), 0, 1)
            best = min(best, float(np.linalg.norm(a - (p2 + u * d2))))
        return best

    pts = [ends(s) for s in segs]
    count = [0] * len(segs)
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if abs(float(np.dot(segs[i]["dir"], segs[j]["dir"]))) > 0.999:
                continue        # parallel bores do not cross (coaxial steps are one hole)
            if seg_dist(*pts[i], *pts[j]) < segs[i]["radius"] + segs[j]["radius"]:
                count[i] += 1
                count[j] += 1
    return count


def cut_bores(body, segs: list[dict], modes: list[str], size):
    import cadquery as cq

    shape = body.val() if isinstance(body, cq.Workplane) else body
    tools = []
    for seg, mode in zip(segs, modes):
        if mode == "skip":
            continue
        lo, hi = _bore_extent(seg, mode, size)
        start = [c + lo * d for c, d in zip(seg["centre"], seg["dir"])]
        tools.append(cq.Solid.makeCylinder(seg["radius"], hi - lo, cq.Vector(*start), cq.Vector(*seg["dir"])))
    if tools:
        shape = shape.cut(*tools)
    return cq.Workplane("XY").newObject([_largest_solid(shape)])


def cut_holes_to_genus(body, task, rounds: int = 6, log=None, t_end: float | None = None):
    """Cut the listed bores so that the through-hole count equals facts["through_holes_genus"].

    A silhouette body is too thick wherever the true part has a pocket, so a bore of the listed
    length often ends inside material and does not count as a through-hole. Start from: daylight
    bores through, the others opened to their nearer side. Then, while the count is short, drill
    more bores fully through (those that best close the volume gap first); while it is over,
    shorten bores that cross others back to their listed length. Returns (body, modes, genus).
    """
    from .geometry import genus, shape_to_mesh

    facts, size = task.facts, box_size(task.facts)
    segs = bores(task)
    target = int(facts.get("through_holes_genus", 0))
    if not segs:
        return body, [], None
    vol_target = float(facts.get("volume_mm3") or 0.0)
    from .geometry import brep_genus

    start = body.val() if hasattr(body, "val") else body
    fast = brep_genus(start) == genus(shape_to_mesh(start, rel_tol=1.5e-3))   # trust the topology count only if it agrees here

    def measure(shape):
        return brep_genus(shape) if fast else genus(shape_to_mesh(shape, rel_tol=1.5e-3))

    def tool(i, mode):
        import cadquery as cq
        lo, hi = _bore_extent(segs[i], mode, size)
        start = [c + lo * d for c, d in zip(segs[i]["centre"], segs[i]["dir"])]
        return cq.Solid.makeCylinder(segs[i]["radius"], hi - lo, cq.Vector(*start), cq.Vector(*segs[i]["dir"]))

    # The facts list bores in patterns (same diameter and axis), and a pattern plays one role, so
    # a whole pattern is tried in one cut: daylight bores through; the others opened to their
    # nearer side, or else as listed, whichever keeps the count at or below the target. Only when
    # a pattern as a whole overshoots are its bores tried one by one.
    import time

    shape = body.val() if hasattr(body, "val") else body
    g = measure(shape)
    modes = ["skip"] * len(segs)

    def late():
        return t_end is not None and time.monotonic() > t_end

    def attempt(idx, mode):
        try:
            new = _largest_solid(shape.cut(*[tool(i, mode) for i in idx]))
            return new, measure(new)
        except Exception:
            return None, -1

    units: dict[tuple, list[int]] = {}
    for i, seg in enumerate(segs):
        units.setdefault((not seg["visible"], -seg["radius"], seg["group"]), []).append(i)
    for key in sorted(units):
        idx, visible = units[key], not key[0]
        if late():      # out of time: everything left goes in as listed, in one cut
            rest = [i for k in sorted(units) if k >= key for i in units[k]]
            new, g2 = attempt(rest, "listed")
            if new is not None and g2 >= 0:
                shape, g = new, g2
                for i in rest:
                    modes[i] = "listed"
            break
        placed = False
        for mode in (("through",) if visible else ("open", "listed")):
            new, g2 = attempt(idx, mode)
            if new is not None and (0 <= g2 <= target or visible):
                shape, g, placed = new, g2, True
                for i in idx:
                    modes[i] = mode
                break
        if not placed and len(idx) > 1:
            for i in idx:
                for mode in ("open", "listed"):
                    new, g2 = attempt([i], mode)
                    if new is not None and 0 <= g2 <= target:
                        shape, g, modes[i] = new, g2, mode
                        break
    # Still short: drill more bores fully through, those that best close the volume gap first.
    def cost(idx):
        total = 0.0
        for i in idx:
            lo, hi = _bore_extent(segs[i], "through", size)
            total += math.pi * segs[i]["radius"] ** 2 * (hi - lo)
        return total

    for _ in range(rounds):
        if g >= target or late():
            break
        spare = shape.Volume() - vol_target
        cand = [[i for i in idx if modes[i] != "through"] for idx in units.values()]
        cand = [c for c in cand if c]
        fits = sorted([c for c in cand if cost(c) < 0.5 * spare], key=lambda c: -cost(c))
        rest = sorted([c for c in cand if c not in fits], key=cost)
        progressed = False
        for idx in fits + rest:
            if g >= target or late():
                break
            new, g2 = attempt(idx, "through")
            if new is not None and g < g2 <= target:
                shape, g, progressed = new, g2, True
                for i in idx:
                    modes[i] = "through"
            elif len(idx) > 1 and (new is None or g2 > target):
                for i in idx:
                    if g >= target:
                        break
                    new, g2 = attempt([i], "through")
                    if new is not None and g < g2 <= target:
                        shape, g, modes[i], progressed = new, g2, "through", True
        if not progressed:
            break
    if log is not None:
        log.append(f"bores {dict((m, modes.count(m)) for m in sorted(set(modes)))}: genus {g} (target {target}), "
                   f"volume x{shape.Volume() / vol_target if vol_target else 0:.3f}")
    import cadquery as cq
    return cq.Workplane("XY").newObject([shape]), modes, g


def _largest_solid(shape):
    solids = shape.Solids()
    if len(solids) <= 1:
        return solids[0] if solids else shape
    return max(solids, key=lambda s: s.Volume())


# --- bodies from silhouettes -----------------------------------------------------------

def _ring_wire(ring_mm: np.ndarray, cam: Camera, depth: float):
    import cadquery as cq

    pts = [cq.Vector(*(a * cam.r + b * cam.u + depth * cam.f)) for a, b in ring_mm]
    return cq.Wire.makePolygon(pts, close=True)


def view_prism(task, stem: str, keep_holes: bool = True, tol_px: float = 0.7, mask=None):
    """The silhouette of one view extruded through the whole bounding box along the view direction."""
    import cadquery as cq

    size = box_size(task.facts)
    if mask is None:
        mask = image_mask(next(v for v in task.views if v.stem == stem))
    cam = Camera(stem, size, mask.shape[0])
    if keep_holes:
        mask = fill_bore_openings(mask, cam, task.facts)
    polys = mask_polygons(mask, tol_px)
    if not polys:
        return None
    corners = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]) @ cam.f
    near, far = corners.min() - 1.0, corners.max() + 1.0
    main = polys[0]

    def ring(px):
        mm = cam.plane_mm(px)
        if stem in MIRROR:      # axis view: the silhouette touches the bounding box, which is exact
            snap = 1.6 / cam.scale
            for k, (c, ext) in enumerate(((cam.c_r, cam.w_mm), (cam.c_u, cam.h_mm))):
                for bound in (c - ext / 2, c + ext / 2):
                    mm[np.abs(mm[:, k] - bound) < snap, k] = bound
        return mm

    outer = _ring_wire(ring(main["outer"]), cam, near)
    inners = [_ring_wire(ring(h), cam, near) for h in main["holes"]] if keep_holes else []
    face = cq.Face.makeFromWires(outer, inners)
    return cq.Solid.extrudeLinear(face, cq.Vector(*(cam.f * (far - near))))


def fill_bore_openings(mask: np.ndarray, cam: Camera, facts: dict) -> np.ndarray:
    """Close the openings in a silhouette that are bores listed in the facts along this view's
    axis. Those are cut later as exact cylinders; a pixel outline of the same circle next to the
    exact one leaves slivers that break the hole count. Other openings (slots, windows) stay."""
    from scipy import ndimage

    enclosed = ndimage.binary_fill_holes(mask) & ~mask
    if not enclosed.any():
        return mask
    discs = np.zeros_like(mask)
    yy, xx = np.mgrid[:mask.shape[0], :mask.shape[1]]
    for seg in hole_segments(facts.get("cylindrical_holes_and_bores") or [], box_size(facts)):
        if abs(float(np.dot(seg["dir"], cam.f))) < 0.999:
            continue
        mid = np.array(seg["start"]) + np.array(seg["dir"]) * seg["length"] / 2
        cx, cy = cam.to_px(mid[None, :])[0]
        discs |= np.hypot(xx + 0.5 - cx, yy + 0.5 - cy) <= seg["radius"] * cam.scale + 2.5
    labels, n = ndimage.label(enclosed)
    out = mask.copy()
    for k in range(1, n + 1):
        region = labels == k
        if (region & discs).sum() >= 0.9 * region.sum():
            out |= region
    return out


def pair_mask(task, stem: str) -> np.ndarray:
    """Silhouette of an axis view, AND-ed with its mirrored opposite view (same outline, less noise)."""
    by_stem = {v.stem: v for v in task.views}
    mask = image_mask(by_stem[stem])
    other = by_stem.get(MIRROR.get(stem, ""))
    if other is not None:
        flipped = image_mask(other)[:, ::-1] if stem != "view_4_top" else image_mask(other)[::-1, :]
        if flipped.shape == mask.shape and (flipped ^ mask).mean() < 0.01:   # only if they really agree
            mask = mask & flipped
    return mask


def hull_body(task, views=AXIS_VIEWS, keep_holes: bool = True, tol_px: float = 0.7):
    """Intersection of the silhouette prisms of `views`, clipped to the bounding box."""
    import cadquery as cq

    size = box_size(task.facts)
    shape = cq.Solid.makeBox(*size)
    have = {v.stem for v in task.views}
    for stem in views:
        if stem not in have:
            continue
        axis_view = stem in MIRROR
        prism = view_prism(task, stem, keep_holes and axis_view, tol_px, pair_mask(task, stem) if axis_view else None)
        if prism is not None:
            shape = shape.intersect(prism)
    return cq.Workplane("XY").newObject([_largest_solid(shape)])


def revolve_axis(task, tol: float = 0.985) -> str | None:
    """'X', 'Y' or 'Z' if the part looks like a body of revolution about that axis: the view along
    the axis is a filled disc (or ring) centred in the box and the other two extents are equal."""
    size = box_size(task.facts)
    by_stem = {v.stem: v for v in task.views}
    for axis, stem, (i, j) in (("Y", "view_0_front", (0, 2)), ("X", "view_2_left", (1, 2)), ("Z", "view_4_top", (0, 1))):
        if stem not in by_stem or abs(size[i] - size[j]) > 0.01 * max(size[i], size[j]):
            continue
        mask = image_mask(by_stem[stem])
        cam = Camera(stem, size, mask.shape[0])
        yy, xx = np.mgrid[:mask.shape[0], :mask.shape[1]]
        rad = np.hypot(xx - cam.mid, yy - cam.mid)
        disc = rad <= size[i] / 2 * cam.scale + 2.5      # the outline stroke is about a pixel wide
        # ring-shaped is fine: compare radial profile, i.e. the mask must not vary with angle
        bins = np.minimum((rad / (size[i] / 2 * cam.scale) * 60).astype(int), 60)
        fill = np.bincount(bins.ravel(), mask.ravel(), 61)[:60] / np.maximum(np.bincount(bins.ravel(), minlength=61)[:60], 1)
        uniform = np.mean(np.minimum(fill, 1 - fill))        # 0 when every radius is all-in or all-out
        if uniform < 1 - tol and (mask & ~disc).mean() < 0.0005:
            return axis
    return None


def revolve_body(task, axis: str | None = None, tol_px: float = 0.5):
    """Lathe hull: the half outline of a side view revolved about the axis. None if not a revolved part."""
    import cadquery as cq

    axis = axis or revolve_axis(task)
    if axis is None:
        return None
    size = box_size(task.facts)
    stem = {"Y": "view_4_top", "X": "view_0_front", "Z": "view_0_front"}[axis]   # a view that shows the axis
    mask = pair_mask(task, stem)
    cam = Camera(stem, size, mask.shape[0])
    k = "XYZ".index(axis)
    axis_vec = np.eye(3)[k]
    centre = size / 2
    # in-image direction of the axis and of the radius
    ax2 = np.array([axis_vec @ cam.r, axis_vec @ cam.u])
    horizontal = abs(ax2[0]) > abs(ax2[1])
    # symmetrise about the axis, then keep one half
    sym = mask & (mask[::-1, :] if horizontal else mask[:, ::-1])
    half = sym.copy()
    mid = int(round(cam.mid))
    if horizontal:
        half[mid + 1:, :] = False       # keep rows above the axis (u >= centre)
        half[mid, :] = half[mid - 1, :]
    else:
        half[:, :mid] = False           # keep columns right of the axis (r >= centre)
        half[:, mid] = half[:, mid + 1]
    polys = mask_polygons(half, tol_px)
    if not polys:
        return None
    ring = cam.plane_mm(polys[0]["outer"])
    snap = 1.6 / cam.scale
    for k, (c, ext) in enumerate(((cam.c_r, cam.w_mm), (cam.c_u, cam.h_mm))):
        for bound in (c - ext / 2, c + ext / 2):
            ring[np.abs(ring[:, k] - bound) < snap, k] = bound
    pts3 = np.array([a * cam.r + b * cam.u for a, b in ring])
    pts3 = pts3 - (pts3 @ cam.f)[:, None] * cam.f                # drop the depth component
    pts3 += centre * np.abs(cam.f)                               # put the profile plane through the box centre
    # clamp tiny negative radii onto the axis
    rad_dir = np.cross(cam.f, axis_vec)
    rad_dir /= np.linalg.norm(rad_dir)
    radius = (pts3 - centre) @ rad_dir
    sign = 1.0 if radius.mean() > 0 else -1.0
    pts3 -= np.minimum(sign * radius, 0.0)[:, None] * sign * rad_dir * 1.0
    wire = cq.Wire.makePolygon([cq.Vector(*p) for p in pts3], close=True)
    solid = cq.Solid.revolve(cq.Face.makeFromWires(wire), 360.0, cq.Vector(*centre), cq.Vector(*(centre + axis_vec)))
    shape = solid.intersect(cq.Solid.makeBox(*size))
    return cq.Workplane("XY").newObject([_largest_solid(shape)])


def body_sources(task) -> list[tuple[str, object]]:
    """Every no-model body we can make for this task, cheapest first. Holes are NOT cut yet."""
    import cadquery as cq

    out = [("box", cq.Workplane("XY").box(*box_size(task.facts), centered=False))]
    if not task.views:
        return out
    makers = [
        ("hull3", lambda: hull_body(task, AXIS_VIEWS, keep_holes=True)),
        ("hull5", lambda: hull_body(task, AXIS_VIEWS + ISO_VIEWS, keep_holes=True)),
        ("revolve", lambda: revolve_body(task)),
    ]
    for name, make in makers:
        try:
            body = make()
        except Exception as exc:   # a kernel failure in one source must not cost the others
            print(f"{task.name}: body source {name} failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        if body is not None:
            out.append((name, body))
    # The tightest hull again, with the space in front of every face a bore starts from removed
    # (forge/layers.py): pockets and recessed faces that no outline shows.
    hulls = [b for n, b in out if n == "hull5"] or [b for n, b in out if n == "hull3"]
    import os

    faces_on = os.environ.get("FORGE_FACES", "on").lower() not in ("off", "0", "no", "false")
    if hulls and faces_on and task.facts.get("cylindrical_holes_and_bores"):
        try:
            from .layers import carve_mouth_faces

            log: list[str] = []
            carved = carve_mouth_faces(hulls[0], task, log=log)
            if carved.val().Volume() < 0.999 * hulls[0].val().Volume():
                out.append(("hull-faces", carved))
        except Exception as exc:
            print(f"{task.name}: body source hull-faces failed: {type(exc).__name__}: {exc}", flush=True)
    # ... and with every flat face that sits deeper than the hull shows it cut down to its depth
    # (an open cavity, a recessed level): forge/layers.py: carve_layers. Needs no bores.
    if hulls and os.environ.get("FORGE_DEPTH", "on").lower() not in ("off", "0", "no", "false"):
        try:
            from .layers import carve_layers

            start = out[-1][1] if out[-1][0] == "hull-faces" else hulls[0]
            deep = carve_layers(start, task, log=[])
            if deep.val().Volume() < 0.999 * start.val().Volume():
                out.append(("hull-depth", deep))
        except Exception as exc:
            print(f"{task.name}: body source hull-depth failed: {type(exc).__name__}: {exc}", flush=True)
    return out


# --- measure, rank, write --------------------------------------------------------------

def measure_body(body, task) -> dict | None:
    """Kernel measurements + self-check + silhouette score of a body, or None if it is not one valid solid."""
    from .backends._cq_runner import measure
    from .facts import self_check
    from .geometry import genus, shape_to_mesh
    from .vision import shape_score

    shape = body.val()
    info = measure(shape)
    if not info["valid"] or info["solids"] != 1 or info["volume"] <= 0:
        return None
    mesh = shape_to_mesh(shape)
    info["genus"] = genus(mesh)
    info["bbox_size"] = [float(e) for e in mesh.extents]    # the kernel's own box can be loose on curved faces
    check = self_check(info, task.facts)
    shape_s = shape_score(mesh, task) if task.views else {"mean": 0.0, "iou_per_view": {}}
    check["silhouette_iou"] = shape_s.get("mean", 0.0)
    check["estimate"] = estimate(check, shape_s)
    return {"measure": info, "check": check, "shape": shape_s, "estimate": check["estimate"]}


def estimate(check: dict, shape_s: dict) -> float:
    """Rough leaderboard estimate, fitted on bench/calibration (16 files, leave-one-out error 0.07):
    0.14 + 0.16 * holes + 0.62 * volume ratio * silhouette IoU. For ranking candidates, not for quoting."""
    vol = check["volume_ratio"]
    vol = min(vol, 1 / vol) if vol > 0 else 0.0
    return 0.139 + 0.16 * check["holes"] + 0.62 * vol * shape_s.get("mean", 0.0) - 0.5 * (1 - check["dimensions"])


def publish_file(src: str | Path, dst: str | Path) -> None:
    """Copy `src` over `dst` so that a reader never sees a half-written file."""
    import os
    import shutil

    dst = Path(dst)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def compile_part(task, out_dir: str | Path, sources=None, publish: str | Path | None = None,
                 budget_s: float | None = None) -> list[dict]:
    """Build every source with the facts' bores, measure, write STEP files.

    Returns rows sorted best first: {"name", "step", "estimate", "check", "shape"}. Whenever a
    row beats the best so far its STEP is copied to `publish` at once, and compile.json is
    rewritten, so stopping this function at any moment loses nothing. `hull.step` (the best
    silhouette body before any bore) is left in out_dir for the model stage.
    """
    import time

    import cadquery as cq

    t_end = time.monotonic() + budget_s if budget_s else None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    has_holes = bool(task.facts.get("cylindrical_holes_and_bores"))

    def add(label, part, note=None):
        try:
            m = measure_body(part, task)
        except Exception as exc:
            print(f"{task.name}: {label} failed: {type(exc).__name__}: {exc}", flush=True)
            return None
        if m is None:
            return None
        step = out_dir / f"{label}.step"
        cq.exporters.export(part.val(), str(step))
        row = {"name": label, "step": str(step), "estimate": m["estimate"], "check": m["check"],
               "shape": m["shape"], "volume": m["measure"]["volume"], "note": note}
        if publish and all(row["estimate"] > r["estimate"] for r in rows):
            publish_file(step, publish)
        rows.append(row)
        (out_dir / "compile.json").write_text(json.dumps(sorted(rows, key=lambda r: -r["estimate"]), indent=1))
        return row

    bodies = []
    for name, body in (sources if sources is not None else body_sources(task)):
        bodies.append((name, body))
        if not has_holes:
            add(name, body)
            continue
        try:
            add(f"{name}+holes", cut_facts_holes(body, task.facts, extend=True))
        except Exception as exc:
            print(f"{task.name}: {name}+holes failed: {type(exc).__name__}: {exc}", flush=True)
    # the best silhouette body, without bores: the model stage starts from it and trims with it
    silhouette = [r for r in sorted(rows, key=lambda r: -r["estimate"]) if not r["name"].startswith("box")]
    if silhouette:
        cq.exporters.export(dict(bodies)[silhouette[0]["name"].split("+")[0]].val(), str(out_dir / "hull.step"))
    if has_holes and rows:
        # the hole-count search costs many kernel runs: only on the best body, and on a revolve
        ranked = sorted(rows, key=lambda r: -r["estimate"])
        todo = [ranked[0]["name"].split("+")[0]] + [n for n, _ in bodies if n == "revolve"]
        for name in dict.fromkeys(todo):
            log: list[str] = []
            try:
                part, _, _ = cut_holes_to_genus(dict(bodies)[name], task, log=log, t_end=t_end)
                add(f"{name}+holes-fit", part, note=log)
            except Exception as exc:
                print(f"{task.name}: {name}+holes-fit failed: {type(exc).__name__}: {exc}", flush=True)
    rows.sort(key=lambda r: -r["estimate"])
    if rows and task.views:
        # the line drawing of the best part against the strokes of the views: the model pass may
        # not replace this part with one whose inside matches the views worse (forge/pipeline.py)
        try:
            from .vision import edge_score

            rows[0]["check"]["edge_all"] = edge_score(rows[0]["step"], task)["all"]
        except Exception as exc:
            print(f"{task.name}: edge score failed: {type(exc).__name__}: {exc}", flush=True)
    (out_dir / "compile.json").write_text(json.dumps(rows, indent=1))
    return rows


def finish_body(result, facts_path: str, hull: str | None = None, holes: str = "open"):
    """Called at the end of a model-written body program. Moves the body so its bounding-box
    minimum corner is at the origin (the facts frame), trims it with the silhouette body
    (the true part lies inside it, so anything outside is wrong), and cuts the facts' bores."""
    import cadquery as cq

    facts = json.loads(Path(facts_path).read_text())
    shape = result.val() if isinstance(result, cq.Workplane) else result
    if isinstance(shape, cq.Compound) and len(shape.Solids()) == 1:
        shape = shape.Solids()[0]
    bb = shape.BoundingBox()
    global RAW_BBOX        # where the model's body really was, for the envelope repair message
    RAW_BBOX = {"min": [bb.xmin, bb.ymin, bb.zmin], "max": [bb.xmax, bb.ymax, bb.zmax]}
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    if hull and Path(hull).is_file():
        trimmed = _largest_solid(shape.intersect(cq.importers.importStep(hull).val()))
        if trimmed.isValid() and trimmed.Volume() > 0.5 * shape.Volume():
            shape = trimmed
    if holes == "fit":
        # the search that makes the through-hole count equal the facts (needs the views)
        from .cases import load_tasks

        task_dir = Path(facts_path).resolve().parent
        task = load_tasks(task_dir.parent, [task_dir.name + "$"])[0]
        shape = cut_holes_to_genus(cq.Workplane("XY").newObject([shape]), task)[0].val()
    elif holes != "none":
        shape = cut_facts_holes(shape, facts, extend=(holes == "open")).val()
    return cq.Workplane("XY").newObject([shape])


if __name__ == "__main__":
    # python -m forge.compile <task_dir> <out_dir> [publish_path] [budget_s]   (run as a subprocess with a timeout)
    import sys

    from .cases import load_tasks

    task_dir = Path(sys.argv[1])
    task = load_tasks(task_dir.parent, [task_dir.name + "$"])[0]
    compile_part(task, sys.argv[2], publish=sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None,
                 budget_s=float(sys.argv[4]) if len(sys.argv) > 4 else None)
