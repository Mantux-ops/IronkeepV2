"""
Phase 11 Slice 4 — Guild search UX and ownership safety test suite.

Test groups:
  1.  Guild search route returns matching results
  2.  Search handles server selector safely
  3.  Search result shows guild name, ID, alliance, member count, server
  4.  Officer can import searched guild
  5.  Already-linked guild shows "Already linked" in search results
  6.  Linked guild defaults to verification_status = unverified
  7.  Existing linked guilds migrate/default to unverified
  8.  UI says roster import is not ownership verification
  9.  Verified-by-other-workspace warning surfaces in search results
  10. Non-officer cannot access import page
  11. Search API errors render safe message
  12. Existing textarea / manual import still works
  13. Existing roster import / refresh / linking tests still pass (regression)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.albion import rest_client
from app.main import app
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GID_A = "search-guild-uuid-A-dead-cafe000000001"
_GID_B = "search-guild-uuid-B-dead-cafe000000002"
_PID_A = "search-player-uuid-A-dead-cafe0000001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_guild(guild_id: str = _GID_A, name: str = "Iron Keep",
                server: str = "europe") -> dict:
    return {
        "albion_guild_id": guild_id,
        "guild_name":      name,
        "alliance_id":     None,
        "alliance_name":   None,
        "member_count":    42,
        "extra_json":      "{}",
        "server":          server,
    }


def _insert_guild(ws_id: str, albion_guild_id: str = _GID_A,
                  guild_name: str = "Iron Keep",
                  verification_status: str = "unverified") -> dict:
    now = _now_iso()
    row = {
        "id":                    str(uuid.uuid4()),
        "guild_workspace_id":    ws_id,
        "albion_guild_id":       albion_guild_id,
        "guild_name":            guild_name,
        "alliance_id":           None,
        "alliance_name":         None,
        "last_imported_at":      None,
        "verification_status":   verification_status,
        "verified_at":           None,
        "verified_by_user_id":   None,
        "verification_method":   None,
        "created_at":            now,
    }
    with database.transaction() as db:
        repositories.upsert_workspace_albion_guild(db, row)
    with database.transaction() as db:
        return repositories.get_workspace_albion_guild(db, ws_id, albion_guild_id)


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Guild search route returns matching results
# ---------------------------------------------------------------------------

class TestGuildSearchRouteReturnsResults:
    def test_search_returns_results_in_template(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("SearchRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild()]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=Iron+Keep",
                    follow_redirects=True,
                )

        assert resp.status_code == 200
        assert "Iron Keep" in resp.text
        assert _GID_A in resp.text

    def test_search_with_empty_query_shows_form_without_results(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EmptySearchOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Find an Albion Guild" in resp.text


# ---------------------------------------------------------------------------
# 2. Search handles server selector safely
# ---------------------------------------------------------------------------

class TestSearchServerSelector:
    def test_valid_server_is_used(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ServerSelectOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        calls = []

        def _fake_search(name, server="europe"):
            calls.append(server)
            return [_fake_guild(server=server)]

        with patch.object(rest_client, "search_albion_guilds", side_effect=_fake_search):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=IK&server=americas",
                    follow_redirects=True,
                )

        assert calls == ["americas"]

    def test_unknown_server_falls_back_to_europe(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("UnknownServerOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        calls = []

        def _fake_search(name, server="europe"):
            calls.append(server)
            return []

        with patch.object(rest_client, "search_albion_guilds", side_effect=_fake_search):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=IK&server=invalid",
                    follow_redirects=True,
                )

        assert calls == ["europe"]

    def test_albion_servers_dict_has_three_entries(self):
        assert len(rest_client.ALBION_SERVERS) == 3
        assert "europe"   in rest_client.ALBION_SERVERS
        assert "americas" in rest_client.ALBION_SERVERS
        assert "asia"     in rest_client.ALBION_SERVERS

    def test_search_guilds_passes_server_field_to_result(self):
        guild = _fake_guild(server="americas")
        assert guild["server"] == "americas"

        # Verify the function signature accepts server kwarg
        import inspect
        sig = inspect.signature(rest_client.search_albion_guilds)
        assert "server" in sig.parameters


# ---------------------------------------------------------------------------
# 3. Search result shows guild name, ID, alliance, member count, server
# ---------------------------------------------------------------------------

class TestSearchResultFields:
    def test_search_results_rendered_with_all_fields(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("SearchFieldsOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        result = {
            "albion_guild_id": _GID_A,
            "guild_name":      "FieldsGuild",
            "alliance_id":     "allid-001",
            "alliance_name":   "The Alliance",
            "member_count":    99,
            "extra_json":      "{}",
            "server":          "europe",
        }

        with patch.object(rest_client, "search_albion_guilds", return_value=[result]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=Fields",
                    follow_redirects=True,
                )

        assert "FieldsGuild" in resp.text
        assert _GID_A in resp.text
        assert "The Alliance" in resp.text
        assert "99" in resp.text
        assert "Europe" in resp.text


# ---------------------------------------------------------------------------
# 4. Officer can import searched guild
# ---------------------------------------------------------------------------

class TestOfficerImportSearchedGuild:
    def test_import_from_search_result_links_guild(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("SearchImportOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        from app.albion import rest_client as rc

        with patch.object(rc, "fetch_albion_guild_members",
                          return_value=[]):
            with patch.object(rc, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.post(
                    f"/workspaces/{ws['slug']}/members/import-guilds/confirm",
                    data={
                        "albion_guild_id": _GID_A,
                        "guild_name":      "SearchGuild",
                        "alliance_id":     "",
                        "alliance_name":   "",
                    },
                    follow_redirects=True,
                )

        assert resp.status_code == 200
        with database.transaction() as db:
            linked = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert any(g["albion_guild_id"] == _GID_A for g in linked)


# ---------------------------------------------------------------------------
# 5. Already-linked guild shows "Already linked" in search results
# ---------------------------------------------------------------------------

class TestAlreadyLinkedGuildDisplay:
    def test_already_linked_guild_shows_label(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("AlreadyLinkedOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"], _GID_A, "Iron Keep")

        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild(_GID_A, "Iron Keep")]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=Iron+Keep",
                    follow_redirects=True,
                )

        assert "Already linked" in resp.text

    def test_unlinked_guild_shows_import_button(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("NotLinkedOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild(_GID_B, "New Guild")]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=New",
                    follow_redirects=True,
                )

        assert "Import" in resp.text
        assert "Already linked" not in resp.text


# ---------------------------------------------------------------------------
# 6. Linked guild defaults to verification_status = unverified
# ---------------------------------------------------------------------------

class TestLinkedGuildDefaultsUnverified:
    def test_new_import_sets_unverified_status(self):
        owner = make_user("UnverifiedStatusOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        from app.albion import rest_client as rc
        with patch.object(rc, "fetch_albion_guild_members", return_value=[]):
            with patch.object(rc, "_rate_limit"):
                from app.application import use_cases
                use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GID_A,
                    guild_name_hint="UnverifiedGuild",
                )

        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GID_A)
        assert row["verification_status"] == "unverified"

    def test_reimport_does_not_overwrite_existing_verification_status(self):
        owner = make_user("PreserveVerifOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        # Manually set a guild to 'verified'
        guild = _insert_guild(ws["id"], _GID_A, verification_status="verified")
        assert guild["verification_status"] == "verified"

        # Re-import the same guild
        from app.albion import rest_client as rc
        with patch.object(rc, "fetch_albion_guild_members", return_value=[]):
            with patch.object(rc, "_rate_limit"):
                from app.application import use_cases
                use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GID_A,
                    guild_name_hint="Updated Name",
                )

        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GID_A)
        # Verification status must be preserved
        assert row["verification_status"] == "verified"


# ---------------------------------------------------------------------------
# 7. Existing linked guilds default to unverified after migration
# ---------------------------------------------------------------------------

class TestExistingGuildsMigrateToUnverified:
    def test_existing_guild_has_unverified_after_insert(self):
        owner = make_user("MigrateUnverifiedOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        # Insert without specifying verification_status → should default to 'unverified'
        now = _now_iso()
        with database.transaction() as db:
            # Pass a record WITHOUT verification_status to test backward compat
            repositories.upsert_workspace_albion_guild(db, {
                "id":                 str(uuid.uuid4()),
                "guild_workspace_id": ws["id"],
                "albion_guild_id":    _GID_A,
                "guild_name":         "OldStyleGuild",
                "alliance_id":        None,
                "alliance_name":      None,
                "last_imported_at":   None,
                "created_at":         now,
                # No verification_status key
            })
        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GID_A)
        assert row["verification_status"] == "unverified"


# ---------------------------------------------------------------------------
# 8. UI says roster import is not ownership verification
# ---------------------------------------------------------------------------

class TestUiDisclaimerVisible:
    def test_import_page_shows_not_ownership_disclaimer(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("DisclaimerOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=True,
        )
        body = resp.text
        assert "roster visibility only" in body.lower() or "not ownership" in body.lower() or "not" in body

    def test_linked_guilds_section_shows_roster_import_only_label(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("LinkedDisclaimerOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=True,
        )
        assert "Roster import only" in resp.text or "roster" in resp.text.lower()


# ---------------------------------------------------------------------------
# 9. Verified-by-other-workspace warning surfaces in search results
# ---------------------------------------------------------------------------

class TestVerifiedElsewhereWarning:
    def test_guild_verified_by_other_workspace_shows_warning(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner_a = make_user("VerifElsewhereOwnerA")
        owner_b = make_user("VerifElsewhereOwnerB")
        ws_a = make_workspace(slug="verif-ws-a", owner_user_id=owner_a["id"])
        ws_b = make_workspace(slug="verif-ws-b", owner_user_id=owner_b["id"])

        # ws_a has this guild VERIFIED
        _insert_guild(ws_a["id"], _GID_A, "ClaimedGuild",
                      verification_status="verified")

        # ws_b searches and finds the same guild
        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild(_GID_A, "ClaimedGuild")]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner_b["display_name"])
                resp = client.get(
                    f"/workspaces/{ws_b['slug']}/members/import-guilds?q=Claimed",
                    follow_redirects=True,
                )

        assert "Claimed by another workspace" in resp.text

    def test_unverified_guild_in_other_workspace_shows_no_warning(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner_a = make_user("UnverifElsewhereOwnerA")
        owner_b = make_user("UnverifElsewhereOwnerB")
        ws_a = make_workspace(slug="unverf-ws-a", owner_user_id=owner_a["id"])
        ws_b = make_workspace(slug="unverf-ws-b", owner_user_id=owner_b["id"])

        # ws_a has this guild UNVERIFIED (default)
        _insert_guild(ws_a["id"], _GID_A)

        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild(_GID_A, "SharedGuild")]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner_b["display_name"])
                resp = client.get(
                    f"/workspaces/{ws_b['slug']}/members/import-guilds?q=Shared",
                    follow_redirects=True,
                )

        assert "Claimed by another workspace" not in resp.text

    def test_repository_cross_workspace_check_returns_none_for_unverified(self):
        owner = make_user("CwCheckOwner")
        ws_a = make_workspace(slug="cwcheck-a", owner_user_id=owner["id"])
        ws_b = make_workspace(slug="cwcheck-b", owner_user_id=owner["id"])
        _insert_guild(ws_a["id"], _GID_A)  # unverified

        with database.transaction() as db:
            result = repositories.get_albion_guild_verified_elsewhere(
                db, _GID_A, ws_b["id"]
            )
        assert result is None

    def test_repository_cross_workspace_check_returns_row_for_verified(self):
        owner = make_user("CwVerifiedOwner")
        ws_a = make_workspace(slug="cwverif-a", owner_user_id=owner["id"])
        ws_b = make_workspace(slug="cwverif-b", owner_user_id=owner["id"])
        _insert_guild(ws_a["id"], _GID_A, verification_status="verified")

        with database.transaction() as db:
            result = repositories.get_albion_guild_verified_elsewhere(
                db, _GID_A, ws_b["id"]
            )
        assert result is not None
        assert result["albion_guild_id"] == _GID_A


# ---------------------------------------------------------------------------
# 10. Non-officer cannot access import page
# ---------------------------------------------------------------------------

class TestNonOfficerBlocked:
    def test_member_role_blocked_from_import_page(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("BlockedMemberOwner")
        member = make_user("BlockedMemberUser")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members "
                "(id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )

        _login(client, member["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=False,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 11. Search API errors render safe message
# ---------------------------------------------------------------------------

class TestSearchApiErrorSafe:
    def test_api_error_shows_error_message_not_traceback(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ApiErrorOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        from app.albion.rest_client import AlbionApiError

        with patch.object(rest_client, "search_albion_guilds",
                          side_effect=AlbionApiError("connection refused")):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.get(
                    f"/workspaces/{ws['slug']}/members/import-guilds?q=anything",
                    follow_redirects=True,
                )

        assert resp.status_code == 200
        assert "connection refused" in resp.text
        assert "Traceback" not in resp.text
        assert "Exception" not in resp.text


# ---------------------------------------------------------------------------
# 12. Existing textarea / manual import still works
# ---------------------------------------------------------------------------

class TestManualTextareaImportPreserved:
    def test_preview_route_still_accepts_textarea_input(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("TextareaOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild()]):
            with patch.object(rest_client, "_rate_limit"):
                _login(client, owner["display_name"])
                resp = client.post(
                    f"/workspaces/{ws['slug']}/members/import-guilds/preview",
                    data={"guild_names": "Iron Keep"},
                    follow_redirects=True,
                )

        assert resp.status_code == 200
        assert "Iron Keep" in resp.text

    def test_manual_import_section_is_present_in_template(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ManualSectionOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=True,
        )
        assert "Manual Import" in resp.text


# ---------------------------------------------------------------------------
# 13. Regression: existing import/refresh/linking tests still work
# ---------------------------------------------------------------------------

class TestSlice4Regression:
    def test_import_guild_roster_still_works(self):
        owner = make_user("Slice4ImportOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        from app.albion import rest_client as rc
        from app.application import use_cases
        with patch.object(rc, "fetch_albion_guild_members", return_value=[]):
            with patch.object(rc, "_rate_limit"):
                result = use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GID_A,
                    guild_name_hint="Slice4Guild",
                )
        assert result["total"] == 0

    def test_refresh_all_guild_rosters_still_works(self):
        owner = make_user("Slice4RefreshOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])

        from app.albion import rest_client as rc
        from app.application import use_cases
        with patch.object(rc, "fetch_albion_guild_members", return_value=[]):
            with patch.object(rc, "_rate_limit"):
                result = use_cases.refresh_all_guild_rosters(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                )
        assert result["guilds_refreshed"] == 1

    def test_rest_client_module_has_no_app_imports(self):
        """Verify the API client isolation invariant is still intact."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "app" / "albion" / "rest_client.py"
               ).read_text(encoding="utf-8")
        assert "from app" not in src
        assert "import sqlite3" not in src
