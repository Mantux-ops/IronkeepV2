"""
Phase 11 Slice 1 — Albion Guild Roster Import test suite.

Test groups:
  1.  REST client: guild search and guild members endpoints
  2.  REST client module boundary (no DB/domain/Discord imports)
  3.  Schema / migration: new tables exist with correct structure
  4.  Repository: workspace_albion_guilds CRUD
  5.  Repository: workspace_albion_players upsert / idempotency
  6.  Repository: player user_id preservation on re-import
  7.  Use case: resolve_albion_guild_preview (happy path + errors)
  8.  Use case: import_albion_guild_roster (single guild)
  9.  Use case: import two guilds — player overlap not duplicated
  10. Use case: re-import same guild is idempotent
  11. Use case: existing user link preserved on re-import
  12. Use case: non-officer cannot import
  13. Use case: unknown guild (API error) raises ValidationError safely
  14. Use case: empty guild_id raises ValidationError
  15. Use case: import stores audit event
  16. Use case: import updates last_imported_at
  17. Use case: manual workspace members / users are unaffected
  18. Routes: GET /members/import-guilds renders form (officer only)
  19. Routes: POST /preview returns preview table
  20. Routes: POST /confirm imports and redirects with success
  21. Routes: non-officer cannot access import routes
  22. Routes: members page shows imported players section
  23. Use case: partial failure — successful guild unaffected (slice 1 is guild-atomic)
  24. Use case: Albion API timeout produces safe ValidationError
  25. Existing albion identity claim tests still pass (regression guard)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import NotFoundError, PermissionDenied, ValidationError
from app.main import app
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GUILD_ID_A = "guild-uuid-0001-dead-beef-cafe00000001"
_GUILD_ID_B = "guild-uuid-0002-dead-beef-cafe00000002"
_PLAYER_ID_1 = "player-uuid-001-dead-beef-cafe000000001"
_PLAYER_ID_2 = "player-uuid-002-dead-beef-cafe000000002"
_PLAYER_ID_3 = "player-uuid-003-dead-beef-cafe000000003"
_PLAYER_ID_SHARED = "player-uuid-shared-cafe000000000001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_guild(guild_id: str = _GUILD_ID_A, name: str = "Iron Keep",
                alliance_id: str | None = None,
                alliance_name: str | None = None,
                member_count: int = 50) -> dict:
    return {
        "albion_guild_id": guild_id,
        "guild_name":      name,
        "alliance_id":     alliance_id,
        "alliance_name":   alliance_name,
        "member_count":    member_count,
        "extra_json":      "{}",
    }


def _fake_member(player_id: str, name: str, guild_id: str = _GUILD_ID_A,
                 guild_name: str = "Iron Keep") -> dict:
    return {
        "albion_player_id": player_id,
        "character_name":   name,
        "guild_id":         guild_id,
        "guild_name":       guild_name,
        "kill_fame":        1000,
        "death_fame":       100,
        "extra_json":       "{}",
    }


def _add_officer(ws_id: str, user_id: str) -> None:
    with database.transaction() as db:
        db.execute(
            "UPDATE workspace_members SET role='officer' WHERE guild_workspace_id=? AND user_id=?",
            (ws_id, user_id),
        )


def _add_member(ws_id: str, user_id: str) -> None:
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,'member',?)",
            (str(uuid.uuid4()), ws_id, user_id, _now_iso()),
        )


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _do_import(ws_id: str, user_id: str, guild_id: str = _GUILD_ID_A,
               members: list | None = None) -> dict:
    """Run import_albion_guild_roster with a mocked API."""
    if members is None:
        members = [
            _fake_member(_PLAYER_ID_1, "Kage"),
            _fake_member(_PLAYER_ID_2, "Vex"),
        ]
    from app.albion import rest_client
    with patch.object(rest_client, "fetch_albion_guild_members", return_value=members):
        with patch.object(rest_client, "_rate_limit"):
            return use_cases.import_albion_guild_roster(
                guild_workspace_id=ws_id,
                requesting_user_id=user_id,
                albion_guild_id=guild_id,
                guild_name_hint="Iron Keep",
            )


# ---------------------------------------------------------------------------
# 1. REST client: guild search and guild members endpoints
# ---------------------------------------------------------------------------

class TestGuildRestClient:
    def test_search_returns_normalised_list(self):
        raw = [
            {"Id": _GUILD_ID_A, "Name": "Iron Keep",
             "AllianceId": "ally-001", "AllianceName": "Iron Alliance",
             "MemberCount": 80},
        ]
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=raw):
            with patch.object(rest_client, "_rate_limit"):
                results = rest_client.search_albion_guilds("Iron Keep")
        assert len(results) == 1
        assert results[0]["albion_guild_id"] == _GUILD_ID_A
        assert results[0]["guild_name"] == "Iron Keep"
        assert results[0]["alliance_name"] == "Iron Alliance"
        assert results[0]["member_count"] == 80

    def test_search_empty_list_returns_empty(self):
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                results = rest_client.search_albion_guilds("Unknown")
        assert results == []

    def test_search_non_list_response_returns_empty(self):
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value={"error": "bad"}):
            with patch.object(rest_client, "_rate_limit"):
                results = rest_client.search_albion_guilds("x")
        assert results == []

    def test_fetch_guild_members_returns_normalised_list(self):
        raw = [
            {"Id": _PLAYER_ID_1, "Name": "Kage", "GuildId": _GUILD_ID_A,
             "GuildName": "Iron Keep", "KillFame": 500, "DeathFame": 20},
            {"Id": _PLAYER_ID_2, "Name": "Vex",  "GuildId": _GUILD_ID_A,
             "GuildName": "Iron Keep", "KillFame": 300, "DeathFame": 10},
        ]
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=raw):
            with patch.object(rest_client, "_rate_limit"):
                members = rest_client.fetch_albion_guild_members(_GUILD_ID_A)
        assert len(members) == 2
        ids = {m["albion_player_id"] for m in members}
        assert ids == {_PLAYER_ID_1, _PLAYER_ID_2}

    def test_fetch_guild_members_empty_guild(self):
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                members = rest_client.fetch_albion_guild_members(_GUILD_ID_A)
        assert members == []

    def test_fetch_guild_members_non_list_raises(self):
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value={"error": "bad"}):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(rest_client.AlbionApiError):
                    rest_client.fetch_albion_guild_members(_GUILD_ID_A)

    def test_search_timeout_raises_albion_api_error(self):
        import httpx
        from app.albion import rest_client
        with patch.object(rest_client, "_rate_limit"):
            with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
                with pytest.raises(rest_client.AlbionApiError):
                    rest_client.search_albion_guilds("Iron Keep")

    def test_fetch_members_timeout_raises_albion_api_error(self):
        import httpx
        from app.albion import rest_client
        with patch.object(rest_client, "_rate_limit"):
            with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
                with pytest.raises(rest_client.AlbionApiError):
                    rest_client.fetch_albion_guild_members(_GUILD_ID_A)


# ---------------------------------------------------------------------------
# 2. REST client module boundary
# ---------------------------------------------------------------------------

class TestGuildRestClientModuleBoundary:
    def _src(self) -> str:
        from pathlib import Path
        return (
            Path(__file__).parent.parent / "app" / "albion" / "rest_client.py"
        ).read_text(encoding="utf-8")

    def test_no_sqlite3_import(self):
        assert "import sqlite3" not in self._src()

    def test_no_discord_import(self):
        assert "import discord" not in self._src()
        assert "from app.discord" not in self._src()

    def test_no_domain_import(self):
        assert "from app.domain" not in self._src()
        assert "from app import" not in self._src()


# ---------------------------------------------------------------------------
# 3. Schema / migration: new tables exist
# ---------------------------------------------------------------------------

class TestSchemaGuildRoster:
    def test_workspace_albion_guilds_table_exists(self):
        with database.transaction() as db:
            info = db.execute("PRAGMA table_info(workspace_albion_guilds)").fetchall()
        col_names = {row["name"] for row in info}
        assert col_names >= {
            "id", "guild_workspace_id", "albion_guild_id", "guild_name",
            "alliance_id", "alliance_name", "last_imported_at", "created_at",
        }

    def test_workspace_albion_players_table_exists(self):
        with database.transaction() as db:
            info = db.execute("PRAGMA table_info(workspace_albion_players)").fetchall()
        col_names = {row["name"] for row in info}
        assert col_names >= {
            "id", "guild_workspace_id", "albion_player_id", "character_name",
            "user_id", "source_guild_id", "last_seen_in_guild_at",
            "created_at", "updated_at",
        }

    def test_workspace_albion_guilds_unique_constraint(self):
        import sqlite3
        owner = make_user("SchemaGuildOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        now = _now_iso()
        row = {
            "id": str(uuid.uuid4()), "guild_workspace_id": ws["id"],
            "albion_guild_id": _GUILD_ID_A, "guild_name": "Iron Keep",
            "alliance_id": None, "alliance_name": None,
            "last_imported_at": now, "created_at": now,
        }
        with database.transaction() as db:
            repositories.upsert_workspace_albion_guild(db, row)
        # Second insert with same (guild_workspace_id, albion_guild_id) should upsert, not raise.
        row2 = {**row, "id": str(uuid.uuid4()), "guild_name": "Iron Keep Updated"}
        with database.transaction() as db:
            repositories.upsert_workspace_albion_guild(db, row2)
        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert len(guilds) == 1
        assert guilds[0]["guild_name"] == "Iron Keep Updated"

    def test_workspace_albion_players_unique_constraint(self):
        owner = make_user("SchemaPlayerOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        now = _now_iso()
        row = {
            "id": str(uuid.uuid4()), "guild_workspace_id": ws["id"],
            "albion_player_id": _PLAYER_ID_1, "character_name": "Kage",
            "user_id": None, "source_guild_id": None,
            "last_seen_in_guild_at": now, "created_at": now, "updated_at": now,
        }
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, row)
        row2 = {**row, "id": str(uuid.uuid4()), "character_name": "KageRenamed"}
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, row2)
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert len(players) == 1
        assert players[0]["character_name"] == "KageRenamed"


# ---------------------------------------------------------------------------
# 4. Repository: workspace_albion_guilds CRUD
# ---------------------------------------------------------------------------

class TestWorkspaceAlbionGuildsRepository:
    def _insert_guild(self, ws_id: str, guild_id: str = _GUILD_ID_A,
                      guild_name: str = "Iron Keep") -> dict:
        now = _now_iso()
        rec = {
            "id": str(uuid.uuid4()), "guild_workspace_id": ws_id,
            "albion_guild_id": guild_id, "guild_name": guild_name,
            "alliance_id": None, "alliance_name": None,
            "last_imported_at": None, "created_at": now,
        }
        with database.transaction() as db:
            repositories.upsert_workspace_albion_guild(db, rec)
        return rec

    def test_upsert_and_get(self):
        owner = make_user("GuildRepoOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert_guild(ws["id"])
        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
        assert row is not None
        assert row["guild_name"] == "Iron Keep"

    def test_get_returns_none_for_missing(self):
        owner = make_user("GuildRepoOwner2")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], "nonexistent")
        assert row is None

    def test_list_guilds_ordered_by_name(self):
        owner = make_user("GuildListOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert_guild(ws["id"], _GUILD_ID_A, "Zebra Guild")
        self._insert_guild(ws["id"], _GUILD_ID_B, "Alpha Guild")
        with database.transaction() as db:
            rows = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert len(rows) == 2
        assert rows[0]["guild_name"] == "Alpha Guild"
        assert rows[1]["guild_name"] == "Zebra Guild"

    def test_upsert_preserves_created_at(self):
        owner = make_user("GuildCreatedAtOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        rec = self._insert_guild(ws["id"])
        original_created_at = rec["created_at"]
        # Re-upsert with a different id/name — created_at must not change.
        now2 = _now_iso()
        rec2 = {
            "id": str(uuid.uuid4()), "guild_workspace_id": ws["id"],
            "albion_guild_id": _GUILD_ID_A, "guild_name": "Iron Keep v2",
            "alliance_id": None, "alliance_name": None,
            "last_imported_at": now2, "created_at": now2,
        }
        with database.transaction() as db:
            repositories.upsert_workspace_albion_guild(db, rec2)
        with database.transaction() as db:
            row = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
        assert row["created_at"] == original_created_at

    def test_guilds_scoped_to_workspace(self):
        owner = make_user("GuildScopeOwner")
        ws1 = make_workspace(slug="gsc1", owner_user_id=owner["id"])
        ws2 = make_workspace(slug="gsc2", owner_user_id=owner["id"])
        self._insert_guild(ws1["id"])
        with database.transaction() as db:
            rows1 = repositories.list_workspace_albion_guilds(db, ws1["id"])
            rows2 = repositories.list_workspace_albion_guilds(db, ws2["id"])
        assert len(rows1) == 1
        assert len(rows2) == 0


# ---------------------------------------------------------------------------
# 5. Repository: workspace_albion_players upsert / idempotency
# ---------------------------------------------------------------------------

class TestWorkspaceAlbionPlayersRepository:
    def _insert_player(self, ws_id: str, player_id: str = _PLAYER_ID_1,
                       char_name: str = "Kage",
                       user_id: str | None = None) -> dict:
        now = _now_iso()
        rec = {
            "id": str(uuid.uuid4()), "guild_workspace_id": ws_id,
            "albion_player_id": player_id, "character_name": char_name,
            "user_id": user_id, "source_guild_id": None,
            "last_seen_in_guild_at": now, "created_at": now, "updated_at": now,
        }
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, rec)
        return rec

    def test_insert_and_get(self):
        owner = make_user("PlayerRepoOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert_player(ws["id"])
        with database.transaction() as db:
            row = repositories.get_workspace_albion_player(db, ws["id"], _PLAYER_ID_1)
        assert row is not None
        assert row["character_name"] == "Kage"

    def test_list_players_ordered_by_name(self):
        owner = make_user("PlayerListOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert_player(ws["id"], _PLAYER_ID_1, "Zebra")
        self._insert_player(ws["id"], _PLAYER_ID_2, "Alpha")
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert players[0]["character_name"] == "Alpha"
        assert players[1]["character_name"] == "Zebra"

    def test_upsert_updates_character_name(self):
        owner = make_user("PlayerRenameOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert_player(ws["id"], _PLAYER_ID_1, "Kage")
        now = _now_iso()
        rec2 = {
            "id": str(uuid.uuid4()), "guild_workspace_id": ws["id"],
            "albion_player_id": _PLAYER_ID_1, "character_name": "KageRenamed",
            "user_id": None, "source_guild_id": None,
            "last_seen_in_guild_at": now, "created_at": now, "updated_at": now,
        }
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, rec2)
        with database.transaction() as db:
            row = repositories.get_workspace_albion_player(db, ws["id"], _PLAYER_ID_1)
        assert row["character_name"] == "KageRenamed"

    def test_players_scoped_to_workspace(self):
        owner = make_user("PlayerScopeOwner")
        ws1 = make_workspace(slug="psc1", owner_user_id=owner["id"])
        ws2 = make_workspace(slug="psc2", owner_user_id=owner["id"])
        self._insert_player(ws1["id"], _PLAYER_ID_1)
        with database.transaction() as db:
            rows1 = repositories.list_workspace_albion_players(db, ws1["id"])
            rows2 = repositories.list_workspace_albion_players(db, ws2["id"])
        assert len(rows1) == 1
        assert len(rows2) == 0

    def test_get_existing_player_ids(self):
        owner = make_user("ExistingIdsOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert_player(ws["id"], _PLAYER_ID_1)
        self._insert_player(ws["id"], _PLAYER_ID_2)
        with database.transaction() as db:
            ids = repositories.get_existing_albion_player_ids(db, ws["id"])
        assert ids == {_PLAYER_ID_1, _PLAYER_ID_2}


# ---------------------------------------------------------------------------
# 6. Repository: player user_id preservation on re-import
# ---------------------------------------------------------------------------

class TestPlayerUserIdPreservation:
    def test_upsert_preserves_user_id_on_conflict(self):
        owner = make_user("UserIdPreserveOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        now = _now_iso()
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, {
                "id": str(uuid.uuid4()), "guild_workspace_id": ws["id"],
                "albion_player_id": _PLAYER_ID_1, "character_name": "Kage",
                "user_id": owner["id"],
                "source_guild_id": None, "last_seen_in_guild_at": now,
                "created_at": now, "updated_at": now,
            })
        # Re-upsert with user_id=None — must NOT overwrite the existing link.
        now2 = _now_iso()
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, {
                "id": str(uuid.uuid4()), "guild_workspace_id": ws["id"],
                "albion_player_id": _PLAYER_ID_1, "character_name": "KageRenamed",
                "user_id": None,
                "source_guild_id": None, "last_seen_in_guild_at": now2,
                "created_at": now2, "updated_at": now2,
            })
        with database.transaction() as db:
            row = repositories.get_workspace_albion_player(db, ws["id"], _PLAYER_ID_1)
        assert row["user_id"] == owner["id"]
        assert row["character_name"] == "KageRenamed"


# ---------------------------------------------------------------------------
# 7. Use case: resolve_albion_guild_preview
# ---------------------------------------------------------------------------

class TestResolveAlbionGuildPreview:
    def test_happy_path_returns_resolved_guild(self):
        owner = make_user("PreviewOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild()]):
            with patch.object(rest_client, "_rate_limit"):
                result = use_cases.resolve_albion_guild_preview(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    guild_name_or_id="Iron Keep",
                )
        assert result["error"] is None
        assert result["albion_guild_id"] == _GUILD_ID_A
        assert result["guild_name"] == "Iron Keep"

    def test_no_results_returns_error(self):
        owner = make_user("PreviewNoResultOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_guilds", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                result = use_cases.resolve_albion_guild_preview(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    guild_name_or_id="Unknown Guild",
                )
        assert result["error"] is not None
        assert result["albion_guild_id"] is None

    def test_api_error_returns_error_not_exception(self):
        owner = make_user("PreviewApiErrOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion.rest_client import AlbionApiError
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_guilds",
                          side_effect=AlbionApiError("timeout")):
            with patch.object(rest_client, "_rate_limit"):
                result = use_cases.resolve_albion_guild_preview(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    guild_name_or_id="Iron Keep",
                )
        assert result["error"] is not None
        assert "API" in result["error"] or "Albion" in result["error"] or "timeout" in result["error"]
        assert result["albion_guild_id"] is None

    def test_empty_input_returns_error(self):
        owner = make_user("PreviewEmptyOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        result = use_cases.resolve_albion_guild_preview(
            guild_workspace_id=ws["id"],
            requesting_user_id=owner["id"],
            guild_name_or_id="   ",
        )
        assert result["error"] is not None

    def test_non_officer_raises_permission_denied(self):
        owner = make_user("PreviewPermOwner")
        plain_member = make_user("PreviewPermMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], plain_member["id"])
        with pytest.raises(PermissionDenied):
            use_cases.resolve_albion_guild_preview(
                guild_workspace_id=ws["id"],
                requesting_user_id=plain_member["id"],
                guild_name_or_id="Iron Keep",
            )


# ---------------------------------------------------------------------------
# 8. Use case: import_albion_guild_roster (single guild)
# ---------------------------------------------------------------------------

class TestImportAlbionGuildRoster:
    def test_happy_path_imports_members(self):
        owner = make_user("ImportOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        members = [_fake_member(_PLAYER_ID_1, "Kage"), _fake_member(_PLAYER_ID_2, "Vex")]
        result = _do_import(ws["id"], owner["id"], members=members)
        assert result["total"] == 2
        assert result["imported"] == 2
        assert result["updated"] == 0
        assert result["errors"] == []
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert len(players) == 2
        names = {p["character_name"] for p in players}
        assert names == {"Kage", "Vex"}

    def test_guild_record_is_stored(self):
        owner = make_user("GuildRecordOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"])
        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert len(guilds) == 1
        assert guilds[0]["albion_guild_id"] == _GUILD_ID_A

    def test_officer_can_import(self):
        owner = make_user("OfficerImportOwner")
        officer = make_user("OfficerImportOfficer")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], officer["id"])
        _add_officer(ws["id"], officer["id"])
        result = _do_import(ws["id"], officer["id"])
        assert result["total"] == 2

    def test_empty_guild_imports_zero_players(self):
        owner = make_user("EmptyGuildOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        result = _do_import(ws["id"], owner["id"], members=[])
        assert result["total"] == 0
        assert result["imported"] == 0
        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert len(guilds) == 1


# ---------------------------------------------------------------------------
# 9. Use case: import two guilds — overlapping player not duplicated
# ---------------------------------------------------------------------------

class TestMultiGuildImport:
    def test_same_player_in_two_guilds_not_duplicated(self):
        owner = make_user("MultiGuildOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        members_a = [
            _fake_member(_PLAYER_ID_SHARED, "Shared", guild_id=_GUILD_ID_A),
            _fake_member(_PLAYER_ID_1, "Kage", guild_id=_GUILD_ID_A),
        ]
        members_b = [
            _fake_member(_PLAYER_ID_SHARED, "Shared", guild_id=_GUILD_ID_B, guild_name="Shadow Syndicate"),
            _fake_member(_PLAYER_ID_3, "Archer", guild_id=_GUILD_ID_B, guild_name="Shadow Syndicate"),
        ]
        _do_import(ws["id"], owner["id"], guild_id=_GUILD_ID_A, members=members_a)
        _do_import(ws["id"], owner["id"], guild_id=_GUILD_ID_B, members=members_b)

        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])

        ids = {p["albion_player_id"] for p in players}
        assert ids == {_PLAYER_ID_SHARED, _PLAYER_ID_1, _PLAYER_ID_3}
        assert len(players) == 3  # no duplicates

    def test_two_guilds_both_recorded(self):
        owner = make_user("TwoGuildsOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"], guild_id=_GUILD_ID_A, members=[_fake_member(_PLAYER_ID_1, "Kage")])
        _do_import(ws["id"], owner["id"], guild_id=_GUILD_ID_B, members=[_fake_member(_PLAYER_ID_2, "Vex", guild_id=_GUILD_ID_B)])
        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert len(guilds) == 2


# ---------------------------------------------------------------------------
# 10. Use case: re-import same guild is idempotent
# ---------------------------------------------------------------------------

class TestReImportIdempotency:
    def test_reimport_same_guild_does_not_duplicate_players(self):
        owner = make_user("ReImportOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        members = [_fake_member(_PLAYER_ID_1, "Kage"), _fake_member(_PLAYER_ID_2, "Vex")]
        _do_import(ws["id"], owner["id"], members=members)
        _do_import(ws["id"], owner["id"], members=members)
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert len(players) == 2

    def test_reimport_counts_updated_not_imported(self):
        owner = make_user("ReImportCountsOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        members = [_fake_member(_PLAYER_ID_1, "Kage")]
        _do_import(ws["id"], owner["id"], members=members)
        result = _do_import(ws["id"], owner["id"], members=members)
        assert result["imported"] == 0
        assert result["updated"] == 1

    def test_reimport_updates_character_name(self):
        owner = make_user("ReImportNameOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"], members=[_fake_member(_PLAYER_ID_1, "Kage")])
        _do_import(ws["id"], owner["id"], members=[_fake_member(_PLAYER_ID_1, "KageRenamed")])
        with database.transaction() as db:
            row = repositories.get_workspace_albion_player(db, ws["id"], _PLAYER_ID_1)
        assert row["character_name"] == "KageRenamed"

    def test_reimport_updates_last_imported_at(self):
        owner = make_user("ReImportAtOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"])
        first_import = None
        with database.transaction() as db:
            g = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
            first_import = g["last_imported_at"]
        _do_import(ws["id"], owner["id"])
        with database.transaction() as db:
            g2 = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
        assert g2["last_imported_at"] is not None
        # last_imported_at must be set (may or may not differ depending on timing)
        assert g2["last_imported_at"] >= first_import


# ---------------------------------------------------------------------------
# 11. Use case: existing user link preserved on re-import
# ---------------------------------------------------------------------------

class TestUserLinkPreservation:
    def test_user_link_preserved_after_reimport(self):
        owner = make_user("UserLinkOwner")
        user2 = make_user("UserLinkUser2")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], user2["id"])
        # First import
        _do_import(ws["id"], owner["id"], members=[_fake_member(_PLAYER_ID_1, "Kage")])
        # Manually link user2 to the imported player
        with database.transaction() as db:
            db.execute(
                "UPDATE workspace_albion_players SET user_id=? "
                "WHERE guild_workspace_id=? AND albion_player_id=?",
                (user2["id"], ws["id"], _PLAYER_ID_1),
            )
        # Re-import
        _do_import(ws["id"], owner["id"], members=[_fake_member(_PLAYER_ID_1, "KageRenamed")])
        with database.transaction() as db:
            row = repositories.get_workspace_albion_player(db, ws["id"], _PLAYER_ID_1)
        assert row["user_id"] == user2["id"]
        assert row["character_name"] == "KageRenamed"


# ---------------------------------------------------------------------------
# 12. Use case: non-officer cannot import
# ---------------------------------------------------------------------------

class TestImportPermissions:
    def test_non_member_cannot_import(self):
        owner = make_user("PermOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        outsider = make_user("Outsider")
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(PermissionDenied):
                    use_cases.import_albion_guild_roster(
                        guild_workspace_id=ws["id"],
                        requesting_user_id=outsider["id"],
                        albion_guild_id=_GUILD_ID_A,
                    )

    def test_plain_member_cannot_import(self):
        owner = make_user("PermOwner2")
        plain = make_user("PermPlainMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], plain["id"])
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(PermissionDenied):
                    use_cases.import_albion_guild_roster(
                        guild_workspace_id=ws["id"],
                        requesting_user_id=plain["id"],
                        albion_guild_id=_GUILD_ID_A,
                    )


# ---------------------------------------------------------------------------
# 13. Use case: unknown guild (API error) raises ValidationError safely
# ---------------------------------------------------------------------------

class TestGuildImportErrorHandling:
    def test_api_error_raises_validation_error(self):
        owner = make_user("ApiErrOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion.rest_client import AlbionApiError
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members",
                          side_effect=AlbionApiError("connection refused")):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(ValidationError, match="Albion API"):
                    use_cases.import_albion_guild_roster(
                        guild_workspace_id=ws["id"],
                        requesting_user_id=owner["id"],
                        albion_guild_id=_GUILD_ID_A,
                    )

    def test_api_timeout_raises_validation_error(self):
        import httpx
        owner = make_user("TimeoutOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion import rest_client
        with patch.object(rest_client, "_rate_limit"):
            with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
                with pytest.raises(ValidationError, match="Albion API"):
                    use_cases.import_albion_guild_roster(
                        guild_workspace_id=ws["id"],
                        requesting_user_id=owner["id"],
                        albion_guild_id=_GUILD_ID_A,
                    )

    def test_api_error_does_not_corrupt_previous_guild_data(self):
        """A failing second guild import must not roll back the first guild's data."""
        owner = make_user("PartialFailOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        # First guild succeeds
        _do_import(ws["id"], owner["id"], guild_id=_GUILD_ID_A,
                   members=[_fake_member(_PLAYER_ID_1, "Kage")])
        # Second guild fails
        from app.albion.rest_client import AlbionApiError
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members",
                          side_effect=AlbionApiError("server error")):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(ValidationError):
                    use_cases.import_albion_guild_roster(
                        guild_workspace_id=ws["id"],
                        requesting_user_id=owner["id"],
                        albion_guild_id=_GUILD_ID_B,
                    )
        # First guild data intact
        with database.transaction() as db:
            row = repositories.get_workspace_albion_player(db, ws["id"], _PLAYER_ID_1)
        assert row is not None
        assert row["character_name"] == "Kage"


# ---------------------------------------------------------------------------
# 14. Use case: empty guild_id raises ValidationError
# ---------------------------------------------------------------------------

class TestImportEmptyGuildId:
    def test_empty_guild_id_raises(self):
        owner = make_user("EmptyIdOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        with pytest.raises(ValidationError):
            use_cases.import_albion_guild_roster(
                guild_workspace_id=ws["id"],
                requesting_user_id=owner["id"],
                albion_guild_id="   ",
            )


# ---------------------------------------------------------------------------
# 15. Use case: import stores audit event
# ---------------------------------------------------------------------------

class TestImportAuditEvent:
    def test_import_emits_audit_event(self):
        owner = make_user("AuditOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"])
        with database.transaction() as db:
            events = db.execute(
                "SELECT * FROM operational_events "
                "WHERE guild_workspace_id=? AND event_type=?",
                (ws["id"], "albion_guild.roster_imported"),
            ).fetchall()
        assert len(events) == 1
        import json
        payload = json.loads(events[0]["payload_json"])
        assert payload["albion_guild_id"] == _GUILD_ID_A


# ---------------------------------------------------------------------------
# 16. Use case: import updates last_imported_at
# ---------------------------------------------------------------------------

class TestLastImportedAt:
    def test_first_import_sets_last_imported_at(self):
        owner = make_user("LastImportedOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"])
        with database.transaction() as db:
            g = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
        assert g["last_imported_at"] is not None

    def test_reimport_updates_last_imported_at(self):
        owner = make_user("LastImportedOwner2")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"])
        with database.transaction() as db:
            g1 = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
        _do_import(ws["id"], owner["id"])
        with database.transaction() as db:
            g2 = repositories.get_workspace_albion_guild(db, ws["id"], _GUILD_ID_A)
        assert g2["last_imported_at"] >= g1["last_imported_at"]


# ---------------------------------------------------------------------------
# 17. Use case: manual workspace members / users are unaffected
# ---------------------------------------------------------------------------

class TestManualMembersUnaffected:
    def test_import_does_not_alter_workspace_members(self):
        owner = make_user("ManualMemberOwner")
        manual = make_user("ManualMemberUser")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], manual["id"])
        _do_import(ws["id"], owner["id"], members=[_fake_member(_PLAYER_ID_1, "Kage")])
        with database.transaction() as db:
            ws_members = repositories.list_workspace_members(db, ws["id"])
        user_ids = {m["user_id"] for m in ws_members}
        assert owner["id"] in user_ids
        assert manual["id"] in user_ids
        assert len(ws_members) == 2

    def test_import_does_not_create_user_accounts(self):
        owner = make_user("NoUserAcctOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"],
                   members=[_fake_member(_PLAYER_ID_1, "ExternalPlayer")])
        with database.transaction() as db:
            users_after = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        # Only the owner account exists — no user created for imported player.
        assert users_after == 1

    def test_import_does_not_create_participants(self):
        owner = make_user("NoParticipantOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"],
                   members=[_fake_member(_PLAYER_ID_1, "ExternalPlayer")])
        with database.transaction() as db:
            p_count = db.execute(
                "SELECT COUNT(*) FROM participants WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchone()[0]
        assert p_count == 0


# ---------------------------------------------------------------------------
# 18. Routes: GET /members/import-guilds (officer only)
# ---------------------------------------------------------------------------

class TestImportGuildsGetRoute:
    def test_officer_can_access_import_page(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ImportRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        response = client.get(f"/workspaces/{ws['slug']}/members/import-guilds",
                              follow_redirects=True)
        assert response.status_code == 200
        assert "Import Guild Roster" in response.text

    def test_plain_member_gets_403(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ImportRoute403Owner")
        plain = make_user("ImportRoute403Member")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], plain["id"])
        _login(client, plain["display_name"])
        response = client.get(f"/workspaces/{ws['slug']}/members/import-guilds",
                              follow_redirects=True)
        assert response.status_code == 403

    def test_linked_guilds_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("LinkedGuildsRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"])
        _login(client, owner["display_name"])
        response = client.get(f"/workspaces/{ws['slug']}/members/import-guilds",
                              follow_redirects=True)
        assert response.status_code == 200
        assert "Linked Guilds" in response.text


# ---------------------------------------------------------------------------
# 19. Routes: POST /preview returns preview table
# ---------------------------------------------------------------------------

class TestImportGuildsPreviewRoute:
    def test_preview_shows_resolved_guild(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PreviewRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild(member_count=42)]):
            with patch.object(rest_client, "_rate_limit"):
                response = client.post(
                    f"/workspaces/{ws['slug']}/members/import-guilds/preview",
                    data={"guild_names": "Iron Keep"},
                    follow_redirects=True,
                )
        assert response.status_code == 200
        assert "Iron Keep" in response.text
        assert "Ready" in response.text

    def test_preview_shows_error_row_for_unknown_guild(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PreviewErrRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_guilds", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                response = client.post(
                    f"/workspaces/{ws['slug']}/members/import-guilds/preview",
                    data={"guild_names": "Unknown Guild XYZ"},
                    follow_redirects=True,
                )
        assert response.status_code == 200
        assert "Unknown Guild XYZ" in response.text

    def test_preview_empty_textarea_redirects_with_error(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PreviewEmptyRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/import-guilds/preview",
            data={"guild_names": ""},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        assert "error" in response.headers.get("location", "")

    def test_preview_does_not_write_to_db(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PreviewNoDatabaseOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_guilds",
                          return_value=[_fake_guild()]):
            with patch.object(rest_client, "_rate_limit"):
                client.post(
                    f"/workspaces/{ws['slug']}/members/import-guilds/preview",
                    data={"guild_names": "Iron Keep"},
                    follow_redirects=True,
                )
        with database.transaction() as db:
            guilds = repositories.list_workspace_albion_guilds(db, ws["id"])
        assert len(guilds) == 0


# ---------------------------------------------------------------------------
# 20. Routes: POST /confirm imports and redirects with success
# ---------------------------------------------------------------------------

class TestImportGuildsConfirmRoute:
    def test_confirm_imports_players_and_redirects(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ConfirmRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        members = [_fake_member(_PLAYER_ID_1, "Kage"), _fake_member(_PLAYER_ID_2, "Vex")]
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=members):
            with patch.object(rest_client, "_rate_limit"):
                response = client.post(
                    f"/workspaces/{ws['slug']}/members/import-guilds/confirm",
                    data={
                        "albion_guild_id": _GUILD_ID_A,
                        "guild_name":      "Iron Keep",
                        "alliance_id":     "",
                        "alliance_name":   "",
                    },
                    follow_redirects=False,
                )
        assert response.status_code in (302, 303)
        assert "success" in response.headers.get("location", "")
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert len(players) == 2

    def test_confirm_with_no_guild_ids_redirects_with_error(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("ConfirmNoIdOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/import-guilds/confirm",
            data={},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        assert "error" in response.headers.get("location", "")


# ---------------------------------------------------------------------------
# 21. Routes: non-officer cannot access import routes
# ---------------------------------------------------------------------------

class TestImportRoutesPermission:
    def test_plain_member_cannot_post_preview(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("RoutePerm403Owner")
        plain = make_user("RoutePerm403Member")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], plain["id"])
        _login(client, plain["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/import-guilds/preview",
            data={"guild_names": "Iron Keep"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303, 403)

    def test_plain_member_cannot_post_confirm(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("RoutePerm403Owner2")
        plain = make_user("RoutePerm403Member2")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], plain["id"])
        _login(client, plain["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/import-guilds/confirm",
            data={"albion_guild_id": _GUILD_ID_A, "guild_name": "Iron Keep",
                  "alliance_id": "", "alliance_name": ""},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303, 403)


# ---------------------------------------------------------------------------
# 22. Routes: members page shows imported players section
# ---------------------------------------------------------------------------

class TestMembersPageShowsImportedPlayers:
    def test_members_page_shows_imported_player(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("MembersImportedOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"],
                   members=[_fake_member(_PLAYER_ID_1, "ImportedKage")])
        _login(client, owner["display_name"])
        response = client.get(f"/workspaces/{ws['slug']}/members",
                              follow_redirects=True)
        assert response.status_code == 200
        assert "ImportedKage" in response.text
        assert "Imported Albion Players" in response.text

    def test_members_page_shows_import_guilds_link(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("MembersLinkOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        response = client.get(f"/workspaces/{ws['slug']}/members",
                              follow_redirects=True)
        assert response.status_code == 200
        assert "import-guilds" in response.text


# ---------------------------------------------------------------------------
# 23. Regression: existing Albion identity claim tests still pass
# ---------------------------------------------------------------------------

class TestAlbionIdentityRegressionGuard:
    """
    Spot-check that roster import did not break the existing albion identity
    claim flow.  Full coverage is in test_albion_identity.py.
    """
    def test_participants_albion_player_id_write_dark_invariant_intact(self):
        from pathlib import Path
        source = (
            Path(__file__).parent.parent / "app" / "repositories.py"
        ).read_text(encoding="utf-8")
        assert "participants.albion_player_id" not in source, (
            "write-dark violation: repositories.py references participants.albion_player_id"
        )

    def test_workspace_albion_players_does_not_touch_participants(self):
        owner = make_user("WAPNoPartOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _do_import(ws["id"], owner["id"],
                   members=[_fake_member(_PLAYER_ID_1, "Kage")])
        with database.transaction() as db:
            p_count = db.execute(
                "SELECT COUNT(*) FROM participants WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchone()[0]
        assert p_count == 0

    def test_guild_roster_event_not_in_dispatchable(self):
        from app.events import DISPATCHABLE_EVENT_TYPES
        from app.domain import operational_events
        assert operational_events.ALBION_GUILD_ROSTER_IMPORTED not in DISPATCHABLE_EVENT_TYPES
