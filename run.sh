#!/usr/bin/env bash
# Start Kumbh Sahayak locally: http://localhost:8000 (voice) and http://localhost:8000/chat (text)
set -e
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt; }
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
