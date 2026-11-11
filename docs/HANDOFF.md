# Handoff: where we are

Written 11 Nov 2026, 23:00. Read this instead of any chat history. What to do next is in
[PLAN.md](PLAN.md); the numbers are in [SCOREBOARD.md](SCOREBOARD.md).

## In one paragraph

Our agent runs end to end against an open model we host ourselves (Qwen3.8-27B on one
Brev GPU). A hand-picked set of its outputs scored **0.658** on the leaderboard; nine
bounding boxes score 0.320; other teams are at about 0.8 and one at 0.92. Dimensions and
hole counts are right on every part that builds. We lose points in three places: two
complex parts do not build at all, the shape of the built parts is only half right, and
a real run neither finishes inside the hour nor keeps the good candidates it builds.

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
| Stable code, docs, practice inputs, box outputs | `main` |
| Bores from facts, fitted dimensions, thinking settings | branch `c/facts-driven` (pushed, not merged) |
| The 0.658 STEP files | `bench/calibration/1111-qwen-picked/` (with the program for each and its leaderboard score) |
| The 0.320 box files | `bench/calibration/1111-boxes/` and `artifacts/outputs/` |
| Result files for `forge board` | `results/` |
| Raw run folders (candidates, logs) | `runs/` on Robin's laptop only (ignored by git) |
| Model server start script | `scripts/serve_vllm.sh` |
| Endpoint settings and key | `team-g.env` on Robin's laptop (ignored by git); the key is also in `~/vllm.key` on the instance |

`main` was reset on 11 Nov to remove two trial submissions (one hand-built part 5, one
hand-picked set). If your clone still has them: `git fetch && git reset --hard origin/main`
on `main`.

## The model server

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
FORGE_WORKERS=9 FORGE_REASONING_EFFORT=medium \
  nohup uv run python -m forge eval --inputs artifacts/inputs --tag <track>-<idea> \
  -o runs/<name> > runs/<name>.log 2>&1 &
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

## What we measured

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

## Known defects (none fixed yet)

| Defect | Where | Effect |
|---|---|---|
| One failed model call discards every candidate of that part | `forge/pipeline.py` (`solve`: the exception leaves `cands` empty) | parts 4, 5, 8 written as boxes despite candidates at 0.89, 0.98, 0.87 |
| The deadline is only checked between steps | `forge/pipeline.py`, `forge/run.py` | the run overshoots its budget (69 min with a 55 min budget) |
| Nothing is written until a part is completely finished | `forge/pipeline.py` | a hard stop at one hour would leave boxes for every unfinished part |
| Thinking depth is one global setting | `forge/llm.py` on `c/facts-driven` | cannot think for the plan and not for code |
| Fitting runs the kernel up to 64 times per candidate, on every candidate | `forge/stages/build.py` on `c/facts-driven` | slow, and fits total volume even when the shape is wrong |
| A fallback box is recorded as self-score 0 | `forge/__main__.py` (`eval`) | run means are not comparable with the leaderboard |

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
