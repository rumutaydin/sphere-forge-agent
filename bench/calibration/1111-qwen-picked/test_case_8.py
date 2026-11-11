import cadquery as cq

# ---- exact dimensions from brief ----
H = 40.2          # overall height Z
W = 80.0          # overall width X
L = 128.0         # overall length Y

# Figure-eight window
win_r = 22.225    # lobe radius (D44.45/2)
win_cx = 40.0
win_cy = 72.95
win_dy = 18.0     # half-offset between lobe centres in Y

# Central web (full Y-length to ensure connectivity)
web_w = 56.0      # X = 12 to 68

# Mounting feet
foot_w = 22.0     # each foot is 22 mm wide (X=0..22, X=58..80)
foot_l = 22.0     # feet extend Y=0..22
foot_cham = 6.0   # 45-degree outer-front corner chamfer

# Flange side lobes (extend web width locally)
side_lobe_r = 9.0
side_lobe_x = 16.0  # left; right is W - side_lobe_x = 64

# 12 mm half-cylinder end-face features (concave recesses on top edges)
sc_r = 6.0
sc_depth = 12  # FIT 4..12

# Main transverse bore
bore_r = 10.0   # D20

# Cross holes
cross_r = 2.1   # D4.2

# Front-face blind holes
front_r = 3.0   # D6
front_depth = 4.0

# ---- helpers ----
def zcyl(x, y, r, h=H):
    """Cylinder along Z, base at Z=0, centred at (x, y)."""
    return cq.Workplane("XY").circle(r).extrude(h).translate((x, y, 0))

def xcyl(y, z, r, length=W):
    """Cylinder along X, from X=0, centred at (y, z)."""
    return (cq.Workplane("XY").circle(r).extrude(length)
            .rotate((0, 0, 0), (0, 1, 0), 90)
            .translate((0, y, z)))

def ycyl(x, y0, z, r, length):
    """Cylinder along +Y, from Y=y0, centred at (x, z)."""
    return (cq.Workplane("XY").circle(r).extrude(length)
            .rotate((0, 0, 0), (1, 0, 0), -90)
            .translate((x, y0, z)))

# ---- main body: central web (full Y-length) ----
body = cq.Workplane("XY").box(web_w, L, H).translate((W / 2, L / 2, H / 2))

# Left foot: X=0..22, Y=0..22 (overlaps web in X=12..22, Y=0..22)
body = body.union(
    cq.Workplane("XY").box(foot_w, foot_l, H).translate((foot_w / 2, foot_l / 2, H / 2))
)

# Right foot: X=58..80, Y=0..22 (overlaps web in X=58..68, Y=0..22)
body = body.union(
    cq.Workplane("XY").box(foot_w, foot_l, H).translate((W - foot_w / 2, foot_l / 2, H / 2))
)

# Flange side lobes (extend web beyond X=12 / X=68 at Y=72.95)
body = body.union(zcyl(side_lobe_x, win_cy, side_lobe_r))
body = body.union(zcyl(W - side_lobe_x, win_cy, side_lobe_r))

# Additional flange lobes (mostly inside web, harmless unions)
for (lx, ly, lr) in [
    (40.0, 122.0, 6.0),
    (18.79, 113.21, 7.0), (61.21, 113.21, 7.0),
    (18.79, 32.69, 7.0),  (61.21, 32.69, 7.0),
    (40.0, 23.9, 7.0),
]:
    body = body.union(zcyl(lx, ly, lr))

# 45-degree chamfers on outer-front corners of the feet
cham_l = (cq.Workplane("XY")
          .polyline([(0, 0), (foot_cham, 0), (0, foot_cham)])
          .close().extrude(H))
cham_r = (cq.Workplane("XY")
          .polyline([(W, 0), (W - foot_cham, 0), (W, foot_cham)])
          .close().extrude(H))
body = body.cut(cham_l).cut(cham_r)

# ---- central figure-eight through window (two overlapping lobes, axis Z) ----
body = body.cut(zcyl(win_cx, win_cy + win_dy, win_r))
body = body.cut(zcyl(win_cx, win_cy - win_dy, win_r))

# ---- main transverse bore (D20, axis X, centred at Y=72.95, Z=20.1) ----
body = body.cut(xcyl(win_cy, 20.1, bore_r))

# ---- cross holes (D4.2, axis X) ----
for (hy, hz) in [(85.45, 32.6), (85.45, 7.6), (60.45, 7.6), (60.45, 32.6)]:
    body = body.cut(xcyl(hy, hz, cross_r))

# ---- front-face blind holes (D6, axis Y, depth 4 from Y=0) ----
for (hx, hz) in [(4.62, 9.0), (4.62, 31.2), (75.38, 31.2), (75.38, 9.0)]:
    body = body.cut(ycyl(hx, 0.0, hz, front_r, front_depth))

# ---- 12 mm concave recesses on top edges (axis Y) ----
# Front face (Y=0): one recess at centreline
body = body.cut(ycyl(40.0, 0.0, H, sc_r, sc_depth))
# Back face (Y=128): three recesses
for x in [18.79, 40.0, 61.21]:
    body = body.cut(ycyl(x, L - sc_depth, H, sc_r, sc_depth))

# ---- safety trim (remove any stray geometry below Z=0) ----
body = body.cut(
    cq.Workplane("XY").box(200, 200, 10).translate((W / 2, L / 2, -5))
)

result = body