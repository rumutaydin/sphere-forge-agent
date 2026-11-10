PROMPT = """A 90-degree pipe elbow with 20 mm outer diameter and 14 mm inner diameter. The centreline starts at the origin heading in +Z, bends through 90 degrees on a 40 mm radius in the XZ plane, and ends at (40, 0, 40) heading in +X."""
import cadquery as cq
# Annulus on the XY plane at the origin, revolved 90 degrees about the Y-parallel axis through (40, 0, 0).
result = cq.Workplane("XY").circle(10).circle(7).revolve(90, (40, 0, 0), (40, 1, 0))
