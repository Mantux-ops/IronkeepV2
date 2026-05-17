"""
Readiness calculation — pure domain logic, no DB access.

A slot's assignment state is derived from the assignments table at query time;
operation_slots itself carries no status column.

Readiness states:
  ready      — every slot has an active assignment
  forming    — >= 75% of slots are assigned
  not_ready  — < 75% of slots are assigned, or no slots exist

The state is based solely on slot/assignment coverage.  Attendance and scout
counts enrich the snapshot but do NOT gate the state: readiness is about
whether the operation can execute, not whether records have been fully marked.

Gap fields:
  missing_roles_json  — dict of role → open-slot count, e.g. {"DPS": 2, "Tank": 1}
  missing_builds_json — dict of build_name → open-slot count, e.g. {"Bow": 1}

Both dicts are empty ({}) when all slots are assigned.  Keys are sorted for
stable, deterministic output.  Source: operation_slots only — never
composition_slot_templates.
"""

from __future__ import annotations

import json
from collections import Counter


def calculate_readiness_state(total_slots: int, open_slots: int) -> str:
    if total_slots == 0:
        return "not_ready"
    if open_slots == 0:
        return "ready"
    fill_ratio = (total_slots - open_slots) / total_slots
    if fill_ratio >= 0.75:
        return "forming"
    return "not_ready"


def _gap_counts(open_slots: list[dict], key: str) -> dict:
    """
    Count open slots by a slot field (e.g. 'role' or 'build_name').
    Returns a dict with sorted keys for stable JSON output.
    """
    counts = Counter(s[key] for s in open_slots)
    return dict(sorted(counts.items()))


def build_readiness_snapshot(
    slots: list[dict],
    assigned_slot_ids: set[str],
    unassigned_signup_count: int,
    attendance_marked_count: int = 0,
    scout_count: int = 0,
    support_count: int = 0,
    reserve_count: int = 0,
) -> dict:
    """
    Compute the fields for a ReadinessSnapshot row.

    Args:
        slots: All operation_slots rows for the operation.
        assigned_slot_ids: Set of operation_slot.id values that have an
            active assignment (status='assigned') in the assignments table.
        unassigned_signup_count: Number of signup_intents for the operation
            where the participant has no active assignment.
        attendance_marked_count: Active assignments that already have an
            attendance record.
        scout_count: Participants checked in as 'scout' for this operation.
        support_count: Participants checked in as 'support' for this operation.
        reserve_count: Participants currently on the reserve/bench list.

    Returns:
        Dict with all readiness_snapshots columns except id, guild_workspace_id,
        guild_operation_id, and created_at (added by the use case).
    """
    total = len(slots)
    assigned = sum(1 for s in slots if s["id"] in assigned_slot_ids)
    open_count = total - assigned

    open_slots = [s for s in slots if s["id"] not in assigned_slot_ids]
    # Dict with counts per role/build, sorted keys → stable JSON.
    missing_roles  = _gap_counts(open_slots, "role")
    missing_builds = _gap_counts(open_slots, "build_name")

    return {
        "total_slots": total,
        "assigned_slots": assigned,
        "open_slots": open_count,
        "unassigned_signup_count": unassigned_signup_count,
        "missing_roles_json": json.dumps(missing_roles),
        "missing_builds_json": json.dumps(missing_builds),
        "attendance_marked_count": attendance_marked_count,
        "attendance_unmarked_count": max(0, assigned - attendance_marked_count),
        "scout_count": scout_count,
        "support_count": support_count,
        "reserve_count": reserve_count,
        "readiness_state": calculate_readiness_state(total, open_count),
    }
