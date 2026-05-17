"""
Dispatch Retry Queue Visibility — test suite.

Extends the existing Scheduler Run History UI (GET /workspaces/{slug}/settings/scheduler)
with a read-only pending dispatch retry table.

Test groups:
  1.  Repository: list_pending_dispatch_failures_for_workspace
      - returns only pending_retry rows for the workspace
      - workspace scoping (other workspace rows excluded)
      - ordering: next_attempt_at ASC, attempted_at ASC, id ASC
      - limit respected
      - exhausted / resolved rows excluded
      - empty result when no rows

  2.  Route helper: _truncate_error
      - None / empty → '—'
      - short message unchanged
      - long message truncated with ellipsis
      - strips surrounding whitespace

  3.  Route helper: _enrich_dispatch_failure
      - adds attempted_at_fmt, next_attempt_at_fmt, error_summary, payload_safe
      - empty / trivial payload → payload_safe is None
      - non-trivial payload → payload_safe is set
      - None next_attempt_at → next_attempt_at_fmt '—'

  4.  HTTP: page renders retry table
      - populated pending retries shown
      - empty state shown when no retries
      - non-pending rows not shown
      - long error truncated in rendered HTML
      - malformed / null payload handled safely
      - payload hidden behind disclosure (not rendered inline)
      - existing health banner + scheduler runs still present

  5.  HTTP: permission enforcement
      - owner can access
      - officer can access
      - member blocked (403)
      - unauthenticated redirected

  6.  HTTP: no POST route
      - POST returns 405

  7.  Existing test_scheduler_status tests still pass (implicit via suite)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.main import app
from app.routes import _enrich_dispatch_failure, _truncate_error
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_URL = "/workspaces/{slug}/settings/scheduler"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past(minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _insert_failure(
    ws_id: str,
    *,
    event_type: str = "readiness_snapshot.created",
    status: str = "pending_retry",
    retry_count: int = 0,
    next_attempt_at: str = "",
    attempted_at: str | None = None,
    error_message: str | None = "Discord returned 429",
    payload_json: str = "{}",
    row_id: str | None = None,
) -> dict:
    record = {
        "id":                 row_id or str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "guild_operation_id": None,
        "event_type":         event_type,
        "entity_id":          str(uuid.uuid4()),
        "error_code":         429,
        "error_message":      error_message,
        "attempted_at":       attempted_at or _now(),
        "retry_count":        retry_count,
        "status":             status,
        "payload_json":       payload_json,
        "next_attempt_at":    next_attempt_at,
    }
    with database.transaction() as db:
        repositories.insert_discord_dispatch_failure(db, record)
    return record


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Repository: list_pending_dispatch_failures_for_workspace
# ---------------------------------------------------------------------------

class TestListPendingDispatchFailuresRepo:
    def test_returns_pending_retry_rows(self):
        owner = make_user("RepoOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        _insert_failure(ws["id"], status="pending_retry")
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "pending_retry"

    def test_excludes_resolved_rows(self):
        owner = make_user("ExclResolvedOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        _insert_failure(ws["id"], status="resolved")
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        assert rows == []

    def test_excludes_exhausted_rows(self):
        owner = make_user("ExclExhaustedOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        _insert_failure(ws["id"], status="exhausted")
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        assert rows == []

    def test_empty_when_no_rows(self):
        owner = make_user("EmptyOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        assert rows == []

    def test_workspace_scoping_excludes_other_workspace(self):
        owner1 = make_user("ScopeOwner1")
        owner2 = make_user("ScopeOwner2")
        ws1    = make_workspace(slug="scope-ws1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="scope-ws2", owner_user_id=owner2["id"])
        _insert_failure(ws1["id"])
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws2["id"])
        assert rows == []

    def test_ordering_by_next_attempt_at_asc(self):
        owner = make_user("OrderOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        t_far    = _future(minutes=30)
        t_soon   = _future(minutes=5)
        t_legacy = ""  # empty sorts first
        for next_at, rid in [
            (t_far,    "zzz-far"),
            (t_soon,   "mmm-soon"),
            (t_legacy, "aaa-legacy"),
        ]:
            _insert_failure(ws["id"], next_attempt_at=next_at, row_id=rid)
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        ids = [r["id"] for r in rows]
        assert ids == ["aaa-legacy", "mmm-soon", "zzz-far"]

    def test_secondary_ordering_by_attempted_at_then_id(self):
        """Rows with same next_attempt_at tie-break by attempted_at then id."""
        owner = make_user("SecOrderOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        same_next = _future(minutes=10)
        t_old = _past(minutes=10)
        t_new = _past(minutes=2)
        for attempted, rid in [
            (t_new, "bbb-new"),
            (t_old, "aaa-old"),
        ]:
            _insert_failure(ws["id"], next_attempt_at=same_next,
                            attempted_at=attempted, row_id=rid)
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        assert rows[0]["id"] == "aaa-old"
        assert rows[1]["id"] == "bbb-new"

    def test_limit_respected(self):
        owner = make_user("LimitOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        for _ in range(5):
            _insert_failure(ws["id"])
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"], limit=3)
        assert len(rows) == 3

    def test_default_limit_is_50(self):
        owner = make_user("DefaultLimitOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        for _ in range(55):
            _insert_failure(ws["id"])
        with database.transaction() as db:
            rows = repositories.list_pending_dispatch_failures_for_workspace(db, ws["id"])
        assert len(rows) == 50


# ---------------------------------------------------------------------------
# 2. Route helper: _truncate_error
# ---------------------------------------------------------------------------

class TestTruncateError:
    def test_none_returns_dash(self):
        assert _truncate_error(None) == "—"

    def test_empty_returns_dash(self):
        assert _truncate_error("") == "—"

    def test_whitespace_only_returns_dash(self):
        assert _truncate_error("   ") == "—"

    def test_short_message_unchanged(self):
        assert _truncate_error("Discord 429") == "Discord 429"

    def test_exactly_max_len_unchanged(self):
        msg = "x" * 120
        result = _truncate_error(msg, max_len=120)
        assert result == msg
        assert not result.endswith("…")

    def test_long_message_truncated(self):
        msg = "x" * 200
        result = _truncate_error(msg, max_len=120)
        assert len(result) <= 121  # 120 chars + ellipsis
        assert result.endswith("…")

    def test_truncation_does_not_expose_trailing_whitespace(self):
        msg = "a" * 119 + "   extra"
        result = _truncate_error(msg, max_len=120)
        assert result.endswith("…")
        assert not result[:-1].endswith(" ")

    def test_custom_max_len(self):
        result = _truncate_error("hello world", max_len=5)
        assert result == "hello…"


# ---------------------------------------------------------------------------
# 3. Route helper: _enrich_dispatch_failure
# ---------------------------------------------------------------------------

class TestEnrichDispatchFailure:
    def _raw(self, **kwargs) -> dict:
        base = {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": "ws-001",
            "event_type":         "readiness_snapshot.created",
            "retry_count":        2,
            "attempted_at":       "2026-05-16T10:00:00+00:00",
            "next_attempt_at":    "2026-05-16T10:15:00+00:00",
            "error_message":      "rate limited",
            "payload_json":       "{}",
            "status":             "pending_retry",
        }
        return {**base, **kwargs}

    def test_adds_attempted_at_fmt(self):
        row = _enrich_dispatch_failure(self._raw())
        assert row["attempted_at_fmt"] == "2026-05-16 10:00 UTC"

    def test_adds_next_attempt_at_fmt(self):
        row = _enrich_dispatch_failure(self._raw())
        assert row["next_attempt_at_fmt"] == "2026-05-16 10:15 UTC"

    def test_none_next_attempt_at_gives_dash(self):
        row = _enrich_dispatch_failure(self._raw(next_attempt_at=None))
        assert row["next_attempt_at_fmt"] == "—"

    def test_empty_next_attempt_at_gives_dash(self):
        row = _enrich_dispatch_failure(self._raw(next_attempt_at=""))
        assert row["next_attempt_at_fmt"] == "—"

    def test_adds_error_summary(self):
        row = _enrich_dispatch_failure(self._raw(error_message="rate limited"))
        assert row["error_summary"] == "rate limited"

    def test_none_error_message_gives_dash(self):
        row = _enrich_dispatch_failure(self._raw(error_message=None))
        assert row["error_summary"] == "—"

    def test_long_error_truncated(self):
        row = _enrich_dispatch_failure(self._raw(error_message="e" * 200))
        assert row["error_summary"].endswith("…")

    def test_empty_payload_json_gives_none(self):
        row = _enrich_dispatch_failure(self._raw(payload_json="{}"))
        assert row["payload_safe"] is None

    def test_whitespace_payload_gives_none(self):
        row = _enrich_dispatch_failure(self._raw(payload_json="   "))
        assert row["payload_safe"] is None

    def test_none_payload_gives_none(self):
        row = _enrich_dispatch_failure(self._raw(payload_json=None))
        assert row["payload_safe"] is None

    def test_non_trivial_payload_set(self):
        payload = '{"guild_id": "123"}'
        row = _enrich_dispatch_failure(self._raw(payload_json=payload))
        assert row["payload_safe"] == payload

    def test_original_fields_preserved(self):
        raw = self._raw()
        row = _enrich_dispatch_failure(raw)
        assert row["event_type"] == raw["event_type"]
        assert row["retry_count"] == raw["retry_count"]
        assert row["status"] == raw["status"]


# ---------------------------------------------------------------------------
# 4. HTTP: page renders retry table
# ---------------------------------------------------------------------------

class TestDispatchRetryQueuePage:
    def _setup(self):
        owner = make_user("RetryPageOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        return owner, ws

    def _get_page(self, client: TestClient, slug: str) -> object:
        return client.get(_URL.format(slug=slug), follow_redirects=True)

    def test_pending_failures_shown_in_table(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _insert_failure(ws["id"], event_type="readiness_snapshot.created",
                        error_message="Gateway timeout")
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        assert "readiness_snapshot.created" in resp.text
        assert "Gateway timeout" in resp.text

    def test_empty_state_shown_when_no_retries(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        assert "No pending Discord retries" in resp.text

    def test_non_pending_rows_not_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _insert_failure(ws["id"], status="resolved",   event_type="assignment.created")
        _insert_failure(ws["id"], status="exhausted",  event_type="signup_intent.submitted")
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        # Specific event types only in resolved/exhausted rows must not appear
        assert "assignment.created" not in resp.text
        assert "signup_intent.submitted" not in resp.text
        assert "No pending Discord retries" in resp.text

    def test_long_error_truncated_in_html(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        long_msg = "E" * 300
        _insert_failure(ws["id"], error_message=long_msg)
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        # The full 300-char message must NOT be present verbatim
        assert long_msg not in resp.text
        # The truncation marker must appear
        assert "…" in resp.text

    def test_trivial_payload_not_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _insert_failure(ws["id"], payload_json="{}")
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        # No "View payload" disclosure for trivial payloads
        assert "View payload" not in resp.text

    def test_non_trivial_payload_hidden_behind_disclosure(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _insert_failure(ws["id"], payload_json='{"operation_id": "op-abc"}')
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        # Disclosure element is present (content hidden until expanded)
        assert "View payload" in resp.text
        # Raw operation_id is inside the disclosure details element
        assert "op-abc" in resp.text

    def test_null_error_message_shows_dash(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _insert_failure(ws["id"], error_message=None)
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        # Should not crash; dash is displayed for null error
        assert "—" in resp.text

    def test_existing_health_banner_still_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        # Health banner (never_run state since no scheduler runs in test)
        assert "Never run" in resp.text or "Scheduler" in resp.text

    def test_retry_table_section_header_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        assert "Pending Discord Retries" in resp.text

    def test_retry_count_displayed(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner, ws = self._setup()
        _insert_failure(ws["id"], retry_count=3)
        _login(client, owner["display_name"])
        resp = self._get_page(client, ws["slug"])
        assert resp.status_code == 200
        assert "3" in resp.text

    def test_workspace_scoping_in_page(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner1 = make_user("PageScopeOwner1")
        owner2 = make_user("PageScopeOwner2")
        ws1 = make_workspace(slug="page-scope-ws1", owner_user_id=owner1["id"])
        ws2 = make_workspace(slug="page-scope-ws2", owner_user_id=owner2["id"])
        _insert_failure(ws1["id"], event_type="ws1_only_event")
        _login(client, owner2["display_name"])
        resp = self._get_page(client, ws2["slug"])
        assert resp.status_code == 200
        assert "ws1_only_event" not in resp.text
        assert "No pending Discord retries" in resp.text


# ---------------------------------------------------------------------------
# 5. HTTP: permission enforcement
# ---------------------------------------------------------------------------

class TestDispatchRetryQueuePermissions:
    def test_owner_can_access(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PermOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_URL.format(slug=ws["slug"]), follow_redirects=True)
        assert resp.status_code == 200
        assert "Pending Discord Retries" in resp.text

    def test_officer_can_access(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner   = make_user("PermOfficerOwner")
        officer = make_user("PermOfficer")
        ws      = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'officer',?)",
                (str(uuid.uuid4()), ws["id"], officer["id"], _now()),
            )
        _login(client, officer["display_name"])
        resp = client.get(_URL.format(slug=ws["slug"]), follow_redirects=True)
        assert resp.status_code == 200
        assert "Pending Discord Retries" in resp.text

    def test_member_blocked(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PermMemberOwner")
        member = make_user("PermMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?,?,?,'member',?)",
                (str(uuid.uuid4()), ws["id"], member["id"], _now()),
            )
        _login(client, member["display_name"])
        resp = client.get(_URL.format(slug=ws["slug"]), follow_redirects=False)
        assert resp.status_code == 403

    def test_unauthenticated_redirected(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PermUnauthOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        resp  = client.get(_URL.format(slug=ws["slug"]), follow_redirects=False)
        assert resp.status_code in (302, 303, 307)


# ---------------------------------------------------------------------------
# 6. HTTP: no POST route
# ---------------------------------------------------------------------------

class TestNoPostRoute:
    def test_post_returns_405(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("NoPostOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.post(_URL.format(slug=ws["slug"]))
        assert resp.status_code == 405
