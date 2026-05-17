#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/run_scheduler.sh — Start the IronkeepV2 scheduler process (production).
#
# Usage:
#   ./scripts/run_scheduler.sh
#
# Environment:
#   Source your environment file before running, or set variables inline.
#   SCHEDULER_ENABLED must be "1" — the process exits immediately otherwise.
#   DISCORD_DISPATCH_ENABLED must be "1" for live Discord retries to execute.
#
# Safety:
#   The scheduler never posts unsolicited announcements or rosters.
#   All dispatch goes through the same gates as the live web dispatcher.
#   Safe to restart at any time — jobs use claim/finalize for deduplication.
# ---------------------------------------------------------------------------
set -euo pipefail

export SCHEDULER_ENABLED="${SCHEDULER_ENABLED:-1}"
export DISCORD_DISPATCH_ENABLED="${DISCORD_DISPATCH_ENABLED:-1}"
POLL="${SCHEDULER_POLL_SECONDS:-300}"

echo "Starting IronkeepV2 scheduler (poll interval: ${POLL}s) ..."

exec python -m app.scheduler
