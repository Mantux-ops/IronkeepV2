"""Discord Sluiten closes the saved raid, dungeon, or event.

These tests call the component handler used by the production bot. Discord HTTP
is patched. The database is a temporary file.
"""

import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ironkeep import config, db, discord_api, main, wow

GUILD_ID = "1001"
OTHER_GUILD_ID = "1002"
OFFICER_ID = "2002"
STRANGER_ID = "3003"
PLAYER_ID = "4004"
SIGNUP_ID = "5005"
POSTER_ROLE = "999"
CHANNEL_ID = "111"


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()


class DiscordRaidCloseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous_db = config.DB_PATH
        config.DB_PATH = str(Path(self.temp.name) / "close.sqlite")
        self.addCleanup(self._restore_db)
        self.assertNotIn("ironkeep.db", config.DB_PATH)
        db.init()
        db.upsert_guild(
            GUILD_ID,
            "Ironkeep",
            [{"id": POSTER_ROLE, "name": "Officer"}],
            [{"id": CHANNEL_ID, "name": "raids"}],
            added_by="Officer",
            added_by_id=OFFICER_ID,
        )
        self.guild = db.guild_by_id(GUILD_ID)
        self.assertTrue(db.set_game(self.guild["slug"], "wow"))
        db.save_wow_settings(
            self.guild["slug"],
            CHANNEL_ID,
            [POSTER_ROLE],
            "UTC",
            question_thread=False,
            close_at_start=False,
            reminder="off",
            posted_ahead=1,
        )
        self.guild = db.guild_by_id(GUILD_ID)
        self.order = []
        self.finishes = []
        self.edits = []
        self.archived = []
        self.sends = []
        self.messages = {}
        self.releases = 0
        self.ack_kind = None
        self.record = threading.Lock()
        for mocked in (
            patch("ironkeep.wow.discord_api.interaction_callback", side_effect=self._ack),
            patch("ironkeep.wow.discord_api.edit_original_interaction", side_effect=self._finish),
            patch("ironkeep.wow.discord_api.edit_message", side_effect=self._edit),
            patch("ironkeep.wow.discord_api.archive_thread", side_effect=self._archive),
            patch("ironkeep.wow.discord_api.send_payload", side_effect=self._send),
            patch("ironkeep.wow.discord_api.get_message", side_effect=self._get),
            patch("ironkeep.wow.discord_api.create_public_thread", return_value={"id": "thread"}),
            patch("ironkeep.wow.discord_api.delete_message"),
            patch("ironkeep.wow.discord_api.delete_channel"),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        original_release = wow.release_raids

        def counted_release(guild, now=None):
            with self.record:
                self.releases += 1
            return original_release(guild, now)

        release_patch = patch("ironkeep.wow.release_raids", side_effect=counted_release)
        release_patch.start()
        self.addCleanup(release_patch.stop)

    def _restore_db(self):
        config.DB_PATH = self.previous_db

    def _ack(self, interaction_id, token, *, kind, data=None):
        with self.record:
            self.order.append("ack")
            self.ack_kind = kind

    def _finish(self, token, payload):
        with self.record:
            self.order.append("finish")
            self.finishes.append(payload)

    def _edit(self, channel_id, message_id, payload, files=None):
        with self.record:
            self.order.append("edit")
            self.edits.append(payload)

    def _archive(self, thread_id):
        with self.record:
            self.order.append("archive")
            self.archived.append(thread_id)

    def _send(self, channel_id, payload, files=None):
        with self.record:
            self.order.append("send")
            self.sends.append(channel_id)
            posted = len(self.sends)
            message_id = f"posted-{posted}"
            body = {
                "id": message_id,
                "nonce": (payload or {}).get("nonce"),
                "channel_id": str(channel_id),
            }
            self.messages[message_id] = body
        return body

    def _get(self, channel_id, message_id):
        with self.record:
            found = self.messages.get(str(message_id))
        if found is None:
            raise discord_api.DiscordError(404, {"code": 10008, "message": "Unknown Message"})
        return dict(found)

    def _raid(self, instance_id, title, size):
        raid_id = db.create_raid(
            GUILD_ID,
            title,
            _future(),
            2,
            2,
            6,
            CHANNEL_ID,
            "Officer",
            size,
            instance_id,
            status="open",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        db.set_raid_message(raid_id, f"message-{raid_id}")
        db.set_raid_thread(raid_id, f"thread-{raid_id}")
        raid = db.raid_by_id(raid_id)
        if instance_id == "event":
            db.place_signup(raid, PLAYER_ID, "Ada", "", "", "event", kind="main")
        else:
            db.place_signup(raid, PLAYER_ID, "Ada", "warrior", "protection", "tank", kind="main")
        db.set_attendance(raid_id, PLAYER_ID, "Ada", True)
        return raid_id

    def _click(self, custom_id, user_id=OFFICER_ID, role_ids=None, guild_id=GUILD_ID):
        if role_ids is None:
            role_ids = [POSTER_ROLE]
        wow.handle_component(
            guild_id,
            user_id,
            "Officer",
            custom_id,
            [],
            "interaction-1",
            "secret-token",
            role_ids,
        )

    def _close(self, instance_id, title, size):
        raid_id = self._raid(instance_id, title, size)
        self._click(f"ikes:{raid_id}")
        return raid_id

    def test_officer_closes_raid_dungeon_and_event(self):
        samples = (
            ("barrow-deeps", "Barrow Deeps", 10),
            ("hall-of-thanes", "Hall of Thanes", 5),
            ("event", "Guild meeting", 0),
        )
        for instance_id, title, size in samples:
            with self.subTest(instance_id=instance_id):
                self.order.clear()
                self.finishes.clear()
                self.edits.clear()
                self.archived.clear()
                raid_id = self._close(instance_id, title, size)
                saved = db.raid_by_id(raid_id)
                self.assertEqual(saved["status"], "closed")
                self.assertEqual(self.ack_kind, 6)
                self.assertLess(self.order.index("ack"), self.order.index("edit"))
                self.assertLess(self.order.index("edit"), self.order.index("archive"))
                self.assertEqual(self.edits[-1]["components"], [])
                self.assertIn("Gesloten", self.edits[-1]["embeds"][-1].get("description", ""))
                self.assertEqual(self.finishes[-1]["content"], "Gesloten.")
                self.assertEqual(self.archived, [f"thread-{raid_id}"])
                signups = db.signups_for(raid_id)
                self.assertEqual([row["user_id"] for row in signups], [PLAYER_ID])
                self.assertEqual(db.attendance_for(raid_id), [{"user_id": PLAYER_ID, "name": "Ada", "present": True}])

    def test_signups_after_close_are_rejected(self):
        raid_id = self._close("barrow-deeps", "Barrow Deeps", 10)
        before = len(db.signups_for(raid_id))
        for custom_id in (f"ikt:{raid_id}", f"ikm:{raid_id}", f"ikn:{raid_id}", f"ikh:{raid_id}"):
            with self.subTest(custom_id=custom_id):
                self.finishes.clear()
                self._click(custom_id, user_id=SIGNUP_ID, role_ids=[])
                self.assertEqual(self.finishes[-1]["content"], "Deze raid is gesloten.")
                self.assertEqual(len(db.signups_for(raid_id)), before)

    def test_event_signup_after_close_is_rejected(self):
        raid_id = self._close("event", "Guild meeting", 0)
        before = len(db.signups_for(raid_id))
        self.finishes.clear()
        self._click(f"ikj:{raid_id}", user_id=SIGNUP_ID, role_ids=[])
        self.assertEqual(self.finishes[-1]["content"], "Deze raid is gesloten.")
        self.assertEqual(len(db.signups_for(raid_id)), before)

    def test_repeated_close_is_not_a_new_success(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = db.create_raid(
            GUILD_ID,
            "Next raid",
            _future(),
            2,
            2,
            6,
            CHANNEL_ID,
            "Officer",
            10,
            "hyjal-summit",
            status="scheduled",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        self._click(f"ikes:{raid_id}")
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(self.releases, 1)
        self.finishes.clear()
        self._click(f"ikes:{raid_id}")
        self.assertEqual(self.finishes[-1]["content"], "Deze raid is gesloten.")
        self.assertNotIn("Gesloten.", self.finishes[-1]["content"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")

    def test_unauthorized_and_cross_guild_clicks_do_not_close(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        self._click(f"ikes:{raid_id}", user_id=STRANGER_ID, role_ids=["1"])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        self.assertEqual(self.finishes[-1]["content"], "Je hebt niet de rol die nodig is om een raid aan te passen.")
        self.assertEqual(self.edits, [])
        self.assertEqual(self.releases, 0)
        self.finishes.clear()
        self._click(f"ikes:{raid_id}", guild_id=OTHER_GUILD_ID)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        self.assertEqual(self.finishes[-1]["content"], "Deze raid bestaat niet meer.")
        self.assertEqual(self.releases, 0)

    def test_database_failure_does_not_report_success(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)

        def fail_close(*_args, **_kwargs):
            raise sqlite3.OperationalError("disk")

        with patch("ironkeep.wow.db.close_raid", side_effect=fail_close):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        self.assertEqual(self.finishes[-1]["content"], "Er ging iets mis. Probeer het opnieuw.")
        self.assertNotIn("Gesloten.", self.finishes[-1]["content"])
        self.assertEqual(self.archived, [])
        self.assertEqual(self.releases, 0)
        self.assertEqual(self.sends, [])
        for payload in self.edits:
            self.assertTrue(payload["components"])

    def test_message_failure_keeps_the_closed_raid(self):
        raid_id = self._raid("hall-of-thanes", "Hall of Thanes", 5)
        queued = db.create_raid(
            GUILD_ID,
            "Next dungeon",
            _future(),
            1,
            1,
            3,
            CHANNEL_ID,
            "Officer",
            5,
            "ruins-of-lordaeron",
            status="scheduled",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )

        def fail_edit(channel_id, message_id, payload, files=None):
            self.order.append("edit")
            self.edits.append(payload)
            raise discord_api.DiscordError(500, "down")

        with patch("ironkeep.wow.discord_api.edit_message", side_effect=fail_edit):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        self.assertIn("Gesloten.", self.finishes[-1]["content"])
        self.assertIn("Het bericht in het kanaal kon niet worden bijgewerkt.", self.finishes[-1]["content"])
        self.assertNotIn("Er ging iets mis", self.finishes[-1]["content"])
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(self.sends, [CHANNEL_ID])

    def test_website_close_still_closes_and_releases(self):
        raid_id = self._raid("onyxias-lair", "Onyxia's Lair", 40)
        queued = db.create_raid(
            GUILD_ID,
            "Next raid",
            _future(),
            2,
            2,
            6,
            CHANNEL_ID,
            "Officer",
            40,
            "hyjal-summit",
            status="scheduled",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 9),
            "server": ("test", 80),
        }
        from starlette.requests import Request

        with patch("ironkeep.main.config.live", return_value=True), patch(
            "ironkeep.main.guild_or_404", return_value=(self.guild, None)
        ), patch("ironkeep.main.deny_unless", return_value=None):
            response = main.close_raid_page(self.guild["slug"], raid_id, Request(scope))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/{self.guild['slug']}/raids")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        self.assertEqual(db.attendance_for(raid_id)[0]["present"], True)
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertLess(self.order.index("edit"), self.order.index("archive"))
        self.assertLess(self.order.index("archive"), self.order.index("send"))

    def _queue(self, title, instance_id, size):
        return db.create_raid(
            GUILD_ID,
            title,
            _future(),
            2,
            2,
            6,
            CHANNEL_ID,
            "Officer",
            size,
            instance_id,
            status="scheduled",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )

    def _together(self, first, second):
        errors = []

        def run(action):
            try:
                action()
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=run, args=(action,)) for action in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def _overlap_closes(self, raid_id, queued, first, second):
        """Hold both callers after they see the raid open, and before either close is saved."""
        close_barrier = threading.Barrier(2)
        seen_open = []
        original_close = db.close_raid

        def gated_close(target, guild_id):
            if int(target) == int(raid_id):
                with self.record:
                    seen_open.append(db.raid_by_id(target)["status"])
                close_barrier.wait(timeout=5)
            return original_close(target, guild_id)

        with patch("ironkeep.db.close_raid", side_effect=gated_close):
            self._together(first, second)
        self.assertEqual(seen_open, ["open", "open"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        posted = db.raid_by_id(queued)
        self.assertEqual(posted["status"], "open")
        self.assertTrue(posted["message_id"])
        self.assertIsNone(posted["post_nonce"])
        self.assertIsNone(posted["post_claim_token"])

    def test_concurrent_discord_closes_publish_once(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)
        self._overlap_closes(
            raid_id,
            queued,
            lambda: self._click(f"ikes:{raid_id}"),
            lambda: self._click(f"ikes:{raid_id}"),
        )

    def test_concurrent_discord_and_website_closes_publish_once(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 9),
            "server": ("test", 80),
        }
        from starlette.requests import Request

        def website():
            with patch("ironkeep.main.config.live", return_value=True), patch(
                "ironkeep.main.guild_or_404", return_value=(self.guild, None)
            ), patch("ironkeep.main.deny_unless", return_value=None):
                main.close_raid_page(self.guild["slug"], raid_id, Request(scope))

        self._overlap_closes(raid_id, queued, lambda: self._click(f"ikes:{raid_id}"), website)

    def test_unknown_message_still_archives_and_releases(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)

        def unknown_message(channel_id, message_id, payload, files=None):
            with self.record:
                self.order.append("edit")
                self.edits.append(payload)
            raise discord_api.DiscordError(404, {"code": 10008, "message": "Unknown Message"})

        with patch("ironkeep.wow.discord_api.edit_message", side_effect=unknown_message):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(self.finishes[-1]["content"], "Gesloten.\nHet bericht in het kanaal kon niet worden bijgewerkt.")
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(db.raid_by_id(queued)["status"], "open")

    def test_archive_failure_still_releases(self):
        raid_id = self._raid("hall-of-thanes", "Hall of Thanes", 5)
        queued = self._queue("Next dungeon", "ruins-of-lordaeron", 5)

        def fail_archive(thread_id):
            with self.record:
                self.order.append("archive")
                self.archived.append(thread_id)
            raise discord_api.DiscordError(500, {"message": "down"})

        with patch("ironkeep.wow.discord_api.archive_thread", side_effect=fail_archive):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual(self.finishes[-1]["content"], "Gesloten.\nDe thread kon niet worden gesloten.")
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(db.raid_by_id(queued)["status"], "open")

    def test_release_failure_keeps_the_closed_raid(self):
        raid_id = self._raid("onyxias-lair", "Onyxia's Lair", 40)
        queued = self._queue("Next raid", "hyjal-summit", 40)

        def fail_release(guild, now=None):
            with self.record:
                self.releases += 1
            raise discord_api.DiscordError(500, {"message": "down"})

        with patch("ironkeep.wow.release_raids", side_effect=fail_release):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(queued)["status"], "scheduled")
        self.assertEqual(self.finishes[-1]["content"], "Gesloten.\nDe volgende raid kon niet worden geplaatst.")

    def test_officer_reply_failure_does_not_repeat_close(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)

        def fail_finish(token, payload):
            with self.record:
                self.order.append("finish")
                self.finishes.append(payload)
            raise discord_api.DiscordError(500, {"message": "down"})

        with patch("ironkeep.wow.discord_api.edit_original_interaction", side_effect=fail_finish):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(self.finishes[-1]["content"], "Gesloten.")
        self.assertEqual(len(self.finishes), 1)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.releases, 1)
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")

    def test_close_crash_before_edit_is_reconciled(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)
        self.assertTrue(db.close_raid(raid_id, GUILD_ID))
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 1)
        self.assertEqual(self.edits, [])
        self.assertEqual(self.archived, [])
        self.assertEqual(self.sends, [])
        wow.reconcile_pending_closes(self.guild)
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        wow.reconcile_pending_closes(self.guild)
        self.assertEqual(self.sends, [CHANNEL_ID])

    def test_close_crash_before_archive_is_reconciled(self):
        raid_id = self._raid("hall-of-thanes", "Hall of Thanes", 5)
        queued = self._queue("Next dungeon", "ruins-of-lordaeron", 5)
        self.assertTrue(db.close_raid(raid_id, GUILD_ID))
        wow.edit_public(self.guild, db.raid_by_id(raid_id))
        self.assertEqual(self.archived, [])
        self.assertEqual(self.sends, [])
        wow.reconcile_pending_closes(self.guild)
        self.assertEqual(self.archived, [f"thread-{raid_id}"])
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)

    def test_close_crash_before_release_is_reconciled(self):
        raid_id = self._raid("onyxias-lair", "Onyxia's Lair", 40)
        queued = self._queue("Next raid", "hyjal-summit", 40)
        self.assertTrue(db.close_raid(raid_id, GUILD_ID))
        wow.edit_public(self.guild, db.raid_by_id(raid_id))
        wow.archive_question_thread(db.raid_by_id(raid_id))
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(queued)["status"], "scheduled")
        wow.reconcile_pending_closes(self.guild)
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)
        wow.reconcile_pending_closes(self.guild)
        self.assertEqual(self.sends, [CHANNEL_ID])

    def _pause_first_archive(self):
        started = threading.Event()
        resume = threading.Event()

        def archive(thread_id):
            self._archive(thread_id)
            if not started.is_set():
                started.set()
                resume.wait(timeout=5)

        return started, resume, archive

    def _assert_one_closed_publication(self, raid_id, queued, payloads):
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(set(self.archived), {f"thread-{raid_id}"})
        self.assertTrue(payloads)
        for payload in payloads:
            self.assertEqual(payload["components"], [])
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        self.assertTrue(db.attendance_for(raid_id)[0]["present"])

    def test_scheduler_reconciles_while_discord_winner_is_active(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)
        started, resume, archive = self._pause_first_archive()
        with patch("ironkeep.wow.discord_api.archive_thread", side_effect=archive):
            worker = threading.Thread(target=lambda: self._click(f"ikes:{raid_id}"))
            worker.start()
            self.assertTrue(started.wait(timeout=5))
            wow.reconcile_pending_closes(self.guild)
            resume.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self._assert_one_closed_publication(raid_id, queued, self.edits)

    def test_scheduler_reconciles_while_website_winner_is_active(self):
        raid_id = self._raid("onyxias-lair", "Onyxia's Lair", 40)
        queued = self._queue("Next raid", "hyjal-summit", 40)
        started, resume, archive = self._pause_first_archive()
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 9),
            "server": ("test", 80),
        }
        from starlette.requests import Request

        def website():
            with patch("ironkeep.main.config.live", return_value=True), patch(
                "ironkeep.main.guild_or_404", return_value=(self.guild, None)
            ), patch("ironkeep.main.deny_unless", return_value=None):
                main.close_raid_page(self.guild["slug"], raid_id, Request(scope))

        with patch("ironkeep.wow.discord_api.archive_thread", side_effect=archive):
            worker = threading.Thread(target=website)
            worker.start()
            self.assertTrue(started.wait(timeout=5))
            wow.reconcile_pending_closes(self.guild)
            resume.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self._assert_one_closed_publication(raid_id, queued, self.edits)

    def test_failed_close_effects_remain_recoverable(self):
        raid_id = self._raid("hall-of-thanes", "Hall of Thanes", 5)
        queued = self._queue("Next dungeon", "ruins-of-lordaeron", 5)

        def fail_edit(channel_id, message_id, payload, files=None):
            self._edit(channel_id, message_id, payload, files)
            raise discord_api.DiscordError(500, "down")

        with patch("ironkeep.wow.discord_api.edit_message", side_effect=fail_edit):
            self._click(f"ikes:{raid_id}")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 1)
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        self.assertTrue(db.attendance_for(raid_id)[0]["present"])
        wow.reconcile_pending_closes(self.guild)
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")

    def test_stale_winner_cannot_finish_incomplete_effects(self):
        raid_id = self._raid("barrow-deeps", "Barrow Deeps", 10)
        queued = self._queue("Next raid", "hyjal-summit", 10)
        started, resume, archive = self._pause_first_archive()
        holder = {}
        clears = []
        previous_release = wow.release_raids
        original_clear = db.clear_close_effects

        def click():
            holder["thread"] = threading.current_thread()
            self._click(f"ikes:{raid_id}")

        def release(guild, now=None):
            if threading.current_thread() is holder.get("thread"):
                raise discord_api.DiscordError(500, {"message": "down"})
            return previous_release(guild, now)

        def clear(target, guild_id):
            clears.append(threading.current_thread())
            return original_clear(target, guild_id)

        with patch("ironkeep.wow.discord_api.archive_thread", side_effect=archive), patch(
            "ironkeep.wow.release_raids", side_effect=release
        ), patch("ironkeep.wow.db.clear_close_effects", side_effect=clear):
            worker = threading.Thread(target=click)
            worker.start()
            self.assertTrue(started.wait(timeout=5))
            wow.reconcile_pending_closes(self.guild)
            self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)
            self.assertEqual(clears, [threading.current_thread()])
            resume.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(clears, [threading.current_thread()])
        self.assertEqual(db.raid_by_id(raid_id)["close_effects_pending"], 0)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(self.sends, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(self.edits[-1]["components"], [])
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], [PLAYER_ID])
        self.assertTrue(db.attendance_for(raid_id)[0]["present"])


if __name__ == "__main__":
    unittest.main()
