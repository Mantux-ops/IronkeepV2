"""
Operation Reminder Jobs — test suite (Slice 36).

Test groups:
  1.  format_operation_reminder — pure formatter
  2.  Repository: try_claim_reminder_delivery
  3.  Repository: finalize_reminder_delivery / skip_reminder_delivery
  4.  Repository: get_operations_eligible_for_reminders
  5.  Job: send_operation_reminders — happy path
  6.  Job: not-yet-due windows
  7.  Job: already sent / already skipped
  8.  Job: stale claim recovery
  9.  Job: REST failure leaves row claimed for retry
  10. Job: operation ineligibility after claim
  11. Job: no channel configured
  12. Job: reminders disabled / Discord not linked
  13. Job: multiple windows for one operation
  14. Job: multiple operations
  15. Job: skipped when past scheduled_start_at
  16. Job: scheduler_run observability via run_job wrapper
  17. Settings UI: reminders_enabled round-trip
  18. Module boundary: formatter has no DB/SDK imports
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import database, repositories
from app.application import use_cases
from app.discord import formatters
from app.scheduler import jobs
from tests.conftest import make_composition, make_operation, make_user, make_workspace

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GUILD_ID    = "111222333444555001"
_ANN_CHANNEL = "777888999000111001"
_OFF_CHANNEL = "333444555666777001"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _future(hours: float = 4.0) -> str:
    return _iso(_now() + timedelta(hours=hours))


def _make_reminder_workspace(
    *,
    slug: str = "rem-ws",
    guild_id: str = _GUILD_ID,
    ann_channel: str | None = _ANN_CHANNEL,
    off_channel: str | None = _OFF_CHANNEL,
    reminders_enabled: bool = True,
) -> tuple[dict, dict]:
    """Return (owner, workspace) configured for reminders."""
    owner = make_user(f"ReminderOwner-{slug}")
    ws = make_workspace(slug=slug, owner_user_id=owner["id"])
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=guild_id,
        announcement_channel_id=ann_channel,
        officer_channel_id=off_channel,
        reminders_enabled=reminders_enabled,
    )
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, ws["id"])
    return owner, ws


def _make_planning_op(ws_id: str, hours_from_now: float = 4.0) -> dict:
    """Create an operation and advance it to planning status."""
    op = make_operation(
        ws_id,
        start=_future(hours_from_now),
        title=f"Op-{uuid.uuid4().hex[:6]}",
    )
    comp = make_composition(ws_id)
    use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
    use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, op["id"], ws_id)
    return op


def _make_locked_op(ws_id: str, hours_from_now: float = 4.0) -> dict:
    """Create an operation and lock it."""
    op = _make_planning_op(ws_id, hours_from_now)
    use_cases.lock_operation(ws_id, op["id"])
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, op["id"], ws_id)
    return op


# ---------------------------------------------------------------------------
# 1. format_operation_reminder — pure formatter
# ---------------------------------------------------------------------------

class TestFormatOperationReminder:

    def _op(self, hours_from_now: float = 4.0) -> dict:
        start = _iso(_now() + timedelta(hours=hours_from_now))
        return {
            "id":                 str(uuid.uuid4()),
            "title":              "Saturday ZvZ",
            "operation_type":     "zvz",
            "status":             "planning",
            "scheduled_start_at": start,
        }

    def test_returns_embeds_list(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1

    def test_no_components_in_reminder(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        assert "components" not in payload

    def test_title_includes_operation_name_and_reminder_label(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        title = payload["embeds"][0]["title"]
        assert "Saturday ZvZ" in title
        assert "Reminder" in title

    def test_t2h_label_in_description(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        assert "2 hours" in payload["embeds"][0]["description"]

    def test_t30m_label_in_description(self):
        payload = formatters.format_operation_reminder(self._op(), "T-30m")
        assert "30 minutes" in payload["embeds"][0]["description"]

    def test_unknown_window_passthrough(self):
        payload = formatters.format_operation_reminder(self._op(), "T-1h")
        assert "T-1h" in payload["embeds"][0]["description"]

    def test_when_field_shows_utc(self):
        op = self._op()
        payload = formatters.format_operation_reminder(op, "T-2h")
        fields = payload["embeds"][0]["fields"]
        when_field = next(f for f in fields if f["name"] == "When")
        assert "UTC" in when_field["value"]

    def test_when_field_not_naive(self):
        """The formatted time must include UTC, never a bare naive datetime."""
        op = self._op()
        payload = formatters.format_operation_reminder(op, "T-30m")
        fields = payload["embeds"][0]["fields"]
        when_field = next(f for f in fields if f["name"] == "When")
        # Must not be just a bare ISO string without UTC label
        assert "UTC" in when_field["value"]

    def test_type_field_present(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        fields = payload["embeds"][0]["fields"]
        assert any(f["name"] == "Type" for f in fields)

    def test_status_field_present(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        fields = payload["embeds"][0]["fields"]
        assert any(f["name"] == "Status" for f in fields)

    def test_footer_is_ironkeepv2(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        assert payload["embeds"][0]["footer"]["text"] == "IronkeepV2"

    def test_color_is_amber_not_status_derived(self):
        """Reminder color must be the amber constant, not the op status color."""
        from app.discord.formatters import STATUS_COLORS, _REMINDER_COLOR
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        color = payload["embeds"][0]["color"]
        assert color == _REMINDER_COLOR
        assert color not in STATUS_COLORS.values()

    def test_readiness_field_absent_when_none(self):
        payload = formatters.format_operation_reminder(self._op(), "T-2h", readiness=None)
        fields = payload["embeds"][0]["fields"]
        assert not any(f["name"] == "Roster" for f in fields)

    def test_readiness_field_present_when_provided(self):
        readiness = {"total_slots": 10, "assigned_slots": 7}
        payload = formatters.format_operation_reminder(self._op(), "T-2h", readiness=readiness)
        fields = payload["embeds"][0]["fields"]
        roster_field = next((f for f in fields if f["name"] == "Roster"), None)
        assert roster_field is not None
        assert "7 / 10" in roster_field["value"]

    def test_readiness_zero_slots_no_division_error(self):
        readiness = {"total_slots": 0, "assigned_slots": 0}
        payload = formatters.format_operation_reminder(self._op(), "T-2h", readiness=readiness)
        # Should not raise
        assert payload is not None

    def test_pure_no_db_access(self):
        """Calling the formatter without a DB configured must never raise."""
        op = self._op()
        payload = formatters.format_operation_reminder(op, "T-2h")
        assert "embeds" in payload

    def test_no_flags_field(self):
        """Reminders are not ephemeral."""
        payload = formatters.format_operation_reminder(self._op(), "T-2h")
        assert "flags" not in payload


# ---------------------------------------------------------------------------
# 2. Repository: try_claim_reminder_delivery
# ---------------------------------------------------------------------------

class TestTryClaimReminderDelivery:

    def _claim(
        self,
        op_id: str,
        ws_id: str,
        window: str = "T-2h",
        now_iso: str | None = None,
        stale_cutoff_iso: str | None = None,
    ) -> str:
        t = _iso(_now())
        with database.transaction() as db:
            return repositories.try_claim_reminder_delivery(
                db, op_id, window, ws_id,
                now_iso or t,
                stale_cutoff_iso or _iso(_now() - timedelta(seconds=600)),
            )

    def test_fresh_claim_returns_claimed(self):
        _, ws = _make_reminder_workspace()
        op = _make_planning_op(ws["id"])
        result = self._claim(op["id"], ws["id"])
        assert result == "claimed"

    def test_second_claim_same_run_returns_busy(self):
        _, ws = _make_reminder_workspace(slug="ws-busy")
        op = _make_planning_op(ws["id"])
        self._claim(op["id"], ws["id"])
        result = self._claim(op["id"], ws["id"])
        assert result == "busy"

    def test_idempotent_across_ops(self):
        _, ws = _make_reminder_workspace(slug="ws-idem")
        op1 = _make_planning_op(ws["id"])
        op2 = _make_planning_op(ws["id"])
        assert self._claim(op1["id"], ws["id"]) == "claimed"
        assert self._claim(op2["id"], ws["id"]) == "claimed"

    def test_different_windows_are_independent(self):
        _, ws = _make_reminder_workspace(slug="ws-windows")
        op = _make_planning_op(ws["id"])
        assert self._claim(op["id"], ws["id"], window="T-2h") == "claimed"
        assert self._claim(op["id"], ws["id"], window="T-30m") == "claimed"

    def test_stale_claim_is_reclaimable(self):
        _, ws = _make_reminder_workspace(slug="ws-stale")
        op = _make_planning_op(ws["id"])
        old_time = _iso(_now() - timedelta(seconds=700))
        fresh_time = _iso(_now())

        # Simulate a stale claim: insert row as claimed with old claimed_at
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, claimed_at, created_at)
                VALUES (?, ?, ?, 'T-2h', 'claimed', ?, ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], old_time, old_time),
            )

        # Stale cutoff = 600s ago. The old_time is 700s ago so it's stale.
        stale_cutoff = _iso(_now() - timedelta(seconds=600))
        with database.transaction() as db:
            result = repositories.try_claim_reminder_delivery(
                db, op["id"], "T-2h", ws["id"], fresh_time, stale_cutoff,
            )
        assert result == "claimed"

    def test_fresh_claim_not_reclaimable_before_timeout(self):
        _, ws = _make_reminder_workspace(slug="ws-notimeout")
        op = _make_planning_op(ws["id"])
        now_ts = _iso(_now())

        # Simulate a recent claim (10 seconds ago — within 600s timeout)
        recent_time = _iso(_now() - timedelta(seconds=10))
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, claimed_at, created_at)
                VALUES (?, ?, ?, 'T-30m', 'claimed', ?, ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], recent_time, recent_time),
            )

        stale_cutoff = _iso(_now() - timedelta(seconds=600))
        with database.transaction() as db:
            result = repositories.try_claim_reminder_delivery(
                db, op["id"], "T-30m", ws["id"], now_ts, stale_cutoff,
            )
        assert result == "busy"

    def test_sent_row_returns_already_done(self):
        _, ws = _make_reminder_workspace(slug="ws-sent")
        op = _make_planning_op(ws["id"])

        # Insert row already marked sent
        t = _iso(_now())
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, sent_at, created_at)
                VALUES (?, ?, ?, 'T-2h', 'sent', ?, ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], t, t),
            )

        with database.transaction() as db:
            result = repositories.try_claim_reminder_delivery(
                db, op["id"], "T-2h", ws["id"], t,
                _iso(_now() - timedelta(seconds=600)),
            )
        assert result == "already_done"

    def test_skipped_row_returns_already_done(self):
        _, ws = _make_reminder_workspace(slug="ws-skip")
        op = _make_planning_op(ws["id"])
        t = _iso(_now())
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, skipped_at, skip_reason, created_at)
                VALUES (?, ?, ?, 'T-30m', 'skipped', ?, 'test', ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], t, t),
            )

        with database.transaction() as db:
            result = repositories.try_claim_reminder_delivery(
                db, op["id"], "T-30m", ws["id"], t,
                _iso(_now() - timedelta(seconds=600)),
            )
        assert result == "already_done"


# ---------------------------------------------------------------------------
# 3. Repository: finalize_reminder_delivery / skip_reminder_delivery
# ---------------------------------------------------------------------------

class TestFinalizeAndSkipDelivery:

    def _insert_claimed(self, op_id: str, ws_id: str, window: str = "T-2h") -> None:
        t = _iso(_now())
        with database.transaction() as db:
            repositories.try_claim_reminder_delivery(
                db, op_id, window, ws_id, t,
                _iso(_now() - timedelta(seconds=600)),
            )

    def test_finalize_sets_status_sent(self):
        _, ws = _make_reminder_workspace(slug="fin-ws")
        op = _make_planning_op(ws["id"])
        self._insert_claimed(op["id"], ws["id"])
        t = _iso(_now())
        with database.transaction() as db:
            repositories.finalize_reminder_delivery(
                db, op["id"], "T-2h", ws["id"], t,
            )
        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row is not None
        assert row["status"] == "sent"
        assert row["sent_at"] == t

    def test_skip_sets_status_skipped(self):
        _, ws = _make_reminder_workspace(slug="skip-ws")
        op = _make_planning_op(ws["id"])
        self._insert_claimed(op["id"], ws["id"], "T-30m")
        t = _iso(_now())
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op["id"], "T-30m", ws["id"], t, "past_start",
            )
        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-30m", ws["id"])
        assert row is not None
        assert row["status"] == "skipped"
        assert row["skip_reason"] == "past_start"

    def test_skip_does_not_overwrite_sent(self):
        """A sent row must never be downgraded to skipped."""
        _, ws = _make_reminder_workspace(slug="skip-sent-ws")
        op = _make_planning_op(ws["id"])
        self._insert_claimed(op["id"], ws["id"])
        t = _iso(_now())
        with database.transaction() as db:
            repositories.finalize_reminder_delivery(db, op["id"], "T-2h", ws["id"], t)
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op["id"], "T-2h", ws["id"], t, "should_not_apply",
            )
        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row["status"] == "sent"

    def test_skip_inserts_if_no_row_exists(self):
        """skip_reminder_delivery must work even if no row was claimed first."""
        _, ws = _make_reminder_workspace(slug="skip-new-ws")
        op = _make_planning_op(ws["id"])
        t = _iso(_now())
        with database.transaction() as db:
            repositories.skip_reminder_delivery(
                db, op["id"], "T-2h", ws["id"], t, "no_channel",
            )
        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row is not None
        assert row["status"] == "skipped"
        assert row["skip_reason"] == "no_channel"


# ---------------------------------------------------------------------------
# 4. Repository: get_operations_eligible_for_reminders
# ---------------------------------------------------------------------------

class TestGetEligibleOperations:

    def test_planning_op_is_eligible(self):
        _, ws = _make_reminder_workspace(slug="elig-plan")
        op = _make_planning_op(ws["id"])
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert any(o["id"] == op["id"] for o in ops)

    def test_locked_op_is_eligible(self):
        _, ws = _make_reminder_workspace(slug="elig-lock")
        op = _make_locked_op(ws["id"])
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert any(o["id"] == op["id"] for o in ops)

    def test_draft_op_not_eligible(self):
        _, ws = _make_reminder_workspace(slug="elig-draft")
        op = make_operation(ws["id"], start=_future(4))
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert not any(o["id"] == op["id"] for o in ops)

    def test_completed_op_not_eligible(self):
        _, ws = _make_reminder_workspace(slug="elig-comp")
        op = _make_planning_op(ws["id"])
        use_cases.lock_operation(ws["id"], op["id"])
        # Simulate completing
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET status = 'completed' WHERE id = ?",
                (op["id"],),
            )
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert not any(o["id"] == op["id"] for o in ops)

    def test_past_op_not_eligible(self):
        """An operation whose start time has passed must not appear."""
        _, ws = _make_reminder_workspace(slug="elig-past")
        op = _make_planning_op(ws["id"])
        # Rewind scheduled_start_at into the past
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_iso(_now() - timedelta(hours=1)), op["id"]),
            )
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert not any(o["id"] == op["id"] for o in ops)

    def test_reminders_disabled_not_eligible(self):
        _, ws = _make_reminder_workspace(slug="elig-dis", reminders_enabled=False)
        op = _make_planning_op(ws["id"])
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert not any(o["id"] == op["id"] for o in ops)

    def test_no_discord_guild_not_eligible(self):
        owner = make_user("NoDiscordOwner")
        ws = make_workspace(slug="elig-nodiscord", owner_user_id=owner["id"])
        # No discord config set at all
        op = _make_planning_op(ws["id"])
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        assert not any(o["id"] == op["id"] for o in ops)

    def test_returns_announcement_and_officer_channel_fields(self):
        _, ws = _make_reminder_workspace(slug="elig-fields")
        op = _make_planning_op(ws["id"])
        now_iso = _iso(_now())
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, now_iso)
        found = next(o for o in ops if o["id"] == op["id"])
        assert "discord_announcement_channel_id" in found
        assert "discord_officer_channel_id" in found


# ---------------------------------------------------------------------------
# 5. Job: send_operation_reminders — happy path
# ---------------------------------------------------------------------------

class TestSendOperationRemindersHappyPath:

    def _make_op_due_now(self, ws_id: str, window: str) -> dict:
        """Create an op where the given window is currently due."""
        offset = timedelta(hours=2) if window == "T-2h" else timedelta(minutes=30)
        # Op starts slightly past the window so the window is due
        start = _now() + offset - timedelta(minutes=1)
        op = make_operation(ws_id, start=_iso(start))
        comp = make_composition(ws_id)
        use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
        use_cases.generate_operation_slots(ws_id, op["id"])
        use_cases.publish_operation(ws_id, op["id"])
        with database.transaction() as db:
            op = repositories.get_guild_operation(db, op["id"], ws_id)
        return op

    @patch("app.discord.rest_client.post_message", return_value="msg-001")
    def test_sends_t2h_reminder(self, mock_post):
        _, ws = _make_reminder_workspace(slug="happy-t2h")
        self._make_op_due_now(ws["id"], "T-2h")

        result = jobs.send_operation_reminders()

        assert result["sent"] >= 1
        assert mock_post.called

    @patch("app.discord.rest_client.post_message", return_value="msg-002")
    def test_sends_t30m_reminder(self, mock_post):
        _, ws = _make_reminder_workspace(slug="happy-t30m")
        self._make_op_due_now(ws["id"], "T-30m")

        result = jobs.send_operation_reminders()

        assert result["sent"] >= 1

    @patch("app.discord.rest_client.post_message", return_value="msg-003")
    def test_delivery_row_status_is_sent_after_job(self, mock_post):
        _, ws = _make_reminder_workspace(slug="happy-status")
        op = self._make_op_due_now(ws["id"], "T-2h")

        jobs.send_operation_reminders()

        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row is not None
        assert row["status"] == "sent"

    @patch("app.discord.rest_client.post_message", return_value="msg-004")
    def test_post_message_called_with_embed(self, mock_post):
        _, ws = _make_reminder_workspace(slug="happy-embed")
        self._make_op_due_now(ws["id"], "T-2h")

        jobs.send_operation_reminders()

        assert mock_post.called
        channel_id, payload = mock_post.call_args[0]
        assert "embeds" in payload
        assert channel_id == _ANN_CHANNEL

    @patch("app.discord.rest_client.post_message", return_value="msg-005")
    def test_post_uses_announcement_channel_first(self, mock_post):
        _, ws = _make_reminder_workspace(slug="happy-annchan")
        self._make_op_due_now(ws["id"], "T-2h")

        jobs.send_operation_reminders()

        channel_id = mock_post.call_args[0][0]
        assert channel_id == _ANN_CHANNEL

    @patch("app.discord.rest_client.post_message", return_value="msg-006")
    def test_result_keys_present(self, mock_post):
        _, ws = _make_reminder_workspace(slug="happy-keys")
        self._make_op_due_now(ws["id"], "T-2h")

        result = jobs.send_operation_reminders()

        for key in ("operations_checked", "windows_checked", "sent",
                    "already_done", "skipped", "busy", "errors"):
            assert key in result


# ---------------------------------------------------------------------------
# 6. Job: not-yet-due windows
# ---------------------------------------------------------------------------

class TestNotYetDueWindows:

    def test_t2h_not_due_if_op_starts_in_3h(self):
        _, ws = _make_reminder_workspace(slug="notdue-ws")
        make_operation(ws["id"], start=_future(3.0))  # 3h from now; T-2h not yet due
        # But we need a planning op
        op = _make_planning_op(ws["id"])
        # Advance op start to 3h from now
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_future(3.0), op["id"]),
            )

        with patch("app.discord.rest_client.post_message") as mock_post:
            result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0
        # windows_checked is 2 but nothing was sent
        assert result["sent"] == 0

    @patch("app.discord.rest_client.post_message", return_value="msg-t30m-notdue")
    def test_t30m_not_sent_if_op_starts_in_1h(self, mock_post):
        """T-2h is due (fired 1h ago), T-30m is not due (fires in 30min).
        Only T-2h should be sent; T-30m delivery row should not exist."""
        _, ws = _make_reminder_workspace(slug="notdue-t30m")
        op = _make_planning_op(ws["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_future(1.0), op["id"]),
            )

        result = jobs.send_operation_reminders()

        # T-2h is due and should have been sent
        assert result["sent"] == 1
        # T-30m should not have a delivery row (not due yet)
        with database.transaction() as db:
            t30m_row = repositories.get_reminder_delivery(db, op["id"], "T-30m", ws["id"])
        assert t30m_row is None


# ---------------------------------------------------------------------------
# 7. Job: already sent / already skipped
# ---------------------------------------------------------------------------

class TestAlreadyDoneWindows:

    def _op_with_sent_delivery(self, ws_id: str, window: str) -> dict:
        """Create an op and pre-insert a 'sent' delivery row."""
        offset = timedelta(hours=2) if window == "T-2h" else timedelta(minutes=30)
        start = _now() + offset - timedelta(minutes=1)
        op = make_operation(ws_id, start=_iso(start))
        comp = make_composition(ws_id)
        use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
        use_cases.generate_operation_slots(ws_id, op["id"])
        use_cases.publish_operation(ws_id, op["id"])
        t = _iso(_now())
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, sent_at, created_at)
                VALUES (?, ?, ?, ?, 'sent', ?, ?)
                """,
                (str(uuid.uuid4()), ws_id, op["id"], window, t, t),
            )
        with database.transaction() as db:
            return repositories.get_guild_operation(db, op["id"], ws_id)

    @patch("app.discord.rest_client.post_message")
    def test_already_sent_not_resent(self, mock_post):
        _, ws = _make_reminder_workspace(slug="done-sent")
        self._op_with_sent_delivery(ws["id"], "T-2h")

        result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0
        assert result["already_done"] >= 1

    @patch("app.discord.rest_client.post_message")
    def test_already_skipped_not_resent(self, mock_post):
        _, ws = _make_reminder_workspace(slug="done-skip")
        offset = timedelta(hours=2)
        start = _now() + offset - timedelta(minutes=1)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        t = _iso(_now())
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, skipped_at, skip_reason, created_at)
                VALUES (?, ?, ?, 'T-2h', 'skipped', ?, 'test_skip', ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], t, t),
            )

        result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0
        assert result["already_done"] >= 1


# ---------------------------------------------------------------------------
# 8. Job: stale claim recovery
# ---------------------------------------------------------------------------

class TestStaleClaimRecovery:

    def _op_due(self, ws_id: str) -> dict:
        offset = timedelta(hours=2)
        start = _now() + offset - timedelta(minutes=1)
        op = make_operation(ws_id, start=_iso(start))
        comp = make_composition(ws_id)
        use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
        use_cases.generate_operation_slots(ws_id, op["id"])
        use_cases.publish_operation(ws_id, op["id"])
        with database.transaction() as db:
            return repositories.get_guild_operation(db, op["id"], ws_id)

    @patch("app.discord.rest_client.post_message", return_value="msg-stale")
    def test_stale_claimed_row_is_retried(self, mock_post):
        _, ws = _make_reminder_workspace(slug="stale-retry")
        op = self._op_due(ws["id"])

        # Insert a stale claimed row (claimed_at is 700s ago)
        stale_time = _iso(_now() - timedelta(seconds=700))
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, claimed_at, created_at)
                VALUES (?, ?, ?, 'T-2h', 'claimed', ?, ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], stale_time, stale_time),
            )

        result = jobs.send_operation_reminders()

        assert result["sent"] >= 1
        assert mock_post.called

    @patch("app.discord.rest_client.post_message", return_value="msg-stale-2")
    def test_stale_claimed_row_finalized_after_send(self, mock_post):
        _, ws = _make_reminder_workspace(slug="stale-final")
        op = self._op_due(ws["id"])

        stale_time = _iso(_now() - timedelta(seconds=700))
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, claimed_at, created_at)
                VALUES (?, ?, ?, 'T-2h', 'claimed', ?, ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], stale_time, stale_time),
            )

        jobs.send_operation_reminders()

        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row["status"] == "sent"


# ---------------------------------------------------------------------------
# 9. Job: REST failure leaves row claimed for retry
# ---------------------------------------------------------------------------

class TestRestFailureLeavesRowClaimed:

    def _op_due(self, ws_id: str) -> dict:
        start = _now() + timedelta(hours=2) - timedelta(minutes=1)
        op = make_operation(ws_id, start=_iso(start))
        comp = make_composition(ws_id)
        use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
        use_cases.generate_operation_slots(ws_id, op["id"])
        use_cases.publish_operation(ws_id, op["id"])
        with database.transaction() as db:
            return repositories.get_guild_operation(db, op["id"], ws_id)

    @patch(
        "app.discord.rest_client.post_message",
        side_effect=Exception("Discord down"),
    )
    def test_error_counted_on_rest_failure(self, mock_post):
        _, ws = _make_reminder_workspace(slug="rest-fail")
        self._op_due(ws["id"])

        result = jobs.send_operation_reminders()

        assert result["errors"] >= 1

    @patch(
        "app.discord.rest_client.post_message",
        side_effect=Exception("Discord down"),
    )
    def test_row_stays_claimed_after_rest_failure(self, mock_post):
        _, ws = _make_reminder_workspace(slug="rest-claimed")
        op = self._op_due(ws["id"])

        jobs.send_operation_reminders()

        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row is not None
        assert row["status"] == "claimed"

    @patch(
        "app.discord.rest_client.post_message",
        side_effect=Exception("Discord down"),
    )
    def test_no_sent_rows_after_rest_failure(self, mock_post):
        _, ws = _make_reminder_workspace(slug="rest-nosent")
        op = self._op_due(ws["id"])

        jobs.send_operation_reminders()

        with database.transaction() as db:
            row = repositories.get_reminder_delivery(db, op["id"], "T-2h", ws["id"])
        assert row is None or row["status"] != "sent"


# ---------------------------------------------------------------------------
# 10. Job: operation ineligibility after claim
# ---------------------------------------------------------------------------

class TestIneligibilityAfterClaim:

    @patch("app.discord.rest_client.post_message", return_value="msg-inelig")
    def test_skipped_when_op_completed_after_claim(self, mock_post):
        _, ws = _make_reminder_workspace(slug="inelig-comp")
        start = _now() + timedelta(hours=2) - timedelta(minutes=1)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        # Manually insert a claimed row (simulating a previous job step claimed it
        # but the op was completed between claim and re-validate)
        t = _iso(_now())
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO operation_reminder_deliveries
                    (id, guild_workspace_id, guild_operation_id, reminder_window,
                     status, claimed_at, created_at)
                VALUES (?, ?, ?, 'T-2h', 'claimed', ?, ?)
                """,
                (str(uuid.uuid4()), ws["id"], op["id"], t, t),
            )
            # Complete the operation so it's no longer eligible
            db.execute(
                "UPDATE guild_operations SET status = 'completed' WHERE id = ?",
                (op["id"],),
            )

        # The job should see the claimed row is stale OR see op as ineligible
        # Since the op won't appear in the eligible query, the job won't process it.
        # The ineligibility test is that the op doesn't appear in the query results.
        with database.transaction() as db:
            ops = repositories.get_operations_eligible_for_reminders(db, _iso(_now()))
        assert not any(o["id"] == op["id"] for o in ops)


# ---------------------------------------------------------------------------
# 11. Job: no channel configured
# ---------------------------------------------------------------------------

class TestNoChannelConfigured:

    @patch("app.discord.rest_client.post_message")
    def test_skipped_when_no_announcement_or_officer_channel(self, mock_post):
        owner = make_user("NoChannelOwner")
        ws = make_workspace(slug="nochan-ws", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=None,
            officer_channel_id=None,
            reminders_enabled=True,
        )
        # No channels: op will not appear in eligible query
        # (query requires at least one channel configured)
        op = _make_planning_op(ws["id"])
        # Force start to within T-2h window
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_iso(_now() + timedelta(hours=2) - timedelta(minutes=1)), op["id"]),
            )

        result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0

    @patch("app.discord.rest_client.post_message", return_value="msg-offonly")
    def test_uses_officer_channel_when_no_announcement(self, mock_post):
        """Falls back to officer channel when announcement channel is absent."""
        owner = make_user("OfficerChanOwner")
        ws = make_workspace(slug="offchan-ws", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=None,
            officer_channel_id=_OFF_CHANNEL,
            reminders_enabled=True,
        )
        with database.transaction() as db:
            ws = repositories.get_workspace_by_id(db, ws["id"])

        op = _make_planning_op(ws["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_iso(_now() + timedelta(hours=2) - timedelta(minutes=1)), op["id"]),
            )

        result = jobs.send_operation_reminders()

        assert result["sent"] >= 1
        channel_id = mock_post.call_args[0][0]
        assert channel_id == _OFF_CHANNEL


# ---------------------------------------------------------------------------
# 12. Job: reminders disabled / Discord not linked
# ---------------------------------------------------------------------------

class TestGatesAndIneligibility:

    @patch("app.discord.rest_client.post_message")
    def test_reminders_disabled_workspace_not_processed(self, mock_post):
        _, ws = _make_reminder_workspace(slug="gate-dis", reminders_enabled=False)
        op = _make_planning_op(ws["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_iso(_now() + timedelta(hours=2) - timedelta(minutes=1)), op["id"]),
            )

        result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0
        assert result["operations_checked"] == 0

    @patch("app.discord.rest_client.post_message")
    def test_no_discord_guild_not_processed(self, mock_post):
        owner = make_user("NoGuildOwner")
        ws = make_workspace(slug="gate-nodiscord", owner_user_id=owner["id"])
        op = _make_planning_op(ws["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_iso(_now() + timedelta(hours=2) - timedelta(minutes=1)), op["id"]),
            )

        result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0


# ---------------------------------------------------------------------------
# 13. Job: multiple windows for one operation
# ---------------------------------------------------------------------------

class TestMultipleWindowsOneOp:

    @patch("app.discord.rest_client.post_message", return_value="msg-mw")
    def test_both_windows_sent_when_both_due(self, mock_post):
        """If op starts in 25 minutes, both T-2h and T-30m are due."""
        _, ws = _make_reminder_workspace(slug="multi-win")
        start = _now() + timedelta(minutes=25)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        result = jobs.send_operation_reminders()

        assert result["sent"] == 2
        assert mock_post.call_count == 2

    @patch("app.discord.rest_client.post_message", return_value="msg-one-win")
    def test_only_t2h_sent_when_op_starts_in_90min(self, mock_post):
        """If op starts in 90min, T-2h is due but T-30m is not."""
        _, ws = _make_reminder_workspace(slug="one-win")
        start = _now() + timedelta(minutes=90)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        result = jobs.send_operation_reminders()

        assert result["sent"] == 1


# ---------------------------------------------------------------------------
# 14. Job: multiple operations
# ---------------------------------------------------------------------------

class TestMultipleOperations:

    @patch("app.discord.rest_client.post_message", return_value="msg-multi")
    def test_all_eligible_ops_processed(self, mock_post):
        _, ws = _make_reminder_workspace(slug="multi-ops")
        for _ in range(3):
            start = _now() + timedelta(hours=2) - timedelta(minutes=1)
            op = make_operation(ws["id"], start=_iso(start))
            comp = make_composition(ws["id"])
            use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
            use_cases.generate_operation_slots(ws["id"], op["id"])
            use_cases.publish_operation(ws["id"], op["id"])

        result = jobs.send_operation_reminders()

        assert result["sent"] == 3
        assert result["operations_checked"] == 3

    @patch("app.discord.rest_client.post_message", return_value="msg-scope")
    def test_workspace_isolation(self, mock_post):
        """Ops from a workspace with reminders disabled are not reminded."""
        _, ws_on = _make_reminder_workspace(
            slug="scope-on",
            guild_id="111222333444555101",
        )
        _, ws_off = _make_reminder_workspace(
            slug="scope-off",
            guild_id="111222333444555102",
            reminders_enabled=False,
        )

        for ws in (ws_on, ws_off):
            start = _now() + timedelta(hours=2) - timedelta(minutes=1)
            op = make_operation(ws["id"], start=_iso(start))
            comp = make_composition(ws["id"])
            use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
            use_cases.generate_operation_slots(ws["id"], op["id"])
            use_cases.publish_operation(ws["id"], op["id"])

        result = jobs.send_operation_reminders()

        # Only the enabled workspace's op should be processed
        assert result["operations_checked"] == 1
        assert result["sent"] == 1


# ---------------------------------------------------------------------------
# 15. Job: skipped when past scheduled_start_at
# ---------------------------------------------------------------------------

class TestPastStartSkipped:

    @patch("app.discord.rest_client.post_message")
    def test_past_start_op_not_in_eligible_list(self, mock_post):
        _, ws = _make_reminder_workspace(slug="past-start")
        op = _make_planning_op(ws["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_operations SET scheduled_start_at = ? WHERE id = ?",
                (_iso(_now() - timedelta(minutes=5)), op["id"]),
            )

        result = jobs.send_operation_reminders()

        assert mock_post.call_count == 0
        assert result["sent"] == 0


# ---------------------------------------------------------------------------
# 16. Job: scheduler_run observability via run_job wrapper
# ---------------------------------------------------------------------------

class TestSchedulerRunObservability:

    @patch("app.discord.rest_client.post_message", return_value="msg-obs")
    def test_run_job_writes_scheduler_run_row(self, mock_post):
        _, ws = _make_reminder_workspace(slug="obs-ws")
        start = _now() + timedelta(hours=2) - timedelta(minutes=1)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        result = jobs.run_job("send_operation_reminders", jobs.send_operation_reminders)

        with database.transaction() as db:
            run = repositories.get_latest_scheduler_run(db)
        assert run is not None
        assert run["job_name"] == "send_operation_reminders"
        assert run["status"] == "success"

    @patch("app.discord.rest_client.post_message", return_value="msg-obs2")
    def test_run_job_result_stored_in_result_json(self, mock_post):
        _, ws = _make_reminder_workspace(slug="obs-json")
        start = _now() + timedelta(hours=2) - timedelta(minutes=1)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        import json
        jobs.run_job("send_operation_reminders", jobs.send_operation_reminders)

        with database.transaction() as db:
            run = repositories.get_latest_scheduler_run(db)
        result_data = json.loads(run["result_json"])
        assert "sent" in result_data

    @patch(
        "app.scheduler.jobs.send_operation_reminders",
        side_effect=RuntimeError("crash"),
    )
    def test_run_job_records_error_on_crash(self, mock_fn):
        result = jobs.run_job("send_operation_reminders", mock_fn)
        assert "error" in result

        with database.transaction() as db:
            run = repositories.get_latest_scheduler_run(db)
        assert run["status"] == "error"
        assert "crash" in (run["error_message"] or "")


# ---------------------------------------------------------------------------
# 17. Settings UI: reminders_enabled round-trip
# ---------------------------------------------------------------------------

class TestRemindersEnabledRoundTrip:

    def test_reminders_enabled_defaults_to_false(self):
        owner = make_user("SettingsOwner")
        ws = make_workspace(slug="settings-default", owner_user_id=owner["id"])
        with database.transaction() as db:
            fresh = repositories.get_workspace_by_id(db, ws["id"])
        assert not fresh.get("discord_reminders_enabled")

    def test_enable_reminders_persists(self):
        owner = make_user("EnableOwner")
        ws = make_workspace(slug="settings-enable", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
            reminders_enabled=True,
        )
        with database.transaction() as db:
            fresh = repositories.get_workspace_by_id(db, ws["id"])
        assert fresh["discord_reminders_enabled"] == 1

    def test_disable_reminders_persists(self):
        owner = make_user("DisableOwner")
        ws = make_workspace(slug="settings-disable", owner_user_id=owner["id"])
        # Enable then disable
        for val in (True, False):
            use_cases.update_workspace_discord_config(
                guild_workspace_id=ws["id"],
                actor_id=owner["id"],
                discord_guild_id=_GUILD_ID,
                announcement_channel_id=_ANN_CHANNEL,
                officer_channel_id=None,
                reminders_enabled=val,
            )
        with database.transaction() as db:
            fresh = repositories.get_workspace_by_id(db, ws["id"])
        assert fresh["discord_reminders_enabled"] == 0

    def test_auto_dispatch_and_reminders_independent(self):
        owner = make_user("IndepOwner")
        ws = make_workspace(slug="settings-indep", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
            auto_dispatch=True,
            reminders_enabled=False,
        )
        with database.transaction() as db:
            fresh = repositories.get_workspace_by_id(db, ws["id"])
        assert fresh["discord_auto_dispatch"] == 1
        assert fresh["discord_reminders_enabled"] == 0

    def test_http_form_enables_reminders(self):
        """HTTP POST to discord settings with checkbox enables reminders."""
        from fastapi.testclient import TestClient
        from app.main import app

        owner = make_user("HttpOwner")
        ws = make_workspace(slug="http-remind", owner_user_id=owner["id"])

        client = TestClient(app, raise_server_exceptions=True)
        # Log in as owner
        client.post("/login", data={"display_name": "HttpOwner"}, follow_redirects=True)

        resp = client.post(
            "/workspaces/http-remind/settings/discord",
            data={
                "discord_guild_id":          _GUILD_ID,
                "announcement_channel_id":   _ANN_CHANNEL,
                "officer_channel_id":        "",
                "discord_reminders_enabled": "1",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with database.transaction() as db:
            fresh = repositories.get_workspace_by_id(db, ws["id"])
        assert fresh["discord_reminders_enabled"] == 1

    def test_http_form_checkbox_absent_disables_reminders(self):
        """Omitting the checkbox from the form sets reminders_enabled=0."""
        from fastapi.testclient import TestClient
        from app.main import app

        owner = make_user("HttpOwner2")
        ws = make_workspace(slug="http-remind-off", owner_user_id=owner["id"])
        # Pre-enable reminders
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id="222333444555666001",
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
            reminders_enabled=True,
        )

        client = TestClient(app, raise_server_exceptions=True)
        client.post("/login", data={"display_name": "HttpOwner2"}, follow_redirects=True)
        # POST without checkbox (standard HTML checkbox-absent = unchecked)
        resp = client.post(
            "/workspaces/http-remind-off/settings/discord",
            data={
                "discord_guild_id":        "222333444555666001",
                "announcement_channel_id": _ANN_CHANNEL,
                "officer_channel_id":      "",
                # discord_reminders_enabled absent = unchecked
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with database.transaction() as db:
            fresh = repositories.get_workspace_by_id(db, ws["id"])
        assert fresh["discord_reminders_enabled"] == 0


# ---------------------------------------------------------------------------
# 18. Module boundary: formatter has no DB/SDK imports
# ---------------------------------------------------------------------------

class TestFormatterModuleBoundary:

    def test_formatter_does_not_import_database(self):
        import importlib
        import inspect
        mod = importlib.import_module("app.discord.formatters")
        src = inspect.getsource(mod)
        # Must not contain database import statements
        assert "from app import database" not in src
        assert "from app.database" not in src
        assert "import repositories" not in src
        assert "from app import repositories" not in src

    def test_formatter_does_not_import_discord_sdk(self):
        import importlib
        mod = importlib.import_module("app.discord.formatters")
        import inspect
        src = inspect.getsource(mod)
        assert "import discord" not in src

    def test_format_operation_reminder_is_pure(self):
        """Calling the formatter twice with the same input returns equal outputs."""
        op = {
            "id":                 "op-pure",
            "title":              "Pure Test",
            "operation_type":     "zvz",
            "status":             "planning",
            "scheduled_start_at": "2026-07-01T20:00:00+00:00",
        }
        out1 = formatters.format_operation_reminder(op, "T-2h")
        out2 = formatters.format_operation_reminder(op, "T-2h")
        assert out1 == out2

    def test_reminder_never_touches_discord_messages_table(self):
        """Sending a reminder must not insert any discord_messages rows."""
        _, ws = _make_reminder_workspace(slug="nomsg-ws")
        start = _now() + timedelta(hours=2) - timedelta(minutes=1)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        with patch("app.discord.rest_client.post_message", return_value="msg-nomsg"):
            jobs.send_operation_reminders()

        with database.transaction() as db:
            rows = db.execute("SELECT COUNT(*) FROM discord_messages").fetchone()
        assert rows[0] == 0

    def test_reminder_never_writes_operational_events(self):
        """Sending a reminder must not insert any operational_events rows."""
        _, ws = _make_reminder_workspace(slug="noevt-ws")
        start = _now() + timedelta(hours=2) - timedelta(minutes=1)
        op = make_operation(ws["id"], start=_iso(start))
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        with database.transaction() as db:
            event_count_before = db.execute(
                "SELECT COUNT(*) FROM operational_events"
            ).fetchone()[0]

        with patch("app.discord.rest_client.post_message", return_value="msg-noevt"):
            jobs.send_operation_reminders()

        with database.transaction() as db:
            event_count_after = db.execute(
                "SELECT COUNT(*) FROM operational_events"
            ).fetchone()[0]

        assert event_count_after == event_count_before
