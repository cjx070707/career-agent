#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

backend_pid=""
frontend_pid=""

cleanup() {
  if [[ -n "${frontend_pid}" ]] && kill -0 "${frontend_pid}" 2>/dev/null; then
    kill "${frontend_pid}" 2>/dev/null || true
  fi
  if [[ -n "${backend_pid}" ]] && kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "${ROOT_DIR}"

if [[ ! -d "web/node_modules" ]]; then
  echo "[dev] Installing frontend dependencies..."
  (cd web && npm install)
fi

echo "[dev] Starting FastAPI: http://${BACKEND_HOST}:${BACKEND_PORT}"
"${PYTHON_BIN}" -m uvicorn app.main:app \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload &
backend_pid="$!"

echo "[dev] Starting Vite: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
(
  cd web
  npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
) &
frontend_pid="$!"

echo ""
echo "[dev] Career Agent is starting."
echo "[dev] Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "[dev] API docs:  http://${BACKEND_HOST}:${BACKEND_PORT}/docs"
echo "[dev] Press Ctrl+C to stop both servers."
echo ""

while true; do
  if ! kill -0 "${backend_pid}" 2>/dev/null; then
    wait "${backend_pid}" || exit $?
    break
  fi
  if ! kill -0 "${frontend_pid}" 2>/dev/null; then
    wait "${frontend_pid}" || exit $?
    break
  fi
  sleep 1
done
