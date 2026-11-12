# T5: test a bigger model against Qwen3.8-27B

Self-contained brief for a session that has no chat history. Owner: Robin. Written 12 Nov,
about 14:30 UTC. Code freeze Fri 13 Nov 08:00.

## The question

Does Qwen3.8-Flash-Next (NVFP4), served on two RTX PRO 6000, write better part **bodies**
than Qwen3.8-27B does? Answer with numbers, per part. Do not change pipeline code.

## What you need to know first

- Read `docs/HANDOFF.md`, then `docs/SCOREBOARD.md` section "Leaderboard, 12 Nov".
- The pipeline builds every part with no model first (pass 1), then asks the model for
  three bodies per part, written with nine helper functions (`forge/library/solids.py`).
  A model body replaces the no-model part only if our estimate is higher by 0.02, its
  dimensions are not worse, and its edge score is not lower (`forge/pipeline.py`).
- With Qwen3.8-27B, thinking off: 19 of 21 bodies run at the first try; a model body wins
  reliably on part 4 only (+0.063 on the leaderboard), sometimes on part 6, and loses
  points on part 7 when accepted. Bodies for parts 5, 7, 8, 9 build but are far from the
  real shape. That is the gap a better model would have to close.
- **The local estimate cannot rank model bodies** (it promised +0.36 once, the
  leaderboard gave +0.06). Use it to describe, never to conclude. The verdict is a
  leaderboard submission, and that is Robin's call.

## Ground rules

- Work in your own git worktree from branch `b/edge-score` (it has the latest code):
  `git worktree add -b a/flashnext .worktrees/flashnext origin/b/edge-score`, then
  `cd .worktrees/flashnext && uv sync`. Another session is working in
  `.worktrees/helper`: do not touch it.
- Never push or merge to `main` (a push to `main` is a submission). Push your branch only.
- Do not stop, restart or reconfigure the instance `clinical-ivory-barnacle`: it serves
  Qwen3.8-27B, the other session uses it, and it is the fallback for the final run.
- Endpoint address and key go in a file named `team-g-flashnext.env` in the repo root
  (`*.env` is ignored by git). Never print the key and never commit it.
- No Claude attribution in commits (Robin's rule). Long runs detached with `nohup` and a
  log file; say which run folder you are quoting.

## Step 1. Serve the model (on the new instance, once Robin says it is provisioned)

`scripts/serve_vllm.sh` is what serves the 27B today; start from it. Nobody here has run
Flash-Next, so check the model card for the exact flags before starting. What the
pipeline needs from the server:

- OpenAI-compatible chat completions with images: at least 9 images per request
  (`--limit-mm-per-prompt '{"image": 24}'`)
- context of 32k tokens or more (our largest request is about 10,700 tokens plus the reply)
- both GPUs used (`--tensor-parallel-size 2` in vLLM)
- an API key (`VLLM_API_KEY`), and `--max-num-seqs` high enough for 27 parallel requests
- if the model thinks: a reasoning parser, so the thinking does not end up in the answer

Then reach it from the laptop on another local port, so it does not collide with the
27B's tunnel on 8000:

```bash
ssh -N -L 8001:localhost:8000 <new-instance>          # keep running
cat > team-g-flashnext.env <<'ENV'
OPENAI_BASE_URL=http://localhost:8001/v1
OPENAI_API_KEY=<key>
OPENAI_MODEL=<model id as /v1/models reports it>
ENV
set -a && . ./team-g-flashnext.env && set +a
curl -s -H "Authorization: Bearer $OPENAI_API_KEY" $OPENAI_BASE_URL/models | head -c 300
```

## Step 2. Smoke test (2 minutes)

One part, to see that images are accepted and a program comes back:

```bash
FORGE_THINKING=off FORGE_CANDIDATES=2 uv run python -m forge eval --inputs artifacts/inputs \
  --only test_case_4 -o runs/flashnext-smoke 2>&1 | tail -8
python3 -c "import json; s=json.load(open('runs/flashnext-smoke/work/test_case_4/summary.json')); print(s['chosen']); [print(c['log']) for c in s['candidates']]"
```

- "no program in the reply" on every candidate, or "reply cut off": the model is thinking.
  Rerun with `FORGE_THINKING=on FORGE_MAX_TOKENS=16000 FORGE_LLM_TIMEOUT_S=700`.
  (`FORGE_THINKING=off` sends Qwen's `enable_thinking: false` chat-template flag; a
  different model family may ignore or reject it.)
- An error about images or context: fix the server flags, not the pipeline.

## Step 3. The comparison run

Same settings as the 27B reference runs:

```bash
FORGE_THINKING=off FORGE_CANDIDATES=3 FORGE_CARVE=0 \
  nohup uv run python -m forge eval --inputs artifacts/inputs --tag a-flashnext-bodies \
  -o runs/flashnext > runs/flashnext.log 2>&1 &
```

About 8 minutes with the 27B (4 of them pass 1, which uses no model). If the smoke test
needed thinking on, use those settings here too and say so. If time allows, a second run
with the same settings: the 27B varies a lot from run to run (part 6: +0.052 in one run,
nothing in the next), so one run is one sample.

## Step 4. Report these numbers, next to the 27B's

Reference runs of the 27B, same settings, in `.worktrees/helper/runs/`: `helper-nothink`
(before the guards) and `budget-nothink` (current code).

| Number | Where | 27B |
|---|---|---|
| bodies that run at the first try | `summary.json` → `candidates[].log[0]` starts with "ran" | 19 of 21 |
| bodies with the right envelope at the first run | no "envelope wrong" in that line | 13 of 21 |
| bodies within 10% of the target volume at the first run | no "volume off" in that line | few |
| bodies refused by the edge veto | "not offered: its edges match" in the log | several |
| parts where a model body was chosen | `chosen` starts with "model body" | 4 and 6, sometimes 2, 5, 7 |
| per part: estimate of the best body against the no-model part | `candidates[].score`, `runs/.../pass1/compile.json[0].estimate` | parts 5, 7, 8, 9 far below |
| seconds for the model pass, tokens per second | the log; server metrics | about 70 s for nine parts |

Then look at the parts that decide it. For parts 5, 7 and 9 open the best candidate's
program (`runs/flashnext/work/test_case_<n>/cand*/try*/part.py`) and render it:

```bash
uv run python -c "
from forge.geometry import load_mesh; from forge.render import render_sheet
render_sheet(load_mesh('runs/flashnext/work/test_case_7/cand0/try0_open/part.step'), 'runs/flashnext/p7.png', tile=420)"
```

and compare with `artifacts/inputs/test_case_7/images/`. Say in one line per part whether
the masses are in the right place.

## Step 5. File it and hand back

```bash
uv run python scripts/save_approach.py 13-flashnext-bodies runs/flashnext/outputs "Qwen3.8-Flash-Next NVFP4 on 2x RTX PRO 6000, thinking off, 3 helper bodies per part, same code and settings as 12"
```

(Take the next free number if 13 exists.) Add `"settings"` to its `scores.json` like the
other approaches, append one line to the Lab notes of `docs/tracks/A-ship.md`, commit,
push the branch, and tell Robin: the table from step 4, your one-line read per part, and
the approach name. **Do not submit.** Robin decides whether it goes to the leaderboard;
only parts where a model body was chosen can differ from approach `12`.

## What would make the switch worth it

A leaderboard gain on parts 5, 6, 7 or 9 that repeats in a second run, with the run still
well inside the hour, and an endpoint that is public, stable and paid for through
judging. Anything less: keep the 27B.
