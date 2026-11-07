"""Regression coverage for the website Discord login.

These checks lock the redirect, cookies, callback, logout, and session behavior
that already serves ironkeep.gg. Companion login is not allowed to change them.
"""

import html
import http.cookies
import os
import shutil
import sqlite3
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

from fastapi.testclient import TestClient

from ironkeep import config, db, discord_api, main


def set_cookie(response, name):
    matches = []
    for header in response.headers.get_list("set-cookie"):
        if header.lower().startswith(name.lower() + "="):
            matches.append(header)
    return matches


def cookie_value(headers, name):
    chosen = [header for header in headers if "max-age=0" not in header.lower()]
    if not chosen:
        raise AssertionError(headers)
    jar = http.cookies.SimpleCookie()
    jar.load(chosen[-1])
    return jar[name].value


def cookie_flags(header):
    return header.lower()


class WebsiteLoginTests(unittest.TestCase):
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

    def test_the_session_table_keeps_its_columns(self):
        conn = sqlite3.connect(config.DB_PATH)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(sessions)")]
        conn.close()
        self.assertEqual(
            columns,
            ["token", "user_id", "name", "username", "access_token", "refresh_token", "expires_at"],
        )

    def test_prototype_login_does_not_send_people_to_discord(self):
        config.BOT_TOKEN = ""
        config.CLIENT_ID = ""
        config.CLIENT_SECRET = ""
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Log in to Ironkeep", page.text)
        self.assertNotIn("discord.com/oauth2", page.text)
        self.assertNotIn("companion-link", page.text)
        self.assertEqual(page.headers.get_list("set-cookie"), [])

    def test_login_uses_the_existing_discord_grant(self):
        response = self.client.get("/login", params={"next": "/admin"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        parsed = urllib.parse.urlparse(response.headers["location"])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "discord.com")
        self.assertEqual(parsed.path, "/oauth2/authorize")
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(
            set(query),
            {"client_id", "redirect_uri", "response_type", "scope", "state"},
        )
        self.assertEqual(query["client_id"], [config.CLIENT_ID])
        self.assertEqual(query["redirect_uri"], ["https://ironkeep.gg/auth/callback"])
        self.assertEqual(query["redirect_uri"], [config.redirect_uri()])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["identify guilds guilds.members.read"])
        self.assertNotIn("prompt", query)
        self.assertNotIn("code_challenge", query)
        self.assertNotIn(config.CLIENT_SECRET, response.headers["location"])
        state = cookie_value(set_cookie(response, "ik_oauth"), "ik_oauth")
        nxt = cookie_value(set_cookie(response, "ik_next"), "ik_next")
        self.assertEqual(query["state"], [state])
        self.assertEqual(nxt, "/admin")
        for name in ("ik_oauth", "ik_next"):
            header = set_cookie(response, name)[0]
            lowered = cookie_flags(header)
            self.assertIn("httponly", lowered)
            self.assertIn("samesite=lax", lowered)
            self.assertIn("max-age=600", lowered)
            self.assertIn("secure", lowered)
        self.assertEqual(set_cookie(response, "ik_session"), [])

    def test_login_is_unchanged_when_companion_auth_is_switched_on(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "true"
        first = self.client.get("/login", follow_redirects=False)
        os.environ.pop("IRONKEEP_COMPANION_AUTH", None)
        second = self.client.get("/login", follow_redirects=False)
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)
        first_query = urllib.parse.parse_qs(urllib.parse.urlparse(first.headers["location"]).query)
        second_query = urllib.parse.parse_qs(urllib.parse.urlparse(second.headers["location"]).query)
        self.assertEqual(first_query["scope"], second_query["scope"])
        self.assertEqual(first_query["redirect_uri"], second_query["redirect_uri"])
        self.assertEqual(first_query["client_id"], second_query["client_id"])
        self.assertEqual(first_query["response_type"], second_query["response_type"])
        self.assertNotIn("companion", first.headers["location"])

    def test_adding_the_bot_still_uses_the_bot_invite(self):
        response = self.client.get("/login", params={"add": "1"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], config.invite_url())
        self.assertIn("scope=bot%20applications.commands", response.headers["location"])
        self.assertNotIn("identify", response.headers["location"])
        self.assertEqual(response.headers.get_list("set-cookie"), [])

    def test_login_refuses_an_off_site_next_page(self):
        external = self.client.get("/login", params={"next": "https://evil.example/steal"}, follow_redirects=False)
        slashed = self.client.get("/login", params={"next": "//evil.example"}, follow_redirects=False)
        self.assertEqual(cookie_value(set_cookie(external, "ik_next"), "ik_next"), "/trial")
        self.assertEqual(cookie_value(set_cookie(slashed, "ik_next"), "ik_next"), "/trial")

    def test_callback_rejects_a_missing_or_mismatched_state(self):
        started = self.client.get("/login", follow_redirects=False)
        state = cookie_value(set_cookie(started, "ik_oauth"), "ik_oauth")

        def explode(code):
            raise AssertionError(code)

        with patch("ironkeep.discord_api.exchange_code", side_effect=explode):
            mismatch = self.client.get(
                "/auth/callback",
                params={"code": "discord-code", "state": "other-state"},
                cookies={"ik_oauth": state, "ik_next": "/admin"},
                follow_redirects=False,
            )
            cancelled = self.client.get(
                "/auth/callback",
                params={"error": "access_denied", "code": "discord-code", "state": state},
                cookies={"ik_oauth": state},
                follow_redirects=False,
            )
            missing = self.client.get("/auth/callback", follow_redirects=False)
        for response in (mismatch, cancelled, missing):
            self.assertEqual(response.status_code, 200)
            self.assertIn("Discord login was cancelled or expired. Try again.", response.text)
            self.assertEqual(set_cookie(response, "ik_session"), [])
        self.assertIsNone(self._only_session())

    def test_callback_keeps_an_existing_session_when_discord_refuses(self):
        existing = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "old-access", "old-refresh", 3600)
        started = self.client.get("/login", follow_redirects=False)
        state = cookie_value(set_cookie(started, "ik_oauth"), "ik_oauth")
        with patch(
            "ironkeep.discord_api.exchange_code",
            side_effect=discord_api.DiscordError(400, {"error": "invalid_grant"}),
        ):
            response = self.client.get(
                "/auth/callback",
                params={"code": "discord-code", "state": state},
                cookies={"ik_oauth": state, "ik_session": existing},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Discord didn't accept the login. The redirect URL in the developer portal must be exactly https://ironkeep.gg/auth/callback.",
            html.unescape(response.text),
        )
        self.assertEqual(set_cookie(response, "ik_session"), [])
        self.assertEqual(db.get_session(existing)["access_token"], "old-access")

    def test_callback_starts_a_website_session_and_nothing_else(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"
        started = self.client.get("/login", params={"next": "/admin"}, follow_redirects=False)
        state = cookie_value(set_cookie(started, "ik_oauth"), "ik_oauth")
        nxt = cookie_value(set_cookie(started, "ik_next"), "ik_next")
        seen = {}

        def exchange(code):
            seen["code"] = code
            return {
                "access_token": "discord-access",
                "refresh_token": "discord-refresh",
                "expires_in": 3600,
                "scope": "identify guilds guilds.members.read",
            }

        def identify(token):
            seen["token"] = token
            return {"id": config.SUPERADMIN_ID, "username": "ada", "global_name": "Ada"}

        with patch("ironkeep.discord_api.exchange_code", side_effect=exchange), patch(
            "ironkeep.discord_api.identify", side_effect=identify
        ):
            response = self.client.get(
                "/auth/callback",
                params={"code": "discord-code", "state": state},
                cookies={"ik_oauth": state, "ik_next": nxt},
                follow_redirects=False,
            )
        self.assertEqual(seen, {"code": "discord-code", "token": "discord-access"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")
        token = cookie_value(set_cookie(response, "ik_session"), "ik_session")
        header = set_cookie(response, "ik_session")[0].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=lax", header)
        self.assertIn("max-age=2592000", header)
        self.assertIn("secure", header)
        self.assertIn("max-age=0", set_cookie(response, "ik_oauth")[0].lower())
        self.assertIn("max-age=0", set_cookie(response, "ik_next")[0].lower())
        row = db.get_session(token)
        self.assertEqual(row["user_id"], config.SUPERADMIN_ID)
        self.assertEqual(row["name"], "Ada")
        self.assertEqual(row["username"], "ada")
        self.assertEqual(row["access_token"], "discord-access")
        self.assertEqual(row["refresh_token"], "discord-refresh")
        self.assertNotIn("companion_sessions", self._tables())
        self.assertNotIn("companion_pairings", self._tables())
        page = self.client.get("/admin", cookies={"ik_session": token}, follow_redirects=False)
        self.assertEqual(page.status_code, 200)

    def test_callback_uses_the_discord_username_when_there_is_no_global_name(self):
        started = self.client.get("/login", follow_redirects=False)
        state = cookie_value(set_cookie(started, "ik_oauth"), "ik_oauth")
        with patch(
            "ironkeep.discord_api.exchange_code",
            return_value={"access_token": "access", "refresh_token": "refresh", "expires_in": 60},
        ), patch(
            "ironkeep.discord_api.identify",
            return_value={"id": "42", "username": "ada"},
        ):
            response = self.client.get(
                "/auth/callback",
                params={"code": "discord-code", "state": state},
                cookies={"ik_oauth": state},
                follow_redirects=False,
            )
        self.assertEqual(response.headers["location"], "/trial")
        row = db.get_session(cookie_value(set_cookie(response, "ik_session"), "ik_session"))
        self.assertEqual(row["name"], "ada")
        self.assertEqual(row["username"], "ada")

    def test_callback_will_not_follow_an_off_site_cookie(self):
        started = self.client.get("/login", follow_redirects=False)
        state = cookie_value(set_cookie(started, "ik_oauth"), "ik_oauth")
        with patch(
            "ironkeep.discord_api.exchange_code",
            return_value={"access_token": "access", "refresh_token": "refresh", "expires_in": 60},
        ), patch(
            "ironkeep.discord_api.identify",
            return_value={"id": config.SUPERADMIN_ID, "username": "ada", "global_name": "Ada"},
        ):
            response = self.client.get(
                "/auth/callback",
                params={"code": "discord-code", "state": state},
                cookies={"ik_oauth": state, "ik_next": "//evil.example"},
                follow_redirects=False,
            )
        self.assertEqual(response.headers["location"], "/trial")

    def test_logout_clears_only_the_presented_website_session(self):
        first = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "access-1", "refresh-1", 3600)
        second = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "access-2", "refresh-2", 3600)
        with patch("ironkeep.discord_api.exchange_code", side_effect=AssertionError("logout must not call Discord")), patch(
            "ironkeep.discord_api.identify", side_effect=AssertionError("logout must not call Discord")
        ), patch(
            "ironkeep.discord_api.refresh_access_token", side_effect=AssertionError("logout must not call Discord")
        ):
            response = self.client.get("/logout", cookies={"ik_session": first}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        self.assertIn("max-age=0", set_cookie(response, "ik_session")[0].lower())
        self.assertIn("max-age=0", set_cookie(response, "ik_view")[0].lower())
        self.assertIsNone(db.get_session(first))
        self.assertEqual(db.get_session(second)["access_token"], "access-2")
        page = self.client.get("/admin", cookies={"ik_session": second}, follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        anonymous = self.client.get("/admin", cookies={"ik_session": first}, follow_redirects=False)
        self.assertEqual(anonymous.status_code, 303)
        self.assertTrue(anonymous.headers["location"].startswith("/login"))

    def test_an_expired_session_is_dropped(self):
        token = db.create_session(config.SUPERADMIN_ID, "Ada", "ada", "access", "refresh", -1)
        self.assertIsNone(db.get_session(token))
        conn = sqlite3.connect(config.DB_PATH)
        left = conn.execute("SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)).fetchone()[0]
        conn.close()
        self.assertEqual(left, 0)
        page = self.client.get("/admin", cookies={"ik_session": token}, follow_redirects=False)
        self.assertEqual(page.status_code, 303)
        self.assertTrue(page.headers["location"].startswith("/login"))

    def test_a_stranger_cannot_open_a_guild_and_a_recruiter_still_can(self):
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Founder", added_by_id="founder")
        guild = db.guild_by_slug("foreverguild")
        settings = guild["settings"]
        settings["recruitment_roles"] = ["role-recruit"]
        db.save_settings(guild["slug"], settings)
        stranger = db.create_session("2002", "Stranger", "stranger", "stranger-access", "", 3600)
        recruiter = db.create_session("3003", "Recruiter", "recruiter", "old-access", "refresh-1", 3600)
        calls = []

        def guild_member(token, guild_id):
            calls.append((token, guild_id))
            if token == "stranger-access":
                return {"roles": ["other"]}
            if token == "old-access":
                raise discord_api.DiscordError(401, {})
            if token == "new-access":
                return {"roles": ["role-recruit"]}
            raise AssertionError(token)

        def refresh(refresh_token):
            self.assertEqual(refresh_token, "refresh-1")
            return {"access_token": "new-access", "refresh_token": "refresh-2", "expires_in": 1200}

        with patch("ironkeep.discord_api.guild_member", side_effect=guild_member), patch(
            "ironkeep.discord_api.refresh_access_token", side_effect=refresh
        ):
            denied = self.client.get(
                "/foreverguild/trial",
                cookies={"ik_session": stranger},
                follow_redirects=False,
            )
            allowed = self.client.get(
                "/foreverguild/trial",
                cookies={"ik_session": recruiter},
                follow_redirects=False,
            )
            again = self.client.get(
                "/foreverguild/trial",
                cookies={"ik_session": recruiter},
                follow_redirects=False,
            )
        self.assertEqual(denied.status_code, 403)
        self.assertIn("You need a recruitment role", denied.text)
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("Forever Guild", allowed.text)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(db.get_session(stranger)["access_token"], "stranger-access")
        self.assertEqual(db.get_session(recruiter)["access_token"], "new-access")
        self.assertEqual(db.get_session(recruiter)["refresh_token"], "refresh-2")
        self.assertEqual(calls, [("stranger-access", "4242"), ("old-access", "4242"), ("new-access", "4242")])

    def test_the_person_who_added_the_bot_can_still_open_the_guild(self):
        db.upsert_guild("4242", "Forever Guild", [], [], added_by="Founder", added_by_id="1001")
        founder = db.create_session("1001", "Founder", "founder", "access", "", 3600)
        with patch("ironkeep.discord_api.guild_member", side_effect=AssertionError("role lookup is not required")):
            page = self.client.get("/foreverguild/trial", cookies={"ik_session": founder}, follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Forever Guild", page.text)

    def _tables(self):
        conn = sqlite3.connect(config.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        return names

    def _only_session(self):
        conn = sqlite3.connect(config.DB_PATH)
        row = conn.execute("SELECT token FROM sessions").fetchone()
        conn.close()
        return row


if __name__ == "__main__":
    unittest.main()
