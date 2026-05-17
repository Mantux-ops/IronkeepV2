"""
Payout ledger domain rules.

Invariants:
- entry_type must be one of VALID_ENTRY_TYPES.
- status must be one of VALID_STATUSES.
- amount_silver must be >= 0 for regear/payout entries.
- adjustment entries may carry any integer amount (including negative).
- Paid and voided entries are immutable — no updates or re-voiding allowed.
- Status transitions are strictly:
    draft → approved → paid  (forward chain)
    draft → voided            (abandon before approval)
    approved → voided         (abandon after approval)
    paid → (nothing)          (terminal — permanent)
    voided → (nothing)        (terminal — permanent)
- Only approved entries may be marked paid.  draft → paid is forbidden.
"""

from __future__ import annotations

from app.errors import ValidationError

VALID_ENTRY_TYPES = frozenset({"regear", "payout", "adjustment"})
VALID_STATUSES    = frozenset({"draft", "approved", "paid", "voided"})

# Statuses from which editing the amount/note is forbidden.
IMMUTABLE_STATUSES = frozenset({"paid", "voided"})

# Statuses from which voiding is forbidden (paid rows are permanent).
UNVOIDABLE_STATUSES = frozenset({"paid"})

# Valid forward transitions (source → {allowed targets}).
_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft":    frozenset({"approved", "voided"}),
    "approved": frozenset({"paid", "voided"}),
    "paid":     frozenset(),          # terminal — no transitions allowed
    "voided":   frozenset(),          # terminal — no transitions allowed
}


def validate_entry_type(entry_type: str) -> None:
    if entry_type not in VALID_ENTRY_TYPES:
        raise ValidationError(
            f"Invalid entry_type '{entry_type}'. "
            f"Must be one of: {sorted(VALID_ENTRY_TYPES)}"
        )


def validate_amount(entry_type: str, amount_silver: int) -> None:
    """
    Enforce the sign constraint on amount_silver.

    regear / payout → must be >= 0.
    adjustment      → any integer (including negative) is allowed.
    """
    if not isinstance(amount_silver, int):
        raise ValidationError("amount_silver must be an integer.")
    if entry_type != "adjustment" and amount_silver < 0:
        raise ValidationError(
            f"amount_silver must be >= 0 for entry_type '{entry_type}'."
        )


def validate_status_transition(current_status: str, new_status: str) -> None:
    """Raise ValidationError if the transition is not permitted."""
    allowed = _VALID_TRANSITIONS.get(current_status, frozenset())
    if new_status not in allowed:
        raise ValidationError(
            f"Cannot transition payout ledger entry from '{current_status}' "
            f"to '{new_status}'."
        )


def assert_mutable(entry: dict) -> None:
    """Raise ValidationError if the entry is in an immutable status."""
    if entry.get("status") in IMMUTABLE_STATUSES:
        raise ValidationError(
            f"Payout ledger entry is {entry['status']} and cannot be modified."
        )


def assert_voidable(entry: dict) -> None:
    """Raise ValidationError if the entry cannot be voided."""
    if entry.get("status") in UNVOIDABLE_STATUSES:
        raise ValidationError(
            "Paid payout ledger entries cannot be voided."
        )
    if entry.get("status") == "voided":
        raise ValidationError(
            "Payout ledger entry is already voided."
        )


def assert_payable(entry: dict) -> None:
    """
    Raise ValidationError if the entry cannot be marked paid.

    Only approved entries may transition to paid.
    draft  → paid is forbidden (must approve first).
    voided → paid is forbidden (terminal).
    paid   → paid is forbidden (already paid).
    """
    status = entry.get("status")
    if status == "paid":
        raise ValidationError("Payout ledger entry is already paid.")
    if status != "approved":
        raise ValidationError(
            f"Only approved entries can be marked paid; this entry is '{status}'."
        )
