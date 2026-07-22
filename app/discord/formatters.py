"""
Discord message formatters — Phase 1 (no Discord SDK, no API calls).

Pure functions: plain dicts in → plain dict payloads out.

Rules:
- No database access.
- No Discord SDK imports.
- No imports from app.routes or app.application.
- Inputs are plain dicts supplied by callers (repositories, use cases, or tests).
- Outputs are JSON-serialisable dicts matching Discord's REST API message shape.

Discord payload shapes used here:

  Message payload:
    {"embeds": [...], "flags": <int, optional>}

  Embed:
    {
      "title": str,
      "description": str | absent,
      "color": int,                   # 24-bit RGB integer
      "timestamp": str | absent,      # ISO 8601
      "fields": [{"name", "value", "inline"}, ...],
      "footer": {"text": str},
    }

  flags=64 marks a response as ephemeral (interaction responses only).

Status colours (matching domain VALID_STATUSES):
  draft      0x95A5A6  grey
  planning   0x3498DB  blue
  locked     0xE67E22  orange
  completed  0x2ECC71  green
  archived   0x7F8C8D  dark grey
"""

from __future__ import annotations

import json
from datetime import timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATUS_COLORS: dict[str, int] = {
    "draft":     0x95A5A6,
    "planning":  0x3498DB,
    "locked":    0xE67E22,
    "completed": 0x2ECC71,
    "archived":  0x7F8C8D,
}

_DEFAULT_COLOR = 0x95A5A6   # fallback for unknown statuses
_FOOTER = "IronkeepV2"
_EPHEMERAL_FLAG = 64         # Discord interaction ephemeral bit


def _color(status: str) -> int:
    return STATUS_COLORS.get(status, _DEFAULT_COLOR)


def _build_components(operation_id: str, signup_url: str | None) -> list[dict]:
    """
    Build a Discord action-row component block for scout/support check-in buttons
    and an optional signup link button.

    Discord component types:
      1 = ActionRow, 2 = Button
    Discord button styles:
      1 = PRIMARY (blurple) — requires custom_id
      5 = LINK (grey)       — requires url, must NOT have custom_id
    """
    buttons: list[dict] = [
        {
            "type":      2,
            "style":     1,
            "label":     "Scout Check-in",
            "custom_id": f"checkin:scout:{operation_id}",
        },
        {
            "type":      2,
            "style":     1,
            "label":     "Support Check-in",
            "custom_id": f"checkin:support:{operation_id}",
        },
    ]
    if signup_url:
        buttons.append({
            "type":  2,
            "style": 5,
            "label": "Open Signup Page",
            "url":   signup_url,
        })
    return [{"type": 1, "components": buttons}]


def _format_scheduled_time(scheduled_start_at: str) -> str:
    """
    Return a human-readable time string from an ISO 8601 timestamp.

    Keeps formatting simple and dependency-free.  If the value is not a
    recognised ISO string the raw value is returned unchanged so callers
    are never broken by unexpected input.
    """
    try:
        from datetime import datetime  # noqa: PLC0415 (deferred to keep top clean)
        dt = datetime.fromisoformat(scheduled_start_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return str(scheduled_start_at)


# ---------------------------------------------------------------------------
# 1. Operation announcement
# ---------------------------------------------------------------------------

def format_operation_announcement(
    operation: dict,
    readiness: dict | None = None,
    signup_url: str | None = None,
) -> dict:
    """
    Build a Discord message payload announcing a new or updated operation.

    operation requires: id, title, operation_type, status, scheduled_start_at
    readiness (optional): total_slots, assigned_slots, open_slots
    signup_url (optional): when provided, adds an "Open Signup Page" link button.
                           If None, only check-in buttons are included.
    """
    fields: list[dict] = [
        {"name": "Type",   "value": operation["operation_type"], "inline": True},
        {"name": "Status", "value": operation["status"],          "inline": True},
        {"name": "When",   "value": _format_scheduled_time(operation["scheduled_start_at"]),
         "inline": False},
    ]

    if readiness is not None:
        total    = readiness.get("total_slots", 0)
        assigned = readiness.get("assigned_slots", 0)
        pct      = int(assigned / total * 100) if total else 0
        fields.append({
            "name":   "Roster",
            "value":  f"{assigned} / {total} filled ({pct}%)",
            "inline": True,
        })

    if signup_url:
        description = f"An operation has been posted.\n**Sign up:** {signup_url}"
    else:
        description = "An operation has been posted. Sign up at the web dashboard."

    embed: dict = {
        "title":       operation["title"],
        "description": description,
        "color":       _color(operation["status"]),
        "timestamp":   operation.get("scheduled_start_at", ""),
        "fields":      fields,
        "footer":      {"text": _FOOTER},
    }

    return {
        "embeds":     [embed],
        "components": _build_components(operation.get("id", ""), signup_url),
    }


# ---------------------------------------------------------------------------
# 2. Readiness summary
# ---------------------------------------------------------------------------

def format_readiness_summary(
    operation: dict,
    readiness: dict,
) -> dict:
    """
    Build a Discord message payload summarising roster readiness.

    operation requires: title, status, scheduled_start_at
    readiness requires: total_slots, assigned_slots, open_slots,
                        readiness_state, missing_roles_json,
                        missing_builds_json, attendance_marked_count,
                        attendance_unmarked_count, scout_count, support_count
    """
    total    = readiness.get("total_slots", 0)
    assigned = readiness.get("assigned_slots", 0)
    pct      = int(assigned / total * 100) if total else 0
    state    = readiness.get("readiness_state", "not_ready")

    fields: list[dict] = [
        {"name": "Roster", "value": f"{assigned} / {total} filled ({pct}%)", "inline": True},
        {"name": "State",  "value": state,                                    "inline": True},
    ]

    # Role gaps — omit entirely when all slots are assigned
    missing_roles: dict = {}
    raw_roles = readiness.get("missing_roles_json", "{}")
    try:
        missing_roles = json.loads(raw_roles) if raw_roles else {}
    except (ValueError, TypeError):
        missing_roles = {}

    if missing_roles:
        gap_lines = "\n".join(f"{role}: {count}" for role, count in sorted(missing_roles.items()))
        fields.append({"name": "Role Gaps", "value": gap_lines, "inline": False})

    # Build gaps — omit entirely when all slots are assigned
    missing_builds: dict = {}
    raw_builds = readiness.get("missing_builds_json", "{}")
    try:
        missing_builds = json.loads(raw_builds) if raw_builds else {}
    except (ValueError, TypeError):
        missing_builds = {}

    if missing_builds:
        build_lines = "\n".join(
            f"{build or '(no build)'}: {count}"
            for build, count in sorted(missing_builds.items())
        )
        fields.append({"name": "Build Gaps", "value": build_lines, "inline": False})

    # Attendance
    marked   = readiness.get("attendance_marked_count", 0)
    unmarked = readiness.get("attendance_unmarked_count", 0)
    fields.append({
        "name":   "Attendance",
        "value":  f"{marked} marked / {unmarked} pending",
        "inline": True,
    })

    # Scout / support
    scouts  = readiness.get("scout_count", 0)
    support = readiness.get("support_count", 0)
    fields.append({
        "name":   "Scout / Support",
        "value":  f"Scouts: {scouts}  Support: {support}",
        "inline": True,
    })

    embed: dict = {
        "title":     f"Readiness: {operation['title']}",
        "color":     _color(operation["status"]),
        "timestamp": operation.get("scheduled_start_at", ""),
        "fields":    fields,
        "footer":    {"text": _FOOTER},
    }

    return {"embeds": [embed]}


# ---------------------------------------------------------------------------
# 3. Roster
# ---------------------------------------------------------------------------

def format_roster(
    operation: dict,
    slots: list[dict],
    assignments: list[dict],
    signup_url: str | None = None,
) -> dict:
    """
    Build a Discord message payload showing the current roster grouped by party.

    operation requires: id, title, status
    slots: list of dicts with id, party_number, slot_index, role, build_name
    assignments: list of dicts with slot_id, display_name, and optional
      discord_user_id (when present, the participant is rendered as an @mention
      so Discord shows their live server nickname and pings them).
    signup_url (optional): when provided, adds an "Open Signup Page" link button.

    Slot line format:
      {slot_index}. {role} — {build_name or '—'} — <@discord_id> or **{name}**  (assigned)
      {slot_index}. {role} — {build_name or '—'} — *(open)*                      (unassigned)
    """
    # Build slot_id → rendered participant string. Prefer an @mention (Discord
    # renders the member's current server nickname) and fall back to bold text.
    assigned: dict[str, str] = {}
    for a in assignments:
        did = a.get("discord_user_id")
        assigned[a["slot_id"]] = f"<@{did}>" if did else f"**{a['display_name']}**"

    # Group slots by party, preserving slot_index order
    parties: dict[int, list[dict]] = {}
    for slot in sorted(slots, key=lambda s: (s["party_number"], s["slot_index"])):
        party = slot["party_number"]
        parties.setdefault(party, []).append(slot)

    fields: list[dict] = []
    for party_num in sorted(parties):
        party_slots = parties[party_num]
        lines: list[str] = []
        for slot in party_slots:
            build  = slot.get("build_name") or "—"
            role   = slot.get("role", "?")
            idx    = slot.get("slot_index", "?")
            participant = assigned.get(slot["id"]) or "*(open)*"
            lines.append(f"{idx}. {role} — {build} — {participant}")
        fields.append({
            "name":   f"Party {party_num}",
            "value":  "\n".join(lines) or "*(empty)*",
            "inline": False,
        })

    total    = len(slots)
    fill_cnt = len(assigned)
    footer_text = f"{_FOOTER} · {fill_cnt} / {total} assigned"

    embed: dict = {
        "title":  f"Roster: {operation['title']}",
        "color":  _color(operation["status"]),
        "fields": fields,
        "footer": {"text": footer_text},
    }

    return {
        "embeds":     [embed],
        "components": _build_components(operation.get("id", ""), signup_url),
    }


# ---------------------------------------------------------------------------
# 4. Operation reminder
# ---------------------------------------------------------------------------

_REMINDER_COLOR = 0xF39C12   # amber — informational, not status-derived

_WINDOW_LABELS: dict[str, str] = {
    "T-2h":  "2 hours",
    "T-30m": "30 minutes",
}


def format_operation_reminder(
    operation: dict,
    window: str,
    readiness: dict | None = None,
) -> dict:
    """
    Build a Discord message payload for a pre-operation reminder.

    This formatter is informational only — it never triggers lifecycle changes,
    status mutations, or signup/assignment actions.

    operation requires: title, operation_type, status, scheduled_start_at
    window: 'T-2h' | 'T-30m'  (any unrecognised value is passed through as-is)
    readiness (optional): total_slots, assigned_slots — never recomputed here

    The 'When' field always shows explicit UTC so recipients are never confused
    by timezone-naive timestamps.
    """
    label = _WINDOW_LABELS.get(window, window)

    fields: list[dict] = [
        {"name": "Type",  "value": operation.get("operation_type", "—"), "inline": True},
        {"name": "Status", "value": operation.get("status", "—"),        "inline": True},
        {
            "name":   "When",
            "value":  _format_scheduled_time(operation["scheduled_start_at"]),
            "inline": False,
        },
    ]

    if readiness is not None:
        total    = readiness.get("total_slots", 0)
        assigned = readiness.get("assigned_slots", 0)
        pct      = int(assigned / total * 100) if total else 0
        fields.append({
            "name":   "Roster",
            "value":  f"{assigned} / {total} filled ({pct}%)",
            "inline": True,
        })

    embed: dict = {
        "title":       f"Reminder: {operation['title']}",
        "description": f"Operation starts in **{label}**. Check the web dashboard for the latest roster.",
        "color":       _REMINDER_COLOR,
        "timestamp":   operation.get("scheduled_start_at", ""),
        "fields":      fields,
        "footer":      {"text": _FOOTER},
    }

    return {"embeds": [embed]}


# ---------------------------------------------------------------------------
# 5. Signup confirmation
# ---------------------------------------------------------------------------

def format_signup_confirmation(
    operation: dict,
    signup: dict,
) -> dict:
    """
    Build a Discord message payload confirming a signup.

    Suitable as an ephemeral interaction response (flags=64).

    operation requires: title, scheduled_start_at
    signup requires: preferred_role, preferred_build_name (nullable),
                     willingness, availability
    """
    fields: list[dict] = [
        {"name": "Role",         "value": signup["preferred_role"],  "inline": True},
    ]

    build = signup.get("preferred_build_name")
    if build:
        fields.append({"name": "Build", "value": build, "inline": True})

    fields += [
        {"name": "Availability", "value": signup.get("availability", ""), "inline": True},
        {"name": "Willingness",  "value": signup.get("willingness", ""),  "inline": True},
        {
            "name":   "When",
            "value":  _format_scheduled_time(operation["scheduled_start_at"]),
            "inline": False,
        },
    ]

    embed: dict = {
        "title":       "✅ Signup Confirmed",
        "description": f"You're signed up for **{operation['title']}**.",
        "color":       STATUS_COLORS["completed"],   # green confirmation
        "fields":      fields,
        "footer":      {"text": _FOOTER},
    }

    return {
        "embeds": [embed],
        "flags":  _EPHEMERAL_FLAG,
    }
