"""
AlbionComposition and CompositionSlotTemplate domain rules.

Compositions are workspace-level, reusable templates.  Editing them after an
operation has generated slots is allowed — operation slots are a frozen
snapshot and are not retroactively affected.
"""

from __future__ import annotations

from app.errors import ValidationError

VALID_PRIORITIES = frozenset({"core", "normal"})

# Standard Albion ZvZ roles.  The validator accepts any non-empty string so
# guild-specific role names are not rejected — this list is informational.
ALBION_STANDARD_ROLES = (
    "Tank",
    "Healer",
    "DPS",
    "Support",
    "Scout",
    "Caller",
    "Battlemount",
    "Fill",
)

_NAME_MIN = 2
_NAME_MAX = 100


def validate_composition_name(name: str) -> None:
    name = name.strip()
    if not name:
        raise ValidationError("Composition name must not be empty.")
    if len(name) < _NAME_MIN:
        raise ValidationError(f"Composition name must be at least {_NAME_MIN} characters.")
    if len(name) > _NAME_MAX:
        raise ValidationError(f"Composition name must be at most {_NAME_MAX} characters.")


def validate_slot_template(slot: dict) -> None:
    """Validate a single composition slot template dict."""
    if not isinstance(slot.get("party_number"), int) or slot["party_number"] < 1:
        raise ValidationError("slot.party_number must be a positive integer.")
    if not isinstance(slot.get("slot_index"), int) or slot["slot_index"] < 1:
        raise ValidationError("slot.slot_index must be a positive integer.")
    role = slot.get("role", "").strip()
    if not role:
        raise ValidationError("slot.role must not be empty.")
    build = slot.get("build_name", "").strip()
    if not build:
        raise ValidationError("slot.build_name must not be empty.")
    priority = slot.get("priority", "normal")
    if priority not in VALID_PRIORITIES:
        raise ValidationError(
            f"slot.priority '{priority}' is invalid. Must be one of: {sorted(VALID_PRIORITIES)}"
        )


def validate_slot_templates(slots: list[dict]) -> None:
    """Validate a full list of slot templates, including uniqueness of (party, index) pairs."""
    if not slots:
        raise ValidationError("A composition must have at least one slot template.")
    for slot in slots:
        validate_slot_template(slot)
    seen: set[tuple[int, int]] = set()
    for slot in slots:
        key = (slot["party_number"], slot["slot_index"])
        if key in seen:
            raise ValidationError(
                f"Duplicate slot template: party_number={key[0]}, slot_index={key[1]}."
            )
        seen.add(key)
