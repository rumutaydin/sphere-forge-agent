import cadquery as cq

# ---- Dimensions from the brief / facts (all given) ----
AX = 105.79          # rotation axis X  (211.59 / 2)
AY = 114.3           # rotation axis Y  (from Ø88.9 centre in facts)

D_SNOUT = 76.2       # end journal diameter
L_SNOUT = 92.71      # end journal length (each end)
D_MAIN = 88.9        # main journal diameter
L_MAIN = 379.46      # main journal length (Z 92.71 -> 472.17)
L_TOTAL = 564.88     # overall length

D_PIN = 101.6        # crank pin diameter
L_PIN = 87.54        # crank pin axial length

WEB_THK = 54.62      # counterweight web thickness in Z
WEB_WID = 76.2       # counterweight web width (rounded outer end Ø76.2)
WEB_LEN = 63.5       # web straight length = throw offset (axis -> pin centre)

# throw: (angle_deg about Z, pin centre X, pin centre Y, pin Z-centre)
THROWS = [
    (270, 105.79, 50.8, 136.48),   # lowest,  -> -Y
    (150,  50.8, 146.05, 282.44),  # middle,  -> -X/+Y
    ( 30, 160.79, 146.05, 428.4),  # top,     -> +X/+Y
]

def zcyl(x, y, r, z0, L):
    """Z-axis cylinder, base at z0, height L, centred at (x,y)."""
    return cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(r).extrude(L)

# ---- 1. Stepped central shaft ----
shaft = (
    zcyl(AX, AY, D_SNOUT / 2, 0.0, L_SNOUT)
    .union(zcyl(AX, AY, D_MAIN / 2, L_SNOUT, L_MAIN))
    .union(zcyl(AX, AY, D_SNOUT / 2, L_SNOUT + L_MAIN, L_SNOUT))
)

# ---- 2. Local counterweight web (axis at origin, radial dir = +X) ----
web_box = cq.Workplane("XY").center(WEB_LEN / 2, 0).box(WEB_LEN, WEB_WID, WEB_THK)
web_end = (
    cq.Workplane("XY").workplane(offset=-WEB_THK / 2)
    .center(WEB_LEN, 0).circle(WEB_WID / 2).extrude(WEB_THK)
)
web_local = web_box.union(web_end)

# ---- 3. Combine everything ----
result = shaft
for (ang, px, py, pz) in THROWS:
    pin = zcyl(px, py, D_PIN / 2, pz - L_PIN / 2, L_PIN)
    web = web_local.rotate((0, 0, 0), (0, 0, 1), ang).translate((AX, AY, pz))
    result = result.union(pin).union(web)

# single solid, no fillets (cosmetic blends dropped for robustness)
result = result