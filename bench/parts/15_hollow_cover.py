PROMPT = """A closed hollow cover box 160 mm (X) by 60 mm (Y) by 90 mm (Z), base on Z=0, with 6 mm thick walls all round and a sealed inner cavity. The four vertical outer edges are rounded with a 12 mm radius. Three 30 mm through holes along Y pass through both large walls at Z=45 and X=40, 80, 120."""
import cadquery as cq
body = cq.Workplane("XY").box(160, 60, 90, centered=False).edges("|Z").fillet(12)
void = cq.Workplane("XY").box(148, 48, 78, centered=False).translate((6, 6, 6)).edges("|Z").fillet(6)
result = body.cut(void)
for x in (40, 80, 120):
    result = result.cut(cq.Workplane("XZ").center(x, 45).circle(15).extrude(-60))
