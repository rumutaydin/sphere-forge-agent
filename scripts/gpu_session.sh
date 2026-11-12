#!/usr/bin/env bash
# One GPU session: start the Brev instance, wait for the model server, make sure the tunnel
# works, run the given command(s) with team-g.env loaded, and ALWAYS stop the instance.
#
#   scripts/gpu_session.sh '<command 1>' ['<command 2>' ...]
#
# Each argument is one shell command line, run from the repo root with the variables of
# team-g.env exported. Example (docs/EXTENDED_RUN.md and the lab notes have the real ones):
#
#   scripts/gpu_session.sh \
#     'FORGE_EXACT=3 uv run python -m forge eval --inputs artifacts/inputs --only test_case_4 test_case_6 -o runs/v6-probe' \
#     'FORGE_EXACT=2 uv run python -m forge eval --inputs artifacts/inputs -o runs/v6-full'
#
# The instance costs $4.84 per hour, so:
#   - nothing is started before the local checks pass (env file, tools, at least one command)
#   - the instance is stopped on every way out: end, error, Ctrl-C, kill, the time cap
#   - `brev stop` is retried (it has been rate-limited before) and `brev ls` is printed at the end
#   - the whole session has a time cap; a hung command is killed and the instance stopped
#
# Settings (environment):
#   GPU_INSTANCE (clinical-ivory-barnacle)  GPU_ENV (team-g.env in the repo root, else in the main checkout)
#   GPU_MAX_MIN (100)      cap on the whole session, in minutes
#   GPU_BOOT_MIN (20)      longest wait for the server after `brev start` (weights load in about 4 minutes)
#   GPU_STOP_TRIES (12)    attempts at `brev stop`, GPU_STOP_WAIT_S (30) apart
#   GPU_KEEP_GOING (1)     1: a failed command does not cancel the ones after it; 0: stop at the first failure
#   GPU_POLL_S (10)        seconds between polls
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTANCE="${GPU_INSTANCE:-clinical-ivory-barnacle}"
MAX_MIN="${GPU_MAX_MIN:-100}"
BOOT_MIN="${GPU_BOOT_MIN:-20}"
STOP_TRIES="${GPU_STOP_TRIES:-12}"
STOP_WAIT_S="${GPU_STOP_WAIT_S:-30}"
KEEP_GOING="${GPU_KEEP_GOING:-1}"
POLL_S="${GPU_POLL_S:-10}"
RATE=4.84
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

T0=$(date +%s)
STARTED=0          # 1 once `brev start` has been issued: from then on the instance is stopped on exit
TUNNEL_PID=""      # set only if this script started a tunnel
CMD_PID=""
CLEANED=0
STATUS=0

say() { printf '[gpu %s +%dm] %s\n' "$(date +%H:%M:%S)" $(( ($(date +%s) - T0) / 60 )) "$*"; }
left_s() { echo $(( T0 + MAX_MIN * 60 - $(date +%s) )); }

instance_line() { brev ls 2>/dev/null | grep -F "$INSTANCE" | head -1; }

stop_instance() {
  local i line
  for i in $(seq 1 "$STOP_TRIES"); do
    say "brev stop $INSTANCE (attempt $i of $STOP_TRIES)"
    brev stop "$INSTANCE" && say "stop accepted" || say "brev stop returned an error"
    sleep 3
    line="$(instance_line)"
    if printf '%s' "$line" | grep -qi 'stop'; then
      say "instance state: $line"
      return 0
    fi
    say "not stopped yet (${line:-no line for $INSTANCE in brev ls}); waiting ${STOP_WAIT_S}s"
    sleep "$STOP_WAIT_S"
  done
  return 1
}

cleanup() {
  [ "$CLEANED" = 1 ] && return
  CLEANED=1
  trap '' INT TERM HUP          # nothing may interrupt the stop
  if [ -n "$CMD_PID" ] && kill -0 "$CMD_PID" 2>/dev/null; then
    say "ending the running command (process group $CMD_PID)"
    kill -TERM -- "-$CMD_PID" 2>/dev/null || kill -TERM "$CMD_PID" 2>/dev/null
    sleep 2
    kill -KILL -- "-$CMD_PID" 2>/dev/null || kill -KILL "$CMD_PID" 2>/dev/null
  fi
  if [ -n "$TUNNEL_PID" ]; then kill "$TUNNEL_PID" 2>/dev/null; say "tunnel started by this script closed"; fi
  if [ "$STARTED" = 1 ]; then
    if ! stop_instance; then
      say "!!!!! THE INSTANCE MAY STILL BE RUNNING (\$$RATE per hour). Stop it by hand: brev stop $INSTANCE, or in the Brev console. !!!!!"
      STATUS=97
    fi
    say "brev ls:"
    brev ls || true
    local min=$(( ($(date +%s) - T0 + 59) / 60 ))
    say "session length ${min} min, about \$$(awk -v m="$min" -v r="$RATE" 'BEGIN{printf "%.2f", m*r/60}') at \$$RATE per hour"
  else
    say "the instance was never started by this script; nothing to stop"
  fi
}
trap 'cleanup; exit $STATUS' EXIT
trap 'say "interrupted"; STATUS=130; exit 130' INT
trap 'say "terminated"; STATUS=143; exit 143' TERM HUP

fail() { say "ERROR: $1"; STATUS="${2:-1}"; exit "$STATUS"; }

# --- 0. local checks: nothing below costs money until these pass ------------------------------------
[ "$#" -ge 1 ] || { STATUS=2; say "usage: scripts/gpu_session.sh '<command>' ['<command>' ...]"; exit 2; }
for tool in brev ssh curl pgrep awk; do command -v "$tool" >/dev/null || fail "$tool not found on PATH" 2; done
ENV_FILE="${GPU_ENV:-$ROOT/team-g.env}"
if [ ! -f "$ENV_FILE" ] && [ -z "${GPU_ENV:-}" ]; then      # a git worktree: the env file lives in the main checkout
  MAIN="$(cd "$ROOT" && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||')"
  [ -n "$MAIN" ] && [ -f "$MAIN/team-g.env" ] && ENV_FILE="$MAIN/team-g.env"
fi
[ -f "$ENV_FILE" ] || fail "env file $ENV_FILE not found (set GPU_ENV)" 2
set -a; . "$ENV_FILE"; set +a
[ -n "${OPENAI_BASE_URL:-}" ] && [ -n "${OPENAI_API_KEY:-}" ] && [ -n "${OPENAI_MODEL:-}" ] \
  || fail "$ENV_FILE must set OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL" 2
[ -f "$ROOT/scripts/serve_vllm.sh" ] || fail "scripts/serve_vllm.sh not found" 2
cd "$ROOT" || fail "cannot enter $ROOT" 2
say "instance $INSTANCE, env $(basename "$ENV_FILE"), model $OPENAI_MODEL, $# command(s), cap ${MAX_MIN} min (about \$$(awk -v m="$MAX_MIN" -v r="$RATE" 'BEGIN{printf "%.2f", m*r/60}') at most)"

# --- a. start the instance ------------------------------------------------------------------------
STARTED=1
say "brev start $INSTANCE"
brev start "$INSTANCE" || say "brev start returned an error (it may be running already); checking by ssh"
brev refresh >/dev/null 2>&1 || true

# --- b. wait for the model server ---------------------------------------------------------------------
remote() { ssh "${SSH_OPTS[@]}" "$INSTANCE" "$@"; }
health() { remote 'curl -sf -m 5 localhost:8000/health' >/dev/null 2>&1; }
boot_end=$(( $(date +%s) + BOOT_MIN * 60 ))
served=0
say "waiting for the server on the instance (up to ${BOOT_MIN} min)"
while ! health; do
  [ "$(date +%s)" -lt "$boot_end" ] || fail "the server did not answer within ${BOOT_MIN} min" 3
  [ "$(left_s)" -gt 0 ] || fail "session cap reached while waiting for the server" 4
  if ! remote true 2>/dev/null; then
    brev refresh >/dev/null 2>&1 || true      # the ssh entry changes when the instance gets a new address
  elif [ "$served" = 0 ]; then
    names="$(remote "docker ps -a --format '{{.Names}}'" 2>/dev/null)"
    if [ "$?" = 0 ]; then
      if ! printf '%s\n' "$names" | grep -qx vllm; then
        say "no vllm container on the instance: running scripts/serve_vllm.sh there"
        served=1
        # without the script's own endless wait at the end: this loop waits, with a limit
        sed '/^echo "waiting for the server/,$d' scripts/serve_vllm.sh | remote 'bash -s' \
          || say "serve_vllm.sh returned an error; still waiting for the server"
        continue
      elif ! remote "docker ps --format '{{.Names}}'" 2>/dev/null | grep -qx vllm; then
        say "vllm container exists but is not running: docker start vllm"
        remote 'docker start vllm' >/dev/null 2>&1 || true
        served=1
      fi
    fi
  fi
  sleep "$POLL_S"
done
say "server healthy on the instance"

# --- c. the endpoint as the pipeline will reach it ------------------------------------------------------
models() { curl -sf -m 10 -H "Authorization: Bearer $OPENAI_API_KEY" "${OPENAI_BASE_URL%/}/models" >/dev/null 2>&1; }
wait_models() { local end=$(( $(date +%s) + $1 )); until models; do [ "$(date +%s)" -lt "$end" ] || return 1; sleep 3; done; }
case "$OPENAI_BASE_URL" in
  *localhost:8000*|*127.0.0.1:8000*)
    if models; then
      say "tunnel on localhost:8000 answers"
    else
      if pgrep -f "ssh -N" >/dev/null 2>&1; then
        say "an 'ssh -N' process is running (a reconnecting tunnel?); giving it 60 s"
        wait_models 60 || true
      fi
      if ! models; then
        say "no tunnel answers: starting one"
        ssh -N "${SSH_OPTS[@]}" -o ServerAliveInterval=15 -o ExitOnForwardFailure=yes -L 8000:localhost:8000 "$INSTANCE" &
        TUNNEL_PID=$!
        wait_models 90 || fail "no answer from ${OPENAI_BASE_URL%/}/models through the tunnel (is port 8000 taken by a dead tunnel? pkill -f 'ssh -N')" 5
      fi
      say "tunnel on localhost:8000 answers"
    fi ;;
  *)
    wait_models 60 || fail "no answer from ${OPENAI_BASE_URL%/}/models" 5
    say "endpoint answers (no tunnel needed for this address)" ;;
esac

# --- d. the commands ------------------------------------------------------------------------------------
n=0
for cmd in "$@"; do
  n=$((n + 1))
  [ "$(left_s)" -gt 60 ] || { say "session cap reached: command $n not started"; STATUS=4; break; }
  say "command $n of $#: $cmd"
  set -m                       # its own process group, so that the whole tree can be ended
  bash -c "$cmd" &
  CMD_PID=$!
  set +m
  while kill -0 "$CMD_PID" 2>/dev/null; do
    if [ "$(left_s)" -le 0 ]; then
      say "session cap of ${MAX_MIN} min reached: ending command $n"
      STATUS=4
      exit 4
    fi
    sleep "$POLL_S" &
    wait $! 2>/dev/null
  done
  wait "$CMD_PID"; code=$?
  CMD_PID=""
  say "command $n ended with code $code"
  if [ "$code" != 0 ]; then
    STATUS=$code
    [ "$KEEP_GOING" = 1 ] || { say "stopping at the first failure (GPU_KEEP_GOING=0)"; break; }
  fi
done
exit "$STATUS"
# --- e. the EXIT trap stops the instance and prints `brev ls` ---------------------------------------------
