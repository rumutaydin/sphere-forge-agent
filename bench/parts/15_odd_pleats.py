PROMPT = """A hollow pleated part with 9 pleats, wider at the top. Bottom disc is 44 mm diameter, 10 mm thick (z 0..10). Top disc is 96 mm diameter, 10 mm thick (z 70..80). Between them (z 10..70) is a 9-point star frustum. At z=10, tip radius is 20 mm; at z=70, tip radius is 46 mm. Groove bottoms are at 50% of the tip radius. The first tip is rotated 10 degrees from the +X axis. The part is hollowed with a uniform 4 mm wall thickness. A blind bore of 16 mm diameter and 8 mm depth is cut into the bottom face on the axis."""
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

# Bottom disc: diameter 44mm, z 0..10
bottom_disc = (cq.Workplane("XY").center(0, 0)
               .circle(44 / 2)
               .extrude(10))

# Top disc: diameter 96mm, z 70..80
top_disc = (cq.Workplane("XY").center(0, 0)
            .circle(96 / 2)
            .extrude(10)
            .translate((0, 0, 70)))

# Star frustum: 9-point star, z 10..70
# At z=10: tip radius 20mm, groove at 50% = 10mm
# At z=70: tip radius 46mm, groove at 50% = 23mm
# First tip at 10 degrees from +X
star_bottom_vertices = make_star_polygon(9, 20, 0.5, 10.0)
star_top_vertices = make_star_polygon(9, 46, 0.5, 10.0)

# Create wires at correct Z positions
w_bottom = cq.Wire.makePolygon(
    [cq.Vector(x, y, 10) for x, y in star_bottom_vertices],
    close=True
)
w_top = cq.Wire.makePolygon(
    [cq.Vector(x, y, 70) for x, y in star_top_vertices],
    close=True
)

# Loft between the two star polygons
frustum_solid = cq.Solid.makeLoft([w_bottom, w_top], ruled=True)
frustum = cq.Workplane("XY").add(frustum_solid)

# Union all three parts
solid = bottom_disc.union(top_disc).union(frustum)

# Make hollow with 4mm wall (negative thickness for inward shell)
hollow = solid.shell(-4)

# Cut blind bore: 16mm diameter, 8mm deep on bottom face (extrude UP from z=0 to z=8)
bore = (cq.Workplane("XY").center(0, 0)
        .circle(16 / 2)
        .extrude(8))

result = hollow.cut(bore)
