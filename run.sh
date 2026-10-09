#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8000}"
exec python -m uvicorn backend.app.main:app --host "${HOST:-127.0.0.1}" --port "$PORT" "$@"
