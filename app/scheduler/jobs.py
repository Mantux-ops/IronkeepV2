"""
Scheduler job functions.

Each job is a plain callable: () -> dict[str, int].  The polling loop in
__main__.py calls them, but tests import and call them directly without
starting the loop.

Safety rules (design decision):
  - Jobs may read any DB table.
  - Jobs may call refresh_discord_metadata (best-effort, already non-fatal).
  - Jobs may write to discord_dispatch_failures (status/retry updates only),
    operation_reminder_deliveries, and scheduler_runs.
  - Jobs may sync the imported Albion guild roster (workspace_albion_guilds,
    workspace_albion_players) via sync_workspace_rosters_system — this refreshes
    imported character data only and NEVER grants workspace memberships or
    links roster rows to Ironkeep users.
  - Jobs must NOT mutate operation status, create/remove assignments,
    post announcements or rosters, or grant workspace memberships.
  - The readiness-only dispatch policy is enforced by the existing
    _EXECUTABLE_EVENT_TYPES gate in dispatcher.py; retry calls resolve_action
    through that same path.

Backoff schedule (indexed by retry_count at time of failure):
  retry_count=0 → wait 5 min  (before 1st retry)
  retry_count=1 → wait 30 min (before 2nd retry)
  retry_count=2 → wait 2 h    (before 3rd retry)
  retry_count=3 → exhausted   (MAX_RETRIES reached after 3rd failure)

Reminder invariants (enforced in send_operation_reminders):
  - Reminders NEVER use operational events.
  - Reminders NEVER touch discord_messages.
  - Reminders ALWAYS create new posts (never edit).
  - Reminders are informational only — no lifecycle/status mutations.
  - Only planning + locked operations are eligible.
  - Reminders NEVER fire at/after scheduled_start_at.
  - Retries NEVER fire outside the reminder grace window.
  - Skipped status is mandatory when the window closes without sending.
  - Stale claimed rows (older than REMINDER_CLAIM_TIMEOUT_SECONDS) are
    reclaimable and retryable.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app import database, repositories

_log = logging.getLogger(__name__)

MAX_RETRIES: int = 3
METADATA_STALE_HOURS: int = 24

# Roster sync: a workspace's linked guilds are re-synced when their newest
# last_imported_at is older than this many hours (or never imported).  Keeps the
# scheduler from hammering the Albion API on every short poll interval.
ROSTER_SYNC_STALE_HOURS: int = 6

# Discord member nickname sync: a workspace's cached server nicknames are
# refreshed when the newest cache row is older than this many hours (or never
# fetched).  Members set their nickname to their in-game name; this keeps the
# workspace display names current without hammering the Discord API.
MEMBER_NICK_SYNC_STALE_HOURS: int = 6

_BACKOFF: list[timedelta] = [
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
]

# ---------------------------------------------------------------------------
# Reminder job constants
# ---------------------------------------------------------------------------

# Reminder windows: (name, offset_before_start).  Both must fire strictly
# before scheduled_start_at; the job skips any window where now >= start.
REMINDER_WINDOWS: list[tuple[str, timedelta]] = [
    ("T-2h",  timedelta(hours=2)),
    ("T-30m", timedelta(minutes=30)),
]

# A claimed delivery row older than this is considered stale and can be
# reclaimed by the next scheduler run (safe retry mechanism).
REMINDER_CLAIM_TIMEOUT_SECONDS: int = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Internal time helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _next_attempt_at(retry_count: int, now: datetime) -> str:
    """Return ISO-8601 UTC string for when the next retry is allowed."""
    delay = _BACKOFF[min(retry_count, len(_BACKOFF) - 1)]
    return _iso(now + delay)


# ---------------------------------------------------------------------------
# Scheduler run observability helpers
# ---------------------------------------------------------------------------

def write_scheduler_run_start(run_id: str, job_name: str, started_at: str) -> None:
    """Write the initial 'running' row.  finished_at is NULL until the job ends."""
    with database.transaction() as db:
        repositories.insert_scheduler_run(db, {
            "id":            run_id,
            "job_name":      job_name,
            "started_at":    started_at,
            "finished_at":   None,
            "status":        "running",
            "result_json":   "{}",
            "error_message": None,
        })


def write_scheduler_run_finish(
    run_id: str,
    status: str,
    result: dict,
    error_message: str | None,
) -> None:
    """Update the scheduler_runs row after the job completes or errors."""
    with database.transaction() as db:
        repositories.update_scheduler_run_finished(
            db,
            run_id=run_id,
            finished_at=_iso(_utcnow()),
            status=status,
            result_json=json.dumps(result),
            error_message=error_message,
        )


def run_job(job_name: str, fn) -> dict:
    """
    Wrapper: write scheduler_run start row → call fn() → write finish row.

    Returns the result dict from fn(), or {"error": str} on failure.
    Never raises: exceptions are caught, logged, and recorded in the run row.
    """
    run_id = str(uuid.uuid4())
    started_at = _iso(_utcnow())
    write_scheduler_run_start(run_id, job_name, started_at)
    try:
        result = fn()
        write_scheduler_run_finish(run_id, "success", result, None)
        _log.info("[%s] done: %s", job_name, result)
        return result
    except Exception as exc:
        _log.error("[%s] error: %s", job_name, exc, exc_info=True)
        write_scheduler_run_finish(run_id, "error", {}, str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Job: retry_dispatch_failures
# ---------------------------------------------------------------------------

def _build_retry_event(row: dict) -> dict:
    """
    Reconstruct the minimal event dict needed by dispatcher.resolve_action.

    The dispatcher reads fresh DB state for each call, so we only need the
    identity fields — not a verbatim replay of the original payload.
    """
    return {
        "id":                 row["id"],  # failure row id as synthetic event id
        "event_type":         row["event_type"],
        "guild_workspace_id": row["guild_workspace_id"],
        "guild_operation_id": row["guild_operation_id"],
        "entity_id":          row.get("entity_id"),
        "actor_type":         "system",
        "actor_id":           None,
        "entity_type":        "guild_operation",
        "payload_json":       row.get("payload_json") or "{}",
        "occurred_at":        row["attempted_at"],
    }


def _execute_retry_rest(action: dict, event: dict) -> str:
    """
    Execute a post_message or edit_message action for a retry attempt.

    Two-phase: REST call outside any DB transaction.
    Returns the Discord message_id on success.
    Raises DiscordApiError on failure (caller handles retry accounting).
    """
    from app.discord.rest_client import DiscordApiError, edit_message, post_message  # noqa: PLC0415

    channel_id = action.get("discord_channel_id")
    if not channel_id:
        raise ValueError(f"retry action has no channel_id: {action!r}")

    if action["action"] == "edit_message":
        try:
            edit_message(channel_id, action["discord_message_id"], action["payload"])
            return action["discord_message_id"]
        except DiscordApiError as err:
            if err.status_code == 404:
                _log.warning(
                    "retry edit_message 404 for failure %s — falling back to post",
                    event.get("id"),
                )
                return post_message(channel_id, action["payload"])
            raise
    else:
        return post_message(channel_id, action["payload"])


def _retry_one(row: dict, now: datetime, result: dict) -> None:
    """Process a single pending dispatch failure row."""
    from app import database, repositories  # noqa: PLC0415  (re-import for clarity inside helper)
    from app.discord import dispatcher  # noqa: PLC0415

    event = _build_retry_event(row)

    # Phase 1 (inside DB): resolve what action would be taken + read workspace
    try:
        with database.transaction() as db:
            action   = dispatcher.resolve_action(event, db)
            ws       = repositories.get_workspace_by_id(db, row["guild_workspace_id"])
    except Exception as exc:
        _log.error("retry_one: resolve_action failed for failure %s: %s", row["id"], exc)
        result["errors"] = result.get("errors", 0) + 1
        return

    # Noop means the operation/workspace is gone or no longer dispatchable.
    if action["action"] == "noop":
        _log.info(
            "retry_one: failure %s resolved as noop (%s)",
            row["id"],
            action.get("reason"),
        )
        with database.transaction() as db:
            repositories.resolve_dispatch_failure(
                db, row["id"], f"noop: {action.get('reason', '')}"
            )
        result["resolved"] = result.get("resolved", 0) + 1
        return

    # Only readiness events are executable (same gate as the live dispatcher).
    from app.discord.dispatcher import _EXECUTABLE_EVENT_TYPES  # noqa: PLC0415

    if row["event_type"] not in _EXECUTABLE_EVENT_TYPES:
        _log.info(
            "retry_one: failure %s event_type %s not in _EXECUTABLE_EVENT_TYPES — resolving",
            row["id"],
            row["event_type"],
        )
        with database.transaction() as db:
            repositories.resolve_dispatch_failure(
                db, row["id"], f"non-executable event type: {row['event_type']}"
            )
        result["resolved"] = result.get("resolved", 0) + 1
        return

    # Gate check: both env var and workspace opt-in must be enabled.
    enabled, reason = dispatcher._is_execution_enabled(ws)
    if not enabled:
        _log.info(
            "retry_one: failure %s gate off (%s) — leaving pending",
            row["id"],
            reason,
        )
        result["gate_skipped"] = result.get("gate_skipped", 0) + 1
        return

    # Phase 2 (outside DB): execute REST call.
    try:
        message_id = _execute_retry_rest(action, event)
    except Exception as exc:
        new_count = row.get("retry_count", 0) + 1
        if new_count >= MAX_RETRIES:
            _log.warning(
                "retry_one: failure %s exhausted after %d attempts: %s",
                row["id"],
                new_count,
                exc,
            )
            with database.transaction() as db:
                repositories.exhaust_dispatch_failure(db, row["id"], new_count, str(exc))
            result["exhausted"] = result.get("exhausted", 0) + 1
        else:
            next_at = _next_attempt_at(new_count, now)
            _log.info(
                "retry_one: failure %s still failing (attempt %d), next at %s: %s",
                row["id"],
                new_count,
                next_at,
                exc,
            )
            with database.transaction() as db:
                repositories.bump_dispatch_failure(db, row["id"], new_count, next_at, str(exc))
            result["still_pending"] = result.get("still_pending", 0) + 1
        return

    # REST succeeded — upsert discord_messages and mark failure resolved.
    msg_record = {
        "id":                 str(uuid.uuid4()),
        "guild_workspace_id": action["guild_workspace_id"],
        "guild_operation_id": action["guild_operation_id"],
        "message_type":       action["message_type"],
        "discord_channel_id": action["discord_channel_id"],
        "discord_message_id": message_id,
        "discord_guild_id":   action.get("discord_guild_id"),
        "posted_at":          _iso(now),
        "last_edited_at":     _iso(now),
        "is_deleted":         0,
    }
    try:
        with database.transaction() as db:
            repositories.upsert_discord_message(db, msg_record)
            repositories.resolve_dispatch_failure(db, row["id"], "ok")
    except Exception as exc:
        _log.error(
            "retry_one: REST succeeded but DB write failed for failure %s: %s",
            row["id"],
            exc,
        )
        result["errors"] = result.get("errors", 0) + 1
        return

    _log.info("retry_one: failure %s resolved (message_id=%s)", row["id"], message_id)
    result["resolved"] = result.get("resolved", 0) + 1


def retry_dispatch_failures() -> dict:
    """
    Retry all pending discord_dispatch_failures rows whose backoff window
    has expired.

    Returns a summary dict:
      {"checked": N, "resolved": N, "still_pending": N,
       "exhausted": N, "gate_skipped": N, "errors": N}
    """
    now = _utcnow()

    with database.transaction() as db:
        failures = repositories.get_pending_dispatch_failures_due(db, _iso(now))

    result: dict[str, int] = {
        "checked":      len(failures),
        "resolved":     0,
        "still_pending": 0,
        "exhausted":    0,
        "gate_skipped": 0,
        "errors":       0,
    }

    for row in failures:
        _retry_one(row, now, result)

    return result


# ---------------------------------------------------------------------------
# Job: refresh_stale_metadata
# ---------------------------------------------------------------------------

def refresh_stale_metadata() -> dict:
    """
    Refresh Discord metadata cache for workspaces where the cache is stale
    or entirely absent.

    A workspace qualifies if discord_guild_id is set AND any cache entry is
    older than METADATA_STALE_HOURS (or no entries exist yet).

    Failures from refresh_discord_metadata are swallowed (already logged by
    the use case) — a refresh error never aborts the scheduler job.

    Returns: {"workspaces_checked": N, "refreshed": N, "skipped": N, "errors": N}
    """
    from app.application import use_cases  # noqa: PLC0415

    now = _utcnow()
    threshold_at = _iso(now - timedelta(hours=METADATA_STALE_HOURS))

    with database.transaction() as db:
        workspaces = repositories.get_workspaces_needing_metadata_refresh(db, threshold_at)

    result: dict[str, int] = {
        "workspaces_checked": len(workspaces),
        "refreshed":          0,
        "skipped":            0,
        "errors":             0,
    }

    for ws in workspaces:
        ws_id = ws["id"]
        try:
            summary = use_cases.refresh_discord_metadata(ws_id)
            _log.info("refresh_stale_metadata: workspace %s refreshed: %s", ws_id, summary)
            result["refreshed"] += 1
        except Exception as exc:
            _log.warning(
                "refresh_stale_metadata: workspace %s error: %s", ws_id, exc
            )
            result["errors"] += 1

    return result


# ---------------------------------------------------------------------------
# Job: sync_albion_guild_rosters
# ---------------------------------------------------------------------------

def sync_albion_guild_rosters() -> dict:
    """Periodically re-sync Albion guild rosters for workspaces whose rosters
    are stale (never imported, or older than ROSTER_SYNC_STALE_HOURS).

    For each qualifying workspace, calls the system-actor roster sync use case
    (no RBAC).  This keeps the imported roster fresh so that Discord users can
    self-join by matching their display name to a current guild character.

    Per-workspace failures (e.g. Albion API errors) are logged and counted but
    never abort the job — one bad workspace does not block the others.

    Returns:
        {"workspaces_checked": N, "synced": N, "players_active": N,
         "stale_marked": N, "errors": N}
    """
    from app.application import use_cases  # noqa: PLC0415

    now = _utcnow()
    threshold_at = _iso(now - timedelta(hours=ROSTER_SYNC_STALE_HOURS))

    with database.transaction() as db:
        workspaces = repositories.get_workspaces_needing_roster_sync(db, threshold_at)

    result: dict[str, int] = {
        "workspaces_checked": len(workspaces),
        "synced":             0,
        "players_active":     0,
        "stale_marked":       0,
        "errors":             0,
    }

    for ws in workspaces:
        ws_id = ws["id"]
        try:
            summary = use_cases.sync_workspace_rosters_system(ws_id)
            result["synced"]         += 1
            result["players_active"] += summary.get("active", 0)
            result["stale_marked"]   += summary.get("stale_marked", 0)
            _log.info("sync_albion_guild_rosters: workspace %s synced: %s", ws_id, summary)
        except Exception as exc:
            _log.warning(
                "sync_albion_guild_rosters: workspace %s error: %s", ws_id, exc
            )
            result["errors"] += 1

    return result


# ---------------------------------------------------------------------------
# Job: sync_discord_member_nicknames
# ---------------------------------------------------------------------------

def sync_discord_member_nicknames() -> dict:
    """Periodically refresh cached Discord server nicknames for workspaces whose
    member cache is stale (never fetched, or older than
    MEMBER_NICK_SYNC_STALE_HOURS).

    For each qualifying workspace, calls sync_discord_member_nicknames_system,
    which reads the guild's members (requires the Server Members Intent) and
    updates workspace display names to members' in-game nicknames.

    Per-workspace failures (Discord errors, intent not enabled, missing token)
    are logged and counted but never abort the job.

    Returns:
        {"workspaces_checked": N, "synced": N, "names_updated": N, "errors": N}
    """
    from app.application import use_cases  # noqa: PLC0415

    now = _utcnow()
    threshold_at = _iso(now - timedelta(hours=MEMBER_NICK_SYNC_STALE_HOURS))

    with database.transaction() as db:
        workspaces = repositories.get_workspaces_needing_member_nick_sync(db, threshold_at)

    result: dict[str, int] = {
        "workspaces_checked": len(workspaces),
        "synced":             0,
        "names_updated":      0,
        "errors":             0,
    }

    for ws in workspaces:
        ws_id = ws["id"]
        try:
            summary = use_cases.sync_discord_member_nicknames_system(ws_id)
            if summary.get("status") == "ok":
                result["synced"] += 1
                result["names_updated"] += summary.get("names_updated", 0)
            else:
                # A non-ok status (e.g. intent not enabled) is not an exception
                # but should still be visible as a soft error in the run record.
                result["errors"] += 1
            _log.info("sync_discord_member_nicknames: workspace %s -> %s", ws_id, summary)
        except Exception as exc:
            _log.warning(
                "sync_discord_member_nicknames: workspace %s error: %s", ws_id, exc
            )
            result["errors"] += 1

    return result


# ---------------------------------------------------------------------------
# Job: send_operation_reminders
# ---------------------------------------------------------------------------

def _reminder_channel(operation_row: dict) -> str | None:
    """
    Return the Discord channel ID to post the reminder to, or None if none
    is configured.

    Preference: announcement channel first, then officer channel.
    """
    return (
        operation_row.get("discord_announcement_channel_id")
        or operation_row.get("discord_officer_channel_id")
    ) or None


def _process_reminder_window(
    op: dict,
    window_name: str,
    window_offset: timedelta,
    now: datetime,
    stale_cutoff_iso: str,
    result: dict,
) -> None:
    """
    Process a single (operation, window) pair for the reminder job.

    Phase 1 (inside DB): claim the delivery slot.
    Phase 2 (outside DB): REST post_message call.
    Phase 3 (inside DB): finalize or leave for stale-claim retry.

    Invariants enforced here:
    - Never fires at/after scheduled_start_at.
    - Retries never fire outside the grace window.
    - Skipped status is written when the window closes.
    """
    from app.discord import formatters  # noqa: PLC0415
    from app.discord.rest_client import DiscordApiError, post_message  # noqa: PLC0415

    now_iso = _iso(now)
    op_id = op["id"]
    ws_id = op["guild_workspace_id"]

    # Parse the operation start time
    try:
        from datetime import datetime as _dt  # noqa: PLC0415
        op_start = _dt.fromisoformat(op["scheduled_start_at"])
        if op_start.tzinfo is None:
            op_start = op_start.replace(tzinfo=__import__("datetime").timezone.utc)
    except (ValueError, TypeError) as exc:
        _log.error(
            "reminder: op %s has unparseable scheduled_start_at %r: %s",
            op_id, op.get("scheduled_start_at"), exc,
        )
        result["errors"] = result.get("errors", 0) + 1
        return

    # Never fire at or after scheduled_start_at (double-check even though the
    # query already filters this — guards against clock skew)
    if now >= op_start:
        _log.info(
            "reminder: op %s window %s past start (%s) — skipping",
            op_id, window_name, op["scheduled_start_at"],
        )
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op_id, window_name, ws_id, now_iso, "past_start",
            )
        result["skipped"] = result.get("skipped", 0) + 1
        return

    # Check if this window's fire time has arrived
    window_fire_at = op_start - window_offset
    if now < window_fire_at:
        # Not yet due — nothing to do this run
        return

    # -----------------------------------------------------------------------
    # Phase 1: claim the delivery slot (inside DB transaction)
    # -----------------------------------------------------------------------
    try:
        with database.transaction() as db:
            claim_result = repositories.try_claim_reminder_delivery(
                db, op_id, window_name, ws_id, now_iso, stale_cutoff_iso,
            )
    except Exception as exc:
        _log.error(
            "reminder: DB claim error for op %s window %s: %s",
            op_id, window_name, exc,
        )
        result["errors"] = result.get("errors", 0) + 1
        return

    if claim_result == "already_done":
        result["already_done"] = result.get("already_done", 0) + 1
        return

    if claim_result == "busy":
        _log.info(
            "reminder: op %s window %s is claimed by another run — skipping",
            op_id, window_name,
        )
        result["busy"] = result.get("busy", 0) + 1
        return

    # claim_result == "claimed" — we own the delivery slot
    # -----------------------------------------------------------------------
    # Re-validate eligibility after claiming (status may have changed between
    # the initial query and now)
    # -----------------------------------------------------------------------
    try:
        with database.transaction() as db:
            fresh_op = repositories.get_guild_operation(db, op_id, ws_id)
    except Exception as exc:
        _log.error(
            "reminder: DB re-fetch error for op %s: %s", op_id, exc,
        )
        result["errors"] = result.get("errors", 0) + 1
        return

    if not fresh_op or fresh_op["status"] not in ("planning", "locked"):
        _log.info(
            "reminder: op %s no longer eligible (status=%s) — skipping window %s",
            op_id, fresh_op.get("status") if fresh_op else "gone", window_name,
        )
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op_id, window_name, ws_id, now_iso, "operation_ineligible",
            )
        result["skipped"] = result.get("skipped", 0) + 1
        return

    # Re-check start time hasn't passed
    try:
        fresh_start = _dt.fromisoformat(fresh_op["scheduled_start_at"])
        if fresh_start.tzinfo is None:
            fresh_start = fresh_start.replace(
                tzinfo=__import__("datetime").timezone.utc
            )
    except (ValueError, TypeError):
        fresh_start = op_start  # fall back to original parsed time

    if now >= fresh_start:
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op_id, window_name, ws_id, now_iso, "past_start",
            )
        result["skipped"] = result.get("skipped", 0) + 1
        return

    # Resolve channel
    channel_id = _reminder_channel(op)
    if not channel_id:
        _log.info(
            "reminder: op %s window %s — no channel configured, skipping",
            op_id, window_name,
        )
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op_id, window_name, ws_id, now_iso, "no_channel",
            )
        result["skipped"] = result.get("skipped", 0) + 1
        return

    # -----------------------------------------------------------------------
    # Optionally attach the latest readiness snapshot (never recomputed live)
    # -----------------------------------------------------------------------
    readiness = None
    try:
        with database.transaction() as db:
            readiness = repositories.get_latest_readiness_snapshot(db, op_id, ws_id)
    except Exception:
        pass  # optional — failure here must not block the reminder

    # Build payload (pure formatter — no DB access, no side effects)
    payload = formatters.format_operation_reminder(fresh_op, window_name, readiness)

    # -----------------------------------------------------------------------
    # Phase 2: REST call (outside any DB transaction)
    # -----------------------------------------------------------------------
    try:
        post_message(channel_id, payload)
    except DiscordApiError as exc:
        _log.error(
            "reminder: REST failed for op %s window %s (channel %s): %s",
            op_id, window_name, channel_id, exc,
        )
        # Leave the row as 'claimed'.  The stale-claim timeout means the next
        # scheduler run (after REMINDER_CLAIM_TIMEOUT_SECONDS) can reclaim and
        # retry — but only while still within the grace window.
        result["errors"] = result.get("errors", 0) + 1
        return
    except Exception as exc:
        _log.error(
            "reminder: unexpected REST error for op %s window %s: %s",
            op_id, window_name, exc,
        )
        result["errors"] = result.get("errors", 0) + 1
        return

    # -----------------------------------------------------------------------
    # Phase 3: finalize (inside DB transaction)
    # -----------------------------------------------------------------------
    try:
        with database.transaction() as db:
            repositories.finalize_reminder_delivery(
                db, op_id, window_name, ws_id, _iso(now),
            )
    except Exception as exc:
        _log.error(
            "reminder: REST succeeded but DB finalize failed for op %s window %s: %s",
            op_id, window_name, exc,
        )
        result["errors"] = result.get("errors", 0) + 1
        return

    _log.info(
        "reminder: sent op %s window %s to channel %s", op_id, window_name, channel_id,
    )
    result["sent"] = result.get("sent", 0) + 1


def send_operation_reminders() -> dict:
    """
    Send pre-operation reminders for eligible operations.

    Eligible operations: status IN ('planning', 'locked'), Discord configured,
    workspace discord_reminders_enabled=1, not yet started.

    Two windows are processed per operation:
      T-2h  — fires when now >= scheduled_start_at - 2h
      T-30m — fires when now >= scheduled_start_at - 30m

    Each window uses a claim/finalize flow to ensure exactly-once delivery
    across scheduler restarts.  Stale claimed rows (older than
    REMINDER_CLAIM_TIMEOUT_SECONDS) are reclaimable.

    Invariants (see module docstring):
      - Never fires at/after scheduled_start_at.
      - Never touches discord_messages or operational_events.
      - Never edits — always posts a new message.
      - Skipped status is written whenever a window closes without sending.

    Returns:
      {"operations_checked": N, "windows_checked": N, "sent": N,
       "already_done": N, "skipped": N, "busy": N, "errors": N}
    """
    now = _utcnow()
    now_iso = _iso(now)
    stale_cutoff = now - timedelta(seconds=REMINDER_CLAIM_TIMEOUT_SECONDS)
    stale_cutoff_iso = _iso(stale_cutoff)

    with database.transaction() as db:
        eligible_ops = repositories.get_operations_eligible_for_reminders(db, now_iso)

    result: dict[str, int] = {
        "operations_checked": len(eligible_ops),
        "windows_checked":    0,
        "sent":               0,
        "already_done":       0,
        "skipped":            0,
        "busy":               0,
        "errors":             0,
    }

    for op in eligible_ops:
        for window_name, window_offset in REMINDER_WINDOWS:
            result["windows_checked"] += 1
            _process_reminder_window(
                op, window_name, window_offset, now, stale_cutoff_iso, result,
            )

    return result
