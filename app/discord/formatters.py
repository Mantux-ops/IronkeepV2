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


#: Discord truncates a select option label or description beyond 100 characters.
_SELECT_TEXT_LIMIT = 100

#: Discord rejects a string select carrying more than 25 options.  A composition
#: with more distinct loadouts than this is beyond what one menu can express, so
#: the surplus is dropped rather than shown wrong.
SELECT_MAX_OPTIONS = 25


def _role_select_row(operation_id: str, role_choices: list[dict]) -> dict | None:
    """Build the action row holding the roster role picker, or None.

    Returns None for an empty roster so a message never carries a select with no
    options, which Discord rejects outright.

    The label leads with role and weapon because that is what a player recognises
    when scanning; the build name goes in the description, where Discord shows it
    as secondary text. Deliberately absent: how many of each role are still open.
    This message is only rewritten when an officer re-posts, so a count would be
    wrong within minutes of the first assignment.
    """
    options = [
        {
            "label": (
                f"{choice['role']} · {choice['weapon_name']}"
                if choice.get("weapon_name")
                else choice["role"]
            )[:_SELECT_TEXT_LIMIT],
            "value": choice["key"],
            **(
                {"description": choice["build_name"][:_SELECT_TEXT_LIMIT]}
                if choice.get("build_name")
                else {}
            ),
        }
        for choice in role_choices[:SELECT_MAX_OPTIONS]
    ]
    if not options:
        return None
    return {
        "type": 1,
        "components": [{
            "type":        3,   # 3 = StringSelect
            "custom_id":   f"signup:{operation_id}",
            "placeholder": "Sign up for a role",
            "min_values":  1,
            "max_values":  1,
            "options":     options,
        }],
    }


def _build_components(
    operation_id: str,
    signup_url: str | None,
    role_choices: list[dict] | None = None,
) -> list[dict]:
    """
    Build the action rows for scout/support check-in buttons, an optional signup
    link button, and — when a roster exists — the role picker.

    Discord component types:
      1 = ActionRow, 2 = Button, 3 = StringSelect
    Discord button styles:
      1 = PRIMARY (blurple) — requires custom_id
      5 = LINK (grey)       — requires url, must NOT have custom_id

    A select must occupy an action row of its own, and it is placed first because
    picking a role is the action most members came for.
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
    rows: list[dict] = []
    select_row = _role_select_row(operation_id, role_choices or [])
    if select_row:
        rows.append(select_row)
    rows.append({"type": 1, "components": buttons})
    return rows


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

def format_role_mentions(role_ids: list[str] | None) -> str:
    """Render Discord role snowflakes as a mention string.

    Returns "" for an empty list so callers can use it as a falsy value.
    """
    return " ".join(f"<@&{role_id}>" for role_id in (role_ids or []) if role_id)


def build_allowed_mentions(role_ids: list[str] | None) -> dict:
    """Restrict a message's pings to exactly these roles.

    ``parse: []`` suppresses @everyone, @here and user mentions that happen to
    appear in embed text.  Without an explicit allowed_mentions object Discord
    resolves every mention it finds, so this is what keeps a ping deliberate
    rather than a side effect of message content.
    """
    return {"parse": [], "roles": [rid for rid in (role_ids or []) if rid]}


def format_operation_announcement(
    operation: dict,
    readiness: dict | None = None,
    signup_url: str | None = None,
    ping_role_ids: list[str] | None = None,
    role_choices: list[dict] | None = None,
) -> dict:
    """
    Build a Discord message payload announcing a new or updated operation.

    operation requires: id, title, operation_type, status, scheduled_start_at
    readiness (optional): total_slots, assigned_slots, open_slots
    signup_url (optional): when provided, adds an "Open Signup Page" link button.
                           If None, only check-in buttons are included.
    ping_role_ids (optional): Discord role snowflakes to mention.  Mentions must
                           sit in the message content — text inside an embed is
                           rendered but never pings.
    role_choices (optional): roster role options from
                           roster_choices.build_role_choices().  When empty the
                           announcement carries no role picker, which is the
                           correct state for an operation with no roster yet.
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

    payload: dict = {
        "embeds":     [embed],
        "components": _build_components(
            operation.get("id", ""), signup_url, role_choices
        ),
    }

    # allowed_mentions is always set, even with no roles: it is the only thing
    # stopping an unexpected @everyone in a title from pinging the server.
    payload["allowed_mentions"] = build_allowed_mentions(ping_role_ids)
    mentions = format_role_mentions(ping_role_ids)
    if mentions:
        payload["content"] = mentions
    return payload


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


# ---------------------------------------------------------------------------
# 6. Role choice — thread notice and build DM
# ---------------------------------------------------------------------------

#: Suppresses every mention type. The thread notice names the member who picked
#: a role, and it addresses someone who is standing right there having just
#: pressed the picker — pinging them would be noise, and pinging anyone else
#: (a role name that happens to match, a stray @everyone) would be worse.
_NO_MENTIONS = {"parse": [], "users": [], "roles": []}


def _role_label(choice: dict) -> str:
    """Role with its weapon, as a player recognises it."""
    role   = (choice.get("role") or "").strip() or "role"
    weapon = (choice.get("weapon_name") or "").strip()
    return f"{role} · {weapon}" if weapon else role


def format_role_choice_notice(
    display_name: str,
    choice: dict,
    discord_user_id: str | None = None,
) -> dict:
    """
    Announce in the operation thread that a member signed up for a role.

    Plain content, no embed: a thread accumulates one of these per member and
    reads as a running list, which a stack of embeds would bury.

    The member is rendered as a Discord mention when their snowflake is known,
    because a mention resolves to their current server nickname instead of
    whatever name Ironkeep happens to store. It never pings — see _NO_MENTIONS.
    """
    who = f"<@{discord_user_id}>" if discord_user_id else f"**{display_name}**"
    return {
        "content":          f"{who} signed up as **{_role_label(choice)}**.",
        "allowed_mentions": _NO_MENTIONS,
    }


#: Equipment fields in the order a player kits up, with the labels they know.
_GEAR_FIELDS: tuple[tuple[str, str], ...] = (
    ("weapon_name",  "Weapon"),
    ("offhand_name", "Off-hand"),
    ("head_name",    "Head"),
    ("armor_name",   "Armor"),
    ("shoes_name",   "Shoes"),
    ("cape_name",    "Cape"),
    ("food_name",    "Food"),
    ("potion_name",  "Potion"),
)


def format_build_dm(
    operation: dict,
    slot: dict,
    spells: list[dict] | None = None,
) -> dict:
    """
    Build the direct message handing a player the build for the role they picked.

    operation requires: title, scheduled_start_at
    slot requires: role, build_name; equipment fields are optional and empty
                   ones are omitted rather than shown as a dash — a missing cape
                   in the doctrine is not information worth a line.
    spells (optional): stored {field_key, spell_name} rows for the slot's pinned
                   build version. Absent for legacy builds, which never had a
                   version to record spells against.

    Carries no components: a DM arrives outside any guild, so a check-in button
    there would have no operation context to act in.
    """
    from app.albion.spell_catalog import (  # noqa: PLC0415 — static catalog, no DB
        SPELL_FIELD_LABELS,
        SPELL_FIELD_ORDER,
    )

    fields: list[dict] = [
        {"name": "Role", "value": (slot.get("role") or "—"), "inline": True},
    ]
    if slot.get("doctrine_role"):
        fields.append(
            {"name": "Assignment", "value": slot["doctrine_role"], "inline": True}
        )
    fields += [
        {"name": label, "value": slot[key], "inline": True}
        for key, label in _GEAR_FIELDS
        if slot.get(key)
    ]

    by_key = {
        row["field_key"]: row["spell_name"]
        for row in (spells or [])
        if row.get("spell_name")
    }
    spell_lines = [
        f"**{SPELL_FIELD_LABELS.get(key, key)}** — {by_key[key]}"
        for key in SPELL_FIELD_ORDER
        if key in by_key
    ]
    if spell_lines:
        fields.append({
            "name":   "Spells",
            "value":  "\n".join(spell_lines),
            "inline": False,
        })

    embed: dict = {
        "title":       slot.get("build_name") or "Your build",
        "description": (
            f"You signed up as **{_role_label(slot)}** for "
            f"**{operation['title']}** — {_format_scheduled_time(operation['scheduled_start_at'])}."
        ),
        "color":       STATUS_COLORS["planning"],
        "fields":      fields,
        "footer":      {"text": _FOOTER},
    }
    return {"embeds": [embed], "allowed_mentions": _NO_MENTIONS}
