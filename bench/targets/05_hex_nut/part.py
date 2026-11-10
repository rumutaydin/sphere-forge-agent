PROMPT = """A hexagonal nut: a regular hexagonal prism 30 mm across corners (two corners lie on the X axis), 12 mm thick from Z=0 to Z=12, with a 16 mm diameter through hole along the Z axis."""
import cadquery as cq
result = cq.Workplane("XY").polygon(6, 30).extrude(12).cut(cq.Workplane("XY").circle(8).extrude(12))
