"""Temporary voice rooms close after they stay empty for the configured time.

Run from the repository root:

    PYTHONPATH=production python3 -m unittest production.tests.test_temp_voice
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironkeep import config, db, discord_api, wow
from ironkeep.bot import temp_voice_snapshot


class _Channel:
    def __init__(self, channel_id):
        self.id = channel_id


class _State:
    def __init__(self, channel):
        self.channel = channel


class _Member:
    def __init__(self, bot=False):
        self.bot = bot


class _Guild:
    def __init__(self):
        self.id = 11
        self.voice_channels = [_Channel(77), _Channel(50)]
        self._voice_states = {}
        self._members = {}

    def get_member(self, user_id):
        return self._members.get(user_id)


class _Client:
    def __init__(self, guild):
        self.guilds = [guild]


class TempVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.previous_db = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmp, "voice.sqlite")
        self.assertNotIn("/var/lib/ironkeep/ironkeep.db", config.DB_PATH)
        db.init()
        db.upsert_guild("11", "Herberg", [], [], added_by="Ada", added_by_id="100")
        guild = db.guild_by_id("11")
        db.set_approval(guild["slug"], "approved")
        settings = db.default_settings()
        settings["game"] = "wow"
        settings["timezone"] = "Europe/Amsterdam"
        settings["wow"] = {
            "raid_channel": "1",
            "poster_roles": ["5"],
            "temp_voice": True,
            "temp_voice_category": "99",
            "temp_voice_empty": 2,
            "temp_voice_hub_id": "50",
        }
        db.save_settings(guild["slug"], settings)
        self.guild = db.guild_by_id("11")
        self.now = datetime(2026, 11, 7, 21, 0, tzinfo=timezone.utc)
        self.deleted = []
        wow._hub_seen.clear()
        self.delete_patch = patch("ironkeep.wow.discord_api.delete_channel", side_effect=self._delete)
        self.delete_patch.start()
        self.addCleanup(self.delete_patch.stop)
        self.addCleanup(self._restore)

    def _restore(self):
        config.DB_PATH = self.previous_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _delete(self, channel_id):
        self.deleted.append(str(channel_id))

    def _seen(self, counts):
        return {"11": {"channels": {"77", "50"}, "counts": counts}}

    def test_a_room_empty_longer_than_the_setting_is_removed(self):
        db.add_temp_room("11", "77", "100")
        db.mark_temp_room_empty("77", (self.now - timedelta(minutes=3)).isoformat())
        wow.settle_temp_rooms(self.guild, self.now, self._seen({}))
        self.assertEqual(self.deleted, ["77"])
        self.assertIsNone(db.temp_room("77"))

    def test_the_timer_starts_when_the_room_is_empty_and_waits_out_the_setting(self):
        db.add_temp_room("11", "77", "100")
        wow.settle_temp_rooms(self.guild, self.now, self._seen({}))
        self.assertEqual(self.deleted, [])
        started = db.temp_room("77")["empty_at"]
        self.assertTrue(started)
        wow.settle_temp_rooms(self.guild, self.now + timedelta(minutes=1), self._seen({}))
        self.assertEqual(self.deleted, [])
        self.assertIsNotNone(db.temp_room("77"))
        wow.settle_temp_rooms(self.guild, self.now + timedelta(minutes=2), self._seen({}))
        self.assertEqual(self.deleted, ["77"])

    def test_someone_in_the_room_keeps_it_and_clears_the_timer(self):
        db.add_temp_room("11", "77", "100")
        db.mark_temp_room_empty("77", (self.now - timedelta(minutes=10)).isoformat())
        wow.settle_temp_rooms(self.guild, self.now, self._seen({"77": 1}))
        self.assertEqual(self.deleted, [])
        self.assertIsNone(db.temp_room("77")["empty_at"])

    def test_a_hidden_room_is_not_treated_as_empty(self):
        db.add_temp_room("11", "77", "100")
        wow.settle_temp_rooms(self.guild, self.now, {"11": {"channels": {"50"}, "counts": {}}})
        self.assertEqual(self.deleted, [])
        self.assertIsNone(db.temp_room("77")["empty_at"])

    def test_a_failed_hub_refresh_still_removes_an_empty_room(self):
        db.add_temp_room("11", "77", "100")
        db.mark_temp_room_empty("77", (self.now - timedelta(minutes=3)).isoformat())

        def broken(_guild):
            raise discord_api.DiscordError(403, {"message": "Missing Access"})

        with patch("ironkeep.wow.ensure_temp_hub", side_effect=broken):
            wow.sync_temp_voice(self.guild, self.now)
        self.assertEqual(self.deleted, ["77"])

    def test_snapshot_counts_people_and_ignores_bots(self):
        guild = _Guild()
        room = _Channel(77)
        guild._voice_states = {100: _State(room), 200: _State(room)}
        guild._members = {100: _Member(False), 200: _Member(bot=True)}
        snapshot = temp_voice_snapshot(_Client(guild))
        self.assertEqual(snapshot["11"]["counts"], {"77": 1})
        self.assertIn("50", snapshot["11"]["channels"])
        self.assertIn("77", snapshot["11"]["channels"])

    def test_an_uncached_person_still_keeps_the_room(self):
        guild = _Guild()
        guild._voice_states = {100: _State(_Channel(77))}
        snapshot = temp_voice_snapshot(_Client(guild))
        self.assertEqual(snapshot["11"]["counts"], {"77": 1})


if __name__ == "__main__":
    unittest.main()
