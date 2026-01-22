#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BIND_HOST="${BIND_HOST:-0.0.0.0}"

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
BIND_HOST="${BIND_HOST:-0.0.0.0}"

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
if [[ -z "$PUBLIC_HOST" ]]; then
  if [[ "$BIND_HOST" == "0.0.0.0" ]]; then
    echo "WARN: could not auto-detect your LAN IP; set PUBLIC_HOST (e.g. PUBLIC_HOST=192.168.1.50)." >&2
  fi
  PUBLIC_HOST="localhost"
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

  echo "WARN: ${label} did not exit; sending SIGKILL..." >&2
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
if ! have_cmd mkcert; then
  cat <<'EOF' >&2
ERROR: mkcert is required for HTTPS + WSS local certs.

Install it and trust the local CA:
  macOS:  brew install mkcert && mkcert -install
  Ubuntu: sudo apt install mkcert && mkcert -install
  Windows: choco install mkcert && mkcert -install
EOF
  exit 1
fi

CERT_DIR="${CERT_DIR:-${ROOT_DIR}/.certs}"
CERT_FILE="${CERT_FILE:-${CERT_DIR}/meetinggenius.pem}"
KEY_FILE="${KEY_FILE:-${CERT_DIR}/meetinggenius-key.pem}"

mkdir -p "$CERT_DIR"

if ! mkcert -install >/dev/null 2>&1; then
  echo "ERROR: mkcert could not install the local CA. Try: mkcert -install" >&2
  exit 1
fi

CERT_HOSTS=("localhost" "127.0.0.1" "::1")
if [[ -n "$PUBLIC_HOST" && "$PUBLIC_HOST" != "localhost" && "$PUBLIC_HOST" != "127.0.0.1" ]]; then
  CERT_HOSTS+=("$PUBLIC_HOST")
fi
if [[ "$BIND_HOST" != "0.0.0.0" && "$BIND_HOST" != "localhost" && "$BIND_HOST" != "127.0.0.1" ]]; then
  CERT_HOSTS+=("$BIND_HOST")
fi

mkcert -cert-file "$CERT_FILE" -key-file "$KEY_FILE" "${CERT_HOSTS[@]}"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip >/dev/null
python -m pip install -e . >/dev/null

(cd apps/web && npm install)

VITE_WS_URL="wss://${PUBLIC_HOST}:${BACKEND_PORT}/ws"

cat <<EOF
Backend:  https://${PUBLIC_HOST}:${BACKEND_PORT}  (bind: ${BIND_HOST})
Frontend: https://${PUBLIC_HOST}:${FRONTEND_PORT}  (bind: ${BIND_HOST})
WSS:      ${VITE_WS_URL}
Cert:     ${CERT_FILE}

LAN mic mode:
  1) Open the frontend URL from another device on your LAN.
  2) Accept the cert warning once (mkcert makes this trusted locally).
  3) Use "Live mic" in the Transcript panel.

Starting backend + frontend (Ctrl+C to stop)...
EOF

start_process BACKEND_PID "exec uvicorn meetinggenius.server:app --reload --host \"${BIND_HOST}\" --port \"${BACKEND_PORT}\" --ssl-keyfile \"${KEY_FILE}\" --ssl-certfile \"${CERT_FILE}\""
start_process FRONTEND_PID "cd apps/web && MG_DEV_HTTPS_CERT=\"${CERT_FILE}\" MG_DEV_HTTPS_KEY=\"${KEY_FILE}\" VITE_WS_URL=\"${VITE_WS_URL}\" exec npm run dev -- --host \"${BIND_HOST}\" --port \"${FRONTEND_PORT}\""

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
