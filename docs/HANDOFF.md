# Handoff: where we are

Written 12 Nov 2026, early morning, after a night session. Read this instead of any chat
history. What to do next is in [PLAN.md](PLAN.md); the numbers are in
[SCOREBOARD.md](SCOREBOARD.md).

## In one paragraph

The agent now builds **all nine practice parts with no model call**, in about six
minutes, with exact outer dimensions and the exact through-hole count on every part. It
does that from the eight views (a visual hull) and `facts.json` (every bore). A second
pass lets the model try to improve each part and keeps a model result only when our
local estimate says it is better. Our local estimate of the leaderboard for the best
set is about 0.8, against 0.658 submitted yesterday and 0.320 for boxes. **Nothing from
tonight has been submitted**: the estimate is a stand-in, fitted on 16 files, and the
first job this morning is to submit the filed approaches one at a time and read the real
values. What remains hard is material hidden from every outline: hollow interiors, fins,
sloped pockets (parts 6 and 7).

## What was built tonight

| Thing | File | State |
|---|---|---|
| Silhouette of each view, exact pixel-to-mm mapping for all eight views | `forge/vision.py` | used everywhere; an exact part scores IoU 0.997 against its views |
| Shape check and leaderboard estimate | `forge/vision.py: shape_score`, `forge/compile.py: estimate` | reproduces the two known leaderboard values to 0.01; see the caveats in the scoreboard |
| Visual hull as a B-rep (five silhouette prisms intersected) | `forge/compile.py: hull_body` | all nine parts; 0.921 true local score on our 12 reference parts (boxes: 0.499) |
| Revolve for turned parts | `forge/compile.py: revolve_body` | parts 2 and 3 |
| Bores from the facts, drilled until the hole count matches | `forge/compile.py: cut_holes_to_genus` | holes 1.00 on nine of nine |
| Faces that bores start from: free space in front removed | `forge/layers.py: carve_mouth_faces` | estimate +0.02; part 9 volume ×1.54 → ×1.23 |
| Through-hole count from the CAD topology, no meshing | `forge/geometry.py: brep_genus` | agrees with the mesh count on 107 files; 100× faster |
| Two passes, best file always on disk, no plan call | `forge/run.py`, `forge/pipeline.py` | 6 min without the model, 28 min with it |
| Model writes the body only; code trims it with the hull and cuts the bores | `forge/stages/build.py` | helps on parts 4 and 6 with thinking on |
| Model lists empty regions; code cuts each and checks it | `forge/stages/carve.py` | most proposals are rejected by the checks; small gains |
| Depth of flat faces by sliding them into the isometric view, with a plain-sight test | `forge/layers.py: face_depths`, `carve_layers` | wired into pass 1; our hollow enclosure 0.68 → 0.99 against its answer; neutral on the practice parts |
| Our reference parts drawn like the organisers' views; depth ideas scored against answers | `forge/render.py: render_organiser_style`, `scripts/bench_layers.py` | reference mean 0.920 → 0.949 |
| Each approach's nine files with local numbers | `bench/approaches/`, `scripts/save_approach.py`, `scripts/submit_approach.sh` | seven filed |

## What we measured tonight

1. **The organisers' framing.** Every view is orthographic, the projected bounding box is
   fitted into 985 of 1024 pixels and centred, isometric views included. The outline
   stroke lies one pixel outside the true edge. With that, silhouettes are exact to
   about 0.1% of part size.
2. **Hull plus bores, no model:** estimate 0.773 (boxes 0.327, yesterday's set 0.652).
   Dimensions and holes are 1.00 on all nine. Volume is too high by 0–8% on parts 1, 2,
   3, 8; 17–22% on 4 and 5; ×1.5 to ×3.2 on 6, 7, 9.
3. **Face carving:** estimate 0.793. Parts 1 (volume ×1.06 → ×1.00), 5 (×1.22 → ×1.13)
   and 9 (×1.54 → ×1.23).
4. **Model pass, Qwen3.8-27B, thinking off:** 3 bodies per part, 10.5 min in total. The
   model's body beat the no-model part on 2 of 9 parts (4 and 6). Many bodies had the
   wrong envelope or fell apart into several solids.
5. **Model pass, thinking on (medium, 16,000 tokens):** 28 min in total; several calls
   used all 16,000 tokens on thinking and returned nothing. The model won on 7 parts,
   mostly by small margins; part 6 went from 0.49 to 0.62. Estimate 0.807.
6. **True local score** (our 12 reference parts with answers, silhouettes only): hull
   0.921, boxes 0.499. The two hollow parts were the failures: enclosure 0.68, elbow 0.53.
   With the depth sweep the enclosure reaches 0.99 and the mean 0.949.

## Rules that were corrected today

- The run limit is **one hour** for all nine parts. Twenty minutes is the wait between
  two leaderboard submissions.
- Every push or merge to `main` is a submission. A commit can be submitted once. The
  best commit counts.
- At the code freeze (Fri 13 Nov, 08:00) the organisers run our image on nine hidden
  parts against the model endpoint we give them, so the endpoint must be public and the
  GPU instance must be running then.

## What is where

| Thing | Where |
|---|---|
| Stable code of 11 Nov, docs, practice inputs, box outputs | `main` (nothing merged since) |
| Tonight's work, stacked | `b/silhouette-score` → `c/compile-hull` → `a/two-pass` (the tip has everything) |
| The depth-sweep experiment at its first commit | `b/face-depth-layers` (its file also lives on `a/two-pass`) |
| Approaches ready to submit | `bench/approaches/<name>/` on `a/two-pass`: nine `.stp` + `scores.json` |
| Yesterday's bores-from-facts branch | `c/facts-driven` (superseded: its bore cutting is now in `forge/compile.py`) |
| Result files for `forge board` | `results/` |
| Raw run folders (candidates, logs) | `runs/` on Robin's laptop only (ignored by git): `two-pass-1`, `-2`, `-3`, `compile-v7` |
| Model server start script | `scripts/serve_vllm.sh` |
| Endpoint settings and key | `team-g.env` on Robin's laptop (ignored by git); the key is also in `~/vllm.key` on the instance |

None of tonight's branches is merged or pushed to `main`, because a merge to `main` is a
submission. `scripts/submit_approach.sh <name>` makes the commit for one approach; the
merge is a person's decision.

`main` was reset on 11 Nov to remove two trial submissions (one hand-built part 5, one
hand-picked set). If your clone still has them: `git fetch && git reset --hard origin/main`
on `main`.

## The model server

**As of 12 Nov, 03:30 the instance is still running** (it was used until 03:27; the
coding agent was not allowed to stop it). Stop it in the Brev console if nobody is
measuring: it costs $4.84 per hour. A reconnecting tunnel may still be running on
Robin's laptop (`pkill -f "ssh -N -o ServerAliveInterval"` ends it).

| | |
|---|---|
| Instance | Brev, name `clinical-ivory-barnacle`, one RTX PRO 6000 Blackwell (96 GB), $4.84/h, about 50 h of credit in total |
| Model | `Qwen/Qwen3.8-27B` (27B, vision, Apache 2.0), full precision, served by vLLM in Docker |
| Speed | 71 tokens/s for one request; about 55 each and 870 in total at 16 in parallel |
| Capacity | about 410,000 tokens of request memory; 27 long requests at once saturate it |

Start it (after starting the instance in the Brev console; the container restarts by
itself, about 4 minutes):

```bash
brev refresh
ssh clinical-ivory-barnacle 'curl -sf localhost:8000/health && echo ready'
# only if the container is missing:
ssh clinical-ivory-barnacle 'bash -s' < scripts/serve_vllm.sh
```

Reach it from the laptop (keep this running in a terminal tab):

```bash
ssh -N -L 8000:localhost:8000 clinical-ivory-barnacle
```

Run the agent against it:

```bash
set -a && . ./team-g.env && set +a
FORGE_THINKING=on FORGE_REASONING_EFFORT=medium FORGE_MAX_TOKENS=16000 FORGE_LLM_TIMEOUT_S=700 \
FORGE_CANDIDATES=2 FORGE_CARVE=1 \
  nohup uv run python -m forge eval --inputs artifacts/inputs --tag <track>-<idea> \
  -o runs/<name> > runs/<name>.log 2>&1 &
# no model at all (6 minutes, no tunnel needed):
FORGE_MODEL_PASS=off uv run python -m forge eval --inputs artifacts/inputs --tag <track>-<idea>
```

Use `nohup ... &` with a log file. A run started as a background task of a coding agent
dies when the chat is rewound or the session restarts.

Watch it:

```bash
tail -f runs/<name>.log
ssh clinical-ivory-barnacle 'docker logs --since 30s vllm 2>&1 | grep throughput | tail -1'
```

Before the freeze: expose port 8000 in the Brev console (Access → HTTP Ports → add 8000 →
Share → public), set `OPENAI_BASE_URL` to that address in `team-g.env`, and test from a
machine that is not on the tunnel. Stop the instance whenever nobody is measuring.

## What we measured on 11 Nov (the old pipeline)

1. **Thinking depth decides whether a call returns at all.** At the model's default
   depth the planning call spent 16,000 tokens thinking and wrote nothing. Medium took
   316 s, off took 186 s. Later, with a 32,000-token limit, some calls thought for all
   32,000 tokens and returned an empty answer.
2. **Base agent, medium thinking, 16,000-token limit:** 3 of 9 parts built in 32 min.
   On five parts every candidate came back with no program because the reply was cut
   off, and the code treated that as nothing to build.
3. **Branch `c/facts-driven`, 32,000-token limit:** 4 of 9 written in 69 min. Seven
   parts had a built candidate on disk; three of those were replaced by the box
   because a later call for the same part timed out (bug below).
4. **Those seven built candidates plus two boxes: leaderboard 0.658.** Per-part table
   in the scoreboard.

## Known defects

| Defect | Where | Effect |
|---|---|---|
| Thinking-on calls can spend the whole token limit thinking and return nothing | `forge/llm.py`, the model | a wasted call of up to 5 minutes; the part keeps its no-model file |
| The model's cut lists are accepted on volume and silhouettes only | `forge/stages/carve.py` | a cut can be in the wrong place and still raise the estimate |
| Part 8 reaches the hole count by leaving out 12 small bores | `forge/compile.py: cut_holes_to_genus` | volume ×1.07; Track C task C2 |
| Pass 1 takes up to 335 s on part 7 | `forge/layers.py: carve_mouth_faces` | fine inside the hour; unknown on a machine with few cores (Track A task A2) |
| The estimate was fitted on 16 files, none of them a hull | `forge/compile.py: estimate` | selection between a hull and a model body may be off; refit after today's submissions |
| The image has not been built or run since the pipeline changed | `Dockerfile` | Track A task A1, before any merge |

Fixed tonight: a failed model call no longer discards a part's candidates; the output
file is written as soon as a better part exists; the plan call is gone; the per-call
timeout respects the deadline; a fallback is recorded with its own score.

## What the practice briefs look like

All nine `description.md` files have the same sections: title, type, envelope (box,
volume, number of through-passages), overall shape, features, edges and finish. Each
feature bullet gives count, diameter, axis, blind or through, and centres measured from
the minimum corner of the bounding box. `facts.json` repeats every bore with diameter,
axis, length and centre; that centre is the **midpoint of the bore**, not where it
enters. Simple parts (1, 2, 3) can be built from the text alone. Complex parts (5, 7, 9)
give every bore but leave body dimensions unstated.

Recurring feature kinds: block or plate, revolved profile, straight bore on X/Y/Z, bore
on a tilted axis, linear pattern, partial-cylinder cut (recess, slot, notch), rib or tab
or boss, rounded-rectangle pocket, hollow shell, fillet or chamfer or countersink.

## Questions still open with the organisers

1. May the endpoint for the final run be a hosted commercial model, or must it be one
   we serve? (One team is at 0.92, probably with a hosted model.)
2. Do the hidden parts come with `facts.json` and the same brief format?
3. How strictly is a re-run compared with our submitted outputs?
4. Does the container have internet access other than to the model endpoint?

## How we work from here

- One question or one build step at a time, each starting from files: this page, the
  plan, the track brief, the code. No step should need a chat history.
- When a step is finished, write the result where the next person will look: a lab note
  in the track brief, a row in the scoreboard, a line in this page if a fact changed.
- Steps marked "offline" in the plan need no GPU and can be done by a cheaper coding
  agent while the instance is stopped.
