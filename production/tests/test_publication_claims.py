"""Publication claims for scheduled raids.

Discord HTTP is patched. These tests check the claim this program sends.
They do not prove how Discord treats nonce or enforce_nonce.
"""

import json
import multiprocessing
import os
import sqlite3
import subprocess
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
OFFICER_ID = "2002"
POSTER_ROLE = "999"
CHANNEL_ID = "111"

WORKER = """
import json, os, sys
os.environ["IRONKEEP_DB"] = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from ironkeep import db, wow
guild = db.guild_by_id(sys.argv[3])
action = sys.argv[4]
if action == "claim":
    print(json.dumps(wow.claim_scheduled_posts(guild)))
elif action == "close":
    print(json.dumps(bool(db.close_raid(int(sys.argv[5]), sys.argv[3]))))
elif action == "signup":
    raid = db.raid_by_id(int(sys.argv[5]))
    try:
        state = db.place_signup(raid, sys.argv[6], sys.argv[7], sys.argv[8], sys.argv[9], sys.argv[10], kind=sys.argv[11])
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
    else:
        print(json.dumps({"state": state}))
elif action == "release":
    from ironkeep import discord_api
    folder = sys.argv[5]
    def send(channel_id, payload, files=None):
        with open(os.path.join(folder, "send-%s" % os.getpid()), "w", encoding="utf-8") as handle:
            handle.write(str(channel_id))
        return {"id": "posted-%s" % os.getpid(), "nonce": (payload or {}).get("nonce"), "channel_id": str(channel_id)}
    def get_message(channel_id, message_id):
        return {"id": message_id, "channel_id": str(channel_id)}
    def delete_message(channel_id, message_id):
        with open(os.path.join(folder, "delete-%s" % os.getpid()), "w", encoding="utf-8") as handle:
            handle.write(str(message_id))
    discord_api.send_payload = send
    discord_api.get_message = get_message
    discord_api.edit_message = lambda *args, **kwargs: None
    discord_api.archive_thread = lambda *args, **kwargs: None
    discord_api.create_public_thread = lambda *args, **kwargs: {"id": "thread"}
    discord_api.delete_message = delete_message
    discord_api.delete_channel = lambda *args, **kwargs: None
    print(json.dumps(wow.release_raids(guild) or ""))
elif action == "effects":
    from ironkeep import discord_api
    folder = sys.argv[6]
    def send(channel_id, payload, files=None):
        with open(os.path.join(folder, str(os.getpid())), "w", encoding="utf-8") as handle:
            handle.write("send")
        return {"id": "posted-%s" % os.getpid(), "nonce": (payload or {}).get("nonce")}
    def get_message(channel_id, message_id):
        return {"id": message_id}
    discord_api.send_payload = send
    discord_api.get_message = get_message
    discord_api.edit_message = lambda *args, **kwargs: None
    discord_api.archive_thread = lambda *args, **kwargs: None
    discord_api.create_public_thread = lambda *args, **kwargs: {"id": "thread"}
    discord_api.delete_message = lambda *args, **kwargs: None
    discord_api.delete_channel = lambda *args, **kwargs: None
    raid = db.raid_by_id(int(sys.argv[5]))
    print(json.dumps(wow.apply_close_effects(guild, raid)))
else:
    raise SystemExit(action)
"""


def _signup_after_status_read(db_path, root, raid_id, user_id, seen, release):
    """Run place_signup and pause after the open check, while its write transaction is open."""
    import os
    import sys

    os.environ["IRONKEEP_DB"] = db_path
    sys.path.insert(0, root)
    from ironkeep import config, db

    config.DB_PATH = db_path
    real_begin = db.begin_immediate

    def begin_immediate():
        conn = real_begin()

        class Holding:
            def execute(self, sql, params=()):
                cursor = conn.execute(sql, params)
                if isinstance(sql, str) and "SELECT status FROM raids WHERE id = ?" in sql:
                    seen.set()
                    if not release.wait(timeout=10):
                        raise TimeoutError("signup was not released")
                return cursor

            def commit(self):
                return conn.commit()

            def rollback(self):
                return conn.rollback()

            def close(self):
                return conn.close()

        return Holding()

    db.begin_immediate = begin_immediate
    raid = db.raid_by_id(raid_id)
    db.place_signup(raid, user_id, "Bea", "warrior", "protection", "tank")


def _when(days=3, hours=0):
    moment = datetime.now(timezone.utc) + timedelta(days=days, hours=hours)
    return moment.replace(microsecond=0).isoformat()


class PublicationClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous_db = config.DB_PATH
        config.DB_PATH = str(Path(self.temp.name) / "claims.sqlite")
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
        self.sends = []
        self.record = threading.Lock()
        wow._reported_recovery.clear()
        for mocked in (
            patch("ironkeep.wow.discord_api.send_payload", side_effect=self._send),
            patch("ironkeep.wow.discord_api.get_message", side_effect=self._get),
            patch("ironkeep.wow.discord_api.edit_message"),
            patch("ironkeep.wow.discord_api.archive_thread"),
            patch("ironkeep.wow.discord_api.delete_message"),
            patch("ironkeep.wow.discord_api.delete_channel"),
            patch("ironkeep.wow.discord_api.create_public_thread", return_value={"id": "thread"}),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def _restore_db(self):
        config.DB_PATH = self.previous_db

    def _send(self, channel_id, payload, files=None):
        with self.record:
            self.sends.append({"channel_id": channel_id, "payload": dict(payload)})
            message_id = f"posted-{len(self.sends)}"
            body = {"id": message_id, "nonce": payload.get("nonce"), "channel_id": str(channel_id)}
        return body

    def _get(self, channel_id, message_id):
        with self.record:
            for sent in self.sends:
                if sent["payload"].get("nonce") and message_id == f"posted-{self.sends.index(sent) + 1}":
                    return {"id": message_id, "nonce": sent["payload"]["nonce"], "channel_id": str(channel_id)}
        raise discord_api.DiscordError(404, {"code": 10008, "message": "Unknown Message"})

    def _retarget(self, channel):
        db.save_wow_settings(
            self.guild["slug"],
            channel,
            [POSTER_ROLE],
            "UTC",
            question_thread=False,
            close_at_start=False,
            reminder="off",
            posted_ahead=1,
        )
        self.guild = db.guild_by_id(GUILD_ID)

    def _ahead(self, count, channel=CHANNEL_ID, mode="one", dungeon=None):
        db.save_wow_settings(
            self.guild["slug"],
            channel,
            [POSTER_ROLE],
            "UTC",
            channel_mode=mode,
            dungeon_channel=dungeon,
            question_thread=False,
            close_at_start=False,
            reminder="off",
            posted_ahead=count,
        )
        self.guild = db.guild_by_id(GUILD_ID)

    def _mark_recovery(self, raid_id, nonce="held-nonce", channel=CHANNEL_ID):
        conn = db.connect()
        conn.execute(
            """UPDATE raids
               SET channel_id = ?, post_nonce = ?, post_nonce_at = ?,
                   post_recovery_required = 1, post_repost_blocked = 1,
                   post_claimed_at = NULL, post_claim_token = NULL, message_id = NULL
               WHERE id = ?""",
            (channel, nonce, "2026-11-14T00:00:00+00:00", raid_id),
        )
        conn.commit()
        conn.close()

    def _signup_buttons(self, raid_id):
        return wow._action_rows(raid_id)

    def _publication_state(self, raid_id):
        row = db.raid_by_id(raid_id)
        return (
            row["status"],
            row["channel_id"],
            row["message_id"],
            row["post_nonce"],
            row["post_recovery_required"],
            row["post_repost_blocked"],
            row["post_claim_token"],
        )

    def _scheduled(self, title, days=3, hours=0):
        return db.create_raid(
            GUILD_ID,
            title,
            _when(days, hours),
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

    def _open(self, title, when):
        raid_id = db.create_raid(
            GUILD_ID,
            title,
            when,
            2,
            2,
            6,
            CHANNEL_ID,
            "Officer",
            10,
            "barrow-deeps",
            status="open",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        db.set_raid_message(raid_id, f"message-{raid_id}")
        return raid_id

    def _processes(self, action, raid_id=None):
        args = [sys.executable, "-c", WORKER, config.DB_PATH, str(ROOT), GUILD_ID, action]
        if raid_id is not None:
            args.append(str(raid_id))
        env = os.environ.copy()
        env["IRONKEEP_DB"] = config.DB_PATH
        procs = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(2)]
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode, 0, err)
            results.append(json.loads(out))
        return results

    def test_cross_process_close_happens_once(self):
        raid_id = self._open("Open raid", _when())
        results = self._processes("close", raid_id)
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(db.signups_for(raid_id), [])

    def _one(self, action, *args):
        command = [sys.executable, "-c", WORKER, config.DB_PATH, str(ROOT), GUILD_ID, action, *[str(arg) for arg in args]]
        env = os.environ.copy()
        env["IRONKEEP_DB"] = config.DB_PATH
        completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def _open_kind(self, title, instance_id, size, caps):
        raid_id = db.create_raid(
            GUILD_ID,
            title,
            _when(),
            caps[0],
            caps[1],
            caps[2],
            CHANNEL_ID,
            "Officer",
            size,
            instance_id,
            status="open",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        db.set_raid_message(raid_id, f"message-{raid_id}")
        return raid_id

    def test_close_before_signup_leaves_the_raid_closed(self):
        samples = (
            ("raid", "barrow-deeps", 10, (2, 2, 6), "warrior", "protection", "tank", "main", wow._enroll, "Deze raid is gesloten."),
            ("dungeon", "hall-of-thanes", 5, (1, 1, 3), "warrior", "protection", "tank", "main", wow._enroll, "Deze raid is gesloten."),
            ("event", "event", 0, (0, 0, 0), "", "", "event", "main", wow._enroll_event, "Dit event is gesloten."),
        )
        for label, instance_id, size, caps, class_id, spec_id, role, kind, caller, message in samples:
            with self.subTest(kind=label):
                raid_id = self._open_kind(label, instance_id, size, caps)
                self.assertIs(self._one("close", raid_id), True)
                saved = self._one("signup", raid_id, "5005", "Bea", class_id, spec_id, role, kind)
                self.assertEqual(saved, {"state": None})
                self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
                self.assertNotIn("5005", [row["user_id"] for row in db.signups_for(raid_id)])
                raid = db.raid_by_id(raid_id)
                with self.assertRaises(wow.PlayerMessage) as raised:
                    if caller is wow._enroll:
                        caller(self.guild, raid, "5005", "Bea", class_id, spec_id, role, kind)
                    else:
                        caller(self.guild, raid, "5005", "Bea", kind)
                self.assertEqual(str(raised.exception), message)

    def test_signup_before_close_remains_stored(self):
        samples = (
            ("raid", "barrow-deeps", 10, (2, 2, 6), "warrior", "protection", "tank", "main"),
            ("dungeon", "hall-of-thanes", 5, (1, 1, 3), "warrior", "protection", "tank", "main"),
            ("event", "event", 0, (0, 0, 0), "", "", "event", "main"),
        )
        for label, instance_id, size, caps, class_id, spec_id, role, kind in samples:
            with self.subTest(kind=label):
                raid_id = self._open_kind(label, instance_id, size, caps)
                saved = self._one("signup", raid_id, "5005", "Bea", class_id, spec_id, role, kind)
                self.assertEqual(saved, {"state": "main"})
                self.assertIs(self._one("close", raid_id), True)
                self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
                stored = [row for row in db.signups_for(raid_id) if row["user_id"] == "5005"]
                self.assertEqual([(row["name"], row["role"], row["state"]) for row in stored], [("Bea", role, "main")])

    def test_closed_raid_does_not_rewrite_an_existing_signup(self):
        raid_id = self._open("Keep", _when())
        self.assertEqual(db.place_signup(db.raid_by_id(raid_id), "4004", "Ada", "warrior", "protection", "tank"), "main")
        before = [(row["user_id"], row["name"], row["role"], row["state"]) for row in db.signups_for(raid_id)]
        self.assertTrue(db.close_raid(raid_id, GUILD_ID))
        self.assertIsNone(db.place_signup(db.raid_by_id(raid_id), "4004", "Bea", "mage", "fire", "ranged"))
        self.assertEqual(
            [(row["user_id"], row["name"], row["role"], row["state"]) for row in db.signups_for(raid_id)],
            before,
        )
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")

    def test_stale_open_read_cannot_insert_after_closure(self):
        raid_id = self._open("Overlap", _when())
        context = multiprocessing.get_context("spawn")
        seen = context.Event()
        release = context.Event()
        process = context.Process(
            target=_signup_after_status_read,
            args=(config.DB_PATH, str(ROOT), raid_id, "5005", seen, release),
        )
        previous_cache = os.environ.get("IRONKEEP_COMPANION_CACHE")
        previous_catalog = os.environ.get("IRONKEEP_WOW_CATALOG")
        os.environ["IRONKEEP_COMPANION_CACHE"] = str(ROOT / "tests" / "fixtures" / "forever.json")
        os.environ["IRONKEEP_WOW_CATALOG"] = str(ROOT / "tests" / "fixtures" / "wow.json")
        process.start()
        if previous_cache is None:
            os.environ.pop("IRONKEEP_COMPANION_CACHE", None)
        else:
            os.environ["IRONKEEP_COMPANION_CACHE"] = previous_cache
        if previous_catalog is None:
            os.environ.pop("IRONKEEP_WOW_CATALOG", None)
        else:
            os.environ["IRONKEEP_WOW_CATALOG"] = previous_catalog
        try:
            self.assertTrue(seen.wait(timeout=20))
            probe = sqlite3.connect(config.DB_PATH, timeout=0, isolation_level=None)
            try:
                probe.execute("PRAGMA busy_timeout=0")
                with self.assertRaises(sqlite3.OperationalError):
                    probe.execute("BEGIN IMMEDIATE")
            finally:
                probe.close()
            reader = sqlite3.connect(config.DB_PATH, timeout=5)
            try:
                self.assertEqual(reader.execute("SELECT status FROM raids WHERE id = ?", (raid_id,)).fetchone()[0], "open")
            finally:
                reader.close()
        finally:
            release.set()
            process.join(timeout=15)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        self.assertEqual(
            [(row["user_id"], row["name"], row["state"]) for row in db.signups_for(raid_id)],
            [("5005", "Bea", "main")],
        )
        self.assertTrue(db.close_raid(raid_id, GUILD_ID))
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual([row["user_id"] for row in db.signups_for(raid_id)], ["5005"])

    def test_cross_process_claims_one_owner_and_one_slot(self):
        earlier = self._scheduled("Earlier", days=2)
        later = self._scheduled("Later", days=4)
        results = self._processes("claim")
        claims = [claim for batch in results for claim in batch]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["id"], earlier)
        saved_earlier = db.raid_by_id(earlier)
        saved_later = db.raid_by_id(later)
        self.assertEqual(saved_earlier["status"], "scheduled")
        self.assertEqual(saved_earlier["post_claim_token"], claims[0]["token"])
        self.assertEqual(saved_earlier["post_nonce"], claims[0]["nonce"])
        self.assertIsNone(saved_later["post_nonce"])
        self.assertIsNone(saved_later["post_claim_token"])

    def test_threads_claim_one_owner(self):
        raid_id = self._scheduled("Only")
        barrier = threading.Barrier(2)
        found = []
        errors = []
        original = wow.claim_scheduled_posts

        def claim():
            try:
                barrier.wait(timeout=5)
                found.append(original(self.guild))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        claims = [claim for batch in found for claim in batch]
        self.assertEqual(len(claims), 1)
        self.assertEqual(db.raid_by_id(raid_id)["post_claim_token"], claims[0]["token"])

    def test_competing_raids_fill_one_slot(self):
        earlier = self._scheduled("Earlier", days=2)
        later = self._scheduled("Later", days=5)
        barrier = threading.Barrier(2)
        original = wow.release_raids

        def release():
            barrier.wait(timeout=5)
            original(self.guild)

        threads = [threading.Thread(target=release) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.sends), 1)
        self.assertTrue(self.sends[0]["payload"]["enforce_nonce"])
        self.assertLessEqual(len(self.sends[0]["payload"]["nonce"]), 25)
        self.assertEqual(db.raid_by_id(earlier)["status"], "open")
        self.assertEqual(db.raid_by_id(earlier)["message_id"], "posted-1")
        self.assertIsNone(db.raid_by_id(earlier)["post_nonce"])
        self.assertEqual(db.raid_by_id(later)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(later)["post_nonce"])

    def test_scheduler_and_close_release_once(self):
        open_id = self._open("Current", _when(days=-1))
        queued = self._scheduled("Next", days=2)
        barrier = threading.Barrier(2)
        original = wow.release_raids

        def gated(guild, now=None):
            barrier.wait(timeout=5)
            return original(guild, now)

        def close():
            wow._close_from_discord(self.guild, db.raid_by_id(open_id))

        def scheduler():
            wow.release_raids(self.guild)

        with patch("ironkeep.wow.release_raids", side_effect=gated):
            threads = [threading.Thread(target=close), threading.Thread(target=scheduler)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
        self.assertEqual(db.raid_by_id(open_id)["status"], "closed")
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertEqual(self.sends[0]["payload"]["nonce"], db.raid_by_id(queued)["post_nonce"] or self.sends[0]["payload"]["nonce"])
        self.assertIsNone(db.raid_by_id(queued)["post_claim_token"])

    def test_two_closes_publish_the_same_queued_raid_once(self):
        first = self._open("One", _when(days=-1))
        second = self._open("Two", _when(days=-1, hours=1))
        queued = self._scheduled("Next", days=2)
        barrier = threading.Barrier(2)
        original = wow.release_raids

        def gated(guild, now=None):
            barrier.wait(timeout=5)
            return original(guild, now)

        def close(raid_id):
            wow._close_from_discord(self.guild, db.raid_by_id(raid_id))

        with patch("ironkeep.wow.release_raids", side_effect=gated):
            threads = [
                threading.Thread(target=close, args=(first,)),
                threading.Thread(target=close, args=(second,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
        self.assertEqual(db.raid_by_id(first)["status"], "closed")
        self.assertEqual(db.raid_by_id(second)["status"], "closed")
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(db.raid_by_id(queued)["status"], "open")

    def test_stale_owner_cannot_finish_or_release(self):
        raid_id = self._scheduled("Only")
        now = datetime.now(timezone.utc)
        first = wow.claim_scheduled_posts(self.guild, now)[0]
        later = now + timedelta(seconds=db.PUBLICATION_REQUEST_BUDGET_SECONDS + 5)
        self.assertEqual(wow.claim_scheduled_posts(self.guild, later), [])
        self.assertFalse(db.finish_publication(raid_id, GUILD_ID, first["token"], "stale", CHANNEL_ID))
        self.assertFalse(db.release_publication_claim(raid_id, GUILD_ID, first["token"]))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["status"], "scheduled")
        self.assertIsNone(saved["post_claim_token"])
        self.assertEqual(saved["post_nonce"], first["nonce"])
        self.assertEqual(saved["post_repost_blocked"], 1)
        self.assertIsNone(saved["message_id"])
        self.assertEqual(self.sends, [])

    def test_definitive_rejection_keeps_the_nonce_for_one_retry(self):
        raid_id = self._scheduled("Only")
        nonces = []

        def send(channel_id, payload, files=None):
            nonces.append(payload["nonce"])
            if len(nonces) == 1:
                raise discord_api.DiscordError(403, {"code": 50013, "message": "Missing Permissions"})
            return {"id": "posted-1", "nonce": payload["nonce"]}

        def get_message(channel_id, message_id):
            return {"id": message_id, "nonce": nonces[-1]}

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send), patch(
            "ironkeep.wow.discord_api.get_message", side_effect=get_message
        ):
            self.assertEqual(wow.release_raids(self.guild), "discord")
            refused = db.raid_by_id(raid_id)
            self.assertEqual(refused["status"], "scheduled")
            self.assertEqual(refused["post_nonce"], nonces[0])
            self.assertIsNone(refused["post_claim_token"])
            self.assertIsNone(wow.release_raids(self.guild))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["status"], "open")
        self.assertEqual(saved["message_id"], "posted-1")
        self.assertEqual(nonces, [nonces[0], nonces[0]])

    def test_lost_response_stops_automatic_retries(self):
        raid_id = self._scheduled("Only")
        nxt = self._scheduled("Next", days=5)
        now = datetime.now(timezone.utc)
        nonces = []

        def fail_send(channel_id, payload, files=None):
            nonces.append(payload["nonce"])
            raise OSError("reset")

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=fail_send):
            self.assertEqual(wow.release_raids(self.guild, now), "discord")
        waiting = db.raid_by_id(raid_id)
        self.assertEqual(waiting["status"], "scheduled")
        self.assertEqual(waiting["post_nonce"], nonces[0])
        self.assertEqual(waiting["post_recovery_required"], 1)
        self.assertEqual(waiting["post_repost_blocked"], 1)
        self.assertIsNone(waiting["post_claim_token"])
        self.assertIsNone(waiting["message_id"])
        later = now + timedelta(seconds=db.PUBLICATION_REQUEST_BUDGET_SECONDS + 5)

        def send(channel_id, payload, files=None):
            nonces.append(payload["nonce"])
            return {"id": "recovered", "nonce": payload["nonce"]}

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send):
            self.assertIsNone(wow.release_raids(self.guild, later))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(nonces, [nonces[0]])
        self.assertEqual(saved["status"], "scheduled")
        self.assertEqual(saved["post_nonce"], nonces[0])
        self.assertEqual(saved["post_repost_blocked"], 1)
        self.assertIsNone(saved["message_id"])
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(nxt)["post_nonce"])

    def test_database_failure_after_accept_keeps_the_claim(self):
        raid_id = self._scheduled("Only")
        now = datetime.now(timezone.utc)

        calls = []

        def send(channel_id, payload, files=None):
            return {"id": "accepted", "nonce": payload["nonce"]}

        def get_message(channel_id, message_id):
            return {"id": message_id, "nonce": send.nonce}

        def remember(channel_id, payload, files=None):
            calls.append(payload["nonce"])
            send.nonce = payload["nonce"]
            return send(channel_id, payload, files)

        def fail_finish(*_args, **_kwargs):
            raise sqlite3.OperationalError("disk")

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=remember), patch(
            "ironkeep.wow.discord_api.get_message", side_effect=get_message
        ), patch("ironkeep.wow.db.finish_publication", side_effect=fail_finish):
            self.assertEqual(wow.release_raids(self.guild, now), "discord")
        waiting = db.raid_by_id(raid_id)
        self.assertEqual(waiting["status"], "scheduled")
        self.assertEqual(waiting["post_nonce"], send.nonce)
        self.assertEqual(waiting["message_id"], "accepted")
        self.assertTrue(waiting["post_claim_token"])
        later = now + timedelta(seconds=db.PUBLICATION_REQUEST_BUDGET_SECONDS + 5)
        with patch("ironkeep.wow.discord_api.send_payload", side_effect=remember), patch(
            "ironkeep.wow.discord_api.get_message", side_effect=get_message
        ):
            self.assertIsNone(wow.release_raids(self.guild, later))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(calls, [send.nonce])
        self.assertEqual(saved["status"], "open")
        self.assertEqual(saved["message_id"], "accepted")
        self.assertIsNone(saved["post_nonce"])

    def test_expired_nonce_stops_automatic_publication(self):
        raid_id = self._scheduled("Only")
        old = wow._stamp(datetime.now(timezone.utc) - timedelta(seconds=db.PUBLICATION_NONCE_REUSE_SECONDS + 60))
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            """UPDATE raids
               SET post_nonce = ?, post_nonce_at = ?, post_claimed_at = ?, post_claim_token = ?
               WHERE id = ?""",
            ("stable-nonce", old, old, "old-token", raid_id),
        )
        conn.commit()
        conn.close()
        with self.assertLogs("ironkeep.wow", level="ERROR") as logs:
            self.assertIsNone(wow.release_raids(self.guild))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["status"], "scheduled")
        self.assertEqual(saved["post_nonce"], "stable-nonce")
        self.assertEqual(saved["post_recovery_required"], 1)
        self.assertIsNone(saved["message_id"])
        self.assertEqual(self.sends, [])
        self.assertIn("manual publication recovery", logs.output[0])
        self.assertIn("attach_verified_publication", logs.output[0])
        self.assertIn("Do not clear post_repost_blocked", logs.output[0])
        self.assertNotIn("allow one new post", logs.output[0])
        self.assertIn(str(raid_id), logs.output[0])
        wow.release_raids(self.guild)
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(raid_id)["post_nonce"], "stable-nonce")

    def test_missing_recovered_message_does_not_mint_a_nonce(self):
        raid_id = self._scheduled("Only")
        nonces = []

        def send(channel_id, payload, files=None):
            nonces.append(payload["nonce"])
            return {"id": "deleted", "nonce": payload["nonce"]}

        def missing(channel_id, message_id):
            raise discord_api.DiscordError(404, {"code": 10008, "message": "Unknown Message"})

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send), patch(
            "ironkeep.wow.discord_api.get_message", side_effect=missing
        ):
            self.assertEqual(wow.release_raids(self.guild), "discord")
            self.assertEqual(wow.release_raids(self.guild), None)
        saved = db.raid_by_id(raid_id)
        self.assertEqual(nonces, [nonces[0]])
        self.assertEqual(saved["post_nonce"], nonces[0])
        self.assertEqual(saved["post_recovery_required"], 1)
        self.assertEqual(saved["status"], "scheduled")
        self.assertIsNone(saved["message_id"])

    def test_publication_blocks_cancel_delete_edit_and_hold(self):
        raid_id = self._scheduled("Only")
        claim = wow.claim_scheduled_posts(self.guild)[0]
        self.assertFalse(db.close_scheduled_raid(raid_id, GUILD_ID))
        self.assertFalse(db.delete_raid(raid_id, GUILD_ID))
        self.assertFalse(db.hold_raid(raid_id))
        current = db.raid_by_id(raid_id)
        self.assertFalse(
            db.update_raid(raid_id, GUILD_ID, current["starts_at"], 2, 2, 6, "changed", None)
        )
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["status"], "scheduled")
        self.assertEqual(saved["post_claim_token"], claim["token"])
        self.assertIsNone(saved["note"])
        self.assertEqual(db.signups_for(raid_id), [])
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
            closed = main.close_raid_page(self.guild["slug"], raid_id, Request(scope))
            removed = main.delete_raid_page(self.guild["slug"], raid_id, Request(scope))
        self.assertIn("error=publishing", closed.headers["location"])
        self.assertIn("error=publishing", removed.headers["location"])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "scheduled")
        self.assertEqual(self.sends, [])

    def test_unresolved_publication_blocks_the_next_raid(self):
        stuck = self._scheduled("Stuck", days=-1)
        nxt = self._scheduled("Next", days=2)
        old = wow._stamp(datetime.now(timezone.utc) - timedelta(minutes=5))
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            """UPDATE raids
               SET post_nonce = ?, post_nonce_at = ?, post_claimed_at = ?, post_claim_token = ?,
                   post_recovery_required = 1
               WHERE id = ?""",
            ("stuck-nonce", old, None, None, stuck),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(stuck)["status"], "scheduled")
        self.assertEqual(db.raid_by_id(stuck)["post_nonce"], "stuck-nonce")
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(nxt)["post_nonce"])

    def test_clearing_nonce_does_not_authorize_a_second_post(self):
        raid_id = self._scheduled("Only")
        nxt = self._scheduled("Next", days=5)
        now = datetime.now(timezone.utc)
        claim = wow.claim_scheduled_posts(self.guild, now)[0]
        later = now + timedelta(seconds=db.PUBLICATION_NONCE_REUSE_SECONDS + 30)
        self.assertEqual(wow.claim_scheduled_posts(self.guild, later), [])
        self.assertEqual(db.raid_by_id(raid_id)["post_repost_blocked"], 1)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            """UPDATE raids
               SET post_nonce = NULL, post_nonce_at = NULL, post_claimed_at = NULL,
                   post_claim_token = NULL, post_recovery_required = 0
               WHERE id = ?""",
            (raid_id,),
        )
        conn.commit()
        conn.close()
        self.assertFalse(db.finish_publication(raid_id, GUILD_ID, claim["token"], "late", CHANNEL_ID))
        self.assertIsNone(wow.release_raids(self.guild, later))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(self.sends, [])
        self.assertEqual(saved["status"], "scheduled")
        self.assertIsNone(saved["message_id"])
        self.assertIsNone(saved["post_nonce"])
        self.assertEqual(saved["post_repost_blocked"], 1)
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(nxt)["post_nonce"])

    def test_inflight_create_is_not_sent_again(self):
        raid_id = self._scheduled("Only")
        nxt = self._scheduled("Next", days=5)
        started = threading.Event()
        resume = threading.Event()

        def send(channel_id, payload, files=None):
            body = self._send(channel_id, payload, files)
            if not started.is_set():
                started.set()
                self.assertTrue(resume.wait(timeout=5))
            return body

        def run():
            wow.release_raids(self.guild)

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send):
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(started.wait(timeout=5))
            self.assertIsNone(wow.release_raids(self.guild))
            resume.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(nxt)["post_nonce"])

    def test_expired_inflight_claim_enters_sticky_recovery(self):
        raid_id = self._scheduled("Only")
        nxt = self._scheduled("Next", days=5)
        now = datetime.now(timezone.utc)
        claim = wow.claim_scheduled_posts(self.guild, now)[0]
        stale = wow._stamp(now - timedelta(seconds=db.PUBLICATION_REQUEST_BUDGET_SECONDS + 5))
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE raids SET post_claimed_at = ? WHERE id = ?", (stale, raid_id))
        conn.commit()
        conn.close()
        later = now + timedelta(seconds=db.PUBLICATION_REQUEST_BUDGET_SECONDS + 5)
        self.assertIsNone(wow.release_raids(self.guild, later))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(self.sends, [])
        self.assertEqual(saved["status"], "scheduled")
        self.assertEqual(saved["post_nonce"], claim["nonce"])
        self.assertEqual(saved["post_recovery_required"], 1)
        self.assertEqual(saved["post_repost_blocked"], 1)
        self.assertIsNone(saved["message_id"])
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")

    def test_server_error_enters_sticky_recovery(self):
        raid_id = self._scheduled("Only")
        attempts = []

        def send(channel_id, payload, files=None):
            attempts.append(payload["nonce"])
            raise discord_api.DiscordError(500, {"message": "down"})

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send):
            self.assertEqual(wow.release_raids(self.guild), "discord")
            self.assertIsNone(wow.release_raids(self.guild))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(attempts, [attempts[0]])
        self.assertEqual(saved["post_nonce"], attempts[0])
        self.assertEqual(saved["post_recovery_required"], 1)
        self.assertEqual(saved["post_repost_blocked"], 1)
        self.assertEqual(saved["status"], "scheduled")
        self.assertIsNone(saved["message_id"])

    def test_observed_message_is_reconciled_without_reposting(self):
        raid_id = self._scheduled("Only")
        claim = wow.claim_scheduled_posts(self.guild)[0]
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            "UPDATE raids SET message_id = ?, channel_id = ? WHERE id = ?",
            ("seen-1", CHANNEL_ID, raid_id),
        )
        conn.commit()
        conn.close()

        def get_message(channel_id, message_id):
            return {"id": message_id, "nonce": claim["nonce"]}

        with patch("ironkeep.wow.discord_api.get_message", side_effect=get_message):
            self.assertIsNone(wow.release_raids(self.guild))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(self.sends, [])
        self.assertEqual(saved["status"], "open")
        self.assertEqual(saved["message_id"], "seen-1")
        self.assertIsNone(saved["post_nonce"])
        self.assertEqual(saved["post_repost_blocked"], 0)

    def test_cross_process_close_effects_publish_one_raid(self):
        open_id = self._open("Current", _when(days=1))
        queued = self._scheduled("Next", days=2)
        raid = db.raid_by_id(open_id)
        db.place_signup(raid, "4004", "Ada", "warrior", "protection", "tank", kind="main")
        db.set_attendance(open_id, "4004", "Ada", True)
        db.set_raid_thread(open_id, "thread-1")
        self.assertTrue(db.close_raid(open_id, GUILD_ID))
        folder = Path(self.temp.name) / "sends"
        folder.mkdir()
        args = [sys.executable, "-c", WORKER, config.DB_PATH, str(ROOT), GUILD_ID, "effects", str(open_id), str(folder)]
        env = os.environ.copy()
        env["IRONKEEP_DB"] = config.DB_PATH
        procs = [
            subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            for _ in range(2)
        ]
        for proc in procs:
            _out, err = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode, 0, err)
        sends = list(folder.iterdir())
        self.assertEqual(len(sends), 1)
        self.assertEqual(db.raid_by_id(open_id)["status"], "closed")
        self.assertEqual(db.raid_by_id(open_id)["close_effects_pending"], 0)
        self.assertEqual(db.raid_by_id(queued)["status"], "open")
        self.assertTrue(db.raid_by_id(queued)["message_id"])
        self.assertEqual([row["user_id"] for row in db.signups_for(open_id)], ["4004"])
        self.assertTrue(db.attendance_for(open_id)[0]["present"])

    def test_past_scheduled_raid_is_still_cancelled_without_a_post(self):
        raid_id = self._scheduled("Late", days=-1)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(db.raid_by_id(raid_id)["status"], "closed")
        self.assertEqual(self.sends, [])

    def test_wrong_guild_cannot_close(self):
        raid_id = self._open("Open", _when())
        self.assertFalse(db.close_raid(raid_id, "9999"))
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")

    def test_guild_delete_keeps_an_unresolved_publication(self):
        raid_id = self._scheduled("Held")
        conn = db.connect()
        conn.execute(
            "UPDATE raids SET post_nonce = ?, post_recovery_required = 1, post_repost_blocked = 1 WHERE id = ?",
            ("held-nonce", raid_id),
        )
        conn.commit()
        conn.close()
        self.assertTrue(db.guild_has_unresolved_publication(self.guild["slug"]))
        self.assertIs(db.delete_guild(self.guild["slug"]), False)
        self.assertEqual(db.raid_by_id(raid_id)["post_nonce"], "held-nonce")
        self.assertIsNotNone(db.guild_by_id(GUILD_ID))

    def test_guild_delete_removes_an_idle_guild(self):
        self._open("Open", _when())
        self.assertIs(db.delete_guild(self.guild["slug"]), True)
        self.assertIsNone(db.guild_by_id(GUILD_ID))

    def test_verified_attach_requires_guild_channel_owner_and_nonce(self):
        raid_id = self._scheduled("Recover")
        conn = db.connect()
        conn.execute(
            "UPDATE raids SET post_nonce = ?, post_recovery_required = 1, post_repost_blocked = 1 WHERE id = ?",
            ("nonce-1", raid_id),
        )
        conn.commit()
        conn.close()
        body = {
            "id": "900",
            "channel_id": CHANNEL_ID,
            "nonce": "nonce-1",
            "author": {"id": "bot-1"},
            "components": self._signup_buttons(raid_id),
        }
        with patch("ironkeep.wow.discord_api.get_message", return_value=dict(body)), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            self.assertEqual(wow.attach_verified_publication("9999", raid_id, "900"), "guild")
            wrong = dict(body, nonce="other")
            with patch("ironkeep.wow.discord_api.get_message", return_value=wrong):
                self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), "nonce")
            stranger = dict(body, author={"id": "someone-else"})
            with patch("ironkeep.wow.discord_api.get_message", return_value=stranger):
                self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), "owner")
            fetched = {key: value for key, value in body.items() if key != "nonce"}
            with patch("ironkeep.wow.discord_api.get_message", return_value=fetched):
                self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), None)
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["status"], "open")
        self.assertEqual(saved["message_id"], "900")
        self.assertEqual(saved["channel_id"], CHANNEL_ID)
        self.assertEqual(saved["post_nonce"], None)
        self.assertEqual(saved["post_repost_blocked"], 0)
        self.assertEqual(self.sends, [])
        second = self._scheduled("Recover with nonce")
        conn = db.connect()
        conn.execute(
            "UPDATE raids SET post_nonce = ?, post_recovery_required = 1, post_repost_blocked = 1 WHERE id = ?",
            ("nonce-2", second),
        )
        conn.commit()
        conn.close()
        matched = {
            "id": "901",
            "channel_id": CHANNEL_ID,
            "nonce": "nonce-2",
            "author": {"id": "bot-1"},
            "components": self._signup_buttons(second),
        }
        with patch("ironkeep.wow.discord_api.get_message", return_value=matched), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            self.assertIsNone(wow.attach_verified_publication(GUILD_ID, second, "901"))
        self.assertEqual(db.raid_by_id(second)["message_id"], "901")
        self.assertEqual(self.sends, [])

    def test_unresolved_publication_does_not_block_a_new_channel(self):
        stuck = self._scheduled("Stuck", days=1)
        fresh = self._scheduled("Fresh", days=2)
        self._mark_recovery(stuck, channel=CHANNEL_ID)
        self._retarget("222")
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual([item["channel_id"] for item in self.sends], ["222"])
        self.assertEqual(db.raid_by_id(fresh)["status"], "open")
        self.assertEqual(db.raid_by_id(fresh)["channel_id"], "222")
        self.assertEqual(db.raid_by_id(stuck)["channel_id"], CHANNEL_ID)
        self.assertEqual(db.raid_by_id(stuck)["post_recovery_required"], 1)
        self.assertEqual(db.raid_by_id(stuck)["post_repost_blocked"], 1)
        self.assertEqual(db.raid_by_id(stuck)["status"], "scheduled")

    def test_original_channel_stays_blocked(self):
        stuck = self._scheduled("Stuck", days=1)
        waiting = self._scheduled("Waiting", days=2)
        self._mark_recovery(stuck, channel=CHANNEL_ID)
        self.assertEqual(wow.release_raids(self.guild), None)
        self.assertEqual(self.sends, [])
        self.assertIsNone(db.raid_by_id(waiting)["post_nonce"])
        self.assertEqual(db.raid_by_id(waiting)["status"], "scheduled")
        self.assertEqual(db.raid_by_id(stuck)["post_repost_blocked"], 1)

    def test_active_claim_keeps_the_claimed_channel(self):
        raid_id = self._scheduled("Claimed")
        claims = wow.claim_scheduled_posts(self.guild)
        self.assertEqual(claims[0]["channel_id"], CHANNEL_ID)
        self._retarget("222")
        self.assertEqual(wow.claim_scheduled_posts(self.guild), [])
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["channel_id"], CHANNEL_ID)
        self.assertEqual(saved["post_claim_token"], claims[0]["token"])
        self.assertEqual(self.sends, [])

    def test_same_nonce_retry_uses_the_original_channel(self):
        raid_id = self._scheduled("Retry")
        channels = []
        nonces = []

        def send(channel_id, payload, files=None):
            channels.append(str(channel_id))
            nonces.append(payload["nonce"])
            if len(channels) == 1:
                raise discord_api.DiscordError(403, {"code": 50013, "message": "Missing Permissions"})
            return {"id": "posted-retry", "nonce": payload["nonce"], "channel_id": str(channel_id)}

        def get_message(channel_id, message_id):
            return {"id": message_id, "nonce": nonces[-1], "channel_id": str(channel_id)}

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send), patch(
            "ironkeep.wow.discord_api.get_message", side_effect=get_message
        ):
            self.assertEqual(wow.release_raids(self.guild), "discord")
            self._retarget("222")
            self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(channels, [CHANNEL_ID, CHANNEL_ID])
        self.assertEqual(db.raid_by_id(raid_id)["channel_id"], CHANNEL_ID)
        self.assertEqual(db.raid_by_id(raid_id)["message_id"], "posted-retry")

    def test_confirmation_uses_the_original_channel(self):
        raid_id = self._scheduled("Seen")
        conn = db.connect()
        conn.execute(
            """UPDATE raids
               SET channel_id = ?, message_id = ?, post_nonce = ?, post_claim_token = ?, post_nonce_at = ?
               WHERE id = ?""",
            (CHANNEL_ID, "seen-1", "seen-nonce", "seen-token", "2026-11-14T00:00:00+00:00", raid_id),
        )
        conn.commit()
        conn.close()
        self._retarget("222")
        seen = []

        def get_message(channel_id, message_id):
            seen.append(str(channel_id))
            return {"id": message_id, "nonce": "seen-nonce", "channel_id": str(channel_id)}

        with patch("ironkeep.wow.discord_api.get_message", side_effect=get_message):
            self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(seen, [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")
        self.assertEqual(db.raid_by_id(raid_id)["channel_id"], CHANNEL_ID)
        self.assertEqual(self.sends, [])

    def test_inflight_configuration_change_cannot_redirect_the_send(self):
        raid_id = self._scheduled("Flight")

        def send(channel_id, payload, files=None):
            self._retarget("222")
            return self._send(channel_id, payload, files)

        with patch("ironkeep.wow.discord_api.send_payload", side_effect=send):
            self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends[0]["channel_id"], CHANNEL_ID)
        self.assertEqual(db.raid_by_id(raid_id)["channel_id"], CHANNEL_ID)
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")

    def test_unclaimed_scheduled_raid_follows_the_current_channel(self):
        raid_id = self._scheduled("Unclaimed")
        self.assertEqual(db.raid_by_id(raid_id)["channel_id"], CHANNEL_ID)
        self._retarget("222")
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends[0]["channel_id"], "222")
        self.assertEqual(db.raid_by_id(raid_id)["channel_id"], "222")
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")

    def test_recovery_rejects_another_raids_message_without_a_nonce(self):
        raid_id = self._scheduled("Recover")
        other = self._scheduled("Other")
        self._mark_recovery(raid_id)
        before = self._publication_state(raid_id)
        body = {
            "id": "900",
            "channel_id": CHANNEL_ID,
            "author": {"id": "bot-1"},
            "components": self._signup_buttons(other),
        }
        with patch("ironkeep.wow.discord_api.get_message", return_value=body), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), "identity")
        self.assertEqual(self._publication_state(raid_id), before)
        self.assertEqual(self.sends, [])

    def test_recovery_rejects_a_message_linked_to_another_raid(self):
        raid_id = self._scheduled("Recover")
        other = self._scheduled("Linked")
        self._mark_recovery(raid_id)
        conn = db.connect()
        conn.execute(
            "UPDATE raids SET status = 'closed', message_id = ? WHERE id = ?",
            ("900", other),
        )
        conn.commit()
        conn.close()
        before = self._publication_state(raid_id)
        body = {
            "id": "900",
            "channel_id": CHANNEL_ID,
            "author": {"id": "bot-1"},
            "components": self._signup_buttons(raid_id),
        }
        with patch("ironkeep.wow.discord_api.get_message", return_value=body), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), "identity")
        self.assertEqual(self._publication_state(raid_id), before)
        self.assertEqual(db.raid_by_id(other)["message_id"], "900")
        self.assertEqual(self.sends, [])

    def test_recovery_rejects_a_closed_message_without_signup_buttons(self):
        raid_id = self._scheduled("Recover")
        self._mark_recovery(raid_id)
        before = self._publication_state(raid_id)
        body = {
            "id": "900",
            "channel_id": CHANNEL_ID,
            "author": {"id": "bot-1"},
            "components": [],
            "embeds": [{"title": "Recover", "description": "Gesloten"}],
        }
        with patch("ironkeep.wow.discord_api.get_message", return_value=body), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), "identity")
        self.assertEqual(self._publication_state(raid_id), before)
        self.assertEqual(self.sends, [])

    def _message(self, message_id, components):
        return {
            "id": message_id,
            "channel_id": CHANNEL_ID,
            "author": {"id": "bot-1"},
            "components": components,
        }

    def _open_copy(self, raid_id):
        raid = dict(db.raid_by_id(raid_id))
        raid["status"] = "open"
        return raid

    def test_recovery_identity_rejects_incomplete_and_malformed_cards(self):
        raid_id = self._scheduled("Recover")
        other = self._scheduled("Other")
        self._mark_recovery(raid_id)
        before = self._publication_state(raid_id)
        settings_only = [{
            "type": 1,
            "components": [{"type": 2, "custom_id": f"ike:{raid_id}", "style": 2}],
        }]
        mixed = wow._action_rows(raid_id)
        mixed[0]["components"][0] = dict(mixed[0]["components"][0], custom_id=f"ikt:{other}")
        ticket = wow._action_rows(raid_id)
        ticket[0]["components"].append({"type": 2, "custom_id": "ikt:open", "style": 1})
        wrong_type = [{
            "type": 1,
            "components": [{"type": 3, "custom_id": f"ikt:{raid_id}"}],
        }]
        nested = [{
            "type": 1,
            "components": [{
                "type": 2,
                "custom_id": f"ikt:{raid_id}",
                "components": [{"type": 2, "custom_id": f"ikm:{raid_id}"}],
            }],
        }]
        cases = [
            mixed,
            settings_only,
            ticket,
            wrong_type,
            nested,
            None,
            5,
            "ikt:1",
            [{"type": 1, "components": None}],
            [{"type": 1, "components": "ikt:1"}],
            [{"type": 1}],
            [{"type": True, "components": wow._action_rows(raid_id)[0]["components"]}],
        ]
        for components in cases:
            body = self._message("900", components)
            with patch("ironkeep.wow.discord_api.get_message", return_value=body), patch(
                "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
            ):
                self.assertEqual(wow.attach_verified_publication(GUILD_ID, raid_id, "900"), "identity")
            self.assertEqual(self._publication_state(raid_id), before)
        self.assertEqual(self.sends, [])

    def test_recovery_accepts_builder_cards_for_raid_dungeon_and_event(self):
        raid_id = self._scheduled("Raid card")
        dungeon_id = self._scheduled("Dungeon card", days=4)
        event_id = self._scheduled("Event card", days=5)
        conn = db.connect()
        conn.execute("UPDATE raids SET instance_id = ? WHERE id = ?", ("barrow-deeps", dungeon_id))
        conn.execute("UPDATE raids SET instance_id = ? WHERE id = ?", ("event", event_id))
        conn.commit()
        conn.close()
        cards = (
            (raid_id, "raid-msg", wow.message_payload(self.guild, self._open_copy(raid_id), [])),
            (dungeon_id, "dungeon-msg", wow.message_payload(self.guild, self._open_copy(dungeon_id), [])),
            (event_id, "event-msg", wow.message_payload(self.guild, self._open_copy(event_id), [])),
        )
        self.assertEqual(cards[0][2]["components"], wow._action_rows(raid_id))
        self.assertEqual(cards[1][2]["components"], wow._action_rows(dungeon_id))
        self.assertEqual(cards[2][2]["components"], wow._event_rows(event_id))
        for raid_id, message_id, payload in cards:
            self._mark_recovery(raid_id, nonce=f"nonce-{message_id}")
            body = self._message(message_id, payload["components"])
            with patch("ironkeep.wow.discord_api.get_message", return_value=body), patch(
                "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
            ):
                self.assertIsNone(wow.attach_verified_publication(GUILD_ID, raid_id, message_id))
            saved = db.raid_by_id(raid_id)
            self.assertEqual(saved["status"], "open")
            self.assertEqual(saved["message_id"], message_id)
            self.assertEqual(saved["post_recovery_required"], 0)
        self.assertEqual(self.sends, [])

    def test_concurrent_recovery_of_one_message_and_one_raid(self):
        owner = self._scheduled("Owner")
        stranger = self._scheduled("Stranger", days=4)
        self._mark_recovery(owner, nonce="owner-nonce")
        self._mark_recovery(stranger, nonce="stranger-nonce")
        before = self._publication_state(stranger)
        card = wow.message_payload(self.guild, self._open_copy(owner), [])["components"]
        body = self._message("shared-msg", card)
        barrier = threading.Barrier(2)
        results = []

        def attempt(raid_id):
            barrier.wait(timeout=5)
            results.append(wow.attach_verified_publication(GUILD_ID, raid_id, "shared-msg"))

        with patch("ironkeep.wow.discord_api.get_message", return_value=body), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            threads = [threading.Thread(target=attempt, args=(raid_id,)) for raid_id in (owner, stranger)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
        self.assertEqual(sorted(results, key=lambda item: str(item)), [None, "identity"])
        self.assertEqual(db.raid_by_id(owner)["status"], "open")
        self.assertEqual(db.raid_by_id(owner)["message_id"], "shared-msg")
        self.assertEqual(self._publication_state(stranger), before)

        again = self._scheduled("Again", days=6)
        self._mark_recovery(again, nonce="again-nonce")
        again_card = wow.message_payload(self.guild, self._open_copy(again), [])["components"]
        again_body = self._message("again-msg", again_card)
        same = []
        entered = threading.Barrier(2)

        def fetch(*_args, **_kwargs):
            entered.wait(timeout=5)
            return again_body

        def retry():
            same.append(wow.attach_verified_publication(GUILD_ID, again, "again-msg"))

        with patch("ironkeep.wow.discord_api.get_message", side_effect=fetch), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            threads = [threading.Thread(target=retry) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
        self.assertEqual(sorted(same, key=lambda item: str(item)), [None, "claim"])
        self.assertEqual(db.raid_by_id(again)["status"], "open")
        self.assertEqual(db.raid_by_id(again)["message_id"], "again-msg")
        self.assertEqual(db.raid_by_id(again)["post_repost_blocked"], 0)
        self.assertEqual(self.sends, [])

    def test_historical_claim_without_a_bound_channel_does_not_send(self):
        raid_id = self._scheduled("Historical")
        conn = db.connect()
        conn.execute(
            """UPDATE raids
               SET post_nonce = ?, post_nonce_at = ?, post_channel_bound = 0,
                   post_claim_token = NULL, post_claimed_at = NULL
               WHERE id = ?""",
            ("old-nonce", "2026-11-14T00:00:00+00:00", raid_id),
        )
        conn.commit()
        conn.close()
        self._retarget("222")
        self.assertIsNone(wow.release_raids(self.guild))
        saved = db.raid_by_id(raid_id)
        self.assertEqual(self.sends, [])
        self.assertEqual(saved["status"], "scheduled")
        self.assertEqual(saved["channel_id"], CHANNEL_ID)
        self.assertEqual(saved["post_nonce"], "old-nonce")
        self.assertEqual(saved["post_channel_bound"], 0)
        self.assertEqual(saved["post_recovery_required"], 1)
        self.assertEqual(saved["post_repost_blocked"], 1)

    def test_send_path_refuses_an_unbound_channel(self):
        raid_id = self._scheduled("Bypass")
        conn = db.connect()
        conn.execute(
            """UPDATE raids
               SET post_nonce = ?, post_nonce_at = ?, post_claim_token = ?, post_channel_bound = 0
               WHERE id = ?""",
            ("old-nonce", "2026-11-14T00:00:00+00:00", "old-token", raid_id),
        )
        conn.commit()
        conn.close()
        result = wow._settle_publication(
            self.guild,
            {"id": raid_id, "nonce": "old-nonce", "token": "old-token", "channel_id": "999"},
            datetime.now(timezone.utc),
        )
        saved = db.raid_by_id(raid_id)
        self.assertIsNone(result)
        self.assertEqual(self.sends, [])
        self.assertEqual(saved["channel_id"], CHANNEL_ID)
        self.assertEqual(saved["post_nonce"], "old-nonce")
        self.assertEqual(saved["post_recovery_required"], 1)
        self.assertEqual(saved["post_repost_blocked"], 1)

    def test_completed_publication_is_not_pending_and_a_fresh_post_rebinds(self):
        raid_id = self._scheduled("Rebound")
        self.assertIsNone(wow.release_raids(self.guild))
        posted = db.raid_by_id(raid_id)
        self.assertEqual(posted["status"], "open")
        self.assertEqual(posted["post_channel_bound"], 1)
        self.assertFalse(db.publication_pending(posted))
        self.assertIsNone(posted["post_nonce"])
        self.assertTrue(db.hold_raid(raid_id))
        held = db.raid_by_id(raid_id)
        self.assertEqual(held["status"], "scheduled")
        self.assertEqual(held["post_channel_bound"], 0)
        self.assertIsNone(held["post_nonce"])
        self.assertIsNone(held["message_id"])
        conn = db.connect()
        conn.execute("UPDATE raids SET post_channel_bound = 1, channel_id = ? WHERE id = ?", (CHANNEL_ID, raid_id))
        conn.commit()
        conn.close()
        self._retarget("222")
        self.sends.clear()
        self.assertIsNone(wow.release_raids(self.guild))
        again = db.raid_by_id(raid_id)
        self.assertEqual(self.sends[0]["channel_id"], "222")
        self.assertEqual(again["channel_id"], "222")
        self.assertEqual(again["post_channel_bound"], 1)
        self.assertEqual(again["status"], "open")
        self.assertFalse(db.publication_pending(again))

    def test_earlier_scheduled_raid_cannot_displace_an_open_raid(self):
        open_id = self._open("Open", _when(days=4))
        early = self._scheduled("Early", days=1)
        message_id = db.raid_by_id(open_id)["message_id"]
        deleted = []
        with patch(
            "ironkeep.wow.discord_api.delete_message",
            side_effect=lambda channel_id, message_id: deleted.append((str(channel_id), str(message_id))),
        ):
            self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(deleted, [])
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(open_id)["status"], "open")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], message_id)
        self.assertEqual(db.raid_by_id(early)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(early)["post_nonce"])

    def test_lowering_posted_ahead_preserves_open_messages(self):
        self._ahead(2)
        first = self._open("First", _when(days=2))
        second = self._open("Second", _when(days=4))
        messages = (db.raid_by_id(first)["message_id"], db.raid_by_id(second)["message_id"])
        self._ahead(1)
        deleted = []
        with patch(
            "ironkeep.wow.discord_api.delete_message",
            side_effect=lambda channel_id, message_id: deleted.append(str(message_id)),
        ):
            self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(deleted, [])
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(first)["status"], "open")
        self.assertEqual(db.raid_by_id(second)["status"], "open")
        self.assertEqual(
            (db.raid_by_id(first)["message_id"], db.raid_by_id(second)["message_id"]),
            messages,
        )

    def test_increasing_posted_ahead_publishes_the_next_raid(self):
        open_id = self._open("Open", _when(days=2))
        nxt = self._scheduled("Next", days=4)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends, [])
        self._ahead(2)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual([item["channel_id"] for item in self.sends], [CHANNEL_ID])
        self.assertEqual(db.raid_by_id(open_id)["status"], "open")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], f"message-{open_id}")
        posted = db.raid_by_id(nxt)
        self.assertEqual(posted["status"], "open")
        self.assertEqual(posted["post_channel_bound"], 1)
        self.assertFalse(db.publication_pending(posted))

    def test_closing_an_open_raid_frees_one_slot(self):
        open_id = self._open("Open", _when(days=2))
        nxt = self._scheduled("Next", days=4)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends, [])
        self.assertTrue(db.close_raid(open_id, GUILD_ID))
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(db.raid_by_id(open_id)["status"], "closed")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], f"message-{open_id}")
        self.assertEqual(db.raid_by_id(nxt)["status"], "open")
        self.assertEqual([item["channel_id"] for item in self.sends], [CHANNEL_ID])

    def test_expired_open_publication_occupies_capacity(self):
        open_id = self._open("Started", _when(days=-1))
        nxt = self._scheduled("Next", days=2)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(open_id)["status"], "open")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], f"message-{open_id}")
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")

    def test_stale_settings_snapshot_cannot_delete_an_open_message(self):
        self._ahead(2)
        open_id = self._open("Open", _when(days=4))
        early = self._scheduled("Early", days=1)
        message_id = db.raid_by_id(open_id)["message_id"]
        stale = json.loads(json.dumps(self.guild))
        stale["settings"]["wow"]["posted_ahead"] = 1
        deleted = []
        with patch(
            "ironkeep.wow.discord_api.delete_message",
            side_effect=lambda channel_id, message_id: deleted.append(str(message_id)),
        ):
            self.assertIsNone(wow.release_raids(stale))
        self.assertEqual(deleted, [])
        self.assertEqual(db.raid_by_id(open_id)["status"], "open")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], message_id)
        self.assertEqual(db.raid_by_id(early)["status"], "open")
        self.assertEqual(self.sends[0]["channel_id"], CHANNEL_ID)

    def test_concurrent_releases_respect_one_free_slot(self):
        self._ahead(2)
        open_id = self._open("Open", _when(days=1))
        earlier = self._scheduled("Earlier", days=2)
        later = self._scheduled("Later", days=4)
        folder = tempfile.mkdtemp(dir=self.temp.name)
        args = [sys.executable, "-c", WORKER, config.DB_PATH, str(ROOT), GUILD_ID, "release", folder]
        env = os.environ.copy()
        env["IRONKEEP_DB"] = config.DB_PATH
        procs = [
            subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            for _ in range(2)
        ]
        for proc in procs:
            _out, err = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(len(list(Path(folder).glob("send-*"))), 1)
        self.assertEqual(list(Path(folder).glob("delete-*")), [])
        self.assertEqual(db.raid_by_id(open_id)["message_id"], f"message-{open_id}")
        self.assertEqual(db.raid_by_id(earlier)["status"], "open")
        self.assertEqual(db.raid_by_id(later)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(later)["post_nonce"])

    def test_concurrent_settings_change_cannot_preempt_an_open_raid(self):
        self._ahead(2)
        first = self._open("First", _when(days=3))
        second = self._open("Second", _when(days=4))
        early = self._scheduled("Early", days=1)
        messages = (db.raid_by_id(first)["message_id"], db.raid_by_id(second)["message_id"])
        stale = json.loads(json.dumps(self.guild))
        barrier = threading.Barrier(2)
        deleted = []
        errors = []

        def change_and_release():
            try:
                barrier.wait(timeout=5)
                self._ahead(1)
                wow.release_raids(db.guild_by_id(GUILD_ID))
            except Exception as error:
                errors.append(error)

        def release_stale():
            try:
                barrier.wait(timeout=5)
                wow.release_raids(stale)
            except Exception as error:
                errors.append(error)

        with patch(
            "ironkeep.wow.discord_api.delete_message",
            side_effect=lambda channel_id, message_id: deleted.append(str(message_id)),
        ):
            threads = [threading.Thread(target=change_and_release), threading.Thread(target=release_stale)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(deleted, [])
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(first)["status"], "open")
        self.assertEqual(db.raid_by_id(second)["status"], "open")
        self.assertEqual(db.raid_by_id(early)["status"], "scheduled")
        self.assertEqual(
            (db.raid_by_id(first)["message_id"], db.raid_by_id(second)["message_id"]),
            messages,
        )

    def test_raid_and_dungeon_channels_have_independent_capacity(self):
        self._ahead(1, mode="split", dungeon="222")
        open_id = self._open("Raid", _when(days=2))
        waiting = self._scheduled("Later raid", days=4)
        dungeon_id = db.create_raid(
            GUILD_ID,
            "Dungeon",
            _when(days=3),
            1,
            1,
            3,
            CHANNEL_ID,
            "Officer",
            5,
            "hall-of-thanes",
            status="scheduled",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual([item["channel_id"] for item in self.sends], ["222"])
        self.assertEqual(db.raid_by_id(open_id)["status"], "open")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], f"message-{open_id}")
        self.assertEqual(db.raid_by_id(waiting)["status"], "scheduled")
        self.assertEqual(db.raid_by_id(dungeon_id)["status"], "open")
        self.assertEqual(db.raid_by_id(dungeon_id)["channel_id"], "222")

    def test_recovery_in_one_channel_does_not_block_another(self):
        self._ahead(1, mode="split", dungeon="222")
        stuck = self._scheduled("Stuck", days=1)
        waiting = self._scheduled("Waiting", days=2)
        self._mark_recovery(stuck, channel=CHANNEL_ID)
        dungeon_id = db.create_raid(
            GUILD_ID,
            "Dungeon",
            _when(days=3),
            1,
            1,
            3,
            CHANNEL_ID,
            "Officer",
            5,
            "hall-of-thanes",
            status="scheduled",
            reminder_minutes=0,
            reminder_2_minutes=0,
        )
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual([item["channel_id"] for item in self.sends], ["222"])
        self.assertEqual(db.raid_by_id(stuck)["channel_id"], CHANNEL_ID)
        self.assertEqual(db.raid_by_id(stuck)["post_recovery_required"], 1)
        self.assertEqual(db.raid_by_id(waiting)["status"], "scheduled")
        self.assertIsNone(db.raid_by_id(waiting)["post_nonce"])
        self.assertEqual(db.raid_by_id(dungeon_id)["status"], "open")
        self.assertEqual(db.raid_by_id(dungeon_id)["channel_id"], "222")

    def test_open_raids_above_the_limit_block_further_posts(self):
        first = self._open("First", _when(days=2))
        second = self._open("Second", _when(days=3))
        nxt = self._scheduled("Next", days=4)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(self.sends, [])
        self.assertEqual(db.raid_by_id(first)["status"], "open")
        self.assertEqual(db.raid_by_id(second)["status"], "open")
        self.assertEqual(db.raid_by_id(nxt)["status"], "scheduled")

    def test_officer_delete_still_removes_an_idle_raid(self):
        raid_id = self._open("Delete", _when())
        deleted = []
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
        ), patch("ironkeep.main.deny_unless", return_value=None), patch(
            "ironkeep.wow.discord_api.delete_message",
            side_effect=lambda channel_id, message_id: deleted.append((str(channel_id), str(message_id))),
        ):
            response = main.delete_raid_page(self.guild["slug"], raid_id, Request(scope))
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("error", response.headers["location"])
        self.assertIsNone(db.raid_by_id(raid_id))
        self.assertEqual(deleted, [(CHANNEL_ID, f"message-{raid_id}")])

    def test_officer_delete_keeps_the_raid_when_discord_refuses(self):
        raid_id = self._open("Delete", _when())
        self.assertIsNotNone(db.place_signup(db.raid_by_id(raid_id), "4004", "Ada", "warrior", "protection", "tank"))
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

        def refuse(channel_id, message_id):
            raise discord_api.DiscordError(500, {"message": "down"})

        with patch("ironkeep.main.config.live", return_value=True), patch(
            "ironkeep.main.guild_or_404", return_value=(self.guild, None)
        ), patch("ironkeep.main.deny_unless", return_value=None), patch(
            "ironkeep.wow.discord_api.delete_message", side_effect=refuse
        ):
            response = main.delete_raid_page(self.guild["slug"], raid_id, Request(scope))
        self.assertEqual(response.status_code, 303)
        self.assertIn("error=removed", response.headers["location"])
        saved = db.raid_by_id(raid_id)
        self.assertEqual(saved["status"], "open")
        self.assertEqual(saved["message_id"], f"message-{raid_id}")
        self.assertEqual([row["name"] for row in db.signups_for(raid_id)], ["Ada"])

    def test_inflight_publication_blocks_guild_deletion(self):
        raid_id = self._scheduled("Held")
        entered = threading.Barrier(2)
        resume = threading.Event()

        def send(channel_id, payload, files=None):
            entered.wait(timeout=5)
            self.assertTrue(resume.wait(timeout=5))
            with self.record:
                self.sends.append({"channel_id": str(channel_id), "payload": dict(payload)})
                message_id = f"posted-{len(self.sends)}"
            return {"id": message_id, "nonce": payload.get("nonce"), "channel_id": str(channel_id)}

        def publish():
            with patch("ironkeep.wow.discord_api.send_payload", side_effect=send):
                wow.release_raids(self.guild)

        worker = threading.Thread(target=publish)
        worker.start()
        entered.wait(timeout=5)
        self.assertIs(db.delete_guild(self.guild["slug"]), False)
        self.assertIsNotNone(db.guild_by_id(GUILD_ID))
        held = db.raid_by_id(raid_id)
        self.assertEqual(held["status"], "scheduled")
        self.assertTrue(held["post_nonce"])
        self.assertEqual(held["post_channel_bound"], 1)
        resume.set()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertIsNotNone(db.guild_by_id(GUILD_ID))
        self.assertEqual(db.raid_by_id(raid_id)["status"], "open")

    def test_open_raid_participants_survive_a_full_queue(self):
        open_id = self._open("Open", _when(days=4))
        self._scheduled("Early", days=1)
        raid = db.raid_by_id(open_id)
        self.assertIsNotNone(db.place_signup(raid, "4004", "Ada", "warrior", "protection", "tank"))
        before = db.signups_for(open_id)
        self.assertIsNone(wow.release_raids(self.guild))
        self.assertEqual(db.signups_for(open_id), before)
        self.assertEqual(db.raid_by_id(open_id)["status"], "open")
        self.assertEqual(db.raid_by_id(open_id)["message_id"], f"message-{open_id}")
        self.assertEqual(self.sends, [])


class PublicationMigrationTests(unittest.TestCase):
    def test_existing_database_migrates_twice(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = str(Path(temp.name) / "old.sqlite")
        previous = config.DB_PATH
        self.addCleanup(lambda: setattr(config, "DB_PATH", previous))
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE raids (
                id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                title TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                tank_cap INTEGER NOT NULL,
                healer_cap INTEGER NOT NULL,
                dps_cap INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                size INTEGER,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                instance_id TEXT,
                note TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                thread_id TEXT,
                loot_rule TEXT,
                voice_channel_id TEXT,
                voice_state TEXT,
                voice_seen INTEGER NOT NULL DEFAULT 0,
                voice_empty_at TEXT,
                party_count INTEGER NOT NULL DEFAULT 1,
                ends_at TEXT,
                reminder_minutes INTEGER NOT NULL DEFAULT 0,
                reminder_2_minutes INTEGER NOT NULL DEFAULT 0,
                reminder_2_sent INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """INSERT INTO raids
               (guild_id, title, starts_at, tank_cap, healer_cap, dps_cap, channel_id, size, status, created_by, created_at, reminder_sent)
               VALUES ('1001', 'Kept', '2026-12-01T18:00:00+00:00', 2, 2, 6, '111', 10, 'scheduled', 'Officer', '2026-11-01T00:00:00+00:00', 0)"""
        )
        conn.execute(
            """INSERT INTO raids
               (guild_id, title, starts_at, tank_cap, healer_cap, dps_cap, channel_id, message_id, size, status, created_by, created_at, reminder_sent)
               VALUES ('1001', 'Posted', '2026-12-02T18:00:00+00:00', 2, 2, 6, '111', 'message-1', 10, 'open', 'Officer', '2026-11-01T00:00:00+00:00', 0)"""
        )
        conn.commit()
        conn.close()
        config.DB_PATH = path
        db.init()
        db.init()
        conn = sqlite3.connect(path)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(raids)")]
        rows = conn.execute(
            """SELECT title, status, message_id, post_recovery_required, post_repost_blocked,
                      close_effects_pending, post_channel_bound
               FROM raids ORDER BY title"""
        ).fetchall()
        conn.close()
        for name in (
            "post_nonce",
            "post_nonce_at",
            "post_claimed_at",
            "post_claim_token",
            "post_recovery_required",
            "post_repost_blocked",
            "close_effects_pending",
            "post_channel_bound",
        ):
            self.assertEqual(columns.count(name), 1)
        self.assertEqual(
            rows,
            [
                ("Kept", "scheduled", None, 0, 0, 0, 0),
                ("Posted", "open", "message-1", 0, 0, 0, 0),
            ],
        )

    def test_previous_release_columns_migrate_twice(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = str(Path(temp.name) / "seven.sqlite")
        previous = config.DB_PATH
        self.addCleanup(lambda: setattr(config, "DB_PATH", previous))
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE raids (
                id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                title TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                tank_cap INTEGER NOT NULL,
                healer_cap INTEGER NOT NULL,
                dps_cap INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                size INTEGER,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                instance_id TEXT,
                note TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                thread_id TEXT,
                loot_rule TEXT,
                voice_channel_id TEXT,
                voice_state TEXT,
                voice_seen INTEGER NOT NULL DEFAULT 0,
                voice_empty_at TEXT,
                party_count INTEGER NOT NULL DEFAULT 1,
                ends_at TEXT,
                reminder_minutes INTEGER NOT NULL DEFAULT 0,
                reminder_2_minutes INTEGER NOT NULL DEFAULT 0,
                reminder_2_sent INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.executescript(
            """
            ALTER TABLE raids ADD COLUMN post_nonce TEXT;
            ALTER TABLE raids ADD COLUMN post_nonce_at TEXT;
            ALTER TABLE raids ADD COLUMN post_claimed_at TEXT;
            ALTER TABLE raids ADD COLUMN post_claim_token TEXT;
            ALTER TABLE raids ADD COLUMN post_recovery_required INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE raids ADD COLUMN post_repost_blocked INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE raids ADD COLUMN close_effects_pending INTEGER NOT NULL DEFAULT 0;
            CREATE TABLE raid_signups (
                raid_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                class_id TEXT NOT NULL,
                spec_id TEXT NOT NULL,
                role TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                note TEXT,
                character_id INTEGER,
                party INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (raid_id, user_id)
            );
            """
        )
        before = [row[1] for row in conn.execute("PRAGMA table_info(raids)")]
        self.assertNotIn("post_channel_bound", before)
        conn.execute(
            """INSERT INTO raids
               (guild_id, title, starts_at, tank_cap, healer_cap, dps_cap, channel_id, message_id, size, status,
                created_by, created_at, post_nonce, post_nonce_at, post_recovery_required, post_repost_blocked, close_effects_pending)
               VALUES ('1001', 'Recovered', '2026-12-02T18:00:00+00:00', 2, 2, 6, '1570488304611102830', 'message-5', 10,
                       'scheduled', 'Officer', '2026-11-01T00:00:00+00:00', 'old-nonce', '2026-11-14T00:00:00+00:00', 1, 1, 0)"""
        )
        conn.execute(
            """INSERT INTO raid_signups
               (raid_id, user_id, name, class_id, spec_id, role, state, created_at)
               VALUES (1, '4004', 'Ada', 'warrior', 'protection', 'tank', 'main', '2026-11-01T00:00:00+00:00')"""
        )
        conn.commit()
        conn.close()
        config.DB_PATH = path
        db.init()
        db.init()
        conn = sqlite3.connect(path)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(raids)")]
        raid = conn.execute(
            """SELECT title, status, channel_id, message_id, post_nonce, post_recovery_required,
                      post_repost_blocked, close_effects_pending, post_channel_bound
               FROM raids"""
        ).fetchone()
        signup = conn.execute(
            "SELECT user_id, name, state FROM raid_signups"
        ).fetchone()
        conn.close()
        self.assertEqual(columns.count("post_channel_bound"), 1)
        self.assertEqual(
            raid,
            ("Recovered", "scheduled", "1570488304611102830", "message-5", "old-nonce", 1, 1, 0, 0),
        )
        self.assertEqual(signup, ("4004", "Ada", "main"))


class DiscordNonceRequestTests(unittest.TestCase):
    def test_json_and_multipart_include_nonce(self):
        """This checks the request this program builds. It does not call Discord."""
        seen = []

        def capture(method, url, **kwargs):
            seen.append(kwargs)
            return 200, {"id": "1", "nonce": "n1"}

        payload = {"content": "raid", "nonce": "n1", "enforce_nonce": True}
        with patch("ironkeep.discord_api._request", side_effect=capture):
            discord_api.send_payload("111", payload)
            discord_api.send_payload("111", payload, files=[("banner.jpg", b"img")])
        self.assertEqual(seen[0]["body"]["nonce"], "n1")
        self.assertIs(seen[0]["body"]["enforce_nonce"], True)
        self.assertIn(b'"nonce": "n1"', seen[1]["raw"])
        self.assertIn(b'"enforce_nonce": true', seen[1]["raw"])

    def test_create_message_rate_limit_is_not_retried(self):
        import io
        import urllib.error
        from email.message import EmailMessage

        attempts = []
        headers = EmailMessage()
        headers["Retry-After"] = "0"

        def urlopen(request, timeout=20):
            attempts.append(request.get_method())
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate",
                headers,
                io.BytesIO(b'{"message":"rate","retry_after":0}'),
            )

        with patch("ironkeep.discord_api.urllib.request.urlopen", side_effect=urlopen):
            with self.assertRaises(discord_api.DiscordError) as caught:
                discord_api.send_payload("111", {"content": "raid", "nonce": "n1", "enforce_nonce": True})
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(attempts, ["POST"])

    def test_create_message_timeout_is_not_retried(self):
        attempts = []

        def urlopen(request, timeout=20):
            attempts.append(request.get_method())
            raise TimeoutError("timed out")

        with patch("ironkeep.discord_api.urllib.request.urlopen", side_effect=urlopen):
            with self.assertRaises(TimeoutError):
                discord_api.send_payload("111", {"content": "raid", "nonce": "n1", "enforce_nonce": True})
        self.assertEqual(attempts, ["POST"])

    def test_edit_still_retries_a_rate_limit(self):
        import io
        import urllib.error
        from email.message import EmailMessage

        attempts = []
        headers = EmailMessage()
        headers["Retry-After"] = "0"

        class Response:
            status = 200

            def read(self):
                return b'{"id":"1"}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def urlopen(request, timeout=20):
            attempts.append(request.get_method())
            if len(attempts) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "rate",
                    headers,
                    io.BytesIO(b'{"message":"rate","retry_after":0}'),
                )
            return Response()

        with patch("ironkeep.discord_api.urllib.request.urlopen", side_effect=urlopen):
            discord_api.edit_message("111", "1", {"content": "closed"})
        self.assertEqual(attempts, ["PATCH", "PATCH"])


if __name__ == "__main__":
    unittest.main()
