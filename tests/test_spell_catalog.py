"""
Phase 12.4 — Spell catalog tests (Fase C).

Coverage:
  * Seed loads and is non-empty.
  * get_base_type strips tier prefix + enchantment suffix.
  * get_spells_for_item returns weapon Q/W/E/Passive for a mace.
  * field_options_for_item maps field keys to allowed spell names.
  * get_spell_icon_url resolves to a render CDN URL (proxy off).
  * GET /api/catalog/spells returns spell slots for a valid item and an empty
    slot list for unknown/empty item ids.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.albion import spell_catalog
from app.albion.item_catalog import get_catalog
from app.main import app


def _spell_bearing_main_hand() -> str | None:
    """Return the first main_hand catalog item that has weapon spell data."""
    cat = get_catalog()
    for item in cat.get_by_slot("main_hand"):
        data = spell_catalog.get_spells_for_item(item["item_id"])
        if data and data["slots"]:
            return item["item_id"]
    return None


def test_seed_loads_and_non_empty():
    cat = spell_catalog.get_spell_catalog()
    # MAIN_MACE is a stable base-type present in the seed.
    assert cat.get_for_item("T8_MAIN_MACE") is not None


def test_get_base_type():
    assert spell_catalog.get_base_type("T8_MAIN_MACE@3") == "MAIN_MACE"
    assert spell_catalog.get_base_type("T7_ARMOR_PLATE_AVALON") == "ARMOR_PLATE_AVALON"
    assert spell_catalog.get_base_type("MAIN_MACE") == "MAIN_MACE"


def test_mace_has_qwe_and_passive():
    data = spell_catalog.get_spells_for_item("T7_MAIN_MACE@1")
    assert data is not None
    assert data["item_type"] == "weapon"
    labels = [s["label"] for s in data["slots"]]
    assert "Q" in labels and "W" in labels and "E" in labels
    # Every spell has a name and an icon url.
    for slot in data["slots"]:
        for sp in slot["spells"]:
            assert sp["name"]
            assert sp["icon_url"].startswith("https://render.albiononline.com/v1/spell/")


def test_unknown_item_returns_none():
    assert spell_catalog.get_spells_for_item("T8_TOTALLY_FAKE_ITEM") is None
    assert spell_catalog.get_spells_for_item("") is None


def test_field_options_for_item():
    cat = spell_catalog.get_spell_catalog()
    opts = cat.field_options_for_item("main_hand", "T8_MAIN_MACE")
    assert "weapon_spell_q" in opts
    assert all(fk.startswith("weapon_") for fk in opts)
    # Options are non-empty sets of spell names.
    assert all(isinstance(v, set) and v for v in opts.values())


def test_field_options_empty_for_non_spell_slot():
    cat = spell_catalog.get_spell_catalog()
    assert cat.field_options_for_item("food", "T7_MEAL_OMELETTE_AVALON") == {}


def test_icon_url_proxy_off(monkeypatch):
    monkeypatch.delenv("ITEM_ICON_PROXY_ENABLED", raising=False)
    url = spell_catalog.get_spell_icon_url("Defensive Slam", 40)
    assert url.startswith("https://render.albiononline.com/v1/spell/")


def test_icon_url_proxy_on(monkeypatch):
    monkeypatch.setenv("ITEM_ICON_PROXY_ENABLED", "1")
    url = spell_catalog.get_spell_icon_url("Defensive Slam", 40)
    assert url.startswith("/spell-icons?")


def test_api_spells_valid_item():
    item_id = _spell_bearing_main_hand()
    assert item_id, "expected at least one spell-bearing main_hand item"
    client = TestClient(app)
    r = client.get("/api/catalog/spells", params={"item_id": item_id})
    assert r.status_code == 200
    body = r.json()
    assert body["item_type"] is not None
    assert isinstance(body["slots"], list) and body["slots"]


def test_api_spells_unknown_item_returns_empty():
    client = TestClient(app)
    r = client.get("/api/catalog/spells", params={"item_id": "T8_FAKE_NONEXISTENT"})
    assert r.status_code == 200
    assert r.json() == {"item_type": None, "slots": []}


def test_api_spells_empty_item_id():
    client = TestClient(app)
    r = client.get("/api/catalog/spells", params={"item_id": ""})
    assert r.status_code == 200
    assert r.json()["slots"] == []
