"""
Scheduler job tests.

All tests call job functions directly — the polling loop in __main__.py is
never started.  SCHEDULER_ENABLED is not set so python -m app.scheduler would
exit immediately if invoked accidentally.

Test groups:
  1. retry_dispatch_failures — core retry logic
  2. retry_dispatch_failures — gate behaviour
  3. refresh_stale_metadata
  4. scheduler_runs observability (write_scheduler_run_start/finish, run_job)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import database, repositories
from app.application import use_cases
from app.scheduler import jobs
from tests.conftest import make_composition, make_operation, make_user, make_workspace

_GUILD_ID    = "111222333444555666"
_ANN_CHANNEL = "777888999000111222"
_OFF_CHANNEL = "333444555666777888"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_linked_workspace():
    """Return (owner, workspace) with Discord config and auto_dispatch=1."""
    owner = make_user("SchedOwner")
    ws = make_workspace(slug="sched-ws", owner_user_id=owner["id"])
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=_ANN_CHANNEL,
        officer_channel_id=None,
    )
    # Enable auto-dispatch
    with database.transaction() as db:
        db.execute(
            "UPDATE guild_workspaces SET discord_auto_dispatch = 1 WHERE id = ?",
            (ws["id"],),
        )
        ws = repositories.get_workspace_by_id(db, ws["id"])
    return owner, ws


def _make_operation_with_readiness(ws_id: str) -> tuple[dict, dict]:
    """Return (operation, readiness_snapshot) for a published op with a plan."""
    comp = make_composition(ws_id)
    op   = make_operation(ws_id)
    use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
    use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    snap = use_cases.calculate_readiness_snapshot(ws_id, op["id"])
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, op["id"], ws_id)
    return op, snap


def _insert_failure(
    ws_id: str,
    op_id: str | None = None,
    event_type: str = "readiness_snapshot.created",
    entity_id: str | None = None,
    retry_count: int = 0,
    next_attempt_at: str = "",
    status: str = "pending_retry",
) -> dict:
    """Insert a discord_dispatch_failures row directly for test setup."""
    now = _iso(_now())
    record = {
        "id":                 str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "guild_operation_id": op_id,
        "event_type":         event_type,
        "entity_id":          entity_id,
        "error_code":         None,
        "error_message":      "simulated failure",
        "attempted_at":       now,
        "retry_count":        retry_count,
        "status":             status,
        "payload_json":       "{}",
        "next_attempt_at":    next_attempt_at,
    }
    with database.transaction() as db:
        repositories.insert_discord_dispatch_failure(db, record)
    return record


def _get_failure(failure_id: str) -> dict:
    with database.transaction() as db:
        row = db.execute(
            "SELECT * FROM discord_dispatch_failures WHERE id = ?",
            (failure_id,),
        ).fetchone()
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# 1. retry_dispatch_failures — core logic
# ---------------------------------------------------------------------------

class TestRetryDispatchFailuresCore:
    def test_resolves_row_on_successful_rest_call(self):
        """A successful REST call marks the failure row as resolved."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(ws["id"], op_id=op["id"], entity_id=snap["id"])

        with (
            patch("app.discord.rest_client.post_message", return_value="msg-123"),
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        assert result["resolved"] >= 1
        assert _get_failure(row["id"])["status"] == "resolved"

    def test_bumps_retry_count_on_rest_failure(self):
        """A failing REST call increments retry_count and sets next_attempt_at."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(ws["id"], op_id=op["id"], entity_id=snap["id"])

        from app.discord.rest_client import DiscordApiError

        with (
            patch("app.discord.rest_client.post_message",
                  side_effect=DiscordApiError(500, "internal error")),
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        updated = _get_failure(row["id"])
        assert updated["status"] == "pending_retry"
        assert updated["retry_count"] == 1
        assert updated["next_attempt_at"] != ""

    def test_exhausts_row_after_max_retries(self):
        """A row at MAX_RETRIES - 1 that fails again becomes exhausted."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(
            ws["id"],
            op_id=op["id"],
            entity_id=snap["id"],
            retry_count=jobs.MAX_RETRIES - 1,
        )

        from app.discord.rest_client import DiscordApiError

        with (
            patch("app.discord.rest_client.post_message",
                  side_effect=DiscordApiError(403, "forbidden")),
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        updated = _get_failure(row["id"])
        assert updated["status"] == "exhausted"
        assert updated["retry_count"] == jobs.MAX_RETRIES
        assert result["exhausted"] >= 1

    def test_skips_row_with_future_next_attempt_at(self):
        """A row whose backoff window has not expired is not attempted."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        future = _iso(_now() + timedelta(hours=1))
        row = _insert_failure(
            ws["id"],
            op_id=op["id"],
            entity_id=snap["id"],
            next_attempt_at=future,
        )

        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert result["checked"] == 0  # not even fetched
        assert _get_failure(row["id"])["status"] == "pending_retry"

    def test_no_operation_context_resolves_as_noop(self):
        """
        A failure row with guild_operation_id=None causes resolve_action to return
        noop (no operation to dispatch for) → row is marked resolved, no REST call.
        """
        _, ws = _make_linked_workspace()
        # guild_operation_id=None: dispatcher._handle_readiness_event returns noop
        row = _insert_failure(ws["id"], op_id=None, entity_id=None)

        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert _get_failure(row["id"])["status"] == "resolved"
        assert result["resolved"] >= 1

    def test_upserts_discord_message_on_success(self):
        """Successful retry writes a discord_messages row."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        _insert_failure(ws["id"], op_id=op["id"], entity_id=snap["id"])

        with (
            patch("app.discord.rest_client.post_message", return_value="new-msg-999"),
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            jobs.retry_dispatch_failures()

        with database.transaction() as db:
            msg = repositories.get_discord_message(db, ws["id"], op["id"], "readiness")
        assert msg is not None
        assert msg["discord_message_id"] == "new-msg-999"

    def test_edit_fallback_to_post_on_404(self):
        """edit_message 404 falls back to post_message and resolves the failure."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])

        # Pre-insert a discord_messages row so resolve_action returns edit_message.
        msg_record = {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "guild_operation_id": op["id"],
            "message_type":       "readiness",
            "discord_channel_id": _ANN_CHANNEL,
            "discord_message_id": "old-msg-111",
            "discord_guild_id":   _GUILD_ID,
            "posted_at":          _iso(_now()),
            "last_edited_at":     None,
            "is_deleted":         0,
        }
        with database.transaction() as db:
            repositories.upsert_discord_message(db, msg_record)

        row = _insert_failure(ws["id"], op_id=op["id"], entity_id=snap["id"])

        from app.discord.rest_client import DiscordApiError

        with (
            patch("app.discord.rest_client.edit_message",
                  side_effect=DiscordApiError(404, "not found")),
            patch("app.discord.rest_client.post_message", return_value="fallback-msg"),
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        assert _get_failure(row["id"])["status"] == "resolved"
        assert result["resolved"] >= 1

    def test_non_executable_event_type_resolves(self):
        """
        A failure row for a non-executable event type (e.g. guild_operation.published)
        is resolved without making a REST call.
        """
        _, ws = _make_linked_workspace()
        op, _ = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(
            ws["id"],
            op_id=op["id"],
            event_type="guild_operation.published",
        )

        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert _get_failure(row["id"])["status"] == "resolved"

    def test_result_checked_count_matches_due_rows(self):
        """checked count equals the number of rows due for retry."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])

        past = _iso(_now() - timedelta(minutes=10))
        future = _iso(_now() + timedelta(hours=1))
        _insert_failure(ws["id"], op_id=op["id"], next_attempt_at=past)  # due
        _insert_failure(ws["id"], op_id=op["id"], next_attempt_at=future)  # not due

        with (
            patch("app.discord.rest_client.post_message", return_value="x"),
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        assert result["checked"] == 1


# ---------------------------------------------------------------------------
# 2. retry_dispatch_failures — gate behaviour
# ---------------------------------------------------------------------------

class TestRetryDispatchGates:
    def test_env_gate_off_leaves_row_pending(self):
        """DISCORD_DISPATCH_ENABLED not set → row stays pending_retry, no REST."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(ws["id"], op_id=op["id"], entity_id=snap["id"])

        env = {"DISCORD_DISPATCH_ENABLED": "0"}
        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", env, clear=False),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert _get_failure(row["id"])["status"] == "pending_retry"
        assert result["gate_skipped"] >= 1

    def test_workspace_auto_dispatch_off_leaves_row_pending(self):
        """workspace.discord_auto_dispatch=0 → row stays pending_retry, no REST."""
        owner = make_user("GateOwner")
        ws = make_workspace(slug="gate-ws", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
        )
        # discord_auto_dispatch defaults to 0 — do NOT enable it

        comp = make_composition(ws["id"])
        op   = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        snap = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

        row = _insert_failure(ws["id"], op_id=op["id"], entity_id=snap["id"])

        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert _get_failure(row["id"])["status"] == "pending_retry"
        assert result["gate_skipped"] >= 1

    def test_exhausted_rows_not_retried(self):
        """Rows with status=exhausted are never picked up by the retry job."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(
            ws["id"],
            op_id=op["id"],
            entity_id=snap["id"],
            status="exhausted",
        )

        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert result["checked"] == 0

    def test_resolved_rows_not_retried(self):
        """Rows with status=resolved are never picked up by the retry job."""
        _, ws = _make_linked_workspace()
        op, snap = _make_operation_with_readiness(ws["id"])
        row = _insert_failure(
            ws["id"],
            op_id=op["id"],
            entity_id=snap["id"],
            status="resolved",
        )

        with (
            patch("app.discord.rest_client.post_message") as mock_post,
            patch.dict("os.environ", {"DISCORD_DISPATCH_ENABLED": "1"}),
        ):
            result = jobs.retry_dispatch_failures()

        mock_post.assert_not_called()
        assert result["checked"] == 0


# ---------------------------------------------------------------------------
# 3. refresh_stale_metadata
# ---------------------------------------------------------------------------

class TestRefreshStaleMetadata:
    def _workspace_with_stale_cache(self) -> dict:
        """Workspace with discord_guild_id but a cache entry older than TTL."""
        owner = make_user("MetaOwner")
        ws = make_workspace(slug="meta-ws", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
        )
        # Insert a stale cache entry (older than METADATA_STALE_HOURS)
        stale_ts = (
            datetime.now(timezone.utc) - timedelta(hours=jobs.METADATA_STALE_HOURS + 1)
        ).isoformat()
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO discord_metadata_cache
                    (id, guild_workspace_id, entity_type, discord_entity_id, name,
                     extra_json, fetched_at)
                VALUES (?, ?, 'guild', ?, 'Old Name', '{}', ?)
                """,
                (str(uuid.uuid4()), ws["id"], _GUILD_ID, stale_ts),
            )
        with database.transaction() as db:
            return dict(repositories.get_workspace_by_id(db, ws["id"]))

    def test_refreshes_workspace_with_stale_cache(self):
        """A workspace with a stale cache entry triggers refresh_discord_metadata."""
        ws = self._workspace_with_stale_cache()

        mock_result = {"guild": "ok", "channels": {}}
        with patch(
            "app.application.use_cases.refresh_discord_metadata",
            return_value=mock_result,
        ) as mock_refresh:
            result = jobs.refresh_stale_metadata()

        mock_refresh.assert_called_once_with(ws["id"])
        assert result["refreshed"] == 1
        assert result["workspaces_checked"] == 1

    def test_refreshes_workspace_with_no_cache(self):
        """A workspace with discord_guild_id but no cache rows at all triggers refresh."""
        owner = make_user("NoCache")
        ws = make_workspace(slug="nocache-ws", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
        )

        mock_result = {"guild": "ok", "channels": {}}
        with patch(
            "app.application.use_cases.refresh_discord_metadata",
            return_value=mock_result,
        ) as mock_refresh:
            result = jobs.refresh_stale_metadata()

        mock_refresh.assert_called_once_with(ws["id"])
        assert result["refreshed"] == 1

    def test_skips_workspace_without_discord_guild_id(self):
        """Workspaces not configured with discord_guild_id are skipped entirely."""
        make_workspace(slug="nodiscord-ws")

        with patch("app.application.use_cases.refresh_discord_metadata") as mock_refresh:
            result = jobs.refresh_stale_metadata()

        mock_refresh.assert_not_called()
        assert result["workspaces_checked"] == 0

    def test_skips_workspace_with_fresh_cache(self):
        """A workspace whose cache was refreshed within TTL is not re-fetched."""
        owner = make_user("FreshOwner")
        ws = make_workspace(slug="fresh-ws", owner_user_id=owner["id"])
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=_ANN_CHANNEL,
            officer_channel_id=None,
        )
        # Insert a fresh cache entry
        fresh_ts = datetime.now(timezone.utc).isoformat()
        with database.transaction() as db:
            db.execute(
                """
                INSERT INTO discord_metadata_cache
                    (id, guild_workspace_id, entity_type, discord_entity_id, name,
                     extra_json, fetched_at)
                VALUES (?, ?, 'guild', ?, 'Fresh Name', '{}', ?)
                """,
                (str(uuid.uuid4()), ws["id"], _GUILD_ID, fresh_ts),
            )

        with patch("app.application.use_cases.refresh_discord_metadata") as mock_refresh:
            result = jobs.refresh_stale_metadata()

        mock_refresh.assert_not_called()
        assert result["workspaces_checked"] == 0

    def test_error_in_refresh_is_recorded_not_raised(self):
        """A REST error during refresh increments errors and does not abort the job."""
        ws = self._workspace_with_stale_cache()

        with patch(
            "app.application.use_cases.refresh_discord_metadata",
            side_effect=Exception("Discord 503"),
        ):
            result = jobs.refresh_stale_metadata()

        assert result["errors"] == 1
        assert result["refreshed"] == 0

    def test_multiple_workspaces_refreshed_independently(self):
        """Each qualifying workspace is refreshed; one error does not skip others."""
        _GUILD_IDS = ["111000000000000001", "111000000000000002", "111000000000000003"]
        ws_ids = []
        for i in range(3):
            owner = make_user(f"MultiOwner{i}")
            ws = make_workspace(slug=f"multi-ws-{i}", owner_user_id=owner["id"])
            use_cases.update_workspace_discord_config(
                guild_workspace_id=ws["id"],
                actor_id=owner["id"],
                discord_guild_id=_GUILD_IDS[i],
                announcement_channel_id=_ANN_CHANNEL,
                officer_channel_id=None,
            )
            ws_ids.append(ws["id"])

        refreshed = []

        def _side_effect(ws_id):
            refreshed.append(ws_id)
            return {"guild": "ok", "channels": {}}

        with patch(
            "app.application.use_cases.refresh_discord_metadata",
            side_effect=_side_effect,
        ):
            result = jobs.refresh_stale_metadata()

        assert result["refreshed"] == 3
        assert set(refreshed) == set(ws_ids)


# ---------------------------------------------------------------------------
# 4. Scheduler runs observability
# ---------------------------------------------------------------------------

class TestSchedulerRuns:
    def test_write_start_creates_running_row(self):
        """write_scheduler_run_start writes a 'running' row with NULL finished_at."""
        run_id = str(uuid.uuid4())
        started = _iso(_now())
        jobs.write_scheduler_run_start(run_id, "test_job", started)

        with database.transaction() as db:
            row = repositories.get_scheduler_run(db, run_id)

        assert row is not None
        assert row["status"] == "running"
        assert row["finished_at"] is None
        assert row["job_name"] == "test_job"
        assert row["started_at"] == started

    def test_write_finish_updates_row(self):
        """write_scheduler_run_finish updates status, finished_at, result_json."""
        run_id = str(uuid.uuid4())
        jobs.write_scheduler_run_start(run_id, "test_job", _iso(_now()))
        jobs.write_scheduler_run_finish(
            run_id, "success", {"resolved": 2, "checked": 3}, None
        )

        with database.transaction() as db:
            row = repositories.get_scheduler_run(db, run_id)

        assert row["status"] == "success"
        assert row["finished_at"] is not None
        assert json.loads(row["result_json"])["resolved"] == 2
        assert row["error_message"] is None

    def test_write_finish_error_records_message(self):
        """write_scheduler_run_finish with status=error records the error_message."""
        run_id = str(uuid.uuid4())
        jobs.write_scheduler_run_start(run_id, "test_job", _iso(_now()))
        jobs.write_scheduler_run_finish(run_id, "error", {}, "something exploded")

        with database.transaction() as db:
            row = repositories.get_scheduler_run(db, run_id)

        assert row["status"] == "error"
        assert row["error_message"] == "something exploded"

    def test_crash_detection_finished_at_remains_null(self):
        """
        If write_scheduler_run_finish is never called (simulated crash),
        the row retains finished_at=NULL and status='running'.
        This is the crash-detection sentinel pattern.
        """
        run_id = str(uuid.uuid4())
        jobs.write_scheduler_run_start(run_id, "crashing_job", _iso(_now()))
        # Intentionally do NOT call write_scheduler_run_finish

        with database.transaction() as db:
            row = repositories.get_scheduler_run(db, run_id)

        assert row["finished_at"] is None
        assert row["status"] == "running"

    def test_run_job_writes_scheduler_run_on_success(self):
        """run_job writes a complete scheduler_runs row on successful fn()."""
        calls = []

        def _fn():
            calls.append(1)
            return {"checked": 5, "resolved": 3}

        result = jobs.run_job("test_success_job", _fn)
        assert result == {"checked": 5, "resolved": 3}
        assert len(calls) == 1

        # Verify a run row exists with status=success
        with database.transaction() as db:
            rows = db.execute(
                "SELECT * FROM scheduler_runs WHERE job_name = 'test_success_job' ORDER BY started_at DESC",
            ).fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["status"] == "success"
        assert dict(rows[0])["finished_at"] is not None

    def test_run_job_writes_scheduler_run_on_error(self):
        """run_job writes a scheduler_runs row with status=error when fn() raises."""

        def _failing_fn():
            raise RuntimeError("test job crash")

        result = jobs.run_job("test_error_job", _failing_fn)
        assert "error" in result

        with database.transaction() as db:
            rows = db.execute(
                "SELECT * FROM scheduler_runs WHERE job_name = 'test_error_job'",
            ).fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["status"] == "error"
        assert "test job crash" in dict(rows[0])["error_message"]

    def test_run_job_does_not_raise_on_fn_error(self):
        """run_job must never raise even when the wrapped job function crashes."""

        def _exploding_fn():
            raise Exception("kaboom")

        result = jobs.run_job("exploding_job", _exploding_fn)
        assert isinstance(result, dict)  # returns error dict, does not raise


# ---------------------------------------------------------------------------
# 5. Backoff correctness
# ---------------------------------------------------------------------------

class TestBackoff:
    def test_next_attempt_at_first_backoff(self):
        """retry_count=0 → backoff is 5 minutes."""
        now = _now()
        result = jobs._next_attempt_at(0, now)
        dt = datetime.fromisoformat(result)
        assert abs((dt - now).total_seconds() - 300) < 2

    def test_next_attempt_at_second_backoff(self):
        """retry_count=1 → backoff is 30 minutes."""
        now = _now()
        result = jobs._next_attempt_at(1, now)
        dt = datetime.fromisoformat(result)
        assert abs((dt - now).total_seconds() - 1800) < 2

    def test_next_attempt_at_third_backoff(self):
        """retry_count=2 → backoff is 2 hours."""
        now = _now()
        result = jobs._next_attempt_at(2, now)
        dt = datetime.fromisoformat(result)
        assert abs((dt - now).total_seconds() - 7200) < 2

    def test_next_attempt_at_clamps_at_last_backoff(self):
        """retry_count beyond list length uses the last backoff value (2h)."""
        now = _now()
        result = jobs._next_attempt_at(99, now)
        dt = datetime.fromisoformat(result)
        assert abs((dt - now).total_seconds() - 7200) < 2


# ---------------------------------------------------------------------------
# 6. dispatcher.py — _record_failure_direct writes new columns
# ---------------------------------------------------------------------------

class TestRecordFailureDirect:
    def test_writes_next_attempt_at_on_failure(self):
        """
        _record_failure_direct populates next_attempt_at (≈now + 5m)
        so the retry job respects the initial backoff window.
        """
        from app.discord.dispatcher import _record_failure_direct

        _, ws = _make_linked_workspace()
        event = {
            "id":                 str(uuid.uuid4()),
            "event_type":         "readiness_snapshot.created",
            "guild_workspace_id": ws["id"],
            "guild_operation_id": None,
            "entity_id":          None,
            "payload_json":       "{}",
            "occurred_at":        _iso(_now()),
        }
        _record_failure_direct(event, Exception("boom"))

        with database.transaction() as db:
            rows = db.execute(
                "SELECT * FROM discord_dispatch_failures WHERE guild_workspace_id = ?",
                (ws["id"],),
            ).fetchall()

        assert len(rows) == 1
        row = dict(rows[0])
        assert row["next_attempt_at"] != ""
        dt_next = datetime.fromisoformat(row["next_attempt_at"])
        dt_now  = _now()
        # Should be ~5 minutes in the future (within a 30s test-execution window)
        diff_s = (dt_next - dt_now).total_seconds()
        assert 270 < diff_s < 330, f"Expected ~300s delay, got {diff_s}s"

    def test_writes_payload_json_on_failure(self):
        """_record_failure_direct stores the original event payload_json."""
        from app.discord.dispatcher import _record_failure_direct

        _, ws = _make_linked_workspace()
        event = {
            "id":                 str(uuid.uuid4()),
            "event_type":         "readiness_snapshot.created",
            "guild_workspace_id": ws["id"],
            "guild_operation_id": None,
            "entity_id":          None,
            "payload_json":       '{"key": "value"}',
            "occurred_at":        _iso(_now()),
        }
        _record_failure_direct(event, Exception("payload test"))

        with database.transaction() as db:
            rows = db.execute(
                "SELECT * FROM discord_dispatch_failures WHERE guild_workspace_id = ?",
                (ws["id"],),
            ).fetchall()

        assert len(rows) == 1
        row = dict(rows[0])
        assert row["payload_json"] != ""
