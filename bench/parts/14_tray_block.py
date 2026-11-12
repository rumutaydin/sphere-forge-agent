PROMPT = """A tray block 120 mm (X) by 80 mm (Y) by 50 mm (Z), base on Z=0. Its vertical outer edges are rounded with a 10 mm radius. The top face carries a rounded-rectangle pocket 35 mm deep that leaves 4 mm thick side walls. Two 20 mm through holes along Z go through the pocket floor at X=35 and X=85, Y=40."""
import cadquery as cq
body = cq.Workplane("XY").box(120, 80, 50, centered=False).edges("|Z").fillet(10)
pocket = (cq.Workplane("XY").workplane(offset=15).center(60, 40).rect(112, 72).extrude(40)
          .edges("|Z").fillet(6))
result = body.cut(pocket)
for x in (35, 85):
    result = result.cut(cq.Workplane("XY").center(x, 40).circle(10).extrude(50))
