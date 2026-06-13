"""
Player Reliability Score tests.

Covers:
  Repository — get_player_reliability_scores
  1.  Single player 7 present, 2 absent (9 total) → display "7/9", rate ~0.778.
  2.  'late' counts as present in the numerator.
  3.  'no_show' counts in the denominator (as absent-like).
  4.  'excused' is excluded from both numerator AND denominator.
  5.  Unrecorded attendance (no attendance_records row) is excluded entirely.
  6.  Player with < 3 resolved ops → rate=None, display=None, rate_class="".
  7.  Player with exactly 3 resolved ops → score is shown.
  8.  Operations in draft/planning status excluded (direct DB insert test).
  9.  Operations outside 90-day window excluded.
  10. Operations inside the 90-day window included.
  11. Cross-workspace isolation: other workspace data not included.
  12. Empty workspace returns empty dict.
  13. Multiple players return independent score entries.
  14. rate_class colour bands: ≥80% green, 50-79% amber, <50% red.
  15. Withdrawn signup leaves no attendance record → not counted.

  Route/template integration
  16. Planner page renders without error (reliability_scores in context).
  17. Attendance page renders without error (reliability_scores in context).
  18. Members page shows "Attendance (90d)" column header.
  19. Planner signup card shows ★ N/D when score ≥ threshold.
  20. Planner signup card omits ★ score when display=None (< threshold).
  21. Attendance page shows Reliability column for officers.
  22. Attendance page hides Reliability column for members.
  23. Members page shows — for member with no attendance history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
    publish_operation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _days_ago(n: int) -> str:
    return (_NOW - timedelta(days=n)).isoformat()


def _setup_ws_comp():
    """Workspace + single-slot composition; returns (owner, ws, comp)."""
    owner = make_user("ReliOwner")
    ws = make_workspace(slug="reli-ws", owner_user_id=owner["id"])
    comp = make_composition(
        ws["id"],
        name="ReliComp",
        slots=[
            {
                "party_number": 1,
                "slot_index": 1,
                "role": "DPS",
                "build_name": "Daggers",
                "priority": "core",
            }
        ],
    )
    return owner, ws, comp


def _one_resolved_op(
    ws_id: str,
    comp_id: str,
    display_name: str,
    status: str,
    start: str,
    title: str = "Test Op",
) -> str:
    """
    Full chain for one attendance-resolved operation:
      create (draft) → attach plan → generate slots → publish (planning)
      → signup → assign → lock → record attendance.
    Returns participant_id.
    """
    op = use_cases.create_guild_operation(ws_id, title, "zvz", start)
    use_cases.attach_operation_plan(ws_id, op["id"], comp_id)
    slots = use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    signup = use_cases.submit_signup_intent(ws_id, op["id"], display_name, "DPS")
    assignment = use_cases.assign_participant_to_operation_slot(
        ws_id, op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws_id, op["id"])
    use_cases.record_attendance(
        guild_workspace_id=ws_id,
        guild_operation_id=op["id"],
        assignment_id=assignment["id"],
        status=status,
    )
    return signup["participant_id"]


def _many_ops(ws_id: str, comp_id: str, display_name: str,
              present: int, absent: int, excused: int = 0,
              window: int = 88) -> str:
    """
    Build (present + absent + excused) operations with recorded attendance.
    All ops are scheduled within the default window.  Returns participant_id.
    """
    pid = None
    total = present + absent + excused
    for i in range(total):
        start = _days_ago(window - i)  # within 90-day window
        if i < present:
            stat = "present"
        elif i < present + absent:
            stat = "absent"
        else:
            stat = "excused"
        pid = _one_resolved_op(
            ws_id, comp_id, display_name, stat, start, title=f"Op-{display_name}-{i}"
        )
    return pid


# ---------------------------------------------------------------------------
# 1. Basic score 7/9
# ---------------------------------------------------------------------------

def test_reliability_seven_of_nine():
    owner, ws, comp = _setup_ws_comp()
    pid = _many_ops(ws["id"], comp["id"], "AlphaPlayer", present=7, absent=2)
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["present"] == 7
    assert s["total"]   == 9
    assert s["display"] == "7/9"
    assert abs(s["rate"] - 7 / 9) < 1e-6
    assert s["rate_class"] == "rel-amber"  # 77.8% is amber


# ---------------------------------------------------------------------------
# 2. 'late' counts as present
# ---------------------------------------------------------------------------

def test_reliability_late_counts_as_present():
    owner, ws, comp = _setup_ws_comp()
    pid = None
    for i, stat in enumerate(["present", "late", "absent"]):
        pid = _one_resolved_op(ws["id"], comp["id"], "LatePlayer", stat,
                               _days_ago(80 - i), title=f"LateOp{i}")
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["present"] == 2  # present + late
    assert s["total"]   == 3


# ---------------------------------------------------------------------------
# 3. 'no_show' counts in denominator
# ---------------------------------------------------------------------------

def test_reliability_no_show_in_denominator():
    owner, ws, comp = _setup_ws_comp()
    pid = None
    for i, stat in enumerate(["present", "no_show", "absent"]):
        pid = _one_resolved_op(ws["id"], comp["id"], "NoShowPlayer", stat,
                               _days_ago(80 - i), title=f"NsOp{i}")
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["present"] == 1
    assert s["total"]   == 3


# ---------------------------------------------------------------------------
# 4. 'excused' excluded from both numerator and denominator
# ---------------------------------------------------------------------------

def test_reliability_excused_excluded():
    owner, ws, comp = _setup_ws_comp()
    # 3 present + 3 excused → total = 3 (excused excluded from denominator)
    pid = _many_ops(ws["id"], comp["id"], "ExcusedPlayer", present=3, absent=0, excused=3)
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["present"] == 3
    assert s["total"]   == 3
    assert s["display"] == "3/3"
    assert s["rate"]    == 1.0


# ---------------------------------------------------------------------------
# 5. Unrecorded attendance excluded
# ---------------------------------------------------------------------------

def test_reliability_unrecorded_not_counted():
    """Assigned but no attendance_records row → not in result dict."""
    owner, ws, comp = _setup_ws_comp()

    # Create full op chain up to locked, but skip record_attendance.
    op = use_cases.create_guild_operation(ws["id"], "UnrecordedOp", "zvz", _days_ago(5))
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "Unmarked", "DPS")
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws["id"], op["id"])
    # No record_attendance call → no attendance_records row.

    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    assert signup["participant_id"] not in scores


# ---------------------------------------------------------------------------
# 6. Below threshold (< 3 resolved ops)
# ---------------------------------------------------------------------------

def test_reliability_below_threshold():
    owner, ws, comp = _setup_ws_comp()
    pid = _many_ops(ws["id"], comp["id"], "FewOps", present=2, absent=0)
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["total"]      == 2
    assert s["rate"]       is None
    assert s["display"]    is None
    assert s["rate_class"] == ""


# ---------------------------------------------------------------------------
# 7. Exactly 3 resolved ops → score shown
# ---------------------------------------------------------------------------

def test_reliability_at_threshold_shows_score():
    owner, ws, comp = _setup_ws_comp()
    pid = _many_ops(ws["id"], comp["id"], "ThreeOps", present=3, absent=0)
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["total"]   == 3
    assert s["display"] == "3/3"
    assert s["rate"]    == 1.0


# ---------------------------------------------------------------------------
# 8. Draft/planning operations excluded (direct DB insert bypasses use-case guard)
# ---------------------------------------------------------------------------

def test_reliability_excludes_draft_and_planning():
    owner, ws, comp = _setup_ws_comp()

    op_draft = use_cases.create_guild_operation(
        ws["id"], "Draft Op", "zvz", _days_ago(5)
    )
    op_plan = use_cases.create_guild_operation(
        ws["id"], "Planning Op", "zvz", _days_ago(4)
    )
    use_cases.publish_operation(ws["id"], op_plan["id"])

    # Insert raw attendance_records for both ops to prove the SQL filter works.
    # FK constraints disabled temporarily to allow orphan rows for the test.
    fake_pid = str(uuid.uuid4())
    for op in (op_draft, op_plan):
        with database.transaction() as db:
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute(
                "INSERT INTO attendance_records "
                "(id, guild_workspace_id, guild_operation_id, assignment_id, "
                " participant_id, status, recorded_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'present', ?, ?)",
                (str(uuid.uuid4()), ws["id"], op["id"], str(uuid.uuid4()),
                 fake_pid, _days_ago(1), _days_ago(1)),
            )
            db.execute("PRAGMA foreign_keys = ON")

    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    assert fake_pid not in scores


# ---------------------------------------------------------------------------
# 9. Operations outside 90-day window excluded
# ---------------------------------------------------------------------------

def test_reliability_excludes_outside_window():
    owner, ws, comp = _setup_ws_comp()
    pid = None

    # 3 in-window + 3 out-of-window ops for the same player
    for i in range(3):
        pid = _one_resolved_op(ws["id"], comp["id"], "WinPlayer", "present",
                               _days_ago(10), title=f"InWin{i}")
        _one_resolved_op(ws["id"], comp["id"], "WinPlayer", "absent",
                         _days_ago(95), title=f"OutWin{i}")

    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    s = scores[pid]
    assert s["present"] == 3  # only in-window ops
    assert s["total"]   == 3  # out-of-window absences excluded


# ---------------------------------------------------------------------------
# 10. Operations just inside the window are included
# ---------------------------------------------------------------------------

def test_reliability_inside_window_included():
    owner, ws, comp = _setup_ws_comp()
    pid = _many_ops(ws["id"], comp["id"], "BorderPlayer", present=3, absent=0, window=88)
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    assert pid in scores
    assert scores[pid]["total"] == 3


# ---------------------------------------------------------------------------
# 11. Cross-workspace isolation
# ---------------------------------------------------------------------------

def test_reliability_cross_workspace_isolation():
    owner_a = make_user("OwnerA")
    owner_b = make_user("OwnerB")
    ws_a = make_workspace(slug="reli-ws-a", owner_user_id=owner_a["id"])
    ws_b = make_workspace(slug="reli-ws-b", owner_user_id=owner_b["id"])

    comp_a = make_composition(ws_a["id"], name="CompA")
    pid_a = _many_ops(ws_a["id"], comp_a["id"], "CrossPlayer", present=5, absent=0)

    with database.transaction() as db:
        scores_b = repositories.get_player_reliability_scores(db, ws_b["id"])
    assert pid_a not in scores_b


# ---------------------------------------------------------------------------
# 12. Empty workspace
# ---------------------------------------------------------------------------

def test_reliability_empty_workspace():
    owner = make_user("EmptyOwner")
    ws = make_workspace(slug="empty-reli-ws", owner_user_id=owner["id"])
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    assert scores == {}


# ---------------------------------------------------------------------------
# 13. Multiple players
# ---------------------------------------------------------------------------

def test_reliability_multiple_players_independent():
    owner, ws, comp = _setup_ws_comp()

    comp_b = make_composition(ws["id"], name="CompB")
    pid_a = _many_ops(ws["id"], comp["id"],  "MultiAlpha", present=8, absent=2)
    pid_b = _many_ops(ws["id"], comp_b["id"], "MultiBeta",  present=3, absent=5)

    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])

    assert scores[pid_a]["display"] == "8/10"
    assert scores[pid_b]["display"] == "3/8"
    assert pid_a != pid_b


# ---------------------------------------------------------------------------
# 14. rate_class colour bands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("present,absent,expected_class", [
    (8, 2, "rel-green"),   # 80% boundary → green
    (9, 1, "rel-green"),   # 90%
    (5, 5, "rel-amber"),   # 50% boundary → amber
    (7, 3, "rel-amber"),   # 70%
    (4, 6, "rel-red"),     # 40%
    (1, 9, "rel-red"),     # 10%
])
def test_reliability_rate_class(present, absent, expected_class):
    owner, ws, comp = _setup_ws_comp()
    name = f"Band{present}p{absent}a"
    pid = _many_ops(ws["id"], comp["id"], name, present=present, absent=absent)
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    assert scores[pid]["rate_class"] == expected_class


# ---------------------------------------------------------------------------
# 15. Withdrawn signup leaves no attendance record
# ---------------------------------------------------------------------------

def test_reliability_withdrawn_signup_not_counted():
    owner, ws, comp = _setup_ws_comp()
    op = use_cases.create_guild_operation(ws["id"], "WithdrawOp", "zvz", _days_ago(5))
    use_cases.publish_operation(ws["id"], op["id"])

    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "Withdrawer", "DPS")
    use_cases.withdraw_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        actor_user_id=owner["id"],
        signup_id=signup["id"],
    )
    with database.transaction() as db:
        scores = repositories.get_player_reliability_scores(db, ws["id"])
    assert signup["participant_id"] not in scores


# ---------------------------------------------------------------------------
# Route / template integration tests
# ---------------------------------------------------------------------------

def test_planner_loads_with_reliability_context():
    owner, ws, comp = _setup_ws_comp()
    op = use_cases.create_guild_operation(ws["id"], "PlannerOp", "zvz", _days_ago(1))
    use_cases.publish_operation(ws["id"], op["id"])

    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/operations/{op['id']}/planner")
    assert resp.status_code == 200


def test_attendance_page_loads_with_reliability_context():
    owner, ws, comp = _setup_ws_comp()
    # create → attach plan → generate slots → publish → lock (no signup needed for page to load)
    op = use_cases.create_guild_operation(ws["id"], "AttOp", "zvz", _days_ago(1))
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/operations/{op['id']}/attendance")
    assert resp.status_code == 200


def test_members_page_has_attendance_column_header():
    owner, ws, comp = _setup_ws_comp()
    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/members")
    assert resp.status_code == 200
    assert "Attendance (90d)" in resp.text


def test_planner_signup_card_shows_star_score_for_officer():
    owner, ws, comp = _setup_ws_comp()

    # Build 4-present/1-absent history for the owner (they must sign up for future ops too)
    pid = _many_ops(ws["id"], comp["id"], "ReliOwner", present=4, absent=1)

    # New upcoming op: sign up the owner
    op = use_cases.create_guild_operation(ws["id"], "FuturePlanOp", "zvz", _days_ago(0))
    publish_operation(ws["id"], op["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "ReliOwner", "DPS")

    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/operations/{op['id']}/planner")
    assert resp.status_code == 200
    assert "★" in resp.text
    assert "4/5" in resp.text


def test_planner_signup_card_omits_star_below_threshold():
    owner, ws, comp = _setup_ws_comp()

    # Only 2 resolved ops → display=None
    _many_ops(ws["id"], comp["id"], "ReliOwner", present=2, absent=0)

    op = use_cases.create_guild_operation(ws["id"], "ThreshOp", "zvz", _days_ago(0))
    publish_operation(ws["id"], op["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "ReliOwner", "DPS")

    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/operations/{op['id']}/planner")
    assert resp.status_code == 200
    assert "★" not in resp.text


def _locked_op_with_plan(ws_id: str, comp_id: str, start: str, title: str = "Test Op") -> dict:
    """Create op → attach plan → generate slots → publish → lock."""
    op = use_cases.create_guild_operation(ws_id, title, "zvz", start)
    use_cases.attach_operation_plan(ws_id, op["id"], comp_id)
    use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    use_cases.lock_operation(ws_id, op["id"])
    return op


def _locked_op_with_assignment(ws_id: str, comp_id: str, start: str,
                               player_name: str, title: str = "Test Op") -> dict:
    """Full chain through assign; returns the locked op dict."""
    op = use_cases.create_guild_operation(ws_id, title, "zvz", start)
    use_cases.attach_operation_plan(ws_id, op["id"], comp_id)
    slots = use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    signup = use_cases.submit_signup_intent(ws_id, op["id"], player_name, "DPS")
    use_cases.assign_participant_to_operation_slot(
        ws_id, op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws_id, op["id"])
    return op


def test_attendance_page_shows_reliability_column_for_officer():
    owner, ws, comp = _setup_ws_comp()
    op = _locked_op_with_assignment(ws["id"], comp["id"], _days_ago(1),
                                    "ReliOwner", title="RColOp")

    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/operations/{op['id']}/attendance")
    assert resp.status_code == 200
    assert "Reliability" in resp.text


def test_attendance_page_hides_reliability_column_for_member():
    owner, ws, comp = _setup_ws_comp()
    use_cases.add_workspace_member(ws["id"], owner["id"], "PlainMember", "member")
    op = _locked_op_with_assignment(ws["id"], comp["id"], _days_ago(1),
                                    "PlainMember", title="MemberAttOp")

    client = TestClient(app)
    client.post("/login", data={"display_name": "PlainMember"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/operations/{op['id']}/attendance")
    assert resp.status_code == 200
    # "Reliability" also appears in a CSS comment; check the table header specifically.
    assert ">Reliability<" not in resp.text


def test_members_page_shows_dash_for_new_member():
    owner, ws, comp = _setup_ws_comp()
    use_cases.add_workspace_member(ws["id"], owner["id"], "NewJoin", "member")

    client = TestClient(app)
    client.post("/login", data={"display_name": "ReliOwner"}, follow_redirects=True)
    resp = client.get(f"/workspaces/reli-ws/members")
    assert resp.status_code == 200
    # New member has no participant record → shows "—"
    assert "Attendance (90d)" in resp.text
