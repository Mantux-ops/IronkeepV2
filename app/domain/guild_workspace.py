"""
GuildWorkspace domain rules.

A GuildWorkspace is the tenant root.  Every other entity must carry its
guild_workspace_id.  These functions enforce naming constraints before any
data reaches the database.
"""

from __future__ import annotations

import re

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
