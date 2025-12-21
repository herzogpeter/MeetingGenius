#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

cd "$ROOT_DIR"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip >/dev/null
python -m pip install -e . >/dev/null

if [[ ! -d "apps/web/node_modules" ]]; then
  (cd apps/web && npm install)
fi

echo "Backend:  http://localhost:${BACKEND_PORT}  (WS: ws://localhost:${BACKEND_PORT}/ws)"
echo "Frontend: http://localhost:${FRONTEND_PORT}"
echo
echo "Starting backend + frontend (Ctrl+C to stop)…"

uvicorn meetinggenius.server:app --reload --port "${BACKEND_PORT}" &
BACKEND_PID=$!

(cd apps/web && VITE_WS_URL="ws://localhost:${BACKEND_PORT}/ws" npm run dev -- --port "${FRONTEND_PORT}") &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
