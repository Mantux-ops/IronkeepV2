"""Production roster upload, officer page, and deletion.

Run from the repository root:

    PYTHONPATH=production python3 -m unittest production.tests.test_roster
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironkeep import config, db, roster
import production.tests.test_companion_phase1 as phase1


def snapshot(captured_at, name="Ada Smith", guild_name="Herberg", level=70):
    return {
        "schema": 1,
        "wowGuildName": guild_name,
        "capturedAt": captured_at,
        "members": [
            {
                "guid": "Player-1",
                "name": name,
                "level": level,
                "classToken": "WARRIOR",
                "className": "Warrior",
                "rankName": "Member",
            }
        ],
    }


class ProductionRosterTests(unittest.TestCase):
    def setUp(self):
        import ironkeep.main as site

        site.templates.env.globals["asset"] = lambda path: "/static/" + path
        self.fx = phase1.Phase1Tests()
        self.fx.setUp()
        self.fx.enable()
        self.fx.guild("11", "dutchchaos", self.fx.wow_settings(["9"]))
        db.upsert_guild("11", "dutchchaos", [], [], added_by="Ada", added_by_id="100")
        self.fx.member_roles[("100", "11")] = ["9"]
        self.fx.session("100")
        code, state = self.fx.allow("dutchchaos")
        self.token = self.fx.exchange(code, state)["access_token"]

    def tearDown(self):
        self.fx.doCleanups()

    def post(self, payload, slug="dutchchaos", token=None):
        return self.fx.client.post(
            "/api/companion/guilds/%s/roster" % slug,
            content=json.dumps(payload),
            headers={
                "Authorization": "Bearer %s" % (self.token if token is None else token),
                "Content-Type": "application/json",
            },
        )

    def test_newer_replaces_and_a_duplicate_does_not_move_the_row(self):
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        received = roster.current("11")["received_at"]
        duplicate = self.post(snapshot(1794011429))
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(roster.current("11")["received_at"], received)
        self.assertEqual(self.post(snapshot(1794013045)).status_code, 200)
        self.assertEqual(roster.current("11")["captured_at"], 1794013045)
        stale = self.post(snapshot(1794011000, name="Cara Quinn"))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(roster.current("11")["captured_at"], 1794013045)

    def test_same_timestamp_conflict_and_wrong_guild_name(self):
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        self.assertEqual(self.post(snapshot(1794011429, level=71)).status_code, 409)
        renamed = self.post(snapshot(1794013045, guild_name="Other Keep"))
        self.assertEqual(renamed.status_code, 409)
        self.assertEqual(roster.current("11")["wow_guild_name"], "Herberg")
        self.assertEqual(roster.current("11")["captured_at"], 1794011429)

    def test_a_future_capture_is_rejected(self):
        self.assertEqual(self.post(snapshot(4102444800)).status_code, 400)
        self.assertIsNone(roster.current("11"))

    def test_discord_outage_keeps_the_token(self):
        self.fx.member_roles[("100", "11")] = "down"
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 503)
        self.fx.member_roles[("100", "11")] = ["9"]
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)

    def test_a_definite_refusal_revokes_the_family(self):
        self.fx.member_roles[("100", "11")] = []
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 403)
        self.fx.member_roles[("100", "11")] = ["9"]
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 401)

    def test_another_guild_in_the_url_is_refused(self):
        self.fx.guild("22", "other", self.fx.wow_settings(["9"]))
        self.fx.member_roles[("100", "22")] = ["9"]
        self.assertEqual(self.post(snapshot(1794011429), slug="other").status_code, 403)
        self.assertIsNone(roster.current("22"))

    def test_delete_and_rejoin_accepts_the_old_body(self):
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        db.delete_guild("dutchchaos")
        self.assertIsNone(roster.current("11"))
        self.fx.guild("11", "dutchchaos", self.fx.wow_settings(["9"]))
        self.fx.session("100")
        code, state = self.fx.allow("dutchchaos")
        self.token = self.fx.exchange(code, state)["access_token"]
        again = self.post(snapshot(1794011429))
        self.assertEqual(again.status_code, 200, again.text)
        self.assertNotIn("duplicate", again.json())

    def test_a_dutch_class_name_is_stored(self):
        payload = snapshot(1794011429)
        payload["members"][0]["classToken"] = "MAGE"
        payload["members"][0]["className"] = "Magiër"
        payload["members"][0]["name"] = "José"
        posted = self.post(payload)
        self.assertEqual(posted.status_code, 200, posted.text)
        row = roster.current("11")["members"][0]
        self.assertEqual(row["className"], "Magiër")
        self.assertEqual(row["name"], "José")
        self.assertEqual(row["classToken"], "MAGE")

    def test_the_officer_page_lists_the_member(self):
        from unittest.mock import patch
        from ironkeep.discord_api import DiscordError

        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        self.fx.session(config.SUPERADMIN_ID)
        with patch("ironkeep.discord_api.guild_member", side_effect=DiscordError(503, {})):
            page = self.fx.client.get("/dutchchaos/roster", cookies={"ik_session": self.fx.website})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Ada Smith", page.text)
        self.assertIn("Herberg", page.text)
        self.assertIn('href="/dutchchaos/roster"', page.text)
        self.assertIn(">Roster<", page.text)

    def test_an_albion_guild_is_sent_to_its_own_home(self):
        self.fx.guild("33", "albionkeep", self.fx.albion_settings(["9"]))
        self.fx.session(config.SUPERADMIN_ID)
        page = self.fx.client.get("/albionkeep/roster", cookies={"ik_session": self.fx.website}, follow_redirects=False)
        self.assertEqual(page.status_code, 303, page.text)
        self.assertTrue(page.headers["location"].endswith("/albionkeep/trial"))

    def test_a_member_without_the_members_page_is_refused(self):
        from unittest.mock import patch

        self.fx.session("200")
        with patch("ironkeep.discord_api.guild_member", return_value={"roles": [], "user": {"id": "200"}}):
            page = self.fx.client.get("/dutchchaos/roster", cookies={"ik_session": self.fx.website})
        self.assertEqual(page.status_code, 403, page.text)
        self.assertIn("include this page", page.text)
        self.assertNotIn("Guild roster", page.text)


if __name__ == "__main__":
    unittest.main()
