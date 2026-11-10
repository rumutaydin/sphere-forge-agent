PROMPT = """A pipe flange centred on the Z axis. A disc of 100 mm diameter and 10 mm thickness sits on Z=0. A concentric hub of 40 mm diameter rises from the disc to a total height of 30 mm. A 20 mm bore runs through everything along Z. Six 9 mm bolt holes pass through the disc, equally spaced on a 75 mm pitch circle, the first one on the +X axis."""
import cadquery as cq
body = cq.Workplane("XY").circle(50).extrude(10).union(cq.Workplane("XY").circle(20).extrude(30))
bore = cq.Workplane("XY").circle(10).extrude(30)
bolts = cq.Workplane("XY").polarArray(37.5, 0, 360, 6).circle(4.5).extrude(10)
result = body.cut(bore).cut(bolts)
