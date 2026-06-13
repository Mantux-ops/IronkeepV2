"""
Build Library CSV/Paste Import tests.

Covers:
  Group 1 — Parser: delimiter detection (CSV, TSV)
  Group 2 — Parser: header detection and alias mapping
  Group 3 — Parser: positional (no header) rows
  Group 4 — Parser: blank-row and edge-case handling
  Group 5 — Use case: bulk_import_albion_builds success
  Group 6 — Use case: bulk_import_albion_builds validation failures
  Group 7 — Use case: permission guard
  Group 8 — Route: GET /builds/import
  Group 9 — Route: POST /builds/import/preview — valid rows
  Group 10 — Route: POST /builds/import/preview — invalid rows
  Group 11 — Route: POST /builds/import/confirm — success
  Group 12 — Route: POST /builds/import/confirm — guard / edge cases
  Group 13 — Template: builds_list.html Import CSV button visibility
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app
from app.routes import _parse_build_import_csv

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_viewer(ws_id: str, owner_id: str, display_name: str) -> dict:
    user = make_user(display_name)
    use_cases.add_workspace_member(ws_id, owner_id, display_name, "member")
    return user


# ---------------------------------------------------------------------------
# Group 1 — Parser: delimiter detection
# ---------------------------------------------------------------------------

class TestParserDelimiter:

    def test_tsv_detected_by_tab(self):
        raw = "name\trole\tweapon_name\nHallowfall Healer\tHealer\tT8.3 Hallowfall"
        rows = _parse_build_import_csv(raw)
        assert len(rows) == 1
        assert rows[0]["name"] == "Hallowfall Healer"
        assert rows[0]["role"] == "Healer"
        assert rows[0]["weapon_name"] == "T8.3 Hallowfall"

    def test_csv_detected_by_comma(self):
        raw = "name,role,weapon_name\nBedrock Tank,Tank,T8.3 Bedrock Cape"
        rows = _parse_build_import_csv(raw)
        assert len(rows) == 1
        assert rows[0]["name"] == "Bedrock Tank"
        assert rows[0]["weapon_name"] == "T8.3 Bedrock Cape"

    def test_empty_input_returns_empty(self):
        assert _parse_build_import_csv("") == []
        assert _parse_build_import_csv("   \n  ") == []

    def test_multiple_data_rows_returned(self):
        raw = "name,role,weapon_name\nBuild A,Tank,Sword\nBuild B,Healer,Staff"
        rows = _parse_build_import_csv(raw)
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Group 2 — Parser: header detection and alias mapping
# ---------------------------------------------------------------------------

class TestParserHeaderAndAliases:

    def test_canonical_headers_consumed(self):
        raw = "name\trole\tweapon_name\nFrost Staff DPS\tDPS\tT8.3 Frost Staff"
        rows = _parse_build_import_csv(raw)
        assert len(rows) == 1
        assert rows[0]["name"] == "Frost Staff DPS"

    def test_weapon_alias_maps_to_weapon_name(self):
        raw = "name,role,weapon\nHallowfall,Healer,Hallowfall"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["weapon_name"] == "Hallowfall"

    def test_offhand_alias_maps_to_offhand_name(self):
        raw = "name,role,weapon_name,offhand\nX,Tank,Sword,Shield"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["offhand_name"] == "Shield"

    def test_armour_alias_maps_to_armor_name(self):
        raw = "name,role,weapon_name,armour\nX,Tank,Sword,Plate Armor"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["armor_name"] == "Plate Armor"

    def test_doctrine_alias_maps_to_doctrine_role(self):
        raw = "name,role,weapon_name,doctrine\nX,Tank,Sword,Main Tank"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["doctrine_role"] == "Main Tank"

    def test_optional_fields_none_when_absent(self):
        raw = "name,role,weapon_name\nX,Tank,Sword"
        rows = _parse_build_import_csv(raw)
        row = rows[0]
        for f in ("offhand_name", "head_name", "armor_name", "shoes_name",
                  "cape_name", "food_name", "potion_name", "doctrine_role", "notes"):
            assert row[f] is None, f"{f} should be None"

    def test_optional_fields_populated_when_present(self):
        raw = (
            "name,role,weapon_name,food_name,potion_name\n"
            "X,Healer,Staff,Beef Stew,Resistance Potion"
        )
        rows = _parse_build_import_csv(raw)
        assert rows[0]["food_name"] == "Beef Stew"
        assert rows[0]["potion_name"] == "Resistance Potion"
        assert rows[0]["head_name"] is None

    def test_case_insensitive_headers(self):
        raw = "Name,Role,Weapon_Name\nX,Tank,Sword"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["name"] == "X"
        assert rows[0]["weapon_name"] == "Sword"

    def test_unknown_header_column_ignored(self):
        raw = "name,role,weapon_name,tier\nX,Tank,Sword,8"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["name"] == "X"
        assert "tier" not in rows[0]


# ---------------------------------------------------------------------------
# Group 3 — Parser: positional (no header) rows
# ---------------------------------------------------------------------------

class TestParserPositional:

    def test_positional_maps_first_three_columns(self):
        raw = "Hallowfall Healer\tHealer\tT8.3 Hallowfall"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["name"] == "Hallowfall Healer"
        assert rows[0]["role"] == "Healer"
        assert rows[0]["weapon_name"] == "T8.3 Hallowfall"

    def test_positional_extra_columns_ignored(self):
        raw = "Build A\tTank\tSword\textra1\textra2"
        rows = _parse_build_import_csv(raw)
        assert rows[0]["name"] == "Build A"
        assert "extra1" not in rows[0]


# ---------------------------------------------------------------------------
# Group 4 — Parser: blank row handling
# ---------------------------------------------------------------------------

class TestParserBlankRows:

    def test_blank_rows_skipped(self):
        raw = "name,role,weapon_name\nBuild A,Tank,Sword\n\n\nBuild B,Healer,Staff"
        rows = _parse_build_import_csv(raw)
        assert len(rows) == 2

    def test_header_only_returns_empty(self):
        raw = "name,role,weapon_name"
        rows = _parse_build_import_csv(raw)
        assert rows == []


# ---------------------------------------------------------------------------
# Group 5 — Use case: bulk_import_albion_builds success
# ---------------------------------------------------------------------------

class TestBulkImportUseCase:

    def setup_method(self):
        self.owner = make_user("bimport-uc-owner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="bimport-uc")

    def _rows(self, overrides_list=None):
        defaults = [
            {"name": "Hallowfall Healer", "role": "Healer", "weapon_name": "T8.3 Hallowfall"},
            {"name": "Bedrock Tank",       "role": "Tank",   "weapon_name": "T8.3 Bedrock Cape"},
        ]
        if overrides_list:
            return overrides_list
        return defaults

    def test_creates_expected_count(self):
        built = use_cases.bulk_import_albion_builds(
            guild_workspace_id=self.ws["id"],
            actor_user_id=self.owner["id"],
            rows=self._rows(),
        )
        assert len(built) == 2

    def test_builds_appear_in_library(self):
        use_cases.bulk_import_albion_builds(
            guild_workspace_id=self.ws["id"],
            actor_user_id=self.owner["id"],
            rows=self._rows(),
        )
        with database.transaction() as db:
            all_builds = repositories.get_albion_builds(db, self.ws["id"])
        names = [b["name"] for b in all_builds]
        assert "Hallowfall Healer" in names
        assert "Bedrock Tank" in names

    def test_optional_field_stored(self):
        rows = [{"name": "Tank Build", "role": "Tank", "weapon_name": "Sword",
                 "food_name": "Beef Stew", "notes": "Main tank rotation"}]
        built = use_cases.bulk_import_albion_builds(
            guild_workspace_id=self.ws["id"],
            actor_user_id=self.owner["id"],
            rows=rows,
        )
        assert built[0]["food_name"] == "Beef Stew"
        assert built[0]["notes"] == "Main tank rotation"

    def test_duplicate_names_allowed(self):
        rows = [
            {"name": "Same Name", "role": "Tank", "weapon_name": "Sword"},
            {"name": "Same Name", "role": "Healer", "weapon_name": "Staff"},
        ]
        built = use_cases.bulk_import_albion_builds(
            guild_workspace_id=self.ws["id"],
            actor_user_id=self.owner["id"],
            rows=rows,
        )
        assert len(built) == 2

    def test_atomic_on_validation_error_nothing_inserted(self):
        from app.errors import ValidationError
        rows = [
            {"name": "Good Build", "role": "Tank", "weapon_name": "Sword"},
            {"name": "",           "role": "Tank", "weapon_name": "Sword"},  # invalid
        ]
        with pytest.raises(ValidationError):
            use_cases.bulk_import_albion_builds(
                guild_workspace_id=self.ws["id"],
                actor_user_id=self.owner["id"],
                rows=rows,
            )
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, self.ws["id"])
        assert len(builds) == 0  # nothing committed


# ---------------------------------------------------------------------------
# Group 6 — Use case: validation failures
# ---------------------------------------------------------------------------

class TestBulkImportValidation:

    def setup_method(self):
        self.owner = make_user("bimport-val-owner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="bimport-val")

    def _import(self, rows):
        return use_cases.bulk_import_albion_builds(
            guild_workspace_id=self.ws["id"],
            actor_user_id=self.owner["id"],
            rows=rows,
        )

    def test_empty_name_raises(self):
        from app.errors import ValidationError
        with pytest.raises(ValidationError, match="Row 1"):
            self._import([{"name": "", "role": "Tank", "weapon_name": "Sword"}])

    def test_empty_role_raises(self):
        from app.errors import ValidationError
        with pytest.raises(ValidationError, match="Row 1"):
            self._import([{"name": "Tank Build", "role": "", "weapon_name": "Sword"}])

    def test_empty_weapon_name_raises(self):
        from app.errors import ValidationError
        with pytest.raises(ValidationError, match="Row 1"):
            self._import([{"name": "Tank Build", "role": "Tank", "weapon_name": ""}])

    def test_error_message_includes_row_number(self):
        from app.errors import ValidationError
        rows = [
            {"name": "Good",  "role": "Tank", "weapon_name": "Sword"},
            {"name": "Good2", "role": "Tank", "weapon_name": "Sword"},
            {"name": "",      "role": "Tank", "weapon_name": "Sword"},  # row 3
        ]
        with pytest.raises(ValidationError, match="Row 3"):
            self._import(rows)

    def test_empty_rows_list_returns_empty(self):
        built = self._import([])
        assert built == []


# ---------------------------------------------------------------------------
# Group 7 — Use case: permission guard
# ---------------------------------------------------------------------------

class TestBulkImportPermission:

    def setup_method(self):
        self.owner  = make_user("bimport-perm-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-perm")
        self.viewer = _make_viewer(self.ws["id"], self.owner["id"], "bimport-perm-viewer")

    def test_member_raises_permission_denied(self):
        from app.errors import PermissionDenied
        rows = [{"name": "Tank Build", "role": "Tank", "weapon_name": "Sword"}]
        with pytest.raises(PermissionDenied):
            use_cases.bulk_import_albion_builds(
                guild_workspace_id=self.ws["id"],
                actor_user_id=self.viewer["id"],
                rows=rows,
            )


# ---------------------------------------------------------------------------
# Group 8 — Route: GET /builds/import
# ---------------------------------------------------------------------------

class TestGetImportRoute:

    def setup_method(self):
        self.owner  = make_user("bimport-get-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-get")
        self.viewer = _make_viewer(self.ws["id"], self.owner["id"], "bimport-get-viewer")
        self.client = TestClient(app)

    def test_officer_gets_200(self):
        _login(self.client, "bimport-get-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/import")
        assert resp.status_code == 200

    def test_form_present(self):
        _login(self.client, "bimport-get-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/import")
        assert "raw-text" in resp.text or "raw_text" in resp.text

    def test_viewer_gets_403(self):
        _login(self.client, "bimport-get-viewer")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/builds/import",
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_error_param_displayed(self):
        _login(self.client, "bimport-get-owner")
        from urllib.parse import quote_plus
        msg = "Something went wrong"
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/builds/import?error={quote_plus(msg)}"
        )
        assert msg in resp.text


# ---------------------------------------------------------------------------
# Group 9 — Route: POST /builds/import/preview — valid rows
# ---------------------------------------------------------------------------

class TestPreviewValid:

    def setup_method(self):
        self.owner  = make_user("bimport-prv-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-prv")
        self.client = TestClient(app)
        _login(self.client, "bimport-prv-owner")

    def _post_preview(self, raw_text: str):
        return self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/preview",
            data={"raw_text": raw_text},
        )

    def test_preview_renders_200(self):
        raw = "name\trole\tweapon_name\nHallowfall Healer\tHealer\tT8.3 Hallowfall"
        assert self._post_preview(raw).status_code == 200

    def test_preview_shows_parsed_name(self):
        raw = "name,role,weapon_name\nHallowfall Healer,Healer,T8.3 Hallowfall"
        resp = self._post_preview(raw)
        assert "Hallowfall Healer" in resp.text

    def test_preview_shows_success_banner(self):
        raw = "name,role,weapon_name\nBedrock Tank,Tank,Bedrock Cape"
        resp = self._post_preview(raw)
        assert "valid" in resp.text.lower() or "✓" in resp.text

    def test_preview_shows_confirm_button_on_no_errors(self):
        raw = "name,role,weapon_name\nBedrock Tank,Tank,Bedrock Cape"
        resp = self._post_preview(raw)
        assert "Confirm" in resp.text or "confirm" in resp.text.lower()

    def test_preview_no_db_writes(self):
        raw = "name,role,weapon_name\nBedrock Tank,Tank,Bedrock Cape"
        self._post_preview(raw)
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, self.ws["id"])
        assert len(builds) == 0

    def test_preview_shows_optional_columns_when_present(self):
        raw = "name,role,weapon_name,food_name\nX,Tank,Sword,Beef Stew"
        resp = self._post_preview(raw)
        assert "Beef Stew" in resp.text

    def test_preview_empty_paste_shows_error(self):
        resp = self._post_preview("")
        assert "alert-error" in resp.text or "error" in resp.text.lower()


# ---------------------------------------------------------------------------
# Group 10 — Route: POST /builds/import/preview — invalid rows
# ---------------------------------------------------------------------------

class TestPreviewInvalid:

    def setup_method(self):
        self.owner  = make_user("bimport-prv2-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-prv2")
        self.client = TestClient(app)
        _login(self.client, "bimport-prv2-owner")

    def _post_preview(self, raw_text: str):
        return self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/preview",
            data={"raw_text": raw_text},
        )

    def test_invalid_row_shows_error_marker(self):
        raw = "name,role,weapon_name\n,Tank,Sword"  # empty name
        resp = self._post_preview(raw)
        assert "✗" in resp.text or "error" in resp.text.lower()

    def test_invalid_row_no_confirm_button(self):
        raw = "name,role,weapon_name\n,Tank,Sword"
        resp = self._post_preview(raw)
        assert "import/confirm" not in resp.text

    def test_mixed_valid_and_invalid_shows_both(self):
        raw = "name,role,weapon_name\nGood Build,Tank,Sword\n,Healer,Staff"
        resp = self._post_preview(raw)
        assert "Good Build" in resp.text
        assert "✗" in resp.text

    def test_raw_text_preserved_in_textarea(self):
        raw = "name,role,weapon_name\nGood Build,Tank,Sword"
        resp = self._post_preview(raw)
        assert "Good Build" in resp.text


# ---------------------------------------------------------------------------
# Group 11 — Route: POST /builds/import/confirm — success
# ---------------------------------------------------------------------------

class TestConfirmSuccess:

    def setup_method(self):
        self.owner  = make_user("bimport-conf-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-conf")
        self.client = TestClient(app)
        _login(self.client, "bimport-conf-owner")

    def _post_confirm(self, raw_text: str, follow: bool = True):
        return self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/confirm",
            data={"raw_text": raw_text},
            follow_redirects=follow,
        )

    def test_confirm_redirects_to_builds_list(self):
        raw = "name,role,weapon_name\nHallowfall Healer,Healer,T8.3 Hallowfall"
        resp = self._post_confirm(raw, follow=False)
        assert resp.status_code == 303
        assert "/builds" in resp.headers["location"]

    def test_confirm_creates_builds_in_db(self):
        raw = "name,role,weapon_name\nHallowfall Healer,Healer,T8.3 Hallowfall\nBedrock Tank,Tank,Bedrock"
        self._post_confirm(raw)
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, self.ws["id"])
        names = [b["name"] for b in builds]
        assert "Hallowfall Healer" in names
        assert "Bedrock Tank" in names

    def test_confirm_success_flash_message(self):
        raw = "name,role,weapon_name\nHallowfall Healer,Healer,T8.3 Hallowfall"
        resp = self._post_confirm(raw)
        assert "Imported" in resp.text and "build" in resp.text

    def test_confirm_single_build_singular(self):
        raw = "name,role,weapon_name\nOnly One,Tank,Sword"
        resp = self._post_confirm(raw, follow=False)
        loc = resp.headers["location"]
        assert "Imported+1+build." in loc or "Imported 1 build" in loc

    def test_confirm_multiple_builds_plural(self):
        raw = "name,role,weapon_name\nBuild A,Tank,Sword\nBuild B,Healer,Staff"
        resp = self._post_confirm(raw, follow=False)
        loc = resp.headers["location"]
        assert "2+build" in loc or "2 build" in loc


# ---------------------------------------------------------------------------
# Group 12 — Route: POST /builds/import/confirm — guard cases
# ---------------------------------------------------------------------------

class TestConfirmGuards:

    def setup_method(self):
        self.owner  = make_user("bimport-cg-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-cg")
        self.viewer = _make_viewer(self.ws["id"], self.owner["id"], "bimport-cg-viewer")
        self.client = TestClient(app)

    def test_viewer_cannot_confirm(self):
        _login(self.client, "bimport-cg-viewer")
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/confirm",
            data={"raw_text": "name,role,weapon_name\nX,Tank,Sword"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_confirm_empty_raw_text_redirects_with_error(self):
        _login(self.client, "bimport-cg-owner")
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/confirm",
            data={"raw_text": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_confirm_invalid_row_redirects_with_error(self):
        _login(self.client, "bimport-cg-owner")
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/confirm",
            data={"raw_text": "name,role,weapon_name\n,Tank,Sword"},  # empty name
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_confirm_invalid_does_not_insert_any_builds(self):
        _login(self.client, "bimport-cg-owner")
        self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/import/confirm",
            data={"raw_text": "name,role,weapon_name\n,Tank,Sword"},
            follow_redirects=False,
        )
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, self.ws["id"])
        assert len(builds) == 0


# ---------------------------------------------------------------------------
# Group 13 — Template: builds_list.html Import CSV button
# ---------------------------------------------------------------------------

class TestBuildsListImportButton:

    def setup_method(self):
        self.owner  = make_user("bimport-list-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="bimport-list")
        self.viewer = _make_viewer(self.ws["id"], self.owner["id"], "bimport-list-viewer")
        self.client = TestClient(app)

    def test_import_button_visible_for_officer(self):
        _login(self.client, "bimport-list-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "Import CSV" in resp.text

    def test_import_button_links_to_import_page(self):
        _login(self.client, "bimport-list-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "/builds/import" in resp.text

    def test_import_button_hidden_for_viewer(self):
        _login(self.client, "bimport-list-viewer")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "Import CSV" not in resp.text
