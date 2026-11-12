#!/usr/bin/env bash
# Stage one filed approach as a submission commit on the current branch. Does NOT push or merge:
# a push or merge to main is the submission, and that step is yours.
#
#   scripts/submit_approach.sh 04-no-model-faces
#
# Copies bench/approaches/<name>/*.stp into artifacts/outputs, writes the approach's settings
# into the Dockerfile's FORGE_* line (so a re-run of the image reproduces the files), commits.
set -euo pipefail
NAME="${1:?approach name, a folder in bench/approaches}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SRC="bench/approaches/$NAME"
[ -f "$SRC/scores.json" ] || { echo "no $SRC/scores.json" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "commit or stash your changes first" >&2; exit 1; }
[ "$(ls "$SRC"/test_case_*.stp | wc -l)" -eq 9 ] || { echo "$SRC does not hold nine parts" >&2; exit 1; }
cp "$SRC"/test_case_*.stp artifacts/outputs/
SETTINGS="$(python3 -c "import json,sys; print(json.load(open('$SRC/scores.json')).get('settings') or 'FORGE_MODEL_PASS=off')")"
python3 - "$SETTINGS" <<'PY'
import re, sys
p = "Dockerfile"
s = open(p).read()
s, n = re.subn(r"^ENV FORGE_[^\n]*$", "ENV " + sys.argv[1], s, flags=re.M)
assert n == 1, "expected exactly one 'ENV FORGE_...' line in the Dockerfile"
open(p, "w").write(s)
PY
git add artifacts/outputs Dockerfile
EST="$(python3 -c "import json; print(json.load(open('$SRC/scores.json'))['mean_estimate'])")"
git commit -q -m "Submit $NAME (local estimate $EST)"
echo "Committed $(git rev-parse --short HEAD) on $(git branch --show-current): $NAME, settings: $SETTINGS"
echo "To submit: merge or push this commit to main, wait 20 minutes before the next one,"
echo "then write the leaderboard value into $SRC/scores.json."
