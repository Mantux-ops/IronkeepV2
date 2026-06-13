"""
AlbionBuild domain rules.

Builds are reusable operational doctrine entities — named, role-specific
equipment loadouts that officers create once and attach to composition slot
templates for doctrine reuse across operations.

Key invariants
--------------
* Editing a build does NOT update slot templates that already reference it.
  The slot template stores a text snapshot (build_name, weapon_name) at
  attach time; the albion_build_id FK is a traceability reference only.
* operation_slots are frozen text-only snapshots and are never affected by
  build edits regardless of FK state.
* Retired builds cannot be newly attached to slot templates, but existing
  compositions and operation_slots that reference them remain stable and
  readable.
"""

from __future__ import annotations

from app.errors import ValidationError

_NAME_MIN   = 2
_NAME_MAX   = 100
_FIELD_MAX  = 120   # equipment item name fields
_NOTES_MAX  = 500   # doctrine notes — longer to support rotation / tier context


def validate_build(data: dict) -> None:
    """Validate a build creation or update payload.

    ``data`` should be a dict with at minimum ``name``, ``role``, and
    ``weapon_name`` keys.  Optional equipment fields are checked for
    max-length only.  Notes has a separate higher limit to allow doctrine
    descriptions.
    """
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("Build name must not be empty.")
    if len(name) < _NAME_MIN:
        raise ValidationError(
            f"Build name must be at least {_NAME_MIN} characters."
        )
    if len(name) > _NAME_MAX:
        raise ValidationError(
            f"Build name must be at most {_NAME_MAX} characters."
        )

    role = (data.get("role") or "").strip()
    if not role:
        raise ValidationError("Build role must not be empty.")

    weapon = (data.get("weapon_name") or "").strip()
    if not weapon:
        raise ValidationError("Build weapon_name must not be empty.")

    equipment_fields = (
        "offhand_name", "head_name", "armor_name", "shoes_name",
        "cape_name", "food_name", "potion_name", "doctrine_role",
    )
    for field in equipment_fields:
        val = data.get(field)
        if val and len(str(val).strip()) > _FIELD_MAX:
            raise ValidationError(
                f"Build field '{field}' must be at most {_FIELD_MAX} characters."
            )

    notes = data.get("notes")
    if notes and len(str(notes).strip()) > _NOTES_MAX:
        raise ValidationError(
            f"Build notes must be at most {_NOTES_MAX} characters."
        )
