"""
GuildWorkspace domain rules.

A GuildWorkspace is the tenant root.  Every other entity must carry its
guild_workspace_id.  These functions enforce naming constraints before any
data reaches the database.
"""

from __future__ import annotations

import re
from typing import Callable

from app.errors import ValidationError

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$")
_NAME_MIN = 2
_NAME_MAX = 80

# Discord snowflakes are 64-bit unsigned ints represented as decimal strings.
# Real-world IDs are currently 17–19 digits; we allow 15–20 to be permissive
# without accepting obvious garbage.
_SNOWFLAKE_RE = re.compile(r"^\d{15,20}$")


def validate_workspace_name(name: str) -> None:
    name = name.strip()
    if not name:
        raise ValidationError("Workspace name must not be empty.")
    if len(name) < _NAME_MIN:
        raise ValidationError(f"Workspace name must be at least {_NAME_MIN} characters.")
    if len(name) > _NAME_MAX:
        raise ValidationError(f"Workspace name must be at most {_NAME_MAX} characters.")


def validate_workspace_slug(slug: str) -> None:
    if not slug:
        raise ValidationError("Workspace slug must not be empty.")
    if not _SLUG_RE.match(slug):
        raise ValidationError(
            "Workspace slug must be 3–64 lowercase alphanumeric characters "
            "or hyphens, must start and end with a letter or digit."
        )


def validate_discord_snowflake(value: str | None, field_name: str = "value") -> str | None:
    """
    Normalise and validate a Discord snowflake string.

    - None or empty string → returns None (field is being cleared)
    - Non-empty → must be digits only, 15–20 characters
    - Returns the stripped value on success, raises ValidationError on failure
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _SNOWFLAKE_RE.match(value):
        raise ValidationError(
            f"'{field_name}' must be a Discord snowflake: digits only, 15–20 characters "
            f"(e.g. 123456789012345678). Got: '{value[:30]}'"
        )
    return value


def derive_workspace_slug_from_guild_name(guild_name: str) -> str:
    """
    Derive a base workspace slug from a Discord guild name.

    Algorithm:
      1. Lowercase the name.
      2. Replace any character that is not a–z or 0–9 with a single hyphen.
      3. Collapse consecutive hyphens into one.
      4. Strip leading/trailing hyphens.
      5. Truncate to 48 characters (leaves room for a -NNN uniqueness suffix).
      6. Strip any trailing hyphen left by truncation.
      7. Fall back to 'discord-guild' when the result is fewer than 3 characters.

    Returns a valid base slug string.  Uniqueness is NOT guaranteed — call
    make_unique_workspace_slug to resolve collisions using a DB lookup.
    """
    slug = guild_name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = slug[:48].rstrip("-")
    if len(slug) < 3:
        slug = "discord-guild"
    return slug


def make_unique_workspace_slug(
    base_slug: str,
    slug_taken: Callable[[str], bool],
) -> str:
    """
    Return base_slug if available, otherwise base_slug-2, base_slug-3, …

    slug_taken(slug) must return True if the slug is already in use.

    Raises ValidationError if no unique slug can be found within 999 attempts
    (astronomically unlikely in practice).
    """
    if not slug_taken(base_slug):
        return base_slug
    for i in range(2, 1000):
        # Keep total length well within the 64-char slug limit.
        candidate = f"{base_slug[:44]}-{i}"
        if not slug_taken(candidate):
            return candidate
    raise ValidationError(
        f"Could not derive a unique slug from '{base_slug}'. "
        "Please create the workspace manually with a custom slug."
    )


def validate_discord_config(
    discord_guild_id: str | None,
    announcement_channel_id: str | None,
    officer_channel_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """
    Validate and normalise all three Discord config fields.

    Returns a tuple of (discord_guild_id, announcement_channel_id,
    officer_channel_id) with empty strings converted to None.
    Raises ValidationError on the first invalid snowflake.
    """
    return (
        validate_discord_snowflake(discord_guild_id, "Discord Server ID"),
        validate_discord_snowflake(announcement_channel_id, "Announcement Channel ID"),
        validate_discord_snowflake(officer_channel_id, "Officer Channel ID"),
    )


# ---------------------------------------------------------------------------
# Announcement routing
# ---------------------------------------------------------------------------

#: Fallback set of operation types treated as a CTA when a workspace has no
#: explicit configuration.  Mid-scale ZvZ is the CTA in every guild that has
#: asked for this split; everything else is a smaller, opt-in event.
DEFAULT_CTA_OPERATION_TYPES: tuple[str, ...] = ("zvz",)


def validate_announcement_routing(
    cta_channel_id: str | None,
    event_channel_id: str | None,
    cta_operation_types: list[str] | None,
    valid_operation_types: frozenset[str] | set[str],
) -> tuple[str | None, str | None, str]:
    """Validate the two routing channels and the CTA type list.

    ``valid_operation_types`` is injected rather than imported: domain modules
    in this codebase do not depend on each other, and the operation type
    vocabulary belongs to the guild_operations domain.

    Returns (cta_channel_id, event_channel_id, cta_operation_types_json) with
    empty strings normalised to None.  An empty selection is allowed and means
    "nothing is a CTA" — every operation then routes to the event channel.
    """
    import json  # noqa: PLC0415

    selected = [str(t).strip().lower() for t in (cta_operation_types or []) if str(t).strip()]
    for op_type in selected:
        if op_type not in valid_operation_types:
            raise ValidationError(
                f"'{op_type}' is not a valid operation type for CTA routing."
            )
    # Deduplicate while keeping a stable stored order so the JSON column does
    # not churn between saves that select the same set.
    ordered = sorted(set(selected))
    return (
        validate_discord_snowflake(cta_channel_id, "CTA Channel"),
        validate_discord_snowflake(event_channel_id, "Event Channel"),
        json.dumps(ordered),
    )


def parse_cta_operation_types(raw: str | None) -> set[str]:
    """Read the stored JSON array of CTA operation types.

    Corrupt or non-list JSON falls back to the default rather than raising:
    announcement routing must never be the reason an operation page fails to
    render, and the worst case is a post landing in the CTA channel.
    """
    import json  # noqa: PLC0415

    if not raw:
        return set(DEFAULT_CTA_OPERATION_TYPES)
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return set(DEFAULT_CTA_OPERATION_TYPES)
    if not isinstance(parsed, list):
        return set(DEFAULT_CTA_OPERATION_TYPES)
    return {str(t).strip().lower() for t in parsed if str(t).strip()}


def is_cta_operation_type(workspace: dict, operation_type: str | None) -> bool:
    """Whether an operation of this type is announced as a CTA."""
    cta_types = parse_cta_operation_types(
        workspace.get("discord_cta_operation_types_json")
    )
    return (operation_type or "").strip().lower() in cta_types


def parse_role_ids(raw: str | None) -> list[str]:
    """Read a stored JSON array of Discord role snowflakes, order preserved.

    Corrupt JSON yields an empty list rather than raising: a broken ping list
    must degrade to "ping nobody", never to a failed announcement.
    """
    import json  # noqa: PLC0415

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for value in parsed:
        role_id = str(value).strip()
        if role_id and role_id not in seen:
            seen.add(role_id)
            ordered.append(role_id)
    return ordered


def validate_ping_role_config(
    cta_ping_role_id: str | None,
    content_role_ids: list[str] | None,
) -> tuple[str | None, str]:
    """Validate the workspace-level ping configuration.

    Returns (cta_ping_role_id, content_role_ids_json) with empty strings
    normalised to None.  Content roles keep the order they were submitted in so
    the per-event picker matches the order shown in settings.
    """
    import json  # noqa: PLC0415

    ordered: list[str] = []
    for value in content_role_ids or []:
        role_id = validate_discord_snowflake(value, "Content role")
        if role_id and role_id not in ordered:
            ordered.append(role_id)
    return (
        validate_discord_snowflake(cta_ping_role_id, "CTA ping role"),
        json.dumps(ordered),
    )


def resolve_ping_role_ids(workspace: dict, operation: dict) -> list[str]:
    """Which Discord roles an announcement for this operation should ping.

    A CTA always pings the single configured CTA role — that audience is the
    whole point of a call to arms and is not a per-operation choice.  Every other
    type pings the roles selected on the operation, filtered to the workspace's
    current content-role list so a role removed from settings stops being pinged
    without having to rewrite past operations.
    """
    if is_cta_operation_type(workspace, operation.get("operation_type")):
        role_id = workspace.get("discord_cta_ping_role_id")
        return [role_id] if role_id else []

    allowed = set(parse_role_ids(workspace.get("discord_content_role_ids_json")))
    return [
        role_id
        for role_id in parse_role_ids(operation.get("discord_ping_role_ids_json"))
        if role_id in allowed
    ]


def resolve_announcement_channel(
    workspace: dict,
    operation_type: str | None,
) -> str | None:
    """Pick the channel an operation of this type is announced in.

    CTA types resolve to the CTA channel, everything else to the event channel.
    Either falls back to the legacy single announcement channel, so a workspace
    that has not configured routing keeps posting exactly where it did before.

    Returns None when nothing is configured — callers must treat that as
    "Discord is not set up" rather than posting to a guessed channel.
    """
    if is_cta_operation_type(workspace, operation_type):
        primary = workspace.get("discord_cta_channel_id")
    else:
        primary = workspace.get("discord_event_channel_id")
    return primary or workspace.get("discord_announcement_channel_id") or None
