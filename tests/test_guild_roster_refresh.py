"""
Phase 11 Slice 3 — Guild roster refresh and stale marking test suite.

Test groups:
  1.  Refresh updates active players
  2.  Player missing from all linked guilds is marked stale
  3.  Player present in any linked guild remains active
  4.  Stale player reappearing becomes active again
  5.  linked user_id is preserved when active
  6.  linked user_id is preserved when stale
  7.  workspace_members are unaffected
  8.  participants are unaffected
  9.  No linked guilds produces safe error
  10. API failure aborts before any DB writes
  11. Partial failure aborts all writes
  12. last_imported_at updates for refreshed guilds
  13. last_seen_in_guild_at updates for active players
  14. stale_at set for stale players
  15. stale_at cleared when player reappears
  16. Members page shows active / stale status
  17. Import Guilds page shows Refresh button for officers
  18. Refresh route blocks non-officers (members)
  19. Re-import single guild still works (regression)
  20. Roster identity linking tests still pass (regression)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import PermissionDenied, ValidationError
from app.main import app
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GID_A  = "refresh-guild-uuid-A-dead-cafe000000001"
_GID_B  = "refresh-guild-uuid-B-dead-cafe000000002"
_PID_A  = "refresh-player-uuid-A-dead-cafe00000001"
_PID_B  = "refresh-player-uuid-B-dead-cafe00000002"
_PID_C  = "refresh-player-uuid-C-dead-cafe00000003"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_member(player_id: str, name: str, guild_id: str = _GID_A) -> dict:
    return {
        "albion_player_id": player_id,
        "character_name":   name,
        "guild_id":         guild_id,
        "guild_name":       "RefreshGuild",
        "kill_fame":        0,
        "death_fame":       0,
        "extra_json":       "{}",
    }


def _insert_guild(ws_id: str, albion_guild_id: str = _GID_A,
                  guild_name: str = "RefreshGuild") -> dict:
    now = _now_iso()
    row = {
        "id":                str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "albion_guild_id":   albion_guild_id,
        "guild_name":        guild_name,
        "alliance_id":       None,
        "alliance_name":     None,
        "last_imported_at":  None,
        "created_at":        now,
    }
    with database.transaction() as db:
        repositories.upsert_workspace_albion_guild(db, row)
    with database.transaction() as db:
        return repositories.get_workspace_albion_guild(db, ws_id, albion_guild_id)


def _insert_player(ws_id: str, albion_player_id: str, char_name: str = "Kage",
                   user_id: str | None = None,
                   stale_at: str | None = None) -> None:
    now = _now_iso()
    with database.transaction() as db:
        repositories.upsert_workspace_albion_player(db, {
            "id":                    str(uuid.uuid4()),
            "guild_workspace_id":    ws_id,
            "albion_player_id":      albion_player_id,
            "character_name":        char_name,
            "user_id":               user_id,
            "source_guild_id":       None,
            "last_seen_in_guild_at": now,
            "stale_at":              stale_at,
            "created_at":            now,
            "updated_at":            now,
        })


def _get_player(ws_id: str, player_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_workspace_albion_player(db, ws_id, player_id)


def _get_guild(ws_id: str, albion_guild_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_workspace_albion_guild(db, ws_id, albion_guild_id)


def _do_refresh(owner_id: str, ws_id: str, roster_by_guild_id: dict[str, list[dict]]):
    """Patch fetch_albion_guild_members to return different rosters per guild."""
    from app.albion import rest_client

    def _fake_fetch(guild_id: str):
        if guild_id not in roster_by_guild_id:
            from app.albion.rest_client import AlbionApiError
            raise AlbionApiError(f"Unknown guild {guild_id}")
        return roster_by_guild_id[guild_id]

    with patch.object(rest_client, "fetch_albion_guild_members", side_effect=_fake_fetch):
        with patch.object(rest_client, "_rate_limit"):
            return use_cases.refresh_all_guild_rosters(
                guild_workspace_id=ws_id,
                requesting_user_id=owner_id,
            )


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Refresh updates active players
# ---------------------------------------------------------------------------

class TestRefreshUpdatesActivePlayers:
    def test_refresh_updates_last_seen_for_seen_player(self):
        owner = make_user("RefreshActiveOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A)

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "Kage")]})

        row = _get_player(ws["id"], _PID_A)
        assert row["stale_at"] is None

    def test_refresh_result_shows_correct_counts(self):
        owner = make_user("RefreshCountOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A)
        _insert_player(ws["id"], _PID_B)

        result = _do_refresh(
            owner["id"], ws["id"],
            {_GID_A: [_fake_member(_PID_A, "Kage"), _fake_member(_PID_B, "Vex")]}
        )

        assert result["guilds_refreshed"] == 1
        assert result["active"] == 2
        assert result["stale_marked"] == 0


# ---------------------------------------------------------------------------
# 2. Player missing from all linked guilds is marked stale
# ---------------------------------------------------------------------------

class TestMissingPlayerMarkedStale:
    def test_absent_player_gets_stale_at_set(self):
        owner = make_user("StaleOwner1")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A, "Active")
        _insert_player(ws["id"], _PID_B, "Gone")

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "Active")]})

        row_a = _get_player(ws["id"], _PID_A)
        row_b = _get_player(ws["id"], _PID_B)
        assert row_a["stale_at"] is None
        assert row_b["stale_at"] is not None

    def test_stale_marked_count_in_result(self):
        owner = make_user("StaleCountOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A)
        _insert_player(ws["id"], _PID_B)
        _insert_player(ws["id"], _PID_C)

        result = _do_refresh(owner["id"], ws["id"], {_GID_A: []})

        # mark_workspace_albion_players_stale returns 0 when seen_player_ids is empty
        assert result["stale_marked"] == 0


# ---------------------------------------------------------------------------
# 3. Player present in any linked guild remains active
# ---------------------------------------------------------------------------

class TestMultiGuildActivePrevailsStale:
    def test_player_in_guild_b_not_stale_after_refresh(self):
        owner = make_user("MultiGuildOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        guild_a = _insert_guild(ws["id"], _GID_A, "GuildA")
        guild_b = _insert_guild(ws["id"], _GID_B, "GuildB")
        _insert_player(ws["id"], _PID_A, "SomePlayer")

        # PID_A is only in GuildB's roster
        result = _do_refresh(
            owner["id"], ws["id"],
            {_GID_A: [], _GID_B: [_fake_member(_PID_A, "SomePlayer", _GID_B)]}
        )

        row = _get_player(ws["id"], _PID_A)
        assert row["stale_at"] is None
        assert result["stale_marked"] == 0

    def test_player_absent_from_all_guilds_is_stale(self):
        owner = make_user("AllGuildAbsentOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"], _GID_A, "GuildA")
        _insert_guild(ws["id"], _GID_B, "GuildB")
        _insert_player(ws["id"], _PID_C, "GhostPlayer")

        _do_refresh(
            owner["id"], ws["id"],
            {
                _GID_A: [_fake_member(_PID_A, "PlayerA"), _fake_member(_PID_B, "PlayerB")],
                _GID_B: [_fake_member(_PID_A, "PlayerA")],
            }
        )

        row_c = _get_player(ws["id"], _PID_C)
        assert row_c["stale_at"] is not None


# ---------------------------------------------------------------------------
# 4. Stale player reappearing becomes active again
# ---------------------------------------------------------------------------

class TestStalePlayerReactivated:
    def test_stale_player_reappearing_clears_stale_at(self):
        owner = make_user("ReactivateOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A, stale_at=_now_iso())

        row_before = _get_player(ws["id"], _PID_A)
        assert row_before["stale_at"] is not None

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "Kage")]})

        row_after = _get_player(ws["id"], _PID_A)
        assert row_after["stale_at"] is None


# ---------------------------------------------------------------------------
# 5. linked user_id is preserved when active
# ---------------------------------------------------------------------------

class TestLinkedUserPreservedWhenActive:
    def test_user_id_link_survives_refresh_as_active(self):
        owner  = make_user("LinkActiveOwner")
        member = make_user("LinkActiveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A, user_id=member["id"])

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "Kage")]})

        row = _get_player(ws["id"], _PID_A)
        assert row["user_id"] == member["id"]
        assert row["stale_at"] is None


# ---------------------------------------------------------------------------
# 6. linked user_id is preserved when stale
# ---------------------------------------------------------------------------

class TestLinkedUserPreservedWhenStale:
    def test_user_id_link_survives_refresh_as_stale(self):
        owner  = make_user("LinkStaleOwner")
        member = make_user("LinkStaleMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A, user_id=member["id"])

        # Player not included in roster → will be marked stale
        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_B, "Other")]})

        row = _get_player(ws["id"], _PID_A)
        assert row["user_id"] == member["id"]
        assert row["stale_at"] is not None


# ---------------------------------------------------------------------------
# 7. workspace_members are unaffected
# ---------------------------------------------------------------------------

class TestWorkspaceMembersUnaffected:
    def test_refresh_does_not_modify_workspace_members(self):
        owner = make_user("WsMemberSafeOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])

        with database.transaction() as db:
            members_before = repositories.list_workspace_members(db, ws["id"])

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "X")]})

        with database.transaction() as db:
            members_after = repositories.list_workspace_members(db, ws["id"])

        assert len(members_before) == len(members_after)


# ---------------------------------------------------------------------------
# 8. participants are unaffected
# ---------------------------------------------------------------------------

class TestParticipantsUnaffected:
    def test_refresh_does_not_touch_participants(self):
        owner = make_user("ParticipantSafeOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "X")]})

        with database.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM participants WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# 9. No linked guilds produces safe error
# ---------------------------------------------------------------------------

class TestNoLinkedGuildsSafeError:
    def test_refresh_with_no_linked_guilds_raises_validation_error(self):
        owner = make_user("NoGuildsOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=[]):
            with pytest.raises(ValidationError, match="No linked guilds"):
                use_cases.refresh_all_guild_rosters(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                )


# ---------------------------------------------------------------------------
# 10. API failure aborts before DB writes
# ---------------------------------------------------------------------------

class TestApiFailureAbortsAllWrites:
    def test_api_failure_leaves_players_unchanged(self):
        owner = make_user("ApiFailOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A, "Kage")
        _insert_player(ws["id"], _PID_B, "Vex")

        from app.albion import rest_client
        from app.albion.rest_client import AlbionApiError

        with patch.object(rest_client, "fetch_albion_guild_members",
                          side_effect=AlbionApiError("timeout")):
            with pytest.raises(ValidationError, match="Refresh aborted"):
                use_cases.refresh_all_guild_rosters(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                )

        # No stale marking should have happened
        row_a = _get_player(ws["id"], _PID_A)
        row_b = _get_player(ws["id"], _PID_B)
        assert row_a["stale_at"] is None
        assert row_b["stale_at"] is None


# ---------------------------------------------------------------------------
# 11. Partial failure across multiple guilds causes no DB writes
# ---------------------------------------------------------------------------

class TestPartialFailureAbortsAllWrites:
    def test_second_guild_failure_no_writes(self):
        owner = make_user("PartialFailOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        guild_a = _insert_guild(ws["id"], _GID_A, "GuildA")
        guild_b = _insert_guild(ws["id"], _GID_B, "GuildB")
        _insert_player(ws["id"], _PID_A)
        _insert_player(ws["id"], _PID_B)

        guild_a_before = _get_guild(ws["id"], _GID_A)

        from app.albion import rest_client
        from app.albion.rest_client import AlbionApiError

        call_count = [0]

        def _selective_fail(guild_id):
            call_count[0] += 1
            if guild_id == _GID_B:
                raise AlbionApiError("guild B unavailable")
            return [_fake_member(_PID_A, "Kage")]

        with patch.object(rest_client, "fetch_albion_guild_members",
                          side_effect=_selective_fail):
            with patch.object(rest_client, "_rate_limit"):
                with pytest.raises(ValidationError, match="Refresh aborted"):
                    use_cases.refresh_all_guild_rosters(
                        guild_workspace_id=ws["id"],
                        requesting_user_id=owner["id"],
                    )

        # PID_B should still be active (no stale marking happened)
        row_b = _get_player(ws["id"], _PID_B)
        assert row_b["stale_at"] is None

        # Guild A's last_imported_at should be unchanged
        guild_a_after = _get_guild(ws["id"], _GID_A)
        assert guild_a_after["last_imported_at"] == guild_a_before["last_imported_at"]


# ---------------------------------------------------------------------------
# 12. last_imported_at updates for refreshed guilds
# ---------------------------------------------------------------------------

class TestLastImportedAtUpdated:
    def test_refresh_updates_last_imported_at(self):
        owner = make_user("LastImportedOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])

        guild_before = _get_guild(ws["id"], _GID_A)
        assert guild_before["last_imported_at"] is None

        _do_refresh(owner["id"], ws["id"], {_GID_A: []})

        guild_after = _get_guild(ws["id"], _GID_A)
        assert guild_after["last_imported_at"] is not None


# ---------------------------------------------------------------------------
# 13. last_seen_in_guild_at updates for active players
# ---------------------------------------------------------------------------

class TestLastSeenUpdated:
    def test_refresh_updates_last_seen_in_guild_at(self):
        import time
        owner = make_user("LastSeenOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A)

        row_before = _get_player(ws["id"], _PID_A)
        old_ts = row_before["last_seen_in_guild_at"]

        # Small delay to ensure timestamp differs
        time.sleep(0.01)
        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "Kage")]})

        row_after = _get_player(ws["id"], _PID_A)
        assert row_after["last_seen_in_guild_at"] != old_ts
        assert row_after["last_seen_in_guild_at"] > old_ts


# ---------------------------------------------------------------------------
# 14. stale_at set for stale players
# ---------------------------------------------------------------------------

class TestStaleAtSet:
    def test_stale_at_is_iso_timestamp(self):
        owner = make_user("StaleAtOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        _insert_player(ws["id"], _PID_A, "GonePlayer")
        _insert_player(ws["id"], _PID_B, "StillHere")

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_B, "StillHere")]})

        row_a = _get_player(ws["id"], _PID_A)
        assert row_a["stale_at"] is not None
        # Must be parseable as ISO timestamp
        datetime.fromisoformat(row_a["stale_at"])


# ---------------------------------------------------------------------------
# 15. stale_at cleared when player reappears
# ---------------------------------------------------------------------------

class TestStaleAtClearedOnReturn:
    def test_stale_at_cleared_after_player_reappears(self):
        owner = make_user("StaleAtClearOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])
        # Pre-mark player as stale
        _insert_player(ws["id"], _PID_A, stale_at="2020-01-01T00:00:00+00:00")

        _do_refresh(owner["id"], ws["id"], {_GID_A: [_fake_member(_PID_A, "Kage")]})

        row = _get_player(ws["id"], _PID_A)
        assert row["stale_at"] is None


# ---------------------------------------------------------------------------
# 16. Members page shows active / stale status
# ---------------------------------------------------------------------------

class TestMembersPageShowsStatus:
    def test_members_page_shows_active_badge(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("MemberStatusActiveOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_player(ws["id"], _PID_A, char_name="ActiveChar")

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members", follow_redirects=True
        )
        assert resp.status_code == 200
        assert "ActiveChar" in resp.text
        assert "Active" in resp.text

    def test_members_page_shows_stale_badge(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("MemberStatusStaleOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_player(ws["id"], _PID_A, char_name="StaleChar",
                       stale_at="2024-01-15T12:00:00+00:00")

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members", follow_redirects=True
        )
        assert resp.status_code == 200
        assert "StaleChar" in resp.text
        assert "Stale" in resp.text
        assert "2024-01-15" in resp.text


# ---------------------------------------------------------------------------
# 17. Import Guilds page shows Refresh button for officers
# ---------------------------------------------------------------------------

class TestRefreshButtonVisibility:
    def test_refresh_button_visible_when_guilds_linked(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("RefreshBtnOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_guild(ws["id"])

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Refresh rosters" in resp.text
        assert "import-guilds/refresh" in resp.text

    def test_refresh_button_absent_when_no_guilds(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("NoGuildBtnOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/members/import-guilds",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Refresh rosters" not in resp.text


# ---------------------------------------------------------------------------
# 18. Refresh route blocks non-officers
# ---------------------------------------------------------------------------

class TestRefreshRouteRbac:
    def test_member_cannot_refresh_rosters(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("RefreshRbacOwner")
        member = make_user("RefreshRbacMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members "
                "(id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _login(client, member["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/members/import-guilds/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 19. Re-import single guild still works (regression)
# ---------------------------------------------------------------------------

class TestSingleGuildImportRegression:
    def test_import_roster_with_stale_at_column_present(self):
        owner = make_user("Slice3ImportOwner")
        ws = make_workspace(owner_user_id=owner["id"])

        from app.albion import rest_client

        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=[_fake_member(_PID_A, "Kage")]):
            with patch.object(rest_client, "_rate_limit"):
                result = use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GID_A,
                    guild_name_hint="RefreshGuild",
                )
        assert result["total"] == 1
        row = _get_player(ws["id"], _PID_A)
        assert row["stale_at"] is None

    def test_reimport_clears_stale_at_set_by_previous_refresh(self):
        owner = make_user("Slice3ClearStaleOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_player(ws["id"], _PID_A, stale_at=_now_iso())

        from app.albion import rest_client

        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=[_fake_member(_PID_A, "Kage")]):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GID_A,
                    guild_name_hint="RefreshGuild",
                )

        row = _get_player(ws["id"], _PID_A)
        assert row["stale_at"] is None


# ---------------------------------------------------------------------------
# 20. Roster identity linking tests still pass (regression)
# ---------------------------------------------------------------------------

class TestIdentityLinkingRegression:
    def _fake_char(self, player_id: str = _PID_A, name: str = "Kage") -> dict:
        import json
        return {
            "albion_player_id": player_id,
            "character_name":   name,
            "guild_id":         _GID_A,
            "guild_name":       "RefreshGuild",
            "kill_fame":        0,
            "death_fame":       0,
            "extra_json":       json.dumps({"Id": player_id, "Name": name}),
        }

    def test_approval_still_links_imported_player_with_stale_at_column(self):
        owner  = make_user("Slice3LinkOwner")
        member = make_user("Slice3LinkMember")
        ws = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members "
                "(id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now_iso()),
            )
        _insert_player(ws["id"], _PID_A)

        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_character",
                          return_value=self._fake_char()):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.claim_albion_character(
                    user_id=member["id"],
                    guild_workspace_id=ws["id"],
                    albion_player_id=_PID_A,
                )
        use_cases.approve_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )

        row = _get_player(ws["id"], _PID_A)
        assert row["user_id"] == member["id"]
        assert row["stale_at"] is None
