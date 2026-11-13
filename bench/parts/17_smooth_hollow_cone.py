PROMPT = """A hollow smooth cone with no grooves. A plain frustum with radius 45 mm at z=0 and radius 25 mm at z=60. A top disc of diameter 60 mm sits on top (z 60..68). The part is hollowed with a uniform 3 mm wall thickness. A blind bore of 12 mm diameter and 6 mm depth is cut into the bottom face on the axis."""
import cadquery as cq
import math

# Bottom frustum: radius 45mm at z=0, radius 25mm at z=60
# Create using loft of two circles
circle_bottom = cq.Wire.makeCircle(45, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
circle_top = cq.Wire.makeCircle(25, cq.Vector(0, 0, 60), cq.Vector(0, 0, 1))

frustum_solid = cq.Solid.makeLoft([circle_bottom, circle_top], ruled=True)
frustum = cq.Workplane("XY").add(frustum_solid)

# Top disc: diameter 60mm (radius 30mm), z 60..68
top_disc = (cq.Workplane("XY").center(0, 0)
            .circle(60 / 2)
            .extrude(8)
            .translate((0, 0, 60)))

# Union frustum and top disc
solid = frustum.union(top_disc)

# Make hollow with 3mm wall (negative thickness for inward shell)
hollow = solid.shell(-3)

# Cut blind bore: 12mm diameter, 6mm deep on bottom face (extrude UP from z=0 to z=6)
bore = (cq.Workplane("XY").center(0, 0)
        .circle(12 / 2)
        .extrude(6))

result = hollow.cut(bore)
