"""
Discord command adapter — Phase 1 (no Discord SDK, no API calls).

Each handler accepts a plain dict interaction payload and a DB connection,
calls existing use cases or repository reads, and returns a plain dict
interaction response payload.

Handler contract:
  payload = {
      "discord_guild_id": str,   # Discord server snowflake
      "discord_user_id":  str,   # Discord user snowflake
      "options": {               # command-specific options (see each handler)
          ...
      },
  }

  Returns:
      {"type": 4, "data": {"embeds": [...], "flags": 64}}   # success
      {"type": 4, "data": {"content": "❌ ...", "flags": 64}}  # error

Rules:
- No business logic here: resolve identity → call use case → format response.
- Domain exceptions (IronkeepError subclasses) become ephemeral error payloads.
- Unknown exceptions are NOT caught — they propagate to the bot's global handler.
- Readiness and roster handlers are read-only (no side-effecting use cases).
- Signup uses source='discord'.
- All responses are ephemeral (flags=64) in Phase 1.
"""

from __future__ import annotations

from app import repositories
from app.application import use_cases
from app.discord.formatters import (
    format_readiness_summary,
    format_roster,
    format_signup_confirmation,
)
from app.discord.identity import get_discord_identity_context
from app.errors import IronkeepError

# Valid role_type values for component check-in interactions.
_VALID_CHECKIN_ROLES = frozenset({"scout", "support"})

# Discord interaction type: CHANNEL_MESSAGE_WITH_SOURCE
_INTERACTION_TYPE = 4
_EPHEMERAL = 64


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _success_response(data: dict) -> dict:
    """Wrap a formatter output in a Discord interaction response payload."""
    return {
        "type": _INTERACTION_TYPE,
        "data": {**data, "flags": _EPHEMERAL},
    }


def _error_response(message: str) -> dict:
    """Build an ephemeral error interaction response."""
    return {
        "type": _INTERACTION_TYPE,
        "data": {
            "content": f"❌ {message}",
            "flags": _EPHEMERAL,
        },
    }


def _get_operation(db, operation_id: str, workspace_id: str) -> dict | None:
    """Fetch an operation and return None if not found in this workspace."""
    return repositories.get_guild_operation(db, operation_id, workspace_id)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_signup_command(payload: dict, db) -> dict:
    """
    Sign up the invoking Discord user for an operation.

    options:
      operation_id  str — UUID of the target operation
      role          str — preferred_role (e.g. "Tank", "DPS")
      build         str | None — preferred_build_name (optional)
      willingness   str — "specific" | "flexible" | "fill" (default "specific")
      availability  str — "confirmed" | "tentative" (default "confirmed")
    """
    guild_id = payload["discord_guild_id"]
    user_id  = payload["discord_user_id"]
    opts     = payload.get("options", {})

    try:
        ctx = get_discord_identity_context(db, guild_id, user_id)
        workspace = ctx["workspace"]
        user      = ctx["user"]

        operation_id = opts["operation_id"]
        operation = _get_operation(db, operation_id, workspace["id"])
        if not operation:
            return _error_response("Operation not found in this workspace.")

        signup = use_cases.submit_signup_intent(
            guild_workspace_id=workspace["id"],
            guild_operation_id=operation_id,
            display_name=user["display_name"],
            preferred_role=opts["role"],
            preferred_build_name=opts.get("build"),
            willingness=opts.get("willingness", "specific"),
            availability=opts.get("availability", "confirmed"),
            source="discord",
        )
        return _success_response(format_signup_confirmation(operation, signup))

    except IronkeepError as exc:
        return _error_response(str(exc))


def handle_readiness_command(payload: dict, db) -> dict:
    """
    Show the current readiness snapshot for an operation.

    Read-only — does NOT recalculate or emit events.

    options:
      operation_id  str — UUID of the target operation
    """
    guild_id = payload["discord_guild_id"]
    user_id  = payload["discord_user_id"]
    opts     = payload.get("options", {})

    try:
        ctx = get_discord_identity_context(db, guild_id, user_id)
        workspace = ctx["workspace"]

        operation_id = opts["operation_id"]
        operation = _get_operation(db, operation_id, workspace["id"])
        if not operation:
            return _error_response("Operation not found in this workspace.")

        readiness = repositories.get_latest_readiness_snapshot(
            db, operation_id, workspace["id"]
        )
        if not readiness:
            return _error_response(
                "No readiness snapshot available yet. "
                "A readiness calculation must be run from the web dashboard first."
            )

        return _success_response(format_readiness_summary(operation, readiness))

    except IronkeepError as exc:
        return _error_response(str(exc))


def handle_roster_command(payload: dict, db) -> dict:
    """
    Show the current roster for an operation, grouped by party.

    Read-only.

    options:
      operation_id  str — UUID of the target operation
    """
    guild_id = payload["discord_guild_id"]
    user_id  = payload["discord_user_id"]
    opts     = payload.get("options", {})

    try:
        ctx = get_discord_identity_context(db, guild_id, user_id)
        workspace = ctx["workspace"]

        operation_id = opts["operation_id"]
        operation = _get_operation(db, operation_id, workspace["id"])
        if not operation:
            return _error_response("Operation not found in this workspace.")

        slots = repositories.get_operation_slots(db, operation_id, workspace["id"])
        assigned_map = repositories.get_assigned_participants_for_operation(
            db, operation_id, workspace["id"]
        )
        assignments = [
            {"slot_id": slot_id, "display_name": info["display_name"]}
            for slot_id, info in assigned_map.items()
        ]

        return _success_response(format_roster(operation, slots, assignments))

    except IronkeepError as exc:
        return _error_response(str(exc))


def handle_checkin_command(payload: dict, db) -> dict:
    """
    Check the invoking Discord user in as scout or support for an operation.

    options:
      operation_id  str — UUID of the target operation
      role_type     str — "scout" | "support"
      notes         str | None — optional free-text notes
    """
    guild_id = payload["discord_guild_id"]
    user_id  = payload["discord_user_id"]
    opts     = payload.get("options", {})

    try:
        ctx = get_discord_identity_context(db, guild_id, user_id)
        workspace = ctx["workspace"]
        user      = ctx["user"]

        operation_id = opts["operation_id"]
        operation = _get_operation(db, operation_id, workspace["id"])
        if not operation:
            return _error_response("Operation not found in this workspace.")

        role_type = opts["role_type"]
        notes     = opts.get("notes")

        use_cases.record_scout_attendance(
            guild_workspace_id=workspace["id"],
            guild_operation_id=operation_id,
            display_name=user["display_name"],
            role_type=role_type,
            notes=notes,
        )

        return _success_response({
            "content": (
                f"✅ Checked in as **{role_type}** for **{operation['title']}**."
            ),
        })

    except IronkeepError as exc:
        return _error_response(str(exc))


def handle_component_interaction(payload: dict, db) -> dict:
    """
    Route a Discord message-component interaction (button click) to the
    appropriate application use case.

    payload shape:
      {
          "discord_guild_id": str,
          "discord_user_id":  str,
          "custom_id":        str,   # e.g. "checkin:scout:{operation_id}"
      }

    Supported custom_id patterns:
      checkin:scout:{operation_id}
      checkin:support:{operation_id}

    Returns an ephemeral type=4 interaction response.
    Unknown exceptions propagate to the bot's global handler.
    """
    guild_id  = payload.get("discord_guild_id", "")
    user_id   = payload.get("discord_user_id", "")
    custom_id = payload.get("custom_id", "")

    # Parse and validate custom_id
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != "checkin":
        return _error_response(
            f"Unknown interaction: '{custom_id}'. "
            "This button is not supported by this bot version."
        )

    _, role_type, operation_id = parts

    if role_type not in _VALID_CHECKIN_ROLES:
        return _error_response(
            f"Invalid check-in role '{role_type}'. "
            "Expected 'scout' or 'support'."
        )

    try:
        ctx       = get_discord_identity_context(db, guild_id, user_id)
        workspace = ctx["workspace"]
        user      = ctx["user"]

        operation = _get_operation(db, operation_id, workspace["id"])
        if not operation:
            return _error_response(
                "Operation not found in this workspace. "
                "It may have been archived or the button is outdated."
            )

        use_cases.record_scout_attendance(
            guild_workspace_id=workspace["id"],
            guild_operation_id=operation_id,
            display_name=user["display_name"],
            role_type=role_type,
            notes=None,
        )

        return {
            "type": _INTERACTION_TYPE,
            "data": {
                "content": (
                    f"✅ Checked in as **{role_type}** for **{operation['title']}**."
                ),
                "flags": _EPHEMERAL,
            },
        }

    except IronkeepError as exc:
        return _error_response(str(exc))
