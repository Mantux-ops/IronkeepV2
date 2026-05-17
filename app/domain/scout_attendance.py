"""
Scout / support attendance domain rules.

Scout and support attendance records are NOT linked to assignments.  They
represent a separate participation path for participants who were operationally
present but not assigned to a composition slot.

Re-checking-in is an upsert: updates the existing row and emits a new event
with previous_role_type (always) and previous_notes (only when notes changed).
"""

from __future__ import annotations

from app.errors import ValidationError

VALID_ROLE_TYPES = frozenset({"scout", "support"})

# Ordered for display in forms and tables.
ROLE_TYPE_ORDER: list[str] = ["scout", "support"]


def validate_role_type(role_type: str) -> None:
    if role_type not in VALID_ROLE_TYPES:
        raise ValidationError(
            f"Invalid scout attendance role_type '{role_type}'. "
            f"Must be one of: {ROLE_TYPE_ORDER}"
        )
