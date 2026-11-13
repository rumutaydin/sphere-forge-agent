PROMPT = """A solid pleated part with 24 pleats. Base disc is 80 mm diameter, 8 mm thick (z 0..8). A 24-point star frustum exists from z 8..50. At z=8, tip radius is 36 mm; at z=50, tip radius is 24 mm. Groove bottoms are at 75% of the tip radius. One tip points along the +X axis. Top disc is 50 mm diameter, 6 mm thick (z 50..56). The part is fully solid with no holes."""
import cadquery as cq
import math

def make_star_polygon(n_points, tip_radius, groove_ratio, start_angle_deg=0.0):
    """Create a star polygon wire with n_points tips and groove bottoms."""
    vertices = []
    start_angle_rad = math.radians(start_angle_deg)
    for i in range(n_points):
        angle = start_angle_rad + 2 * math.pi * i / n_points
        # Tip vertex
        x_tip = tip_radius * math.cos(angle)
        y_tip = tip_radius * math.sin(angle)
        vertices.append((x_tip, y_tip))
        # Groove vertex (between tips)
        groove_radius = tip_radius * groove_ratio
        angle_groove = start_angle_rad + 2 * math.pi * (i + 0.5) / n_points
        x_groove = groove_radius * math.cos(angle_groove)
        y_groove = groove_radius * math.sin(angle_groove)
        vertices.append((x_groove, y_groove))
    return vertices

# Base disc: diameter 80mm, z 0..8
base_disc = (cq.Workplane("XY").center(0, 0)
             .circle(80 / 2)
             .extrude(8))

# Top disc: diameter 50mm, z 50..56
top_disc = (cq.Workplane("XY").center(0, 0)
            .circle(50 / 2)
            .extrude(6)
            .translate((0, 0, 50)))

# Star frustum: 24-point star, z 8..50
# At z=8: tip radius 36mm, groove at 75% = 27mm
# At z=50: tip radius 24mm, groove at 75% = 18mm
# One tip on +X (start_angle = 0)
star_bottom_vertices = make_star_polygon(24, 36, 0.75, 0.0)
star_top_vertices = make_star_polygon(24, 24, 0.75, 0.0)

# Create wires at correct Z positions
w_bottom = cq.Wire.makePolygon(
    [cq.Vector(x, y, 8) for x, y in star_bottom_vertices],
    close=True
)
w_top = cq.Wire.makePolygon(
    [cq.Vector(x, y, 50) for x, y in star_top_vertices],
    close=True
)

# Loft between the two star polygons
frustum_solid = cq.Solid.makeLoft([w_bottom, w_top], ruled=True)
frustum = cq.Workplane("XY").add(frustum_solid)

# Union all three parts (Solid, no hollowing)
result = base_disc.union(top_disc).union(frustum)
