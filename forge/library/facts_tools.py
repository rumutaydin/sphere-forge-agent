"""Geometry taken straight from facts.json, with no model in between.

facts.json lists every cylindrical hole and bore of the target with diameter, axis,
length and centre. `cut_listed_holes` turns that list into cuts. Positions in the
facts are measured from the minimum corner of the bounding box, and a centre is the
midpoint of the bore, not the point where it enters the part.
"""
from __future__ import annotations

import math
import re

AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def parse_axis(axis) -> tuple[float, float, float] | None:
    """'X' / 'Y' / 'Z', or a vector written as '(-0.00, 0.71, 0.71)'. Returns a unit vector."""
    if isinstance(axis, str) and axis.strip().upper() in AXES:
        return AXES[axis.strip().upper()]
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", str(axis))] if not isinstance(axis, (list, tuple)) else list(axis)
    if len(nums) != 3:
        return None
    norm = math.sqrt(sum(n * n for n in nums))
    if norm < 1e-9:
        return None
    v = [n / norm for n in nums]
    # The facts round a 45 degree axis to 0.71; snap such pairs back to exact.
    for i in range(3):
        for j in range(i + 1, 3):
            if abs(abs(v[i]) - abs(v[j])) < 0.02 and abs(abs(v[i]) - math.sqrt(0.5)) < 0.02:
                v[i] = math.copysign(math.sqrt(0.5), v[i])
                v[j] = math.copysign(math.sqrt(0.5), v[j])
    return (v[0], v[1], v[2])


def _exit_distance(point, direction, size) -> float:
    """Distance from `point` along `direction` to the surface of the box [0, size]."""
    best = math.inf
    for p, d, s in zip(point, direction, size):
        if d > 1e-9:
            best = min(best, (s - p) / d)
        elif d < -1e-9:
            best = min(best, -p / d)
    return max(best, 0.0)


def hole_segments(holes: list[dict], size, extend: bool = False) -> list[dict]:
    """One {start, dir, length, radius} per listed bore, in bounding-box coordinates.

    extend=True also opens each bore to the outside through its nearer end, the way a
    drill would have entered. Use it when the body lacks the pocket or counterbore the
    bore starts from, so the bore is not left as a closed void.
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
            start = [c + lo * d for c, d in zip(centre, direction)]
            out.append({"start": start, "dir": direction, "length": hi - lo, "radius": diameter / 2})
    return out


def cut_listed_holes(result, holes: list[dict], extend: bool = False):
    """cut_listed_holes(result, holes, extend=False) -> cq.Workplane with every bore listed in
    facts.json["cylindrical_holes_and_bores"] cut into `result`. Cutting a hole that already
    exists changes nothing, so it is safe to call on a part that has some of them."""
    import cadquery as cq

    shape = result.val() if isinstance(result, cq.Workplane) else result
    bb = shape.BoundingBox()
    origin = (bb.xmin, bb.ymin, bb.zmin)
    for seg in hole_segments(holes, (bb.xlen, bb.ylen, bb.zlen), extend):
        start = cq.Vector(*[o + s for o, s in zip(origin, seg["start"])])
        tool = cq.Solid.makeCylinder(seg["radius"], seg["length"], start, cq.Vector(*seg["dir"]))
        shape = shape.cut(tool)
    return cq.Workplane("XY").newObject([shape])
