PROMPT = """A bearing pillow block. The base is 100 mm (X) by 30 mm (Y) by 12 mm thick, centred in X and Y on Z=0. On top of it, an upright block 50 mm wide in X and the full 30 mm deep in Y rises to a total height of 50 mm, centred on the base. A 25 mm diameter bore passes through the upright along the Y axis, with its axis at height Z=32 above the base plane and x=0. Two 9 mm vertical mounting holes go through the base at (38, 0) and (-38, 0)."""
import cadquery as cq
base = cq.Workplane("XY").box(100, 30, 12, centered=(True, True, False))
upright = cq.Workplane("XY").box(50, 30, 50, centered=(True, True, False))
bore = cq.Workplane("XZ").center(0, 32).circle(12.5).extrude(15, both=True)
mounts = cq.Workplane("XY").pushPoints([(38, 0), (-38, 0)]).circle(4.5).extrude(12)
result = base.union(upright).cut(bore).cut(mounts)
