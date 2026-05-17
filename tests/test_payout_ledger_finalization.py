"""
Payout Ledger Finalization Integrity — test suite (Slice 42).

Test groups:
  1.  Domain: assert_payable
      - approved entry is payable
      - draft entry is not payable
      - voided entry is not payable
      - paid entry (already) raises "already paid"

  2.  Repository: mark_payout_ledger_entry_paid
      - sets status to 'paid'
      - sets paid_at
      - sets paid_by_user_id
      - updates updated_at
      - returns 1 on success
      - returns 0 for unknown entry

  3.  Use case: mark_payout_ledger_entry_paid — happy path
      - approved → paid succeeds
      - paid_at and paid_by_user_id persisted
      - PAYOUT_LEDGER_ENTRY_PAID operational event emitted
      - event payload contains entry_type / amount_silver / participant_id

  4.  Use case: invalid transitions
      - draft → paid raises ValidationError
      - voided → paid raises ValidationError
      - paid → paid raises ValidationError (double-paid prevention)

  5.  Use case: RBAC
      - owner can mark paid
      - officer can mark paid
      - member cannot mark paid (PermissionDenied)
      - non-member cannot mark paid (PermissionDenied)

  6.  Use case: paid immutability — no further state changes
      - paid entry cannot be voided
      - paid entry cannot be approved
      - paid entry cannot be updated (edit amount/note)

  7.  HTTP POST /ledger/{entry_id}/mark-paid
      - owner: 303 redirect to ledger URL
      - officer: 303 redirect to ledger URL
      - member: 403
      - unauthenticated: redirect to login
      - draft entry: error redirect
      - approved entry: success redirect
      - already-paid entry: error redirect

  8.  HTTP GET ledger page — UI visibility
      - approved entry shows "Mark paid" button
      - draft entry does NOT show "Mark paid" button
      - paid entry does NOT show "Mark paid" button
      - voided entry does NOT show "Mark paid" button

  9.  Paid audit column
      - paid_at shown in audit column for paid entries
      - paid_by display_name shown for paid entries
      - ✓ symbol present for paid entries
      - paid_at not shown for non-paid entries

 10.  Timeline rendering
      - PAID event renders "Ledger entry paid" label
      - timeline shows payout detail (entry_type, amount_silver)
      - actor attribution shown

 11.  CSV export — paid columns
      - paid_at present in header
      - paid_by present in header
      - paid entry: paid_at and paid_by populated
      - non-paid entry: paid_at and paid_by empty
      - paid_by resolved to display_name

 12.  Existing export test guard
      - paid_at / paid_by columns appear in all exports (backward compat)
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import payout_ledger as payout_ledger_domain
from app.errors import NotFoundError, PermissionDenied, ValidationError
from app.main import app
from tests.conftest import make_operation, make_user, make_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _make_member(ws_id: str, user_id: str, role: str = "member") -> None:
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), ws_id, user_id, role, _now()),
        )


def _make_participant(ws_id: str, display_name: str = "Blade") -> dict:
    with database.transaction() as db:
        pid = str(uuid.uuid4())
        now = _now()
        db.execute(
            "INSERT INTO participants (id, guild_workspace_id, display_name, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (pid, ws_id, display_name, now, now),
        )
    return {"id": pid, "display_name": display_name}


def _create_entry(ws_id, op_id, participant_id, creator_id, **kw) -> dict:
    return use_cases.create_payout_ledger_entry(
        guild_workspace_id=ws_id,
        guild_operation_id=op_id,
        participant_id=participant_id,
        entry_type=kw.get("entry_type", "payout"),
        amount_silver=kw.get("amount_silver", 1000),
        note=kw.get("note"),
        actor_user_id=creator_id,
    )


def _approve(ws_id, entry_id, actor_id):
    use_cases.approve_payout_ledger_entry(
        guild_workspace_id=ws_id,
        entry_id=entry_id,
        actor_user_id=actor_id,
    )


def _mark_paid(ws_id, entry_id, actor_id):
    use_cases.mark_payout_ledger_entry_paid(
        guild_workspace_id=ws_id,
        entry_id=entry_id,
        actor_user_id=actor_id,
    )


def _get_entry(ws_id, entry_id) -> dict:
    with database.transaction() as db:
        return repositories.get_payout_ledger_entry(db, entry_id, ws_id)


def _mark_paid_url(ws_slug, op_id, entry_id):
    return f"/workspaces/{ws_slug}/operations/{op_id}/ledger/{entry_id}/mark-paid"


def _ledger_url(ws_slug, op_id):
    return f"/workspaces/{ws_slug}/operations/{op_id}/ledger"


def _export_url(ws_slug, op_id):
    return f"/workspaces/{ws_slug}/operations/{op_id}/ledger/export.csv"


def _parse_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


# ---------------------------------------------------------------------------
# 1. Domain: assert_payable
# ---------------------------------------------------------------------------

class TestAssertPayable:
    def _entry(self, status: str) -> dict:
        return {"id": "x", "status": status}

    def test_approved_is_payable(self):
        payout_ledger_domain.assert_payable(self._entry("approved"))  # no raise

    def test_draft_is_not_payable(self):
        with pytest.raises(ValidationError, match="Only approved"):
            payout_ledger_domain.assert_payable(self._entry("draft"))

    def test_voided_is_not_payable(self):
        with pytest.raises(ValidationError, match="Only approved"):
            payout_ledger_domain.assert_payable(self._entry("voided"))

    def test_already_paid_raises(self):
        with pytest.raises(ValidationError, match="already paid"):
            payout_ledger_domain.assert_payable(self._entry("paid"))


# ---------------------------------------------------------------------------
# 2. Repository: mark_payout_ledger_entry_paid
# ---------------------------------------------------------------------------

class TestRepoMarkPaid:
    def _setup(self):
        owner = make_user("RepoPaidOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        return owner, ws, op, p, entry

    def test_sets_status_paid(self):
        owner, ws, _, _, entry = self._setup()
        with database.transaction() as db:
            repositories.mark_payout_ledger_entry_paid(
                db, entry["id"], ws["id"], _now(), owner["id"]
            )
        assert _get_entry(ws["id"], entry["id"])["status"] == "paid"

    def test_sets_paid_at(self):
        owner, ws, _, _, entry = self._setup()
        ts = "2026-05-01T12:00:00"
        with database.transaction() as db:
            repositories.mark_payout_ledger_entry_paid(
                db, entry["id"], ws["id"], ts, owner["id"]
            )
        assert _get_entry(ws["id"], entry["id"])["paid_at"] == ts

    def test_sets_paid_by_user_id(self):
        owner, ws, _, _, entry = self._setup()
        with database.transaction() as db:
            repositories.mark_payout_ledger_entry_paid(
                db, entry["id"], ws["id"], _now(), owner["id"]
            )
        assert _get_entry(ws["id"], entry["id"])["paid_by_user_id"] == owner["id"]

    def test_updates_updated_at(self):
        owner, ws, _, _, entry = self._setup()
        ts = "2026-05-10T08:00:00"
        with database.transaction() as db:
            repositories.mark_payout_ledger_entry_paid(
                db, entry["id"], ws["id"], ts, owner["id"]
            )
        assert _get_entry(ws["id"], entry["id"])["updated_at"] == ts

    def test_returns_1_on_success(self):
        owner, ws, _, _, entry = self._setup()
        with database.transaction() as db:
            rc = repositories.mark_payout_ledger_entry_paid(
                db, entry["id"], ws["id"], _now(), owner["id"]
            )
        assert rc == 1

    def test_returns_0_for_unknown_entry(self):
        _, ws, _, _, _ = self._setup()
        with database.transaction() as db:
            rc = repositories.mark_payout_ledger_entry_paid(
                db, str(uuid.uuid4()), ws["id"], _now(), "x"
            )
        assert rc == 0


# ---------------------------------------------------------------------------
# 3. Use case: mark_payout_ledger_entry_paid — happy path
# ---------------------------------------------------------------------------

class TestUseCaseMarkPaidHappy:
    def _setup(self):
        owner = make_user("UCPaidHappyOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        return owner, ws, op, p, entry

    def test_approved_to_paid_succeeds(self):
        owner, ws, _, _, entry = self._setup()
        _mark_paid(ws["id"], entry["id"], owner["id"])
        assert _get_entry(ws["id"], entry["id"])["status"] == "paid"

    def test_paid_at_persisted(self):
        owner, ws, _, _, entry = self._setup()
        _mark_paid(ws["id"], entry["id"], owner["id"])
        assert _get_entry(ws["id"], entry["id"])["paid_at"] is not None

    def test_paid_by_persisted(self):
        owner, ws, _, _, entry = self._setup()
        _mark_paid(ws["id"], entry["id"], owner["id"])
        assert _get_entry(ws["id"], entry["id"])["paid_by_user_id"] == owner["id"]

    def test_operational_event_emitted(self):
        owner, ws, op, _, entry = self._setup()
        _mark_paid(ws["id"], entry["id"], owner["id"])
        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])
        paid_events = [e for e in events if e["event_type"] == "payout_ledger.entry.paid"]
        assert len(paid_events) == 1

    def test_event_payload_contains_entry_type(self):
        owner, ws, op, _, entry = self._setup()
        _mark_paid(ws["id"], entry["id"], owner["id"])
        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])
        paid_ev = next(e for e in events if e["event_type"] == "payout_ledger.entry.paid")
        payload = json.loads(paid_ev["payload_json"])
        assert payload["entry_type"] == "payout"

    def test_event_payload_contains_amount_silver(self):
        owner, ws, op, _, entry = self._setup()
        _mark_paid(ws["id"], entry["id"], owner["id"])
        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])
        paid_ev = next(e for e in events if e["event_type"] == "payout_ledger.entry.paid")
        payload = json.loads(paid_ev["payload_json"])
        assert payload["amount_silver"] == 1000


# ---------------------------------------------------------------------------
# 4. Use case: invalid transitions
# ---------------------------------------------------------------------------

class TestUseCaseInvalidTransitions:
    def _setup(self, status: str):
        owner = make_user(f"UCInvalidTrans{status}")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        if status in ("voided",):
            use_cases.void_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )
        elif status == "paid":
            _approve(ws["id"], entry["id"], owner["id"])
            _mark_paid(ws["id"], entry["id"], owner["id"])
        return owner, ws, entry

    def test_draft_to_paid_raises(self):
        owner, ws, entry = self._setup("draft")
        with pytest.raises(ValidationError, match="Only approved"):
            _mark_paid(ws["id"], entry["id"], owner["id"])

    def test_voided_to_paid_raises(self):
        owner, ws, entry = self._setup("voided")
        with pytest.raises(ValidationError, match="Only approved"):
            _mark_paid(ws["id"], entry["id"], owner["id"])

    def test_double_paid_raises(self):
        owner, ws, entry = self._setup("paid")
        with pytest.raises(ValidationError, match="already paid"):
            _mark_paid(ws["id"], entry["id"], owner["id"])


# ---------------------------------------------------------------------------
# 5. Use case: RBAC
# ---------------------------------------------------------------------------

class TestUseCaseRBAC:
    def _approved_entry(self):
        owner = make_user("RBACPaidOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        return owner, ws, entry

    def test_owner_can_mark_paid(self):
        owner, ws, entry = self._approved_entry()
        _mark_paid(ws["id"], entry["id"], owner["id"])  # no raise

    def test_officer_can_mark_paid(self):
        owner, ws, entry = self._approved_entry()
        officer = make_user("RBACPaidOfficer")
        _make_member(ws["id"], officer["id"], "officer")
        _mark_paid(ws["id"], entry["id"], officer["id"])  # no raise

    def test_member_cannot_mark_paid(self):
        owner, ws, entry = self._approved_entry()
        member = make_user("RBACPaidMember")
        _make_member(ws["id"], member["id"], "member")
        with pytest.raises(PermissionDenied):
            _mark_paid(ws["id"], entry["id"], member["id"])

    def test_non_member_cannot_mark_paid(self):
        _, ws, entry = self._approved_entry()
        stranger = make_user("RBACPaidStranger")
        with pytest.raises(PermissionDenied):
            _mark_paid(ws["id"], entry["id"], stranger["id"])


# ---------------------------------------------------------------------------
# 6. Use case: paid immutability — no further state changes
# ---------------------------------------------------------------------------

class TestPaidImmutability:
    def _paid_entry(self):
        owner = make_user("ImmutPaidOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        return owner, ws, entry

    def test_paid_entry_cannot_be_voided(self):
        owner, ws, entry = self._paid_entry()
        with pytest.raises(ValidationError, match="cannot be voided"):
            use_cases.void_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_paid_entry_cannot_be_approved_again(self):
        owner, ws, entry = self._paid_entry()
        with pytest.raises(ValidationError):
            use_cases.approve_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_paid_entry_cannot_be_updated(self):
        owner, ws, entry = self._paid_entry()
        with pytest.raises(ValidationError):
            use_cases.update_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                amount_silver=9999,
                note="changed",
                actor_user_id=owner["id"],
            )


# ---------------------------------------------------------------------------
# 7. HTTP POST /ledger/{entry_id}/mark-paid
# ---------------------------------------------------------------------------

class TestHttpMarkPaid:
    def _approved_entry(self, user_suffix=""):
        owner = make_user(f"HttpMarkPaidOwner{user_suffix}")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        return owner, ws, op, entry

    def test_owner_gets_303_redirect(self):
        owner, ws, op, entry = self._approved_entry("Owner")
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, owner["display_name"])
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/ledger" in resp.headers["location"]

    def test_officer_gets_303_redirect(self):
        owner, ws, op, entry = self._approved_entry("Offr")
        officer = make_user("HttpMarkPaidOfficer")
        _make_member(ws["id"], officer["id"], "officer")
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, officer["display_name"])
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_member_gets_403(self):
        owner, ws, op, entry = self._approved_entry("Memb")
        member = make_user("HttpMarkPaidMember")
        _make_member(ws["id"], member["id"], "member")
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, member["display_name"])
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
        )
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self):
        owner, ws, op, entry = self._approved_entry("Unauth")
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 307)
        assert "login" in resp.headers["location"].lower()

    def test_draft_entry_error_redirect(self):
        owner = make_user("HttpMarkPaidDraftOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _create_entry(ws["id"], op["id"], p["id"], owner["id"])  # draft
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, owner["display_name"])
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "error" in str(resp.url).lower() or "error" in resp.text.lower()

    def test_approved_entry_success_redirect(self):
        owner, ws, op, entry = self._approved_entry("Succ")
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, owner["display_name"])
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert _get_entry(ws["id"], entry["id"])["status"] == "paid"

    def test_already_paid_entry_error_redirect(self):
        owner, ws, op, entry = self._approved_entry("AlrPaid")
        _mark_paid(ws["id"], entry["id"], owner["id"])
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, owner["display_name"])
        resp = client.post(
            _mark_paid_url(ws["slug"], op["id"], entry["id"]),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "error" in str(resp.url).lower() or "error" in resp.text.lower()


# ---------------------------------------------------------------------------
# 8. HTTP GET ledger page — UI visibility
# ---------------------------------------------------------------------------

class TestMarkPaidUIVisibility:
    def test_approved_entry_shows_mark_paid_button(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("UIMarkPaidApprOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert "Mark paid" in resp.text

    def test_draft_entry_no_mark_paid_button(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("UIMarkPaidDraftOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert "mark-paid" not in resp.text

    def test_paid_entry_no_mark_paid_button(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("UIMarkPaidPaidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert "mark-paid" not in resp.text

    def test_voided_entry_no_mark_paid_button(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("UIMarkPaidVoidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        use_cases.void_payout_ledger_entry(
            guild_workspace_id=ws["id"], entry_id=entry["id"],
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert "mark-paid" not in resp.text


# ---------------------------------------------------------------------------
# 9. Paid audit column
# ---------------------------------------------------------------------------

class TestPaidAuditColumn:
    def test_paid_at_shown_in_audit_column(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditPaidAtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        stored = _get_entry(ws["id"], entry["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert stored["paid_at"][:10] in resp.text

    def test_paid_by_display_name_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditPaidByOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert owner["display_name"] in resp.text

    def test_checkmark_symbol_present_for_paid(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditCheckOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert "✓" in resp.text

    def test_paid_at_not_shown_for_draft_entry(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditNoPaidAtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_ledger_url(ws["slug"], op["id"]))
        assert "✓" not in resp.text


# ---------------------------------------------------------------------------
# 10. Timeline rendering
# ---------------------------------------------------------------------------

class TestTimelinePaidEvent:
    def test_paid_event_renders_ledger_entry_paid_label(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TLPaidLabelOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline")
        assert "Ledger entry paid" in resp.text

    def test_paid_timeline_shows_amount(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TLPaidAmtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"], amount_silver=7500)
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline")
        assert "7,500" in resp.text

    def test_paid_timeline_shows_actor_attribution(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TLPaidActorOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline")
        assert "Officer action" in resp.text


# ---------------------------------------------------------------------------
# 11. CSV export — paid columns
# ---------------------------------------------------------------------------

class TestCsvPaidColumns:
    def test_paid_at_in_header(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("CsvPaidHdrOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert "paid_at" in resp.text.splitlines()[0]

    def test_paid_by_in_header(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("CsvPaidByHdrOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert "paid_by" in resp.text.splitlines()[0]

    def test_paid_entry_has_paid_at_and_paid_by(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("CsvPaidValOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        assert rows[0]["paid_at"] != ""
        assert rows[0]["paid_by"] == owner["display_name"]

    def test_non_paid_entry_has_empty_paid_columns(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("CsvNoPaidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _create_entry(ws["id"], op["id"], p["id"], owner["id"])  # draft
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["paid_at"] == ""
        assert rows[0]["paid_by"] == ""

    def test_paid_by_resolved_to_display_name(self):
        client  = TestClient(app, raise_server_exceptions=True)
        owner   = make_user("CsvPaidByResOwner")
        officer = make_user("CsvPaidByResOfficer")
        ws      = make_workspace(owner_user_id=owner["id"])
        op      = make_operation(ws["id"])
        p       = _make_participant(ws["id"])
        _make_member(ws["id"], officer["id"], "officer")
        entry   = _create_entry(ws["id"], op["id"], p["id"], owner["id"])
        _approve(ws["id"], entry["id"], owner["id"])
        _mark_paid(ws["id"], entry["id"], officer["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["paid_by"] == officer["display_name"]


# ---------------------------------------------------------------------------
# 12. Existing export test guard — paid columns appear in all exports
# ---------------------------------------------------------------------------

class TestExportBackwardCompat:
    def test_empty_export_includes_paid_columns(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("ExportCompatOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        first_line = resp.text.splitlines()[0]
        assert "paid_at" in first_line
        assert "paid_by" in first_line
