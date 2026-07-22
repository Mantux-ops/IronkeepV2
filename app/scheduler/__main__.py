"""
IronkeepV2 scheduler entry point.

Usage:
    SCHEDULER_ENABLED=1 python -m app.scheduler

Environment variables:
    SCHEDULER_ENABLED       Must be set to "1" — process exits otherwise.
    SCHEDULER_POLL_SECONDS  Poll interval in seconds (default: 300 = 5 min).
    IRONKEEP_DB_PATH        Path to the SQLite database (same as web process).
    DISCORD_DISPATCH_ENABLED  Must be "1" for retry REST calls to execute.
    DISCORD_BOT_TOKEN         Required for metadata refresh REST calls.

Safety:
    The scheduler never mutates operation status, assignments, workspace
    memberships, or posts unsolicited announcements/rosters.
    All dispatch execution goes through the same _EXECUTABLE_EVENT_TYPES
    and _is_execution_enabled gates as the live dispatcher.
"""

from __future__ import annotations

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_log = logging.getLogger("app.scheduler")

POLL_SECONDS: int = int(os.environ.get("SCHEDULER_POLL_SECONDS", "300"))


def main() -> None:
    if not os.environ.get("SCHEDULER_ENABLED"):
        print(
            "SCHEDULER_ENABLED is not set — set it to '1' to start the scheduler.",
            file=sys.stderr,
        )
        sys.exit(0)

    from app import database  # noqa: PLC0415
    from app.scheduler import jobs  # noqa: PLC0415

    database.init_schema()
    _log.info("Scheduler started. Poll interval: %ds", POLL_SECONDS)

    while True:
        jobs.run_job("retry_dispatch_failures",   jobs.retry_dispatch_failures)
        jobs.run_job("refresh_stale_metadata",    jobs.refresh_stale_metadata)
        jobs.run_job("sync_albion_guild_rosters", jobs.sync_albion_guild_rosters)
        jobs.run_job("send_operation_reminders",  jobs.send_operation_reminders)
        _log.info("Sleeping %ds until next poll", POLL_SECONDS)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
