"""
GuildOperation domain rules.

An operation is a structured, time-bound event for which a guild commits
resources.  These functions validate operation data before persistence.

Status lifecycle:
  draft     — just created; not yet open for roster assembly
  planning  — open for signups and comp work (publish_operation)
  locked    — roster frozen; no more signups expected (lock_operation)
  completed — operation ran; attendance can be marked (complete_operation)
  archived  — historical record; no further changes (archive_operation)

Valid transitions:
  draft    → planning
  planning → locked
  planning → completed   (small ops fast-path — skip lock step)
  locked   → completed
  completed → archived
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.errors import ConflictError, ValidationError

VALID_OPERATION_TYPES = frozenset({"zvz", "ganking", "roads", "hellgate", "avalon", "other"})
VALID_STATUSES = frozenset({"draft", "planning", "locked", "completed", "archived"})
SIGNUP_SUBMISSION_ALLOWED_STATUSES = frozenset({"planning"})
PLAN_ATTACHMENT_ALLOWED_STATUSES = frozenset({"draft"})
SLOT_GENERATION_ALLOWED_STATUSES = frozenset({"draft", "planning"})
ASSIGNMENT_MUTATION_ALLOWED_STATUSES = frozenset({"planning", "locked"})
RESERVE_MUTATION_ALLOWED_STATUSES = frozenset({"planning", "locked"})
ATTENDANCE_RECORDING_ALLOWED_STATUSES = frozenset({"locked", "completed"})
SCOUT_ATTENDANCE_RECORDING_ALLOWED_STATUSES = frozenset({"planning", "locked", "completed"})
READINESS_RECALCULATION_ALLOWED_STATUSES = frozenset({"draft", "planning", "locked", "completed"})

# Maps each status to the set of statuses it may transition to.
_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft":     frozenset({"planning"}),
    "planning":  frozenset({"locked", "completed"}),
    "locked":    frozenset({"completed"}),
    "completed": frozenset({"archived"}),
    "archived":  frozenset(),  # terminal state
}

_TITLE_MIN = 3
_TITLE_MAX = 120


def validate_operation_title(title: str) -> None:
    title = title.strip()
    if not title:
        raise ValidationError("Operation title must not be empty.")
    if len(title) < _TITLE_MIN:
        raise ValidationError(f"Operation title must be at least {_TITLE_MIN} characters.")
    if len(title) > _TITLE_MAX:
        raise ValidationError(f"Operation title must be at most {_TITLE_MAX} characters.")


def validate_operation_type(operation_type: str) -> None:
    if operation_type not in VALID_OPERATION_TYPES:
        raise ValidationError(
            f"Invalid operation_type '{operation_type}'. "
            f"Must be one of: {sorted(VALID_OPERATION_TYPES)}"
        )


def validate_scheduled_start_at(value: str) -> None:
    """Must be a parseable ISO-8601 datetime string."""
    if not value:
        raise ValidationError("scheduled_start_at must not be empty.")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(
            f"scheduled_start_at '{value}' is not a valid ISO-8601 datetime."
        )


def validate_operation_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValidationError(
            f"Invalid operation status '{status}'. "
            f"Must be one of: {sorted(VALID_STATUSES)}"
        )


def _validate_operation_action_allowed(
    operation_status: str,
    allowed_statuses: frozenset[str],
    action_label: str,
) -> None:
    if operation_status not in allowed_statuses:
        allowed = ", ".join(sorted(allowed_statuses)) or "none"
        raise ConflictError(
            f"Cannot {action_label} while operation status is "
            f"'{operation_status}'. Allowed statuses: {allowed}."
        )


def validate_signup_submission_allowed(operation_status: str) -> None:
    """Raise ConflictError when new SignupIntent submission is not allowed."""
    if operation_status not in SIGNUP_SUBMISSION_ALLOWED_STATUSES:
        if operation_status == "draft":
            message = (
                "Signups are not open yet. Publish the operation to planning "
                "before accepting signups."
            )
        else:
            message = (
                f"Signups are closed because the operation status is "
                f"'{operation_status}'."
            )
        raise ConflictError(message)


def validate_plan_attachment_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        PLAN_ATTACHMENT_ALLOWED_STATUSES,
        "attach an operation plan",
    )


def validate_slot_generation_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        SLOT_GENERATION_ALLOWED_STATUSES,
        "generate operation slots",
    )


def validate_assignment_mutation_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        ASSIGNMENT_MUTATION_ALLOWED_STATUSES,
        "change assignments",
    )


def validate_reserve_mutation_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        RESERVE_MUTATION_ALLOWED_STATUSES,
        "change reserve participants",
    )


def validate_attendance_recording_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        ATTENDANCE_RECORDING_ALLOWED_STATUSES,
        "record attendance",
    )


def validate_scout_attendance_recording_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        SCOUT_ATTENDANCE_RECORDING_ALLOWED_STATUSES,
        "record scout or support attendance",
    )


def validate_readiness_recalculation_allowed(operation_status: str) -> None:
    _validate_operation_action_allowed(
        operation_status,
        READINESS_RECALCULATION_ALLOWED_STATUSES,
        "recalculate readiness",
    )


def validate_status_transition(current: str, target: str) -> None:
    """
    Raise ConflictError if transitioning from current to target is not permitted.

    The transition table is defined in _VALID_TRANSITIONS.  Unknown current
    statuses (e.g. legacy values) are also rejected.
    """
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ConflictError(
            f"Invalid status transition: '{current}' → '{target}'. "
            f"Allowed from '{current}': {sorted(allowed) or 'none (terminal state)'}."
        )
