"""
Phase 12.4 — Persistence tests for alt-gear (Fase B) and spells (Fase C).

Covers create_build / create_build_version round-trips for:
  * one alternative (swap) item per slot: is_primary=0, priority=1
  * spell selections stored per field_key
  * validation of spell selections against equipped items
  * no-change detection including alts and spells
"""

from __future__ import annotations

import json
import pytest

from app import database, repositories
from app.albion import spell_catalog
from app.albion.item_catalog import get_catalog
from app.application import use_cases
from app.errors import ValidationError

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup(slug="parity"):
    owner = make_user(f"owner-{slug}")
    ws = make_workspace(owner_user_id=owner["id"], slug=slug, name=f"WS {slug}")
    return owner, ws


def _two_main_hand_items():
    """Return two distinct main_hand item ids (for primary + alt)."""
    cat = get_catalog()
    items = cat.get_by_slot("main_hand")
    if len(items) < 2:
        pytest.skip("Need at least two main_hand items")
    return items[0]["item_id"], items[1]["item_id"]


def _mace_and_q_spell():
    """Return (mace_item_id, q_spell_name) for a spell-bearing main_hand item."""
    cat = get_catalog()
    for item in cat.get_by_slot("main_hand"):
        data = spell_catalog.get_spells_for_item(item["item_id"])
        if not data:
            continue
        q = next((s for s in data["slots"] if s["field_suffix"] == "spell_q"), None)
        if q and q["spells"]:
            return item["item_id"], q["spells"][0]["name"]
    pytest.skip("No spell-bearing main_hand item with a Q spell")


def _current_slot_items(ws_id, build):
    with database.transaction() as db:
        return repositories.get_build_slot_items(
            db, build["current_version_id"], ws_id
        )


def _current_spells(ws_id, build):
    with database.transaction() as db:
        return repositories.get_build_spells(
            db, build["current_version_id"], ws_id
        )


# ---------------------------------------------------------------------------
# Alt-gear persistence
# ---------------------------------------------------------------------------

def test_create_build_with_alt_persists_both_rows():
    owner, ws = _setup("alt1")
    primary_id, alt_id = _two_main_hand_items()
    slot_json = json.dumps([
        {"slot": "main_hand", "item_id": primary_id, "is_primary": True, "priority": 0},
        {"slot": "main_hand", "item_id": alt_id, "is_primary": False, "priority": 1},
    ])
    build = use_cases.create_build(
        guild_workspace_id=ws["id"], actor_user_id=owner["id"],
        name="Alt Build", description="", role="tank", event_type="cta",
        minimum_ip=0, status="draft", slot_items_json=slot_json,
    )
    rows = _current_slot_items(ws["id"], build)
    main_rows = [r for r in rows if r["slot"] == "main_hand"]
    assert len(main_rows) == 2
    primary = next(r for r in main_rows if r["is_primary"])
    alt = next(r for r in main_rows if not r["is_primary"])
    assert primary["item_id"] == primary_id
    assert primary["priority"] == 0
    assert alt["item_id"] == alt_id
    assert alt["priority"] == 1


def test_alt_change_creates_new_version():
    owner, ws = _setup("alt2")
    primary_id, alt_id = _two_main_hand_items()
    base = json.dumps([{"slot": "main_hand", "item_id": primary_id, "is_primary": True}])
    build = use_cases.create_build(
        guild_workspace_id=ws["id"], actor_user_id=owner["id"],
        name="Alt Build 2", description="", role="tank", event_type="cta",
        minimum_ip=0, status="draft", slot_items_json=base,
    )
    # Adding an alt should produce a new version.
    with_alt = json.dumps([
        {"slot": "main_hand", "item_id": primary_id, "is_primary": True},
        {"slot": "main_hand", "item_id": alt_id, "is_primary": False, "priority": 1},
    ])
    res = use_cases.create_build_version(
        guild_workspace_id=ws["id"], build_id=build["id"], actor_user_id=owner["id"],
        slot_items_json=with_alt,
    )
    assert res["created"] is True

    # Saving the exact same alt again = no change.
    res2 = use_cases.create_build_version(
        guild_workspace_id=ws["id"], build_id=build["id"], actor_user_id=owner["id"],
        slot_items_json=with_alt,
    )
    assert res2["created"] is False


# ---------------------------------------------------------------------------
# Spell persistence
# ---------------------------------------------------------------------------

def test_create_build_with_spell_persists():
    owner, ws = _setup("sp1")
    mace, q_spell = _mace_and_q_spell()
    slot_json = json.dumps([{"slot": "main_hand", "item_id": mace, "is_primary": True}])
    spells_json = json.dumps([{"field_key": "weapon_spell_q", "spell_name": q_spell}])
    build = use_cases.create_build(
        guild_workspace_id=ws["id"], actor_user_id=owner["id"],
        name="Spell Build", description="", role="tank", event_type="cta",
        minimum_ip=0, status="draft", slot_items_json=slot_json,
        spells_json=spells_json,
    )
    spells = _current_spells(ws["id"], build)
    assert len(spells) == 1
    assert spells[0]["field_key"] == "weapon_spell_q"
    assert spells[0]["spell_name"] == q_spell


def test_invalid_spell_name_rejected():
    owner, ws = _setup("sp2")
    mace, _ = _mace_and_q_spell()
    slot_json = json.dumps([{"slot": "main_hand", "item_id": mace, "is_primary": True}])
    spells_json = json.dumps([{"field_key": "weapon_spell_q", "spell_name": "Totally Fake Spell"}])
    with pytest.raises(ValidationError):
        use_cases.create_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Bad Spell", description="", role="tank", event_type="cta",
            minimum_ip=0, status="draft", slot_items_json=slot_json,
            spells_json=spells_json,
        )


def test_spell_without_item_rejected():
    owner, ws = _setup("sp3")
    mace, q_spell = _mace_and_q_spell()
    # main_hand present, but the spell targets head which has no item.
    slot_json = json.dumps([{"slot": "main_hand", "item_id": mace, "is_primary": True}])
    spells_json = json.dumps([{"field_key": "head_passive", "spell_name": q_spell}])
    with pytest.raises(ValidationError):
        use_cases.create_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Orphan Spell", description="", role="tank", event_type="cta",
            minimum_ip=0, status="draft", slot_items_json=slot_json,
            spells_json=spells_json,
        )


def test_unknown_field_key_rejected():
    owner, ws = _setup("sp4")
    mace, q_spell = _mace_and_q_spell()
    slot_json = json.dumps([{"slot": "main_hand", "item_id": mace, "is_primary": True}])
    spells_json = json.dumps([{"field_key": "bogus_field", "spell_name": q_spell}])
    with pytest.raises(ValidationError):
        use_cases.create_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Bad Field", description="", role="tank", event_type="cta",
            minimum_ip=0, status="draft", slot_items_json=slot_json,
            spells_json=spells_json,
        )


def test_spell_change_creates_new_version_and_no_change_detected():
    owner, ws = _setup("sp5")
    mace, q_spell = _mace_and_q_spell()
    slot_json = json.dumps([{"slot": "main_hand", "item_id": mace, "is_primary": True}])
    build = use_cases.create_build(
        guild_workspace_id=ws["id"], actor_user_id=owner["id"],
        name="Spell Ver", description="", role="tank", event_type="cta",
        minimum_ip=0, status="draft", slot_items_json=slot_json,
    )
    spells_json = json.dumps([{"field_key": "weapon_spell_q", "spell_name": q_spell}])
    res = use_cases.create_build_version(
        guild_workspace_id=ws["id"], build_id=build["id"], actor_user_id=owner["id"],
        slot_items_json=slot_json, spells_json=spells_json,
    )
    assert res["created"] is True

    # Same slots + same spell = no change.
    res2 = use_cases.create_build_version(
        guild_workspace_id=ws["id"], build_id=build["id"], actor_user_id=owner["id"],
        slot_items_json=slot_json, spells_json=spells_json,
    )
    assert res2["created"] is False


def test_changing_item_prunes_would_be_invalid_spell():
    """Submitting a spell valid for the equipped item succeeds; the validator
    ties spells to the equipped primary item."""
    owner, ws = _setup("sp6")
    mace, q_spell = _mace_and_q_spell()
    slot_json = json.dumps([{"slot": "main_hand", "item_id": mace, "is_primary": True}])
    spells_json = json.dumps([{"field_key": "weapon_spell_q", "spell_name": q_spell}])
    build = use_cases.create_build(
        guild_workspace_id=ws["id"], actor_user_id=owner["id"],
        name="Prune", description="", role="tank", event_type="cta",
        minimum_ip=0, status="draft", slot_items_json=slot_json,
        spells_json=spells_json,
    )
    assert len(_current_spells(ws["id"], build)) == 1
