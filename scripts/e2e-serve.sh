#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"

HOST="${E2E_HOST:-127.0.0.1}"
BACKEND_PORT="${E2E_BACKEND_PORT:-8010}"
FRONTEND_PORT="${E2E_FRONTEND_PORT:-5174}"

DB_PATH="${E2E_DB_PATH:-/tmp/meetinggenius-e2e.sqlite3}"
MINDMAP_MIN_INTERVAL="${E2E_MINDMAP_MIN_INTERVAL_SECONDS:-0.9}"
MINDMAP_EXTRACTOR="${E2E_MINDMAP_EXTRACTOR:-${MEETINGGENIUS_MINDMAP_EXTRACTOR:-stub}}"

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

pick_python() {
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    echo "${ROOT_DIR}/.venv/bin/python"
    return 0
  fi
  if have_cmd python3; then
    echo "python3"
    return 0
  fi
  if have_cmd python; then
    echo "python"
    return 0
  fi
  return 1
}

terminate_pid_tree() {
  local -r pid="$1"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
}

cleanup() {
  terminate_pid_tree "${FRONTEND_PID:-}"
  terminate_pid_tree "${BACKEND_PID:-}"
}
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

if ! have_cmd npm; then
  echo "ERROR: npm not found on PATH (install Node.js 18+)." >&2
  exit 1
fi

PY="$(pick_python || true)"
if [[ -z "${PY}" ]]; then
  echo "ERROR: python not found on PATH." >&2
  exit 1
fi

if [[ ! -d "${ROOT_DIR}/apps/web/node_modules" ]]; then
  echo "ERROR: missing frontend dependencies." >&2
  echo "Run: (cd apps/web && npm install)" >&2
  exit 1
fi

cat <<EOF
E2E servers:
  Backend:  http://${HOST}:${BACKEND_PORT}  (WS: ws://${HOST}:${BACKEND_PORT}/ws)
  Frontend: http://${HOST}:${FRONTEND_PORT}
EOF

(
  cd "${ROOT_DIR}"
  MEETINGGENIUS_DB_PATH="${DB_PATH}" \
  MEETINGGENIUS_MINDMAP_EXTRACTOR="${MINDMAP_EXTRACTOR}" \
  MEETINGGENIUS_MINDMAP_AI_MIN_INTERVAL_SECONDS="${MINDMAP_MIN_INTERVAL}" \
  exec "${PY}" -m uvicorn meetinggenius.server:app --host "${HOST}" --port "${BACKEND_PORT}"
) &
BACKEND_PID="$!"

(
  cd "${ROOT_DIR}/apps/web"
  VITE_WS_URL="ws://${HOST}:${BACKEND_PORT}/ws" \
  exec npm run dev -- --host "${HOST}" --port "${FRONTEND_PORT}" --strictPort
) &
FRONTEND_PID="$!"

while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: backend process exited." >&2
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "ERROR: frontend process exited." >&2
    exit 1
  fi
  sleep 0.25
done
