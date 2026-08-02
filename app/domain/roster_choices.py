"""
Roster choice rules — turning a roster into the options a player can pick from.

No DB access, no Discord imports. The Discord surface that renders these choices
owns its own shape limits; this module only decides what the choices are.

A roster is a flat list of operation slots, and a 20-man composition typically
repeats the same loadout five times over. Offering every slot individually would
make a player choose between five identical "DPS · Fire Staff" entries, so slots
are collapsed to their distinct role + build + weapon combinations.

Key invariants enforced here:
- A choice is identified by a content digest, never by list position. The picker
  lives in a Discord message that is only rewritten when an officer re-posts, so
  an index would silently shift onto a different role the moment the composition
  is edited. A digest either resolves to the same choice or to nothing at all.
- Choices are not filtered by assignment state and carry no free-slot count.
  Both would be read from a message that goes stale the instant someone is
  assigned, and a picker that quietly lies is worse than one that says less.
- Roster order is preserved (party, then slot), so the picker reads in the same
  order as the composition an officer built.
"""

from __future__ import annotations

import hashlib

#: Field separator for the digest. A unit separator cannot occur in a role or
#: build name, so "Tank" + "Mace" can never collide with "Tan" + "kMace".
_FIELD_SEP = "\x1f"


def picker_is_offered(operation_status: str | None, plan: dict | None) -> bool:
    """Whether a role picker should be rendered for this operation at all.

    A picker is only honest while the same conditions that let a signup through
    hold: an announcement can be posted from draft, and slots can be generated in
    draft too, so without this check a member would face a menu whose every
    option answers "signups are not open yet".
    """
    from app.domain import guild_operations  # noqa: PLC0415 — sibling, no cycle

    if (operation_status or "") not in guild_operations.SIGNUP_SUBMISSION_ALLOWED_STATUSES:
        return False
    return not (plan and plan.get("signup_status") == "closed")


def choice_key(
    role: str | None,
    build_name: str | None,
    weapon_name: str | None,
) -> str:
    """Stable identifier for one role choice.

    Derived from the content rather than stored, so the same choice keeps the
    same key across processes and restarts — the web process writes the key into
    a Discord message and the bot process resolves it back much later.
    """
    raw = _FIELD_SEP.join((
        (role or "").strip(),
        (build_name or "").strip(),
        (weapon_name or "").strip(),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_role_choices(slots: list[dict]) -> list[dict]:
    """Collapse roster slots into the distinct roles a player can pick.

    Returns one dict per distinct (role, build_name, weapon_name) in first-seen
    order, each with: key, role, build_name, weapon_name.

    Slots missing a role are skipped: an unnamed role cannot be offered as a
    choice, and such rows exist (a slot can be saved with placeholder text).
    """
    seen: set[str] = set()
    choices: list[dict] = []
    for slot in slots:
        role = (slot.get("role") or "").strip()
        if not role:
            continue
        build_name  = (slot.get("build_name") or "").strip()
        weapon_name = (slot.get("weapon_name") or "").strip()
        key = choice_key(role, build_name, weapon_name)
        if key in seen:
            continue
        seen.add(key)
        choices.append({
            "key":         key,
            "role":        role,
            "build_name":  build_name,
            "weapon_name": weapon_name,
        })
    return choices


def find_role_choice(slots: list[dict], key: str) -> dict | None:
    """Resolve a picked key back to its choice, or None when it no longer exists.

    None is the expected outcome for a stale picker — the composition was edited
    after the message was posted — and callers must report that rather than
    guessing at a replacement role.
    """
    if not key:
        return None
    for choice in build_role_choices(slots):
        if choice["key"] == key:
            return choice
    return None


def find_matching_slots(slots: list[dict], choice: dict) -> list[dict]:
    """Every roster slot that this choice describes, in roster order."""
    key = choice.get("key") or choice_key(
        choice.get("role"), choice.get("build_name"), choice.get("weapon_name")
    )
    return [
        slot
        for slot in slots
        if choice_key(
            slot.get("role"), slot.get("build_name"), slot.get("weapon_name")
        ) == key
    ]
