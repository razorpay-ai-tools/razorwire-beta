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

wait "$backend_pid" "$frontend_pid"
