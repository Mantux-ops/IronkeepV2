"""
Phase 11 Slice 5 — Alliance Discovery test suite.

Test groups:
  1.  Alliance lookup (rest_client.fetch_albion_alliance normalises the response).
  2.  Guild search exposes View Alliance action when guild has an alliance_id.
  3.  Alliance discovery page renders with alliance data.
  4.  Already-linked guilds show '✓ Already linked' on the alliance page.
  5.  Import button appears only for guilds not yet linked.
  6.  Server is preserved through the discovery URL and stored on import.
  7.  API error on alliance fetch renders a safe error message.
  8.  No DB writes happen during discovery (GET only).
  9.  Existing guild import regression (confirms existing workflow unchanged).
  10. Existing refresh regression.
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
# Shared constants
# ---------------------------------------------------------------------------

_AID = "alliance-uuid-dead-cafe-000000000001"
_GID_A = "alliance-disc-guild-A-dead-cafe0001"
_GID_B = "alliance-disc-guild-B-dead-cafe0002"
_PID_A = "alliance-disc-player-A-dead-cafe001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_alliance_raw(
    alliance_id: str = _AID,
    name: str = "Iron Legion",
    tag: str = "IRON",
    guilds: list[dict] | None = None,
) -> dict:
    """Mimics the raw Albion API /alliances/{id} response dict."""
    if guilds is None:
        guilds = [
            {"Id": _GID_A, "Name": "Iron Keep"},
            {"Id": _GID_B, "Name": "Shadow Force"},
        ]
    return {
        "Id":           alliance_id,
        "AllianceName": name,
        "AllianceTag":  tag,
        "Founded":      "2021-01-15T00:00:00.000Z",
        "NumPlayers":   80,
        "Guilds":       guilds,
    }


def _fake_search_guild(guild_id: str = _GID_A, name: str = "Iron Keep",
                       alliance_id: str = _AID, server: str = "europe") -> dict:
    return {
        "albion_guild_id": guild_id,
        "guild_name":      name,
        "alliance_id":     alliance_id,
        "alliance_name":   "Iron Legion",
        "member_count":    42,
        "extra_json":      "{}",
        "server":          server,
    }


def _insert_linked_guild(ws_id: str, albion_guild_id: str = _GID_A,
                         guild_name: str = "Iron Keep",
                         server: str = "europe") -> None:
    now = _now_iso()
    with database.transaction() as db:
        repositories.upsert_workspace_albion_guild(db, {
            "id":                    str(uuid.uuid4()),
            "guild_workspace_id":    ws_id,
            "albion_guild_id":       albion_guild_id,
            "guild_name":            guild_name,
            "server":                server,
            "alliance_id":           _AID,
            "alliance_name":         "Iron Legion",
            "last_imported_at":      now,
            "created_at":            now,
        })


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"},
                follow_redirects=True)


def _make_officer(ws_id: str, user_id: str) -> None:
    with database.transaction() as db:
        row = repositories.get_workspace_membership(db, ws_id, user_id)
        if row and row["role"] in ("officer", "owner"):
            return
    with database.transaction() as db:
        db.execute(
            "INSERT OR REPLACE INTO workspace_members "
            "(id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?, ?, ?, 'officer', datetime('now'))",
            (str(uuid.uuid4()), ws_id, user_id),
        )


# ---------------------------------------------------------------------------
# Test 1: rest_client.fetch_albion_alliance normalises response
# ---------------------------------------------------------------------------

class TestFetchAlbionAlliance:
    def test_normalises_alliance_metadata(self):
        raw = _fake_alliance_raw()
        with patch.object(rest_client, "_get_from", return_value=raw):
            result = rest_client.fetch_albion_alliance(_AID, server="europe")

        assert result["alliance_id"] == _AID
        assert result["alliance_name"] == "Iron Legion"
        assert result["alliance_tag"] == "IRON"
        assert result["server"] == "europe"
        assert result["num_players"] == 80

    def test_normalises_guild_list(self):
        raw = _fake_alliance_raw()
        with patch.object(rest_client, "_get_from", return_value=raw):
            result = rest_client.fetch_albion_alliance(_AID)

        assert len(result["guilds"]) == 2
        guild_ids = {g["albion_guild_id"] for g in result["guilds"]}
        assert _GID_A in guild_ids
        assert _GID_B in guild_ids

    def test_empty_guild_list_is_safe(self):
        raw = _fake_alliance_raw(guilds=[])
        with patch.object(rest_client, "_get_from", return_value=raw):
            result = rest_client.fetch_albion_alliance(_AID)
        assert result["guilds"] == []

    def test_non_dict_response_raises_albion_api_error(self):
        with patch.object(rest_client, "_get_from", return_value=[]):
            with pytest.raises(rest_client.AlbionApiError):
                rest_client.fetch_albion_alliance(_AID)

    def test_missing_alliance_id_in_response_raises(self):
        raw = {"AllianceName": "Orphan"}  # no Id
        with patch.object(rest_client, "_get_from", return_value=raw):
            with pytest.raises(rest_client.AlbionApiError):
                rest_client.fetch_albion_alliance(_AID)

    def test_server_maps_to_correct_base_url(self):
        # Albion host suffixes do NOT match region names:
        #   Americas = no suffix, Europe = "-ams" (Amsterdam), Asia = "-sgp".
        captured: list[tuple] = []

        def _fake_get_from(base_url: str, path: str, params=None, timeout=None):
            captured.append((base_url, path))
            return _fake_alliance_raw()

        with patch.object(rest_client, "_get_from", side_effect=_fake_get_from):
            rest_client.fetch_albion_alliance(_AID, server="americas")
            rest_client.fetch_albion_alliance(_AID, server="europe")

        assert captured[0][0] == "https://gameinfo.albiononline.com/api/gameinfo"
        assert "gameinfo-ams" in captured[1][0]


# ---------------------------------------------------------------------------
# Test 2: guild search exposes View Alliance action
# ---------------------------------------------------------------------------

class TestViewAllianceButtonInSearchResults:
    def test_view_alliance_link_appears_when_guild_has_alliance(self):
        user = make_user("va-btn-user")
        ws = make_workspace(owner_user_id=user["id"], slug="va-btn-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        search_guild = _fake_search_guild()
        with patch.object(rest_client, "_get_from",
                          return_value=[{
                              "Id": search_guild["albion_guild_id"],
                              "Name": search_guild["guild_name"],
                              "AllianceId": _AID,
                              "AllianceName": "Iron Legion",
                              "MemberCount": 42,
                          }]):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds?q=Iron+Keep&server=europe"
            )

        assert resp.status_code == 200
        assert "View Alliance" in resp.text
        assert f"/alliance/{_AID}" in resp.text

    def test_view_alliance_link_absent_when_no_alliance(self):
        user = make_user("va-no-btn-user")
        ws = make_workspace(owner_user_id=user["id"], slug="va-no-btn-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=[{
                              "Id": _GID_A,
                              "Name": "Lone Wolf",
                              "AllianceId": None,
                              "AllianceName": None,
                              "MemberCount": 5,
                          }]):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds?q=Lone&server=europe"
            )

        assert resp.status_code == 200
        assert "View Alliance" not in resp.text


# ---------------------------------------------------------------------------
# Test 3: alliance discovery page renders
# ---------------------------------------------------------------------------

class TestAllianceDiscoveryPageRenders:
    def test_alliance_page_shows_name_and_tag(self):
        user = make_user("adp-render-user")
        ws = make_workspace(owner_user_id=user["id"], slug="adp-render-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=europe"
            )

        assert resp.status_code == 200
        assert "Iron Legion" in resp.text
        assert "[IRON]" in resp.text

    def test_alliance_page_shows_member_guilds(self):
        user = make_user("adp-guilds-user")
        ws = make_workspace(owner_user_id=user["id"], slug="adp-guilds-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        assert resp.status_code == 200
        assert "Iron Keep" in resp.text
        assert "Shadow Force" in resp.text

    def test_alliance_page_shows_server_label(self):
        user = make_user("adp-server-user")
        ws = make_workspace(owner_user_id=user["id"], slug="adp-server-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=americas"
            )

        assert resp.status_code == 200
        assert "Americas" in resp.text

    def test_alliance_page_shows_discovery_disclaimer(self):
        user = make_user("adp-disc-user")
        ws = make_workspace(owner_user_id=user["id"], slug="adp-disc-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        assert resp.status_code == 200
        assert "Discovery only" in resp.text


# ---------------------------------------------------------------------------
# Test 4: already-linked guilds detected
# ---------------------------------------------------------------------------

class TestAlreadyLinkedGuildsDetected:
    def test_linked_guild_shows_already_linked_badge(self):
        user = make_user("linked-detect-user")
        ws = make_workspace(owner_user_id=user["id"], slug="linked-detect-ws")
        _insert_linked_guild(ws["id"], _GID_A, guild_name="Iron Keep", server="europe")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=europe"
            )

        assert resp.status_code == 200
        assert "Already linked" in resp.text

    def test_unlinked_guild_does_not_show_already_linked(self):
        user = make_user("not-linked-user")
        ws = make_workspace(owner_user_id=user["id"], slug="not-linked-ws")
        # Only _GID_A linked; _GID_B is not
        _insert_linked_guild(ws["id"], _GID_A, server="europe")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw(guilds=[
                              {"Id": _GID_B, "Name": "Shadow Force"},
                          ])):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=europe"
            )

        assert resp.status_code == 200
        assert "Already linked" not in resp.text


# ---------------------------------------------------------------------------
# Test 5: Import button appears only when guild is not yet linked
# ---------------------------------------------------------------------------

class TestImportButtonPresence:
    def test_import_button_present_for_unlinked_guild(self):
        user = make_user("import-btn-user")
        ws = make_workspace(owner_user_id=user["id"], slug="import-btn-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw(guilds=[
                              {"Id": _GID_A, "Name": "Iron Keep"},
                          ])):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        assert resp.status_code == 200
        # Import form targets the confirm route
        assert "import-guilds/confirm" in resp.text

    def test_import_button_absent_for_already_linked_guild(self):
        user = make_user("import-btn-absent-user")
        ws = make_workspace(owner_user_id=user["id"], slug="import-btn-absent-ws")
        _insert_linked_guild(ws["id"], _GID_A, server="europe")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw(guilds=[
                              {"Id": _GID_A, "Name": "Iron Keep"},
                          ])):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=europe"
            )

        assert resp.status_code == 200
        assert "Already linked" in resp.text
        # The confirm form should NOT be present for this guild
        assert "import-guilds/confirm" not in resp.text


# ---------------------------------------------------------------------------
# Test 6: server is preserved through discovery
# ---------------------------------------------------------------------------

class TestServerPreservedInDiscovery:
    def test_alliance_page_passes_server_to_import_forms(self):
        """Import forms on the alliance page must carry the correct server value."""
        user = make_user("srv-disc-user")
        ws = make_workspace(owner_user_id=user["id"], slug="srv-disc-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw(guilds=[
                              {"Id": _GID_A, "Name": "Iron Keep"},
                          ])):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=americas"
            )

        assert resp.status_code == 200
        # Hidden server input in the import form must be americas
        assert 'value="americas"' in resp.text

    def test_unknown_server_falls_back_to_europe(self):
        user = make_user("srv-fb-user")
        ws = make_workspace(owner_user_id=user["id"], slug="srv-fb-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        captured_servers: list[str] = []

        def _fake_get_from(base_url, path, params=None):
            captured_servers.append(base_url)
            return _fake_alliance_raw()

        with patch.object(rest_client, "_get_from", side_effect=_fake_get_from):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
                f"?server=invalid_server"
            )

        assert resp.status_code == 200
        # Must have used the Europe base URL (Amsterdam host = gameinfo-ams).
        assert any("gameinfo-ams.albiononline.com" in u for u in captured_servers)


# ---------------------------------------------------------------------------
# Test 7: API error renders safe message
# ---------------------------------------------------------------------------

class TestAllianceApiError:
    def test_api_error_shows_safe_message_not_traceback(self):
        user = make_user("api-err-user")
        ws = make_workspace(owner_user_id=user["id"], slug="api-err-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          side_effect=rest_client.AlbionApiError("Connection refused")):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        assert resp.status_code == 200
        assert "Could not load alliance data" in resp.text
        assert "Traceback" not in resp.text
        assert "AlbionApiError" not in resp.text

    def test_api_error_does_not_crash_the_route(self):
        user = make_user("api-err2-user")
        ws = make_workspace(owner_user_id=user["id"], slug="api-err2-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with patch.object(rest_client, "_get_from",
                          side_effect=rest_client.AlbionApiError("Timeout")):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test 8: no DB writes during discovery
# ---------------------------------------------------------------------------

class TestNoDbWritesDuringDiscovery:
    def test_alliance_page_does_not_create_guild_rows(self):
        user = make_user("no-write-user")
        ws = make_workspace(owner_user_id=user["id"], slug="no-write-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with database.transaction() as db:
            guilds_before = repositories.list_workspace_albion_guilds(db, ws["id"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        with database.transaction() as db:
            guilds_after = repositories.list_workspace_albion_guilds(db, ws["id"])

        assert len(guilds_before) == len(guilds_after)

    def test_alliance_page_does_not_create_player_rows(self):
        user = make_user("no-write2-user")
        ws = make_workspace(owner_user_id=user["id"], slug="no-write2-ws")

        client = TestClient(app)
        _login(client, user["display_name"])

        with database.transaction() as db:
            players_before = repositories.list_workspace_albion_players(db, ws["id"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        with database.transaction() as db:
            players_after = repositories.list_workspace_albion_players(db, ws["id"])

        assert len(players_before) == len(players_after)


# ---------------------------------------------------------------------------
# Test 9: non-officer is blocked
# ---------------------------------------------------------------------------

class TestNonOfficerBlocked:
    def test_plain_member_gets_403_on_alliance_page(self):
        owner = make_user("alldisc-owner")
        member = make_user("alldisc-member")
        ws = make_workspace(owner_user_id=owner["id"], slug="alldisc-ws")

        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members "
                "(id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?, ?, ?, 'member', datetime('now'))",
                (str(uuid.uuid4()), ws["id"], member["id"]),
            )

        client = TestClient(app)
        _login(client, member["display_name"])

        with patch.object(rest_client, "_get_from",
                          return_value=_fake_alliance_raw()):
            resp = client.get(
                f"/workspaces/{ws['slug']}/members/import-guilds/alliance/{_AID}"
            )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 10: existing regression — import and refresh still work
# ---------------------------------------------------------------------------

class TestExistingRegressionSlice5:
    def test_import_guild_roster_still_works(self):
        from app.application import use_cases

        user = make_user("s5-reg-import-user")
        ws = make_workspace(owner_user_id=user["id"], slug="s5-reg-import-ws")
        _make_officer(ws["id"], user["id"])

        player = {
            "albion_player_id": _PID_A,
            "character_name": "TestWarrior",
            "guild_name": "Iron Keep",
            "guild_id": _GID_A,
        }
        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=[player]):
            result = use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_A,
                guild_name_hint="Iron Keep",
                server="europe",
            )

        assert result["imported"] == 1
        assert result["errors"] == []

    def test_refresh_all_guild_rosters_still_works(self):
        from app.application import use_cases

        user = make_user("s5-reg-refresh-user")
        ws = make_workspace(owner_user_id=user["id"], slug="s5-reg-refresh-ws")
        _make_officer(ws["id"], user["id"])

        with patch.object(rest_client, "fetch_albion_guild_members", return_value=[{
            "albion_player_id": _PID_A,
            "character_name": "TestWarrior",
            "guild_name": "Iron Keep",
            "guild_id": _GID_A,
        }]):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_A,
                guild_name_hint="Iron Keep",
                server="europe",
            )

        with patch.object(rest_client, "fetch_albion_guild_members", return_value=[{
            "albion_player_id": _PID_A,
            "character_name": "TestWarrior",
            "guild_name": "Iron Keep",
            "guild_id": _GID_A,
        }]):
            result = use_cases.refresh_all_guild_rosters(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
            )

        assert result["guilds_refreshed"] == 1
        assert result["active"] >= 1
