import math
import cadquery as cq

# ---- given dimensions (brief / facts) ----
flange_R   = 70.0     # Ø140 bottom flange
flange_h   = 27.5     # flange thickness z 0..27.5
cone_R_bot = 60.0     # Ø120 cone base at z=27.5
cone_R_top = 26.5     # Ø53 cone top at z=109
cone_h     = 81.5     # cone height 27.5..109
cap_R      = 36.5     # Ø73 cap
cap_h      = 27.5     # cap thickness 109..136.5
round_R    = 10.0     # four outer R10 rounds
bore_R     = 15.0     # Ø30 blind bore
bore_depth = 17.5     # blind depth from z=0

# ---- estimated dimensions (search-tuned) ----
r_c = 15  # FIT 15..25   groove crease (apex) radius
groove_half_ang = 10  # FIT 5..10    half opening angle of each V groove (deg)
n_grooves       = 16     # 16 fins: 4 on cardinals + equally spaced
R_out           = 80.0   # groove cutter outer extent (beyond cone surface)

# ---- derived ----
cap_z   = flange_h + cone_h          # 109
top_z   = cap_z + cap_h              # 136.5
pitch   = 360.0 / n_grooves          # 22.5
goff    = pitch / 2.0                # 11.25 (offset so fins land on cardinals)
g_z0    = flange_h                   # 27.5
g_z1    = cap_z                      # 109
g_h     = g_z1 - g_z0                # 81.5

# ---- base solid (axisymmetric, axis at world origin) ----
flange = cq.Solid.makeCylinder(flange_R, flange_h)
cone   = cq.Solid.makeCone(cone_R_bot, cone_R_top, cone_h).translate(cq.Vector(0, 0, flange_h))
cap    = cq.Solid.makeCylinder(cap_R, cap_h).translate(cq.Vector(0, 0, cap_z))
base   = flange.fuse(cone).fuse(cap)

# ---- R10 rounds on the four outer circular edges ----
def _is_round_edge(e):
    if e.geomType() != 'CIRCLE':
        return False
    c = e.Center()
    r = e.Length() / (2.0 * math.pi)
    tol = 0.6
    if abs(r - flange_R) < tol:
        return abs(c.z) < tol or abs(c.z - flange_h) < tol
    if abs(r - cap_R) < tol:
        return abs(c.z - cap_z) < tol or abs(c.z - top_z) < tol
    return False

try:
    base = cq.Workplane("XY").newObject([base]).edges(_is_round_edge).fillet(round_R).val()
except Exception:
    pass

# ---- 16 radial V-grooves (sunburst) ----
groove_solid = None
for k in range(n_grooves):
    thc = math.radians(goff + k * pitch)
    th1 = thc - math.radians(groove_half_ang)
    th2 = thc + math.radians(groove_half_ang)
    ax  = r_c   * math.cos(thc)
    ay  = r_c   * math.sin(thc)
    x1  = R_out * math.cos(th1)
    y1  = R_out * math.sin(th1)
    x2  = R_out * math.cos(th2)
    y2  = R_out * math.sin(th2)

    cutter = (cq.Workplane("XY")
               .workplane(offset=g_z0)
               .moveTo(x1, y1)
               .lineTo(x2, y2)
               .lineTo(ax, ay)
               .close()
               .extrude(g_h)
               .val())
    groove_solid = cutter if groove_solid is None else groove_solid.fuse(cutter)

base = base.cut(groove_solid)

# ---- Ø30 blind bore on bottom face ----
bore = cq.Solid.makeCylinder(bore_R, bore_depth)
base = base.cut(bore)

# ---- translate so bounding-box min corner is at the origin ----
result = base.translate(cq.Vector(70.0, 70.0, 0.0))