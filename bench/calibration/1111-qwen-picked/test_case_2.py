import cadquery as cq

# ---- Given / derived dimensions (mm) ----
head_od          = 53.34          # brief + facts
R_h              = head_od / 2.0  # 26.67 head outer radius
head_rim_t       = 1.27           # brief + facts (rim band, Y 0..1.27)
stem_d           = 6.36           # brief + facts
R_s              = stem_d / 2.0   # 3.18 stem radius
stem_len         = 66.35          # brief + facts
stem_y0          = 17.955         # stem straight start (facts centre 51.13 - len/2)
stem_y1          = 84.305         # stem straight end (51.13 + len/2)
overall_len      = 85.55          # brief + facts
axis_x           = 26.67          # mid X of bounding box
axis_z           = 26.67          # mid Z of bounding box

# ---- Estimated dimensions (brief does not state) ----
rim_chamfer = 0.3  # FIT 0.3..0.8   45 deg leg on both rim edges
tip_chamfer      = 1.245          # derived: overall_len - stem_y1 (45 deg)

# Dish arc control points (radial, axial) in the revolve workplane
A_r,  A_y  = R_h - rim_chamfer, head_rim_t            # back rim corner
B_r,  B_y  = R_s, stem_y0                            # stem root
dish_mid_r = 14.08
dish_mid_y = 4.51

# ---- Build the half-profile in the XY workplane (X=radial, Y=axial) ----
wp = (
    cq.Workplane("XY")
    .moveTo(0.0, 0.0)
    .lineTo(R_h - rim_chamfer, 0.0)               # flat front face
    .lineTo(R_h, rim_chamfer)                     # front rim 45 deg chamfer
    .lineTo(R_h, head_rim_t - rim_chamfer)        # outer rim cylinder
    .lineTo(R_h - rim_chamfer, head_rim_t)        # back rim 45 deg chamfer -> A
    .threePointArc((dish_mid_r, dish_mid_y), (B_r, B_y))  # concave dish
    .lineTo(R_s, stem_y1)                         # straight stem
    .lineTo(R_s - tip_chamfer, overall_len)       # stem tip 45 deg chamfer
    .lineTo(0.0, overall_len)                     # flat tip to axis
    .lineTo(0.0, 0.0)                             # axis line
    .close()
)

# Revolve 360 deg about the local Y line (world Y through origin)
solid = wp.revolve(360, (0, 0, 0), (0, 1, 0))

# Move the revolution axis to (axis_x, *, axis_z) so the bbox min corner is the origin
result = solid.translate((axis_x, 0.0, axis_z))