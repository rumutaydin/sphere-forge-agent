PROMPT = """A solid duct transition piece: a 60 mm (X) by 40 mm (Y) rectangle on Z=0 lofted smoothly to a 30 mm diameter circle at Z=50, both centred on the Z axis."""
import cadquery as cq
result = cq.Workplane("XY").rect(60, 40).workplane(offset=50).circle(15).loft(combine=True)
