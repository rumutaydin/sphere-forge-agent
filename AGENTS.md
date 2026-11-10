# Instructions for coding agents

You are working in a hackathon repo: an agent that turns a prompt or image into a CAD
part, ranked by geometric similarity to a hidden target. Three people work in parallel,
each with their own coding agent. Your job is to raise the eval score inside one track
without breaking the other two.

## Before you write anything

1. Ask the human which track they are on (A, B or C) if they have not said.
2. Read `docs/ARCHITECTURE.md`, then that track's brief in `docs/tracks/`. The brief has
   the owned paths, the target numbers, a ranked backlog and search terms.
3. Pick **one** backlog item. State the hypothesis and the number you expect to move
   before editing code.

## File ownership

| Track | Paths |
|---|---|
| A — Measure | `forge/metrics.py` `forge/geometry.py` `forge/render.py` `forge/bench.py` `forge/sensitivity.py` `forge/__main__.py` `forge/llm.py` `bench/` `results/` `scripts/` |
| B — Understand | `forge/stages/understand.py` `forge/library/` |
| C — Build | `forge/stages/build.py` `forge/stages/verify.py` `forge/stages/select.py` `forge/backends/` |
| Shared | `forge/types.py` `forge/pipeline.py` `AGENTS.md` `docs/ARCHITECTURE.md` `docs/STRATEGY.md` |

Edit only your track's paths plus its brief in `docs/tracks/` and its tests in `tests/`.
If a change needs a file outside them, stop and tell the human; do not make the edit.
Changes to shared files go in their own pull request.

## The loop

```
measure -> change one thing -> measure -> keep or revert -> write it down
```

1. `uv run pytest -q` passes before and after. It needs no API key.
2. Baseline: `uv run python -m forge eval --tag <track>-<idea>-before` (add `--only` for a
   quick subset while iterating, the full set before a pull request).
3. Make the change.
4. `uv run python -m forge eval --tag <track>-<idea>-after`, then `uv run python -m forge board`.
5. If the score did not improve beyond run-to-run noise, revert. Say so plainly.
6. Append one line to the Lab notes of your track brief: date, idea, before → after, kept or dropped.

When a case scores badly, open `runs/<run>/<case>/spec.md` first. A wrong brief is a
Track B problem; a right brief with a wrong part is Track C.

## Rules

- **A failed part scores zero and counts in the mean.** Never report an average over
  only the parts that built.
- **Never tune on held-out cases** or paste benchmark targets into prompts.
- **Do not invent scores.** If you could not run the eval (no key, no time), say that.
- **Frame and proportions before features.** See the floors table in `docs/SCOREBOARD.md`.
- **No new dependency** without telling the human; three people share one lockfile.
- **Keep `forge/pipeline.py` thin.** Logic belongs in a stage.
- **Generated CAD programs run in a subprocess with a timeout.** Keep it that way.
- Branch `<track>/<idea>`, pull request into `main`, description states before → after.

## Commands

```bash
uv sync
uv run pytest -q
uv run python -m forge bench
uv run python -m forge solve "a 40 mm cube with a 10 mm hole through the top" -o runs/try
uv run python -m forge eval --only 03 08 --tag c-example
uv run python -m forge score runs/try/cand0/try0/part.step bench/targets/03_flange/part.step
uv run python -m forge board
```

`ANTHROPIC_API_KEY` must be set for `solve` and `eval`. `FORGE_MODEL` overrides the model.
