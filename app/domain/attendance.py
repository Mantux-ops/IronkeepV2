"""
Attendance domain rules.

Attendance records the actual outcome for each assigned participant in a
GuildOperation.  Only active assignments (status='assigned') can receive an
attendance record — unassigned signers are out of scope.

Re-marking is an update, not a duplicate insert.  Every record or update
emits an attendance.recorded OperationalEvent within the same transaction.
"""

from __future__ import annotations

from app.errors import ValidationError

VALID_STATUSES = frozenset({"present", "late", "absent", "no_show", "excused"})

# Ordered for display in forms and tables.
STATUS_ORDER: list[str] = ["present", "late", "absent", "no_show", "excused"]


def validate_attendance_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValidationError(
            f"Invalid attendance status '{status}'. "
            f"Must be one of: {STATUS_ORDER}"
        )
