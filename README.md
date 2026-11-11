# forge — design brief and views to a STEP solid

Team repo for Sphere Forge #1 (Munich, 11–13 Nov 2026, code freeze Friday 08:00).
For each mechanical part we get a written brief with exact dimensions, a `facts.json`
with the target's measurements, and eight orthographic views. We return one STEP solid.

```mermaid
flowchart LR
    IN(["brief + facts + 8 views"]) --> P["plan<br/>Track B"]
    P --> G["build + repair<br/>Track C"]
    G --> K["self-check vs facts and views<br/>Track B"]
    K --> V["critic + select<br/>Track C"]
    V --> OUT(["test_case_n.stp"])
    OUT --> SUB["submit, leaderboard<br/>Track A"]
    SUB -. "what to fix" .-> P
    SUB -. "what to fix" .-> G
```

**Score:** `0.30 volume + 0.30 surface + 0.20 dimensions + 0.20 holes`, after rigid
alignment. Pose is free; size and handedness are not. A missing file scores 0.

## Start here

| If you want to… | Read |
|---|---|
| understand how the agent works | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| know the rules, the split, the timeline, and why we are not training a network | [docs/STRATEGY.md](docs/STRATEGY.md) |
| pick up your track | [A — Ship](docs/tracks/A-ship.md) · [B — See](docs/tracks/B-see.md) · [C — Build](docs/tracks/C-build.md) |
| see the scoring rule and target numbers | [docs/SCOREBOARD.md](docs/SCOREBOARD.md) |
| find open problems and vocabulary | [docs/RESEARCH.md](docs/RESEARCH.md) |
| brief your coding agent | [AGENTS.md](AGENTS.md) (Claude Code reads it via `CLAUDE.md`) |

## Setup

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run pytest -q
```

To run the agent, point it at an OpenAI-compatible endpoint that accepts images:

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1 OPENAI_API_KEY=... OPENAI_MODEL=...
```

```bash
uv run python scripts/main.py --input_dir artifacts/inputs --output_dir artifacts/outputs
```

`artifacts/inputs` is the organisers' practice set from their
[submission template](https://github.com/sphere-energy/hackathon-submission).
Without a reachable model the run still writes a bounding-box solid for every part.

## Status

- Offline tests pass. The pipeline reads the organisers' nine practice parts and writes
  nine valid `.stp` files (fallback blocks) without a model. The Docker image builds and
  does the same as a non-root user (built on arm64; the `linux/amd64` build is untested).
- **Not yet run with a real model, and nothing submitted.** No leaderboard score exists.
- This repo is not yet merged into a repo created from the organisers' template;
  that is Track A's first job.
