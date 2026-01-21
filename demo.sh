#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"

cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  xtrace_was_on=0
  if [[ "$-" == *x* ]]; then
    xtrace_was_on=1
    set +x
  fi
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
  if [[ "$xtrace_was_on" == "1" ]]; then
    set -x
  fi
fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"

detect_public_host() {
  local ip=""
  if command -v ipconfig >/dev/null 2>&1; then
    ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
    if [[ -z "$ip" ]]; then
      ip="$(ipconfig getifaddr en1 2>/dev/null || true)"
    fi
  fi
  if [[ -z "$ip" ]] && command -v ifconfig >/dev/null 2>&1; then
    ip="$(ifconfig | awk '/inet / && $2 != \"127.0.0.1\" {print $2; exit}' || true)"
  fi
  printf "%s" "$ip"
}

PUBLIC_HOST="${PUBLIC_HOST:-}"
if [[ -z "$PUBLIC_HOST" ]]; then
  if [[ "$BIND_HOST" == "0.0.0.0" ]]; then
    PUBLIC_HOST="$(detect_public_host)"
  else
    PUBLIC_HOST="$BIND_HOST"
  fi
fi
if [[ -z "$PUBLIC_HOST" && "$BIND_HOST" == "0.0.0.0" ]]; then
  echo "WARN: could not auto-detect your LAN IP; set PUBLIC_HOST (e.g. PUBLIC_HOST=192.168.1.50)." >&2
fi

# Only force VITE_WS_URL when needed; otherwise let the UI infer it from window.location.
if [[ -z "${VITE_WS_URL:-}" && "${BACKEND_PORT}" != "8000" ]]; then
  VITE_WS_URL="ws://${PUBLIC_HOST:-localhost}:${BACKEND_PORT}/ws"
fi

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

start_process() {
  local -r out_var="$1"
  local -r cmd="$2"

  bash -lc "$cmd" &
  printf -v "$out_var" "%s" "$!"
}

kill_descendants() {
  local -r pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  if [[ -z "$children" ]]; then
    return 0
  fi

  local child
  for child in $children; do
    kill_descendants "$child" || true
    kill -TERM "$child" 2>/dev/null || true
  done
}

terminate_pid_tree() {
  local -r pid="$1"
  local -r label="$2"

  if [[ -z "$pid" ]]; then
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  kill_descendants "$pid" || true
  kill -TERM "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done

  echo "WARN: ${label} did not exit; sending SIGKILL…" >&2
  kill_descendants "$pid" || true
  kill -KILL "$pid" 2>/dev/null || true
}

cleanup() {
  terminate_pid_tree "${FRONTEND_PID:-}" "frontend"
  terminate_pid_tree "${BACKEND_PID:-}" "backend"
}
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

if ! have_cmd python3; then
  echo "ERROR: python3 not found on PATH." >&2
  exit 1
fi
if ! have_cmd npm; then
  echo "ERROR: npm not found on PATH (install Node.js 18+)." >&2
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip >/dev/null
python -m pip install -e . >/dev/null

(cd apps/web && npm install)

cat <<EOF
Backend:  http://${PUBLIC_HOST:-localhost}:${BACKEND_PORT}  (bind: ${BIND_HOST})
Frontend: http://${PUBLIC_HOST:-localhost}:${FRONTEND_PORT}  (bind: ${BIND_HOST})
WS:       ws://${PUBLIC_HOST:-localhost}:${BACKEND_PORT}/ws
${VITE_WS_URL:+VITE_WS_URL=${VITE_WS_URL}}

Demo steps:
  1) Open the frontend URL.
  2) In the header, set "External research" to On (recommended for data-backed cards).
  3) In the Transcript panel, click Reset (optional).
  4) Paste a prompt and click Send.
  5) If you want to force/re-run, click "Run AI now".

Try these prompts:
  - Standup: "Summarize today's standup into 3 wins, 3 blockers, and 3 next steps."
  - Planning: "Turn our planning discussion into a prioritized backlog with owners and rough estimates."
  - Sales call: "Extract buyer pain points, objections, and next steps from this sales call."

Starting backend + frontend (Ctrl+C to stop)…
EOF

start_process BACKEND_PID "exec uvicorn meetinggenius.server:app --reload --host \"${BIND_HOST}\" --port \"${BACKEND_PORT}\""
if [[ -n "${VITE_WS_URL:-}" ]]; then
  start_process FRONTEND_PID "cd apps/web && VITE_WS_URL=\"${VITE_WS_URL}\" exec npm run dev -- --host \"${BIND_HOST}\" --port \"${FRONTEND_PORT}\""
else
  start_process FRONTEND_PID "cd apps/web && exec npm run dev -- --host \"${BIND_HOST}\" --port \"${FRONTEND_PORT}\""
fi

while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: backend process exited." >&2
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "ERROR: frontend process exited." >&2
    exit 1
  fi
  sleep 0.2
done
