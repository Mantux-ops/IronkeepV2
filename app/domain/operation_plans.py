"""
OperationPlan domain rules.

An operation plan links a GuildOperation to an AlbionComposition and
governs signup state.
"""

from __future__ import annotations

from app.errors import ValidationError

VALID_SIGNUP_STATUSES = frozenset({"open", "closed"})
VALID_WILLINGNESS = frozenset({"specific", "flexible", "fill"})
VALID_AVAILABILITY = frozenset({"confirmed", "tentative", "absent"})


def validate_signup_status(status: str) -> None:
    if status not in VALID_SIGNUP_STATUSES:
        raise ValidationError(
            f"Invalid signup_status '{status}'. Must be one of: {sorted(VALID_SIGNUP_STATUSES)}"
        )


def validate_willingness(willingness: str) -> None:
    if willingness not in VALID_WILLINGNESS:
        raise ValidationError(
            f"Invalid willingness '{willingness}'. Must be one of: {sorted(VALID_WILLINGNESS)}"
        )


def validate_availability(availability: str) -> None:
    if availability not in VALID_AVAILABILITY:
        raise ValidationError(
            f"Invalid availability '{availability}'. Must be one of: {sorted(VALID_AVAILABILITY)}"
        )


def validate_preferred_role(role: str) -> None:
    role = role.strip()
    if not role:
        raise ValidationError("preferred_role must not be empty.")
