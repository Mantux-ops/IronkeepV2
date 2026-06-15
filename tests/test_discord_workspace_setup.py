"""
Phase 10 Slice 2 — Discord setup completion and safe owner bootstrap.

Tests the full ownership-claim path: use case, repository helpers, route,
template states, and regression against Slice 1 and existing auth flows.

Coverage map:
  Group 1 — Use case: successful ownership claim
  1.  Verified guild owner claims ownerless workspace → status 'claimed'.
  2.  After claim, count_workspace_owners == 1.
  3.  workspace.owner_claimed operational event is emitted.
  4.  Claim is idempotent: same owner re-visits → 'already_claimed' (not re-granted).
  5.  Claim creates exactly one membership row (not two on repeat call).

  Group 2 — Use case: already claimed
  6.  Workspace with existing owner → 'already_claimed'.
  7.  workspace dict is included in 'already_claimed' result.
  8.  A second, different verified user cannot claim after first.

  Group 3 — Use case: not found
  9.  Unknown guild_id → 'not_found'.
  10. Empty guild_id → 'not_found'.
  11. workspace is None in 'not_found' result.

  Group 4 — Use case: verification failed
  12. User with no Discord identity → 'verification_failed'.
  13. User whose Discord ID does not match stored owner → 'verification_failed'.
  14. No stored guild owner ID (provisioned without owner_id) → 'verification_failed'.
  15. No membership row created on verification_failed.

  Group 5 — Repository: grant_workspace_owner_if_unclaimed
  16. Returns True on first call (row inserted).
  17. Returns False on second call with same user (NOT EXISTS guard).
  18. Returns False when a different owner already exists.
  19. Rowcount-based return is correct (not exception-based).

  Group 6 — Repository: get_discord_identity_for_user
  20. Returns identity for user with user_auth_identities row.
  21. Returns identity for legacy user (auth_provider on users row).
  22. Returns None for dev-only user with no Discord identity.

  Group 7 — Provisioning: discord_guild_owner_id stored at install
  23. ensure_workspace_for_discord_guild stores owner_id in discord_guild_installs.
  24. Re-join (upsert) with new owner_id updates the stored value.
  25. Re-join with None owner_id preserves the previous stored value (COALESCE).

  Group 8 — Route: /discord/setup/continue
  26. GET without login → 303 redirect to /login.
  27. GET without guild_id → renders not_found state.
  28. GET with unknown guild_id → renders not_found state.
  29. GET with verified guild owner → renders claimed state, mentions workspace name.
  30. GET with existing-owner workspace → renders already_claimed state.
  31. GET with wrong Discord user → renders verification_failed state.
  32. GET with user who has no Discord identity → renders verification_failed state.

  Group 9 — Regression
  33. Manual workspace creation (create_guild_workspace) still works.
  34. Existing Slice 1 provisioning path (no owner_id) still works.
  35. complete_discord_workspace_setup never raises for expected failure modes.
  36. No secrets appear in log output from provisioning.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.discord import provisioning as prov_module
from app.main import app

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GUILD_ID       = "111122223333444455"
_GUILD_NAME     = "Orbie Gaming Guild"
_OWNER_DISC_ID  = "999888777666555444"   # guild owner's Discord snowflake
_OTHER_DISC_ID  = "111000111000111000"   # a different Discord user


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _provision(*, guild_id=_GUILD_ID, name=_GUILD_NAME, owner_id=_OWNER_DISC_ID):
    """Create a bot-provisioned workspace with a stored guild owner ID."""
    return use_cases.ensure_workspace_for_discord_guild(
        guild_id, name, discord_guild_owner_id=owner_id
    )


def _discord_user(display_name: str, discord_snowflake: str) -> dict:
    """Create a dev user and link a Discord identity to it."""
    user = make_user(display_name)
    use_cases.link_discord_identity(user["id"], discord_snowflake)
    return user


def _claim(guild_id: str, user_id: str) -> dict:
    return use_cases.complete_discord_workspace_setup(
        discord_guild_id=guild_id,
        user_id=user_id,
    )


def _owner_count(workspace_id: str) -> int:
    with database.transaction() as db:
        return repositories.count_workspace_owners(db, workspace_id)


def _get_events(workspace_id: str, event_type: str) -> list[dict]:
    with database.transaction() as db:
        return db.execute(
            "SELECT * FROM operational_events "
            "WHERE guild_workspace_id = ? AND event_type = ?",
            (workspace_id, event_type),
        ).fetchall()


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


# ===========================================================================
# Group 1 — Use case: successful ownership claim
# ===========================================================================

class TestSuccessfulClaim:
    def test_returns_claimed_status(self):
        ws    = _provision()
        owner = _discord_user("Owner1", _OWNER_DISC_ID)
        result = _claim(_GUILD_ID, owner["id"])
        assert result["status"] == "claimed"

    def test_workspace_dict_returned(self):
        ws    = _provision()
        owner = _discord_user("Owner2", _OWNER_DISC_ID)
        result = _claim(_GUILD_ID, owner["id"])
        assert result["workspace"] is not None
        assert result["workspace"]["id"] == ws["id"]

    def test_owner_count_is_one_after_claim(self):
        ws    = _provision()
        owner = _discord_user("Owner3", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        assert _owner_count(ws["id"]) == 1

    def test_owner_claimed_event_emitted(self):
        ws    = _provision()
        owner = _discord_user("Owner4", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        events = _get_events(ws["id"], "workspace.owner_claimed")
        assert len(events) == 1

    def test_claim_is_idempotent_status(self):
        """Same owner re-visits → already_claimed (not re-granted)."""
        ws    = _provision()
        owner = _discord_user("Owner5", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        result = _claim(_GUILD_ID, owner["id"])
        assert result["status"] == "already_claimed"

    def test_claim_idempotent_single_membership(self):
        """Repeated claim by same owner creates exactly one membership row."""
        ws    = _provision()
        owner = _discord_user("Owner6", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        _claim(_GUILD_ID, owner["id"])
        assert _owner_count(ws["id"]) == 1

    def test_claim_single_event_on_idempotent(self):
        """Only one workspace.owner_claimed event even on repeated calls."""
        ws    = _provision()
        owner = _discord_user("Owner7", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        _claim(_GUILD_ID, owner["id"])
        events = _get_events(ws["id"], "workspace.owner_claimed")
        assert len(events) == 1


# ===========================================================================
# Group 2 — Use case: already claimed
# ===========================================================================

class TestAlreadyClaimed:
    def test_returns_already_claimed_status(self):
        owner = make_user("AlreadyOwner")
        ws    = make_workspace(slug="already-owned", owner_user_id=owner["id"])
        # Attach a guild ID so complete_discord_workspace_setup can find it.
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_workspaces SET discord_guild_id = ? WHERE id = ?",
                (_GUILD_ID, ws["id"]),
            )
            repositories.upsert_discord_guild_install(
                db,
                discord_guild_id=_GUILD_ID,
                guild_name=_GUILD_NAME,
                guild_workspace_id=ws["id"],
                discord_guild_owner_id=_OWNER_DISC_ID,
            )
        claimant = _discord_user("LateClaimant", _OWNER_DISC_ID)
        result   = _claim(_GUILD_ID, claimant["id"])
        assert result["status"] == "already_claimed"

    def test_workspace_included_in_already_claimed(self):
        owner = make_user("AlreadyOwner2")
        ws    = make_workspace(slug="already-owned-2", owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_workspaces SET discord_guild_id = ? WHERE id = ?",
                (_GUILD_ID, ws["id"]),
            )
            repositories.upsert_discord_guild_install(
                db,
                discord_guild_id=_GUILD_ID,
                guild_name=_GUILD_NAME,
                guild_workspace_id=ws["id"],
                discord_guild_owner_id=_OWNER_DISC_ID,
            )
        claimant = _discord_user("LateClaimant2", _OWNER_DISC_ID)
        result   = _claim(_GUILD_ID, claimant["id"])
        assert result["workspace"] is not None
        assert result["workspace"]["id"] == ws["id"]

    def test_second_user_sees_already_claimed_after_first_owner(self):
        """After owner_a claims, any subsequent caller sees 'already_claimed'.

        The use case checks for existing owners BEFORE verification, so once
        the workspace is owned the response is 'already_claimed' regardless of
        the caller's Discord identity.  This prevents information leakage about
        whose Discord ID is stored.
        """
        _provision()
        owner_a = _discord_user("RaceA", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner_a["id"])
        # owner_b has a different (non-matching) Discord snowflake.
        owner_b = _discord_user("RaceB", _OTHER_DISC_ID)
        result  = _claim(_GUILD_ID, owner_b["id"])
        # Workspace is already owned → 'already_claimed', not 'verification_failed'.
        assert result["status"] == "already_claimed"


# ===========================================================================
# Group 3 — Use case: not found
# ===========================================================================

class TestNotFound:
    def test_unknown_guild_id(self):
        user   = make_user("NfUser")
        result = _claim("999000000000000000", user["id"])
        assert result["status"] == "not_found"

    def test_empty_guild_id(self):
        user   = make_user("EmptyGuild")
        result = _claim("", user["id"])
        assert result["status"] == "not_found"

    def test_workspace_none_on_not_found(self):
        user   = make_user("NfUser2")
        result = _claim("000000000000000001", user["id"])
        assert result["workspace"] is None


# ===========================================================================
# Group 4 — Use case: verification failed
# ===========================================================================

class TestVerificationFailed:
    def test_user_no_discord_identity(self):
        """Dev-only user (no Discord link) cannot claim."""
        _provision()
        dev_user = make_user("DevOnly")
        result   = _claim(_GUILD_ID, dev_user["id"])
        assert result["status"] == "verification_failed"

    def test_wrong_discord_user_id(self):
        """User with a Discord identity that does not match the guild owner."""
        _provision()
        wrong = _discord_user("WrongOwner", _OTHER_DISC_ID)
        result = _claim(_GUILD_ID, wrong["id"])
        assert result["status"] == "verification_failed"

    def test_no_stored_owner_id(self):
        """Workspace provisioned without guild owner ID → verification fails."""
        use_cases.ensure_workspace_for_discord_guild(
            _GUILD_ID, _GUILD_NAME, discord_guild_owner_id=None
        )
        user   = _discord_user("NullOwner", _OWNER_DISC_ID)
        result = _claim(_GUILD_ID, user["id"])
        assert result["status"] == "verification_failed"

    def test_no_membership_row_on_verification_failed(self):
        """Verification failure must not insert any membership row."""
        ws     = _provision()
        wrong  = _discord_user("WrongUser", _OTHER_DISC_ID)
        _claim(_GUILD_ID, wrong["id"])
        assert _owner_count(ws["id"]) == 0

    def test_workspace_none_on_verification_failed(self):
        _provision()
        dev_user = make_user("DevOnly2")
        result   = _claim(_GUILD_ID, dev_user["id"])
        assert result["workspace"] is None


# ===========================================================================
# Group 5 — Repository: grant_workspace_owner_if_unclaimed
# ===========================================================================

class TestGrantWorkspaceOwnerIfUnclaimed:
    def _make_ownerless(self, slug: str) -> dict:
        ws = use_cases.ensure_workspace_for_discord_guild(
            "777777777777777777", "Ownerless Guild " + slug,
        )
        return ws

    def test_returns_true_first_call(self):
        ws   = self._make_ownerless("gwoic-a")
        user = make_user("GrantA")
        with database.transaction() as db:
            granted = repositories.grant_workspace_owner_if_unclaimed(
                db, ws["id"], user["id"], "2026-01-01T00:00:00"
            )
        assert granted is True

    def test_returns_false_second_call_same_user(self):
        ws   = self._make_ownerless("gwoic-b")
        user = make_user("GrantB")
        with database.transaction() as db:
            repositories.grant_workspace_owner_if_unclaimed(
                db, ws["id"], user["id"], "2026-01-01T00:00:00"
            )
        with database.transaction() as db:
            granted = repositories.grant_workspace_owner_if_unclaimed(
                db, ws["id"], user["id"], "2026-01-01T00:01:00"
            )
        assert granted is False

    def test_returns_false_when_different_owner_exists(self):
        ws     = make_workspace(slug="gwoic-c")
        user_b = make_user("GrantC2")
        with database.transaction() as db:
            granted = repositories.grant_workspace_owner_if_unclaimed(
                db, ws["id"], user_b["id"], "2026-01-01T00:00:00"
            )
        assert granted is False

    def test_member_count_correct_after_calls(self):
        ws   = self._make_ownerless("gwoic-d")
        user = make_user("GrantD")
        with database.transaction() as db:
            repositories.grant_workspace_owner_if_unclaimed(
                db, ws["id"], user["id"], "2026-01-01T00:00:00"
            )
        assert _owner_count(ws["id"]) == 1


# ===========================================================================
# Group 6 — Repository: get_discord_identity_for_user
# ===========================================================================

class TestGetDiscordIdentityForUser:
    def test_returns_identity_via_auth_identities(self):
        user = _discord_user("AuthIdUser", _OWNER_DISC_ID)
        with database.transaction() as db:
            identity = repositories.get_discord_identity_for_user(db, user["id"])
        assert identity is not None
        assert identity["provider_user_id"] == _OWNER_DISC_ID
        assert identity["auth_provider"] == "discord"

    def test_returns_none_for_dev_only_user(self):
        user = make_user("DevOnlyNoLink")
        with database.transaction() as db:
            identity = repositories.get_discord_identity_for_user(db, user["id"])
        assert identity is None

    def test_legacy_fallback_pure_discord_user(self):
        """Pure Discord user (no user_auth_identities row yet) via legacy column."""
        # Simulate a legacy user: discord auth_provider on the users row but
        # no user_auth_identities row.
        import uuid as _uuid
        now = "2026-01-01T00:00:00"
        user_id = str(_uuid.uuid4())
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO users (id, display_name, auth_provider, provider_user_id,
                                   created_at, updated_at)
                VALUES (?, ?, 'discord', ?, ?, ?)
                """,
                (user_id, "LegacyDiscord", "legacy-snowflake-001", now, now),
            )
            identity = repositories.get_discord_identity_for_user(db, user_id)
        assert identity is not None
        assert identity["provider_user_id"] == "legacy-snowflake-001"
        assert identity["auth_provider"] == "discord"


# ===========================================================================
# Group 7 — Provisioning: discord_guild_owner_id stored at install
# ===========================================================================

class TestOwnerIdStoredAtInstall:
    def test_owner_id_stored_in_guild_installs(self):
        _provision()
        with database.transaction() as db:
            row = repositories.get_discord_guild_install(db, _GUILD_ID)
        assert row is not None
        assert row["discord_guild_owner_id"] == _OWNER_DISC_ID

    def test_rejoin_with_new_owner_id_updates_stored_value(self):
        _provision()
        new_owner = "111999111999111999"
        use_cases.ensure_workspace_for_discord_guild(
            _GUILD_ID, _GUILD_NAME, discord_guild_owner_id=new_owner
        )
        with database.transaction() as db:
            row = repositories.get_discord_guild_install(db, _GUILD_ID)
        assert row["discord_guild_owner_id"] == new_owner

    def test_rejoin_with_none_owner_preserves_existing(self):
        """COALESCE: re-join without owner_id must not overwrite existing value."""
        _provision()
        use_cases.ensure_workspace_for_discord_guild(
            _GUILD_ID, _GUILD_NAME, discord_guild_owner_id=None
        )
        with database.transaction() as db:
            row = repositories.get_discord_guild_install(db, _GUILD_ID)
        assert row["discord_guild_owner_id"] == _OWNER_DISC_ID

    def test_provisioning_module_passes_owner_id(self):
        """provisioning.handle_guild_join delegates owner_id to use case."""
        prov_module.handle_guild_join(
            discord_guild_id=_GUILD_ID,
            guild_name=_GUILD_NAME,
            discord_guild_owner_id=_OWNER_DISC_ID,
        )
        with database.transaction() as db:
            row = repositories.get_discord_guild_install(db, _GUILD_ID)
        assert row["discord_guild_owner_id"] == _OWNER_DISC_ID


# ===========================================================================
# Group 8 — Route: GET /discord/setup/continue
# ===========================================================================

class TestSetupRoute:
    def _provisioned_guild_and_owner(self, slug_suffix: str) -> tuple[dict, dict, TestClient]:
        """Create a claimable workspace + logged-in owner; return (ws, owner, client)."""
        ws    = _provision()
        owner = _discord_user(f"RouteOwner{slug_suffix}", _OWNER_DISC_ID)
        client = TestClient(app, follow_redirects=False)
        _login(client, f"RouteOwner{slug_suffix}")
        return ws, owner, client

    def test_unauthenticated_redirects_to_login(self):
        client = TestClient(app, follow_redirects=False)
        resp = client.get(f"/discord/setup/continue?guild_id={_GUILD_ID}")
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_no_guild_id_renders_not_found(self):
        owner  = _discord_user("NogidOwner", _OWNER_DISC_ID)
        client = TestClient(app, follow_redirects=False)
        _login(client, "NogidOwner")
        resp = client.get("/discord/setup/continue", follow_redirects=True)
        assert resp.status_code == 200
        assert "not_found" in resp.text.lower() or "workspace not found" in resp.text.lower()

    def test_unknown_guild_id_renders_not_found(self):
        owner  = _discord_user("UnkGuildOwner", _OWNER_DISC_ID)
        client = TestClient(app, follow_redirects=False)
        _login(client, "UnkGuildOwner")
        resp = client.get(
            "/discord/setup/continue?guild_id=000000000000000002",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "not found" in resp.text.lower()

    def test_verified_owner_renders_claimed(self):
        ws, owner, client = self._provisioned_guild_and_owner("Claimed")
        resp = client.get(
            f"/discord/setup/continue?guild_id={_GUILD_ID}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "setup complete" in resp.text.lower() or "claimed" in resp.text.lower()
        assert ws["name"] in resp.text

    def test_claimed_workspace_renders_already_claimed(self):
        existing_owner = make_user("ExistingOwnerRoute")
        ws             = make_workspace(slug="already-claimed-route", owner_user_id=existing_owner["id"])
        # Attach discord guild metadata.
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_workspaces SET discord_guild_id = ? WHERE id = ?",
                (_GUILD_ID, ws["id"]),
            )
            repositories.upsert_discord_guild_install(
                db,
                discord_guild_id=_GUILD_ID,
                guild_name=_GUILD_NAME,
                guild_workspace_id=ws["id"],
                discord_guild_owner_id=_OWNER_DISC_ID,
            )
        claimant = _discord_user("LateRouteClaimant", _OWNER_DISC_ID)
        client   = TestClient(app, follow_redirects=False)
        _login(client, "LateRouteClaimant")
        resp = client.get(
            f"/discord/setup/continue?guild_id={_GUILD_ID}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "already" in resp.text.lower()

    def test_wrong_discord_user_renders_verification_failed(self):
        _provision()
        wrong  = _discord_user("WrongRouteUser", _OTHER_DISC_ID)
        client = TestClient(app, follow_redirects=False)
        _login(client, "WrongRouteUser")
        resp = client.get(
            f"/discord/setup/continue?guild_id={_GUILD_ID}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "verification failed" in resp.text.lower()

    def test_no_discord_identity_renders_verification_failed(self):
        _provision()
        dev_user = make_user("DevOnlyRoute")
        client   = TestClient(app, follow_redirects=False)
        _login(client, "DevOnlyRoute")
        resp = client.get(
            f"/discord/setup/continue?guild_id={_GUILD_ID}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "verification failed" in resp.text.lower()

    def test_login_redirect_preserves_guild_id(self):
        """Unauthenticated request: redirect must include guild_id in next param."""
        client = TestClient(app, follow_redirects=False)
        resp   = client.get(f"/discord/setup/continue?guild_id={_GUILD_ID}")
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/login" in location
        # guild_id should survive in the ?next= parameter.
        assert _GUILD_ID in location or "guild_id" in location


# ===========================================================================
# Group 9 — Regression
# ===========================================================================

class TestRegression:
    def test_manual_workspace_creation_unaffected(self):
        owner = make_user("ManualOwner")
        ws    = make_workspace(slug="manual-reg", owner_user_id=owner["id"])
        assert ws["id"]
        assert _owner_count(ws["id"]) == 1

    def test_slice1_provisioning_without_owner_id_still_works(self):
        """Backwards compat: Slice 1 callers that don't pass owner_id still work."""
        ws = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID, _GUILD_NAME)
        assert ws["id"]
        assert ws["discord_guild_id"] == _GUILD_ID

    def test_complete_setup_never_raises_for_expected_failures(self):
        """All expected failure modes return a dict; no exceptions propagate."""
        dev_user = make_user("SafeUser")
        for guild_id in ("", "000000000000000003"):
            result = use_cases.complete_discord_workspace_setup(guild_id, dev_user["id"])
            assert isinstance(result, dict)
            assert "status" in result

    def test_no_secrets_in_provisioning_logs(self, caplog):
        """Provisioning log must not contain OAuth tokens or auth secrets."""
        with caplog.at_level(logging.DEBUG, logger="app.discord.provisioning"):
            prov_module.handle_guild_join(
                discord_guild_id=_GUILD_ID,
                guild_name=_GUILD_NAME,
                discord_guild_owner_id=_OWNER_DISC_ID,
            )
        combined = "\n".join(caplog.messages)
        for secret_pattern in ("secret", "token", "password", "oauth"):
            assert secret_pattern not in combined.lower()
