#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "created backend/.env"
fi

if [ ! -f .env.local ]; then
  cp .env.example .env.local
  echo "created .env.local"
fi

if [ ! -d node_modules ]; then
  npm install
fi

if [ ! -x backend/.venv/bin/python ]; then
  python3 -m venv backend/.venv
fi

backend/.venv/bin/python -m pip install -q -r backend/requirements.txt

cleanup() {
  kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(
  cd backend
  .venv/bin/python -m uvicorn app.main:app --port 8000
) &
backend_pid=$!

npm run dev &
frontend_pid=$!

while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid"
    exit $?
  fi
  if ! kill -0 "$frontend_pid" 2>/dev/null; then
    wait "$frontend_pid"
    exit $?
  fi
  sleep 1
done
