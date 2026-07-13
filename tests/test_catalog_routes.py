"""
Tests for app/routes_catalog.py — Phase 12.1 HTTP catalog endpoints.

Endpoints tested:
  GET /api/catalog/slots
  GET /api/catalog/items
  GET /api/catalog/items/{item_id}

Uses a minimal FastAPI app containing only the catalog router, so no database
or session setup is needed.  The catalog is reset to the bundled seed before
each test class via reload_catalog().
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.albion.item_catalog import VALID_SLOTS, reload_catalog
from app.routes_catalog import router

# Build a minimal app that only has the catalog router.
_test_app = FastAPI()
_test_app.include_router(router)

client = TestClient(_test_app, raise_server_exceptions=True)

_REQUIRED_FIELDS = {"item_id", "display_name", "tier", "enchantment", "slot", "is_two_handed", "icon_url"}


@pytest.fixture(autouse=True)
def fresh_catalog():
    """Reset catalog singleton to the bundled seed before each test."""
    reload_catalog()


# ---------------------------------------------------------------------------
# GET /api/catalog/slots
# ---------------------------------------------------------------------------

class TestSlotsEndpoint:
    def test_returns_200(self):
        r = client.get("/api/catalog/slots")
        assert r.status_code == 200

    def test_returns_list(self):
        r = client.get("/api/catalog/slots")
        assert isinstance(r.json(), list)

    def test_returns_all_10_slots(self):
        r = client.get("/api/catalog/slots")
        assert set(r.json()) == VALID_SLOTS

    def test_slots_are_sorted(self):
        r = client.get("/api/catalog/slots")
        slots = r.json()
        assert slots == sorted(slots)

    def test_no_legacy_slot_names(self):
        r = client.get("/api/catalog/slots")
        legacy = {"armor", "weapon", "hand", "ring", "neck"}
        assert not set(r.json()) & legacy


# ---------------------------------------------------------------------------
# GET /api/catalog/items/{item_id}
# ---------------------------------------------------------------------------

class TestItemDetailEndpoint:
    def test_known_item_returns_200(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        assert r.status_code == 200

    def test_response_has_required_fields(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        data = r.json()
        assert _REQUIRED_FIELDS.issubset(data.keys())

    def test_item_id_field_correct(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        assert r.json()["item_id"] == "T8_2H_CLAYMORE@3"

    def test_slot_main_hand(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        assert r.json()["slot"] == "main_hand"

    def test_is_two_handed_true(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        assert r.json()["is_two_handed"] is True

    def test_tier_and_enchantment_correct(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        data = r.json()
        assert data["tier"] == 8
        assert data["enchantment"] == 3

    def test_icon_url_in_response(self):
        r = client.get("/api/catalog/items/T8_2H_CLAYMORE@3")
        assert "render.albiononline.com" in r.json()["icon_url"]

    def test_lowercase_item_id_accepted(self):
        r = client.get("/api/catalog/items/t8_2h_claymore@3")
        assert r.status_code == 200
        assert r.json()["item_id"] == "T8_2H_CLAYMORE@3"

    def test_unknown_item_returns_404(self):
        r = client.get("/api/catalog/items/T8_INVENTED_WEAPON@1")
        assert r.status_code == 404

    def test_404_response_has_detail(self):
        r = client.get("/api/catalog/items/T8_INVENTED_WEAPON@1")
        assert "detail" in r.json()

    def test_one_handed_sword(self):
        r = client.get("/api/catalog/items/T8_MAIN_SWORD")
        assert r.status_code == 200
        data = r.json()
        assert data["slot"] == "main_hand"
        assert data["is_two_handed"] is False

    def test_off_hand_shield(self):
        r = client.get("/api/catalog/items/T7_OFF_SHIELD")
        assert r.status_code == 200
        assert r.json()["slot"] == "off_hand"


# ---------------------------------------------------------------------------
# GET /api/catalog/items (list with filters)
# ---------------------------------------------------------------------------

class TestItemListEndpoint:
    def test_no_filters_returns_all(self):
        r = client.get("/api/catalog/items")
        assert r.status_code == 200
        assert len(r.json()) > 100

    def test_response_items_have_required_fields(self):
        r = client.get("/api/catalog/items")
        for item in r.json()[:5]:
            assert _REQUIRED_FIELDS.issubset(item.keys())

    def test_filter_by_slot(self):
        r = client.get("/api/catalog/items?slot=main_hand")
        assert r.status_code == 200
        assert all(e["slot"] == "main_hand" for e in r.json())

    def test_filter_by_tier(self):
        r = client.get("/api/catalog/items?tier=7")
        assert r.status_code == 200
        assert all(e["tier"] == 7 for e in r.json())

    def test_filter_by_tier_8(self):
        r = client.get("/api/catalog/items?tier=8")
        assert r.status_code == 200
        assert all(e["tier"] == 8 for e in r.json())

    def test_filter_by_enchantment(self):
        r = client.get("/api/catalog/items?enchantment=3")
        assert r.status_code == 200
        assert all(e["enchantment"] == 3 for e in r.json())

    def test_filter_by_is_two_handed_true(self):
        r = client.get("/api/catalog/items?is_two_handed=true")
        assert r.status_code == 200
        assert len(r.json()) > 0
        assert all(e["is_two_handed"] for e in r.json())

    def test_filter_by_is_two_handed_false(self):
        r = client.get("/api/catalog/items?is_two_handed=false")
        assert r.status_code == 200
        assert all(not e["is_two_handed"] for e in r.json())

    def test_filter_by_name_q(self):
        r = client.get("/api/catalog/items?q=claymore")
        assert r.status_code == 200
        assert len(r.json()) > 0
        assert all("Claymore" in e["display_name"] for e in r.json())

    def test_filter_q_case_insensitive(self):
        r_lower = client.get("/api/catalog/items?q=claymore")
        r_upper = client.get("/api/catalog/items?q=CLAYMORE")
        assert r_lower.json() == r_upper.json()

    def test_combined_filters(self):
        r = client.get("/api/catalog/items?slot=main_hand&tier=8&enchantment=3&q=claymore")
        assert r.status_code == 200
        for e in r.json():
            assert e["slot"] == "main_hand"
            assert e["tier"] == 8
            assert e["enchantment"] == 3
            assert "Claymore" in e["display_name"]

    def test_no_results_returns_empty_list(self):
        r = client.get("/api/catalog/items?q=xyznotexist999")
        assert r.status_code == 200
        assert r.json() == []

    def test_invalid_slot_returns_422(self):
        r = client.get("/api/catalog/items?slot=weapon")
        assert r.status_code == 422

    def test_invalid_tier_returns_422(self):
        r = client.get("/api/catalog/items?tier=6")
        assert r.status_code == 422

    def test_invalid_tier_9_returns_422(self):
        r = client.get("/api/catalog/items?tier=9")
        assert r.status_code == 422

    def test_invalid_enchantment_returns_422(self):
        r = client.get("/api/catalog/items?enchantment=5")
        assert r.status_code == 422

    def test_negative_enchantment_returns_422(self):
        r = client.get("/api/catalog/items?enchantment=-1")
        assert r.status_code == 422

    def test_422_has_detail(self):
        r = client.get("/api/catalog/items?slot=invalid_slot")
        assert "detail" in r.json()

    def test_no_t8_4_items_in_default_response(self):
        r = client.get("/api/catalog/items")
        assert all(e["enchantment"] <= 3 for e in r.json())

    def test_all_10_slots_represented(self):
        r = client.get("/api/catalog/items")
        present_slots = {e["slot"] for e in r.json()}
        assert present_slots == VALID_SLOTS

    def test_response_items_sorted_by_slot(self):
        r = client.get("/api/catalog/items")
        items = r.json()
        slots = [e["slot"] for e in items]
        assert slots == sorted(slots)
