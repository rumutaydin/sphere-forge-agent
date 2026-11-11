import cadquery as cq

# ---- dimensions (all from brief) ----
cy = 66.04          # axis centre, world Y
cz = 66.04          # axis centre, world Z
bore_r = 38.10      # central bore Ø76.2 / 2
main_r = 63.50      # main sleeve OD Ø127.0 / 2
flange_r = 66.04    # flange OD Ø132.08 / 2
main_len = 19.05    # main sleeve length (X 0 -> 19.05)
flange_len = 2.54   # flange thickness (X 19.05 -> 21.59)
total_len = 21.59   # overall length / bore length

# ---- main sleeve outer cylinder (along +X, from X=0) ----
main = (cq.Workplane("YZ")
        .center(cy, cz)
        .circle(main_r)
        .extrude(main_len))

# ---- flange / collar outer cylinder (from X=19.05) ----
flange = (cq.Workplane("YZ")
          .workplane(offset=main_len)
          .center(cy, cz)
          .circle(flange_r)
          .extrude(flange_len))

# ---- fuse into one stepped solid ----
body = main.union(flange)

# ---- central through-bore (cut all the way through) ----
bore = (cq.Workplane("YZ")
        .center(cy, cz)
        .circle(bore_r)
        .extrude(total_len))

# ---- final part ----
result = body.cut(bore)

# --- bores from facts.json (added by forge) ---
from forge.library.facts_tools import cut_listed_holes as _cut_listed_holes
result = _cut_listed_holes(result, [{'diameter': 76.2, 'axis': 'X', 'count': 1, 'lengths': [21.59], 'centres': [[10.8, 66.04, 66.04]]}], extend=True)
