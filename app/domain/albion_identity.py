"""
Albion Online identity domain validation.

Rules enforced here:
- albion_player_id: non-empty trimmed string, max 128 chars.
  The Albion API is the authority on validity; we only reject obviously bad values.
- character_name: non-empty trimmed string, max 128 chars.

UUID-format validation is deliberately NOT enforced — Albion IDs look like
GUIDs in current API responses, but the game's API specification does not
guarantee this, so we leave format verification to the API itself.
"""

from __future__ import annotations

from app.errors import ValidationError

ALBION_GAME = "albion"
_MAX_ID_LEN = 128
_MAX_NAME_LEN = 128


def validate_albion_player_id(player_id: str) -> str:
    """
    Validate and normalise an Albion player ID.

    Returns the trimmed ID.
    Raises ValidationError if invalid.
    """
    if not isinstance(player_id, str):
        raise ValidationError("Albion player ID must be a string.")
    pid = player_id.strip()
    if not pid:
        raise ValidationError("Albion player ID must not be empty.")
    if len(pid) > _MAX_ID_LEN:
        raise ValidationError(
            f"Albion player ID must be at most {_MAX_ID_LEN} characters."
        )
    return pid


def validate_albion_character_name(name: str) -> str:
    """
    Validate and normalise an Albion character name.

    Returns the trimmed name.
    Raises ValidationError if invalid.
    """
    if not isinstance(name, str):
        raise ValidationError("Albion character name must be a string.")
    n = name.strip()
    if not n:
        raise ValidationError("Albion character name must not be empty.")
    if len(n) > _MAX_NAME_LEN:
        raise ValidationError(
            f"Albion character name must be at most {_MAX_NAME_LEN} characters."
        )
    return n
