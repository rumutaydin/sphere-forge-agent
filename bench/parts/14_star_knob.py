PROMPT = """A solid star knob with a 12-point star cross-section. The frustum has tip radius 30 mm at z=0 and 20 mm at z=40, with groove bottoms at 70% of the tip radius. One tip points along +Y. On top is a solid round cap of 36 mm diameter from z=40 to z=48. The part is fully solid with no cavity. A through hole of 8 mm diameter runs along the Z axis."""
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

# Star frustum: 12-point star, z 0..40
# At z=0: tip radius 30mm, groove at 70% = 21mm
# At z=40: tip radius 20mm, groove at 70% = 14mm
# One tip along +Y (start_angle = pi/2)
star_bottom_vertices = make_star_polygon(12, 30, 0.7, math.pi / 2)
star_top_vertices = make_star_polygon(12, 20, 0.7, math.pi / 2)

# Create wires at correct Z positions using cq.Wire.makePolygon
w_bottom = cq.Wire.makePolygon(
    [cq.Vector(x, y, 0) for x, y in star_bottom_vertices],
    close=True
)
w_top = cq.Wire.makePolygon(
    [cq.Vector(x, y, 40) for x, y in star_top_vertices],
    close=True
)

# Loft between the two star polygons using Solid.makeLoft
frustum_solid = cq.Solid.makeLoft([w_bottom, w_top], ruled=True)
frustum = cq.Workplane("XY").add(frustum_solid)

# Round cap: diameter 36mm from z=40 to z=48
cap = (cq.Workplane("XY").center(0, 0)
       .circle(36 / 2)
       .extrude(8)
       .translate((0, 0, 40)))

# Union frustum and cap
solid = frustum.union(cap)

# Cut through hole: 8mm diameter along Z axis (extrude through entire part with margin)
hole = (cq.Workplane("XY").center(0, 0)
        .circle(8 / 2)
        .extrude(53))  # Extrude from z=0 to z=53 (past top at z=48)

result = solid.cut(hole)
