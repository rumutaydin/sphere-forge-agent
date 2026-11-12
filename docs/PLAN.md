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
| best value per part across all submissions | 0.873 (a ceiling, not a run) |

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

## Rules that came out of today

- `main` receives submission commits only; work on `<track>/<idea>` branches off `main`.
- Decide between configurations on leaderboard values, not on the estimate.
- A cut into a silhouette body is kept only if it is checked (valid solid, hole count,
  silhouettes, volume) **and** justified by something a view shows.
- One approach number per folder in `bench/approaches/`; take the next free one.
