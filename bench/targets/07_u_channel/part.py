PROMPT = """A U-channel 120 mm long along X, 40 mm wide (Y) and 30 mm tall (Z), centred in X and Y with its base on Z=0. A 30 mm wide, 25 mm deep slot open at the top runs the full length, leaving 5 mm side walls and a 5 mm floor. Two 6 mm holes go through the floor at (40, 0) and (-40, 0)."""
import cadquery as cq
body = cq.Workplane("XY").box(120, 40, 30, centered=(True, True, False))
slot = cq.Workplane("XY").workplane(offset=5).box(120, 30, 25, centered=(True, True, False))
holes = cq.Workplane("XY").pushPoints([(40, 0), (-40, 0)]).circle(3).extrude(5)
result = body.cut(slot).cut(holes)
