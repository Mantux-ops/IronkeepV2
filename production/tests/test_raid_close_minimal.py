"""Tests for the minimal raid-close hotfix on origin/main.

Imports production/ironkeep from this worktree. Discord is not contacted.
Each database is a temporary file.
"""

import ast
import hashlib
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKTREE = ROOT.parent
PUBLICATION_COLUMNS = {
    "post_nonce",
    "post_nonce_at",
    "post_claimed_at",
    "post_claim_token",
    "post_recovery_required",
    "post_repost_blocked",
    "close_effects_pending",
    "post_channel_bound",
}
DB_CHANGED = {
    "place_signup",
    "set_signup_lane",
    "set_party_count",
    "fill_open_parties",
    "remove_signup",
}
WOW_CHANGED = {"_action", "handle_absence"}


def _sha256(path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _head_text(path):
    return subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=WORKTREE).decode("utf-8")


def _top_level_text(text):
    tree = ast.parse(text)
    items = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            items.append(("def", node.name, ast.dump(node, include_attributes=False)))
        else:
            items.append(("other", None, ast.dump(node, include_attributes=False)))
    return items


os.environ["IRONKEEP_DB"] = ""
os.environ["IRONKEEP_ENV_FILE"] = ""
os.environ["IRONKEEP_COMPANION_AUTH"] = ""
os.environ["DISCORD_BOT_TOKEN"] = ""
os.environ["DISCORD_CLIENT_ID"] = ""
os.environ["DISCORD_CLIENT_SECRET"] = ""
os.environ["IRONKEEP_COMPANION_CACHE"] = str(ROOT / "tests" / "fixtures" / "forever.json")
os.environ["IRONKEEP_WOW_CATALOG"] = str(ROOT / "tests" / "fixtures" / "wow.json")
sys.path.insert(0, str(ROOT))

from ironkeep import config, db, wow


def _top_level(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    items = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            items.append(("def", node.name, ast.dump(node, include_attributes=False)))
        else:
            items.append(("other", None, ast.dump(node, include_attributes=False)))
    return items


def _mutate(db_path, action, raid_id, started, outcome):
    from ironkeep import config as child_config
    from ironkeep import db as child_db

    child_config.DB_PATH = db_path
    started.set()
    try:
        if action == "lane":
            value = child_db.set_signup_lane(raid_id, "4004", "healer", "main", 1)
        elif action == "party":
            value = child_db.set_party_count(raid_id, 2)
        elif action == "fill":
            value = child_db.fill_open_parties(raid_id)
        elif action == "leave":
            value = child_db.remove_signup(raid_id, "4004")
        elif action == "place":
            raid = child_db.raid_by_id(raid_id)
            value = child_db.place_signup(raid, "7007", "Dee", "warrior", "arms", "dps")
        else:
            raise AssertionError(action)
        outcome.put(("ok", value))
    except Exception as error:
        outcome.put(("error", f"{type(error).__name__}: {error}"))


def _leave_after_status_read(db_path, raid_id, user_id, seen, release):
    from ironkeep import config as child_config
    from ironkeep import db as child_db

    child_config.DB_PATH = db_path
    real_begin = child_db.begin_immediate

    def begin_immediate():
        conn = real_begin()

        class Holding:
            def execute(self, sql, params=()):
                cursor = conn.execute(sql, params)
                if isinstance(sql, str) and "SELECT status FROM raids WHERE id = ?" in sql:
                    seen.set()
                    if not release.wait(timeout=10):
                        raise TimeoutError("leave was not released")
                return cursor

            def commit(self):
                return conn.commit()

            def rollback(self):
                return conn.rollback()

            def close(self):
                return conn.close()

        return Holding()

    child_db.begin_immediate = begin_immediate
    child_db.remove_signup(raid_id, user_id)


class HotfixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous = config.DB_PATH
        config.DB_PATH = str(Path(self.temp.name) / "hotfix.sqlite")
        self.addCleanup(lambda: setattr(config, "DB_PATH", self.previous))
        normalized = config.DB_PATH.replace("\\", "/")
        self.assertNotIn("/var/lib/ironkeep", normalized)
        db.init()

    def _raid(self, status="open"):
        db.upsert_guild(
            "1001",
            "Keep",
            [{"id": "999", "name": "Officer"}],
            [{"id": "111", "name": "raids"}],
            added_by_id="42",
        )
        guild = db.guild_by_id("1001")
        if guild.get("game") != "wow":
            self.assertTrue(db.set_game(guild["slug"], "wow"))
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()
        return db.create_raid(
            "1001", "Keep", start, 1, 1, 1, "111", "Officer", 10, "barrow-deeps", status=status
        )

    def _rows(self, raid_id):
        conn = db.connect()
        try:
            return [
                (row["user_id"], row["role"], row["state"], int(row["party"] or 1))
                for row in conn.execute(
                    """SELECT user_id, role, state, party FROM raid_signups
                       WHERE raid_id = ? ORDER BY user_id""",
                    (raid_id,),
                )
            ]
        finally:
            conn.close()

    def _attendance(self, raid_id):
        conn = db.connect()
        try:
            return [
                (row["user_id"], row["name"], row["present"])
                for row in conn.execute(
                    "SELECT user_id, name, present FROM raid_attendance WHERE raid_id = ? ORDER BY user_id",
                    (raid_id,),
                )
            ]
        finally:
            conn.close()

    def _seed(self, raid_id):
        raid = db.raid_by_id(raid_id)
        self.assertEqual(db.place_signup(raid, "4004", "Ada", "warrior", "protection", "tank"), "main")
        self.assertEqual(db.place_signup(raid, "5005", "Bea", "priest", "holy", "healer"), "main")
        self.assertEqual(
            db.place_signup(db.raid_by_id(raid_id), "6006", "Cid", "priest", "discipline", "healer"),
            "reserve",
        )
        db.set_attendance(raid_id, "4004", "Ada", True)

    def _close_while_blocked(self, raid_id, action, expected):
        context = multiprocessing.get_context("spawn")
        started = context.Event()
        outcome = context.Queue()
        holder = sqlite3.connect(config.DB_PATH, timeout=5, isolation_level=None)
        holder.execute("PRAGMA busy_timeout=5000")
        holder.execute("BEGIN IMMEDIATE")
        process = context.Process(target=_mutate, args=(config.DB_PATH, action, raid_id, started, outcome))
        process.start()
        try:
            self.assertTrue(started.wait(timeout=15))
            probe = sqlite3.connect(config.DB_PATH, timeout=0, isolation_level=None)
            try:
                probe.execute("PRAGMA busy_timeout=0")
                with self.assertRaises(sqlite3.OperationalError):
                    probe.execute("BEGIN IMMEDIATE")
            finally:
                probe.close()
            holder.execute("UPDATE raids SET status = 'closed' WHERE id = ?", (raid_id,))
            holder.commit()
        finally:
            holder.close()
            process.join(timeout=20)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        kind, value = outcome.get(timeout=5)
        self.assertEqual(kind, "ok", value)
        self.assertEqual(value, expected)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")

    def _answers(self):
        sent = []

        def edit(token, payload):
            sent.append(payload.get("content"))

        return sent, edit

    def test_open_raid_accepts_signup_lane_change_and_leave(self):
        raid_id = self._raid()
        self._seed(raid_id)
        self.assertTrue(db.set_signup_lane(raid_id, "4004", "healer", "late", 1))
        self.assertIn(("4004", "healer", "late", 1), self._rows(raid_id))
        self.assertTrue(db.remove_signup(raid_id, "4004"))
        self.assertNotIn("4004", [row[0] for row in self._rows(raid_id)])
        self.assertIn(("5005", "healer", "main", 1), self._rows(raid_id))
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

    def test_open_party_change_and_fill_keep_their_results(self):
        raid_id = self._raid()
        self._seed(raid_id)
        self.assertTrue(db.set_party_count(raid_id, 1))
        self.assertFalse(db.set_party_count(raid_id, 0))
        self.assertFalse(db.set_party_count(raid_id, 5))
        self.assertTrue(db.set_party_count(raid_id, 2))
        self.assertEqual(db.raid_by_id(raid_id)["party_count"], 2)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            """INSERT INTO raid_signups
               (raid_id, user_id, name, class_id, spec_id, role, state, party, created_at)
               VALUES (?, '8008', 'Eve', 'warrior', 'protection', 'tank', 'reserve', 1, '2026-01-01T00:00:00')""",
            (raid_id,),
        )
        conn.commit()
        conn.close()
        self.assertTrue(db.fill_open_parties(raid_id))
        self.assertIn(("8008", "tank", "main", 2), self._rows(raid_id))

    def test_closed_raid_rejects_every_writer_and_keeps_attendance(self):
        raid_id = self._raid()
        self._seed(raid_id)
        before = self._rows(raid_id)
        db.close_raid(raid_id)
        self.assertIsNone(db.close_raid(raid_id))
        raid = db.raid_by_id(raid_id)
        self.assertEqual(raid["status"], "closed")
        self.assertIsNone(db.place_signup(raid, "7007", "Dee", "warrior", "arms", "dps"))
        self.assertFalse(db.set_signup_lane(raid_id, "4004", "healer", "main", 1))
        self.assertFalse(db.set_party_count(raid_id, 2))
        self.assertFalse(db.fill_open_parties(raid_id))
        self.assertFalse(db.remove_signup(raid_id, "4004"))
        self.assertFalse(db.remove_signup(raid_id, "missing"))
        self.assertEqual(self._rows(raid_id), before)
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])
        self.assertNotIn("7007", [row[0] for row in self._rows(raid_id)])

    def test_invalid_arguments_return_before_taking_the_write_lock(self):
        raid_id = self._raid()
        self._seed(raid_id)
        holder = sqlite3.connect(config.DB_PATH, timeout=0, isolation_level=None)
        holder.execute("PRAGMA busy_timeout=0")
        holder.execute("BEGIN IMMEDIATE")
        try:
            self.assertFalse(db.set_signup_lane(raid_id, "4004", "nope", "main"))
            self.assertFalse(db.set_party_count(raid_id, 0))
            self.assertFalse(db.set_party_count(raid_id, 9))
        finally:
            holder.rollback()
            holder.close()
        self.assertIn(("4004", "tank", "main", 1), self._rows(raid_id))

    def _restore(self, raid_id):
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("DROP TRIGGER IF EXISTS abort_write")
        conn.execute("DELETE FROM raid_signups WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM raid_attendance WHERE raid_id = ?", (raid_id,))
        conn.execute("UPDATE raids SET status = 'open', party_count = 1 WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()
        self._seed(raid_id)

    def test_aborted_writes_roll_back_and_a_retry_succeeds(self):
        raid_id = self._raid()
        cases = (
            (
                "CREATE TRIGGER abort_write BEFORE INSERT ON raid_signups BEGIN SELECT RAISE(ABORT, 'forced'); END",
                lambda: db.place_signup(db.raid_by_id(raid_id), "7007", "Dee", "warrior", "arms", "dps"),
            ),
            (
                "CREATE TRIGGER abort_write BEFORE UPDATE ON raid_signups BEGIN SELECT RAISE(ABORT, 'forced'); END",
                lambda: db.set_signup_lane(raid_id, "4004", "healer", "main", 1),
            ),
            (
                "CREATE TRIGGER abort_write BEFORE UPDATE ON raids BEGIN SELECT RAISE(ABORT, 'forced'); END",
                lambda: db.set_party_count(raid_id, 2),
            ),
            (
                "CREATE TRIGGER abort_write BEFORE DELETE ON raid_signups BEGIN SELECT RAISE(ABORT, 'forced'); END",
                lambda: db.remove_signup(raid_id, "4004"),
            ),
        )
        for trigger, call in cases:
            self._restore(raid_id)
            before = self._rows(raid_id)
            attendance = self._attendance(raid_id)
            conn = sqlite3.connect(config.DB_PATH)
            conn.execute(trigger)
            conn.commit()
            conn.close()
            with self.assertRaises(sqlite3.IntegrityError):
                call()
            self.assertEqual(self._rows(raid_id), before)
            self.assertEqual(self._attendance(raid_id), attendance)
            self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
            self.assertEqual(db.raid_by_id(raid_id)["party_count"], 1)
            conn = sqlite3.connect(config.DB_PATH)
            conn.execute("DROP TRIGGER IF EXISTS abort_write")
            conn.commit()
            conn.close()
            call()

        self._restore(raid_id)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE raids SET party_count = 2 WHERE id = ?", (raid_id,))
        conn.execute(
            "CREATE TRIGGER abort_write BEFORE UPDATE ON raid_signups BEGIN SELECT RAISE(ABORT, 'forced'); END"
        )
        conn.commit()
        conn.close()
        before = self._rows(raid_id)
        attendance = self._attendance(raid_id)
        with self.assertRaises(sqlite3.IntegrityError):
            db.fill_open_parties(raid_id)
        self.assertEqual(self._rows(raid_id), before)
        self.assertEqual(self._attendance(raid_id), attendance)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("DROP TRIGGER IF EXISTS abort_write")
        conn.commit()
        conn.close()
        self.assertTrue(db.fill_open_parties(raid_id))
        self.assertIn(("6006", "healer", "main", 2), self._rows(raid_id))
        self.assertEqual(self._attendance(raid_id), attendance)

    def test_closure_beats_a_waiting_signup_update(self):
        raid_id = self._raid()
        self._seed(raid_id)
        before = self._rows(raid_id)
        self._close_while_blocked(raid_id, "lane", False)
        self.assertEqual(self._rows(raid_id), before)
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

    def test_closure_beats_a_waiting_party_change_fill_and_signup(self):
        raid_id = self._raid()
        self._seed(raid_id)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE raids SET party_count = 2 WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()
        before = self._rows(raid_id)
        self._close_while_blocked(raid_id, "party", False)
        self.assertEqual(db.raid_by_id(raid_id)["party_count"], 2)
        self.assertEqual(self._rows(raid_id), before)
        raid_id = self._raid()
        self._seed(raid_id)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE raids SET party_count = 2 WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()
        before = self._rows(raid_id)
        self._close_while_blocked(raid_id, "fill", False)
        self.assertEqual(self._rows(raid_id), before)
        raid_id = self._raid()
        self._seed(raid_id)
        before = self._rows(raid_id)
        self._close_while_blocked(raid_id, "place", None)
        self.assertEqual(self._rows(raid_id), before)
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

    def test_closure_beats_a_waiting_leave(self):
        raid_id = self._raid()
        self._seed(raid_id)
        before = self._rows(raid_id)
        self._close_while_blocked(raid_id, "leave", False)
        self.assertEqual(self._rows(raid_id), before)
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

    def test_leave_that_holds_the_lock_finishes_before_close(self):
        raid_id = self._raid()
        self._seed(raid_id)
        context = multiprocessing.get_context("spawn")
        seen = context.Event()
        release = context.Event()
        process = context.Process(
            target=_leave_after_status_read,
            args=(config.DB_PATH, raid_id, "4004", seen, release),
        )
        process.start()
        try:
            self.assertTrue(seen.wait(timeout=15))
            probe = sqlite3.connect(config.DB_PATH, timeout=0, isolation_level=None)
            try:
                probe.execute("PRAGMA busy_timeout=0")
                with self.assertRaises(sqlite3.OperationalError):
                    probe.execute("BEGIN IMMEDIATE")
            finally:
                probe.close()
        finally:
            release.set()
            process.join(timeout=15)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        self.assertNotIn("4004", [row[0] for row in self._rows(raid_id)])
        self.assertIn(("5005", "healer", "main", 1), self._rows(raid_id))
        db.close_raid(raid_id)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])
        self.assertFalse(db.remove_signup(raid_id, "5005"))
        self.assertIn(("5005", "healer", "main", 1), self._rows(raid_id))

    def test_discord_leave_responses(self):
        raid_id = self._raid()
        self._seed(raid_id)
        sent, edit = self._answers()
        with patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            wow.handle_component("1001", "4004", "Ada", f"ikl:{raid_id}", None, "i", "t", role_ids=[])
        self.assertEqual(sent, ["Je bent afgemeld."])
        self.assertNotIn("4004", [row[0] for row in self._rows(raid_id)])
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

        sent, edit = self._answers()
        with patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            wow.handle_component("1001", "4004", "Ada", f"ikl:{raid_id}", None, "i", "t", role_ids=[])
        self.assertEqual(sent, ["Je stond niet aangemeld."])

        sent, edit = self._answers()
        db.close_raid(raid_id)
        with patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            wow.handle_component("1001", "5005", "Bea", f"ikl:{raid_id}", None, "i", "t", role_ids=[])
        self.assertEqual(sent, ["Deze raid is gesloten."])
        self.assertIn(("5005", "healer", "main", 1), self._rows(raid_id))

        raid_id = self._raid()
        self._seed(raid_id)
        sent, edit = self._answers()
        with patch.object(wow, "_gate"), patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            db.close_raid(raid_id)
            wow.handle_component("1001", "4004", "Ada", f"ikl:{raid_id}", None, "i", "t", role_ids=[])
        self.assertEqual(sent, ["Deze raid is gesloten."])
        self.assertIn(("4004", "tank", "main", 1), self._rows(raid_id))
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

    def test_absence_form_leave_responses(self):
        raid_id = self._raid()
        self._seed(raid_id)
        sent, edit = self._answers()
        with patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            wow.handle_absence("1001", "4004", "Ada", f"ikx:{raid_id}", "weg", "i", "t", role_ids=[])
        self.assertEqual(sent, ["Je bent afgemeld."])
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

        sent, edit = self._answers()
        with patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            wow.handle_absence("1001", "4004", "Ada", f"ikx:{raid_id}", "weg", "i", "t", role_ids=[])
        self.assertEqual(sent, ["Je stond niet aangemeld."])

        sent, edit = self._answers()
        db.close_raid(raid_id)
        with patch.object(wow.discord_api, "interaction_callback"), patch.object(
            wow.discord_api, "edit_original_interaction", edit
        ):
            wow.handle_absence("1001", "5005", "Bea", f"ikx:{raid_id}", "weg", "i", "t", role_ids=[])
        self.assertEqual(sent, ["Deze raid is gesloten."])
        self.assertIn(("5005", "healer", "main", 1), self._rows(raid_id))
        self.assertEqual(self._attendance(raid_id), [("4004", "Ada", 1)])

    def test_ikes_still_does_not_close_and_posting_stays(self):
        raid_id = self._raid()
        data, _edit = wow._action("1001", "42", "Off", "ikes", [str(raid_id)], None, role_ids=[])
        self.assertEqual(data["content"], "Gesloten.")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        scheduled = self._raid(status="scheduled")
        db.mark_raid_posted(scheduled, "message-1", "111", 0, 0)
        posted = db.raid_by_id(scheduled)
        self.assertEqual(posted["status"], "open")
        self.assertEqual(posted["message_id"], "message-1")
        self.assertTrue(callable(db.mark_raid_posted))
        self.assertEqual(db.close_raid.__code__.co_argcount, 1)

    def test_schema_does_not_require_publication_columns(self):
        conn = db.connect()
        try:
            raid_columns = {row[1] for row in conn.execute("PRAGMA table_info(raids)")}
            signup_columns = {row[1] for row in conn.execute("PRAGMA table_info(raid_signups)")}
            attendance = {row[1] for row in conn.execute("PRAGMA table_info(raid_attendance)")}
        finally:
            conn.close()
        self.assertFalse(PUBLICATION_COLUMNS & raid_columns)
        self.assertTrue({"id", "status", "party_count", "tank_cap", "healer_cap", "dps_cap"} <= raid_columns)
        self.assertTrue({"raid_id", "user_id", "role", "state", "party"} <= signup_columns)
        self.assertTrue({"raid_id", "user_id", "present"} <= attendance)
        source = Path(db.__file__).read_text(encoding="utf-8")
        for column in PUBLICATION_COLUMNS:
            self.assertNotIn(column, source)
        wow_source = Path(wow.__file__).read_text(encoding="utf-8")
        for name in ("apply_close_effects", "_close_from_discord", "publication_pending", "claim_scheduled_posts"):
            self.assertNotIn(name, wow_source)

    def test_only_the_allowed_functions_differ_from_production(self):
        self.assertEqual(Path(db.__file__).resolve(), (ROOT / "ironkeep" / "db.py").resolve())
        self.assertEqual(Path(wow.__file__).resolve(), (ROOT / "ironkeep" / "wow.py").resolve())
        self.assertNotIn("Ironkeep-raid-close-hotfix", str(Path(db.__file__)))
        database = _top_level(Path(db.__file__))
        original = _top_level_text(_head_text("production/ironkeep/db.py"))
        database_defs = {name: body for kind, name, body in database if kind == "def"}
        original_defs = {name: body for kind, name, body in original if kind == "def"}
        self.assertEqual(set(database_defs) - set(original_defs), {"begin_immediate"})
        self.assertEqual(set(original_defs) - set(database_defs), set())
        changed = {name for name in original_defs if original_defs[name] != database_defs[name]}
        self.assertEqual(changed, DB_CHANGED)
        self.assertEqual(
            [item for item in database if item[0] != "def"],
            [item for item in original if item[0] != "def"],
        )
        current = _top_level(Path(wow.__file__))
        previous = _top_level_text(_head_text("production/ironkeep/wow.py"))
        current_defs = {name: body for kind, name, body in current if kind == "def"}
        previous_defs = {name: body for kind, name, body in previous if kind == "def"}
        self.assertEqual(set(current_defs) - set(previous_defs), {"_leave_signup"})
        self.assertEqual(set(previous_defs) - set(current_defs), set())
        changed = {name for name in previous_defs if previous_defs[name] != current_defs[name]}
        self.assertEqual(changed, WOW_CHANGED)
        for name in ("run_schedule", "settle_temp_rooms", "sync_temp_voice"):
            self.assertEqual(current_defs[name], previous_defs[name])
        self.assertEqual(
            [item for item in current if item[0] != "def"],
            [item for item in previous if item[0] != "def"],
        )

    def test_begin_immediate_closes_a_connection_when_the_lock_fails(self):
        closed = []
        real_connect = db.sqlite3.connect

        class Proxy:
            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def execute(self, sql, *params):
                if isinstance(sql, str) and sql.startswith("BEGIN"):
                    raise sqlite3.OperationalError("busy")
                return self._conn.execute(sql, *params)

            def close(self):
                closed.append(config.DB_PATH)
                return self._conn.close()

            def __setattr__(self, key, value):
                if key == "row_factory":
                    self._conn.row_factory = value
                    return
                object.__setattr__(self, key, value)

        def connect(path, *args, **kwargs):
            return Proxy(real_connect(path, *args, **kwargs))

        with patch.object(db.sqlite3, "connect", connect):
            with self.assertRaises(sqlite3.OperationalError):
                db.begin_immediate()
        self.assertEqual(closed, [config.DB_PATH])
        conn = db.begin_immediate()
        conn.rollback()
        conn.close()

    def test_release_files_compile_and_contain_no_database(self):
        for module in (db, wow):
            source = Path(module.__file__).read_text(encoding="utf-8")
            compile(source, module.__file__, "exec")
        names = {path.name for path in (WORKTREE).iterdir()}
        self.assertIn("production", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
