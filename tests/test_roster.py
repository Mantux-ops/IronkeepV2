"""Guild roster upload, officer page, and deletion. Attendance stays on its own route."""

import json
import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ironkeep import config, db, discord_api, main
from tests.test_companion_auth import (
    CHALLENGE,
    LOOPBACK,
    REPORT,
    STATE,
    VERIFIER,
    cookie_value,
)


def snapshot(captured_at, name="Ada Smith", guild_name="Herberg"):
    return {
        "schema": 1,
        "wowGuildName": guild_name,
        "capturedAt": captured_at,
        "members": [
            {
                "guid": "Player-1",
                "name": name,
                "level": 70,
                "classToken": "WARRIOR",
                "className": "Warrior",
                "rankName": "Member",
            }
        ],
    }


class RosterHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_config = (
            config.BOT_TOKEN,
            config.CLIENT_ID,
            config.CLIENT_SECRET,
            config.DB_PATH,
            config.PUBLIC_URL,
        )
        self.old_flag = os.environ.get("IRONKEEP_COMPANION_AUTH")
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        config.BOT_TOKEN = "bot-token"
        config.CLIENT_ID = "ironkeep-client"
        config.CLIENT_SECRET = "client-secret-stays-on-the-server"
        config.PUBLIC_URL = "https://ironkeep.gg"
        config.DB_PATH = os.path.join(self.tmp, "ik.db")
        db.init()
        self.client = TestClient(main.app)
        self.roles = ["9"]
        self.member_status = 200

        def bot_member(guild_id, user_id):
            if self.member_status >= 500:
                raise discord_api.DiscordError(self.member_status, {})
            if self.member_status == 404:
                return None
            return {"roles": list(self.roles), "user": {"id": str(user_id)}}

        self._member = patch("ironkeep.discord_api.bot_member", side_effect=bot_member)
        self._member.start()
        self.guild = self.make_guild()
        self.website = db.create_session("1001", "Ada", "ada", "discord-access", "discord-refresh", 3600)
        self.token = self.connect()

    def tearDown(self):
        self._member.stop()
        self.client.close()
        config.BOT_TOKEN, config.CLIENT_ID, config.CLIENT_SECRET, config.DB_PATH, config.PUBLIC_URL = self.old_config
        if self.old_flag is None:
            os.environ.pop("IRONKEEP_COMPANION_AUTH", None)
        else:
            os.environ["IRONKEEP_COMPANION_AUTH"] = self.old_flag
        shutil.rmtree(self.tmp)

    def make_guild(self):
        db.upsert_guild("4242", "Dutch Chaos", [], [], added_by="Ada", added_by_id="1001")
        guild = db.guild_by_slug("dutchchaos")
        settings = guild["settings"]
        settings["game"] = "wow"
        settings["companion_roles"] = ["9"]
        db.save_settings(guild["slug"], settings)
        db.set_approval(guild["slug"], "approved")
        return db.guild_by_slug(guild["slug"])

    def connect(self):
        page = self.client.get(
            "/companion/connect",
            params={
                "response_type": "code",
                "client_id": "ironkeep-companion",
                "redirect_uri": LOOPBACK,
                "state": STATE,
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
            },
            cookies={"ik_session": self.website},
        )
        self.assertEqual(page.status_code, 200, page.text)
        csrf = cookie_value(page, "ik_companion_csrf")
        approved = self.client.post(
            "/companion/connect",
            data={"state": STATE, "csrf": csrf, "guild": "dutchchaos", "decision": "allow"},
            cookies={"ik_session": self.website, "ik_companion_csrf": csrf},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303, approved.text)
        code = approved.headers["location"].split("code=")[1].split("&")[0]
        exchanged = self.client.post(
            "/api/companion/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": LOOPBACK,
            },
        )
        self.assertEqual(exchanged.status_code, 200, exchanged.text)
        return exchanged.json()["access_token"]

    def post(self, payload, token=None, slug="dutchchaos"):
        return self.client.post(
            "/api/companion/guilds/%s/roster" % slug,
            content=json.dumps(payload),
            headers={
                "Authorization": "Bearer %s" % (self.token if token is None else token),
                "Content-Type": "application/json",
            },
        )

    def test_newer_capture_replaces_and_the_page_shows_it(self):
        first = self.post(snapshot(1794011429))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertNotIn("duplicate", first.json())
        duplicate = self.post(snapshot(1794011429))
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertTrue(duplicate.json()["duplicate"])
        newer = self.post(snapshot(1794013045))
        self.assertEqual(newer.status_code, 200, newer.text)
        self.assertNotIn("duplicate", newer.json())
        stale = self.post(snapshot(1794011000, name="Cara Quinn"))
        self.assertEqual(stale.status_code, 409)
        changed = snapshot(1794013045, name="Bea Stone")
        self.assertEqual(self.post(changed).status_code, 409)
        page = self.client.get("/dutchchaos/roster", cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Herberg", page.text)
        self.assertIn("Ada Smith", page.text)
        self.assertNotIn("Bea Stone", page.text)
        self.assertIn('data-guid="Player-1"', page.text)
        self.assertIsNone(re.search(r">\s*Player-1\s*<", page.text))
        self.assertIn('id="roster-search"', page.text)
        self.assertIn("roster.js", page.text)

    def test_attendance_route_still_accepts_its_report(self):
        posted = self.client.post(
            "/api/companion/guilds/dutchchaos/attendance",
            content=REPORT,
            headers={"Authorization": "Bearer %s" % self.token, "Content-Type": "text/plain"},
        )
        self.assertEqual(posted.status_code, 200, posted.text)
        self.assertEqual(db.count_attendance(self.guild["id"]), 1)

    def test_discord_outage_does_not_revoke_the_token(self):
        self.member_status = 503
        refused = self.post(snapshot(1794011429))
        self.assertEqual(refused.status_code, 503)
        self.member_status = 200
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)

    def test_a_definite_refusal_revokes_the_family(self):
        self.roles = []
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 403)
        self.roles = ["9"]
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 401)

    def test_a_wow_page_links_the_roster_and_another_game_does_not(self):
        page = self.client.get("/dutchchaos/roster", cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('href="/dutchchaos/roster"', page.text)
        self.assertIn("Roster", page.text)
        db.upsert_guild("5252", "Albion Keep", [], [], added_by="Ada", added_by_id="1001")
        guild = db.guild_by_slug("albionkeep")
        settings = guild["settings"]
        settings["game"] = "albion"
        db.save_settings(guild["slug"], settings)
        db.set_approval(guild["slug"], "approved")
        refused = self.client.get("/albionkeep/roster", cookies={"ik_session": self.website})
        self.assertEqual(refused.status_code, 404, refused.text)
        self.assertIn("This guild has no roster page.", refused.text)
        self.assertNotIn("Guild roster", refused.text)

    def test_someone_without_access_cannot_open_the_roster(self):
        outsider = db.create_session("2002", "Bea", "bea", "discord-access", "discord-refresh", 3600)
        refused = self.client.get("/dutchchaos/roster", cookies={"ik_session": outsider})
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_the_table_sorts_by_name_and_colors_the_class_token(self):
        payload = snapshot(1794011429)
        payload["members"] = [
            {
                "guid": "Player-1",
                "name": "Bea Stone",
                "level": 12,
                "classToken": "MAGE",
                "className": "Magiër",
                "rankName": "Officier",
            },
            {
                "guid": "Player-2",
                "name": "Ada Smith",
                "level": 70,
                "classToken": "WARRIOR",
                "className": "Warrior",
                "rankName": "Member",
            },
        ]
        self.assertEqual(self.post(payload).status_code, 200)
        page = self.client.get("/dutchchaos/roster", cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertLess(page.text.find("Ada Smith"), page.text.find("Bea Stone"))
        self.assertIn("Magiër", page.text)
        self.assertIn("#69CCF0", page.text)
        self.assertIn("#C79C6E", page.text)
        self.assertIn(">Magiër</option>", page.text)
        self.assertIn(">Officier</option>", page.text)
        self.assertIn(">Warrior</option>", page.text)
        self.assertIn(">Member</option>", page.text)
        self.assertIn("2 of 2 characters", page.text)
        self.assertIn('id="roster-none" hidden', page.text)
        self.assertIn('data-guid="Player-1"', page.text)
        self.assertIn('data-guid="Player-2"', page.text)
        self.assertNotIn(">GUID<", page.text)
        self.assertNotIn(">Guid<", page.text)

    def test_character_names_are_escaped(self):
        payload = snapshot(1794011429, name="A&B <script>alert(1)</script>")
        posted = self.post(payload)
        self.assertEqual(posted.status_code, 200, posted.text)
        page = self.client.get("/dutchchaos/roster", cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertNotIn("<script>alert", page.text)
        self.assertIn("A&amp;B &lt;script&gt;alert(1)&lt;/script&gt;", page.text)

    def test_an_empty_roster_explains_how_to_capture_one(self):
        page = self.client.get("/dutchchaos/roster", cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("No guild roster yet.", page.text)
        self.assertNotIn("roster.js", page.text)
        self.assertNotIn("<table", page.text)

    def test_a_dutch_class_name_is_stored(self):
        payload = snapshot(1794011429)
        payload["members"][0]["classToken"] = "MAGE"
        payload["members"][0]["className"] = "Magiër"
        payload["members"][0]["rankName"] = "Officier"
        posted = self.post(payload)
        self.assertEqual(posted.status_code, 200, posted.text)
        from ironkeep import roster

        self.assertEqual(roster.current("4242")["members"][0]["className"], "Magiër")
        self.assertEqual(roster.current("4242")["members"][0]["classToken"], "MAGE")

    def test_guild_deletion_then_rejoin_starts_empty(self):
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        db.delete_guild("dutchchaos")
        from ironkeep import roster
        self.assertIsNone(roster.current("4242"))
        self.guild = self.make_guild()
        self.token = self.connect()
        again = self.post(snapshot(1794011429))
        self.assertEqual(again.status_code, 200, again.text)
        self.assertNotIn("duplicate", again.json())


if __name__ == "__main__":
    unittest.main()
