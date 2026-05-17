"""
OperationalEvent construction helpers.

Every state-changing use-case command must emit at least one event within
the same database transaction.  Events are append-only and must never be
deleted or updated.

  Event taxonomy:
  Workspace-level  — guild_operation_id is None
    workspace.created
    workspace.discord_config.updated
    workspace.member.removed
    albion_composition.created
    albion_composition.deleted
    albion_identity.claimed
    albion_identity.approved
    albion_identity.rejected

  Operation-level  — guild_operation_id is required
    guild_operation.created
    guild_operation.published
    guild_operation.locked
    guild_operation.completed
    guild_operation.archived
    operation_plan.attached
    operation_slots.generated
    signup_intent.submitted
    signup_intent.withdrawn
    assignment.created
    assignment.removed
    reserve.created
    reserve.removed
    readiness_snapshot.created
    payout_ledger.entry.created
    payout_ledger.entry.updated
    payout_ledger.entry.approved
    payout_ledger.entry.paid
    payout_ledger.entry.voided
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.errors import ValidationError

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
WORKSPACE_CREATED = "workspace.created"
WORKSPACE_DISCORD_CONFIG_UPDATED = "workspace.discord_config.updated"
WORKSPACE_MEMBER_REMOVED = "workspace.member.removed"
ALBION_COMPOSITION_CREATED = "albion_composition.created"
ALBION_COMPOSITION_DELETED = "albion_composition.deleted"
GUILD_OPERATION_CREATED    = "guild_operation.created"
GUILD_OPERATION_PUBLISHED  = "guild_operation.published"
GUILD_OPERATION_LOCKED     = "guild_operation.locked"
GUILD_OPERATION_COMPLETED  = "guild_operation.completed"
GUILD_OPERATION_ARCHIVED   = "guild_operation.archived"
OPERATION_PLAN_ATTACHED = "operation_plan.attached"
OPERATION_SLOTS_GENERATED = "operation_slots.generated"
SIGNUP_INTENT_SUBMITTED  = "signup_intent.submitted"
SIGNUP_INTENT_WITHDRAWN  = "signup_intent.withdrawn"
ASSIGNMENT_CREATED = "assignment.created"
ASSIGNMENT_REMOVED = "assignment.removed"
RESERVE_CREATED    = "reserve.created"
RESERVE_REMOVED    = "reserve.removed"
READINESS_SNAPSHOT_CREATED = "readiness_snapshot.created"
ATTENDANCE_RECORDED         = "attendance.recorded"
SCOUT_ATTENDANCE_RECORDED   = "scout_attendance.recorded"
SUPPORT_ATTENDANCE_RECORDED = "support_attendance.recorded"
# Explicit officer actions — Discord outbound messages triggered from the web UI.
# These are audit events only; they are NOT in DISPATCHABLE_EVENT_TYPES because
# the officer already caused the Discord action directly and no further dispatch
# should follow.
DISCORD_ANNOUNCEMENT_POSTED  = "discord_announcement.posted"
DISCORD_ANNOUNCEMENT_UPDATED = "discord_announcement.updated"
DISCORD_ROSTER_POSTED  = "discord_roster.posted"
DISCORD_ROSTER_UPDATED = "discord_roster.updated"
# Identity events — workspace-level, audit-only, not dispatchable.
# Emitted once per workspace the user is a member of.
USER_DISCORD_LINKED = "user.discord_linked"
# Albion identity events — workspace-level, audit-only, not dispatchable.
# Emitted when a user submits, an officer approves, or an officer rejects
# an Albion character claim within a workspace.
ALBION_IDENTITY_CLAIMED  = "albion_identity.claimed"
ALBION_IDENTITY_APPROVED = "albion_identity.approved"
ALBION_IDENTITY_REJECTED = "albion_identity.rejected"
# Payout ledger events — operation-level, audit-only, not dispatchable.
# Emitted when a ledger entry is created, updated, approved, or voided.
PAYOUT_LEDGER_ENTRY_CREATED  = "payout_ledger.entry.created"
PAYOUT_LEDGER_ENTRY_UPDATED  = "payout_ledger.entry.updated"
PAYOUT_LEDGER_ENTRY_APPROVED = "payout_ledger.entry.approved"
PAYOUT_LEDGER_ENTRY_PAID     = "payout_ledger.entry.paid"
PAYOUT_LEDGER_ENTRY_VOIDED   = "payout_ledger.entry.voided"

_OPERATION_LEVEL_EVENTS = frozenset(
    {
        GUILD_OPERATION_CREATED,
        GUILD_OPERATION_PUBLISHED,
        GUILD_OPERATION_LOCKED,
        GUILD_OPERATION_COMPLETED,
        GUILD_OPERATION_ARCHIVED,
        OPERATION_PLAN_ATTACHED,
        OPERATION_SLOTS_GENERATED,
        SIGNUP_INTENT_SUBMITTED,
        SIGNUP_INTENT_WITHDRAWN,
        ASSIGNMENT_CREATED,
        ASSIGNMENT_REMOVED,
        RESERVE_CREATED,
        RESERVE_REMOVED,
        READINESS_SNAPSHOT_CREATED,
        ATTENDANCE_RECORDED,
        SCOUT_ATTENDANCE_RECORDED,
        SUPPORT_ATTENDANCE_RECORDED,
        DISCORD_ANNOUNCEMENT_POSTED,
        DISCORD_ANNOUNCEMENT_UPDATED,
        DISCORD_ROSTER_POSTED,
        DISCORD_ROSTER_UPDATED,
        PAYOUT_LEDGER_ENTRY_CREATED,
        PAYOUT_LEDGER_ENTRY_UPDATED,
        PAYOUT_LEDGER_ENTRY_APPROVED,
        PAYOUT_LEDGER_ENTRY_PAID,
        PAYOUT_LEDGER_ENTRY_VOIDED,
    }
)


def make_event(
    *,
    guild_workspace_id: str,
    guild_operation_id: str | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    payload: dict | None = None,
) -> dict:
    """
    Build a complete operational_events row dict.

    guild_operation_id is required for operation-level events and will raise
    ValidationError if absent for those event types.
    """
    if event_type in _OPERATION_LEVEL_EVENTS and not guild_operation_id:
        raise ValidationError(
            f"Event type '{event_type}' is operation-level and requires guild_operation_id."
        )
    return {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": guild_workspace_id,
        "guild_operation_id": guild_operation_id,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload_json": json.dumps(payload or {}),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
