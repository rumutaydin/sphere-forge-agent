# Running the extended set on another machine

The organisers' extended practice set (20 parts: briefs, views, facts, no answers) is our
closest stand-in for the hidden set. The pipeline gets the brief and the views only, as the
hidden parts will arrive; the real facts stay in a separate folder and are used for scoring
afterwards. The number that comes out is the **local estimate** against the real facts and
views (dimensions and holes exact, volume and outline standing in for the rest). It is not a
leaderboard prediction.

The set is in the repo: `bench/extended/parts/<id>/` (brief, views, context image; 20 MB) and
`bench/extended/facts/<id>.json` (the real facts, kept apart so that nothing reads them by
accident).

## 1. On the other machine

Needs: this branch (`a/v6`, not on the remote unless someone pushed it: `git bundle create
v6.bundle origin/main..a/v6` here and `git fetch v6.bundle a/v6:a/v6` there works without a push),
`uv`, and an OpenAI-compatible endpoint that accepts images.

```bash
git checkout a/v6
uv sync
uv run python scripts/prep_extended.py            # -> runs/extended/inputs (no facts.json), scoring/, map.json

export OPENAI_BASE_URL=http://<host>:8000/v1 OPENAI_API_KEY=<key> OPENAI_MODEL=<model>

# the Dockerfile's FORGE_* line, plus the exact path, plus a budget for 20 parts instead of 9
FORGE_THINKING=off FORGE_CANDIDATES=3 FORGE_CARVE=0 FORGE_MODEL_MARGIN=0.02 FORGE_EDGE_VETO=0.015 FORGE_SHELL_VOL=99 \
FORGE_WORKERS=9 FORGE_BUDGET_S=7200 FORGE_LLM_TIMEOUT_S=600 \
FORGE_EXACT=2 FORGE_EXACT_ROUNDS=3 FORGE_BRIEF_LLM=1 \
  nohup uv run python -m forge eval --inputs runs/extended/inputs -o runs/ext-v6 > runs/ext-v6.log 2>&1 &
tail -f runs/ext-v6.log
```

- The inputs have no `facts.json`, so the facts come from the brief without any switch.
  `FORGE_BRIEF_LLM=1` adds one short text call per part for bores the parser missed; leave it
  out to test the parser alone.
- `FORGE_EXACT_THINKING` (default `medium`) is sent as `reasoning_effort`. If the server
  rejects that field, set `FORGE_EXACT_THINKING=on`.
- `FORGE_EXACT_RELAX` stays unset: the run logs what the relaxed rule would have chosen anyway.
- A quick check first (two parts, a few minutes): add `--only test_case_2$ test_case_5$` and
  `-o runs/ext-smoke`.
- The self-score and estimate that `forge eval` prints are against the facts read from the
  brief. Ignore them; score with step 2.

Wall-clock, not measured for this configuration: pass 1 (no model) took 643 s for ten of these
parts on a 16-core laptop, one part hitting the 600 s cap, so expect 20 to 30 minutes for
twenty; the model pass depends on the endpoint (each exact program is up to 4 calls of up to
16,000 tokens with thinking, 9 parts at a time). Expect 1 to 2 hours in all; `FORGE_BUDGET_S=7200`
ends it at 2 hours whatever happens, with the best part found so far on disk for every task. To
rehearse the real limit (9 parts in 1 hour), run nine parts with `FORGE_BUDGET_S=3000`:
`--only` takes the task names.

Without a model (`FORGE_MODEL_PASS=off`, same command) the run gives the hull tier alone.

## 2. Bring the outputs back and score them here

On the other machine:

```bash
tar czf ext-v6.tgz -C runs/ext-v6 outputs work/run_summary.json scores.json
```

Here (the laptop with the repo):

```bash
mkdir -p runs/ext-v6 && tar xzf ext-v6.tgz -C runs/ext-v6
uv run python scripts/prep_extended.py                               # once: builds runs/extended/scoring
uv run python scripts/score_extended.py runs/ext-v6/outputs --tag a-v6-extended
```

`score_extended.py` prints one line per part (task, part id, source, dimensions, holes, volume
ratio, outline IoU, estimate), the mean over all parts with a missing or invalid file counted
as 0, and the mean per source (`exact`, `body`, `hull`, `box`). The source comes from
`work/run_summary.json`; if that file is missing the column shows `?`. Where the strict and the
relaxed rule of the exact gate would have chosen differently, the line says so. `--tag` saves
the table to `results/`.

To compare two runs on the same parts (for example with and without the model):
`uv run python scripts/rescore.py runs/ext-v6/outputs runs/ext-nomodel/outputs --inputs runs/extended/scoring`.

## 3. What to look at

1. Mean estimate against the no-model run of the same parts (ten of them scored 0.60 on
   12 Nov; the nine practice parts 0.80).
2. `by_source` in `work/run_summary.json`: how many parts an exact program took, and
   `by_source_if_relaxed` for what `FORGE_EXACT_RELAX=1` would have changed.
3. Per part with an exact program: did the estimate rise against the hull's (`hull.estimate`
   in the same file is against the brief's facts; rescore the hull run for a like-for-like number).
