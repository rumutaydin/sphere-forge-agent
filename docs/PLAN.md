# Plan v5, Thu 12 Nov, 21:45 (supersedes v4 below; v4 kept for its task notes)

## The leaderboard says our architecture is capped

| Rank | Team | Mean | 4 | 5 | 6 | 7 | 9 |
|---|---|---|---|---|---|---|---|
| 1 | team-a | 0.988 | 0.998 | 0.972 | 0.999 | 0.945 | 0.982 |
| 2 | team-f | 0.979 | 0.999 | 0.963 | 0.999 | 0.883 | 0.988 |
| 3 | team-b | 0.976 | 0.999 | 0.981 | 1.000 | 0.849 | 0.972 |
| **4** | team-e | **0.928** | 0.966 | 0.896 | 0.927 | 0.777 | 0.857 |
| 5 | team-d | 0.895 | 0.963 | 0.883 | 0.707 | 0.774 | 0.831 |
| 7 | **us** (`14`) | 0.877 | 0.913 | 0.838 | 0.685 | 0.755 | 0.831 |

Three teams score 0.999-1.000 on part 6 (16 V-grooves, 72 spline faces). A visual hull cannot
do that; an exact parametric program can. Brief 6 gives every dimension except the fin count
(top view: 16) and the groove depth, and facts.json gives volume, surface area, face count and
face types, which pin the rest. **The top teams write the whole part as a program and check it
against the facts; we trace a hull and let the model add a body that is then trimmed by the
hull.** Small tuning of the hull path cannot reach 0.93 (top 4).

What limits our model pass today (`forge/stages/build.py`): nine helper solids only, no fillets
or chamfers ("leave out edge rounds"), "ten to thirty solids", output trimmed by the pixel hull
(faceted surfaces), selected by an estimate that cannot see inside the outline, thinking off,
3 calls per part, about 8 of the 60 minutes used.

## Architecture v6: generators and one judge (decided 12 Nov, 23:30)

Stop layering on the hull. Every add-on since `06` (cut lists, veto, shell, pockets, fill)
moved the leaderboard by +-0.01 and added a guard; all of them modify the hull, so the hull's
limit (~0.88) is ours. New structure:

1. **Spec** from the brief (P0): bbox, volume, through-holes, bores. facts.json only for testing.
2. **Independent generators**, each a complete solid, none trims another: `retrieval` (Fusion 360
   Gallery, seconds, R1), `exact program` (model + report rounds, V1), `hull` (pass 1, frozen:
   no more carving work), `box`.
3. **One judge, tiers not a fitted estimate:** retrieved part with views matching (worst IoU ~0.98)
   > exact program passing the gate > model body (today's rules) > hull > box. The margin/veto/estimate rules stay only for
   choosing among hull variants.
4. **Cost order:** retrieval first; a retrieved part gets no model call. Hull always runs in
   parallel as the net. Model time only for parts not retrieved.
5. Model bodies stay ON (`FORGE_CANDIDATES=3`, thinking off) in the first combined run, as a tier
   between exact programs and the hull (they beat the hull only under today's margin/veto rules).
   Reason: the only model gain proven on the leaderboard (part 4, +0.06, twice). Drop them after
   that submission if exact programs take part 4 or bodies win nothing.

Open: part 6's stated volume is below its own flange+cap volume (V1 lab note). Measure the real
volume of retrieved parts against the briefs before trusting the volume gate.

Extended set (20 parts, briefs + views + facts, no answers): after the merge, run the pipeline on
them on the team's other compute (brief-only inputs, facts.json removed), then score the outputs
against the real facts and views here. This is our closest stand-in for the hidden set.

## P0 (BEFORE V1): hidden parts come WITHOUT facts.json

The organisers' extended practice set (`~/Downloads/extended-practice.zip`, 20 parts with briefs,
views and facts, no answers) says in its README: "Inputs to your pipeline: images/, context.png
(if present) and description.md. Nothing else is available for hidden parts." Today, with no
facts.json, `forge/run.py: pass1` returns None and the box fallback has no size: **on the hidden
parts we would output nothing or boxes.** Fix: build facts from the brief (`**Envelope:** X x Y x Z
mm; volume V cm^3; N through-passages` is uniform across all 29 briefs; bores from the feature
bullets, by regex and, if the endpoint is up, one JSON extraction call). Surface area, face counts
and face types are NOT derivable: nothing may require them. Test: practice and extended parts
with facts.json hidden; compare parsed facts with the real ones; no-model outputs scored against
the real facts. Number: no-model self-score with parsed facts vs with real facts.

GPU budget: about $25 of credit left at 22:30; keep $5-10 for the judging run (the organisers use
our endpoint after the freeze). Start the instance only for a finished, combined run; stop it at once.

## V1. Exact-program path (Track C + shared; the one big change)

A second kind of model candidate, in parallel with the body candidates, never trimmed by the hull:

1. **Prompt:** the whole brief, the facts, the eight views. Write the complete part in CadQuery
   (raw cadquery allowed, plus the helpers), world frame (bbox min at origin), every feature of
   the brief including bores, fillets and chamfers, with every free dimension as a named
   variable at the top. Thinking on (medium, 16k).
2. **Objective report** after each run, from facts and views only: bbox per axis, volume ratio,
   surface-area ratio, through-hole count, face count and face-type histogram, silhouette IoU per
   view and *where* each view differs (mm ranges of extra/missing material).
3. **Rounds:** the report goes back to the model; up to 3 revisions per candidate, the best
   version kept.
4. **Acceptance (strict, objective):** replaces the floor only if bbox within 1%, holes exact,
   volume within 4%, area within 8%, worst-view silhouette IoU high (calibrate the bar on the
   answers in `bench/cases`: the answer must pass, the hull must not). Otherwise the floor stays,
   so the path can only lose where the bar is wrong.
5. **Budget:** pass 1 ~8 min, then this path with the rest of the hour; report wall-clock.

Number: leaderboard of parts 4, 5, 6, 9 (top teams 0.96-1.00, we 0.68-0.91). Target mean >= 0.93.

## V2. Fit the free parameters to the facts (after V1 runs)

The model declares `PARAMS = {name: (lo, hi)}` for the dimensions the brief does not give;
code searches them (coordinate descent, about 20 runs) to match volume and area, then the
silhouettes. Part 6's groove depth is exactly this.

## Kept from v4

Freeze checklist (T10 and "Do not forget before the freeze") still applies. The 27B on
`clinical-ivory-barnacle` stays the model.

# Plan v4, Thu 12 Nov, midday

Replaces plan v3. State: [HANDOFF.md](HANDOFF.md). Numbers and the twelve lessons from
the leaderboard: [SCOREBOARD.md](SCOREBOARD.md). Code freeze: **Fri 13 Nov, 08:00**.
A new session can start from this page alone.

## Where we are

| | Leaderboard |
|---|---|
| boxes (11 Nov) | 0.320 |
| hand-picked model parts (11 Nov) | 0.658 |
| no model at all (`01`) | 0.847 |
| no model, with face and depth carving (`06`) | 0.856 |
| the same plus the model pass (`05`, our best) | **0.870** |
| the same with helper-API bodies and cut lists (`09`) | 0.863 |
| radial grooves on part 6 (`12`) | 0.871 |
| pockets where a view contradicts a flat lid (`14`, **our best, on `main`**) | **0.877** |
| best value per part across all submissions | 0.882 (a ceiling, not a run) |

Dimensions and holes are exact on all nine parts. Everything left is **shape inside
the outline**, and almost all of it is in three parts: 6 (0.61–0.66), 7 (0.68–0.71),
9 (0.83–0.84). Parts 5 and 4 are at 0.84–0.91; parts 1, 2, 3, 8 at 0.92–0.99.

## The clean configuration (on `main` after submission `10`)

```
FORGE_THINKING=off FORGE_CANDIDATES=3 FORGE_CARVE=0 FORGE_MODEL_MARGIN=0.02 FORGE_WORKERS=9 FORGE_BUDGET_S=3000
```

Pass 1 (no model): hull or revolve, face carving, depth sweep, bores to the hole count.
Pass 2: three bodies per part written with the helper solids
(`forge/library/solids.py`), thinking off, envelope repair, hole search on model
bodies. A model body replaces the no-model part only if its estimate is higher by 0.02
and its outer dimensions are not worse. No cut lists. One real run in Docker: about 160 s.
Approach `10-clean-bodies-nothink` is that run.

Why each choice, from the leaderboard: cut lists sum to zero over three runs with ±0.05
swings; thinking is not needed for the one reliable model gain (part 4, +0.063 either
way); small estimated gains were noise.

## What is wrong with parts 6, 7 and 9 (looked at the views and at our solids)

| Part | What the real part is | What we output | Why the code misses it |
|---|---|---|---|
| 6 | a cone whose side is cut by 16 deep V grooves running **up the cone**; seen from the top it is a 16-point star | a smooth cone made of stacked rings, volume ×3.2 | the outline is a disc from the top and a cone from the side, so the revolve looks perfect to every silhouette; the grooves exist only as strokes and shades inside the outline. The rings are the pixel steps of the revolved outline, not a feature |
| 7 | a top flange that is an **open tray** (deep pocket, thin walls), a neck, and a thin tilted plate with a boss; empty space between flange and plate | flange and plate fused into one block, tray filled, volume ×1.9 | three axis outlines cannot separate a thin plate from the block behind it; the tray floor is partly curved, so the depth sweep (flat faces only) finds little |
| 9 | two cylinder banks, each with a recessed head-plate tray around its three bores | one bank has its tray, the other does not, volume ×1.23 | face carving needs a view that sees the bank face head-on; one bank is edge-on to both isometric cameras |

The vertical stripes on our solids are a different thing: outlines traced from pixels
become many short flat faces. The scorer barely minds (parts 1 and 3 score 0.99), but
the files are large and ugly (task T9).

## Tasks, in the order I would do them

Each is one to three hours, offline unless marked GPU, and ends in one number.
"Measure" commands: `uv run pytest -q`, `uv run python scripts/compile_all.py --tag <t>`
(nine practice parts, no model, 7 min on the laptop), `uv run python
scripts/bench_layers.py --tag <t>` (12 reference parts with answers).

### T1. An edge score: see inside the outline (built 12 Nov; first use wired in)

**Result.** `forge/vision.py: edge_score` draws our part as lines (where the surface normal
turns by more than 28° or the depth jumps, from a real depth buffer) and compares them with
the strokes of the eight views. Tested on the 72 part scores of eight submissions
(`scripts/calibrate_edges.py`, 4.5 min):

| Within a part, rank correlation with the leaderboard | estimate | edge score |
|---|---|---|
| all variants | 0.68 | **0.78** |
| without the boxes | 0.48 | **0.65** |

On the 21 cases where a model result or a carving step replaced the floor and the
leaderboard moved: the estimate said "better" every time (7 were worse). The edge score
flagged 6 of those 7 losses (all but part 5's face carving) and wrongly flagged 5 of the
14 gains, three of them changes under 0.005. So it is a **veto**, not a replacement: a
model body is refused if its edge score is more than 0.015 below the no-model part's
(`FORGE_EDGE_VETO`). Replayed on those cases, that avoids 0.082 of losses and gives up
0.027 of gains. It costs about 17 s per check at 1024 px.

**Still to do with it:** (a) use it as the acceptance test for cuts in
`forge/layers.py` and for T2–T4, where it should rise when a groove or tray lands in the
right place; (b) it scores 0.70 on an exact part because the views also stroke smooth
seams we do not draw: find what those are; (c) make it faster (512 px, or only the views
a change touches).

What the task was:

Our estimate compares outlines and volume. It cannot tell a groove in the right place
from one in the wrong place, which is why it promised +0.36 for `09` and the leaderboard
gave +0.06. The views do show the inside: every face border is a black stroke.
Build `forge/vision.py: edge_score(step, task)`: render our part with
`forge/render.py: render_organiser_style` in the eight views, take the stroke maps of
both, and score their agreement (share of target stroke pixels within 2–3 px of ours and
the reverse, as an F-score). **Test before use:** `bench/approaches/*/` holds 7
submissions × 9 parts with a leaderboard value each (`scores.json` → `cases` →
`leaderboard`). For each part, does the edge score rank the 7 variants as the
leaderboard does, better than `estimate` does? Report both rank correlations. If yes:
put it into `forge/compile.py: estimate`, and into the checks of every cut and every
model body. Number: rank correlation with the leaderboard within a part.

### T2. Part 6: radial patterns (Track C)

**Built 12 Nov** (`forge/layers.py: carve_radial`, body source `revolve-radial`): edge
score on part 6 0.18 → 0.32, volume ×3.23 → ×2.84; leaderboard value in approach `12`.
Open: the grooves are only as deep as the top view shows at the flange (valley at 51 of
70 mm), yet the volume says far more is empty; view 7 shows thin fins with deep gaps.
Try deeper valleys higher up, judged by the edge score. It also takes 225 s; the checks
(17 s each) are the cost.

What the task was:

Count the pattern from the top view: sample the stroke image on a circle around the
axis and take the strongest period (16 here). Then cut one V wedge and repeat it with
`polar` (`forge/library/solids.py`); the wedge's inner and outer radius come from where
the strokes start and end in the top view, its depth from T1's edge score or from the
facts' volume. Trigger on "the axis view is a disc and its strokes repeat n-fold", never
on the part. Number: part 6 volume ratio ×3.2 → below ×1.3; leaderboard 0.61 → ?

### T3. Part 7: the tray and the space behind the plate (Track B)

Print `forge.layers.face_depths` for part 7's top view and see why the tray floor is
not taken (curved floor fails the flat-shade test; try accepting a region whose shade
varies smoothly). Then the general case: a point is empty if **any** view sees
something behind it. With T1's renderer we can render depth too; compare where our
solid hides a stroke that the target view shows. Number: part 7 volume ratio ×1.9 → ?

### T4. Part 9: the other bank (Track C)

The carved bank proves the tray; the other bank is its mirror image shifted 25.4 mm in
X (the brief says so, and the bore lists of the two banks show it). Detect "two bore
patterns that are mirror images of each other" in the facts and apply each face cut
found on one to the other, checked like every cut. Number: part 9 volume ×1.23 → ?

### T5. Model ablation (GPU; Robin's teammate is setting up a bigger model)

The pipeline talks to any OpenAI-compatible endpoint that accepts images:

```bash
export OPENAI_BASE_URL=http://<host>:8000/v1 OPENAI_API_KEY=<key> OPENAI_MODEL=<model id>
FORGE_THINKING=off FORGE_CANDIDATES=3 FORGE_CARVE=0 \
  nohup uv run python -m forge eval --inputs artifacts/inputs --tag a-<model>-bodies \
  -o runs/<model> > runs/<model>.log 2>&1 &
uv run python scripts/save_approach.py 1x-<model> runs/<model>/outputs "what it is"
```

`FORGE_THINKING=off` sends Qwen's chat-template switch; for another model family set
`FORGE_THINKING=on` and, if it thinks, `FORGE_MAX_TOKENS=16000 FORGE_LLM_TIMEOUT_S=700`.
Compare with Qwen3.8-27B on the same settings: bodies that run at the first try (19 of
21), bodies that beat the no-model part (3–4 of 7 parts), and above all the
**leaderboard** values of parts 4, 5, 6, 7, 9, because the local estimate cannot rank
model bodies. With the helper API the model no longer needs to know CadQuery, so this
measures spatial ability. The current endpoint must stay up as the fallback until a new
one has beaten it on a submission.

### T6. A vision model as a classifier, not a modeller

The pipeline's model already sees the views; a second, smaller one adds nothing by
itself. What does work is asking for **discrete answers that code can check**: "do the
grooves run along the axis or around it", "how many fins", "is the top face a tray".
Each answer selects a code recipe (T2, T3), and the recipe's result is checked against
the views (T1). Cheap to try once T1 exists: one call per part, thinking off.

### T7. A real benchmark from the Fusion 360 Gallery Assembly dataset

We think the nine practice parts come from it; that is not confirmed. Two uses, very
different:
- **Fine:** take 30–50 parts from it, render them with `render_organiser_style`, write
  `facts.json` for each (`forge/facts.py: facts_from_measure`, plus a bore list), and
  score our pipeline against the real STEP with `forge/score.py`. That gives a true
  local score on realistic parts, which is the thing we lack most. Number: local score
  on that set, per tier.
- **Ask the organisers first:** looking the hidden parts up in the dataset and returning
  the stored solid. That is retrieving the answers, not building them, and a re-run
  review would show it. Do not build it without a clear yes.

### T8. Another scripting language (build123d): not recommended now

The model no longer writes CadQuery; it writes calls to nine helper functions, and
errors fell from 80 to 2. A different kernel API behind the helpers changes nothing the
model sees.

### T9. Smoother outlines (Track C)

Fit lines and arcs to the traced outlines (`forge/vision.py: mask_polygons`) so round
faces are cylinders again. Smaller files, cleaner solids, maybe a little surface score.
Measure the surface term on `scripts/bench_nomodel.py`.

### T10. Freeze checklist (Track A, Thursday evening)

- [ ] the final configuration is the Dockerfile's `FORGE_*` line, and `artifacts/outputs`
      was produced by one run of that image
- [ ] port 8000 public, `team-g.env` with the public address, tested from outside the tunnel
- [ ] `docker run --cpus 4`: pass 1 still inside `FORGE_PASS1_S`
- [ ] the organisers answered: is `facts.json` in the hidden set; how strictly is a re-run compared
- [ ] Brev credit lasts through judging; instance not stopped after the address is handed over
- [ ] three slides: approach (code first, model second), numbers (0.32 → 0.87), cost (a minute per run without the model)

## Do not forget before the freeze (agreed 12 Nov, 14:40 UTC; 17 hours left then)

The ranking is decided on nine hidden parts, run by the organisers from our image against
our endpoint. Each of these can cost everything, and none needs new research:

- [ ] `main` holds the configuration we want to ship (today: approach `12`, 0.871, one real Docker run)
- [ ] the model endpoint is **public** (today it is only reachable through Robin's SSH tunnel),
      the handover env file has the public address, tested from a machine outside the tunnel
- [ ] asked the organisers: do the hidden parts come with `facts.json`? (without it pass 1 has no bounding box)
- [ ] asked the organisers: how many CPU cores does the container get? then `docker run --cpus <n>` once
- [ ] the instance that serves the final model stays up, with credit, through judging
- [ ] if a second model is adopted: it beat the 27B on a submission first, and the 27B stays up until then

Where the points are (after 10 submissions): floor 0.856, best 0.871, best value per part
0.877. Headroom is the interior shape of parts 6 (0.685), 7 (0.706), 5 (0.838), 9 (0.831).

### T11. Incremental extrusion: depth for every region of every view (next, no GPU)

**Built 12 Nov as `forge/layers.py: carve_pockets`** (body source `hull-pockets`, switches
`FORGE_POCKETS`, `FORGE_POCKETS_S` 150, `FORGE_POCKET_DEPTH` 0.75). Splitting a view into
regions by its strokes does not work on our views (strokes are 1 px and leak; part 7's top
view came out as one region). The same idea from the other side does: in an isometric view
all flat faces with one normal have one shade, so where our body has a flat lid and the
view shows another shade, the lid is not there. The opening is cut with straight walls to
the depth where the view draws the wall/floor line, or else to 0.75 of the deepest cut that
keeps the part whole; kept only if solid, hole count, silhouettes and volume hold and the
line drawing improves in the view facing the opening. **Leaderboard, approach `14`: 0.877
(from 0.871); part 7 0.706 -> 0.755, the other eight unchanged.** Estimate:
part 7 0.618 -> 0.658 (volume x1.89 -> x1.70, tray open); other parts unchanged; 12
reference parts 0.949 -> 0.949. Open: the depth guess (0.75) is
a prior, try 0.9 on a submission; part 9's top opening (5886 mm2) is found but refused;
part 5's back openings break the hole count.

The general form of face carving and the depth sweep; see the research pass of 12 Nov in
`docs/RESEARCH.md`. Our hull extrudes each view's **outline** through the whole box. The
classic method (Shum et al.) extrudes each **region** of a view (the areas its strokes cut
it into) only as far as the neighbouring views allow, unions the regions of a view pair,
and intersects the three. For us: for each region of an axis view, candidate depths are
the positions of strokes in the two side-on views within that region's span (a face that
is seen head-on in one view is an edge line in the views beside it); choose per region by
the edge score and the plain-sight test, cut, check as every cut is checked. Measure on
`scripts/bench_layers.py` first (enclosure, elbow, loft adapter have answers), then the
nine practice parts. Expected to matter on parts 5, 7 and 9 (trays, pockets, levels).

### T12. Feedback loop: the model sees our render beside the target (GPU)

From the two-model proposal of 12 Nov (vision model -> JSON -> coding model -> sandbox ->
render -> back to the vision model). Most of that chain we have or have measured as not
worth it (see the table in `docs/RESEARCH.md` once written up: facts give dimensions and
holes exactly, code errors are already 2 of 21, cut lists summed to zero). The one piece
not yet tested fairly is the loop: rounds were tried before the edge score existed, so a
bad revision could not be told from a good one.

Test: `FORGE_ROUNDS=1` (then 2) on top of the clean configuration, only for parts whose
no-model edge score is low (the weak ones here are 6, 7, 9; choose by a threshold on the
edge score, never by part number). Each round shows the model the eight target views and
our render of the current part in the same views (`forge/vision.py: diff_sheet` or
`forge/render.py: render_organiser_style`), and asks for a changed helper program. A
revision replaces the current part only if the estimate does not fall, the dimensions are
not worse and the edge score does not fall (`FORGE_EDGE_VETO`). Report: how many revisions
pass the veto, the wall-clock per round (one hour limit for the whole run), and the
**leaderboard** values of the revised parts, since the estimate cannot rank model bodies.
Expect little: published critic loops gain 1-3 points of overlap over five rounds. Stop
after one submission if no part moves by more than 0.02.

## Rules that came out of today

- `main` receives submission commits only; work on `<track>/<idea>` branches off `main`.
- Decide between configurations on leaderboard values, not on the estimate.
- A cut into a silhouette body is kept only if it is checked (valid solid, hole count,
  silhouettes, volume) **and** justified by something a view shows.
- One approach number per folder in `bench/approaches/`; take the next free one.
