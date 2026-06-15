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
