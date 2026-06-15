"""
Phase 11 Slice 2 — Roster identity linking test suite.

When an Albion character claim is approved, if workspace_albion_players
contains a row for the same (guild_workspace_id, albion_player_id),
workspace_albion_players.user_id is automatically set.

Test groups:
  1.  Approval links matching workspace_albion_players row
  2.  Pending claim does NOT link
  3.  Rejected claim does NOT link
  4.  Officer approval path links the row
  5.  Owner self-approval path links the row
  6.  No imported row — no failure, no side effects
  7.  Already linked to same user — idempotent (no error)
  8.  Already linked to different user — no overwrite
  9.  Same albion_player_id in different workspace is not linked
  10. Same character name but different albion_player_id is not linked
  11. Re-import after approval preserves linked user_id
  12. Members page shows linked user indicator
  13. Members page shows unlinked state for unlinked players
  14. workspace_members are not created by linking
  15. participants are not modified by linking
  16. Existing Albion identity tests still pass (regression guard)
  17. Existing guild roster import tests still pass (regression guard)
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

_GUILD_ID_A  = "link-guild-uuid-0001-dead-cafe00000001"
_GUILD_ID_B  = "link-guild-uuid-0002-dead-cafe00000002"
_PLAYER_ID_A = "link-player-uuid-A-dead-cafe000000001"
_PLAYER_ID_B = "link-player-uuid-B-dead-cafe000000002"
_PLAYER_ID_C = "link-player-uuid-C-dead-cafe000000003"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_char(player_id: str = _PLAYER_ID_A, name: str = "Kage") -> dict:
    import json
    return {
        "albion_player_id": player_id,
        "character_name":   name,
        "guild_id":         _GUILD_ID_A,
        "guild_name":       "Iron Keep",
        "kill_fame":        1000,
        "death_fame":       50,
        "extra_json":       json.dumps({"Id": player_id, "Name": name}),
    }


def _add_officer(ws_id: str, user_id: str) -> None:
    with database.transaction() as db:
        db.execute(
            "UPDATE workspace_members SET role='officer' "
            "WHERE guild_workspace_id=? AND user_id=?",
            (ws_id, user_id),
        )


def _add_member_row(ws_id: str, user_id: str) -> None:
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members "
            "(id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,'member',?)",
            (str(uuid.uuid4()), ws_id, user_id, _now_iso()),
        )


def _insert_imported_player(
    ws_id: str,
    albion_player_id: str,
    char_name: str = "Kage",
    user_id: str | None = None,
    guild_id: str | None = None,
) -> None:
    now = _now_iso()
    with database.transaction() as db:
        # Ensure guild row exists for FK if needed (nullable, so skipping is fine)
        repositories.upsert_workspace_albion_player(db, {
            "id":                    str(uuid.uuid4()),
            "guild_workspace_id":    ws_id,
            "albion_player_id":      albion_player_id,
            "character_name":        char_name,
            "user_id":               user_id,
            "source_guild_id":       None,
            "last_seen_in_guild_at": now,
            "created_at":            now,
            "updated_at":            now,
        })


def _make_claim(user_id: str, ws_id: str, player_id: str = _PLAYER_ID_A,
                name: str = "Kage") -> None:
    from app.albion import rest_client
    with patch.object(rest_client, "fetch_albion_character",
                      return_value=_fake_char(player_id, name)):
        with patch.object(rest_client, "_rate_limit"):
            use_cases.claim_albion_character(
                user_id=user_id,
                guild_workspace_id=ws_id,
                albion_player_id=player_id,
            )


def _approve(reviewer_id: str, target_id: str, ws_id: str) -> None:
    use_cases.approve_albion_character_claim(
        reviewer_user_id=reviewer_id,
        target_user_id=target_id,
        guild_workspace_id=ws_id,
    )


def _get_imported_player(ws_id: str, player_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_workspace_albion_player(db, ws_id, player_id)


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Approval links matching workspace_albion_players row
# ---------------------------------------------------------------------------

class TestApprovalLinksImportedPlayer:
    def test_approval_sets_user_id_on_imported_player(self):
        owner  = make_user("LinkApproveOwner")
        member = make_user("LinkApproveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row is not None
        assert row["user_id"] == member["id"]

    def test_approval_does_not_create_extra_player_rows(self):
        owner  = make_user("LinkNoExtraOwner")
        member = make_user("LinkNoExtraMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert len(players) == 1

    def test_link_uses_albion_player_id_not_name(self):
        """Link is keyed on albion_player_id, not character_name."""
        owner  = make_user("LinkByIdOwner")
        member = make_user("LinkByIdMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        # Import a player with a DIFFERENT character name but same player_id
        _insert_imported_player(ws["id"], _PLAYER_ID_A, char_name="DifferentName")
        _make_claim(member["id"], ws["id"], player_id=_PLAYER_ID_A, name="Kage")
        _approve(owner["id"], member["id"], ws["id"])
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == member["id"]


# ---------------------------------------------------------------------------
# 2. Pending claim does NOT link
# ---------------------------------------------------------------------------

class TestPendingClaimDoesNotLink:
    def test_pending_claim_leaves_user_id_null(self):
        owner  = make_user("PendingLinkOwner")
        member = make_user("PendingLinkMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        # Do NOT approve
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row is not None
        assert row["user_id"] is None

    def test_pending_claim_then_reject_leaves_user_id_null(self):
        owner  = make_user("PendingRejectOwner")
        member = make_user("PendingRejectMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] is None


# ---------------------------------------------------------------------------
# 3. Rejected claim does NOT link (covered above; separate explicit test)
# ---------------------------------------------------------------------------

class TestRejectedClaimDoesNotLink:
    def test_rejection_does_not_link(self):
        owner  = make_user("RejectNoLinkOwner")
        member = make_user("RejectNoLinkMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        use_cases.reject_albion_character_claim(
            reviewer_user_id=owner["id"],
            target_user_id=member["id"],
            guild_workspace_id=ws["id"],
        )
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] is None


# ---------------------------------------------------------------------------
# 4. Officer approval path links the row
# ---------------------------------------------------------------------------

class TestOfficerApprovalLinks:
    def test_officer_approving_member_claim_links_player(self):
        owner   = make_user("OfficerLinkOwner")
        officer = make_user("OfficerLinkOfficer")
        member  = make_user("OfficerLinkMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], officer["id"])
        _add_member_row(ws["id"], member["id"])
        _add_officer(ws["id"], officer["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(officer["id"], member["id"], ws["id"])
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == member["id"]


# ---------------------------------------------------------------------------
# 5. Owner self-approval path links the row
# ---------------------------------------------------------------------------

class TestOwnerSelfApprovalLinks:
    def test_owner_approving_own_claim_links_player(self):
        owner = make_user("SelfApproveOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(owner["id"], ws["id"])
        _approve(owner["id"], owner["id"], ws["id"])
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == owner["id"]


# ---------------------------------------------------------------------------
# 6. No imported row — approval succeeds with no side effect
# ---------------------------------------------------------------------------

class TestApprovalWithNoImportedRow:
    def test_approval_without_imported_player_does_not_fail(self):
        owner  = make_user("NoImportOwner")
        member = make_user("NoImportMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        # No imported player row
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        # No exception — approval completes successfully
        with database.transaction() as db:
            players = repositories.list_workspace_albion_players(db, ws["id"])
        assert len(players) == 0

    def test_approval_without_imported_player_claim_still_approved(self):
        owner  = make_user("NoImportApproveOwner")
        member = make_user("NoImportApproveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        with database.transaction() as db:
            claim = repositories.get_player_game_identity_for_user(
                db, member["id"], ws["id"]
            )
        assert claim["verification_status"] == "approved"


# ---------------------------------------------------------------------------
# 7. Already linked to same user — idempotent
# ---------------------------------------------------------------------------

class TestAlreadyLinkedSameUser:
    def test_already_linked_same_user_is_idempotent(self):
        owner  = make_user("IdempotentOwner")
        member = make_user("IdempotentMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        # Pre-link the player to the same user
        _insert_imported_player(ws["id"], _PLAYER_ID_A, user_id=member["id"])
        _make_claim(member["id"], ws["id"])
        # Approval should not fail even though user_id IS NOT NULL
        _approve(owner["id"], member["id"], ws["id"])
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == member["id"]

    def test_double_approval_call_does_not_error(self):
        """
        If approve is somehow called twice (edge case), the link call is a no-op
        the second time (user_id IS NULL fails) and no exception is raised.
        """
        owner  = make_user("DoubleApproveOwner")
        member = make_user("DoubleApproveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == member["id"]
        # The use case itself would raise ValidationError on the second call
        # (claim status is no longer pending) — but the repository function
        # itself is safe.  Test the repository directly.
        with database.transaction() as db:
            result = repositories.link_workspace_albion_player_to_user(
                db, ws["id"], _PLAYER_ID_A, member["id"]
            )
        # Returns False because user_id IS NOT NULL now
        assert result is False


# ---------------------------------------------------------------------------
# 8. Already linked to different user — no overwrite
# ---------------------------------------------------------------------------

class TestAlreadyLinkedDifferentUser:
    def test_already_linked_different_user_not_overwritten(self):
        owner   = make_user("ConflictOwner")
        member1 = make_user("ConflictMember1")
        member2 = make_user("ConflictMember2")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member1["id"])
        _add_member_row(ws["id"], member2["id"])
        # Pre-link the player to member1
        _insert_imported_player(ws["id"], _PLAYER_ID_A, user_id=member1["id"])
        # member2 claims and gets approved
        _make_claim(member2["id"], ws["id"])
        # Normally this would fail at claim_albion_character because the player_id
        # is already claimed by member1 (pending/approved). Test the repo directly.
        with database.transaction() as db:
            result = repositories.link_workspace_albion_player_to_user(
                db, ws["id"], _PLAYER_ID_A, member2["id"]
            )
        # No overwrite — returns False
        assert result is False
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == member1["id"]

    def test_repository_link_function_returns_true_only_on_actual_link(self):
        owner = make_user("ReturnTrueOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)  # user_id = NULL
        with database.transaction() as db:
            result = repositories.link_workspace_albion_player_to_user(
                db, ws["id"], _PLAYER_ID_A, owner["id"]
            )
        assert result is True
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == owner["id"]


# ---------------------------------------------------------------------------
# 9. Same albion_player_id in different workspace is not linked
# ---------------------------------------------------------------------------

class TestCrossWorkspaceIsolation:
    def test_approval_in_workspace_a_does_not_link_workspace_b(self):
        owner = make_user("CrossWsOwner")
        ws_a = make_workspace(slug="link-cw-a", owner_user_id=owner["id"])
        ws_b = make_workspace(slug="link-cw-b", owner_user_id=owner["id"])
        # Import the same player into both workspaces
        _insert_imported_player(ws_a["id"], _PLAYER_ID_A)
        _insert_imported_player(ws_b["id"], _PLAYER_ID_A)
        # Claim and approve in workspace A only
        _make_claim(owner["id"], ws_a["id"])
        _approve(owner["id"], owner["id"], ws_a["id"])
        # Workspace A: linked
        row_a = _get_imported_player(ws_a["id"], _PLAYER_ID_A)
        assert row_a["user_id"] == owner["id"]
        # Workspace B: still unlinked
        row_b = _get_imported_player(ws_b["id"], _PLAYER_ID_A)
        assert row_b["user_id"] is None


# ---------------------------------------------------------------------------
# 10. Same character name but different albion_player_id is not linked
# ---------------------------------------------------------------------------

class TestNoDifferentPlayerIdLink:
    def test_imported_player_with_different_id_not_linked(self):
        owner  = make_user("DiffIdOwner")
        member = make_user("DiffIdMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        # Import player_B (different ID, same name)
        _insert_imported_player(ws["id"], _PLAYER_ID_B, char_name="Kage")
        # Claim and approve player_A
        _make_claim(member["id"], ws["id"], player_id=_PLAYER_ID_A, name="Kage")
        _approve(owner["id"], member["id"], ws["id"])
        # player_B must NOT be linked
        row_b = _get_imported_player(ws["id"], _PLAYER_ID_B)
        assert row_b["user_id"] is None


# ---------------------------------------------------------------------------
# 11. Re-import after approval preserves linked user_id
# ---------------------------------------------------------------------------

class TestReImportPreservesLink:
    def test_reimport_preserves_linked_user_id(self):
        owner  = make_user("ReImportLinkOwner")
        member = make_user("ReImportLinkMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        # Import, claim, approve
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        row_before = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row_before["user_id"] == member["id"]
        # Re-import the same player (via upsert with user_id=None)
        now = _now_iso()
        with database.transaction() as db:
            repositories.upsert_workspace_albion_player(db, {
                "id":                    str(uuid.uuid4()),
                "guild_workspace_id":    ws["id"],
                "albion_player_id":      _PLAYER_ID_A,
                "character_name":        "KageRenamed",
                "user_id":               None,  # import always passes NULL
                "source_guild_id":       None,
                "last_seen_in_guild_at": now,
                "created_at":            now,
                "updated_at":            now,
            })
        row_after = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row_after["user_id"] == member["id"]
        assert row_after["character_name"] == "KageRenamed"


# ---------------------------------------------------------------------------
# 12. Members page shows linked user indicator
# ---------------------------------------------------------------------------

class TestMembersPageLinkedDisplay:
    def test_members_page_shows_linked_user_after_approval(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("MembersLinkedOwner")
        member = make_user("MembersLinkedMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A, char_name="KageChar")
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        _login(client, owner["display_name"])
        response = client.get(
            f"/workspaces/{ws['slug']}/members", follow_redirects=True
        )
        assert response.status_code == 200
        assert "KageChar" in response.text
        # The linked member's display name should appear in the imported players section
        assert "MembersLinkedMember" in response.text


# ---------------------------------------------------------------------------
# 13. Members page shows unlinked state for unlinked players
# ---------------------------------------------------------------------------

class TestMembersPageUnlinkedDisplay:
    def test_members_page_shows_dash_for_unlinked_player(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("MembersUnlinkedOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A, char_name="UnlinkedChar")
        _login(client, owner["display_name"])
        response = client.get(
            f"/workspaces/{ws['slug']}/members", follow_redirects=True
        )
        assert response.status_code == 200
        assert "UnlinkedChar" in response.text
        assert "Imported Albion Players" in response.text


# ---------------------------------------------------------------------------
# 14. workspace_members are not created by linking
# ---------------------------------------------------------------------------

class TestLinkingDoesNotCreateWorkspaceMembers:
    def test_approval_linking_does_not_create_workspace_member(self):
        owner  = make_user("NoWsMemberOwner")
        member = make_user("NoWsMemberMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        with database.transaction() as db:
            ws_members_before = repositories.list_workspace_members(db, ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        with database.transaction() as db:
            ws_members_after = repositories.list_workspace_members(db, ws["id"])
        assert len(ws_members_after) == len(ws_members_before)


# ---------------------------------------------------------------------------
# 15. participants are not modified by linking
# ---------------------------------------------------------------------------

class TestLinkingDoesNotTouchParticipants:
    def test_approval_linking_does_not_modify_participants(self):
        owner  = make_user("NoPartModOwner")
        member = make_user("NoPartModMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        with database.transaction() as db:
            p_count = db.execute(
                "SELECT COUNT(*) FROM participants WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchone()[0]
        assert p_count == 0

    def test_participants_albion_player_id_write_dark_invariant_still_intact(self):
        from pathlib import Path
        source = (
            Path(__file__).parent.parent / "app" / "repositories.py"
        ).read_text(encoding="utf-8")
        assert "participants.albion_player_id" not in source


# ---------------------------------------------------------------------------
# 16. Regression: existing Albion identity tests (spot checks)
# ---------------------------------------------------------------------------

class TestAlbionIdentityRegressionSlice2:
    """
    Spot-check that Slice 2 did not break the Albion identity claim/approve
    flow.  Full coverage is in test_albion_identity.py.
    """

    def test_claim_still_creates_pending_status(self):
        owner = make_user("Slice2ClaimOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        _make_claim(owner["id"], ws["id"])
        with database.transaction() as db:
            claim = repositories.get_player_game_identity_for_user(
                db, owner["id"], ws["id"]
            )
        assert claim["verification_status"] == "pending"

    def test_approval_still_sets_approved_status(self):
        owner  = make_user("Slice2ApproveOwner")
        member = make_user("Slice2ApproveMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        with database.transaction() as db:
            claim = repositories.get_player_game_identity_for_user(
                db, member["id"], ws["id"]
            )
        assert claim["verification_status"] == "approved"
        assert claim["reviewed_by"] == owner["id"]

    def test_officer_cannot_approve_own_claim_still_blocked(self):
        owner   = make_user("Slice2OfficerSelfOwner")
        officer = make_user("Slice2OfficerSelf")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], officer["id"])
        _add_officer(ws["id"], officer["id"])
        _make_claim(officer["id"], ws["id"])
        with pytest.raises(PermissionDenied, match="Officers cannot approve"):
            _approve(officer["id"], officer["id"], ws["id"])

    def test_approval_emits_audit_event(self):
        from app.domain import operational_events
        owner  = make_user("Slice2EventOwner")
        member = make_user("Slice2EventMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        with database.transaction() as db:
            events = db.execute(
                "SELECT * FROM operational_events WHERE event_type=? AND guild_workspace_id=?",
                (operational_events.ALBION_IDENTITY_APPROVED, ws["id"]),
            ).fetchall()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# 17. Regression: existing guild roster import tests (spot checks)
# ---------------------------------------------------------------------------

class TestGuildRosterImportRegressionSlice2:
    """
    Spot-check that Slice 2 did not break guild roster import.
    Full coverage is in test_guild_roster_import.py.
    """

    def _fake_member(self, player_id: str, name: str) -> dict:
        return {
            "albion_player_id": player_id,
            "character_name":   name,
            "guild_id":         _GUILD_ID_A,
            "guild_name":       "Iron Keep",
            "kill_fame":        500,
            "death_fame":       20,
            "extra_json":       "{}",
        }

    def test_roster_import_still_works(self):
        owner = make_user("Slice2ImportOwner")
        ws = make_workspace(owner_user_id=owner["id"])
        from app.albion import rest_client
        members = [self._fake_member(_PLAYER_ID_A, "Kage"),
                   self._fake_member(_PLAYER_ID_B, "Vex")]
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=members):
            with patch.object(rest_client, "_rate_limit"):
                result = use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GUILD_ID_A,
                    guild_name_hint="Iron Keep",
                )
        assert result["total"] == 2
        assert result["imported"] == 2

    def test_reimport_preserves_user_id_set_by_approval(self):
        owner  = make_user("Slice2ReImportOwner")
        member = make_user("Slice2ReImportMember")
        ws = make_workspace(owner_user_id=owner["id"])
        _add_member_row(ws["id"], member["id"])
        _insert_imported_player(ws["id"], _PLAYER_ID_A)
        _make_claim(member["id"], ws["id"])
        _approve(owner["id"], member["id"], ws["id"])
        # Re-import same player
        from app.albion import rest_client
        members = [self._fake_member(_PLAYER_ID_A, "KageV2")]
        with patch.object(rest_client, "fetch_albion_guild_members", return_value=members):
            with patch.object(rest_client, "_rate_limit"):
                use_cases.import_albion_guild_roster(
                    guild_workspace_id=ws["id"],
                    requesting_user_id=owner["id"],
                    albion_guild_id=_GUILD_ID_A,
                    guild_name_hint="Iron Keep",
                )
        row = _get_imported_player(ws["id"], _PLAYER_ID_A)
        assert row["user_id"] == member["id"]
        assert row["character_name"] == "KageV2"
