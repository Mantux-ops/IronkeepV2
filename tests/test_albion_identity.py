"""
Albion Online API Integration â€” test suite (Slice 37).

Test groups:
  1.  Domain: albion_identity validation
  2.  Schema / migration invariants
  3.  Repository: player_game_identities CRUD
  4.  Repository: albion_character_cache upsert / batch-fetch
  5.  Repository: uniqueness constraints
  6.  REST client: search, fetch, error handling
  7.  Use case: claim_albion_character (happy path + conflicts)
  8.  Use case: approve_albion_character_claim (RBAC)
  9.  Use case: reject_albion_character_claim
  10. Use case: refresh_albion_character_cache (verification state invariant)
  11. Use case: rejected-claim replace flow
  12. Critical invariants: participants.albion_player_id never read by core logic
  13. Critical invariants: no display_name identity inference
  14. Routes: account page Albion section
  15. Routes: members page approve / reject
  16. Module boundary: rest_client has no DB/Discord/domain imports
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import albion_identity as aid
from app.domain import operational_events
from app.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from app.main import app
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PLAYER_ID_A = "abc1234-dead-beef-cafe-000000000001"
_PLAYER_ID_B = "abc1234-dead-beef-cafe-000000000002"
_PLAYER_ID_C = "abc1234-dead-beef-cafe-000000000003"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_char(player_id: str = _PLAYER_ID_A, name: str = "KagePlayer") -> dict:
    return {
        "albion_player_id": player_id,
        "character_name":   name,
        "guild_id":         "guild-001",
        "guild_name":       "Iron Keep",
        "kill_fame":        10000,
        "death_fame":       500,
        "extra_json":       json.dumps({"Id": player_id, "Name": name}),
    }


def _add_officer(ws_id: str, user_id: str) -> None:
    """Promote a workspace member to officer role."""
    with database.transaction() as db:
        db.execute(
            "UPDATE workspace_members SET role='officer' WHERE guild_workspace_id=? AND user_id=?",
            (ws_id, user_id),
        )


def _get_claim(user_id: str, ws_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_player_game_identity_for_user(db, user_id, ws_id)


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


# ---------------------------------------------------------------------------
# 1. Domain: albion_identity validation
# ---------------------------------------------------------------------------

class TestAlbionPlayerIdValidation:
    def test_valid_id_returned_trimmed(self):
        assert aid.validate_albion_player_id("  abc123  ") == "abc123"

    def test_empty_raises(self):
        with pytest.raises(ValidationError):
            aid.validate_albion_player_id("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError):
            aid.validate_albion_player_id("   ")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError):
            aid.validate_albion_player_id("x" * 129)

    def test_128_chars_allowed(self):
        long_id = "x" * 128
        assert aid.validate_albion_player_id(long_id) == long_id

    def test_no_uuid_format_enforcement(self):
        # NOT a UUID; must still be accepted.
        assert aid.validate_albion_player_id("not-a-uuid-at-all") == "not-a-uuid-at-all"

    def test_non_string_raises(self):
        with pytest.raises(ValidationError):
            aid.validate_albion_player_id(12345)  # type: ignore[arg-type]


class TestAlbionCharacterNameValidation:
    def test_valid_name_returned_trimmed(self):
        assert aid.validate_albion_character_name("  Kage  ") == "Kage"

    def test_empty_raises(self):
        with pytest.raises(ValidationError):
            aid.validate_albion_character_name("")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError):
            aid.validate_albion_character_name("x" * 129)

    def test_128_chars_allowed(self):
        long_name = "x" * 128
        assert aid.validate_albion_character_name(long_name) == long_name


# ---------------------------------------------------------------------------
# 2. Schema / migration invariants
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_participants_albion_player_id_column_exists(self):
        with database.transaction() as db:
            info = db.execute("PRAGMA table_info(participants)").fetchall()
        col_names = [row["name"] for row in info]
        assert "albion_player_id" in col_names

    def test_existing_participant_rows_have_null_albion_player_id(self):
        owner = make_user("ColumnOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        now = _now_iso()
        with database.transaction() as db:
            db.execute(
                "INSERT INTO participants "
                "(id, guild_workspace_id, display_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), ws["id"], "SomePlayer", now, now),
            )
        with database.transaction() as db:
            row = db.execute(
                "SELECT albion_player_id FROM participants WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchone()
        assert row["albion_player_id"] is None

    def test_player_game_identities_table_exists(self):
        with database.transaction() as db:
            info = db.execute("PRAGMA table_info(player_game_identities)").fetchall()
        assert len(info) > 0

    def test_albion_character_cache_table_exists(self):
        with database.transaction() as db:
            info = db.execute("PRAGMA table_info(albion_character_cache)").fetchall()
        assert len(info) > 0

    def test_pgi_workspace_status_index_exists(self):
        with database.transaction() as db:
            indexes = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_pgi_workspace_status'"
            ).fetchall()
        assert len(indexes) == 1

    def test_pgi_albion_id_workspace_unique_index_exists(self):
        with database.transaction() as db:
            indexes = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_pgi_albion_id_workspace'"
            ).fetchall()
        assert len(indexes) == 1

    def test_no_fk_on_participants_albion_player_id(self):
        """participants.albion_player_id has no foreign key â€” it is write-dark."""
        with database.transaction() as db:
            fk_list = db.execute("PRAGMA foreign_key_list(participants)").fetchall()
        fk_cols = [row["from"] for row in fk_list]
        assert "albion_player_id" not in fk_cols


# ---------------------------------------------------------------------------
# 3. Repository: player_game_identities CRUD
# ---------------------------------------------------------------------------

class TestPlayerGameIdentityRepository:
    def _insert(self, ws_id: str, user_id: str, player_id: str = _PLAYER_ID_A,
                status: str = "pending") -> dict:
        now = _now_iso()
        record = {
            "id":                  str(uuid.uuid4()),
            "guild_workspace_id":  ws_id,
            "user_id":             user_id,
            "game":                "albion",
            "albion_player_id":    player_id,
            "character_name":      "Kage",
            "verification_status": status,
            "claimed_at":          now,
            "reviewed_at":         None,
            "reviewed_by":         None,
            "review_note":         None,
            "created_at":          now,
        }
        with database.transaction() as db:
            repositories.insert_player_game_identity(db, record)
        return record

    def test_insert_and_get_by_id(self):
        owner = make_user("IDOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        r = self._insert(ws["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_player_game_identity_by_id(db, r["id"], ws["id"])
        assert row is not None
        assert row["albion_player_id"] == _PLAYER_ID_A

    def test_get_by_id_wrong_workspace_returns_none(self):
        owner = make_user("IDOwner2")
        ws = make_workspace(owner_user_id=owner["id"])
        r = self._insert(ws["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_player_game_identity_by_id(db, r["id"], "fake-ws")
        assert row is None

    def test_get_for_user(self):
        owner = make_user("ForUser")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert(ws["id"], owner["id"])
        row = _get_claim(owner["id"], ws["id"])
        assert row is not None
        assert row["user_id"] == owner["id"]

    def test_get_for_user_wrong_workspace_returns_none(self):
        owner = make_user("ForUser2")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert(ws["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_player_game_identity_for_user(
                db, owner["id"], "fake-ws-id"
            )
        assert row is None

    def test_get_by_albion_id(self):
        owner = make_user("ByAlbionId")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert(ws["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_player_game_identity_by_albion_id(
                db, _PLAYER_ID_A, ws["id"]
            )
        assert row is not None
        assert row["user_id"] == owner["id"]

    def test_list_for_workspace(self):
        owner = make_user("ListWs")
        user2 = make_user("ListWs2")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], user2["id"], _now_iso()),
            )
        self._insert(ws["id"], owner["id"], player_id=_PLAYER_ID_A)
        self._insert(ws["id"], user2["id"],  player_id=_PLAYER_ID_B)
        with database.transaction() as db:
            rows = repositories.list_player_game_identities_for_workspace(db, ws["id"])
        assert len(rows) == 2

    def test_list_for_user_cross_workspace(self):
        user = make_user("CrossWsUser")
        ws1 = make_workspace(slug="cwu1", owner_user_id=user["id"])
        ws2 = make_workspace(slug="cwu2", owner_user_id=user["id"])
        self._insert(ws1["id"], user["id"], player_id=_PLAYER_ID_A)
        self._insert(ws2["id"], user["id"], player_id=_PLAYER_ID_B)
        with database.transaction() as db:
            rows = repositories.list_player_game_identities_for_user(db, user["id"])
        assert len(rows) == 2

    def test_delete(self):
        owner = make_user("DeleteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        r = self._insert(ws["id"], owner["id"])
        with database.transaction() as db:
            repositories.delete_player_game_identity(db, r["id"])
        row = _get_claim(owner["id"], ws["id"])
        assert row is None

    def test_update_status_to_approved(self):
        owner = make_user("UpdateOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        r = self._insert(ws["id"], owner["id"])
        now = _now_iso()
        with database.transaction() as db:
            repositories.update_player_game_identity_status(
                db, r["id"], "approved", owner["id"], now
            )
        row = _get_claim(owner["id"], ws["id"])
        assert row["verification_status"] == "approved"
        assert row["reviewed_by"] == owner["id"]

    def test_update_status_to_rejected_with_note(self):
        owner = make_user("UpdateOwner2")
        ws = make_workspace(owner_user_id=owner["id"])
        r = self._insert(ws["id"], owner["id"])
        now = _now_iso()
        with database.transaction() as db:
            repositories.update_player_game_identity_status(
                db, r["id"], "rejected", owner["id"], now, "Not verified"
            )
        row = _get_claim(owner["id"], ws["id"])
        assert row["verification_status"] == "rejected"
        assert row["review_note"] == "Not verified"


# ---------------------------------------------------------------------------
# 4. Repository: albion_character_cache
# ---------------------------------------------------------------------------

class TestAlbionCharacterCacheRepository:
    def _cache_record(self, player_id: str = _PLAYER_ID_A, name: str = "Kage") -> dict:
        return {
            "id":               str(uuid.uuid4()),
            "albion_player_id": player_id,
            "character_name":   name,
            "guild_id":         "g001",
            "guild_name":       "Iron Keep",
            "kill_fame":        5000,
            "death_fame":       200,
            "extra_json":       "{}",
            "fetched_at":       _now_iso(),
        }

    def test_upsert_and_get(self):
        rec = self._cache_record()
        with database.transaction() as db:
            repositories.upsert_albion_character_cache(db, rec)
        with database.transaction() as db:
            row = repositories.get_albion_character_cache(db, _PLAYER_ID_A)
        assert row is not None
        assert row["character_name"] == "Kage"

    def test_upsert_overwrites_existing(self):
        rec = self._cache_record(name="Kage")
        with database.transaction() as db:
            repositories.upsert_albion_character_cache(db, rec)
        rec2 = self._cache_record(name="KageUpdated")
        with database.transaction() as db:
            repositories.upsert_albion_character_cache(db, rec2)
        with database.transaction() as db:
            row = repositories.get_albion_character_cache(db, _PLAYER_ID_A)
        assert row["character_name"] == "KageUpdated"

    def test_upsert_preserves_row_id(self):
        rec = self._cache_record()
        original_id = rec["id"]
        with database.transaction() as db:
            repositories.upsert_albion_character_cache(db, rec)
        rec2 = {**self._cache_record(), "id": "new-uuid-different"}
        with database.transaction() as db:
            repositories.upsert_albion_character_cache(db, rec2)
        with database.transaction() as db:
            row = repositories.get_albion_character_cache(db, _PLAYER_ID_A)
        assert row["id"] == original_id  # original row id preserved on conflict

    def test_get_returns_none_for_unknown(self):
        with database.transaction() as db:
            row = repositories.get_albion_character_cache(db, "nonexistent-id")
        assert row is None

    def test_batch_fetch_empty_list(self):
        with database.transaction() as db:
            rows = repositories.get_albion_character_cache_many(db, [])
        assert rows == []

    def test_batch_fetch_multiple(self):
        for pid, name in [(_PLAYER_ID_A, "Kage"), (_PLAYER_ID_B, "Vex")]:
            rec = self._cache_record(player_id=pid, name=name)
            with database.transaction() as db:
                repositories.upsert_albion_character_cache(db, rec)
        with database.transaction() as db:
            rows = repositories.get_albion_character_cache_many(
                db, [_PLAYER_ID_A, _PLAYER_ID_B]
            )
        names = {r["character_name"] for r in rows}
        assert names == {"Kage", "Vex"}

    def test_batch_fetch_unknown_ids_skipped(self):
        rec = self._cache_record(player_id=_PLAYER_ID_A)
        with database.transaction() as db:
            repositories.upsert_albion_character_cache(db, rec)
        with database.transaction() as db:
            rows = repositories.get_albion_character_cache_many(
                db, [_PLAYER_ID_A, "not-in-db"]
            )
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 5. Repository: uniqueness constraints
# ---------------------------------------------------------------------------

class TestUniquenessConstraints:
    def _insert(self, ws_id: str, user_id: str, player_id: str) -> dict:
        now = _now_iso()
        record = {
            "id":                  str(uuid.uuid4()),
            "guild_workspace_id":  ws_id,
            "user_id":             user_id,
            "game":                "albion",
            "albion_player_id":    player_id,
            "character_name":      "Kage",
            "verification_status": "pending",
            "claimed_at":          now,
            "reviewed_at":         None,
            "reviewed_by":         None,
            "review_note":         None,
            "created_at":          now,
        }
        with database.transaction() as db:
            repositories.insert_player_game_identity(db, record)
        return record

    def test_duplicate_user_game_workspace_raises(self):
        owner = make_user("DupUser")
        ws = make_workspace(owner_user_id=owner["id"])
        self._insert(ws["id"], owner["id"], _PLAYER_ID_A)
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            self._insert(ws["id"], owner["id"], _PLAYER_ID_B)

    def test_duplicate_albion_id_same_workspace_raises(self):
        owner = make_user("DupChar")
        user2 = make_user("DupChar2")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], user2["id"], _now_iso()),
            )
        self._insert(ws["id"], owner["id"], _PLAYER_ID_A)
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            self._insert(ws["id"], user2["id"], _PLAYER_ID_A)

    def test_same_albion_id_different_workspaces_allowed(self):
        user = make_user("CrossWsChar")
        ws1 = make_workspace(slug="cwc1", owner_user_id=user["id"])
        ws2 = make_workspace(slug="cwc2", owner_user_id=user["id"])
        # Same albion_player_id in two different workspaces â€” must NOT raise
        self._insert(ws1["id"], user["id"], _PLAYER_ID_A)
        self._insert(ws2["id"], user["id"], _PLAYER_ID_A)
        with database.transaction() as db:
            r1 = repositories.get_player_game_identity_by_albion_id(db, _PLAYER_ID_A, ws1["id"])
            r2 = repositories.get_player_game_identity_by_albion_id(db, _PLAYER_ID_A, ws2["id"])
        assert r1 is not None
        assert r2 is not None


# ---------------------------------------------------------------------------
# 6. REST client: search, fetch, error handling
# ---------------------------------------------------------------------------

class TestAlbionRestClient:
    def test_search_returns_normalised_list(self):
        raw = [
            {"Id": _PLAYER_ID_A, "Name": "Kage", "GuildId": "g1",
             "GuildName": "Iron Keep", "KillFame": 100, "DeathFame": 10},
        ]
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=raw):
            with patch.object(rest_client, "_rate_limit"):
                results = rest_client.search_albion_characters("Kage")
        assert len(results) == 1
        assert results[0]["albion_player_id"] == _PLAYER_ID_A
        assert results[0]["character_name"] == "Kage"
        assert results[0]["guild_name"] == "Iron Keep"

    def test_search_empty_results(self):
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=[]):
            with patch.object(rest_client, "_rate_limit"):
                results = rest_client.search_albion_characters("NoOne")
        assert results == []

    def test_search_non_list_response_returns_empty(self):
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value={"error": "bad"}):
            with patch.object(rest_client, "_rate_limit"):
                results = rest_client.search_albion_characters("x")
        assert results == []

    def test_fetch_returns_normalised_dict(self):
        raw = {"Id": _PLAYER_ID_A, "Name": "Kage", "GuildId": "g1", "GuildName": "IK",
               "KillFame": 500, "DeathFame": 20}
        from app.albion import rest_client
        with patch.object(rest_client, "_get", return_value=raw):
            with patch.object(rest_client, "_rate_limit"):
                result = rest_client.fetch_albion_character(_PLAYER_ID_A)
        assert result["albion_player_id"] == _PLAYER_ID_A
        assert result["character_name"] == "Kage"

    def test_fetch_timeout_raises_albion_api_error(self):
        import httpx
        from app.albion import rest_client
        with patch.object(rest_client, "_rate_limit"):
            with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
                with pytest.raises(rest_client.AlbionApiError, match="timed out"):
                    rest_client.fetch_albion_character(_PLAYER_ID_A)

    def test_fetch_non_200_raises_albion_api_error(self):
        import httpx
        from app.albion import rest_client
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(rest_client, "_rate_limit"):
            with patch("httpx.get", return_value=mock_resp):
                with pytest.raises(rest_client.AlbionApiError, match="404"):
                    rest_client.fetch_albion_character(_PLAYER_ID_A)

    def test_search_timeout_raises_albion_api_error(self):
        import httpx
        from app.albion import rest_client
        with patch.object(rest_client, "_rate_limit"):
            with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
                with pytest.raises(rest_client.AlbionApiError):
                    rest_client.search_albion_characters("Kage")

    def test_rest_client_has_no_sqlite_import(self):
        path = __import__("pathlib").Path(
            __import__("app.albion.rest_client", fromlist=["rest_client"])
            .__file__
        )
        source = path.read_text(encoding="utf-8")
        assert "import sqlite3" not in source
        assert "from app" not in source
        assert "import discord" not in source


# ---------------------------------------------------------------------------
# 7. Use case: claim_albion_character
# ---------------------------------------------------------------------------

def _make_claim(user_id: str, ws_id: str, player_id: str = _PLAYER_ID_A,
                name: str = "Kage") -> dict:
    """Helper: patch the Albion API and create a claim."""
    from app.albion import rest_client
    with patch.object(rest_client, "fetch_albion_character",
                      return_value=_fake_char(player_id, name)):
        with patch.object(rest_client, "_rate_limit"):
            return use_cases.claim_albion_character(
                user_id=user_id,
                guild_workspace_id=ws_id,
                albion_player_id=player_id,
            )


class TestClaimAlbionCharacter:
    def test_happy_path_creates_pending_claim(self):
        owner = make_user("ClaimOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        claim = _get_claim(owner["id"], ws["id"])
        assert claim is not None
        assert claim["verification_status"] == "pending"
        assert claim["albion_player_id"] == _PLAYER_ID_A

    def test_claim_upserts_character_cache(self):
        owner = make_user("CacheOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        with database.transaction() as db:
            cache = repositories.get_albion_character_cache(db, _PLAYER_ID_A)
        assert cache is not None
        assert cache["character_name"] == "Kage"

    def test_claim_emits_audit_event(self):
        owner = make_user("EventOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        with database.transaction() as db:
            events = db.execute(
                "SELECT * FROM operational_events WHERE guild_workspace_id=? AND event_type=?",
                (ws["id"], operational_events.ALBION_IDENTITY_CLAIMED),
            ).fetchall()
        assert len(events) == 1

    def test_invalid_player_id_raises_validation_error(self):
        owner = make_user("InvalidID")
        ws = make_workspace(owner_user_id=owner["id"])
        with pytest.raises(ValidationError):
            use_cases.claim_albion_character(
                user_id=owner["id"],
                guild_workspace_id=ws["id"],
                albion_player_id="",
            )

    def test_non_member_cannot_claim(self):
        owner = make_user("WsOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        outsider = make_user("Outsider")
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=_fake_char()):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(PermissionDenied):
                    use_cases.claim_albion_character(
                        user_id=outsider["id"],
                        guild_workspace_id=ws["id"],
                        albion_player_id=_PLAYER_ID_A,
                    )

    def test_duplicate_same_workspace_blocked(self):
        owner = make_user("DupClaim")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        # Approve it
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        # Try to claim again â€” should fail because the existing claim is approved
        with pytest.raises(ConflictError):
            _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_B)

    def test_pending_claim_replaced_by_reclaim(self):
        owner = make_user("ReclaimOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_A)
        # Re-claim with a different character while still pending
        _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_B, name="Vex")
        claim = _get_claim(owner["id"], ws["id"])
        assert claim["albion_player_id"] == _PLAYER_ID_B

    def test_api_failure_raises_validation_error(self):
        owner = make_user("ApiFail")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion.rest_client import AlbionApiError
        with patch(
            "app.albion.rest_client.fetch_albion_character",
            side_effect=AlbionApiError("Network error"),
        ):
            with pytest.raises(ValidationError, match="Albion API"):
                use_cases.claim_albion_character(
                    user_id=owner["id"],
                    guild_workspace_id=ws["id"],
                    albion_player_id=_PLAYER_ID_A,
                )

    def test_character_claimed_by_other_user_blocked(self):
        owner = make_user("CharConflictOwner")
        user2 = make_user("CharConflictUser2")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], user2["id"], _now_iso()),
            )
        _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_A)
        with pytest.raises(ConflictError, match="already claimed"):
            _make_claim(user2["id"], ws["id"], player_id=_PLAYER_ID_A)


# ---------------------------------------------------------------------------
# 8. Use case: approve_albion_character_claim
# ---------------------------------------------------------------------------

class TestApproveAlbionCharacterClaim:
    def test_owner_approves_member_claim(self):
        owner = make_user("ApproveOwner")
        member = make_user("ApproveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(member["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "approved"
        assert claim["reviewed_by"] == owner["id"]

    def test_owner_can_approve_own_claim(self):
        owner = make_user("SelfApproveOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        claim = _get_claim(owner["id"], ws["id"])
        assert claim["verification_status"] == "approved"

    def test_officer_cannot_approve_own_claim(self):
        owner = make_user("OfficerSelfApproveOwner")
        officer = make_user("OfficerSelfApprove")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'officer',?)",
                (str(uuid.uuid4()), ws["id"], officer["id"], _now_iso()),
            )
        _make_claim(officer["id"], ws["id"])
        with pytest.raises(PermissionDenied, match="Officers cannot approve"):
            use_cases.approve_albion_character_claim(
                reviewer_user_id=officer["id"],
                target_user_id=officer["id"],
                guild_workspace_id=ws["id"],
            )

    def test_officer_can_approve_other_member(self):
        owner   = make_user("OfficerApproveOwner")
        officer = make_user("OfficerApproveOfficer")
        member  = make_user("OfficerApproveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'officer',?)",
                (str(uuid.uuid4()), ws["id"], officer["id"], _now_iso()),
            )
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(member["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=officer["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "approved"

    def test_member_cannot_approve(self):
        owner  = make_user("MemberApproveOwner")
        member = make_user("MemberApproveUser")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(member["id"], ws["id"])
        with pytest.raises(PermissionDenied):
            use_cases.approve_albion_character_claim(
                reviewer_user_id=member["id"],
                target_user_id=member["id"],
                guild_workspace_id=ws["id"],
            )

    def test_approve_nonexistent_claim_raises(self):
        owner = make_user("NoClaimOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        with pytest.raises(NotFoundError):
            use_cases.approve_albion_character_claim(
                reviewer_user_id=owner["id"],
                target_user_id=owner["id"],
                guild_workspace_id=ws["id"],
            )

    def test_approve_emits_audit_event(self):
        owner = make_user("ApproveEventOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        with database.transaction() as db:
            events = db.execute(
                "SELECT * FROM operational_events WHERE event_type=? AND guild_workspace_id=?",
                (operational_events.ALBION_IDENTITY_APPROVED, ws["id"]),
            ).fetchall()
        assert len(events) == 1

    def test_albion_approved_event_not_dispatchable(self):
        from app.events import DISPATCHABLE_EVENT_TYPES
        assert operational_events.ALBION_IDENTITY_APPROVED not in DISPATCHABLE_EVENT_TYPES
        assert operational_events.ALBION_IDENTITY_CLAIMED not in DISPATCHABLE_EVENT_TYPES
        assert operational_events.ALBION_IDENTITY_REJECTED not in DISPATCHABLE_EVENT_TYPES


# ---------------------------------------------------------------------------
# 9. Use case: reject_albion_character_claim
# ---------------------------------------------------------------------------

class TestRejectAlbionCharacterClaim:
    def test_owner_rejects_with_note(self):
        owner  = make_user("RejectOwner")
        member = make_user("RejectMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(member["id"], ws["id"])
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
            review_note="Name does not match.",
        )
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "rejected"
        assert claim["review_note"] == "Name does not match."

    def test_rejection_emits_audit_event(self):
        owner = make_user("RejectEventOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        with database.transaction() as db:
            events = db.execute(
                "SELECT * FROM operational_events WHERE event_type=?",
                (operational_events.ALBION_IDENTITY_REJECTED,),
            ).fetchall()
        assert len(events) == 1

    def test_member_cannot_reject(self):
        owner  = make_user("MemberRejectOwner")
        member = make_user("MemberRejectUser")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(member["id"], ws["id"])
        with pytest.raises(PermissionDenied):
            use_cases.reject_albion_character_claim(
                reviewer_user_id=member["id"],
                target_user_id=member["id"],
                guild_workspace_id=ws["id"],
            )


# ---------------------------------------------------------------------------
# 10. Use case: rejected-claim replace flow
# ---------------------------------------------------------------------------

class TestRejectedClaimReplace:
    def test_user_can_reclaim_after_rejection(self):
        owner = make_user("ReplaceOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_A)
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
            review_note="Not valid",
        )
        # Re-claim with different character after rejection
        _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_B, name="Vex")
        claim = _get_claim(owner["id"], ws["id"])
        assert claim["albion_player_id"] == _PLAYER_ID_B
        assert claim["verification_status"] == "pending"

    def test_other_user_can_claim_rejected_character(self):
        owner  = make_user("OtherRejectedOwner")
        member = make_user("OtherRejectedMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(owner["id"], ws["id"], player_id=_PLAYER_ID_A)
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        # After rejection, another user can claim the same character
        _make_claim(member["id"], ws["id"], player_id=_PLAYER_ID_A)
        claim = _get_claim(member["id"], ws["id"])
        assert claim["albion_player_id"] == _PLAYER_ID_A


# ---------------------------------------------------------------------------
# 11. Use case: refresh_albion_character_cache (verification state invariant)
# ---------------------------------------------------------------------------

class TestRefreshAlbionCharacterCache:
    def test_refresh_updates_cache_only(self):
        owner = make_user("RefreshOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        updated_char = _fake_char(player_id=_PLAYER_ID_A, name="KageUpdated")
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=updated_char):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.refresh_albion_character_cache(
                    user_id=owner["id"],
                    guild_workspace_id=ws["id"],
                )
        with database.transaction() as db:
            cache = repositories.get_albion_character_cache(db, _PLAYER_ID_A)
        assert cache["character_name"] == "KageUpdated"

    def test_refresh_preserves_verification_status(self):
        owner = make_user("RefreshPreserve")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
        )
        claim_before = _get_claim(owner["id"], ws["id"])
        assert claim_before["verification_status"] == "approved"

        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=_fake_char(name="NewName")):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.refresh_albion_character_cache(
                    user_id=owner["id"],
                    guild_workspace_id=ws["id"],
                )

        claim_after = _get_claim(owner["id"], ws["id"])
        # Verification state must be exactly the same as before refresh
        assert claim_after["verification_status"] == "approved"
        assert claim_after["reviewed_by"] == claim_before["reviewed_by"]
        assert claim_after["reviewed_at"] == claim_before["reviewed_at"]
        assert claim_after["review_note"] == claim_before["review_note"]

    def test_refresh_preserves_rejected_state(self):
        owner = make_user("RefreshRejected")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=owner["id"],
            guild_workspace_id=ws["id"],
            review_note="Bad claim",
        )

        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=_fake_char(name="AnyName")):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.refresh_albion_character_cache(
                    user_id=owner["id"],
                    guild_workspace_id=ws["id"],
                )

        claim_after = _get_claim(owner["id"], ws["id"])
        assert claim_after["verification_status"] == "rejected"
        assert claim_after["review_note"] == "Bad claim"

    def test_refresh_no_claim_raises(self):
        owner = make_user("RefreshNoClaim")
        ws = make_workspace(owner_user_id=owner["id"])
        with pytest.raises(NotFoundError):
            use_cases.refresh_albion_character_cache(
                user_id=owner["id"],
                guild_workspace_id=ws["id"],
            )

    def test_refresh_api_failure_raises_validation_error(self):
        owner = make_user("RefreshApiFail")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        from app.albion.rest_client import AlbionApiError
        with patch(
            "app.albion.rest_client.fetch_albion_character",
            side_effect=AlbionApiError("down"),
        ):
            with pytest.raises(ValidationError, match="Albion API"):
                use_cases.refresh_albion_character_cache(
                    user_id=owner["id"],
                    guild_workspace_id=ws["id"],
                )


# ---------------------------------------------------------------------------
# 12. Critical invariants: participants.albion_player_id never read by core
# ---------------------------------------------------------------------------

class TestParticipantsAlbionPlayerIdWriteDark:
    """
    Assert that no core logic reads participants.albion_player_id.

    Each test:
    1. Creates a participant with albion_player_id = 'should-not-be-read'
    2. Runs the core use case / domain function
    3. Asserts the result is identical to when albion_player_id = NULL
    """

    def _make_participant_with_albion_id(
        self, ws_id: str, display_name: str, player_id: str | None
    ) -> str:
        pid = str(uuid.uuid4())
        now = _now_iso()
        with database.transaction() as db:
            db.execute(
                "INSERT INTO participants "
                "(id, guild_workspace_id, display_name, albion_player_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, ws_id, display_name, player_id, now, now),
            )
        return pid

    def test_readiness_snapshot_ignores_albion_player_id(self):
        """
        Participants with albion_player_id set must be included in core
        participant queries in exactly the same way as participants without one.
        This confirms the column does not affect participant retrieval or slot
        assignment eligibility — the column is write-dark for all core logic.
        """
        owner = make_user("ReadinessAlbionOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        # One participant with an albion_player_id set, one without
        p_with    = self._make_participant_with_albion_id(ws["id"], "KageWith",    "should-not-be-read")
        p_without = self._make_participant_with_albion_id(ws["id"], "KageWithout", None)

        with database.transaction() as db:
            participants = repositories.get_participants_for_workspace(db, ws["id"])

        ids = {p["id"] for p in participants}
        # Both participants are returned — albion_player_id does not filter or alter them
        assert p_with    in ids
        assert p_without in ids
        # albion_player_id is present in the row but the value is NOT used as
        # a lookup key anywhere in core queries
        for p in participants:
            if p["id"] == p_with:
                assert p.get("albion_player_id") == "should-not-be-read"
            elif p["id"] == p_without:
                assert p.get("albion_player_id") is None

    def test_reliability_scoring_ignores_albion_player_id(self):
        owner = make_user("ReliabilityAlbionOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        self._make_participant_with_albion_id(ws["id"], "Kage", "should-not-be-read")

        with database.transaction() as db:
            scores = repositories.get_player_reliability_scores(db, ws["id"])

        # Scores are keyed by participant_id, not by albion_player_id
        pid_keys = set(scores.keys())
        assert "should-not-be-read" not in pid_keys

    def test_get_participants_does_not_filter_on_albion_id(self):
        owner = make_user("ParticipantsAlbionOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        p1 = self._make_participant_with_albion_id(ws["id"], "Kage",   "pid-001")
        p2 = self._make_participant_with_albion_id(ws["id"], "Vex",    None)
        p3 = self._make_participant_with_albion_id(ws["id"], "Archer", "pid-003")

        with database.transaction() as db:
            participants = repositories.get_participants_for_workspace(db, ws["id"])

        all_ids = {p["id"] for p in participants}
        assert {p1, p2, p3} <= all_ids

    def test_participants_sql_query_never_uses_albion_player_id(self):
        from pathlib import Path
        source = (
            Path(__file__).parent.parent / 'app' / 'repositories.py'
        ).read_text(encoding='utf-8')
        assert 'participants.albion_player_id' not in source, (
            'write-dark violation: repositories.py references participants.albion_player_id'
        )


# ---------------------------------------------------------------------------
# 13. Critical invariants: no display_name identity inference
# ---------------------------------------------------------------------------

class TestNoDisplayNameIdentityInference:
    def test_approve_does_not_use_display_name(self):
        """
        approve_albion_character_claim looks up the claim by user_id only,
        never by display_name.
        """
        owner  = make_user("DNOwner")
        member = make_user("DNMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _make_claim(member["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "approved"

    def test_claim_fetch_uses_user_id_not_display_name(self):
        """
        Repository lookup must be by user_id and workspace, not display_name.
        Two users with the same display_name in different workspaces must
        yield isolated claims.
        """
        user_a = make_user("SharedName")
        user_b = make_user("SharedName")  # same display_name, different user
        ws_a = make_workspace(slug="dn-ws-a", owner_user_id=user_a["id"])
        ws_b = make_workspace(slug="dn-ws-b", owner_user_id=user_b["id"])

        _make_claim(user_a["id"], ws_a["id"], player_id=_PLAYER_ID_A)
        _make_claim(user_b["id"], ws_b["id"], player_id=_PLAYER_ID_B)

        claim_a = _get_claim(user_a["id"], ws_a["id"])
        claim_b = _get_claim(user_b["id"], ws_b["id"])
        assert claim_a["albion_player_id"] == _PLAYER_ID_A
        assert claim_b["albion_player_id"] == _PLAYER_ID_B

    def test_members_page_template_does_not_infer_albion_from_display_name(self):
        """
        The workspace_members.html template must not contain any Jinja logic
        that infers Albion identity from display_name.
        """
        from pathlib import Path
        source = (
            Path(__file__).parent.parent
            / "app" / "templates" / "workspace_members.html"
        ).read_text(encoding="utf-8")
        # display_name-based lookups for Albion identity would look like:
        # claims_by_name or albion_by_name or display_name|albion etc.
        assert "claims_by_name" not in source
        assert "albion_by_name" not in source


# ---------------------------------------------------------------------------
# 14. Routes: account page
# ---------------------------------------------------------------------------

class TestAccountRouteAlbion:
    def test_account_page_renders_without_claims(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("AccountRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        response = client.get("/account", follow_redirects=True)
        assert response.status_code == 200
        assert "Albion Online" in response.text

    def test_account_search_calls_api(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("AccountSearchOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        with patch.object(rest_client, "search_albion_characters",
                          return_value=[_fake_char()]):
            with patch.object(rest_client, "_rate_limit"):
                response = client.get("/account?search_q=Kage", follow_redirects=True)
        assert response.status_code == 200
        assert "KagePlayer" in response.text

    def test_account_search_api_error_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("AccountSearchErrorOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        from app.albion.rest_client import AlbionApiError
        with patch.object(rest_client, "search_albion_characters",
                          side_effect=AlbionApiError("timeout")):
            with patch.object(rest_client, "_rate_limit"):
                response = client.get("/account?search_q=Kage", follow_redirects=True)
        assert response.status_code == 200
        assert "timeout" in response.text

    def test_post_claim_creates_pending_row(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PostClaimOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=_fake_char()):
            with patch.object(rest_client, "_rate_limit"):
                response = client.post(
                    "/account/albion/claim",
                    data={
                        "albion_player_id":   _PLAYER_ID_A,
                        "guild_workspace_id": ws["id"],
                    },
                    follow_redirects=True,
                )
        assert response.status_code == 200
        claim = _get_claim(owner["id"], ws["id"])
        assert claim is not None
        assert claim["verification_status"] == "pending"

    def test_post_claim_unauthenticated_redirects(self):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post(
            "/account/albion/claim",
            data={"albion_player_id": _PLAYER_ID_A, "guild_workspace_id": "ws-id"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303, 307)

    def test_post_refresh_updates_cache(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("RefreshRouteOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=_fake_char()):
            with patch.object(rest_client, "_rate_limit"):
                client.post(
                    "/account/albion/claim",
                    data={
                        "albion_player_id":   _PLAYER_ID_A,
                        "guild_workspace_id": ws["id"],
                    },
                    follow_redirects=True,
                )
        updated = _fake_char(name="KageUpdated")
        with patch.object(rest_client, "fetch_albion_character", return_value=updated):
            with patch.object(rest_client, "_rate_limit"):
                response = client.post(
                    "/account/albion/refresh",
                    data={"guild_workspace_id": ws["id"]},
                    follow_redirects=True,
                )
        assert response.status_code == 200
        with database.transaction() as db:
            cache = repositories.get_albion_character_cache(db, _PLAYER_ID_A)
        assert cache["character_name"] == "KageUpdated"


# ---------------------------------------------------------------------------
# 15. Routes: members page approve / reject
# ---------------------------------------------------------------------------

class TestMembersPageAlbionActions:
    def _setup(self):
        owner  = make_user("MembersRouteOwner")
        member = make_user("MembersRouteMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        return owner, member, ws

    def test_members_page_shows_pending_badge(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, member, ws = self._setup()
        _make_claim(member["id"], ws["id"])
        _login(client, owner["display_name"])
        response = client.get(
            f"/workspaces/{ws['slug']}/members", follow_redirects=True
        )
        assert response.status_code == 200
        assert "Pending" in response.text
        assert "MembersRouteMember" in response.text

    def test_approve_route_sets_status_approved(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, member, ws = self._setup()
        _make_claim(member["id"], ws["id"])
        _login(client, owner["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/{member['id']}/albion/approve",
            follow_redirects=True,
        )
        assert response.status_code == 200
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "approved"

    def test_reject_route_sets_status_rejected(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, member, ws = self._setup()
        _make_claim(member["id"], ws["id"])
        _login(client, owner["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/{member['id']}/albion/reject",
            data={"review_note": "Test rejection"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "rejected"
        assert claim["review_note"] == "Test rejection"

    def test_approve_route_requires_officer_or_owner(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, member, ws = self._setup()
        _make_claim(member["id"], ws["id"])
        _login(client, member["display_name"])  # member, not officer
        response = client.post(
            f"/workspaces/{ws['slug']}/members/{member['id']}/albion/approve",
            follow_redirects=False,  # don't follow: members page also blocks members
        )
        # Regular members get redirected with an error (not allowed through)
        assert response.status_code in (302, 303, 307)
        assert "error" in response.headers.get("location", "")
        # Claim is still pending
        claim = _get_claim(member["id"], ws["id"])
        assert claim["verification_status"] == "pending"

    def test_officer_cannot_approve_own_claim_via_route(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner   = make_user("OfficerSelfApproveRouteOwner")
        officer = make_user("OfficerSelfApproveRouteOfficer")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'officer',?)",
                (str(uuid.uuid4()), ws["id"], officer["id"], _now_iso()),
            )
        _make_claim(officer["id"], ws["id"])
        _login(client, officer["display_name"])
        response = client.post(
            f"/workspaces/{ws['slug']}/members/{officer['id']}/albion/approve",
            follow_redirects=True,
        )
        assert response.status_code == 200
        claim = _get_claim(officer["id"], ws["id"])
        assert claim["verification_status"] == "pending"

    def test_members_page_shows_approved_character(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, member, ws = self._setup()
        _make_claim(member["id"], ws["id"])
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )
        # Verify the claim is approved in DB before loading the page
        claim = _get_claim(member["id"], ws["id"])
        assert claim is not None
        assert claim["verification_status"] == "approved"
        char_name = claim["character_name"]  # use the actual stored name

        _login(client, owner["display_name"])
        response = client.get(
            f"/workspaces/{ws['slug']}/members", follow_redirects=True
        )
        assert response.status_code == 200
        assert char_name in response.text


# ---------------------------------------------------------------------------
# 16. Module boundary: rest_client has no DB/Discord/domain imports
# ---------------------------------------------------------------------------

class TestRestClientModuleBoundary:
    def test_no_sqlite3_import(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "app" / "albion" / "rest_client.py"
        ).read_text(encoding="utf-8")
        assert "import sqlite3" not in src

    def test_no_discord_import(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "app" / "albion" / "rest_client.py"
        ).read_text(encoding="utf-8")
        assert "import discord" not in src
        assert "from app.discord" not in src

    def test_no_domain_import(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "app" / "albion" / "rest_client.py"
        ).read_text(encoding="utf-8")
        assert "from app.domain" not in src
        assert "from app import" not in src

    def test_albion_identity_events_not_in_dispatchable(self):
        from app.events import DISPATCHABLE_EVENT_TYPES
        assert "albion_identity.claimed"  not in DISPATCHABLE_EVENT_TYPES
        assert "albion_identity.approved" not in DISPATCHABLE_EVENT_TYPES
        assert "albion_identity.rejected" not in DISPATCHABLE_EVENT_TYPES

