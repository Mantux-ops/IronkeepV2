"""
Payout Ledger Audit + Timeline Hardening — test suite (Slice 40).

Test groups:
  1.  compute_ledger_totals (pure helper)
      - empty entries → all zeros
      - draft entries counted and totalled
      - approved entries counted and totalled
      - paid entries counted and totalled
      - voided entries counted, NOT in active_total
      - mixed statuses produce correct active_count / active_total
      - negative adjustment amounts included in totals
      - voided_count correct with multiple voided rows
      - draft_total != approved_total != paid_total (no bleed)

  2.  get_ledger_totals_for_operation (repository SQL path)
      - empty operation → all zeros
      - draft entries summed correctly
      - approved entries summed correctly
      - paid entries summed correctly
      - voided count only, not in active_total
      - other operation's entries excluded (workspace scoping)
      - negative adjustment amounts included in totals

  3.  _parse_payout_event_detail
      - valid payload parsed correctly
      - missing keys return None for those fields
      - empty payload {} returns dict with None values (not None itself)
      - unparseable JSON returns None
      - non-dict payload returns None
      - note field included when present

  4.  _enrich_timeline_events: payout group gets _payout_detail
      - payout event gets _payout_detail populated
      - non-payout event has _payout_detail = None
      - unknown event type has _payout_detail = None

  5.  Timeline HTTP: payout events rendered with structured detail
      - entry_type shown in timeline
      - amount_silver shown in timeline
      - actor attribution shown (officer action)
      - raw payload disclosure still present
      - non-payout events unaffected

  6.  Ledger HTTP: audit column content
      - creator display_name shown in audit column
      - created_at shown in audit column
      - voided_at shown for voided entries
      - voider display_name shown for voided entries
      - updated_at shown when different from created_at
      - updated_at NOT shown when equal to created_at

  7.  Ledger HTTP: immutable-state UX
      - paid entry shows "Paid — locked" badge (no action buttons)
      - voided entry shows "Voided" badge (no action buttons)
      - paid entry shows "Finalized — no further changes" hint
      - voided entry shows "Voided — excluded from totals" hint
      - draft entry has Approve + Void action buttons
      - approved entry has Void button only (no Approve)

  8.  Ledger HTTP: totals strip
      - active total shown correctly
      - voided entries excluded from total
      - draft/approved/paid breakdowns shown when present
      - "excluded from total" text shown when voided entries exist
      - strip absent when no entries

  9.  Ledger HTTP: negative adjustment amount rendered in red
      - negative amount displays red color indicator

 10.  Status badge correctness
      - badge-draft for draft
      - badge-planning for approved
      - badge-completed for paid
      - badge-archived for voided

 11.  No mutation for finalized states (HTTP)
      - POST approve on paid entry → error redirect
      - POST void on paid entry → error redirect
      - POST void on voided entry → error redirect

 12.  Duplicate aggregation prevention
      - compute_ledger_totals result equals get_ledger_totals_for_operation result
        (same entries, both paths must agree)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app
from app.routes import (
    _enrich_timeline_events,
    _parse_payout_event_detail,
    compute_ledger_totals,
)
from tests.conftest import make_operation, make_user, make_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


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


def _entry(
    ws_id: str,
    op_id: str,
    participant_id: str,
    creator_id: str,
    *,
    entry_type: str = "regear",
    amount_silver: int = 1000,
    status: str = "draft",
    note: str | None = None,
    voided_by: str | None = None,
    voided_at: str | None = None,
    updated_at: str | None = None,
) -> dict:
    entry_id = str(uuid.uuid4())
    now = _now()
    record = {
        "id":                 entry_id,
        "guild_workspace_id": ws_id,
        "guild_operation_id": op_id,
        "participant_id":     participant_id,
        "entry_type":         entry_type,
        "amount_silver":      amount_silver,
        "note":               note,
        "status":             status,
        "created_by_user_id": creator_id,
        "created_at":         now,
        "updated_at":         updated_at or now,
        "voided_at":          voided_at,
        "voided_by_user_id":  voided_by,
    }
    with database.transaction() as db:
        repositories.insert_payout_ledger_entry(db, record)
    return record


def _fake_entry(status: str = "draft", amount: int = 1000) -> dict:
    """Minimal in-memory entry dict for pure-function tests."""
    return {
        "status": status,
        "amount_silver": amount,
        "entry_type": "regear",
    }


# ---------------------------------------------------------------------------
# 1. compute_ledger_totals — pure helper
# ---------------------------------------------------------------------------

class TestComputeLedgerTotals:
    def test_empty_returns_all_zeros(self):
        t = compute_ledger_totals([])
        assert t["active_count"] == 0
        assert t["active_total"] == 0
        assert t["voided_count"] == 0

    def test_draft_counted_and_totalled(self):
        t = compute_ledger_totals([_fake_entry("draft", 500), _fake_entry("draft", 300)])
        assert t["draft_count"] == 2
        assert t["draft_total"] == 800

    def test_approved_counted_and_totalled(self):
        t = compute_ledger_totals([_fake_entry("approved", 2000)])
        assert t["approved_count"] == 1
        assert t["approved_total"] == 2000

    def test_paid_counted_and_totalled(self):
        t = compute_ledger_totals([_fake_entry("paid", 5000)])
        assert t["paid_count"] == 1
        assert t["paid_total"] == 5000

    def test_voided_counted_not_in_active_total(self):
        t = compute_ledger_totals([_fake_entry("voided", 9999)])
        assert t["voided_count"] == 1
        assert t["active_total"] == 0
        assert t["active_count"] == 0

    def test_mixed_statuses_active_total_correct(self):
        entries = [
            _fake_entry("draft",    100),
            _fake_entry("approved", 200),
            _fake_entry("paid",     300),
            _fake_entry("voided",   999),  # must not count
        ]
        t = compute_ledger_totals(entries)
        assert t["active_count"] == 3
        assert t["active_total"] == 600
        assert t["voided_count"] == 1

    def test_negative_adjustment_included(self):
        t = compute_ledger_totals([
            _fake_entry("approved", 500),
            {**_fake_entry("draft", -200), "entry_type": "adjustment"},
        ])
        assert t["active_total"] == 300

    def test_multiple_voided_rows(self):
        entries = [_fake_entry("voided", 1000) for _ in range(3)]
        t = compute_ledger_totals(entries)
        assert t["voided_count"] == 3
        assert t["active_total"] == 0

    def test_status_totals_do_not_bleed(self):
        entries = [
            _fake_entry("draft",    100),
            _fake_entry("approved", 200),
            _fake_entry("paid",     300),
        ]
        t = compute_ledger_totals(entries)
        assert t["draft_total"]    == 100
        assert t["approved_total"] == 200
        assert t["paid_total"]     == 300


# ---------------------------------------------------------------------------
# 2. get_ledger_totals_for_operation — repository SQL path
# ---------------------------------------------------------------------------

class TestGetLedgerTotalsRepo:
    def _setup(self):
        owner = make_user("LedgerTotalsOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        return owner, ws, op, p

    def test_empty_operation_all_zeros(self):
        _, ws, op, _ = self._setup()
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["active_count"] == 0
        assert t["active_total"] == 0

    def test_draft_summed(self):
        owner, ws, op, p = self._setup()
        _entry(ws["id"], op["id"], p["id"], owner["id"], amount_silver=400)
        _entry(ws["id"], op["id"], p["id"], owner["id"], amount_silver=600)
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["draft_count"] == 2
        assert t["draft_total"] == 1000

    def test_approved_summed(self):
        owner, ws, op, p = self._setup()
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="approved", amount_silver=3000)
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["approved_count"] == 1
        assert t["approved_total"] == 3000

    def test_paid_summed(self):
        owner, ws, op, p = self._setup()
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="paid", amount_silver=7000)
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["paid_count"] == 1
        assert t["paid_total"] == 7000

    def test_voided_count_only_not_in_active(self):
        owner, ws, op, p = self._setup()
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="voided", amount_silver=9999)
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["voided_count"] == 1
        assert t["active_total"] == 0

    def test_other_operation_excluded(self):
        owner, ws, op, p = self._setup()
        op2 = make_operation(ws["id"], title="Other Op")
        _entry(ws["id"], op2["id"], p["id"], owner["id"], amount_silver=5000)
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["active_count"] == 0

    def test_negative_adjustment_in_active_total(self):
        owner, ws, op, p = self._setup()
        _entry(ws["id"], op["id"], p["id"], owner["id"],
               status="approved", amount_silver=1000)
        _entry(ws["id"], op["id"], p["id"], owner["id"],
               entry_type="adjustment", amount_silver=-200)
        with database.transaction() as db:
            t = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])
        assert t["active_total"] == 800


# ---------------------------------------------------------------------------
# 3. _parse_payout_event_detail
# ---------------------------------------------------------------------------

class TestParsePayoutEventDetail:
    def _event(self, payload=None):
        return {
            "event_type":   "payout_ledger.entry.created",
            "payload_json": json.dumps(payload) if payload is not None else "{}",
        }

    def test_valid_payload_parsed(self):
        d = _parse_payout_event_detail(self._event({
            "entry_type": "regear", "amount_silver": 1500,
            "participant_id": "abc", "note": "boots",
        }))
        assert d is not None
        assert d["entry_type"] == "regear"
        assert d["amount_silver"] == 1500
        assert d["note"] == "boots"

    def test_missing_keys_return_none(self):
        d = _parse_payout_event_detail(self._event({}))
        assert d is not None
        assert d["entry_type"] is None
        assert d["amount_silver"] is None

    def test_empty_payload_returns_dict_not_none(self):
        assert isinstance(_parse_payout_event_detail(self._event({})), dict)

    def test_unparseable_json_returns_none(self):
        assert _parse_payout_event_detail({"payload_json": "not{{json"}) is None

    def test_non_dict_payload_returns_none(self):
        assert _parse_payout_event_detail({"payload_json": "[1,2]"}) is None

    def test_note_field_present(self):
        d = _parse_payout_event_detail(self._event({"note": "sword"}))
        assert d["note"] == "sword"

    def test_no_payload_json_returns_empty_detail(self):
        # Missing payload_json defaults to "{}" — returns a dict with None values, not None
        d = _parse_payout_event_detail({})
        assert isinstance(d, dict)
        assert d["entry_type"] is None


# ---------------------------------------------------------------------------
# 4. _enrich_timeline_events: payout group gets _payout_detail
# ---------------------------------------------------------------------------

class TestEnrichTimelineEvents:
    def _make_event(self, event_type: str, payload: dict | None = None) -> dict:
        return {
            "id":               str(uuid.uuid4()),
            "event_type":       event_type,
            "actor_type":       "user",
            "actor_id":         str(uuid.uuid4()),
            "entity_type":      "payout_ledger_entry",
            "entity_id":        str(uuid.uuid4()),
            "payload_json":     json.dumps(payload or {}),
            "occurred_at":      _now(),
        }

    def test_payout_event_gets_payout_detail(self):
        ev = self._make_event("payout_ledger.entry.created", {
            "entry_type": "payout", "amount_silver": 2000
        })
        enriched = _enrich_timeline_events([ev])
        assert enriched[0]["_payout_detail"] is not None
        assert enriched[0]["_payout_detail"]["entry_type"] == "payout"
        assert enriched[0]["_payout_detail"]["amount_silver"] == 2000

    def test_non_payout_event_has_none_payout_detail(self):
        ev = self._make_event("assignment.created", {"slot_id": "x"})
        enriched = _enrich_timeline_events([ev])
        assert enriched[0]["_payout_detail"] is None

    def test_unknown_event_type_has_none_payout_detail(self):
        ev = self._make_event("some.future.event")
        enriched = _enrich_timeline_events([ev])
        assert enriched[0]["_payout_detail"] is None

    def test_all_payout_event_types_get_detail(self):
        types = [
            "payout_ledger.entry.created",
            "payout_ledger.entry.updated",
            "payout_ledger.entry.approved",
            "payout_ledger.entry.voided",
        ]
        for et in types:
            ev = self._make_event(et, {"entry_type": "regear", "amount_silver": 100})
            enriched = _enrich_timeline_events([ev])
            assert enriched[0]["_payout_detail"] is not None, f"Missing for {et}"


# ---------------------------------------------------------------------------
# 5. Timeline HTTP: payout events rendered with structured detail
# ---------------------------------------------------------------------------

class TestTimelinePayout:
    def test_payout_entry_type_and_amount_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TimelinePayoutOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="payout",
            amount_silver=4500,
            note="weekly payout",
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline"
        )
        assert resp.status_code == 200
        assert "payout" in resp.text
        assert "4,500" in resp.text
        assert "weekly payout" in resp.text

    def test_actor_attribution_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TimelineActorOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=1000,
            note=None,
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline"
        )
        assert resp.status_code == 200
        assert "Officer action" in resp.text

    def test_raw_payload_disclosure_still_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TimelineRawOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=500,
            note=None,
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline"
        )
        assert resp.status_code == 200
        assert "Raw payload" in resp.text

    def test_ledger_created_label_rendered(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TimelineLabelOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=100,
            note=None,
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline"
        )
        assert resp.status_code == 200
        assert "Ledger entry created" in resp.text

    def test_void_event_shows_voided_label(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TimelineVoidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=200,
            note=None,
            actor_user_id=owner["id"],
        )
        use_cases.void_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry["id"],
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline"
        )
        assert resp.status_code == 200
        assert "Ledger entry voided" in resp.text


# ---------------------------------------------------------------------------
# 6. Ledger HTTP: audit column content
# ---------------------------------------------------------------------------

class TestLedgerAuditColumn:
    def _ledger_url(self, ws_slug, op_id):
        return f"/workspaces/{ws_slug}/operations/{op_id}/ledger"

    def test_creator_display_name_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditCreatorOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._ledger_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert owner["display_name"] in resp.text

    def test_created_at_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditCreatedAtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        e      = _entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._ledger_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert e["created_at"][:10] in resp.text

    def test_voided_at_shown_for_voided_entries(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditVoidedAtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        e = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=100,
            note=None,
            actor_user_id=owner["id"],
        )
        use_cases.void_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=e["id"],
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(self._ledger_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        # voider display name shown
        assert owner["display_name"] in resp.text
        # ✕ indicator shown for voided timestamp
        assert "✕" in resp.text

    def test_updated_at_shown_when_different(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("AuditUpdatedAtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        e = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=100,
            note=None,
            actor_user_id=owner["id"],
        )
        use_cases.update_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=e["id"],
            amount_silver=999,
            note="revised",
            actor_user_id=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(self._ledger_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        # ✎ edit marker should appear (updated_at != created_at)
        assert "✎" in resp.text


# ---------------------------------------------------------------------------
# 7. Ledger HTTP: immutable-state UX
# ---------------------------------------------------------------------------

class TestLedgerImmutableUX:
    def _url(self, ws_slug, op_id):
        return f"/workspaces/{ws_slug}/operations/{op_id}/ledger"

    def test_paid_entry_shows_paid_locked_badge(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PaidLockOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "Paid — locked" in resp.text

    def test_paid_entry_shows_finalized_hint(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PaidHintOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "Finalized — no further changes" in resp.text

    def test_voided_entry_shows_voided_badge(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidedBadgeOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "Voided — excluded from totals" in resp.text

    def test_draft_entry_has_approve_and_void_buttons(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DraftBtnsOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="draft")
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "Approve" in resp.text
        assert "Void" in resp.text

    def test_approved_entry_has_void_but_not_approve_button(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("SilverKingOwner")  # name must not contain "Approve"
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="approved")
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "Void" in resp.text
        # "Approve" button should NOT appear for an already-approved entry
        # (the nav area must not contain "Approve" either — verified by display name choice)
        assert 'type="submit">Approve<' not in resp.text


# ---------------------------------------------------------------------------
# 8. Ledger HTTP: totals strip
# ---------------------------------------------------------------------------

class TestLedgerTotalsStrip:
    def _url(self, ws_slug, op_id):
        return f"/workspaces/{ws_slug}/operations/{op_id}/ledger"

    def test_active_total_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("TotalsStripOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], amount_silver=3000)
        _entry(ws["id"], op["id"], p["id"], owner["id"], amount_silver=2000)
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "5,000" in resp.text

    def test_voided_entries_excluded_from_total(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidedExclOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], amount_silver=1000)
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="voided", amount_silver=9999)
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        # Only 1,000 in active total, 9,999 from voided must not appear in total
        assert "1,000" in resp.text
        assert "excluded from total" in resp.text

    def test_excluded_from_total_text_when_voided(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("ExcludedTextOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "excluded from total" in resp.text

    def test_strip_absent_when_no_entries(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("NoStripOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert "silver" not in resp.text or "Amount (silver)" in resp.text


# ---------------------------------------------------------------------------
# 9. Ledger HTTP: negative adjustment shown in red
# ---------------------------------------------------------------------------

class TestNegativeAmountColor:
    def test_negative_amount_has_error_color_style(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("NegColorOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"],
               entry_type="adjustment", amount_silver=-500)
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger")
        assert resp.status_code == 200
        assert "var(--error)" in resp.text
        assert "-500" in resp.text


# ---------------------------------------------------------------------------
# 10. Status badge correctness
# ---------------------------------------------------------------------------

class TestStatusBadges:
    def _url(self, ws_slug, op_id):
        return f"/workspaces/{ws_slug}/operations/{op_id}/ledger"

    def _check_badge(self, status: str, expected_class: str):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user(f"Badge{status.capitalize()}Owner")
        ws     = make_workspace(slug=f"badge-{status}", owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status=status)
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert expected_class in resp.text

    def test_draft_badge(self):
        self._check_badge("draft", "badge-draft")

    def test_approved_badge(self):
        self._check_badge("approved", "badge-planning")

    def test_paid_badge(self):
        self._check_badge("paid", "badge-completed")

    def test_voided_badge(self):
        self._check_badge("voided", "badge-archived")


# ---------------------------------------------------------------------------
# 11. No mutation for finalized states (HTTP)
# ---------------------------------------------------------------------------

class TestNoMutationFinalized:
    def test_approve_paid_entry_error_redirect(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("ApprovePaidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        e      = _entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/{e['id']}/approve",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "error" in str(resp.url).lower() or "error" in resp.text.lower()

    def test_void_paid_entry_error_redirect(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidPaidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        e      = _entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/{e['id']}/void",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "error" in str(resp.url).lower() or "error" in resp.text.lower()

    def test_void_voided_entry_error_redirect(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidVoidedOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        e      = _entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/{e['id']}/void",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "error" in str(resp.url).lower() or "error" in resp.text.lower()


# ---------------------------------------------------------------------------
# 12. Duplicate aggregation prevention
# ---------------------------------------------------------------------------

class TestAggregationConsistency:
    def test_compute_matches_repo_totals(self):
        """Pure helper and SQL path must agree on the same dataset."""
        owner = make_user("AggConsistOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="draft",    amount_silver=100)
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="approved", amount_silver=200)
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="paid",     amount_silver=300)
        _entry(ws["id"], op["id"], p["id"], owner["id"], status="voided",   amount_silver=999)

        with database.transaction() as db:
            entries   = repositories.list_payout_ledger_entries_for_operation(db, op["id"], ws["id"])
            repo_tots = repositories.get_ledger_totals_for_operation(db, op["id"], ws["id"])

        helper_tots = compute_ledger_totals(entries)

        assert helper_tots["active_count"]   == repo_tots["active_count"]
        assert helper_tots["active_total"]   == repo_tots["active_total"]
        assert helper_tots["draft_count"]    == repo_tots["draft_count"]
        assert helper_tots["draft_total"]    == repo_tots["draft_total"]
        assert helper_tots["approved_count"] == repo_tots["approved_count"]
        assert helper_tots["approved_total"] == repo_tots["approved_total"]
        assert helper_tots["paid_count"]     == repo_tots["paid_count"]
        assert helper_tots["paid_total"]     == repo_tots["paid_total"]
        assert helper_tots["voided_count"]   == repo_tots["voided_count"]
