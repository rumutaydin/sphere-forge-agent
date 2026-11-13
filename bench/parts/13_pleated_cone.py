PROMPT = """A hollow pleated cone with a 16-point star cross-section. Bottom flange is a 110 mm diameter disc, 14 mm thick (z 0..14). Top cap is a 50 mm diameter disc, 12 mm thick with top at z=100 (z 88..100). Between them (z 14..88) is a pleated frustum with 16 V-grooves around the axis. Star tips lie on a cone of radius 48 mm at z=14 and 22 mm at z=88. Groove bottoms are at 60% of the tip radius at each height. One tip points along +X. The entire part is hollow with a uniform 3 mm wall thickness. A blind bore of 20 mm diameter and 10 mm depth is cut into the bottom face on the axis."""
import cadquery as cq
import math

def make_star_polygon(n_points, tip_radius, groove_ratio, start_angle=0.0):
    """Create a star polygon wire with n_points tips and groove bottoms."""
    vertices = []
    for i in range(n_points):
        angle = start_angle + 2 * math.pi * i / n_points
        # Tip vertex
        x_tip = tip_radius * math.cos(angle)
        y_tip = tip_radius * math.sin(angle)
        vertices.append((x_tip, y_tip))
        # Groove vertex (between tips)
        groove_radius = tip_radius * groove_ratio
        angle_groove = start_angle + 2 * math.pi * (i + 0.5) / n_points
        x_groove = groove_radius * math.cos(angle_groove)
        y_groove = groove_radius * math.sin(angle_groove)
        vertices.append((x_groove, y_groove))
    return vertices

# Bottom flange: disc diameter 110mm, 14mm thick (z 0..14)
flange = (cq.Workplane("XY").center(0, 0)
          .circle(110 / 2)
          .extrude(14))

# Top cap: disc diameter 50mm, 12mm thick, top at z=100 (so z 88..100)
cap = (cq.Workplane("XY").center(0, 0)
       .circle(50 / 2)
       .extrude(12)
       .translate((0, 0, 88)))

# Pleated frustum: 16-point star, z 14..88
# At z=14: tip radius 48mm, groove at 60% = 28.8mm
# At z=88: tip radius 22mm, groove at 60% = 13.2mm
# One tip along +X (start_angle = 0)
star_bottom_vertices = make_star_polygon(16, 48, 0.6, 0.0)
star_top_vertices = make_star_polygon(16, 22, 0.6, 0.0)

# Create wires at correct Z positions using cq.Wire.makePolygon
w_bottom = cq.Wire.makePolygon(
    [cq.Vector(x, y, 14) for x, y in star_bottom_vertices],
    close=True
)
w_top = cq.Wire.makePolygon(
    [cq.Vector(x, y, 88) for x, y in star_top_vertices],
    close=True
)

# Loft between the two star polygons using Solid.makeLoft
frustum_solid = cq.Solid.makeLoft([w_bottom, w_top], ruled=True)
frustum = cq.Workplane("XY").add(frustum_solid)

# Union all three parts
solid = flange.union(cap).union(frustum)

# Make hollow with 3mm wall
hollow = solid.shell(-3)

# Cut blind bore: 20mm diameter, 10mm deep on bottom face (extrude UP from z=0 to z=10)
bore = (cq.Workplane("XY").center(0, 0)
        .circle(20 / 2)
        .extrude(10))

result = hollow.cut(bore)
