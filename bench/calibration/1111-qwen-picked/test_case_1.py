import cadquery as cq
import math

# ---- dimensions (mm) ----
XW       = 19.0     # part width in X
Yplate   = 14.0     # plate thickness in Y
Zlen     = 50.8     # part length in Z
rib_tip  = 19.0     # rib tip in Y (14 + 5)
rib_proj = 5.0      # rear rib projection

rec_R    = 12.7     # front recess radius (D25.4)
rec_cz   = 25.4     # recess axis Z (mid height)
rec_cy   = 7.0      # recess axis Y (mid thickness)
rec_depth= 9.15     # blind pocket depth from front face (Y) -> rear wall ~4.85

rib_R    = 12.5     # rib concave-edge radius (D25.0)
xhalf    = 9.5      # half width in X
rib_band = 16.0     # central Z band of rear rib (edge-to-edge height)

hole_d   = 6.75
hole_z1  = 6.35
hole_z2  = 44.45

# rib concave-edge geometry (axes parallel to Y, centred X = 9.5)
rib_sag   = math.sqrt(rib_R**2 - xhalf**2)
rib_top_c = 25.4 + rib_band / 2.0
rib_bot_c = 25.4 - rib_band / 2.0
Zc_top    = rib_top_c + rib_sag
Zc_bot    = rib_bot_c - rib_sag

# ---- 1. main plate ----
plate = (cq.Workplane("XY")
         .center(xhalf, Yplate / 2.0)
         .rect(XW, Yplate)
         .extrude(Zlen))

# ---- 2. front recess (blind pocket, axis parallel to X) ----
rec_cyl = (cq.Workplane("YZ")           # normal +X, local x=Y, local y=Z
           .center(rec_cy, rec_cz)
           .circle(rec_R)
           .extrude(XW))                # cylinder X 0..19
cap_box = (cq.Workplane("XY")           # front band Y 0..rec_depth
           .center(XW / 2.0, rec_depth / 2.0)
           .rect(XW, rec_depth)
           .extrude(Zlen))
front_pocket = rec_cyl.intersect(cap_box)
plate = plate.cut(front_pocket)

# ---- 3. rear rib (concave top/bottom, axes parallel to Y) ----
rib_thk = rib_proj + 0.5                # overlap 0.5 into plate for clean fuse
rib_box = (cq.Workplane("XZ")           # normal -Y, local x=X, local y=Z
           .center(xhalf, 25.4)
           .rect(XW, rib_band)
           .extrude(-rib_thk))          # Y 0..thk
top_circ = (cq.Workplane("XZ")
            .center(xhalf, Zc_top)
            .circle(rib_R)
            .extrude(-rib_thk))
bot_circ = (cq.Workplane("XZ")
            .center(xhalf, Zc_bot)
            .circle(rib_R)
            .extrude(-rib_thk))
rib = rib_box.cut(top_circ).cut(bot_circ)
rib = rib.translate(cq.Vector(0, Yplate - 0.5, 0))   # Y 13.5..19

# ---- final single solid ----
result = plate.union(rib)

# ---- 4. mounting through-holes (axis along Y) ----
for zc in (hole_z1, hole_z2):
    h = (cq.Workplane("XZ")
         .center(xhalf, zc)
         .circle(hole_d / 2.0)
         .extrude(-Yplate - 2.0))        # Y 0..16, through the plate
    result = result.cut(h)

# --- bores from facts.json (added by forge) ---
from forge.library.facts_tools import cut_listed_holes as _cut_listed_holes
result = _cut_listed_holes(result, [{'diameter': 6.75, 'axis': 'Y', 'count': 2, 'lengths': [14.0], 'centres': [[9.5, 7.0, 6.35], [9.5, 7.0, 44.45]]}], extend=False)
