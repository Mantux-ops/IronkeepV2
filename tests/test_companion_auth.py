"""Companion authorization stays off, and cannot pass for a website session."""

import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ironkeep import attendance, config, db, main
from ironkeep.companion_auth import SESSION_SECONDS

REPORT = "\n".join(
    [
        "Ironkeep group",
        "Place: Hall of Thanes",
        "Started: 2026-11-01 12:00",
        "",
        "Name | Class | Role | Time | Status",
        "Ada Smith | Warrior | Tank | 20m | here",
        "",
        "format: ironkeep-group 1",
    ]
)


class CompanionAuthTests(unittest.TestCase):
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
        os.environ.pop("IRONKEEP_COMPANION_AUTH", None)
        config.BOT_TOKEN = "bot-token"
        config.CLIENT_ID = "ironkeep-client"
        config.CLIENT_SECRET = "client-secret-stays-on-the-server"
        config.PUBLIC_URL = "https://ironkeep.gg"
        config.DB_PATH = os.path.join(self.tmp, "ik.db")
        db.init()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        config.BOT_TOKEN, config.CLIENT_ID, config.CLIENT_SECRET, config.DB_PATH, config.PUBLIC_URL = self.old_config
        if self.old_flag is None:
            os.environ.pop("IRONKEEP_COMPANION_AUTH", None)
        else:
            os.environ["IRONKEEP_COMPANION_AUTH"] = self.old_flag
        shutil.rmtree(self.tmp)

    def test_companion_routes_are_missing_until_the_flag_is_set(self):
        self.assertFalse(config.companion_auth_enabled())
        website = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "discord-access", "discord-refresh", 3600)
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Ada", added_by_id=config.SUPERADMIN_ID)
        for method, path in (
            ("GET", "/api/companion/session"),
            ("POST", "/api/companion/session"),
            ("DELETE", "/api/companion/session"),
            ("POST", "/api/companion/exchange"),
            ("POST", "/api/companion/logout"),
            ("POST", "/api/foreverguild/companion-link"),
            ("GET", "/api/foreverguild/companion-link"),
            ("POST", "/api/no-such-guild/companion-link"),
        ):
            response = self.client.request(
                method,
                path,
                cookies={"ik_session": website},
                headers={"Authorization": "Bearer " + website},
            )
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertNotIn("companion_sessions", self._tables())
        self.assertNotIn("companion_pairings", self._tables())
        os.environ["IRONKEEP_COMPANION_AUTH"] = "false"
        self.assertFalse(config.companion_auth_enabled())
        self.assertEqual(self.client.post("/api/companion/exchange", json={"code": "x"}).status_code, 404)

    def test_the_flag_does_nothing_while_the_site_is_on_sample_data(self):
        config.BOT_TOKEN = ""
        config.CLIENT_ID = ""
        config.CLIENT_SECRET = ""
        os.environ["IRONKEEP_COMPANION_AUTH"] = "yes"
        self.assertFalse(config.live())
        response = self.client.post("/api/companion/exchange", json={"code": "x"})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("companion_sessions", self._tables())

    def test_a_website_session_and_a_companion_session_do_not_cross(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "true"
        self.assertTrue(config.companion_auth_enabled())
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Ada", added_by_id="founder")
        guild = db.guild_by_slug("foreverguild")
        settings = guild["settings"]
        settings["recruitment_roles"] = ["role-recruit"]
        db.save_settings(guild["slug"], settings)
        website = db.create_session(
            config.SUPERADMIN_ID,
            "Ada",
            "ada",
            "discord-access-SHOULD-NOT-LEAK",
            "discord-refresh-SHOULD-NOT-LEAK",
            3600,
        )
        stranger = db.create_session("2002", "Stranger", "stranger", "other-access", "other-refresh", 3600)
        with patch("ironkeep.discord_api.exchange_code", side_effect=AssertionError("no Discord grant")), patch(
            "ironkeep.discord_api.identify", side_effect=AssertionError("no Discord identify")
        ), patch(
            "ironkeep.discord_api.refresh_access_token", side_effect=AssertionError("no Discord refresh")
        ), patch(
            "ironkeep.discord_api.guild_member", side_effect=AssertionError("superadmin does not need a role lookup")
        ):
            denied = self.client.post(
                "/api/foreverguild/companion-link",
                headers={"Authorization": "Bearer ikc.not-a-website-session"},
            )
            linked = self.client.post("/api/foreverguild/companion-link", cookies={"ik_session": website})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(set(linked.json()), {"code", "expires_in", "guild"})
        self.assertEqual(linked.json()["expires_in"], 300)
        self.assertEqual(linked.json()["guild"], "foreverguild")
        self.assertNotIn(website, linked.text)
        self.assertNotIn("discord-access-SHOULD-NOT-LEAK", linked.text)
        self.assertEqual(linked.headers.get_list("set-cookie"), [])

        with patch("ironkeep.discord_api.guild_member", return_value={"roles": []}):
            blocked = self.client.post("/api/foreverguild/companion-link", cookies={"ik_session": stranger})
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(self._count("companion_pairings", "used = 0"), 1)

        exchanged = self.client.post(
            "/api/companion/exchange",
            json={"code": linked.json()["code"]},
            cookies={"ik_session": stranger},
        )
        self.assertEqual(exchanged.status_code, 200)
        self.assertEqual(exchanged.headers.get_list("set-cookie"), [])
        body = exchanged.json()
        self.assertEqual(
            set(body),
            {"ok", "token", "expires_in", "user_id", "name", "username", "guild_id", "guild_slug"},
        )
        self.assertTrue(body["token"].startswith("ikc."))
        self.assertNotIn(".", body["token"][4:])
        self.assertEqual(body["expires_in"], SESSION_SECONDS)
        self.assertEqual(body["user_id"], config.SUPERADMIN_ID)
        self.assertEqual(body["name"], "Ada")
        self.assertEqual(body["guild_slug"], "foreverguild")
        self.assertNotIn("discord-access-SHOULD-NOT-LEAK", exchanged.text)
        self.assertNotIn("refresh", exchanged.text)
        again = self.client.post("/api/companion/exchange", json={"code": linked.json()["code"]})
        self.assertEqual(again.status_code, 401)
        self.assertEqual(self._count("companion_sessions"), 1)

        companion = body["token"]
        who = self.client.get(
            "/api/companion/session",
            headers={"Authorization": "Bearer " + companion},
            cookies={"ik_session": stranger},
        )
        self.assertEqual(who.status_code, 200)
        self.assertEqual(who.json()["user_id"], config.SUPERADMIN_ID)
        self.assertEqual(who.json()["name"], "Ada")
        self.assertNotEqual(who.json()["name"], "Stranger")
        self.assertEqual(
            set(who.json()),
            {"ok", "user_id", "name", "username", "guild_id", "guild_slug"},
        )

        stolen = self.client.get(
            "/api/companion/session",
            headers={"Authorization": "Bearer " + website},
            cookies={"ik_session": website},
        )
        self.assertEqual(stolen.status_code, 401)
        self.assertEqual(stolen.json()["error"], "Companion login is required.")
        self.assertEqual(self.client.get("/api/companion/session").status_code, 401)

        as_website = self.client.get("/admin", cookies={"ik_session": companion}, follow_redirects=False)
        self.assertEqual(as_website.status_code, 303)
        self.assertTrue(as_website.headers["location"].startswith("/login"))
        self.assertIsNone(db.get_session(companion))
        self.assertIsNotNone(db.get_session(website))
        columns = self._columns("sessions")
        self.assertEqual(
            columns,
            ["token", "user_id", "name", "username", "access_token", "refresh_token", "expires_at"],
        )
        self.assertNotIn("access_token", self._columns("companion_sessions"))
        self.assertNotIn("refresh_token", self._columns("companion_sessions"))
        self.assertEqual(self._count("sessions", "token = ?", (companion,)), 0)
        self.assertEqual(self._count("companion_sessions", "token = ?", (website,)), 0)

        key = attendance.token_for(db.guild_by_slug("foreverguild"))
        posted = self.client.post(
            "/api/foreverguild/attendance",
            content=REPORT,
            headers={"Authorization": "Bearer " + key},
        )
        self.assertEqual(posted.status_code, 200)
        for presented in (companion, website):
            rejected = self.client.post(
                "/api/foreverguild/attendance",
                content=REPORT,
                headers={"Authorization": "Bearer " + presented},
            )
            self.assertEqual(rejected.status_code, 401)
            self.assertEqual(rejected.json()["error"], "Unknown companion key.")
        cookie_only = self.client.post(
            "/api/foreverguild/attendance",
            content=REPORT,
            cookies={"ik_session": website},
        )
        self.assertEqual(cookie_only.status_code, 401)

        logged_out = self.client.post(
            "/api/companion/logout",
            headers={"Authorization": "Bearer " + companion},
            cookies={"ik_session": website},
        )
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(logged_out.headers.get_list("set-cookie"), [])
        self.assertEqual(
            self.client.get("/api/companion/session", headers={"Authorization": "Bearer " + companion}).status_code,
            401,
        )
        self.assertIsNotNone(db.get_session(website))
        self.assertEqual(self.client.get("/admin", cookies={"ik_session": website}, follow_redirects=False).status_code, 200)

        website_logout = self.client.get("/logout", cookies={"ik_session": website}, follow_redirects=False)
        self.assertEqual(website_logout.status_code, 303)
        self.assertIsNone(db.get_session(website))

    def test_logout_of_the_website_leaves_the_companion_session(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Ada", added_by_id=config.SUPERADMIN_ID)
        website = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "access", "refresh", 3600)
        linked = self.client.post("/api/foreverguild/companion-link", cookies={"ik_session": website})
        exchanged = self.client.post("/api/companion/exchange", json={"code": linked.json()["code"]})
        companion = exchanged.json()["token"]
        self.client.get("/logout", cookies={"ik_session": website}, follow_redirects=False)
        self.assertIsNone(db.get_session(website))
        who = self.client.get("/api/companion/session", headers={"Authorization": "Bearer " + companion})
        self.assertEqual(who.status_code, 200)
        self.assertEqual(who.json()["user_id"], config.SUPERADMIN_ID)

    def test_a_recruitment_role_can_mint_a_link_and_a_stale_one_cannot_be_used(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Founder", added_by_id="founder")
        guild = db.guild_by_slug("foreverguild")
        settings = guild["settings"]
        settings["recruitment_roles"] = ["role-recruit"]
        db.save_settings(guild["slug"], settings)
        recruiter = db.create_session("3003", "Recruiter", "recruiter", "access", "refresh", 3600)
        with patch("ironkeep.discord_api.guild_member", return_value={"roles": ["role-recruit"]}):
            linked = self.client.post("/api/foreverguild/companion-link", cookies={"ik_session": recruiter})
        self.assertEqual(linked.status_code, 200)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            "UPDATE companion_pairings SET expires_at = ? WHERE code = ?",
            ("2000-01-01T00:00:00", linked.json()["code"]),
        )
        conn.commit()
        conn.close()
        expired = self.client.post("/api/companion/exchange", json={"code": linked.json()["code"]})
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(self._count("companion_sessions"), 0)
        self.assertEqual(self.client.post("/api/companion/exchange", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/companion/exchange", content=b"nope").status_code, 400)

    def test_an_expired_companion_session_is_rejected(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Ada", added_by_id=config.SUPERADMIN_ID)
        website = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "access", "refresh", 3600)
        linked = self.client.post("/api/foreverguild/companion-link", cookies={"ik_session": website})
        exchanged = self.client.post("/api/companion/exchange", json={"code": linked.json()["code"]})
        companion = exchanged.json()["token"]
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE companion_sessions SET expires_at = ? WHERE token = ?", ("2000-01-01T00:00:00", companion))
        conn.commit()
        conn.close()
        rejected = self.client.get("/api/companion/session", headers={"Authorization": "Bearer " + companion})
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(self._count("companion_sessions"), 0)

    def test_one_link_can_be_exchanged_once(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Ada", added_by_id=config.SUPERADMIN_ID)
        website = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "access", "refresh", 3600)
        linked = self.client.post("/api/foreverguild/companion-link", cookies={"ik_session": website})
        code = linked.json()["code"]
        barrier = threading.Barrier(4)
        raced = []

        def once():
            barrier.wait()
            client = TestClient(main.app)
            try:
                raced.append(client.post("/api/companion/exchange", json={"code": code}).status_code)
            finally:
                client.close()

        threads = [threading.Thread(target=once) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(raced), [200, 401, 401, 401])
        self.assertEqual(self._count("companion_sessions"), 1)

    def _tables(self):
        conn = sqlite3.connect(config.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        return names

    def _columns(self, table):
        conn = sqlite3.connect(config.DB_PATH)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)]
        conn.close()
        return columns

    def _count(self, table, where="", params=()):
        conn = sqlite3.connect(config.DB_PATH)
        sql = "SELECT COUNT(*) FROM " + table
        if where:
            sql += " WHERE " + where
        try:
            count = conn.execute(sql, params).fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        conn.close()
        return count


if __name__ == "__main__":
    unittest.main()
