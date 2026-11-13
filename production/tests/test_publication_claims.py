"""Publication claims for scheduled raids.

Discord HTTP is patched. These tests check the claim this program sends.
They do not prove how Discord treats nonce or enforce_nonce.
"""

import json
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
        body = {"id": "900", "channel_id": CHANNEL_ID, "nonce": "nonce-1", "author": {"id": "bot-1"}}
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
        matched = {"id": "901", "channel_id": CHANNEL_ID, "nonce": "nonce-2", "author": {"id": "bot-1"}}
        with patch("ironkeep.wow.discord_api.get_message", return_value=matched), patch(
            "ironkeep.wow.discord_api.bot_user", return_value={"id": "bot-1"}
        ):
            self.assertIsNone(wow.attach_verified_publication(GUILD_ID, second, "901"))
        self.assertEqual(db.raid_by_id(second)["message_id"], "901")
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
            "SELECT title, status, message_id, post_recovery_required, post_repost_blocked, close_effects_pending FROM raids ORDER BY title"
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
        ):
            self.assertEqual(columns.count(name), 1)
        self.assertEqual(
            rows,
            [("Kept", "scheduled", None, 0, 0, 0), ("Posted", "open", "message-1", 0, 0, 0)],
        )


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
