"""Security coverage for the Companion connection. Website login is covered separately."""

import http.cookies
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
import urllib.parse
from unittest.mock import patch

from fastapi.testclient import TestClient

from ironkeep import attendance, config, db, discord_api, main
from ironkeep.companion_auth import (
    ACCESS_SECONDS,
    CODE_SECONDS,
    REFRESH_SECONDS,
    pkce_s256,
)

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
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
LOOPBACK = "http://127.0.0.1:43123/callback"
STATE = "state-value-0123456789"


def cookie_headers(response, name):
    return [header for header in response.headers.get_list("set-cookie") if header.lower().startswith(name.lower() + "=")]


def cookie_value(response, name):
    jar = http.cookies.SimpleCookie()
    jar.load(cookie_headers(response, name)[0])
    return jar[name].value


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
        self.member_roles = {}
        self.member_calls = []

        def bot_member(guild_id, user_id):
            self.member_calls.append((str(guild_id), str(user_id)))
            found = self.member_roles.get((str(user_id), str(guild_id)))
            if found is None:
                raise discord_api.DiscordError(404, {})
            return {"roles": list(found)}

        self._member = patch("ironkeep.discord_api.bot_member", side_effect=bot_member)
        self._member.start()

    def tearDown(self):
        self._member.stop()
        self.client.close()
        config.BOT_TOKEN, config.CLIENT_ID, config.CLIENT_SECRET, config.DB_PATH, config.PUBLIC_URL = self.old_config
        if self.old_flag is None:
            os.environ.pop("IRONKEEP_COMPANION_AUTH", None)
        else:
            os.environ["IRONKEEP_COMPANION_AUTH"] = self.old_flag
        shutil.rmtree(self.tmp)

    def enable(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"

    def guild(self, discord_id="4242", name="Forever Guild", roles=None, added_by_id="1001"):
        db.upsert_guild(discord_id, name, [], [], added_by="Founder", added_by_id=added_by_id)
        guild = db.guild_by_slug(name.lower().replace(" ", ""))
        settings = guild["settings"]
        settings["companion_roles"] = list(roles or [])
        settings["recruitment_roles"] = ["1103"]
        db.save_settings(guild["slug"], settings)
        return db.guild_by_slug(guild["slug"])

    def session(self, user_id, name="Ada", username="ada"):
        return db.create_session(user_id, name, username, "discord-access-SHOULD-NOT-LEAK", "discord-refresh-SHOULD-NOT-LEAK", 3600)

    def start(self, token, redirect_uri=LOOPBACK, state=STATE, challenge=CHALLENGE, method="S256", client_id="ironkeep-companion"):
        return self.client.get(
            "/companion/connect",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": method,
            },
            cookies={"ik_session": token} if token else None,
            follow_redirects=False,
        )

    def hidden(self, page, name):
        marker = 'name="%s" value="' % name
        start = page.text.index(marker) + len(marker)
        return page.text[start:page.text.index('"', start)]

    def approve(self, token, page, slug, decision="allow", csrf=None, state=None):
        return self.client.post(
            "/companion/connect",
            data={
                "state": STATE if state is None else state,
                "csrf": self.hidden(page, "csrf") if csrf is None else csrf,
                "guild": slug,
                "decision": decision,
            },
            cookies={
                "ik_session": token,
                "ik_companion_csrf": cookie_value(page, "ik_companion_csrf") if csrf is None else csrf or "",
            },
            follow_redirects=False,
        )

    def exchange(self, code, verifier=VERIFIER, redirect_uri=LOOPBACK):
        return self.client.post(
            "/api/companion/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
        )

    def connect(self, user_id=config.SUPERADMIN_ID, roles=None, state=STATE):
        self.enable()
        guild = self.guild(roles=roles)
        if user_id != config.SUPERADMIN_ID:
            self.member_roles[(str(user_id), guild["id"])] = list(roles or [])
        token = self.session(user_id)
        page = self.start(token, state=state)
        self.assertEqual(page.status_code, 200, page.text)
        approved = self.approve(token, page, guild["slug"], state=state)
        self.assertEqual(approved.status_code, 303, approved.text)
        parsed = urllib.parse.urlparse(approved.headers["location"])
        query = urllib.parse.parse_qs(parsed.query)
        exchanged = self.exchange(query["code"][0])
        self.assertEqual(exchanged.status_code, 200, exchanged.text)
        return guild, token, exchanged.json(), approved.headers["location"]

    def test_pkce_s256_matches_the_published_vector(self):
        self.assertEqual(pkce_s256(VERIFIER), CHALLENGE)

    def test_routes_stay_missing_until_the_flag_is_set(self):
        self.assertFalse(config.companion_auth_enabled())
        website = self.session(config.SUPERADMIN_ID)
        paths = (
            ("GET", "/companion/connect"),
            ("POST", "/companion/connect"),
            ("POST", "/api/companion/token"),
            ("POST", "/api/companion/revoke"),
            ("POST", "/api/companion/logout"),
            ("GET", "/api/companion/guilds"),
            ("POST", "/api/companion/guilds/foreverguild/attendance"),
            ("POST", "/api/companion/exchange"),
            ("GET", "/api/companion/session"),
        )
        for method, path in paths:
            response = self.client.request(method, path, cookies={"ik_session": website})
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertNotIn("companion_connect", self.tables())
        self.assertNotIn("companion_credentials", self.tables())
        config.BOT_TOKEN = ""
        config.CLIENT_ID = ""
        config.CLIENT_SECRET = ""
        os.environ["IRONKEEP_COMPANION_AUTH"] = "yes"
        self.assertEqual(self.client.post("/api/companion/token", json={}).status_code, 404)

    def test_a_bad_redirect_or_pkce_method_is_refused_before_a_row_is_stored(self):
        self.enable()
        token = self.session(config.SUPERADMIN_ID)
        samples = [
            "https://evil.example/callback",
            "http://evil.example/callback",
            "http://127.0.0.1/callback",
            "http://127.0.0.1:43123/callback?next=https://evil.example",
            "http://127.0.0.1:43123/callback#fragment",
            "http://127.0.0.1.evil.com:43123/callback",
            "http://127.0.0.1:43123@evil.com/callback",
            "http://localhost:43123/callback/../steal",
            "http://127.0.0.1:43123",
            LOOPBACK + " ",
        ]
        for redirect_uri in samples:
            response = self.start(token, redirect_uri=redirect_uri)
            self.assertEqual(response.status_code, 400, redirect_uri)
            self.assertNotIn("location", {key.lower() for key in response.headers})
            self.assertNotIn(redirect_uri, response.headers.get("location", ""))
        plain = self.start(token, method="plain")
        self.assertEqual(plain.status_code, 400)
        self.assertNotIn("companion_connect", self.tables())
        self.assertEqual(self.start(token, client_id=config.CLIENT_ID).status_code, 400)

    def test_get_does_not_approve_and_login_stays_on_the_website(self):
        self.enable()
        anonymous = self.start(None)
        self.assertEqual(anonymous.status_code, 303)
        parsed = urllib.parse.urlparse(anonymous.headers["location"])
        self.assertEqual(parsed.path, "/login")
        nxt = urllib.parse.parse_qs(parsed.query)["next"][0]
        self.assertTrue(nxt.startswith("/companion/connect?"))
        self.assertNotIn("discord.com", anonymous.headers["location"])
        self.assertEqual(cookie_headers(anonymous, "ik_session"), [])
        token = self.session(config.SUPERADMIN_ID)
        self.guild()
        page = self.start(token)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Connect the Companion", page.text)
        self.assertIn('type="submit"', page.text)
        self.assertNotIn("location", {key.lower() for key in page.headers})
        header = cookie_headers(page, "ik_companion_csrf")[0].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=lax", header)
        self.assertIn("secure", header)
        self.assertIn("path=/companion/connect", header)

    def test_csrf_and_state_are_required(self):
        self.enable()
        guild = self.guild()
        token = self.session(config.SUPERADMIN_ID)
        page = self.start(token)
        missing = self.client.post(
            "/companion/connect",
            data={"state": STATE, "csrf": self.hidden(page, "csrf"), "guild": guild["slug"], "decision": "allow"},
            cookies={"ik_session": token},
            follow_redirects=False,
        )
        self.assertEqual(missing.status_code, 403)
        mismatched = self.approve(token, page, guild["slug"], csrf="different-csrf-value")
        self.assertEqual(mismatched.status_code, 403)
        other = self.start(token, state="other-state-0123456789")
        crossed = self.client.post(
            "/companion/connect",
            data={
                "state": "other-state-0123456789",
                "csrf": self.hidden(page, "csrf"),
                "guild": guild["slug"],
                "decision": "allow",
            },
            cookies={"ik_session": token, "ik_companion_csrf": cookie_value(page, "ik_companion_csrf")},
            follow_redirects=False,
        )
        self.assertNotEqual(self.hidden(page, "csrf"), self.hidden(other, "csrf"))
        self.assertEqual(crossed.status_code, 403)
        self.assertEqual(self.count("companion_credentials"), 0)

    def test_cancel_returns_to_loopback_without_a_code(self):
        self.enable()
        guild = self.guild()
        token = self.session(config.SUPERADMIN_ID)
        page = self.start(token)
        denied = self.approve(token, page, guild["slug"], decision="deny")
        self.assertEqual(denied.status_code, 303)
        parsed = urllib.parse.urlparse(denied.headers["location"])
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "127.0.0.1:43123")
        self.assertEqual(parsed.path, "/callback")
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["error"], ["access_denied"])
        self.assertEqual(query["state"], [STATE])
        self.assertNotIn("code", query)
        self.assertEqual(self.count("companion_credentials"), 0)

    def test_the_connection_issues_hashed_rotating_tokens(self):
        guild, website, body, location = self.connect()
        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["state"], [STATE])
        self.assertTrue(body["access_token"].startswith("ika."))
        self.assertTrue(body["refresh_token"].startswith("ikr."))
        self.assertTrue(query["code"][0].startswith("ikn."))
        self.assertEqual(body["expires_in"], ACCESS_SECONDS)
        self.assertEqual(body["refresh_expires_in"], REFRESH_SECONDS)
        self.assertLessEqual(ACCESS_SECONDS, CODE_SECONDS * 20)
        self.assertEqual(body["guild_slug"], guild["slug"])
        self.assertNotIn("discord-access-SHOULD-NOT-LEAK", str(body))
        stored = self.database_bytes()
        self.assertNotIn(body["access_token"].encode(), stored)
        self.assertNotIn(body["refresh_token"].encode(), stored)
        self.assertNotIn(query["code"][0].encode(), stored)
        self.assertIsNone(db.get_session(body["access_token"]))
        columns = self.columns("sessions")
        self.assertEqual(
            columns,
            ["token", "user_id", "name", "username", "access_token", "refresh_token", "expires_at"],
        )
        self.assertNotIn("access_token", self.columns("companion_credentials"))

    def test_pkce_replay_and_concurrent_exchange(self):
        self.enable()
        guild = self.guild()
        token = self.session(config.SUPERADMIN_ID)
        page = self.start(token)
        approved = self.approve(token, page, guild["slug"])
        code = urllib.parse.parse_qs(urllib.parse.urlparse(approved.headers["location"]).query)["code"][0]
        wrong = self.exchange(code, verifier="x" * 50)
        self.assertEqual(wrong.status_code, 401)
        retried = self.exchange(code)
        self.assertEqual(retried.status_code, 401)
        self.assertEqual(self.count("companion_credentials"), 0)

        page = self.start(token, state="second-state-012345678")
        approved = self.approve(token, page, guild["slug"], state="second-state-012345678")
        code = urllib.parse.parse_qs(urllib.parse.urlparse(approved.headers["location"]).query)["code"][0]
        first = self.exchange(code)
        self.assertEqual(first.status_code, 200)
        access = first.json()["access_token"]
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE companion_connect SET used_at = ? WHERE code_hash IS NOT NULL", ("2000-01-01T00:00:00",))
        conn.commit()
        conn.close()
        replay = self.exchange(code)
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(
            self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + access}).status_code,
            401,
        )

        page = self.start(token, state="third-state-0123456789")
        approved = self.approve(token, page, guild["slug"], state="third-state-0123456789")
        code = urllib.parse.parse_qs(urllib.parse.urlparse(approved.headers["location"]).query)["code"][0]
        barrier = threading.Barrier(4)
        raced = []

        def once():
            barrier.wait()
            client = TestClient(main.app)
            try:
                raced.append(client.post(
                    "/api/companion/token",
                    json={
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": VERIFIER,
                        "redirect_uri": LOOPBACK,
                    },
                ).status_code)
            finally:
                client.close()

        threads = [threading.Thread(target=once) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(raced).count(200), 1)
        self.assertEqual(sorted(raced).count(401), 3)

    def test_refresh_rotates_and_reuse_revokes_the_family(self):
        _guild, _website, body, _location = self.connect()
        refreshed = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 200)
        new_body = refreshed.json()
        self.assertNotEqual(new_body["refresh_token"], body["refresh_token"])
        self.assertNotEqual(new_body["access_token"], body["access_token"])
        old_refresh = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(old_refresh.status_code, 401)
        current = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + new_body["access_token"]})
        self.assertEqual(current.status_code, 200)
        previous = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(previous.status_code, 200)

        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            "UPDATE companion_credentials SET rotated_at = ? WHERE rotated_at IS NOT NULL",
            ("2000-01-01T00:00:00",),
        )
        conn.commit()
        conn.close()
        reused = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(reused.status_code, 401)
        killed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + new_body["access_token"]})
        self.assertEqual(killed.status_code, 401)
        again = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": new_body["refresh_token"]},
        )
        self.assertEqual(again.status_code, 401)

    def test_concurrent_refresh_keeps_one_family(self):
        _guild, _website, body, _location = self.connect()
        barrier = threading.Barrier(2)
        raced = []

        def once():
            barrier.wait()
            client = TestClient(main.app)
            try:
                response = client.post(
                    "/api/companion/token",
                    json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
                )
                raced.append((response.status_code, response.json()))
            finally:
                client.close()

        threads = [threading.Thread(target=once) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(item[0] for item in raced), [200, 401])
        winner = next(item[1] for item in raced if item[0] == 200)
        found = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + winner["access_token"]})
        self.assertEqual(found.status_code, 200)

    def test_expiry_revoke_and_website_logout_are_separate(self):
        _guild, website, body, _location = self.connect()
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            "UPDATE companion_credentials SET expires_at = ? WHERE kind = 'access'",
            ("2000-01-01T00:00:00",),
        )
        conn.commit()
        conn.close()
        self.assertEqual(
            self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]}).status_code,
            401,
        )
        refreshed = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 200)
        access = refreshed.json()["access_token"]
        refresh = refreshed.json()["refresh_token"]
        self.client.get("/logout", cookies={"ik_session": website}, follow_redirects=False)
        self.assertIsNone(db.get_session(website))
        self.assertEqual(
            self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + access}).status_code,
            200,
        )
        revoked = self.client.post("/api/companion/revoke", json={"token": refresh})
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.headers.get("cache-control"), "no-store")
        self.assertEqual(
            self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + access}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": refresh}).status_code,
            401,
        )

    def test_upload_rechecks_companion_roles_and_preserves_the_report(self):
        self.enable()
        guild = self.guild(roles=["501"])
        other = self.guild(discord_id="5252", name="Other Guild", roles=["501"])
        user = "3003"
        self.member_roles[(user, guild["id"])] = ["501"]
        self.member_roles[(user, other["id"])] = ["501"]
        token = self.session(user, name="Recruiter", username="recruiter")
        page = self.start(token)
        self.assertIn(guild["name"], page.text)
        self.assertIn(other["name"], page.text)
        approved = self.approve(token, page, guild["slug"])
        code = urllib.parse.parse_qs(urllib.parse.urlparse(approved.headers["location"]).query)["code"][0]
        exchanged = self.exchange(code)
        access = exchanged.json()["access_token"]
        headers = {"Authorization": "Bearer " + access}
        posted = self.client.post("/api/companion/guilds/%s/attendance" % guild["slug"], content=REPORT, headers=headers)
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json(), {"ok": True, "duplicate": False, "place": "Hall of Thanes", "people": 1})
        again = self.client.post("/api/companion/guilds/%s/attendance" % guild["slug"], content=REPORT, headers=headers)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["duplicate"])
        self.assertEqual(db.count_attendance(guild["id"]), 1)

        self.member_roles[(user, guild["id"])] = ["1103"]
        lost = self.client.post("/api/companion/guilds/%s/attendance" % guild["slug"], content=REPORT, headers=headers)
        self.assertEqual(lost.status_code, 403)
        discovered = self.client.get("/api/companion/guilds", headers=headers)
        self.assertEqual(discovered.status_code, 200)
        self.assertEqual(discovered.json()["guilds"], [])
        self.member_roles[(user, guild["id"])] = ["501"]
        restored = self.client.get("/api/companion/guilds", headers=headers)
        self.assertEqual(restored.json()["guilds"], [{"id": guild["id"], "slug": guild["slug"], "name": guild["name"]}])
        cross = self.client.post("/api/companion/guilds/%s/attendance" % other["slug"], content=REPORT, headers=headers)
        self.assertEqual(cross.status_code, 403)
        self.assertEqual(db.count_attendance(other["id"]), 0)

    def test_recruitment_and_the_bot_adder_cannot_upload(self):
        self.enable()
        guild = self.guild(roles=["501"], added_by_id="3003")
        self.member_roles[("3003", guild["id"])] = ["1103"]
        token = self.session("3003", name="Founder", username="founder")
        page = self.start(token)
        self.assertNotIn('name="guild"', page.text)
        csrf = cookie_value(page, "ik_companion_csrf")
        forced = self.client.post(
            "/companion/connect",
            data={"state": STATE, "csrf": csrf, "guild": guild["slug"], "decision": "allow"},
            cookies={"ik_session": token, "ik_companion_csrf": csrf},
            follow_redirects=False,
        )
        self.assertEqual(forced.status_code, 403)
        self.assertNotIn("location", {key.lower() for key in forced.headers})

    def test_the_superadmin_is_the_only_role_exception(self):
        self.enable()
        guild = self.guild(roles=[])
        token = self.session(config.SUPERADMIN_ID)
        self.member_calls.clear()
        page = self.start(token)
        approved = self.approve(token, page, guild["slug"])
        self.assertEqual(approved.status_code, 303)
        self.assertEqual(self.member_calls, [])
        code = urllib.parse.parse_qs(urllib.parse.urlparse(approved.headers["location"]).query)["code"][0]
        exchanged = self.exchange(code)
        access = exchanged.json()["access_token"]
        posted = self.client.post(
            "/api/companion/guilds/%s/attendance" % guild["slug"],
            content=REPORT,
            headers={"Authorization": "Bearer " + access},
        )
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(self.member_calls, [])

    def test_credentials_do_not_cross_and_the_legacy_key_still_works(self):
        guild, website, body, _location = self.connect(roles=["501"])
        access = body["access_token"]
        key = attendance.token_for(guild)
        legacy = self.client.post(
            "/api/%s/attendance" % guild["slug"],
            content=REPORT,
            headers={"Authorization": "Bearer " + key},
        )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()["duplicate"], False)
        for presented in (access, body["refresh_token"], website):
            rejected = self.client.post(
                "/api/%s/attendance" % guild["slug"],
                content=REPORT,
                headers={"Authorization": "Bearer " + presented},
            )
            self.assertEqual(rejected.status_code, 401)
            self.assertEqual(rejected.json()["error"], "Unknown companion key.")
        cookie_only = self.client.post(
            "/api/%s/attendance" % guild["slug"],
            content=REPORT,
            cookies={"ik_session": website},
        )
        self.assertEqual(cookie_only.status_code, 401)
        companion = self.client.post(
            "/api/companion/guilds/%s/attendance" % guild["slug"],
            content=REPORT,
            headers={"Authorization": "Bearer " + key},
        )
        self.assertEqual(companion.status_code, 401)
        website_bearer = self.client.post(
            "/api/companion/guilds/%s/attendance" % guild["slug"],
            content=REPORT,
            headers={"Authorization": "Bearer " + website},
            cookies={"ik_session": website},
        )
        self.assertEqual(website_bearer.status_code, 401)
        as_website = self.client.get("/admin", cookies={"ik_session": access}, follow_redirects=False)
        self.assertEqual(as_website.status_code, 303)
        self.assertTrue(as_website.headers["location"].startswith("/login"))
        logged_out = self.client.post("/api/companion/logout", headers={"Authorization": "Bearer " + access})
        self.assertEqual(logged_out.status_code, 200)
        self.assertIsNotNone(db.get_session(website))
        self.assertEqual(
            self.client.get("/admin", cookies={"ik_session": website}, follow_redirects=False).status_code,
            200,
        )

    def test_companion_roles_survive_a_settings_save_and_start_empty(self):
        self.enable()
        guild = self.guild(roles=["501"])
        self.assertEqual(db.guild_by_slug(guild["slug"])["settings"]["companion_roles"], ["501"])
        fresh = db.guild_by_slug(self.guild(discord_id="6262", name="Empty Guild", roles=None)["slug"])
        self.assertEqual(fresh["settings"]["companion_roles"], [])
        token = self.session(config.SUPERADMIN_ID)
        kept = dict(db.guild_by_slug(guild["slug"])["settings"])
        kept.pop("companion_roles")
        saved = self.client.post(
            "/api/%s/settings" % guild["slug"],
            json=kept,
            cookies={"ik_session": token},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(db.guild_by_slug(guild["slug"])["settings"]["companion_roles"], ["501"])
        updated = dict(db.guild_by_slug(guild["slug"])["settings"])
        updated["companion_roles"] = ["777"]
        changed = self.client.post(
            "/api/%s/settings" % guild["slug"],
            json=updated,
            cookies={"ik_session": token},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(db.guild_by_slug(guild["slug"])["settings"]["companion_roles"], ["777"])
        rejected = self.client.post(
            "/api/%s/settings" % guild["slug"],
            json={"companion_roles": "777"},
            cookies={"ik_session": token},
        )
        self.assertEqual(rejected.status_code, 400)
        page = self.client.get("/%s/settings" % guild["slug"], cookies={"ik_session": token})
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-picker="companion_roles"', page.text)
        self.assertIn("recruitment role does not include this", page.text)

    def test_deleting_a_guild_rejects_its_companion_tokens_and_rejoining_starts_clean(self):
        guild, website, body, _location = self.connect()
        access = body["access_token"]
        refresh = body["refresh_token"]
        headers = {"Authorization": "Bearer " + access}
        posted = self.client.post("/api/companion/guilds/%s/attendance" % guild["slug"], content=REPORT, headers=headers)
        self.assertEqual(posted.status_code, 200)
        self.assertFalse(posted.json()["duplicate"])
        db.upsert_guild("7777", "Other Keep", [], [])
        other = db.guild_by_slug("otherkeep")
        kept = {
            "place": "Other Hall",
            "started": "2026-11-02 12:00",
            "received_at": "2026-11-04T19:00:00+00:00",
            "people": [],
            "digest": "other-digest",
        }
        self.assertTrue(db.add_attendance(other["id"], kept))
        pending_state = "pending-state-0123456789"
        page = self.start(website, state=pending_state)
        approved = self.approve(website, page, guild["slug"], state=pending_state)
        self.assertEqual(approved.status_code, 303)
        pending_code = urllib.parse.parse_qs(urllib.parse.urlparse(approved.headers["location"]).query)["code"][0]
        conn = sqlite3.connect(config.DB_PATH)
        for name in ("companion_connect", "companion_credentials"):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]
            self.assertNotIn("FOREIGN KEY", sql.upper())
        conn.execute(
            """INSERT INTO companion_credentials
               (token_hash, family_id, kind, user_id, name, username, guild_id, guild_slug, created_at, expires_at)
               VALUES ('other-hash', 'other-family', 'refresh', '1001', 'Other', 'other', '7777', 'otherkeep',
                       '2026-11-01T00:00:00', '2099-01-01T00:00:00')"""
        )
        conn.commit()
        conn.close()
        db.create_trial(guild, "9", "Ada", "ada", start="2026-11-01", content_roles=[], albion_name=None, text="joined")

        db.delete_guild(guild["slug"])
        self.assertIsNone(db.guild_by_id(guild["id"]))
        self.assertEqual(db.count_attendance(guild["id"]), 0)
        self.assertEqual(db.count_attendance_hashes(guild["id"]), 0)
        self.assertEqual(self.bound("companion_credentials", guild["id"], guild["slug"]), 0)
        self.assertEqual(self.bound("companion_connect", guild["id"], guild["slug"]), 0)
        self.assertEqual(self.bound("companion_credentials", "7777", "otherkeep"), 1)
        self.assertFalse(db.add_attendance(other["id"], kept))

        stale_refresh = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": refresh},
        )
        self.assertEqual(stale_refresh.status_code, 401)
        stale_upload = self.client.post(
            "/api/companion/guilds/%s/attendance" % guild["slug"],
            content=REPORT,
            headers=headers,
        )
        self.assertEqual(stale_upload.status_code, 401)
        self.assertEqual(self.exchange(pending_code).status_code, 401)

        db.upsert_guild(guild["id"], "Forever Guild", [], [])
        revived = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": refresh},
        )
        self.assertEqual(revived.status_code, 401)
        reborn, _website, fresh, _location = self.connect()
        self.assertEqual(reborn["id"], guild["id"])
        uploaded = self.client.post(
            "/api/companion/guilds/%s/attendance" % reborn["slug"],
            content=REPORT,
            headers={"Authorization": "Bearer " + fresh["access_token"]},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertFalse(uploaded.json()["duplicate"])
        duplicate = self.client.post(
            "/api/companion/guilds/%s/attendance" % reborn["slug"],
            content=REPORT,
            headers={"Authorization": "Bearer " + fresh["access_token"]},
        )
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(db.count_attendance_hashes(other["id"]), 1)
        self.assertEqual(self.bound("companion_credentials", "7777", "otherkeep"), 1)

    def bound(self, table, guild_id, slug):
        conn = sqlite3.connect(config.DB_PATH)
        found = conn.execute(
            "SELECT COUNT(*) FROM %s WHERE guild_id = ? OR guild_slug = ?" % table,
            (guild_id, slug),
        ).fetchone()[0]
        conn.close()
        return found

    def tables(self):
        conn = sqlite3.connect(config.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        return names

    def columns(self, table):
        conn = sqlite3.connect(config.DB_PATH)
        found = [row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)]
        conn.close()
        return found

    def count(self, table):
        conn = sqlite3.connect(config.DB_PATH)
        try:
            found = conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        except sqlite3.OperationalError:
            found = 0
        conn.close()
        return found

    def database_bytes(self):
        blob = b""
        for name in os.listdir(self.tmp):
            with open(os.path.join(self.tmp, name), "rb") as handle:
                blob += handle.read()
        return blob


if __name__ == "__main__":
    unittest.main()
