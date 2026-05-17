"""
Payout Ledger Export v1 — test suite (Slice 41).

Test groups:
  1.  Permission enforcement
      - unauthenticated → redirect to login
      - member (non-officer) → 403
      - officer → 200
      - owner → 200

  2.  Response headers
      - Content-Type: text/csv
      - Content-Disposition: attachment; filename=...
      - Filename contains operation id prefix

  3.  Empty export
      - 200 returned with header row only
      - Correct column headers present

  4.  Populated export
      - all stable columns present
      - entry values correct
      - created_by resolved to display_name
      - note field included

  5.  Signed adjustment amounts
      - negative adjustment amount exported as-is (no coercion)

  6.  Voided entry
      - voided entry included in export
      - status = 'voided'
      - voided_at present
      - voided_by resolved to display_name

  7.  Workspace isolation
      - entries from another workspace not in export

  8.  Deterministic ordering
      - rows ordered created_at ASC, id ASC

  9.  CSV escaping
      - note with comma correctly quoted
      - note with newline correctly quoted
      - note with double-quote correctly escaped

 10.  Export CSV link on ledger page
      - link present in ledger page HTML
      - link points to correct URL
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
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
        now = _now()
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), ws_id, user_id, role, now),
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


def _insert_entry(
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
    created_at: str | None = None,
) -> dict:
    entry_id = str(uuid.uuid4())
    now = created_at or _now()
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
        "updated_at":         now,
        "voided_at":          voided_at,
        "voided_by_user_id":  voided_by,
    }
    with database.transaction() as db:
        repositories.insert_payout_ledger_entry(db, record)
    return record


def _export_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/ledger/export.csv"


def _parse_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


# ---------------------------------------------------------------------------
# 1. Permission enforcement
# ---------------------------------------------------------------------------

class TestExportPermissions:
    def test_unauthenticated_redirects_to_login(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("PermUnauthOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        resp  = client.get(_export_url(ws["slug"], op["id"]), follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "login" in resp.headers["location"].lower()

    def test_member_gets_403(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PermMemberOwner")
        member = make_user("PermMemberUser")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _make_member(ws["id"], member["id"], role="member")
        _login(client, member["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert resp.status_code == 403

    def test_officer_gets_200(self):
        client  = TestClient(app, raise_server_exceptions=True)
        owner   = make_user("PermOfficerOwner")
        officer = make_user("PermOfficerUser")
        ws      = make_workspace(owner_user_id=owner["id"])
        op      = make_operation(ws["id"])
        _make_member(ws["id"], officer["id"], role="officer")
        _login(client, officer["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert resp.status_code == 200

    def test_owner_gets_200(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PermOwnerUser")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Response headers
# ---------------------------------------------------------------------------

class TestExportHeaders:
    def test_content_type_is_csv(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HdrCtypeOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_content_disposition_is_attachment(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HdrCdispOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert "attachment" in resp.headers["content-disposition"]

    def test_filename_contains_operation_id_prefix(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HdrFnameOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        disposition = resp.headers["content-disposition"]
        assert op["id"][:8] in disposition
        assert ".csv" in disposition


# ---------------------------------------------------------------------------
# 3. Empty export
# ---------------------------------------------------------------------------

class TestEmptyExport:
    def test_empty_export_returns_200(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("EmptyExportOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        assert resp.status_code == 200

    def test_empty_export_has_header_row_only(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("EmptyHdrOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp  = client.get(_export_url(ws["slug"], op["id"]))
        rows  = _parse_csv(resp.text)
        assert rows == []  # header present but no data rows

    def test_empty_export_has_correct_columns(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("EmptyColOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        first_line = resp.text.splitlines()[0]
        expected = [
            "operation_id", "participant_id", "entry_type", "status",
            "amount_silver", "note", "created_by", "created_at",
            "updated_at", "voided_at", "voided_by",
        ]
        for col in expected:
            assert col in first_line


# ---------------------------------------------------------------------------
# 4. Populated export
# ---------------------------------------------------------------------------

class TestPopulatedExport:
    def test_all_columns_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PopColOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], note="test note")
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        row = rows[0]
        assert "operation_id"  in row
        assert "participant_id" in row
        assert "entry_type"    in row
        assert "status"        in row
        assert "amount_silver" in row
        assert "note"          in row
        assert "created_by"    in row
        assert "created_at"    in row
        assert "updated_at"    in row
        assert "voided_at"     in row
        assert "voided_by"     in row

    def test_entry_values_correct(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PopValsOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        rec    = _insert_entry(
            ws["id"], op["id"], p["id"], owner["id"],
            entry_type="payout", amount_silver=2500, note="boots claim",
        )
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        row = rows[0]
        assert row["entry_type"]    == "payout"
        assert row["amount_silver"] == "2500"
        assert row["note"]          == "boots claim"
        assert row["status"]        == "draft"
        assert row["operation_id"]  == op["id"]
        assert row["participant_id"] == p["id"]

    def test_created_by_resolved_to_display_name(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PopCreatorOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["created_by"] == owner["display_name"]

    def test_note_field_included(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PopNoteOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], note="sword chest drop")
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["note"] == "sword chest drop"

    def test_empty_note_exported_as_empty_string(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PopEmptyNoteOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], note=None)
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["note"] == ""


# ---------------------------------------------------------------------------
# 5. Signed adjustment amounts
# ---------------------------------------------------------------------------

class TestSignedAdjustment:
    def test_negative_adjustment_exported_correctly(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("SignedAdjOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(
            ws["id"], op["id"], p["id"], owner["id"],
            entry_type="adjustment", amount_silver=-750,
        )
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["amount_silver"] == "-750"
        assert rows[0]["entry_type"]    == "adjustment"

    def test_positive_adjustment_exported_correctly(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("PosAdjOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(
            ws["id"], op["id"], p["id"], owner["id"],
            entry_type="adjustment", amount_silver=300,
        )
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["amount_silver"] == "300"


# ---------------------------------------------------------------------------
# 6. Voided entry
# ---------------------------------------------------------------------------

class TestVoidedEntryExport:
    def test_voided_entry_included(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidedExportOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        voided_at = _now()
        _insert_entry(
            ws["id"], op["id"], p["id"], owner["id"],
            status="voided", voided_at=voided_at, voided_by=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        assert rows[0]["status"] == "voided"

    def test_voided_at_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidedAtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        voided_at = "2026-01-15T10:00:00"
        _insert_entry(
            ws["id"], op["id"], p["id"], owner["id"],
            status="voided", voided_at=voided_at, voided_by=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["voided_at"] == voided_at

    def test_voided_by_resolved_to_display_name(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("VoidedByOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(
            ws["id"], op["id"], p["id"], owner["id"],
            status="voided", voided_at=_now(), voided_by=owner["id"],
        )
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert rows[0]["voided_by"] == owner["display_name"]


# ---------------------------------------------------------------------------
# 7. Workspace isolation
# ---------------------------------------------------------------------------

class TestWorkspaceIsolation:
    def test_other_workspace_entries_excluded(self):
        client  = TestClient(app, raise_server_exceptions=True)
        owner   = make_user("WsIsoOwner")
        owner2  = make_user("WsIsoOwner2")
        ws      = make_workspace(owner_user_id=owner["id"])
        ws2     = make_workspace(slug="ws-iso-other", owner_user_id=owner2["id"])
        op      = make_operation(ws["id"])
        op2     = make_operation(ws2["id"])
        p       = _make_participant(ws["id"])
        p2      = _make_participant(ws2["id"])
        _insert_entry(ws["id"],  op["id"],  p["id"],  owner["id"])
        _insert_entry(ws2["id"], op2["id"], p2["id"], owner2["id"])
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        assert rows[0]["operation_id"] == op["id"]


# ---------------------------------------------------------------------------
# 8. Deterministic ordering
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_rows_ordered_by_created_at_asc(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("OrderOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"],
                      amount_silver=300, note="third",
                      created_at="2026-03-01T10:00:00")
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"],
                      amount_silver=100, note="first",
                      created_at="2026-01-01T10:00:00")
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"],
                      amount_silver=200, note="second",
                      created_at="2026-02-01T10:00:00")
        _login(client, owner["display_name"])
        resp  = client.get(_export_url(ws["slug"], op["id"]))
        rows  = _parse_csv(resp.text)
        notes = [r["note"] for r in rows]
        assert notes == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# 9. CSV escaping
# ---------------------------------------------------------------------------

class TestCsvEscaping:
    def _export_rows(self, note: str) -> list[dict]:
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user(f"EscOwner{uuid.uuid4().hex[:6]}")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], note=note)
        _login(client, owner["display_name"])
        resp = client.get(_export_url(ws["slug"], op["id"]))
        return _parse_csv(resp.text)

    def test_note_with_comma_correctly_quoted(self):
        rows = self._export_rows("boots, helm, gloves")
        assert rows[0]["note"] == "boots, helm, gloves"

    def test_note_with_newline_correctly_quoted(self):
        rows = self._export_rows("line one\nline two")
        assert rows[0]["note"] == "line one\nline two"

    def test_note_with_double_quote_correctly_escaped(self):
        rows = self._export_rows('he said "hello"')
        assert rows[0]["note"] == 'he said "hello"'


# ---------------------------------------------------------------------------
# 10. Export CSV link on ledger page
# ---------------------------------------------------------------------------

class TestExportLinkOnLedgerPage:
    def test_export_link_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("LinkOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger")
        assert resp.status_code == 200
        assert "Export CSV" in resp.text

    def test_export_link_points_to_correct_url(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("LinkUrlOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger")
        assert f"/ledger/export.csv" in resp.text
