"""
Payout Ledger — test suite (Slice 39: Regear / Payout Tracking — Ledger Foundation).

Test groups:
  1.  Schema constraints
      - valid entry_type values accepted
      - invalid entry_type rejected by CHECK
      - valid status values accepted
      - invalid status rejected by CHECK
      - amount_silver < 0 rejected for regear/payout by CHECK
      - amount_silver < 0 accepted for adjustment
      - amount_silver = 0 accepted for all types
      - foreign key: participant_id must exist in workspace
      - workspace scoping column is NOT NULL

  2.  Domain validation (payout_ledger module)
      - validate_entry_type accepts valid values
      - validate_entry_type rejects invalid
      - validate_amount rejects negative for regear
      - validate_amount rejects negative for payout
      - validate_amount accepts negative for adjustment
      - validate_amount accepts zero for all types
      - validate_amount rejects non-integer
      - validate_status_transition happy path
      - validate_status_transition rejects invalid transitions
      - assert_mutable raises for paid/voided
      - assert_mutable passes for draft/approved
      - assert_voidable raises for paid
      - assert_voidable raises for already-voided
      - assert_voidable passes for draft/approved

  3.  Repository: insert + get
      - insert + get roundtrip
      - get returns None for wrong workspace
      - get returns None for missing entry

  4.  Repository: list_for_operation
      - returns entries for the operation
      - excludes entries from other operations
      - excludes entries from other workspaces
      - stable ordering: created_at ASC, id ASC

  5.  Repository: list_for_participant
      - returns entries for the participant
      - excludes entries for other participants
      - ordered created_at DESC

  6.  Repository: update_draft
      - updates amount and note
      - does not update wrong workspace (rowcount 0)

  7.  Repository: approve
      - transitions draft → approved
      - rowcount 0 for wrong workspace

  8.  Repository: void
      - sets status=voided, voided_at, voided_by_user_id
      - rowcount 0 for wrong workspace

  9.  Use case: create_payout_ledger_entry
      - happy path: creates draft entry
      - officer can create
      - member cannot create (PermissionDenied)
      - participant from other workspace rejected (NotFoundError)
      - operation from other workspace rejected (NotFoundError)
      - invalid entry_type rejected (ValidationError)
      - negative amount for regear rejected (ValidationError)
      - negative amount for adjustment accepted
      - creates operational event

 10.  Use case: update_payout_ledger_entry
      - happy path: updates draft
      - approved entry cannot be updated (ValidationError)
      - paid entry cannot be updated (ValidationError)
      - voided entry cannot be updated (ValidationError)
      - member cannot update (PermissionDenied)
      - wrong workspace returns NotFoundError

 11.  Use case: approve_payout_ledger_entry
      - happy path: draft → approved
      - approved entry cannot be re-approved (ValidationError)
      - paid entry cannot be approved (ValidationError)
      - voided entry cannot be approved (ValidationError)
      - member cannot approve (PermissionDenied)

 12.  Use case: void_payout_ledger_entry
      - happy path: draft → voided
      - approved → voided
      - paid entry cannot be voided (ValidationError)
      - already-voided cannot be re-voided (ValidationError)
      - member cannot void (PermissionDenied)

 13.  No display_name identity logic
      - ledger entry is linked to participant_id, not display_name

 14.  Workspace isolation
      - no cross-workspace reads or writes

 15.  HTTP: GET ledger page
      - officer sees the page
      - member gets 403
      - unauthenticated redirected
      - empty state shown
      - entries shown on page
      - voided entries rendered with muted class

 16.  HTTP: POST create
      - creates entry, redirects back
      - invalid form (bad type) → error redirect
      - member gets 403

 17.  HTTP: POST void
      - voids entry, redirects back
      - member gets 403

 18.  HTTP: POST approve
      - approves entry, redirects back
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import payout_ledger as ple
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


def _make_participant(ws_id: str, display_name: str = "Blade") -> dict:
    with database.transaction() as db:
        pid = str(uuid.uuid4())
        now = _now()
        db.execute(
            "INSERT INTO participants (id, guild_workspace_id, display_name, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (pid, ws_id, display_name, now, now),
        )
    return {"id": pid, "display_name": display_name, "guild_workspace_id": ws_id}


def _add_member(ws_id: str, user_id: str, role: str = "member") -> None:
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), ws_id, user_id, role, _now()),
        )


def _insert_entry(
    ws_id: str,
    op_id: str,
    participant_id: str,
    creator_id: str,
    *,
    entry_type: str = "regear",
    amount_silver: int = 1000,
    note: str | None = "test",
    status: str = "draft",
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
        "updated_at":         now,
        "voided_at":          None,
        "voided_by_user_id":  None,
    }
    with database.transaction() as db:
        repositories.insert_payout_ledger_entry(db, record)
    return record


# ---------------------------------------------------------------------------
# 1. Schema constraints
# ---------------------------------------------------------------------------

class TestSchemaConstraints:
    def _setup(self):
        owner = make_user("SchemaOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        return owner, ws, op, p

    def _raw(self, ws_id, op_id, pid, uid, **kwargs):
        base = {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": ws_id,
            "guild_operation_id": op_id,
            "participant_id":     pid,
            "entry_type":         "regear",
            "amount_silver":      500,
            "note":               None,
            "status":             "draft",
            "created_by_user_id": uid,
            "created_at":         _now(),
            "updated_at":         _now(),
            "voided_at":          None,
            "voided_by_user_id":  None,
        }
        return {**base, **kwargs}

    def test_valid_entry_type_regear(self):
        owner, ws, op, p = self._setup()
        with database.transaction() as db:
            repositories.insert_payout_ledger_entry(
                db, self._raw(ws["id"], op["id"], p["id"], owner["id"], entry_type="regear")
            )

    def test_valid_entry_type_payout(self):
        owner, ws, op, p = self._setup()
        with database.transaction() as db:
            repositories.insert_payout_ledger_entry(
                db, self._raw(ws["id"], op["id"], p["id"], owner["id"], entry_type="payout")
            )

    def test_valid_entry_type_adjustment(self):
        owner, ws, op, p = self._setup()
        with database.transaction() as db:
            repositories.insert_payout_ledger_entry(
                db, self._raw(ws["id"], op["id"], p["id"], owner["id"], entry_type="adjustment")
            )

    def test_invalid_entry_type_rejected(self):
        owner, ws, op, p = self._setup()
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                repositories.insert_payout_ledger_entry(
                    db, self._raw(ws["id"], op["id"], p["id"], owner["id"], entry_type="bonus")
                )

    def test_valid_statuses(self):
        for i, status in enumerate(("draft", "approved", "paid", "voided")):
            owner = make_user(f"StatusOwner{i}")
            ws    = make_workspace(slug=f"valid-status-{i}", owner_user_id=owner["id"])
            op    = make_operation(ws["id"])
            p     = _make_participant(ws["id"])
            with database.transaction() as db:
                repositories.insert_payout_ledger_entry(
                    db, self._raw(ws["id"], op["id"], p["id"], owner["id"], status=status)
                )

    def test_invalid_status_rejected(self):
        owner, ws, op, p = self._setup()
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                repositories.insert_payout_ledger_entry(
                    db, self._raw(ws["id"], op["id"], p["id"], owner["id"], status="pending")
                )

    def test_negative_amount_rejected_for_regear(self):
        owner, ws, op, p = self._setup()
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                repositories.insert_payout_ledger_entry(
                    db, self._raw(ws["id"], op["id"], p["id"], owner["id"],
                                  entry_type="regear", amount_silver=-100)
                )

    def test_negative_amount_rejected_for_payout(self):
        owner, ws, op, p = self._setup()
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                repositories.insert_payout_ledger_entry(
                    db, self._raw(ws["id"], op["id"], p["id"], owner["id"],
                                  entry_type="payout", amount_silver=-1)
                )

    def test_negative_amount_accepted_for_adjustment(self):
        owner, ws, op, p = self._setup()
        with database.transaction() as db:
            repositories.insert_payout_ledger_entry(
                db, self._raw(ws["id"], op["id"], p["id"], owner["id"],
                              entry_type="adjustment", amount_silver=-500)
            )

    def test_zero_amount_accepted_for_all_types(self):
        for i, et in enumerate(("regear", "payout", "adjustment")):
            owner = make_user(f"ZeroAmtOwner{i}")
            ws    = make_workspace(slug=f"zero-amt-{i}", owner_user_id=owner["id"])
            op    = make_operation(ws["id"])
            p     = _make_participant(ws["id"])
            with database.transaction() as db:
                repositories.insert_payout_ledger_entry(
                    db, self._raw(ws["id"], op["id"], p["id"], owner["id"],
                                  entry_type=et, amount_silver=0)
                )


# ---------------------------------------------------------------------------
# 2. Domain validation
# ---------------------------------------------------------------------------

class TestDomainValidation:
    def test_validate_entry_type_valid(self):
        for t in ("regear", "payout", "adjustment"):
            ple.validate_entry_type(t)  # no exception

    def test_validate_entry_type_invalid(self):
        with pytest.raises(ValidationError):
            ple.validate_entry_type("bonus")

    def test_validate_amount_negative_regear(self):
        with pytest.raises(ValidationError):
            ple.validate_amount("regear", -1)

    def test_validate_amount_negative_payout(self):
        with pytest.raises(ValidationError):
            ple.validate_amount("payout", -1)

    def test_validate_amount_negative_adjustment_ok(self):
        ple.validate_amount("adjustment", -999)  # no exception

    def test_validate_amount_zero_all_types(self):
        for t in ("regear", "payout", "adjustment"):
            ple.validate_amount(t, 0)  # no exception

    def test_validate_amount_non_integer(self):
        with pytest.raises(ValidationError):
            ple.validate_amount("regear", 1.5)

    def test_status_transition_draft_to_approved(self):
        ple.validate_status_transition("draft", "approved")

    def test_status_transition_draft_to_voided(self):
        ple.validate_status_transition("draft", "voided")

    def test_status_transition_approved_to_paid(self):
        ple.validate_status_transition("approved", "paid")

    def test_status_transition_approved_to_voided(self):
        ple.validate_status_transition("approved", "voided")

    def test_status_transition_invalid_draft_to_paid(self):
        with pytest.raises(ValidationError):
            ple.validate_status_transition("draft", "paid")

    def test_status_transition_paid_terminal(self):
        with pytest.raises(ValidationError):
            ple.validate_status_transition("paid", "approved")

    def test_status_transition_voided_terminal(self):
        with pytest.raises(ValidationError):
            ple.validate_status_transition("voided", "draft")

    def test_assert_mutable_raises_for_paid(self):
        with pytest.raises(ValidationError):
            ple.assert_mutable({"status": "paid"})

    def test_assert_mutable_raises_for_voided(self):
        with pytest.raises(ValidationError):
            ple.assert_mutable({"status": "voided"})

    def test_assert_mutable_passes_for_draft(self):
        ple.assert_mutable({"status": "draft"})  # no exception

    def test_assert_mutable_passes_for_approved(self):
        ple.assert_mutable({"status": "approved"})  # no exception

    def test_assert_voidable_raises_for_paid(self):
        with pytest.raises(ValidationError):
            ple.assert_voidable({"status": "paid"})

    def test_assert_voidable_raises_for_already_voided(self):
        with pytest.raises(ValidationError):
            ple.assert_voidable({"status": "voided"})

    def test_assert_voidable_passes_for_draft(self):
        ple.assert_voidable({"status": "draft"})  # no exception

    def test_assert_voidable_passes_for_approved(self):
        ple.assert_voidable({"status": "approved"})  # no exception


# ---------------------------------------------------------------------------
# 3. Repository: insert + get
# ---------------------------------------------------------------------------

class TestRepoInsertGet:
    def test_insert_get_roundtrip(self):
        owner = make_user("RepoOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row is not None
        assert row["id"] == entry["id"]
        assert row["entry_type"] == "regear"
        assert row["amount_silver"] == 1000
        assert row["status"] == "draft"

    def test_get_returns_none_for_wrong_workspace(self):
        owner1 = make_user("WsIsoOwner1")
        owner2 = make_user("WsIsoOwner2")
        ws1    = make_workspace(slug="ws-iso1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="ws-iso2", owner_user_id=owner2["id"])
        op     = make_operation(ws1["id"])
        p      = _make_participant(ws1["id"])
        entry  = _insert_entry(ws1["id"], op["id"], p["id"], owner1["id"])
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws2["id"])
        assert row is None

    def test_get_returns_none_for_missing(self):
        owner = make_user("GetMissingOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, "nonexistent", ws["id"])
        assert row is None


# ---------------------------------------------------------------------------
# 4. Repository: list_for_operation
# ---------------------------------------------------------------------------

class TestRepoListForOperation:
    def test_returns_entries_for_operation(self):
        owner = make_user("ListOpOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], entry_type="payout")
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_operation(db, op["id"], ws["id"])
        assert len(rows) == 2

    def test_excludes_other_operations(self):
        owner = make_user("ExclOpOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op1   = make_operation(ws["id"], title="Op1")
        op2   = make_operation(ws["id"], title="Op2")
        p     = _make_participant(ws["id"])
        _insert_entry(ws["id"], op1["id"], p["id"], owner["id"])
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_operation(db, op2["id"], ws["id"])
        assert rows == []

    def test_excludes_other_workspaces(self):
        owner1 = make_user("ExclWsOwner1")
        owner2 = make_user("ExclWsOwner2")
        ws1    = make_workspace(slug="exclws1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="exclws2", owner_user_id=owner2["id"])
        op1    = make_operation(ws1["id"])
        p1     = _make_participant(ws1["id"])
        _insert_entry(ws1["id"], op1["id"], p1["id"], owner1["id"])
        op2    = make_operation(ws2["id"])
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_operation(db, op2["id"], ws2["id"])
        assert rows == []

    def test_stable_ordering_created_at_asc(self):
        owner = make_user("OrderListOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        ids = []
        for i in range(3):
            e = _insert_entry(ws["id"], op["id"], p["id"], owner["id"],
                              note=f"entry {i}")
            ids.append(e["id"])
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_operation(db, op["id"], ws["id"])
        assert [r["id"] for r in rows] == ids


# ---------------------------------------------------------------------------
# 5. Repository: list_for_participant
# ---------------------------------------------------------------------------

class TestRepoListForParticipant:
    def test_returns_entries_for_participant(self):
        owner = make_user("ListPartOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], entry_type="payout")
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_participant(db, p["id"], ws["id"])
        assert len(rows) == 2

    def test_excludes_other_participant(self):
        owner = make_user("ExclPartOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p1    = _make_participant(ws["id"], "PlayerA")
        p2    = _make_participant(ws["id"], "PlayerB")
        _insert_entry(ws["id"], op["id"], p1["id"], owner["id"])
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_participant(db, p2["id"], ws["id"])
        assert rows == []

    def test_ordered_newest_first(self):
        owner = make_user("PartOrderOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        ids = []
        for i in range(3):
            e = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], note=f"n{i}")
            ids.append(e["id"])
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_participant(db, p["id"], ws["id"])
        assert [r["id"] for r in rows] == list(reversed(ids))


# ---------------------------------------------------------------------------
# 6. Repository: update_draft
# ---------------------------------------------------------------------------

class TestRepoUpdateDraft:
    def test_updates_amount_and_note(self):
        owner = make_user("UpdateOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        with database.transaction() as db:
            rc = repositories.update_payout_ledger_entry_draft(
                db, entry["id"], ws["id"], 2000, "updated note", _now()
            )
        assert rc == 1
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["amount_silver"] == 2000
        assert row["note"] == "updated note"

    def test_wrong_workspace_rowcount_zero(self):
        owner1 = make_user("UpdWsOwner1")
        owner2 = make_user("UpdWsOwner2")
        ws1    = make_workspace(slug="updws1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="updws2", owner_user_id=owner2["id"])
        op     = make_operation(ws1["id"])
        p      = _make_participant(ws1["id"])
        entry  = _insert_entry(ws1["id"], op["id"], p["id"], owner1["id"])
        with database.transaction() as db:
            rc = repositories.update_payout_ledger_entry_draft(
                db, entry["id"], ws2["id"], 9999, "evil", _now()
            )
        assert rc == 0


# ---------------------------------------------------------------------------
# 7. Repository: approve
# ---------------------------------------------------------------------------

class TestRepoApprove:
    def test_approve_transitions_status(self):
        owner = make_user("ApproveOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        with database.transaction() as db:
            rc = repositories.approve_payout_ledger_entry(db, entry["id"], ws["id"], _now())
        assert rc == 1
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "approved"

    def test_approve_wrong_workspace_rowcount_zero(self):
        owner1 = make_user("AppWsOwner1")
        owner2 = make_user("AppWsOwner2")
        ws1    = make_workspace(slug="appws1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="appws2", owner_user_id=owner2["id"])
        op     = make_operation(ws1["id"])
        p      = _make_participant(ws1["id"])
        entry  = _insert_entry(ws1["id"], op["id"], p["id"], owner1["id"])
        with database.transaction() as db:
            rc = repositories.approve_payout_ledger_entry(db, entry["id"], ws2["id"], _now())
        assert rc == 0


# ---------------------------------------------------------------------------
# 8. Repository: void
# ---------------------------------------------------------------------------

class TestRepoVoid:
    def test_void_sets_status_and_metadata(self):
        owner = make_user("VoidRepoOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        voided_at = _now()
        with database.transaction() as db:
            rc = repositories.void_payout_ledger_entry(
                db, entry["id"], ws["id"], voided_at, owner["id"]
            )
        assert rc == 1
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "voided"
        assert row["voided_by_user_id"] == owner["id"]
        assert row["voided_at"] is not None

    def test_void_wrong_workspace_rowcount_zero(self):
        owner1 = make_user("VoidWsOwner1")
        owner2 = make_user("VoidWsOwner2")
        ws1    = make_workspace(slug="voidws1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="voidws2", owner_user_id=owner2["id"])
        op     = make_operation(ws1["id"])
        p      = _make_participant(ws1["id"])
        entry  = _insert_entry(ws1["id"], op["id"], p["id"], owner1["id"])
        with database.transaction() as db:
            rc = repositories.void_payout_ledger_entry(
                db, entry["id"], ws2["id"], _now(), owner2["id"]
            )
        assert rc == 0


# ---------------------------------------------------------------------------
# 9. Use case: create_payout_ledger_entry
# ---------------------------------------------------------------------------

class TestUseCaseCreate:
    def test_happy_path_creates_draft_entry(self):
        owner = make_user("CreateOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=5000,
            note="boots",
            actor_user_id=owner["id"],
        )
        assert entry["status"] == "draft"
        assert entry["amount_silver"] == 5000
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row is not None

    def test_officer_can_create(self):
        owner   = make_user("OfficerCreateOwner")
        officer = make_user("OfficerCreator")
        ws      = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], officer["id"], "officer")
        op = make_operation(ws["id"])
        p  = _make_participant(ws["id"])
        entry = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="payout",
            amount_silver=100,
            note=None,
            actor_user_id=officer["id"],
        )
        assert entry["created_by_user_id"] == officer["id"]

    def test_member_cannot_create(self):
        owner  = make_user("MemberCreateOwner")
        member = make_user("MemberCreator")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op = make_operation(ws["id"])
        p  = _make_participant(ws["id"])
        with pytest.raises(PermissionDenied):
            use_cases.create_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                guild_operation_id=op["id"],
                participant_id=p["id"],
                entry_type="regear",
                amount_silver=100,
                note=None,
                actor_user_id=member["id"],
            )

    def test_participant_from_other_workspace_rejected(self):
        owner1 = make_user("CrossWsCreate1")
        owner2 = make_user("CrossWsCreate2")
        ws1    = make_workspace(slug="cwsc1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="cwsc2", owner_user_id=owner2["id"])
        op1    = make_operation(ws1["id"])
        p2     = _make_participant(ws2["id"])  # belongs to ws2
        with pytest.raises(NotFoundError):
            use_cases.create_payout_ledger_entry(
                guild_workspace_id=ws1["id"],
                guild_operation_id=op1["id"],
                participant_id=p2["id"],  # wrong workspace
                entry_type="regear",
                amount_silver=100,
                note=None,
                actor_user_id=owner1["id"],
            )

    def test_operation_from_other_workspace_rejected(self):
        owner1 = make_user("CrossWsOp1")
        owner2 = make_user("CrossWsOp2")
        ws1    = make_workspace(slug="cwsop1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="cwsop2", owner_user_id=owner2["id"])
        op2    = make_operation(ws2["id"])  # belongs to ws2
        p1     = _make_participant(ws1["id"])
        with pytest.raises(NotFoundError):
            use_cases.create_payout_ledger_entry(
                guild_workspace_id=ws1["id"],
                guild_operation_id=op2["id"],  # wrong workspace
                participant_id=p1["id"],
                entry_type="regear",
                amount_silver=100,
                note=None,
                actor_user_id=owner1["id"],
            )

    def test_invalid_entry_type_rejected(self):
        owner = make_user("InvalidTypeOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        with pytest.raises(ValidationError):
            use_cases.create_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                guild_operation_id=op["id"],
                participant_id=p["id"],
                entry_type="bonus",
                amount_silver=100,
                note=None,
                actor_user_id=owner["id"],
            )

    def test_negative_amount_for_regear_rejected(self):
        owner = make_user("NegRegearOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        with pytest.raises(ValidationError):
            use_cases.create_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                guild_operation_id=op["id"],
                participant_id=p["id"],
                entry_type="regear",
                amount_silver=-100,
                note=None,
                actor_user_id=owner["id"],
            )

    def test_negative_amount_for_adjustment_accepted(self):
        owner = make_user("NegAdjOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="adjustment",
            amount_silver=-200,
            note="deduction",
            actor_user_id=owner["id"],
        )
        assert entry["amount_silver"] == -200

    def test_creates_operational_event(self):
        owner = make_user("EventCreateOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=1000,
            note=None,
            actor_user_id=owner["id"],
        )
        with database.transaction() as db:
            row = db.execute(
                "SELECT * FROM operational_events WHERE entity_id = ? AND event_type = ?",
                (entry["id"], "payout_ledger.entry.created"),
            ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# 10. Use case: update_payout_ledger_entry
# ---------------------------------------------------------------------------

class TestUseCaseUpdate:
    def test_happy_path_updates_draft(self):
        owner = make_user("UpdateUCOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        use_cases.update_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry["id"],
            amount_silver=9999,
            note="revised",
            actor_user_id=owner["id"],
        )
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["amount_silver"] == 9999
        assert row["note"] == "revised"

    def test_approved_entry_cannot_be_updated(self):
        owner = make_user("ApprUpdOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="approved")
        with pytest.raises(ValidationError):
            use_cases.update_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                amount_silver=999,
                note=None,
                actor_user_id=owner["id"],
            )

    def test_paid_entry_cannot_be_updated(self):
        owner = make_user("PaidUpdOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        with pytest.raises(ValidationError):
            use_cases.update_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                amount_silver=1,
                note=None,
                actor_user_id=owner["id"],
            )

    def test_voided_entry_cannot_be_updated(self):
        owner = make_user("VoidedUpdOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        with pytest.raises(ValidationError):
            use_cases.update_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                amount_silver=1,
                note=None,
                actor_user_id=owner["id"],
            )

    def test_member_cannot_update(self):
        owner  = make_user("MemberUpdOwner")
        member = make_user("MemberUpdMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        with pytest.raises(PermissionDenied):
            use_cases.update_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                amount_silver=1,
                note=None,
                actor_user_id=member["id"],
            )

    def test_wrong_workspace_raises_not_found(self):
        owner1 = make_user("UpdNF1")
        owner2 = make_user("UpdNF2")
        ws1    = make_workspace(slug="updnf1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="updnf2", owner_user_id=owner2["id"])
        op     = make_operation(ws1["id"])
        p      = _make_participant(ws1["id"])
        entry  = _insert_entry(ws1["id"], op["id"], p["id"], owner1["id"])
        with pytest.raises(NotFoundError):
            use_cases.update_payout_ledger_entry(
                guild_workspace_id=ws2["id"],
                entry_id=entry["id"],
                amount_silver=1,
                note=None,
                actor_user_id=owner2["id"],
            )


# ---------------------------------------------------------------------------
# 11. Use case: approve_payout_ledger_entry
# ---------------------------------------------------------------------------

class TestUseCaseApprove:
    def test_happy_path_draft_to_approved(self):
        owner = make_user("ApproveDraftOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        use_cases.approve_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry["id"],
            actor_user_id=owner["id"],
        )
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "approved"

    def test_already_approved_cannot_be_re_approved(self):
        owner = make_user("ReApproveOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="approved")
        with pytest.raises(ValidationError):
            use_cases.approve_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_paid_cannot_be_approved(self):
        owner = make_user("PaidApproveOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        with pytest.raises(ValidationError):
            use_cases.approve_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_voided_cannot_be_approved(self):
        owner = make_user("VoidedApproveOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        with pytest.raises(ValidationError):
            use_cases.approve_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_member_cannot_approve(self):
        owner  = make_user("MemberApprOwner")
        member = make_user("MemberApprMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        with pytest.raises(PermissionDenied):
            use_cases.approve_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=member["id"],
            )


# ---------------------------------------------------------------------------
# 12. Use case: void_payout_ledger_entry
# ---------------------------------------------------------------------------

class TestUseCaseVoid:
    def test_draft_can_be_voided(self):
        owner = make_user("VoidDraftOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        use_cases.void_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry["id"],
            actor_user_id=owner["id"],
        )
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "voided"
        assert row["voided_by_user_id"] == owner["id"]

    def test_approved_can_be_voided(self):
        owner = make_user("VoidApprOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="approved")
        use_cases.void_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry["id"],
            actor_user_id=owner["id"],
        )
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "voided"

    def test_paid_cannot_be_voided(self):
        owner = make_user("PaidVoidOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="paid")
        with pytest.raises(ValidationError):
            use_cases.void_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_already_voided_cannot_be_re_voided(self):
        owner = make_user("ReVoidOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        with pytest.raises(ValidationError):
            use_cases.void_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=owner["id"],
            )

    def test_member_cannot_void(self):
        owner  = make_user("MemberVoidOwner")
        member = make_user("MemberVoider")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        with pytest.raises(PermissionDenied):
            use_cases.void_payout_ledger_entry(
                guild_workspace_id=ws["id"],
                entry_id=entry["id"],
                actor_user_id=member["id"],
            )


# ---------------------------------------------------------------------------
# 13. No display_name identity logic
# ---------------------------------------------------------------------------

class TestNoDisplayNameIdentity:
    def test_entry_linked_to_participant_id_not_display_name(self):
        owner = make_user("NoNameOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"], "Shadowblade")
        entry = use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            participant_id=p["id"],
            entry_type="regear",
            amount_silver=100,
            note=None,
            actor_user_id=owner["id"],
        )
        # The stored row uses participant_id, not display_name
        assert entry["participant_id"] == p["id"]
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert "display_name" not in (row or {})
        assert row["participant_id"] == p["id"]


# ---------------------------------------------------------------------------
# 14. Workspace isolation
# ---------------------------------------------------------------------------

class TestWorkspaceIsolation:
    def test_no_cross_workspace_read(self):
        owner1 = make_user("IsoRead1")
        owner2 = make_user("IsoRead2")
        ws1    = make_workspace(slug="isoread1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="isoread2", owner_user_id=owner2["id"])
        op1    = make_operation(ws1["id"])
        p1     = _make_participant(ws1["id"])
        _insert_entry(ws1["id"], op1["id"], p1["id"], owner1["id"])
        op2    = make_operation(ws2["id"])
        with database.transaction() as db:
            rows = repositories.list_payout_ledger_entries_for_operation(db, op1["id"], ws2["id"])
        assert rows == []

    def test_no_cross_workspace_void(self):
        owner1 = make_user("IsoVoid1")
        owner2 = make_user("IsoVoid2")
        ws1    = make_workspace(slug="isovoid1", owner_user_id=owner1["id"])
        ws2    = make_workspace(slug="isovoid2", owner_user_id=owner2["id"])
        op1    = make_operation(ws1["id"])
        p1     = _make_participant(ws1["id"])
        entry  = _insert_entry(ws1["id"], op1["id"], p1["id"], owner1["id"])
        with pytest.raises(NotFoundError):
            use_cases.void_payout_ledger_entry(
                guild_workspace_id=ws2["id"],
                entry_id=entry["id"],
                actor_user_id=owner2["id"],
            )


# ---------------------------------------------------------------------------
# 15. HTTP: GET ledger page
# ---------------------------------------------------------------------------

_URL_LEDGER = "/workspaces/{slug}/operations/{op_id}/ledger"


class TestHttpGet:
    def test_officer_sees_the_page(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("HttpGetOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_URL_LEDGER.format(slug=ws["slug"], op_id=op["id"]))
        assert resp.status_code == 200
        assert "Ledger" in resp.text

    def test_member_gets_403(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpGet403Owner")
        member = make_user("HttpGet403Member")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op = make_operation(ws["id"])
        _login(client, member["display_name"])
        resp = client.get(_URL_LEDGER.format(slug=ws["slug"], op_id=op["id"]))
        assert resp.status_code == 403

    def test_unauthenticated_redirected(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpGetUnauthOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        resp   = client.get(
            _URL_LEDGER.format(slug=ws["slug"], op_id=op["id"]),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 307)

    def test_empty_state_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpGetEmptyOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp = client.get(_URL_LEDGER.format(slug=ws["slug"], op_id=op["id"]))
        assert resp.status_code == 200
        assert "No ledger entries" in resp.text

    def test_entries_shown_on_page(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpGetListOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"], "SilverKnight")
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"],
                      entry_type="regear", amount_silver=3000, note="bow regear")
        _login(client, owner["display_name"])
        resp = client.get(_URL_LEDGER.format(slug=ws["slug"], op_id=op["id"]))
        assert resp.status_code == 200
        assert "SilverKnight" in resp.text
        assert "regear" in resp.text
        assert "3,000" in resp.text
        assert "bow regear" in resp.text

    def test_voided_entries_rendered_with_muted_class(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpGetVoidedOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _insert_entry(ws["id"], op["id"], p["id"], owner["id"], status="voided")
        _login(client, owner["display_name"])
        resp = client.get(_URL_LEDGER.format(slug=ws["slug"], op_id=op["id"]))
        assert resp.status_code == 200
        assert "row-muted" in resp.text

    def test_ledger_tab_shown_for_officer(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("LedgerTabOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        _login(client, owner["display_name"])
        resp   = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
        assert resp.status_code == 200
        assert "Ledger" in resp.text


# ---------------------------------------------------------------------------
# 16. HTTP: POST create
# ---------------------------------------------------------------------------

class TestHttpCreate:
    def test_create_entry_redirects_back(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpCreateOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/create",
            data={
                "participant_id": p["id"],
                "entry_type":     "regear",
                "amount_silver":  "2500",
                "note":           "sword regear",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "ledger" in resp.headers["location"]

    def test_invalid_amount_error_redirect(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpBadAmtOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/create",
            data={
                "participant_id": p["id"],
                "entry_type":     "regear",
                "amount_silver":  "notanumber",
                "note":           "",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "error" in str(resp.url) or "Amount" in resp.text or "error" in resp.text.lower()

    def test_member_post_create_forbidden(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpCreateForbOwner")
        member = make_user("HttpCreateForbMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op = make_operation(ws["id"])
        p  = _make_participant(ws["id"])
        _login(client, member["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/create",
            data={
                "participant_id": p["id"],
                "entry_type":     "regear",
                "amount_silver":  "100",
                "note":           "",
            },
            follow_redirects=True,
        )
        # Should end up with error (either 403 or error redirect)
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            assert "error" in str(resp.url) or "permission" in resp.text.lower() or "officer" in resp.text.lower()


# ---------------------------------------------------------------------------
# 17. HTTP: POST void
# ---------------------------------------------------------------------------

class TestHttpVoid:
    def test_void_entry_redirects_back(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpVoidOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/{entry['id']}/void",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "voided"

    def test_member_void_forbidden(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpVoidForbOwner")
        member = make_user("HttpVoidForbMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        _add_member(ws["id"], member["id"], "member")
        op    = make_operation(ws["id"])
        p     = _make_participant(ws["id"])
        entry = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, member["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/{entry['id']}/void",
            follow_redirects=True,
        )
        assert resp.status_code in (200, 403)
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "draft"


# ---------------------------------------------------------------------------
# 18. HTTP: POST approve
# ---------------------------------------------------------------------------

class TestHttpApprove:
    def test_approve_entry_redirects_back(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("HttpApprOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        op     = make_operation(ws["id"])
        p      = _make_participant(ws["id"])
        entry  = _insert_entry(ws["id"], op["id"], p["id"], owner["id"])
        _login(client, owner["display_name"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/ledger/{entry['id']}/approve",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            row = repositories.get_payout_ledger_entry(db, entry["id"], ws["id"])
        assert row["status"] == "approved"
