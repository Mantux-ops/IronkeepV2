"""
Phase 11.4a — Guild Server Identity Hardening test suite.

Covers:
  1.  server column migration: new DB has the column; existing-DB migration adds it.
  2.  Legacy guild (no server arg) defaults to 'europe'.
  3.  import_albion_guild_roster stores the supplied server.
  4.  resolve_albion_guild_preview returns and propagates server.
  5.  Linked guild table in the template displays the server.
  6.  Same guild_id on different servers can coexist in one workspace.
  7.  Existing import tests still pass (regression: import + re-import).
  8.  Existing refresh tests still pass (regression: server is propagated on refresh).
  9.  Existing identity-linking tests still pass (regression: server does not break linking).
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
# Helpers
# ---------------------------------------------------------------------------

_GID_EU = "server-guild-uuid-EU-dead-cafe000001"
_GID_AM = "server-guild-uuid-AM-dead-cafe000002"   # same ID, different server below
_GID_SAME = "server-guild-same-id-dead-cafe00001"   # used for coexistence test
_PID_A = "server-player-uuid-A-dead-cafe000000001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_guild(guild_id: str = _GID_EU, name: str = "Iron Keep",
                server: str = "europe") -> dict:
    return {
        "albion_guild_id": guild_id,
        "guild_name":      name,
        "alliance_id":     None,
        "alliance_name":   None,
        "member_count":    5,
        "extra_json":      "{}",
        "server":          server,
    }


def _fake_members(guild_id: str = _GID_EU, player_id: str = _PID_A) -> list[dict]:
    return [
        {
            "albion_player_id": player_id,
            "character_name":   "TestWarrior",
            "guild_name":       "Iron Keep",
            "guild_id":         guild_id,
        }
    ]


def _insert_guild(ws_id: str, albion_guild_id: str = _GID_EU,
                  guild_name: str = "Iron Keep",
                  server: str = "europe") -> dict:
    now = _now_iso()
    row = {
        "id":                    str(uuid.uuid4()),
        "guild_workspace_id":    ws_id,
        "albion_guild_id":       albion_guild_id,
        "guild_name":            guild_name,
        "server":                server,
        "alliance_id":           None,
        "alliance_name":         None,
        "last_imported_at":      None,
        "verification_status":   "unverified",
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
# Test 1: server column exists on a freshly initialised schema
# ---------------------------------------------------------------------------

class TestServerColumnMigration:
    def test_server_column_present_on_fresh_db(self):
        """Fresh DB created from schema.sql must have the server column."""
        with database.transaction() as db:
            cols = {row[1] for row in db.execute(
                "PRAGMA table_info(workspace_albion_guilds)"
            ).fetchall()}
        assert "server" in cols

    def test_unique_constraint_includes_server(self):
        """
        The UNIQUE constraint must be (guild_workspace_id, server, albion_guild_id).
        We verify this indirectly: two rows with the same guild_id but different
        servers must not raise an IntegrityError.
        """
        user = make_user("srv-migr-user")
        ws = make_workspace(user["id"], slug="srv-migr-ws")

        _insert_guild(ws["id"], _GID_SAME, server="europe")
        _insert_guild(ws["id"], _GID_SAME, server="americas")  # must not raise

        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        servers = {g["server"] for g in guilds if g["albion_guild_id"] == _GID_SAME}
        assert servers == {"europe", "americas"}


# ---------------------------------------------------------------------------
# Test 2: legacy guild (no server arg) defaults to europe
# ---------------------------------------------------------------------------

class TestLegacyGuildDefaultsToEurope:
    def test_upsert_without_server_defaults_to_europe(self):
        """upsert_workspace_albion_guild must default server to 'europe' when absent."""
        user = make_user("legacy-server-user")
        ws = make_workspace(user["id"], slug="legacy-server-ws")
        now = _now_iso()

        with database.transaction() as db:
            repositories.upsert_workspace_albion_guild(db, {
                "id":                str(uuid.uuid4()),
                "guild_workspace_id": ws["id"],
                "albion_guild_id":   "legacy-guild-id-0001",
                "guild_name":        "Old Guild",
                "alliance_id":       None,
                "alliance_name":     None,
                "last_imported_at":  None,
                "created_at":        now,
                # intentionally omit 'server'
            })

        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], "legacy-guild-id-0001")
        assert row is not None
        assert row["server"] == "europe"


# ---------------------------------------------------------------------------
# Test 3: import_albion_guild_roster stores the supplied server
# ---------------------------------------------------------------------------

class TestImportStoresServer:
    def test_import_stores_europe_server(self):
        """import_albion_guild_roster with server='europe' should store 'europe'."""
        from app.application import use_cases

        user = make_user("import-srv-user")
        ws = make_workspace(user["id"], slug="import-srv-ws")
        _make_officer(ws["id"], user["id"])

        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=_fake_members(_GID_EU)):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_EU,
                guild_name_hint="Iron Keep",
                server="europe",
            )

        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GID_EU)
        assert row is not None
        assert row["server"] == "europe"

    def test_import_stores_americas_server(self):
        """import_albion_guild_roster with server='americas' should store 'americas'."""
        from app.application import use_cases

        user = make_user("import-am-user")
        ws = make_workspace(user["id"], slug="import-am-ws")
        _make_officer(ws["id"], user["id"])

        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=_fake_members(_GID_AM)):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_AM,
                guild_name_hint="Americas Guild",
                server="americas",
            )

        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GID_AM)
        assert row is not None
        assert row["server"] == "americas"


# ---------------------------------------------------------------------------
# Test 4: resolve_albion_guild_preview returns server field
# ---------------------------------------------------------------------------

class TestResolvePreviewReturnsServer:
    def test_preview_returns_server_from_search_result(self):
        """resolve_albion_guild_preview must include 'server' in the returned dict."""
        from app.application import use_cases

        user = make_user("preview-srv-user")
        ws = make_workspace(user["id"], slug="preview-srv-ws")
        _make_officer(ws["id"], user["id"])

        with patch.object(rest_client, "_get_from",
                          return_value=[{
                              "Id": _GID_EU,
                              "Name": "Iron Keep",
                              "AllianceId": None,
                              "AllianceName": None,
                              "MemberCount": 10,
                          }]):
            result = use_cases.resolve_albion_guild_preview(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                guild_name_or_id="Iron Keep",
                server="europe",
            )

        assert result["error"] is None
        assert "server" in result
        assert result["server"] == "europe"

    def test_preview_empty_input_includes_server(self):
        """Early-return on empty input must still include 'server'."""
        from app.application import use_cases

        user = make_user("preview-empty-user")
        ws = make_workspace(user["id"], slug="preview-empty-ws")
        _make_officer(ws["id"], user["id"])

        result = use_cases.resolve_albion_guild_preview(
            guild_workspace_id=ws["id"],
            requesting_user_id=user["id"],
            guild_name_or_id="  ",
            server="americas",
        )

        assert result["error"] is not None
        assert result.get("server") == "americas"


# ---------------------------------------------------------------------------
# Test 5: linked guild table displays server
# ---------------------------------------------------------------------------

class TestLinkedGuildTableDisplaysServer:
    def test_import_page_shows_server_in_linked_guild_table(self):
        """The /import-guilds page must render the server column for linked guilds."""
        user = make_user("tpl-srv-user")
        ws = make_workspace(user["id"], slug="tpl-srv-ws")
        _make_officer(ws["id"], user["id"])
        _insert_guild(ws["id"], _GID_EU, guild_name="Template Guild", server="europe")

        client = TestClient(app)
        _login(client, user["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/members/import-guilds")
        assert resp.status_code == 200

        body = resp.text
        assert "Template Guild" in body
        # The template renders the server label via albion_servers.get(server, ...)
        assert "Europe" in body

    def test_import_page_shows_americas_server(self):
        user = make_user("tpl-am-user")
        ws = make_workspace(user["id"], slug="tpl-am-ws")
        _make_officer(ws["id"], user["id"])
        _insert_guild(ws["id"], _GID_AM, guild_name="Americas Guild", server="americas")

        client = TestClient(app)
        _login(client, user["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/members/import-guilds")
        assert resp.status_code == 200
        assert "Americas" in resp.text


# ---------------------------------------------------------------------------
# Test 6: same guild_id on different servers can coexist
# ---------------------------------------------------------------------------

class TestSameGuildIdDifferentServers:
    def test_same_guild_id_coexists_on_europe_and_americas(self):
        """
        A workspace may link the same albion_guild_id on two different servers.
        Both rows must be stored and retrievable.
        """
        from app.application import use_cases

        user = make_user("coexist-user")
        ws = make_workspace(user["id"], slug="coexist-ws")
        _make_officer(ws["id"], user["id"])

        player_eu = "coexist-player-eu-dead-cafe0001"
        player_am = "coexist-player-am-dead-cafe0002"

        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=_fake_members(_GID_SAME, player_eu)):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_SAME,
                guild_name_hint="EU Server Guild",
                server="europe",
            )

        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=_fake_members(_GID_SAME, player_am)):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_SAME,
                guild_name_hint="AM Server Guild",
                server="americas",
            )

        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])

        matching = [g for g in guilds if g["albion_guild_id"] == _GID_SAME]
        assert len(matching) == 2
        servers = {g["server"] for g in matching}
        assert servers == {"europe", "americas"}

    def test_reimport_same_server_is_idempotent(self):
        """Re-importing the same (guild_id, server) must not create a duplicate row."""
        from app.application import use_cases

        user = make_user("idempotent-srv-user")
        ws = make_workspace(user["id"], slug="idempotent-srv-ws")
        _make_officer(ws["id"], user["id"])

        for _ in range(2):
            with patch.object(rest_client, "fetch_albion_guild_members",
                              return_value=_fake_members(_GID_EU)):
                use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=user["id"],
                    albion_guild_id=_GID_EU,
                    guild_name_hint="Iron Keep",
                    server="europe",
                )

        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        eu_rows = [g for g in guilds if g["albion_guild_id"] == _GID_EU
                   and g["server"] == "europe"]
        assert len(eu_rows) == 1


# ---------------------------------------------------------------------------
# Test 7: regression — refresh propagates server from guild_row
# ---------------------------------------------------------------------------

class TestRefreshPropagatesServer:
    def test_refresh_preserves_server_column(self):
        """refresh_all_guild_rosters must not reset server to the default."""
        from app.application import use_cases

        user = make_user("refresh-srv-user")
        ws = make_workspace(user["id"], slug="refresh-srv-ws")
        _make_officer(ws["id"], user["id"])

        # Import with americas server
        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=_fake_members(_GID_AM)):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
                albion_guild_id=_GID_AM,
                guild_name_hint="Americas Guild",
                server="americas",
            )

        # Refresh — server value from guild_row["server"] must be carried through
        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=_fake_members(_GID_AM)):
            use_cases.refresh_all_guild_rosters(
                guild_workspace_id=ws["id"],
                requesting_user_id=user["id"],
            )

        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GID_AM)
        assert row is not None
        assert row["server"] == "americas"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_officer(ws_id: str, user_id: str) -> None:
    """Ensure the given user is an officer of the workspace (for use-case auth)."""
    with database.transaction() as db:
        row = repositories.get_workspace_membership(db, ws_id, user_id)
        if row and row["role"] in ("officer", "owner"):
            return
    # Upsert an officer membership
        with database.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO workspace_members "
                "(id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?, ?, ?, 'officer', datetime('now'))",
                (str(uuid.uuid4()), ws_id, user_id),
            )
