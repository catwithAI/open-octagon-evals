#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${OCTAGON_EVALS_PYTHON:-}"
if [[ -z "$PYTHON_BIN" && -x "$ROOT_DIR/.venv/bin/python" ]]; then PYTHON_BIN="$ROOT_DIR/.venv/bin/python"; fi
if [[ -z "$PYTHON_BIN" ]]; then PYTHON_BIN="python3"; fi
port_free() { "$PYTHON_BIN" - "$1" <<'PY'
import socket, sys
s=socket.socket(); s.settimeout(.2)
try: s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError: raise SystemExit(1)
finally: s.close()
PY
}
API_HOST="${OCTAGON_EVALS_HOST:-127.0.0.1}"
API_PORT="${OCTAGON_EVALS_PORT:-8000}"
WEB_HOST="${OCTAGON_EVALS_WEB_HOST:-127.0.0.1}"
WEB_PORT="${OCTAGON_EVALS_WEB_PORT:-5173}"
JUDGE_HOST="${OCTAGON_JUDGE_HOST:-127.0.0.1}"
JUDGE_PORT="${OCTAGON_JUDGE_PORT:-8001}"
PI_BIN="${OCTAGON_JUDGE_PI_BIN:-pi}"
DB_PATH="${OCTAGON_EVALS_DB:-${ROOT_DIR}/data/octagon-evals.db}"

mkdir -p "$(dirname "$DB_PATH")"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export OCTAGON_EVALS_DB="$DB_PATH"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "error: Python interpreter not found: $PYTHON_BIN" >&2
  exit 1
}
"$PYTHON_BIN" -c 'import uvicorn, fastapi' >/dev/null 2>&1 || {
  echo "error: FastAPI/uvicorn are missing for $PYTHON_BIN; install with: $PYTHON_BIN -m pip install -e .'" >&2
  exit 1
}
command -v "$PI_BIN" >/dev/null 2>&1 || {
  echo "error: pi CLI not found: $PI_BIN; see docs/pi-judge.md#prerequisites" >&2
  exit 1
}
"$PI_BIN" --version >/dev/null 2>&1 || {
  echo "error: pi CLI is not runnable: $PI_BIN" >&2
  exit 1
}
if [[ -n "${OCTAGON_JUDGE_PROVIDER:-}" || -n "${OCTAGON_JUDGE_MODEL:-}" ]]; then
  auth_args=()
  [[ -n "${OCTAGON_JUDGE_PROVIDER:-}" ]] && auth_args+=(--provider "$OCTAGON_JUDGE_PROVIDER")
  [[ -n "${OCTAGON_JUDGE_MODEL:-}" ]] && auth_args+=(--model "$OCTAGON_JUDGE_MODEL")
  "$PI_BIN" auth check "${auth_args[@]}" --json >/dev/null || {
    echo "error: pi provider/model is not ready; run: $PI_BIN auth check ${auth_args[*]} --json" >&2
    exit 1
  }
fi
export OCTAGON_JUDGE_PI_BIN="$PI_BIN"

if ! port_free "$API_PORT"; then
  requested_api_port="$API_PORT"
  for candidate in $(seq $((API_PORT + 1)) $((API_PORT + 20))); do
    if [[ "$candidate" != "$JUDGE_PORT" && "$candidate" != "$WEB_PORT" ]] && port_free "$candidate"; then API_PORT="$candidate"; break; fi
  done
  [[ "$API_PORT" == "$requested_api_port" ]] && { echo "error: no free API port near $requested_api_port" >&2; exit 1; }
  echo "warning: API port $requested_api_port is busy; using $API_PORT" >&2
fi

if [[ "$JUDGE_PORT" == "$API_PORT" || "$JUDGE_PORT" == "$WEB_PORT" ]] || ! port_free "$JUDGE_PORT"; then
  requested_judge_port="$JUDGE_PORT"
  for candidate in $(seq $((JUDGE_PORT + 1)) $((JUDGE_PORT + 20))); do
    if [[ "$candidate" != "$API_PORT" && "$candidate" != "$WEB_PORT" ]] && port_free "$candidate"; then JUDGE_PORT="$candidate"; break; fi
  done
  [[ "$JUDGE_PORT" == "$requested_judge_port" ]] && { echo "error: no free judge port near $requested_judge_port" >&2; exit 1; }
  echo "warning: judge port $requested_judge_port is unavailable; using $JUDGE_PORT" >&2
fi
export OCTAGON_JUDGE_SERVICE_URL="http://${JUDGE_HOST}:${JUDGE_PORT}"

api_pid=""
web_pid=""
judge_pid=""
cleanup() {
  trap - EXIT INT TERM
  [[ -n "$api_pid" ]] && kill "$api_pid" 2>/dev/null || true
  [[ -n "$judge_pid" ]] && kill "$judge_pid" 2>/dev/null || true
  [[ -n "$web_pid" ]] && kill "$web_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "octagon-evals API: http://${API_HOST}:${API_PORT}"
echo "octagon-evals web: http://${WEB_HOST}:${WEB_PORT}"
echo "octagon-evals judge: http://${JUDGE_HOST}:${JUDGE_PORT}"
echo "open frontend with API: http://${WEB_HOST}:${WEB_PORT}/?api=http://${API_HOST}:${API_PORT}"
echo "SQLite database: ${DB_PATH}"

"$PYTHON_BIN" -m uvicorn octagon_evals.api:app --host "$API_HOST" --port "$API_PORT" &
api_pid=$!
"$PYTHON_BIN" -m uvicorn octagon_evals.judge_service.app:judge_app --host "$JUDGE_HOST" --port "$JUDGE_PORT" &
judge_pid=$!
python3 -m http.server "$WEB_PORT" --bind "$WEB_HOST" --directory "$ROOT_DIR/web" &
web_pid=$!

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$judge_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
echo "a server process exited; shutting down" >&2
exit 1
