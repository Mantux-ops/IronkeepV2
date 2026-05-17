"""User identity validation for auth providers."""

from __future__ import annotations

import re

from app.errors import ValidationError

DEV_AUTH_PROVIDER     = "dev"
DISCORD_AUTH_PROVIDER = "discord"

_PROVIDER_USER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")

_DISPLAY_NAME_MIN = 2
_DISPLAY_NAME_MAX = 80


def validate_display_name(display_name: str) -> None:
    name = display_name.strip()
    if not name:
        raise ValidationError("Display name must not be empty.")
    if len(name) < _DISPLAY_NAME_MIN:
        raise ValidationError(
            f"Display name must be at least {_DISPLAY_NAME_MIN} characters."
        )
    if len(name) > _DISPLAY_NAME_MAX:
        raise ValidationError(
            f"Display name must be at most {_DISPLAY_NAME_MAX} characters."
        )


def dev_provider_user_id(display_name: str) -> str:
    """Stable dev identity key derived from display name."""
    validate_display_name(display_name)
    slug = display_name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) < 3:
        slug = f"user-{slug}" if slug else "user"
    if not _PROVIDER_USER_ID_RE.match(slug):
        raise ValidationError("Display name cannot be converted to a valid dev user id.")
    return slug
