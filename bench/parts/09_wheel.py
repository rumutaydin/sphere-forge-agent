PROMPT = """A wheel blank centred on the Z axis: a disc 80 mm in diameter and 8 mm thick on Z=0, with a 24 mm diameter hub rising to Z=16. A 10 mm bore goes through the centre. Five 16 mm lightening holes pass through the disc, equally spaced on a circle of radius 26 mm, the first on the +X axis."""
import cadquery as cq
body = cq.Workplane("XY").circle(40).extrude(8).union(cq.Workplane("XY").circle(12).extrude(16))
bore = cq.Workplane("XY").circle(5).extrude(16)
holes = cq.Workplane("XY").polarArray(26, 0, 360, 5).circle(8).extrude(8)
result = body.cut(bore).cut(holes)
