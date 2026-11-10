from __future__ import annotations

import math

import cadquery as cq


def spur_gear(module: float, teeth: int, width: float, bore: float = 0.0,
              pressure_angle: float = 20.0) -> cq.Workplane:
    """spur_gear(module, teeth, width, bore=0, pressure_angle=20) -> cq.Workplane
    Involute spur gear, axis on Z, bottom face on Z=0, one tooth centred on +X.
    Pitch diameter = module * teeth. Outer diameter = module * (teeth + 2).
    Root diameter = module * (teeth - 2.5). `bore` is the through-hole diameter.
    If only the outer diameter D and tooth count are known: module = D / (teeth + 2).
    """
    alpha = math.radians(pressure_angle)
    r_pitch = module * teeth / 2
    r_base = r_pitch * math.cos(alpha)
    r_tip = r_pitch + module
    r_root = r_pitch - 1.25 * module
    r_start = max(r_base, r_root)  # the involute only exists outside the base circle

    def inv(phi: float) -> float:
        return math.tan(phi) - phi

    def half_angle(r: float) -> float:
        # Half the tooth's angular thickness at radius r.
        return math.pi / (2 * teeth) + inv(alpha) - inv(math.acos(min(1.0, r_base / r)))

    radii = [r_start + (r_tip - r_start) * i / 7 for i in range(8)]
    pts = []
    for k in range(teeth):
        mid = 2 * math.pi * k / teeth
        flank = [(r, half_angle(r)) for r in radii]
        if r_root < r_start:  # radial segment from the root circle up to the base circle
            flank.insert(0, (r_root, half_angle(r_start)))
        for r, h in flank:
            pts.append((r * math.cos(mid - h), r * math.sin(mid - h)))
        for r, h in reversed(flank):
            pts.append((r * math.cos(mid + h), r * math.sin(mid + h)))
    gear = cq.Workplane("XY").polyline(pts).close().extrude(width)
    if bore > 0:
        gear = gear.cut(cq.Workplane("XY").circle(bore / 2).extrude(width))
    return gear
