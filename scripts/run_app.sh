#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/run_app.sh — Start the IronkeepV2 web process (production).
#
# Usage:
#   ./scripts/run_app.sh
#
# Environment:
#   Source your environment file before running, or set variables inline.
#   See docs/deployment.md for the full list of required variables.
#
# Assumptions:
#   - Running from the project root directory.
#   - The virtual environment is activated (or uvicorn is on PATH).
#   - IRONKEEP_ENV, IRONKEEP_SESSION_SECRET, IRONKEEP_DB_PATH are set.
# ---------------------------------------------------------------------------
set -euo pipefail

HOST="${IRONKEEP_HOST:-0.0.0.0}"
PORT="${IRONKEEP_PORT:-8000}"
LOG_LEVEL="${IRONKEEP_LOG_LEVEL:-info}"

echo "Starting IronkeepV2 web process on ${HOST}:${PORT} ..."

exec uvicorn app.main:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --workers 1 \
  --log-level "${LOG_LEVEL}"
