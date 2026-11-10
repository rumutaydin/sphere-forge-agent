PROMPT = """A heat sink. The base plate is 60 mm by 60 mm and 5 mm thick, centred in X and Y on Z=0. Eight straight fins stand on it, each 2 mm thick in X, 60 mm long in Y and 20 mm tall (so the total height is 25 mm). The fin centres are 8 mm apart in X, from x=-28 to x=28."""
import cadquery as cq
result = cq.Workplane("XY").box(60, 60, 5, centered=(True, True, False))
for i in range(8):
    fin = cq.Workplane("XY").box(2, 60, 21, centered=(True, True, False)).translate((-28 + 8 * i, 0, 4))
    result = result.union(fin)
