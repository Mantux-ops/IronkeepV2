"""
Tests for Discord infrastructure persistence layer.

Covers:
- guild_workspaces Discord config columns (default null, update, lookup)
- discord_guild_id uniqueness constraint
- discord_messages CRUD (upsert, fetch, mark deleted)
- discord_dispatch_failures (insert, pending-only query)
"""

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from app import database, repositories
from tests.conftest import make_workspace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Workspace Discord config
# ---------------------------------------------------------------------------

def test_workspace_discord_config_defaults_null():
    ws = make_workspace()
    with database.transaction() as db:
        row = repositories.get_workspace_by_id(db, ws["id"])
    assert row["discord_guild_id"] is None
    assert row["discord_announcement_channel_id"] is None
    assert row["discord_officer_channel_id"] is None


def test_update_workspace_discord_config():
    ws = make_workspace()
    with database.transaction() as db:
        repositories.update_workspace_discord_config(
            db,
            workspace_id=ws["id"],
            discord_guild_id="111222333444555666",
            announcement_channel_id="777000111222333444",
            officer_channel_id="888000111222333444",
        )
    with database.transaction() as db:
        row = repositories.get_workspace_by_id(db, ws["id"])
    assert row["discord_guild_id"] == "111222333444555666"
    assert row["discord_announcement_channel_id"] == "777000111222333444"
    assert row["discord_officer_channel_id"] == "888000111222333444"


def test_get_workspace_by_discord_guild_id():
    ws = make_workspace()
    discord_guild_id = "123456789012345678"
    with database.transaction() as db:
        repositories.update_workspace_discord_config(
            db, ws["id"], discord_guild_id, None, None
        )
    with database.transaction() as db:
        found = repositories.get_workspace_by_discord_guild_id(db, discord_guild_id)
    assert found is not None
    assert found["id"] == ws["id"]


def test_get_workspace_by_discord_guild_id_returns_none_for_unknown():
    with database.transaction() as db:
        result = repositories.get_workspace_by_discord_guild_id(db, "000000000000000000")
    assert result is None


def test_discord_guild_id_is_unique():
    ws1 = make_workspace(name="WS One", slug="ws-one")
    ws2 = make_workspace(name="WS Two", slug="ws-two")
    discord_guild_id = "999888777666555444"
    with database.transaction() as db:
        repositories.update_workspace_discord_config(
            db, ws1["id"], discord_guild_id, None, None
        )
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as db:
            repositories.update_workspace_discord_config(
                db, ws2["id"], discord_guild_id, None, None
            )


def test_update_discord_config_clears_field_when_none():
    ws = make_workspace()
    with database.transaction() as db:
        repositories.update_workspace_discord_config(
            db, ws["id"], "111", "ach-ch", "off-ch"
        )
    with database.transaction() as db:
        repositories.update_workspace_discord_config(
            db, ws["id"], None, None, None
        )
    with database.transaction() as db:
        row = repositories.get_workspace_by_id(db, ws["id"])
    assert row["discord_guild_id"] is None


# ---------------------------------------------------------------------------
# discord_messages
# ---------------------------------------------------------------------------

def _make_discord_message(
    workspace_id: str,
    operation_id: str,
    message_type: str = "announcement",
    discord_message_id: str = "dm-001",
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": workspace_id,
        "guild_operation_id": operation_id,
        "message_type": message_type,
        "discord_channel_id": "ch-001",
        "discord_message_id": discord_message_id,
        "discord_guild_id": "gld-001",
        "posted_at": _now(),
        "last_edited_at": None,
        "is_deleted": 0,
    }


def _setup_operation(workspace_id: str):
    from app.application import use_cases
    op = use_cases.create_guild_operation(
        guild_workspace_id=workspace_id,
        title="Test Op",
        operation_type="zvz",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
    )
    return op


def test_upsert_discord_message_insert():
    ws = make_workspace()
    op = _setup_operation(ws["id"])
    record = _make_discord_message(ws["id"], op["id"])
    with database.transaction() as db:
        repositories.upsert_discord_message(db, record)
    with database.transaction() as db:
        fetched = repositories.get_discord_message(
            db, ws["id"], op["id"], "announcement"
        )
    assert fetched is not None
    assert fetched["discord_message_id"] == "dm-001"
    assert fetched["is_deleted"] == 0


def test_upsert_discord_message_update_replaces_message_id():
    ws = make_workspace()
    op = _setup_operation(ws["id"])
    record1 = _make_discord_message(ws["id"], op["id"], discord_message_id="dm-001")
    record2 = _make_discord_message(ws["id"], op["id"], discord_message_id="dm-002")
    with database.transaction() as db:
        repositories.upsert_discord_message(db, record1)
    with database.transaction() as db:
        repositories.upsert_discord_message(db, record2)
    with database.transaction() as db:
        fetched = repositories.get_discord_message(
            db, ws["id"], op["id"], "announcement"
        )
    assert fetched["discord_message_id"] == "dm-002"


def test_upsert_discord_message_different_types_coexist():
    ws = make_workspace()
    op = _setup_operation(ws["id"])
    ann = _make_discord_message(ws["id"], op["id"], message_type="announcement")
    roster = _make_discord_message(ws["id"], op["id"], message_type="roster")
    with database.transaction() as db:
        repositories.upsert_discord_message(db, ann)
        repositories.upsert_discord_message(db, roster)
    with database.transaction() as db:
        fetched_ann = repositories.get_discord_message(
            db, ws["id"], op["id"], "announcement"
        )
        fetched_roster = repositories.get_discord_message(
            db, ws["id"], op["id"], "roster"
        )
    assert fetched_ann is not None
    assert fetched_roster is not None


def test_get_discord_message_returns_none_when_absent():
    ws = make_workspace()
    op = _setup_operation(ws["id"])
    with database.transaction() as db:
        result = repositories.get_discord_message(
            db, ws["id"], op["id"], "announcement"
        )
    assert result is None


def test_mark_discord_message_deleted():
    ws = make_workspace()
    op = _setup_operation(ws["id"])
    record = _make_discord_message(ws["id"], op["id"])
    with database.transaction() as db:
        repositories.upsert_discord_message(db, record)
    with database.transaction() as db:
        repositories.mark_discord_message_deleted(db, record["id"])
    with database.transaction() as db:
        fetched = repositories.get_discord_message(
            db, ws["id"], op["id"], "announcement"
        )
    assert fetched["is_deleted"] == 1


def test_discord_messages_scoped_by_workspace():
    ws1 = make_workspace(name="WS A", slug="ws-a")
    ws2 = make_workspace(name="WS B", slug="ws-b")
    op1 = _setup_operation(ws1["id"])
    op2 = _setup_operation(ws2["id"])
    rec1 = _make_discord_message(ws1["id"], op1["id"])
    with database.transaction() as db:
        repositories.upsert_discord_message(db, rec1)
    with database.transaction() as db:
        # same operation_id type but wrong workspace — should not be found
        result = repositories.get_discord_message(
            db, ws2["id"], op2["id"], "announcement"
        )
    assert result is None


# ---------------------------------------------------------------------------
# discord_dispatch_failures
# ---------------------------------------------------------------------------

def _make_failure(workspace_id: str, status: str = "pending_retry") -> dict:
    return {
        "id":                 str(uuid.uuid4()),
        "guild_workspace_id": workspace_id,
        "guild_operation_id": None,
        "event_type":         "guild_operation.published",
        "entity_id":          str(uuid.uuid4()),
        "error_code":         429,
        "error_message":      "rate limited",
        "attempted_at":       _now(),
        "retry_count":        0,
        "status":             status,
        "payload_json":       "{}",
        "next_attempt_at":    "",
    }


def test_insert_discord_dispatch_failure():
    ws = make_workspace()
    record = _make_failure(ws["id"])
    with database.transaction() as db:
        repositories.insert_discord_dispatch_failure(db, record)
    with database.transaction() as db:
        pending = repositories.get_pending_discord_dispatch_failures(db, ws["id"])
    assert len(pending) == 1
    assert pending[0]["event_type"] == "guild_operation.published"
    assert pending[0]["error_code"] == 429


def test_get_pending_dispatch_failures_excludes_resolved():
    ws = make_workspace()
    pending1 = _make_failure(ws["id"], status="pending_retry")
    pending2 = _make_failure(ws["id"], status="pending_retry")
    resolved = _make_failure(ws["id"], status="resolved")
    failed = _make_failure(ws["id"], status="failed")
    with database.transaction() as db:
        for r in [pending1, pending2, resolved, failed]:
            repositories.insert_discord_dispatch_failure(db, r)
    with database.transaction() as db:
        result = repositories.get_pending_discord_dispatch_failures(db, ws["id"])
    assert len(result) == 2
    assert all(r["status"] == "pending_retry" for r in result)


def test_dispatch_failures_scoped_by_workspace():
    ws1 = make_workspace(name="WS X", slug="ws-x")
    ws2 = make_workspace(name="WS Y", slug="ws-y")
    with database.transaction() as db:
        repositories.insert_discord_dispatch_failure(db, _make_failure(ws1["id"]))
    with database.transaction() as db:
        result = repositories.get_pending_discord_dispatch_failures(db, ws2["id"])
    assert result == []
