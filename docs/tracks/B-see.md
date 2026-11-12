# Track B — See

**In plain words:** nobody gives us the answer file, so you build the instruments that
tell the agent whether a part is right: numbers from `facts.json`, and outlines from the
eight views. Everything you build is used twice: by the critic to fix a part, and by
the selector to pick the best candidate. This is the track for a 3D-vision background.

```mermaid
flowchart LR
    V["8 target views"] --> SIL["silhouette masks"]
    SIL --> CMP["compare with our render,<br/>view by view"]
    SIL --> HULL["visual hull<br/>(carve a voxel block)"]
    F["facts.json"] --> CHK["numeric self-check"]
    CMP --> SS["self-score + issue list"]
    CHK --> SS
    HULL --> SS
    HULL --> FB["better fallback than a box"]
    SS --> C["Track C: critic and selection"]
```

## You own

`forge/facts.py` `forge/render.py` `forge/geometry.py` `forge/stages/understand.py`
`forge/vision.py` (new, yours to create)

## Numbers you move

| Number | How to read it | Now | Target |
|---|---|---|---|
| Self-score vs leaderboard | rank correlation over our submissions | unmeasured | a higher self-score reliably means a higher leaderboard score |
| Silhouette agreement on a correct part | mean IoU over 8 views, our render of an answer vs its views | not built | above 0.98 |
| Fallback score | leaderboard with fallbacks only | box, about 0.3 | visual hull, 0.5 or more |

## Backlog, in order

1. **Silhouette masks from the target views.** Background is plain white; the part is
   tan with black outline strokes. Threshold, clean up, done. Check all 72 practice images.
2. **Match their framing.** To compare outlines, our render must frame the part as
   theirs does. Work out their rule from the practice views (the bounding box in
   `facts.json` gives real sizes): is each view fitted on its own, or is one scale used
   for all eight? Then make `forge/render.py` reproduce it, and render masks directly
   from triangles (the point-splat renderer is for model eyes, not for measurement).
3. **Silhouette IoU per view** between target mask and our mask. Add it to the
   self-check: per-view scores and a line per bad view ("top view: 0.71, extra material
   at lower left"). A difference image (red = missing, blue = extra) is the most useful
   thing a critic can be shown; make one sheet of eight.
4. **Visual hull.** Start from a voxel block of the facts' bounding box. For each of the
   six axis views, clear every voxel whose projection falls outside the silhouette; then
   the two isometric views. The result has the exact size and keeps every through-hole
   visible along an axis. Uses:
   - **pseudo-target**: score a candidate against the hull with `forge/score.py`
     (a correct part lies inside the hull and fills most of it);
   - **fallback**: turn the hull into one valid STEP solid and submit it when the agent
     fails. The slide says a convex shrink-wrap scores 0.51; a hull with holes should do
     better than that. Converting voxels or a mesh into a clean solid is the hard part:
     try extruding the axis silhouettes and intersecting the three prisms in CadQuery,
     which gives a B-rep directly;
   - **prior for the plan**: where is the mass, which views show holes.
5. **Holes from views.** Count enclosed background regions in each axis silhouette and
   compare with `through_holes_genus`. Tells the planner which holes go through, along
   which axis, and roughly where; the hole inventory in the facts gives exact diameters.
6. **Calibrate the self-score.** Once several submissions have leaderboard values,
   check which ingredients (volume ratio, area ratio, silhouette IoU, hull IoU) track
   it, and reweight `self_check`.
7. **Gap filling for complex parts.** Find what the brief leaves out (compare its
   feature list against the facts' face counts and hole inventory) and ask the model
   targeted questions about named views. Crop and enlarge the region first.
8. **Depth cues (speculative).** Shading in the views encodes surface orientation.
   Probably not worth the time; the outlines carry most of the signal.

## Search terms

silhouette extraction, shape from silhouette, visual hull, space carving, voxel carving,
orthographic projection, silhouette IoU, chamfer distance between contours, difference
image, rasterising triangles to a mask, connected components / hole counting in a binary
image, Euler number of a binary image, marching cubes, mesh to B-rep, sewing faces into
a solid (OpenCASCADE BRepBuilderAPI_Sewing), intersection of extruded profiles,
contour tracing to polyline, polygon simplification (Douglas–Peucker), analysis by
synthesis, render-and-compare, differentiable rendering.

## Traps

- Trusting volume and area alone. Two different shapes can share both.
- Comparing outlines with mismatched framing: every part will look wrong by a few pixels.
- A hull fallback that is not a single valid solid. That scores 0, worse than a box.
  Always validate with the backend and keep the box as the last resort.
- The isometric views: their exact camera angle is "from +X, -Y, +Z"; confirm it is the
  (1, -1, 1) diagonal before carving with them.

## Lab notes

Append one line per experiment: date, idea, number before → after, kept or dropped.

- 11 Nov: self-score vs leaderboard on seven built parts: gap 0.00–0.27, all in shape. Silhouette check is now the top item; calibration files in `bench/calibration/`.
- 12 Nov: framing solved: the projected bounding box is fitted into 985 of 1024 px and centred in all eight views; outline stroke is 1 px outside the edge. Silhouette IoU of an exact part against its views 0.985 → 0.997. Kept (`forge/vision.py`).
- 12 Nov: silhouette IoU vs leaderboard shape points on 16 calibration files: rank correlation 0.93 (volume ratio 0.95, area ratio 0.76). The gate in the old plan (beat the volume ratio) was not passed on its own; `0.14 + 0.16 holes + 0.62 volume ratio × IoU` predicts the leaderboard with leave-one-out error 0.07 and is what selection uses. Kept as `forge/compile.py: estimate`.
- 12 Nov: visual hull as B-rep (5 prisms): true local score on our 12 reference parts 0.499 (boxes) → 0.921. Hollow parts fail: enclosure 0.68, elbow 0.53. Kept.
- 12 Nov: faces that bores start from, free space on the line of sight removed (`forge/layers.py: carve_mouth_faces`): practice estimate 0.773 → 0.794. Kept.
- 12 Nov: depth of flat faces by plane sweep into the isometric view (`face_depths`, `carve_layers`): finds part 5's front face at 22.24 mm (exact), but no gain on the practice parts and accidental matches on small regions. Not wired in; needs the renderer of task B1 to test against answers.
- 12 Nov: today's tasks are B1–B4 in `docs/PLAN.md`.
- 12 Nov: depth sweep with a plain-sight test (a point with no hull between it and the isometric camera must show the face's shade): true local score on our reference parts 0.920 → 0.949, enclosure 0.682 → 0.991, no part lower; practice estimate unchanged (0.793 → 0.794). Kept, wired into pass 1 as `hull-depth`.
- 12 Nov: edge score (line drawing of our part against the strokes of the views, `forge/vision.py: edge_score`). Within-part rank correlation with the leaderboard over 72 part scores: estimate 0.68, edge score 0.78 (without boxes 0.48 against 0.65). It flags 6 of the 7 model or carving results that lost points. Kept as a veto on model bodies (`FORGE_EDGE_VETO=0.015`); not yet used for cuts.
- 12 Nov: radial patterns on turned parts (`forge/layers.py: carve_radial`): the stroke drawing of the axis view repeats n times (part 6: 18; parts 2, 3, 4, 8: none), the flat faces seen between the fins are copied to all n positions and the space above removed, then grooves narrowing with the profile are tried and kept if the edge score rises. Part 6: edge score 0.18 → 0.32 (the best model body: 0.25, leaderboard 0.662), volume x3.23 → x2.84, estimate 0.489 → 0.516. Takes 225 s on that part. Wired into pass 1 as `revolve-radial`. Pass 1 now writes each body before the next source runs, after one container run lost part 6 to a crash and handed in a box.
- 12 Nov, leaderboard for `12`: 0.871, the best so far. Part 6 with the radial grooves: 0.610 → 0.685 (the best model body had 0.662), from code alone and repeatable. All other parts as in `11`.
- 12 Nov, pockets from contradicted lids (`carve_pockets`, T11): estimate part 7 0.618 → 0.658, others unchanged; reference parts local score 0.949 → 0.949; kept, leaderboard pending. Bench renderer now uses the depth buffer (the painter's order drew wrong faces).
- 12 Nov, leaderboard for `14-pockets`: 0.871 → 0.877; part 7 0.706 → 0.755, others unchanged. Kept.
