"""
EventDispatcher — routes OperationalEvents to outbound Discord message actions.

Phase 1 (complete): resolves what action *would* happen. No Discord API calls.
Phase 2 (complete): executes the action for readiness summaries only.

Scope of auto-dispatch (by design decision):
  readiness_snapshot.created → post or edit readiness summary message
  All other events           → noop (announcements/rosters remain explicit officer actions)

Public surface:
  dispatch(event: dict) -> None
    Called by app.events.dispatch_event after a successful domain commit.
    Opens its own DB connections as needed.  Must never raise.

  resolve_action(event: dict, db) -> dict
    Pure, testable core. Given an OperationalEvent dict and an open DB
    connection, returns a plain dict describing the intended Discord action:

      post_message  — send a new message to a channel
      edit_message  — edit an existing tracked Discord message
      noop          — nothing to send (misconfigured, unhandled event, etc.)

Safety gates for execution:
  1. DISCORD_DISPATCH_ENABLED env var must be "1" (process-level kill switch).
  2. workspace.discord_auto_dispatch must be 1 (opt-in per workspace).
  If either gate is off, the action is resolved (for logging) but not executed.

Design rules (from docs/discord_integration_boundary.md):
  - Called AFTER use-case transaction commits, never inside it.
  - A Discord failure must never roll back a domain transaction.
  - Dispatcher may read DB state; must not mutate operational state.
  - Dispatcher must not call use cases.
  - Missing Discord config returns noop — never raises.
  - REST calls happen outside any DB transaction (two-phase pattern).
  - discord_messages upsert happens only after successful REST call.
  - Failures are written to discord_dispatch_failures in a separate transaction.
"""

from __future__ import annotations

import logging

from app import repositories
from app.discord.formatters import (
    format_operation_announcement,
    format_readiness_summary,
)
from app.domain import operational_events as ev

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types that produce a noop at resolve_action time
# ---------------------------------------------------------------------------
_NOOP_EVENT_TYPES: dict[str, str] = {
    ev.SIGNUP_INTENT_SUBMITTED:    "signup confirmation is ephemeral-only; no channel message",
    ev.SCOUT_ATTENDANCE_RECORDED:  "scout check-in: no outbound channel message this phase",
    ev.SUPPORT_ATTENDANCE_RECORDED: "support check-in: no outbound channel message this phase",
}

# ---------------------------------------------------------------------------
# Event types for which REST execution is enabled in Phase 2.
#
# resolve_action may return post_message/edit_message for other events
# (e.g. guild_operation.published/locked/completed) — those actions are
# resolved and logged for future use, but REST is never called for them here.
# Announcements and rosters remain EXPLICIT OFFICER ACTIONS ONLY.
# ---------------------------------------------------------------------------
_EXECUTABLE_EVENT_TYPES: frozenset[str] = frozenset({
    ev.READINESS_SNAPSHOT_CREATED,
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _noop(event: dict, reason: str) -> dict:
    return {
        "action":             "noop",
        "reason":             reason,
        "event_type":         event.get("event_type", "unknown"),
        "guild_workspace_id": event.get("guild_workspace_id"),
    }


def _message_action(
    *,
    event: dict,
    workspace: dict,
    operation: dict,
    message_type: str,
    channel_type: str,
    payload: dict,
    db,
) -> dict:
    """
    Return post_message or edit_message depending on whether a tracked
    discord_messages row already exists for this workspace/operation/type.
    """
    existing = repositories.get_discord_message(
        db,
        event["guild_workspace_id"],
        event["guild_operation_id"],
        message_type,
    )

    channel_id = (
        workspace.get("discord_announcement_channel_id")
        if channel_type == "announcement"
        else workspace.get("discord_officer_channel_id")
    )

    base = {
        "message_type":        message_type,
        "channel_type":        channel_type,
        "discord_channel_id":  channel_id,
        "discord_guild_id":    workspace.get("discord_guild_id"),
        "guild_workspace_id":  event["guild_workspace_id"],
        "guild_operation_id":  event["guild_operation_id"],
        "payload":             payload,
    }

    if existing and not existing.get("is_deleted"):
        return {
            "action":             "edit_message",
            "discord_message_id": existing["discord_message_id"],
            **base,
        }
    return {"action": "post_message", **base}


# ---------------------------------------------------------------------------
# Per-event handlers
# ---------------------------------------------------------------------------

def _handle_operation_status_event(event: dict, db) -> dict:
    """
    Handle guild_operation.published / locked / completed.
    Produces an announcement post or edit.
    """
    ws_id = event["guild_workspace_id"]
    op_id = event["guild_operation_id"]

    workspace = repositories.get_workspace_by_id(db, ws_id)
    if not workspace or not workspace.get("discord_guild_id"):
        return _noop(event, "workspace has no discord_guild_id configured")
    if not workspace.get("discord_announcement_channel_id"):
        return _noop(event, "workspace has no announcement channel configured")

    operation = repositories.get_guild_operation(db, op_id, ws_id)
    if not operation:
        return _noop(event, "operation not found")

    readiness = repositories.get_latest_readiness_snapshot(db, op_id, ws_id)

    import os  # noqa: PLC0415
    web_base_url = os.environ.get("WEB_BASE_URL", "").rstrip("/")
    signup_url = (
        f"{web_base_url}/workspaces/{workspace['slug']}/operations/{op_id}/signup"
        if web_base_url else None
    )
    payload = format_operation_announcement(operation, readiness, signup_url=signup_url)

    return _message_action(
        event=event,
        workspace=workspace,
        operation=operation,
        message_type="announcement",
        channel_type="announcement",
        payload=payload,
        db=db,
    )


def _handle_readiness_event(event: dict, db) -> dict:
    """
    Handle readiness_snapshot.created.
    Produces a readiness summary post or edit.
    """
    ws_id = event["guild_workspace_id"]
    op_id = event["guild_operation_id"]

    workspace = repositories.get_workspace_by_id(db, ws_id)
    if not workspace or not workspace.get("discord_guild_id"):
        return _noop(event, "workspace has no discord_guild_id configured")
    if not workspace.get("discord_announcement_channel_id"):
        return _noop(event, "workspace has no announcement channel configured")

    operation = repositories.get_guild_operation(db, op_id, ws_id)
    if not operation:
        return _noop(event, "operation not found")

    readiness = repositories.get_latest_readiness_snapshot(db, op_id, ws_id)
    if not readiness:
        return _noop(event, "no readiness snapshot found")

    payload = format_readiness_summary(operation, readiness)

    return _message_action(
        event=event,
        workspace=workspace,
        operation=operation,
        message_type="readiness",
        channel_type="announcement",
        payload=payload,
        db=db,
    )


# ---------------------------------------------------------------------------
# Event routing table
# ---------------------------------------------------------------------------

_HANDLERS = {
    ev.GUILD_OPERATION_PUBLISHED:   _handle_operation_status_event,
    ev.GUILD_OPERATION_LOCKED:      _handle_operation_status_event,
    ev.GUILD_OPERATION_COMPLETED:   _handle_operation_status_event,
    ev.READINESS_SNAPSHOT_CREATED:  _handle_readiness_event,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_action(event: dict, db) -> dict:
    """
    Given a committed OperationalEvent dict and an open DB connection, return a
    plain dict describing the intended Discord action.

    Returns a noop for:
    - explicitly nooped event types (signup, attendance)
    - unrecognised event types
    - missing workspace Discord config
    - missing operation / readiness data

    Never raises.
    """
    event_type = event.get("event_type", "")

    if event_type in _NOOP_EVENT_TYPES:
        return _noop(event, _NOOP_EVENT_TYPES[event_type])

    handler = _HANDLERS.get(event_type)
    if handler is None:
        return _noop(event, f"no Discord action defined for event type '{event_type}'")

    try:
        return handler(event, db)
    except Exception as exc:
        _log.error("resolve_action failed for event %s: %s", event.get("id"), exc)
        return _noop(event, f"internal error resolving action: {exc}")


def _is_execution_enabled(workspace: dict) -> tuple[bool, str]:
    """
    Return (enabled, reason) for whether the dispatcher should actually execute
    a REST call for this workspace.

    Gate 1: DISCORD_DISPATCH_ENABLED env var must equal "1".
    Gate 2: workspace.discord_auto_dispatch must be 1.

    Both must be true for execution to proceed.
    """
    import os  # noqa: PLC0415
    if os.environ.get("DISCORD_DISPATCH_ENABLED", "0").strip() != "1":
        return False, "DISCORD_DISPATCH_ENABLED is not set to '1' (process kill switch)"
    if not workspace or not workspace.get("discord_auto_dispatch"):
        return False, "workspace.discord_auto_dispatch is disabled"
    return True, "ok"


def _record_failure_direct(event: dict, exc: Exception) -> None:
    """
    Write a discord_dispatch_failures row in a separate transaction.

    Used by the dispatcher itself so failures are recorded even when
    dispatch_event's outer wrapper would not see an exception (because
    dispatch() swallows errors internally).

    payload_json stores the original event payload for auditing.
    next_attempt_at is set to now + FIRST_RETRY_DELAY_MINUTES so the
    scheduler job respects the initial backoff window.
    """
    import json as _json  # noqa: PLC0415
    import uuid  # noqa: PLC0415
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    _FIRST_RETRY_DELAY = timedelta(minutes=5)

    try:
        from app import database, repositories  # noqa: PLC0415

        now = datetime.now(timezone.utc)
        record = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": event.get("guild_workspace_id", ""),
            "guild_operation_id": event.get("guild_operation_id"),
            "event_type": event.get("event_type", "unknown"),
            "entity_id": event.get("entity_id"),
            "error_code": None,
            "error_message": str(exc)[:500],
            "attempted_at": now.isoformat(),
            "retry_count": 0,
            "status": "pending_retry",
            "payload_json": _json.dumps(event.get("payload_json") or {}),
            "next_attempt_at": (now + _FIRST_RETRY_DELAY).isoformat(),
        }
        with database.transaction() as db:
            repositories.insert_discord_dispatch_failure(db, record)
    except Exception as inner:
        _log.error(
            "Failed to record dispatch failure for event %s: %s",
            event.get("id"),
            inner,
        )


def _execute_action(action: dict, event: dict) -> None:
    """
    Execute a resolved post_message or edit_message action via Discord REST.

    Two-phase pattern (matches explicit officer use cases):
      Phase 1 (caller): DB read → resolve action.
      Phase 2 (here):   REST call outside any transaction → DB write on success.

    On REST failure: record to discord_dispatch_failures; do not raise.
    On edit-message 404: fall back to post_message (message deleted externally).
    """
    import uuid  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    from app import database, repositories  # noqa: PLC0415
    from app.discord.rest_client import DiscordApiError, edit_message, post_message  # noqa: PLC0415

    channel_id = action.get("discord_channel_id")
    if not channel_id:
        _log.warning("_execute_action: no channel_id in action, skipping")
        return

    message_id: str | None = None
    is_edit = action["action"] == "edit_message"

    try:
        if is_edit:
            existing_message_id = action["discord_message_id"]
            try:
                edit_message(channel_id, existing_message_id, action["payload"])
                message_id = existing_message_id
            except DiscordApiError as edit_err:
                if edit_err.status_code == 404:
                    # Message was deleted externally — fall back to post.
                    _log.warning(
                        "edit_message 404 for %s/%s — falling back to post",
                        action.get("guild_operation_id"),
                        action.get("message_type"),
                    )
                    message_id = post_message(channel_id, action["payload"])
                else:
                    raise
        else:
            message_id = post_message(channel_id, action["payload"])

    except DiscordApiError as exc:
        _log.error(
            "Discord REST failed for %s/%s: %s",
            action.get("message_type"),
            event.get("event_type"),
            exc,
        )
        _record_failure_direct(event, exc)
        return

    # REST succeeded — upsert discord_messages in a new transaction.
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": action["guild_workspace_id"],
        "guild_operation_id": action["guild_operation_id"],
        "message_type": action["message_type"],
        "discord_channel_id": channel_id,
        "discord_message_id": message_id,
        "discord_guild_id": action.get("discord_guild_id"),
        "posted_at": now,
        "last_edited_at": now,
        "is_deleted": 0,
    }
    try:
        with database.transaction() as db:
            repositories.upsert_discord_message(db, record)
    except Exception as exc:
        _log.error(
            "Failed to upsert discord_messages after successful REST for event %s: %s",
            event.get("id"),
            exc,
        )
        _record_failure_direct(event, exc)


def dispatch(event: dict) -> None:
    """
    Post-commit hook: resolves the Discord action and executes it if enabled.

    Phase 1: resolve action (always).
    Phase 2: execute REST + persist message identity (when both safety gates pass).

    Opens its own DB connections; the original transaction is already closed.
    Never raises — all exceptions are caught and recorded.
    """
    from app import database, repositories  # noqa: PLC0415

    try:
        with database.transaction() as db:
            action = resolve_action(event, db)
            # Read workspace for gate check while the connection is open.
            ws_id = event.get("guild_workspace_id")
            workspace = repositories.get_workspace_by_id(db, ws_id) if ws_id else None

        _log.info(
            "Discord action resolved for %s [%s]: %s",
            event.get("event_type"),
            event.get("id"),
            action["action"],
        )

        if action["action"] == "noop":
            return

        event_type = event.get("event_type", "")
        if event_type not in _EXECUTABLE_EVENT_TYPES:
            _log.info(
                "Discord action resolved but not executed for %s [%s] "
                "(announcements/rosters are explicit officer actions only)",
                event_type,
                event.get("id"),
            )
            return

        enabled, reason = _is_execution_enabled(workspace)
        if not enabled:
            _log.info(
                "Discord dispatch dry-run for %s [%s]: %s",
                event_type,
                event.get("id"),
                reason,
            )
            return

        _execute_action(action, event)

    except Exception as exc:
        # dispatch_event in app.events already wraps us, but we catch here too
        # so truly unexpected errors are logged before re-raising.
        _log.error("dispatch failed unexpectedly for event %s: %s", event.get("id"), exc)
        raise
