"""Plain solids in absolute coordinates, for model-written bodies.

A model that writes raw CadQuery loses most attempts to conventions (a box centred on the
origin, workplane-local coordinates, methods that do not exist). These few functions take
world coordinates only: millimetres, the frame of the brief, the bounding-box minimum corner
at the origin. Each returns a cq.Workplane holding one solid.
"""
from __future__ import annotations

import math

_AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def _wp(shape):
    import cadquery as cq

    return cq.Workplane("XY").newObject([shape])


def _shape(obj):
    import cadquery as cq

    if isinstance(obj, cq.Workplane):
        vals = [v for v in obj.vals() if isinstance(v, cq.Shape)]
        if not vals:
            raise ValueError("this object holds no solid")
        return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    return obj


def _axis(axis):
    if isinstance(axis, str):
        if axis.strip().upper() not in _AXES:
            raise ValueError(f"axis must be 'X', 'Y' or 'Z' or a vector, got {axis!r}")
        return _AXES[axis.strip().upper()]
    v = [float(a) for a in axis]
    n = math.sqrt(sum(a * a for a in v))
    if len(v) != 3 or n < 1e-9:
        raise ValueError(f"axis vector must have three numbers, got {axis!r}")
    return tuple(a / n for a in v)


def _flat(items):
    out = []
    for it in items:
        out += _flat(it) if isinstance(it, (list, tuple)) else [it]
    return out


def box(p0, p1):
    """box(p0, p1) -> a block between two opposite corners, e.g. box((0, 0, 0), (80, 50, 8)).
    The corners are world coordinates; nothing is centred."""
    import cadquery as cq

    lo = [min(float(a), float(b)) for a, b in zip(p0, p1)]
    hi = [max(float(a), float(b)) for a, b in zip(p0, p1)]
    size = [h - l for l, h in zip(lo, hi)]
    if min(size) <= 0:
        raise ValueError(f"box{tuple(p0)}..{tuple(p1)} has no thickness on one axis")
    return _wp(cq.Solid.makeBox(*size, cq.Vector(*lo)))


def cylinder(p0, p1, diameter):
    """cylinder(p0, p1, diameter) -> a round bar whose axis runs from point p0 to point p1,
    e.g. cylinder((40, 25, 0), (40, 25, 30), 12). Any direction works, tilted ones too."""
    return cone(p0, p1, diameter, diameter)


def cone(p0, p1, d0, d1):
    """cone(p0, p1, d0, d1) -> a tapered round bar from point p0 (diameter d0) to point p1
    (diameter d1). d0 == d1 gives a cylinder; one of them may be 0 for a point."""
    import cadquery as cq

    a, b = cq.Vector(*[float(v) for v in p0]), cq.Vector(*[float(v) for v in p1])
    length = (b - a).Length
    if length <= 0 or max(d0, d1) <= 0:
        raise ValueError("cylinder/cone needs two different end points and a positive diameter")
    if abs(d0 - d1) < 1e-9:
        return _wp(cq.Solid.makeCylinder(d0 / 2, length, a, b - a))
    return _wp(cq.Solid.makeCone(d0 / 2, d1 / 2, length, a, b - a))


def prism(axis, points, lo, hi):
    """prism(axis, points, lo, hi) -> a flat outline pushed straight along a world axis.
    axis is 'X', 'Y' or 'Z'. points is the closed outline as 2D corners in the other two world
    coordinates, in alphabetical order: axis 'Z' -> (x, y), axis 'Y' -> (x, z), axis 'X' -> (y, z).
    The solid spans lo..hi along the axis, e.g. an L-profile 60 mm long in X:
    prism('X', [(0, 0), (40, 0), (40, 8), (8, 8), (8, 30), (0, 30)], 0, 60)."""
    import cadquery as cq

    k = "XYZ".index(axis.strip().upper())
    others = [i for i in range(3) if i != k]
    lo, hi = sorted((float(lo), float(hi)))
    if hi - lo <= 0 or len(points) < 3:
        raise ValueError("prism needs at least three points and lo < hi")
    pts3 = []
    for p in points:
        v = [0.0, 0.0, 0.0]
        v[others[0]], v[others[1]], v[k] = float(p[0]), float(p[1]), lo
        pts3.append(cq.Vector(*v))
    face = cq.Face.makeFromWires(cq.Wire.makePolygon(pts3, close=True))
    direction = [0.0, 0.0, 0.0]
    direction[k] = hi - lo
    return _wp(cq.Solid.extrudeLinear(face, cq.Vector(*direction)))


def revolve(axis, through, profile):
    """revolve(axis, through, profile) -> a turned (lathe) solid. The rotation axis is the line
    through the world point `through` along `axis` ('X', 'Y' or 'Z'). profile is the half outline
    as (radius, position) pairs, position being the world coordinate along the axis; it is closed
    onto the axis for you. A stepped shaft along Z through (30, 30, 0):
    revolve('Z', (30, 30, 0), [(10, 0), (10, 40), (6, 40), (6, 90)])."""
    import cadquery as cq

    k = "XYZ".index(axis.strip().upper())
    r_dir = [0.0, 0.0, 0.0]
    r_dir[(k + 1) % 3] = 1.0
    prof = [(max(float(r), 0.0), float(h)) for r, h in profile]
    if len(prof) < 2:
        raise ValueError("revolve needs at least two (radius, position) pairs")
    closed = [(0.0, prof[0][1])] + prof + [(0.0, prof[-1][1])]
    pts = []
    for r, h in closed:
        v = [float(c) for c in through]
        v[k] = h
        v = [a + r * b for a, b in zip(v, r_dir)]
        if not pts or (cq.Vector(*v) - pts[-1]).Length > 1e-7:
            pts.append(cq.Vector(*v))
    if len(pts) < 3:
        raise ValueError("revolve profile encloses no area")
    face = cq.Face.makeFromWires(cq.Wire.makePolygon(pts, close=True))
    base = [float(c) for c in through]
    tip = list(base)
    tip[k] += 1.0
    return _wp(cq.Solid.revolve(face, 360.0, cq.Vector(*base), cq.Vector(*tip)))


def polar(solid, axis, through, count):
    """polar(solid, axis, through, count) -> a list of `count` copies of `solid`, turned evenly
    around the line through the world point `through` along `axis` (the first copy is the solid
    itself). Pass the list to union(...) or cut(body, ...): ribs, fins, bolt bosses."""
    import cadquery as cq

    a = _axis(axis)
    base = cq.Vector(*[float(c) for c in through])
    tip = base + cq.Vector(*a)
    shape = _shape(solid)
    return [_wp(shape.rotate(base, tip, 360.0 * i / int(count))) for i in range(int(count))]


def union(*solids):
    """union(a, b, c, ...) -> one solid made of all of them (lists are accepted). Pieces must
    overlap or share a face; pieces that only touch along an edge stay separate."""
    shapes = [_shape(s) for s in _flat(solids)]
    if not shapes:
        raise ValueError("union of nothing")
    out = shapes[0]
    if len(shapes) > 1:
        out = out.fuse(*shapes[1:]).clean()
    return _wp(out)


def cut(body, *tools):
    """cut(body, a, b, ...) -> body with every tool removed (lists are accepted). A tool may
    stick out of the body; only the overlap is removed."""
    shapes = [_shape(s) for s in _flat(tools)]
    out = _shape(body)
    if shapes:
        out = out.cut(*shapes).clean()
    return _wp(out)


def common(a, b):
    """common(a, b) -> the part of space that is in both a and b."""
    return _wp(_shape(a).intersect(_shape(b)).clean())
