import cadquery as cq

# ---- given envelope ----
Xmin, Xmax = 0.0, 508.0
Ymin, Ymax = 0.0, 85.73
Zmin, Zmax = 0.0, 165.1
end_round = 25.4          # X–Z end corner radius (brief)
back_wall = 2.54          # back wall = Ø127 opening depth (brief)

# ---- estimated (searched) walls ----
tab_depth = 9.833  # FIT 8..30   Y of front face / tab boss depth
front_wall = 15.33  # FIT 8..30   front wall thickness
side_wall = 40  # FIT 20..80  side (X) wall thickness
bot_wall = 55.0           # FIT 30..120 bottom (Z) wall thickness
top_wall = 35.0           # top wall (kept fixed)

# ---- tab geometry (read from views) ----
tab_xs = [47.6, 193.65, 339.7, 485.75]
tab_w = 32.0              # X width of a tab
tab_z0, tab_z1 = 100.0, 160.0
notch_r = 19.0
notch_z = 130.0

# ---- top pocket geometry (read from top view) ----
pocket_xs = [120.35, 266.4, 412.45]
poc_w, poc_d = 40.0, 30.0   # X, Y extent
poc_depth = 12.0
poc_hole_d = 5.11

def rounded_y_box(x0, x1, y0, y1, z0, z1, r):
    b = cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0)
    b = b.translate(((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0))
    b = b.edges("|Y").fillet(r)
    return b

# ---- main body (front face at Y = tab_depth) ----
body = rounded_y_box(Xmin, Xmax, tab_depth, Ymax, Zmin, Zmax, end_round)

# ---- four side tabs on the front face ----
for tx in tab_xs:
    tab = cq.Workplane("XY").box(tab_w, tab_depth, tab_z1 - tab_z0)
    tab = tab.translate((tx, tab_depth / 2.0, (tab_z0 + tab_z1) / 2.0))
    body = body.union(tab)

# ---- semicircular notch on each tab outer (Y=0) face, axis X ----
for tx in tab_xs:
    notch = cq.Workplane("YZ").circle(notch_r).extrude(tab_w)
    notch = notch.translate((tx - tab_w / 2.0, 0.0, notch_z))
    body = body.cut(notch)

# ---- internal cavity (hollows the cover) ----
cav = rounded_y_box(
    side_wall, Xmax - side_wall,
    tab_depth + front_wall, Ymax - back_wall,
    bot_wall, Zmax - top_wall,
    max(1.0, end_round - side_wall)
)
body = body.cut(cav)

# ---- three shallow rounded-rect top pockets + blind central hole ----
for px in pocket_xs:
    pk = cq.Workplane("XY", origin=(0, 0, Zmax)).rect(poc_w, poc_d).extrude(-poc_depth)
    pk = pk.translate((px, (Ymin + Ymax) / 2.0, 0))
    body = body.cut(pk)
    ch = cq.Workplane("XY", origin=(0, 0, Zmax)).circle(poc_hole_d / 2.0).extrude(-10.0)
    ch = ch.translate((px, (Ymin + Ymax) / 2.0, 0))
    body = body.cut(ch)

result = body

# --- bores from facts.json (added by forge) ---
from forge.library.facts_tools import cut_listed_holes as _cut_listed_holes
result = _cut_listed_holes(result, [{'diameter': 5.11, 'axis': 'Y', 'count': 14, 'lengths': [16.51], 'centres': [[89.87, 30.49, 102.87], [150.83, 30.49, 102.87], [235.92, 30.49, 102.87], [296.88, 30.49, 102.87], [381.97, 30.49, 102.87], [442.93, 30.49, 102.87], [193.65, 8.26, 149.23], [193.65, 8.26, 111.13], [47.6, 8.26, 149.23], [47.6, 8.26, 111.13], [339.7, 8.26, 111.13], [339.7, 8.26, 149.23]], 'more_not_listed': 2}, {'diameter': 28.0, 'axis': 'Y', 'count': 6, 'lengths': [7.62], 'centres': [[235.92, 26.04, 82.55], [381.97, 26.04, 82.55], [442.93, 26.04, 82.55], [296.88, 26.04, 82.55], [89.87, 26.04, 82.55], [150.83, 26.04, 82.55]]}, {'diameter': 6.35, 'axis': 'Y', 'count': 6, 'lengths': [18.67, 18.84, 18.87, 18.9, 18.98], 'centres': [[150.83, 39.3, 82.55], [89.87, 39.18, 82.55], [296.88, 39.34, 82.55], [442.93, 39.28, 82.55], [381.97, 39.18, 82.55], [235.92, 39.27, 82.55]]}, {'diameter': 127.0, 'axis': 'Y', 'count': 3, 'lengths': [2.54], 'centres': [[412.45, 84.46, 82.55], [120.35, 84.46, 82.55], [266.4, 84.46, 82.55]]}, {'diameter': 12.7, 'axis': '(-0.00, 0.91, 0.42)', 'count': 3, 'lengths': [10.7], 'centres': [[266.7, 81.02, 43.04], [412.75, 81.02, 43.04], [120.65, 81.02, 43.04]]}, {'diameter': 25.4, 'axis': 'X', 'count': 1, 'lengths': [457.15], 'centres': [[266.68, 0.0, 130.18]]}], extend=True)
