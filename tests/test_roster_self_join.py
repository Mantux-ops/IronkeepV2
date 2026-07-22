"""
Albion roster self-join + automatic roster sync test suite.

Feature: after an officer imports an Albion guild roster, a Discord user whose
display name matches an unlinked roster character can self-join the workspace
(no manual officer add), and a scheduler job keeps rosters fresh.

Test groups:
  1. Repository: find_unlinked_roster_players_by_name (match/case/stale/linked)
  2. Repository: find_roster_join_candidates_for_user (member exclusion)
  3. Repository: get_workspaces_needing_roster_sync (staleness)
  4. Use case: join_workspace_via_roster_match (happy path + errors)
  5. Use case: sync_workspace_rosters_system (no RBAC, no membership grant)
  6. Scheduler job: sync_albion_guild_rosters
  7. Routes: home page shows candidate; POST join-via-roster works
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, ValidationError
from app.main import app
from tests.conftest import make_user, make_workspace

_GUILD_ID = "guild-uuid-selfjoin-000000000000000001"
_PID_1 = "player-selfjoin-0000000000000000000001"
_PID_2 = "player-selfjoin-0000000000000000000002"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_member(player_id: str, name: str) -> dict:
    return {
        "albion_player_id": player_id,
        "character_name":   name,
        "guild_id":         _GUILD_ID,
        "guild_name":       "Iron Keep",
        "kill_fame":        1000,
        "death_fame":       100,
        "extra_json":       "{}",
    }


def _import_roster(ws_id: str, officer_id: str, members: list[dict],
                   guild_id: str = _GUILD_ID) -> dict:
    """Import a guild roster with the Albion API mocked."""
    from app.albion import rest_client
    with patch.object(rest_client, "fetch_albion_guild_members", return_value=members):
        with patch.object(rest_client, "_rate_limit"):
            return use_cases.import_albion_guild_roster(
                guild_workspace_id=ws_id,
                requesting_user_id=officer_id,
                albion_guild_id=guild_id,
                guild_name_hint="Iron Keep",
            )


def _seed_ws_with_roster(members: list[dict], slug: str = "sj-ws"):
    """Create a workspace (owned by a separate user) with an imported roster."""
    owner = make_user(display_name="Roster Owner")
    ws = make_workspace(owner_user_id=owner["id"], slug=slug, name="Iron Keep WS")
    _import_roster(ws["id"], owner["id"], members)
    return owner, ws


# ---------------------------------------------------------------------------
# 1. Repository: find_unlinked_roster_players_by_name
# ---------------------------------------------------------------------------

class TestFindUnlinkedRosterPlayersByName:

    def test_exact_match(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        with database.transaction() as db:
            rows = repositories.find_unlinked_roster_players_by_name(db, ws["id"], "Kage")
        assert len(rows) == 1
        assert rows[0]["albion_player_id"] == _PID_1

    def test_case_insensitive_match(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        with database.transaction() as db:
            rows = repositories.find_unlinked_roster_players_by_name(db, ws["id"], "kAgE")
        assert len(rows) == 1

    def test_no_match_returns_empty(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        with database.transaction() as db:
            rows = repositories.find_unlinked_roster_players_by_name(db, ws["id"], "Nobody")
        assert rows == []

    def test_linked_player_excluded(self):
        owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        # Link the roster player to some user.
        u = make_user(display_name="Someone Else")
        with database.transaction() as db:
            repositories.link_workspace_albion_player_to_user(
                db, guild_workspace_id=ws["id"], albion_player_id=_PID_1, user_id=u["id"]
            )
        with database.transaction() as db:
            rows = repositories.find_unlinked_roster_players_by_name(db, ws["id"], "Kage")
        assert rows == []

    def test_stale_player_excluded(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        with database.transaction() as db:
            db.execute(
                "UPDATE workspace_albion_players SET stale_at=? WHERE albion_player_id=?",
                (_now_iso(), _PID_1),
            )
        with database.transaction() as db:
            rows = repositories.find_unlinked_roster_players_by_name(db, ws["id"], "Kage")
        assert rows == []


# ---------------------------------------------------------------------------
# 2. Repository: find_roster_join_candidates_for_user
# ---------------------------------------------------------------------------

class TestFindRosterJoinCandidates:

    def test_candidate_found_for_matching_name(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        user = make_user(display_name="Kage")
        with database.transaction() as db:
            cands = repositories.find_roster_join_candidates_for_user(
                db, user["id"], user["display_name"]
            )
        assert len(cands) == 1
        assert cands[0]["slug"] == ws["slug"]
        assert cands[0]["character_name"] == "Kage"

    def test_existing_member_not_a_candidate(self):
        owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        # add_workspace_member and make_user both key off the dev provider id
        # derived from the display name, so they resolve to the same user.
        user = make_user(display_name="Kage")
        use_cases.add_workspace_member(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            display_name="Kage", role="member",
        )
        with database.transaction() as db:
            cands = repositories.find_roster_join_candidates_for_user(
                db, user["id"], user["display_name"]
            )
        # Already a member → not offered as a join candidate.
        assert cands == []

    def test_no_candidate_when_name_differs(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        user = make_user(display_name="TotallyDifferent")
        with database.transaction() as db:
            cands = repositories.find_roster_join_candidates_for_user(
                db, user["id"], user["display_name"]
            )
        assert cands == []


# ---------------------------------------------------------------------------
# 3. Repository: get_workspaces_needing_roster_sync
# ---------------------------------------------------------------------------

class TestGetWorkspacesNeedingRosterSync:

    def test_recently_imported_not_returned(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        # last_imported_at is 'now' → not stale for a 6h threshold.
        threshold = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        with database.transaction() as db:
            rows = repositories.get_workspaces_needing_roster_sync(db, threshold)
        assert all(r["id"] != ws["id"] for r in rows)

    def test_stale_import_returned(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with database.transaction() as db:
            db.execute(
                "UPDATE workspace_albion_guilds SET last_imported_at=? WHERE guild_workspace_id=?",
                (old, ws["id"]),
            )
        threshold = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        with database.transaction() as db:
            rows = repositories.get_workspaces_needing_roster_sync(db, threshold)
        assert any(r["id"] == ws["id"] for r in rows)

    def test_workspace_without_linked_guild_not_returned(self):
        owner = make_user(display_name="No Guild Owner")
        ws = make_workspace(owner_user_id=owner["id"], slug="no-guild-ws")
        threshold = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        with database.transaction() as db:
            rows = repositories.get_workspaces_needing_roster_sync(db, threshold)
        assert all(r["id"] != ws["id"] for r in rows)


# ---------------------------------------------------------------------------
# 4. Use case: join_workspace_via_roster_match
# ---------------------------------------------------------------------------

class TestJoinWorkspaceViaRosterMatch:

    def test_happy_path_creates_membership_and_links(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        user = make_user(display_name="Kage")

        result = use_cases.join_workspace_via_roster_match(
            user_id=user["id"], guild_workspace_id=ws["id"]
        )
        assert result["character_name"] == "Kage"

        with database.transaction() as db:
            mem = repositories.get_workspace_membership(db, ws["id"], user["id"])
            assert mem is not None
            assert mem["role"] == "member"
            # roster player linked to the user
            players = repositories.list_workspace_albion_players(db, ws["id"])
            linked = [p for p in players if p["albion_player_id"] == _PID_1][0]
            assert linked["user_id"] == user["id"]
            # approved identity created
            ident = repositories.get_player_game_identity_for_user(db, user["id"], ws["id"])
            assert ident is not None
            assert ident["verification_status"] == "approved"
            assert ident["albion_player_id"] == _PID_1

    def test_case_insensitive_join(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        user = make_user(display_name="kage")  # lowercase
        result = use_cases.join_workspace_via_roster_match(
            user_id=user["id"], guild_workspace_id=ws["id"]
        )
        assert result["character_name"] == "Kage"

    def test_no_match_raises_validation_error(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        user = make_user(display_name="Stranger")
        with pytest.raises(ValidationError, match="No unlinked guild-roster character"):
            use_cases.join_workspace_via_roster_match(
                user_id=user["id"], guild_workspace_id=ws["id"]
            )
        # No membership was created.
        with database.transaction() as db:
            assert repositories.get_workspace_membership(db, ws["id"], user["id"]) is None

    def test_already_member_raises_conflict(self):
        owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        user = make_user(display_name="Kage")
        use_cases.join_workspace_via_roster_match(
            user_id=user["id"], guild_workspace_id=ws["id"]
        )
        with pytest.raises(ConflictError, match="already a member"):
            use_cases.join_workspace_via_roster_match(
                user_id=user["id"], guild_workspace_id=ws["id"]
            )

    def test_ambiguous_match_raises_validation_error(self):
        # Two roster characters with the same name → ambiguous, refuse.
        _owner, ws = _seed_ws_with_roster([
            _fake_member(_PID_1, "Kage"),
            _fake_member(_PID_2, "Kage"),
        ])
        user = make_user(display_name="Kage")
        with pytest.raises(ValidationError, match="Multiple roster characters"):
            use_cases.join_workspace_via_roster_match(
                user_id=user["id"], guild_workspace_id=ws["id"]
            )
        with database.transaction() as db:
            assert repositories.get_workspace_membership(db, ws["id"], user["id"]) is None

    def test_unknown_workspace_raises_not_found(self):
        user = make_user(display_name="Kage")
        with pytest.raises(NotFoundError):
            use_cases.join_workspace_via_roster_match(
                user_id=user["id"], guild_workspace_id="does-not-exist"
            )

    def test_stale_roster_player_cannot_be_joined(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        with database.transaction() as db:
            db.execute(
                "UPDATE workspace_albion_players SET stale_at=? WHERE albion_player_id=?",
                (_now_iso(), _PID_1),
            )
        user = make_user(display_name="Kage")
        with pytest.raises(ValidationError, match="No unlinked guild-roster character"):
            use_cases.join_workspace_via_roster_match(
                user_id=user["id"], guild_workspace_id=ws["id"]
            )


# ---------------------------------------------------------------------------
# 5. Use case: sync_workspace_rosters_system
# ---------------------------------------------------------------------------

class TestSyncWorkspaceRostersSystem:

    def test_system_sync_updates_roster_without_auth(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        # Sync with a new member added and Kage still present.
        new_members = [_fake_member(_PID_1, "Kage"), _fake_member(_PID_2, "Vex")]
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=new_members):
            with patch.object(rest_client, "_rate_limit"):
                summary = use_cases.sync_workspace_rosters_system(ws["id"])
        assert summary["active"] == 2
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert {p["albion_player_id"] for p in players} == {_PID_1, _PID_2}

    def test_system_sync_does_not_grant_membership(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=[_fake_member(_PID_1, "Kage")]):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.sync_workspace_rosters_system(ws["id"])
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
            members = repositories.list_workspace_members(db, ws["id"])
        # Roster player is NOT linked and only the owner is a member.
        assert all(p["user_id"] is None for p in players)
        assert len(members) == 1  # owner only

    def test_system_sync_marks_absent_player_stale(self):
        _owner, ws = _seed_ws_with_roster([
            _fake_member(_PID_1, "Kage"), _fake_member(_PID_2, "Vex")
        ])
        # Vex leaves the guild.
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=[_fake_member(_PID_1, "Kage")]):
            with patch.object(rest_client, "_rate_limit"):
                summary = use_cases.sync_workspace_rosters_system(ws["id"])
        assert summary["stale_marked"] == 1


# ---------------------------------------------------------------------------
# 6. Scheduler job: sync_albion_guild_rosters
# ---------------------------------------------------------------------------

class TestSyncAlbionGuildRostersJob:

    def test_job_syncs_stale_workspace(self):
        from app.scheduler import jobs
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with database.transaction() as db:
            db.execute(
                "UPDATE workspace_albion_guilds SET last_imported_at=? WHERE guild_workspace_id=?",
                (old, ws["id"]),
            )
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members",
                          return_value=[_fake_member(_PID_1, "Kage"),
                                        _fake_member(_PID_2, "Vex")]):
            with patch.object(rest_client, "_rate_limit"):
                result = jobs.sync_albion_guild_rosters()
        assert result["synced"] >= 1
        assert result["errors"] == 0
        assert result["players_active"] >= 2

    def test_job_skips_fresh_workspace(self):
        from app.scheduler import jobs
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        # last_imported_at is now → not stale → job does not touch it.
        from app.albion import rest_client
        with patch.object(rest_client, "fetch_albion_guild_members") as fetch_mock:
            with patch.object(rest_client, "_rate_limit"):
                result = jobs.sync_albion_guild_rosters()
        assert result["workspaces_checked"] == 0
        fetch_mock.assert_not_called()

    def test_job_counts_errors_without_aborting(self):
        from app.scheduler import jobs
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with database.transaction() as db:
            db.execute(
                "UPDATE workspace_albion_guilds SET last_imported_at=? WHERE guild_workspace_id=?",
                (old, ws["id"]),
            )
        from app.albion import rest_client
        from app.albion.rest_client import AlbionApiError
        with patch.object(rest_client, "fetch_albion_guild_members",
                          side_effect=AlbionApiError("boom")):
            with patch.object(rest_client, "_rate_limit"):
                result = jobs.sync_albion_guild_rosters()
        assert result["errors"] == 1
        assert result["synced"] == 0


# ---------------------------------------------------------------------------
# 7. Routes: home page candidate + POST join-via-roster
# ---------------------------------------------------------------------------

class TestRosterJoinRoutes:

    def _login(self, client: TestClient, display_name: str) -> None:
        client.post("/login", data={"display_name": display_name, "next": "/"},
                    follow_redirects=True)

    def test_home_shows_join_candidate(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        # Ensure a dev user named Kage exists so login maps to the same identity.
        make_user(display_name="Kage")
        client = TestClient(app)
        self._login(client, "Kage")
        resp = client.get("/workspaces")
        assert resp.status_code == 200
        assert "We found your character" in resp.text
        assert "Iron Keep WS" in resp.text

    def test_post_join_grants_access(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        make_user(display_name="Kage")
        client = TestClient(app)
        self._login(client, "Kage")
        resp = client.post(
            f"/workspaces/{ws['slug']}/join-via-roster", follow_redirects=False
        )
        assert resp.status_code == 303
        assert resp.headers["location"].startswith(f"/workspaces/{ws['slug']}")
        # The workspace now appears in the user's workspace list.
        home = client.get("/workspaces")
        assert "Iron Keep WS" in home.text

    def test_post_join_no_match_redirects_with_error(self):
        _owner, ws = _seed_ws_with_roster([_fake_member(_PID_1, "Kage")])
        make_user(display_name="Interloper")
        client = TestClient(app)
        self._login(client, "Interloper")
        resp = client.post(
            f"/workspaces/{ws['slug']}/join-via-roster", follow_redirects=False
        )
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/workspaces?error=")
