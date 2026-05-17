"""
Post-commit OperationalEvent dispatch orchestration.

Rules (from docs/discord_integration_boundary.md):
- Called AFTER a use-case transaction commits, never inside it.
- A dispatch failure must never rollback the already-committed domain transaction.
- Dispatch is synchronous and best-effort; this module never raises to callers.
- Only events in DISPATCHABLE_EVENT_TYPES are forwarded to the dispatcher.
  All others are silently skipped — they have no outbound communication purpose.
- Failures are recorded in discord_dispatch_failures using a separate
  transaction; a double-fault (failure recording also fails) is logged only.

Phase 1: dispatcher.dispatch() is a no-op, so no Discord calls are made.
Phase 2: dispatcher routes events to Discord API.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist: only these event types are forwarded to the dispatcher.
# Internal bookkeeping events (assignment.created, reserve.*, slots.generated,
# operation_plan.attached, etc.) are excluded — they have no Discord output.
# Add types here when a Discord handler is wired in Phase 2.
# ---------------------------------------------------------------------------
DISPATCHABLE_EVENT_TYPES: frozenset[str] = frozenset({
    "workspace.created",
    "guild_operation.published",
    "guild_operation.locked",
    "guild_operation.completed",
    "readiness_snapshot.created",
    "signup_intent.submitted",
    "scout_attendance.recorded",
    "support_attendance.recorded",
})


def dispatch_event(event: dict) -> None:
    """
    Dispatch one committed OperationalEvent to outbound handlers.

    Best-effort: never raises.  Dispatcher exceptions are caught and recorded
    in discord_dispatch_failures via a separate DB transaction.
    """
    if event.get("event_type") not in DISPATCHABLE_EVENT_TYPES:
        return

    try:
        from app.discord import dispatcher  # noqa: PLC0415
        dispatcher.dispatch(event)
    except Exception as exc:
        _log.error(
            "Discord dispatch failed for event %s (%s): %s",
            event.get("id"),
            event.get("event_type"),
            exc,
        )
        _record_failure(event, exc)


def _record_failure(event: dict, exc: Exception) -> None:
    """
    Persist a dispatch failure row in a separate transaction.

    This is fully independent of the already-committed domain transaction.
    A double-fault here is logged but never re-raised.
    """
    try:
        from datetime import timedelta  # noqa: PLC0415

        from app import database, repositories  # noqa: PLC0415

        _FIRST_RETRY_DELAY = timedelta(minutes=5)
        now = datetime.now(timezone.utc)
        record = {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": event.get("guild_workspace_id", ""),
            "guild_operation_id": event.get("guild_operation_id"),
            "event_type":         event.get("event_type", "unknown"),
            "entity_id":          event.get("entity_id"),
            "error_code":         None,
            "error_message":      str(exc)[:500],
            "attempted_at":       now.isoformat(),
            "retry_count":        0,
            "status":             "pending_retry",
            "payload_json":       event.get("payload_json") or "{}",
            "next_attempt_at":    (now + _FIRST_RETRY_DELAY).isoformat(),
        }
        with database.transaction() as db:
            repositories.insert_discord_dispatch_failure(db, record)
    except Exception as record_exc:
        _log.error(
            "Failed to record dispatch failure for event %s: %s",
            event.get("id"),
            record_exc,
        )
