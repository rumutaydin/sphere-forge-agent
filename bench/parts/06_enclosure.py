PROMPT = """An open-top electronics enclosure. Outer size 100 mm (X) by 60 mm (Y) by 40 mm (Z), centred in X and Y with the base on Z=0. The four vertical outer edges are rounded with an 8 mm radius. Walls and floor are 3 mm thick and the top is completely open."""
import cadquery as cq
result = (cq.Workplane("XY").box(100, 60, 40, centered=(True, True, False))
          .edges("|Z").fillet(8).faces(">Z").shell(-3))
