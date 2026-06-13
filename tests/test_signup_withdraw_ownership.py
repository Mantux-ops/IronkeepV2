"""Signup withdraw ownership — non-member and display-name-collision tests.

Covers:
  1. Non-member sees Withdraw button for their own signup.
  2. Non-member does NOT see Withdraw button for another user's signup.
  3. Non-member can POST withdraw their own signup.
  4. Non-member cannot POST withdraw another user's signup.
  5. Officer can withdraw any signup.
  6. Display-name collision does NOT allow withdrawing another user's signup.
  7. Workspace member behavior remains unchanged.
  8. Unauthenticated POST to withdraw redirects to login.

Key design: signup_intents.source stores "web:{user_id}" for authenticated web
signups.  Withdrawal uses this ID to determine ownership without requiring a
schema change or workspace membership from the withdrawing user.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import PermissionDenied
from app.main import app

from tests.conftest import make_user, make_workspace, make_operation, publish_operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _signup_url(slug: str, op_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}/signup"


def _withdraw_url(slug: str, op_id: str, signup_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}/signups/{signup_id}/withdraw"


def _make_published_op(ws_id: str) -> dict:
    op = make_operation(ws_id)
    publish_operation(ws_id, op["id"])
    return op


def _post_signup(client, slug, op_id, display_name, role="DPS"):
    return client.post(
        _signup_url(slug, op_id),
        data={
            "display_name":   display_name,
            "preferred_role": role,
            "willingness":    "flexible",
            "availability":   "confirmed",
        },
        follow_redirects=True,
    )


def _get_signups(ws_id, op_id):
    with database.transaction() as db:
        return repositories.get_signups_with_display_names(db, op_id, ws_id)


def _get_signup_id_for(ws_id, op_id, display_name):
    for s in _get_signups(ws_id, op_id):
        if s["display_name"] == display_name:
            return s["id"]
    raise LookupError(f"No signup for {display_name!r}")


# ---------------------------------------------------------------------------
# Test 1 — Non-member sees Withdraw for their own signup
# ---------------------------------------------------------------------------

class TestNonMemberSeesOwnWithdraw:

    def setup_method(self):
        self.owner    = make_user("wo-t1-owner")
        self.ws       = make_workspace(owner_user_id=self.owner["id"], slug="wo-t1")
        self.op       = _make_published_op(self.ws["id"])
        self.visitor  = make_user("wo-t1-visitor")
        self.client   = TestClient(app)

    def test_withdraw_button_visible_for_own_signup(self):
        _login(self.client, "wo-t1-visitor")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t1-visitor")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200
        assert "/withdraw" in resp.text

    def test_source_encodes_user_id(self):
        """signup_intents.source must be 'web:{user_id}' for web submissions."""
        _login(self.client, "wo-t1-visitor")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t1-visitor")
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert len(signups) == 1
        assert signups[0]["source"] == f"web:{self.visitor['id']}"


# ---------------------------------------------------------------------------
# Test 2 — Non-member does NOT see Withdraw for another user's signup
# ---------------------------------------------------------------------------

class TestNonMemberNoWithdrawForOthers:

    def setup_method(self):
        self.owner   = make_user("wo-t2-owner")
        self.ws      = make_workspace(owner_user_id=self.owner["id"], slug="wo-t2")
        self.op      = _make_published_op(self.ws["id"])
        self.visitor = make_user("wo-t2-visitor")
        self.other   = make_user("wo-t2-other")
        self.client  = TestClient(app)

    def test_no_withdraw_button_for_other_signup(self):
        # Other user signs up.
        _login(self.client, "wo-t2-other")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t2-other")
        # Visitor views page — should not see Withdraw for "wo-t2-other".
        _login(self.client, "wo-t2-visitor")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200
        assert "wo-t2-other" in resp.text   # sees the row
        assert "/withdraw" not in resp.text  # but no withdraw button


# ---------------------------------------------------------------------------
# Test 3 — Non-member can POST withdraw their own signup
# ---------------------------------------------------------------------------

class TestNonMemberCanWithdrawOwn:

    def setup_method(self):
        self.owner   = make_user("wo-t3-owner")
        self.ws      = make_workspace(owner_user_id=self.owner["id"], slug="wo-t3")
        self.op      = _make_published_op(self.ws["id"])
        self.visitor = make_user("wo-t3-visitor")
        self.client  = TestClient(app)

    def test_post_withdraw_own_signup_succeeds(self):
        _login(self.client, "wo-t3-visitor")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t3-visitor")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t3-visitor")

        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Signup must be gone from active list.
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert not any(s["display_name"] == "wo-t3-visitor" for s in signups)

    def test_post_withdraw_redirects_to_signup_page(self):
        _login(self.client, "wo-t3-visitor")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t3-visitor")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t3-visitor")

        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/signup" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test 4 — Non-member CANNOT POST withdraw another user's signup
# ---------------------------------------------------------------------------

class TestNonMemberCannotWithdrawOthers:

    def setup_method(self):
        self.owner   = make_user("wo-t4-owner")
        self.ws      = make_workspace(owner_user_id=self.owner["id"], slug="wo-t4")
        self.op      = _make_published_op(self.ws["id"])
        self.visitor = make_user("wo-t4-visitor")
        self.other   = make_user("wo-t4-other")
        self.client  = TestClient(app)

    def test_post_withdraw_other_signup_rejected(self):
        # "other" signs up.
        _login(self.client, "wo-t4-other")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t4-other")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t4-other")

        # "visitor" tries to withdraw "other"'s signup.
        _login(self.client, "wo-t4-visitor")
        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=True,
        )
        # Should fail — signup must still be active.
        assert resp.status_code == 200
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert any(s["display_name"] == "wo-t4-other" for s in signups)

    def test_post_withdraw_other_redirect_contains_error(self):
        _login(self.client, "wo-t4-other")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t4-other")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t4-other")

        _login(self.client, "wo-t4-visitor")
        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test 5 — Officer can withdraw any signup
# ---------------------------------------------------------------------------

class TestOfficerCanWithdrawAny:

    def setup_method(self):
        self.owner   = make_user("wo-t5-owner")
        self.ws      = make_workspace(owner_user_id=self.owner["id"], slug="wo-t5")
        self.op      = _make_published_op(self.ws["id"])
        self.visitor = make_user("wo-t5-visitor")
        self.client  = TestClient(app)

    def test_officer_withdraws_non_member_signup(self):
        # Non-member signs up.
        _login(self.client, "wo-t5-visitor")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t5-visitor")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t5-visitor")

        # Officer withdraws it.
        _login(self.client, "wo-t5-owner")
        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert not any(s["display_name"] == "wo-t5-visitor" for s in signups)


# ---------------------------------------------------------------------------
# Test 6 — ID-based check blocks different user even if display_name matches
# ---------------------------------------------------------------------------

class TestIdBasedOwnershipCheck:
    """New-style signups (source="web:{user_id}") are protected by ID only.

    The dev auth system cannot have two users with the same display_name, so
    we prove the protection by:
    a) signing up as User A → source = "web:{alice_id}"
    b) calling withdraw_signup_intent directly as User B (different ID)
    c) confirming PermissionDenied is raised despite Bob knowing Alice's signup_id

    We also verify the legacy path still works: a signup with bare source="web"
    falls back to display_name matching (known limitation, not fixable without
    schema change; acceptable for pre-existing signups).
    """

    def setup_method(self):
        self.owner = make_user("wo-t6-owner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="wo-t6")
        self.op    = _make_published_op(self.ws["id"])
        self.alice = make_user("wo-t6-alice")
        self.bob   = make_user("wo-t6-bob")
        self.client = TestClient(app)

    def test_new_style_signup_protected_by_user_id(self):
        """Bob cannot withdraw Alice's new-style signup even if he knows the ID."""
        _login(self.client, "wo-t6-alice")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t6-alice")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t6-alice")
        # Confirm source is stamped.
        src = _get_signups(self.ws["id"], self.op["id"])[0]["source"]
        assert src == f"web:{self.alice['id']}"

        # Bob tries to withdraw directly via use case.
        with pytest.raises(PermissionDenied):
            use_cases.withdraw_signup_intent(
                guild_workspace_id=self.ws["id"],
                guild_operation_id=self.op["id"],
                actor_user_id=self.bob["id"],
                signup_id=signup_id,
            )

    def test_source_stamped_not_web_plain(self):
        """New web signups must carry 'web:{user_id}', not bare 'web'."""
        _login(self.client, "wo-t6-alice")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t6-alice")
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert len(signups) == 1
        src = signups[0]["source"]
        assert src.startswith("web:"), f"Expected 'web:<id>', got {src!r}"
        assert len(src) > 4, "user_id must be non-empty after 'web:'"

    def test_legacy_source_web_allows_display_name_match(self):
        """Legacy signups (source='web') still fall back to display_name check."""
        # Create a signup directly in the DB with bare source='web' to simulate
        # a pre-existing row that predates user-ID stamping.
        with database.transaction() as db:
            import uuid as _uuid
            from app.application.use_cases import _now
            participant = repositories.find_or_create_participant(
                db, self.ws["id"], "wo-t6-alice"
            )
            legacy_signup = {
                "id": str(_uuid.uuid4()),
                "guild_workspace_id": self.ws["id"],
                "guild_operation_id": self.op["id"],
                "participant_id": participant["id"],
                "preferred_role": "Tank",
                "preferred_build_name": None,
                "willingness": "flexible",
                "availability": "confirmed",
                "source": "web",   # legacy — no user_id embedded
                "created_at": _now(),
            }
            repositories.insert_signup_intent(db, legacy_signup)

        # Alice (matching display_name) can still withdraw via display_name fallback.
        use_cases.withdraw_signup_intent(
            guild_workspace_id=self.ws["id"],
            guild_operation_id=self.op["id"],
            actor_user_id=self.alice["id"],
            signup_id=legacy_signup["id"],
        )
        # Signup removed.
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert not any(s["id"] == legacy_signup["id"] for s in signups)


# ---------------------------------------------------------------------------
# Test 7 — Workspace member behavior unchanged
# ---------------------------------------------------------------------------

class TestMemberBehaviorUnchanged:

    def setup_method(self):
        self.owner  = make_user("wo-t7-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="wo-t7")
        self.op     = _make_published_op(self.ws["id"])
        self.member = make_user("wo-t7-member")
        use_cases.add_workspace_member(self.ws["id"], self.owner["id"], "wo-t7-member", "member")
        self.client = TestClient(app)

    def test_member_can_withdraw_own_signup(self):
        _login(self.client, "wo-t7-member")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t7-member")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t7-member")

        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert not any(s["display_name"] == "wo-t7-member" for s in signups)

    def test_member_cannot_withdraw_officer_signup(self):
        # Owner signs up.
        _login(self.client, "wo-t7-owner")
        _post_signup(self.client, self.ws["slug"], self.op["id"], "wo-t7-owner")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t7-owner")

        # Member tries to withdraw it.
        _login(self.client, "wo-t7-member")
        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]
        # Signup still active.
        signups = _get_signups(self.ws["id"], self.op["id"])
        assert any(s["display_name"] == "wo-t7-owner" for s in signups)


# ---------------------------------------------------------------------------
# Test 8 — Unauthenticated POST withdraw redirects to login
# ---------------------------------------------------------------------------

class TestUnauthenticatedWithdraw:

    def setup_method(self):
        self.owner  = make_user("wo-t8-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="wo-t8")
        self.op     = _make_published_op(self.ws["id"])
        self.client = TestClient(app)

    def test_unauthenticated_withdraw_redirects_to_login(self):
        # Owner signs up (authenticated).
        auth_client = TestClient(app)
        _login(auth_client, "wo-t8-owner")
        _post_signup(auth_client, self.ws["slug"], self.op["id"], "wo-t8-owner")
        signup_id = _get_signup_id_for(self.ws["id"], self.op["id"], "wo-t8-owner")

        # Anonymous client tries to withdraw.
        resp = self.client.post(
            _withdraw_url(self.ws["slug"], self.op["id"], signup_id),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]
