PROMPT = """A stepped shaft along the Z axis with its base at Z=0: 30 mm diameter for the first 40 mm, then 20 mm diameter for 30 mm, then 12 mm diameter for the last 20 mm (90 mm total). The outer circular edge at the bottom end and at the top end each have a 1 mm 45-degree chamfer."""
import cadquery as cq
s = cq.Workplane("XY").circle(15).extrude(40)
s = s.union(cq.Workplane("XY").workplane(offset=40).circle(10).extrude(30))
s = s.union(cq.Workplane("XY").workplane(offset=70).circle(6).extrude(20))
result = s.faces("<Z").edges().chamfer(1).faces(">Z").edges().chamfer(1)
