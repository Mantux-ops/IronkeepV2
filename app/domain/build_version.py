"""
Versioned build domain rules  (Phase 12.3).

This module validates input for the normalized
    Build (albion_builds, expanded)
    → BuildVersion (albion_build_versions)
    → BuildSlotItem (albion_build_slot_items)
model driven by the visual build editor.

It is intentionally separate from albion_builds.py, which handles the
legacy flat text-field builds used by compositions and operation_slots.

Key invariants enforced here
----------------------------
* Build name is non-empty and within length bounds.
* Role must be one of VALID_ROLES.
* Event type must be one of VALID_EVENT_TYPES.
* Minimum IP is a non-negative integer.
* Status must be one of VALID_STATUSES (draft | published | archived).
* Each slot item belongs to a valid slot in VALID_BUILD_SLOTS.
* At most one primary item per slot.
* Two-handed main_hand cannot coexist with an off_hand item.
* Published status requires PUBLISHED_REQUIRED_SLOTS to be filled.
"""

from __future__ import annotations

from app.errors import ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NAME_MIN    = 2
_NAME_MAX    = 100
_DESC_MAX    = 1000
_NOTES_MAX   = 500
_SUMMARY_MAX = 300

VALID_ROLES: frozenset[str] = frozenset({
    "tank", "healer", "support", "melee_dps", "ranged_dps", "battlemount", "utility",
})

VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "cta", "zvz", "gank", "roam", "ava", "bomb_squad", "other",
})

VALID_STATUSES: frozenset[str] = frozenset({"draft", "published", "archived"})

#: Equipment slots supported by the visual editor.
#: Must match VALID_SLOTS in app/albion/item_catalog.py exactly.
VALID_BUILD_SLOTS: frozenset[str] = frozenset({
    "main_hand", "off_hand", "head", "chest", "shoes",
    "cape", "bag", "mount", "food", "potion",
})

#: Slots that must be filled for status='published'.
#: Chosen to cover the core combat loadout; remaining slots are optional.
PUBLISHED_REQUIRED_SLOTS: frozenset[str] = frozenset({
    "main_hand", "head", "chest", "shoes", "food", "potion",
})

ROLE_DISPLAY: dict[str, str] = {
    "tank":       "Tank",
    "healer":     "Healer",
    "support":    "Support",
    "melee_dps":  "Melee DPS",
    "ranged_dps": "Ranged DPS",
    "battlemount": "Battlemount",
    "utility":    "Utility",
}

EVENT_TYPE_DISPLAY: dict[str, str] = {
    "cta":        "CTA",
    "zvz":        "ZvZ",
    "gank":       "Gank",
    "roam":       "Roam",
    "ava":        "AvA",
    "bomb_squad": "Bomb Squad",
    "other":      "Other",
}

# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------

def validate_build_meta(data: dict) -> None:
    """
    Validate the metadata fields of a versioned build.

    Checks: name, description, role, event_type, minimum_ip, status,
    change_summary.  Raises ValidationError for any invalid field.
    Does NOT validate slot items — call validate_slot_items() separately.
    """
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("Build name must not be empty.")
    if len(name) < _NAME_MIN:
        raise ValidationError(f"Build name must be at least {_NAME_MIN} characters.")
    if len(name) > _NAME_MAX:
        raise ValidationError(f"Build name must be at most {_NAME_MAX} characters.")

    description = (data.get("description") or "").strip()
    if len(description) > _DESC_MAX:
        raise ValidationError(
            f"Description must be at most {_DESC_MAX} characters."
        )

    role = (data.get("role") or "").strip()
    if not role:
        raise ValidationError("Build role must not be empty.")
    if role not in VALID_ROLES:
        raise ValidationError(
            f"Invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}."
        )

    event_type = (data.get("event_type") or "").strip()
    if not event_type:
        raise ValidationError("Event type must not be empty.")
    if event_type not in VALID_EVENT_TYPES:
        raise ValidationError(
            f"Invalid event type '{event_type}'. "
            f"Must be one of: {sorted(VALID_EVENT_TYPES)}."
        )

    minimum_ip_raw = data.get("minimum_ip", 0)
    try:
        minimum_ip = int(minimum_ip_raw)
    except (ValueError, TypeError):
        raise ValidationError("Minimum IP must be a non-negative integer.")
    if minimum_ip < 0:
        raise ValidationError("Minimum IP must be 0 or greater.")

    status = (data.get("status") or "draft").strip()
    if status not in VALID_STATUSES:
        raise ValidationError(
            f"Invalid status '{status}'. "
            f"Must be one of: {sorted(VALID_STATUSES)}."
        )
    if status == "archived":
        raise ValidationError(
            "Cannot set status to 'archived' directly. Use the archive action."
        )

    change_summary = (data.get("change_summary") or "").strip()
    if len(change_summary) > _SUMMARY_MAX:
        raise ValidationError(
            f"Change summary must be at most {_SUMMARY_MAX} characters."
        )


# ---------------------------------------------------------------------------
# Slot item validation
# ---------------------------------------------------------------------------

def validate_slot_items(slot_items: list[dict], status: str) -> None:
    """
    Validate a list of slot item dicts (post-catalog lookup).

    Each dict must have: slot, item_id, tier, enchantment, is_two_handed,
    is_primary.  These fields are set by the use case after catalog lookup —
    client-supplied tier/enchantment/display_name are never trusted here.

    Invariants checked:
    * Slot must be in VALID_BUILD_SLOTS.
    * Tier must be 7 or 8.
    * Enchantment must be 0–3.
    * At most one primary item per slot.
    * No duplicate item_id within the same slot.
    * Two-handed main_hand forbids any off_hand item.
    * Published status requires PUBLISHED_REQUIRED_SLOTS all filled.
    """
    primary_per_slot: dict[str, bool] = {}
    ids_per_slot: dict[str, set[str]] = {}
    is_main_two_handed = False

    for item in slot_items:
        slot = (item.get("slot") or "").strip()
        if not slot:
            raise ValidationError("Slot item is missing the 'slot' field.")
        if slot not in VALID_BUILD_SLOTS:
            raise ValidationError(
                f"Unknown slot '{slot}'. "
                f"Must be one of: {sorted(VALID_BUILD_SLOTS)}."
            )

        item_id = (item.get("item_id") or "").strip()
        if not item_id:
            raise ValidationError(f"Slot '{slot}' has an empty item_id.")

        tier = item.get("tier")
        if tier not in (7, 8):
            raise ValidationError(
                f"Slot '{slot}': tier must be 7 or 8, got {tier!r}."
            )

        enchantment = item.get("enchantment")
        if not isinstance(enchantment, int) or not (0 <= enchantment <= 3):
            raise ValidationError(
                f"Slot '{slot}': enchantment must be 0–3, got {enchantment!r}."
            )

        is_primary = bool(item.get("is_primary", True))
        if is_primary:
            if primary_per_slot.get(slot):
                raise ValidationError(
                    f"Slot '{slot}' has more than one primary item. "
                    "Only one primary item is allowed per slot."
                )
            primary_per_slot[slot] = True

        # Duplicate item_id within the same slot
        ids_per_slot.setdefault(slot, set())
        if item_id in ids_per_slot[slot]:
            raise ValidationError(
                f"Item '{item_id}' appears more than once in slot '{slot}'."
            )
        ids_per_slot[slot].add(item_id)

        if item.get("is_two_handed") and slot == "main_hand":
            is_main_two_handed = True

    if is_main_two_handed and "off_hand" in primary_per_slot:
        raise ValidationError(
            "A two-handed main weapon cannot be combined with an off-hand item."
        )

    if status == "published":
        filled_primary = {
            s for s, has in primary_per_slot.items() if has
        }
        missing = PUBLISHED_REQUIRED_SLOTS - filled_primary
        if missing:
            raise ValidationError(
                "Published builds require these slots to be filled: "
                + ", ".join(sorted(missing))
                + "."
            )


# ---------------------------------------------------------------------------
# Build type discriminators
# ---------------------------------------------------------------------------

#: Sentinel used for legacy NOT NULL constraint on weapon_name.
#: Post-migration (Phase 12.3b) V2 builds store NULL in weapon_name.
#: This constant is kept for reference only — new code must use NULL,
#: not this sentinel, when checking is_versioned_build().
VERSIONED_BUILD_WEAPON_NAME_LEGACY_SENTINEL = ""


def is_versioned_build(build: dict) -> bool:
    """Return True when *build* is a Phase 12.3 versioned build.

    Discriminator: ``current_version_id IS NOT NULL``.
    V2 builds are managed via the visual editor and store equipment in
    ``albion_build_slot_items`` via ``albion_build_versions``.
    They must never be processed by legacy equipment logic (weapon_name,
    offhand_name, doctrine_summary, import, fork, composition-slot-select).
    """
    return bool(build.get("current_version_id"))


def is_legacy_build(build: dict) -> bool:
    """Return True when *build* is a legacy flat-equipment build.

    Discriminator: ``current_version_id IS NULL``.
    Legacy builds store equipment in flat text columns on ``albion_builds``
    (weapon_name, offhand_name, head_name, …) and are consumed by
    compositions, operation_slots, and the legacy flat-form editor.
    They must never be processed by V2 versioning logic.
    """
    return not bool(build.get("current_version_id"))
