PROMPT = """A conical pleated filter element on the Z axis. A solid 110 mm diameter base disc 12 mm thick (Z=0 to 12) and a solid 60 mm diameter top disc 12 mm thick (Z=88 to 100) are joined by a pleated conical sheet 1.5 mm thick with 12 pleats: the pleat tips run from radius 52 mm at the base disc to radius 28 mm at the top disc, the pleat valleys lie at 0.7 of the tip radius. The inside of the pleated cone is hollow and closed by the two discs."""
import math
import cadquery as cq

def star(r_tip, k=0.7, n=12):
    pts = []
    for i in range(2 * n):
        r = r_tip if i % 2 == 0 else k * r_tip
        a = math.pi * i / n
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts

def cone(r0, r1, z0, z1):
    return (cq.Workplane("XY").workplane(offset=z0).polyline(star(r0)).close()
            .workplane(offset=z1 - z0).polyline(star(r1)).close().loft(ruled=True))

outer = cone(52, 28, 12, 88)
inner = (cq.Workplane("XY").workplane(offset=12).polyline(star(52)).close().offset2D(-1.5)
         .workplane(offset=76).polyline(star(28)).close().offset2D(-1.5).loft(ruled=True))
sheet = outer.cut(inner)
base = cq.Workplane("XY").circle(55).extrude(12)
top = cq.Workplane("XY").workplane(offset=88).circle(30).extrude(12)
result = base.union(sheet).union(top)
