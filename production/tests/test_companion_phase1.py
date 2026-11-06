"""Phase 1 Companion login against the production backend.

Run from the repository root:

    PYTHONPATH=production python3 -m unittest production.tests.test_companion_phase1

The database is a temporary file. Discord role lookups are patched.
"""

import ast
import http.cookies
import inspect
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["IRONKEEP_COMPANION_CACHE"] = str(ROOT / "tests" / "fixtures" / "forever.json")
os.environ["IRONKEEP_WOW_CATALOG"] = str(ROOT / "tests" / "fixtures" / "wow.json")
os.environ.pop("IRONKEEP_DB", None)
os.environ.pop("IRONKEEP_COMPANION_AUTH", None)

from fastapi.testclient import TestClient

from ironkeep import companion_auth, config, db, discord_api, main
from ironkeep.companion_auth import REUSE_GRACE_SECONDS, pkce_s256

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


class Phase1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "phase1.sqlite")
        self.assertNotIn("/var/lib/ironkeep/ironkeep.db", self.db_path)
        os.environ.pop("IRONKEEP_COMPANION_AUTH", None)
        config.BOT_TOKEN = "bot-token"
        config.CLIENT_ID = "ironkeep-client"
        config.CLIENT_SECRET = "client-secret-stays-on-the-server"
        config.PUBLIC_URL = "https://ironkeep.gg"
        config.DB_PATH = self.db_path
        db.init()
        self.client = TestClient(main.app)
        self.member_roles = {}

        def member_as_bot(guild_id, user_id):
            found = self.member_roles.get((str(user_id), str(guild_id)))
            if found is None:
                raise discord_api.DiscordError(404, {})
            if found == "down":
                raise discord_api.DiscordError(503, {})
            return {"roles": list(found)}

        self._member = patch("ironkeep.discord_api.member_as_bot", side_effect=member_as_bot)
        self._member.start()
        self.addCleanup(self._member.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def tables(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()

    def enable(self):
        os.environ["IRONKEEP_COMPANION_AUTH"] = "1"

    def guild(self, discord_id, slug, settings):
        db.upsert_guild(discord_id, slug, [], [])
        db.set_approval(slug, "approved")
        db.save_settings(slug, settings)
        return db.guild_by_slug(slug)

    def albion_settings(self, companion=None):
        settings = db.default_settings()
        settings["game"] = "albion"
        settings["albion"]["guild_name"] = "Keep"
        settings["recruitment_roles"] = ["10"]
        settings["messages"]["welcome"]["text"] = "welcome-text"
        if companion is not None:
            settings["companion_roles"] = list(companion)
        return settings

    def wow_settings(self, companion=None):
        settings = self.albion_settings(companion)
        settings["game"] = "wow"
        settings["wow"] = {"raid_channel": "1", "poster_roles": ["5"]}
        return settings

    def session(self, user_id="100"):
        self.website = db.create_session(user_id, "Ada", "ada", "discord-access", "discord-refresh", 3600)
        return self.website

    def connect_query(self, state=STATE):
        return {
            "response_type": "code",
            "client_id": "ironkeep-companion",
            "redirect_uri": LOOPBACK,
            "state": state,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        }

    def allow(self, slug, state=STATE):
        page = self.client.get("/companion/connect", params=self.connect_query(state), cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200, page.text)
        csrf = cookie_value(page, "ik_companion_csrf")
        response = self.client.post(
            "/companion/connect",
            data={"state": state, "csrf": csrf, "decision": "allow", "guild": slug},
            cookies={"ik_session": self.website, "ik_companion_csrf": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(response.headers["location"]).query)
        return query["code"][0], query["state"][0]

    def exchange(self, code, state=STATE):
        response = self.client.post(
            "/api/companion/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": LOOPBACK,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(LOOPBACK).query), {})
        body = response.json()
        self.assertTrue(pkce_s256(VERIFIER) == CHALLENGE)
        self.assertEqual(state, STATE)
        return body

    def test_flag_off_hides_routes_and_leaves_website_login(self):
        response = self.client.get("/companion/connect", params=self.connect_query())
        self.assertEqual(response.status_code, 404)
        for path in (
            "/api/companion/token",
            "/api/companion/revoke",
            "/api/companion/logout",
            "/api/companion/guilds",
            "/api/companion/guilds/keep/attendance",
        ):
            self.assertEqual(self.client.post(path).status_code, 404)
        self.assertNotIn("companion_connect", self.tables())
        self.assertNotIn("companion_credentials", self.tables())
        self.assertNotIn("companion_reports", self.tables())
        login = self.client.get("/login", follow_redirects=False)
        self.assertEqual(login.status_code, 303)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(login.headers["location"]).query)
        self.assertEqual(query["scope"], ["identify guilds guilds.members.read"])
        self.assertEqual(query["redirect_uri"], ["https://ironkeep.gg/auth/callback"])
        self.assertNotIn("/api/companion/guilds/keep/attendance", login.headers["location"])

    def test_successful_login_is_bound_to_the_selected_guild(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.guild("2", "other", self.wow_settings(["88"]))
        self.member_roles[("100", "1")] = ["77"]
        self.member_roles[("100", "2")] = ["88"]
        self.session()
        code, state = self.allow("keep")
        body = self.exchange(code, state)
        self.assertEqual(body["guild_slug"], "keep")
        self.assertNotIn("other", json.dumps(body))
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["slug"] for item in listed.json()["guilds"]], ["keep"])
        upload = self.client.post(
            "/api/companion/guilds/keep/attendance",
            headers={"Authorization": "Bearer " + body["access_token"]},
        )
        self.assertEqual(upload.status_code, 415)
        self.assertEqual(upload.json()["ok"], False)
        self.assertNotIn(body["access_token"], upload.text)
        self.assertNotIn("companion_reports", self.tables())

    def test_invalid_redirect_and_bad_token_request_are_refused(self):
        self.enable()
        bad = self.client.get("/companion/connect", params={**self.connect_query(), "redirect_uri": "https://evil.example/callback"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("not valid", bad.text)
        token = self.client.post("/api/companion/token", json={"grant_type": "nope"})
        self.assertEqual(token.status_code, 400)

    def test_expired_access_token_is_refused(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        body = self.exchange(code)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE companion_credentials SET expires_at = ? WHERE kind = 'access'",
            ("2000-01-01T00:00:00",),
        )
        conn.commit()
        conn.close()
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(listed.status_code, 401)

    def test_other_guild_and_missing_role_are_refused(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.guild("2", "other", self.wow_settings(["88"]))
        self.member_roles[("100", "1")] = ["10"]
        self.member_roles[("100", "2")] = ["88"]
        self.session()
        page = self.client.get("/companion/connect", params=self.connect_query(), cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('value="keep"', page.text)
        self.assertIn('value="other"', page.text)
        csrf = cookie_value(page, "ik_companion_csrf")
        refused = self.client.post(
            "/companion/connect",
            data={"state": STATE, "csrf": csrf, "decision": "allow", "guild": "keep"},
            cookies={"ik_session": self.website, "ik_companion_csrf": csrf},
        )
        self.assertEqual(refused.status_code, 403)
        code, _state = self.allow("other", state="state-value-other-guild-01")
        swapped = self.client.post(
            "/api/companion/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": "http://127.0.0.1:9/stolen",
            },
        )
        self.assertEqual(swapped.status_code, 401)

    def test_recruitment_and_wow_poster_roles_do_not_grant_companion_access(self):
        self.enable()
        settings = self.albion_settings([])
        settings["recruitment_roles"] = ["10"]
        self.guild("1", "keep", settings)
        wow = db.default_settings()
        wow["game"] = "wow"
        wow["recruitment_roles"] = []
        wow["companion_roles"] = []
        wow["wow"] = {"poster_roles": ["5"], "raid_channel": "1"}
        self.guild("3", "raiders", wow)
        self.member_roles[("100", "1")] = ["10"]
        self.member_roles[("100", "3")] = ["5"]
        self.session()
        page = self.client.get("/companion/connect", params=self.connect_query(), cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(">keep<", page.text)
        self.assertNotIn(">raiders<", page.text)
        poster = {"user_id": "100", "access_token": "discord-access", "refresh_token": ""}
        with patch("ironkeep.discord_api.guild_member", return_value={"roles": ["10"]}):
            self.assertTrue(main.can_access(poster, db.guild_by_slug("keep")))
        with patch("ironkeep.discord_api.guild_member", return_value={"roles": ["5"]}):
            self.assertTrue(main.can_access(poster, db.guild_by_slug("raiders")))
        with patch("ironkeep.discord_api.guild_member", return_value={"roles": ["77"]}):
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM member_cache")
            conn.commit()
            conn.close()
            raiders = db.guild_by_slug("raiders")
            raiders["settings"]["companion_roles"] = ["77"]
            self.assertFalse(main.can_access(poster, raiders))

    def test_superadmin_can_connect_when_the_role_list_is_empty(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings([]))
        self.member_roles[(config.SUPERADMIN_ID, "1")] = []
        self.session(config.SUPERADMIN_ID)
        code, _state = self.allow("keep")
        body = self.exchange(code)
        self.assertEqual(body["guild_slug"], "keep")

    def credential_rows(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT guild_slug, kind FROM companion_credentials").fetchall()
        finally:
            conn.close()

    def test_missing_membership_role_and_lost_permission_never_issue_a_token(self):
        self.enable()
        self.guild("10", "derelict", self.wow_settings(["77"]))
        self.guild("11", "chaos", self.wow_settings(["77"]))
        self.guild("12", "herberg", self.wow_settings(["77"]))
        self.guild("13", "ironkeep", self.wow_settings(["77"]))
        for guild_id in ("11", "12", "13"):
            self.member_roles[("100", guild_id)] = ["77"]
        self.session()
        page = self.client.get("/companion/connect", params=self.connect_query(), cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('value="derelict"', page.text)
        for slug in ("chaos", "herberg", "ironkeep"):
            self.assertIn(f'value="{slug}"', page.text)
        csrf = cookie_value(page, "ik_companion_csrf")
        missing = self.client.post(
            "/companion/connect",
            data={"state": STATE, "csrf": csrf, "decision": "allow", "guild": "derelict"},
            cookies={"ik_session": self.website, "ik_companion_csrf": csrf},
            follow_redirects=False,
        )
        self.assertEqual(missing.status_code, 403)
        self.assertNotIn("code=", missing.headers.get("location", ""))
        self.member_roles[("100", "12")] = ["10"]
        role_page = self.client.get(
            "/companion/connect",
            params=self.connect_query("state-value-missing-role"),
            cookies={"ik_session": self.website},
        )
        self.assertNotIn('value="herberg"', role_page.text)
        self.assertNotIn('value="derelict"', role_page.text)
        self.assertIn('value="chaos"', role_page.text)
        role_csrf = cookie_value(role_page, "ik_companion_csrf")
        missing_role = self.client.post(
            "/companion/connect",
            data={"state": "state-value-missing-role", "csrf": role_csrf, "decision": "allow", "guild": "herberg"},
            cookies={"ik_session": self.website, "ik_companion_csrf": role_csrf},
            follow_redirects=False,
        )
        self.assertEqual(missing_role.status_code, 403)
        self.assertEqual(self.credential_rows(), [])

        self.member_roles[(config.SUPERADMIN_ID, "11")] = []
        self.session(config.SUPERADMIN_ID)
        admin_page = self.client.get(
            "/companion/connect",
            params=self.connect_query("state-value-admin-member"),
            cookies={"ik_session": self.website},
        )
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn('value="chaos"', admin_page.text)
        for slug in ("derelict", "herberg", "ironkeep"):
            self.assertNotIn(f'value="{slug}"', admin_page.text)
        admin_csrf = cookie_value(admin_page, "ik_companion_csrf")
        admin_missing = self.client.post(
            "/companion/connect",
            data={"state": "state-value-admin-member", "csrf": admin_csrf, "decision": "allow", "guild": "derelict"},
            cookies={"ik_session": self.website, "ik_companion_csrf": admin_csrf},
            follow_redirects=False,
        )
        self.assertEqual(admin_missing.status_code, 403)

        shown = self.client.get(
            "/companion/connect",
            params=self.connect_query("state-value-admin-recheck"),
            cookies={"ik_session": self.website},
        )
        self.assertIn('value="chaos"', shown.text)
        del self.member_roles[(config.SUPERADMIN_ID, "11")]
        rechecked = self.client.post(
            "/companion/connect",
            data={"state": "state-value-admin-recheck", "csrf": cookie_value(shown, "ik_companion_csrf"), "decision": "allow", "guild": "chaos"},
            cookies={"ik_session": self.website, "ik_companion_csrf": cookie_value(shown, "ik_companion_csrf")},
            follow_redirects=False,
        )
        self.assertEqual(rechecked.status_code, 403)
        self.assertEqual(self.credential_rows(), [])

        self.member_roles[(config.SUPERADMIN_ID, "11")] = []
        code, _state = self.allow("chaos", state="state-value-admin-exchange")
        del self.member_roles[(config.SUPERADMIN_ID, "11")]
        exchanged = self.client.post(
            "/api/companion/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": LOOPBACK,
            },
        )
        self.assertEqual(exchanged.status_code, 403)
        self.assertNotIn("access_token", exchanged.text)
        self.assertEqual(self.credential_rows(), [])

        self.member_roles[("100", "11")] = ["77"]
        self.session()
        code, _state = self.allow("chaos", state="state-value-leave-guild")
        body = self.exchange(code)
        del self.member_roles[("100", "11")]
        left = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(left.status_code, 403)
        left_again = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(left_again.status_code, 401)
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(listed.status_code, 401)

        self.member_roles[("100", "11")] = ["77"]
        code, _state = self.allow("chaos", state="state-value-lose-role")
        body = self.exchange(code)
        self.member_roles[("100", "11")] = ["10"]
        lost = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(lost.status_code, 403)
        lost_again = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(lost_again.status_code, 401)

    def test_refresh_rotates_and_reuse_revokes_the_family(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        first = self.exchange(code)
        reused = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        self.assertEqual(reused.status_code, 200, reused.text)
        self.assertNotEqual(reused.json()["refresh_token"], first["refresh_token"])
        conn = sqlite3.connect(self.db_path)
        old = (datetime.now(timezone.utc) - timedelta(seconds=REUSE_GRACE_SECONDS + 5)).strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "UPDATE companion_credentials SET rotated_at = ? WHERE token_hash != '' AND kind = 'refresh' AND rotated_at IS NOT NULL",
            (old,),
        )
        conn.commit()
        conn.close()
        again = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        self.assertEqual(again.status_code, 401)
        follow = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": reused.json()["refresh_token"]},
        )
        self.assertEqual(follow.status_code, 401)

    def test_refresh_inside_the_grace_period_does_not_revoke_the_new_token(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        first = self.exchange(code)
        reused = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        self.assertEqual(reused.status_code, 200)
        immediate = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        self.assertEqual(immediate.status_code, 401)
        follow = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": reused.json()["refresh_token"]},
        )
        self.assertEqual(follow.status_code, 200, follow.text)

    def test_revoked_refresh_token_stays_refused(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        body = self.exchange(code)
        goodbye = self.client.post("/api/companion/logout", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(goodbye.status_code, 200)
        again = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
        self.assertEqual(again.status_code, 401)
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(listed.status_code, 401)

    def test_losing_the_role_blocks_refresh_and_guild_lookup(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        body = self.exchange(code)
        self.member_roles[("100", "1")] = ["10"]
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(listed.status_code, 403)
        refreshed = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
        self.assertEqual(refreshed.status_code, 401)

    def test_discord_outage_does_not_revoke_the_refresh_token(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        body = self.exchange(code)
        self.member_roles[("100", "1")] = "down"
        stalled = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
        self.assertEqual(stalled.status_code, 503)
        self.member_roles[("100", "1")] = ["77"]
        recovered = self.client.post("/api/companion/token", json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
        self.assertEqual(recovered.status_code, 200, recovered.text)

    def test_companion_role_changes_keep_albion_and_wow_settings(self):
        self.enable()
        self.session(config.SUPERADMIN_ID)
        settings = self.albion_settings(["77"])
        self.guild("1", "keep", settings)
        settings["companion_roles"] = []
        saved = self.client.post("/api/keep/settings", json=settings, cookies={"ik_session": self.website})
        self.assertEqual(saved.status_code, 200, saved.text)
        fresh = db.guild_by_slug("keep")
        self.assertEqual(fresh["settings"]["companion_roles"], [])
        self.assertEqual(fresh["settings"]["recruitment_roles"], ["10"])
        self.assertEqual(fresh["settings"]["albion"]["guild_name"], "Keep")
        self.assertEqual(fresh["settings"]["messages"]["welcome"]["text"], "welcome-text")
        wow = db.default_settings()
        wow["game"] = "wow"
        wow["albion"]["guild_name"] = "still-here"
        wow["companion_roles"] = ["9"]
        wow["tickets"] = {"enabled": False, "language": "en"}
        self.guild("3", "raiders", wow)
        self.assertTrue(db.save_wow_settings("raiders", "55", ["5"], "Europe/Amsterdam", companion_roles=["8"]))
        stored = db.guild_by_slug("raiders")["settings"]
        self.assertEqual(stored["companion_roles"], ["8"])
        self.assertEqual(stored["wow"]["poster_roles"], ["5"])
        self.assertEqual(stored["wow"]["raid_channel"], "55")
        self.assertEqual(stored["albion"]["guild_name"], "still-here")
        self.assertEqual(stored["tickets"]["language"], "en")
        self.assertTrue(db.save_wow_settings("raiders", "55", ["5"], "Europe/Amsterdam"))
        kept = db.guild_by_slug("raiders")["settings"]
        self.assertEqual(kept["companion_roles"], ["8"])
        self.assertEqual(kept["wow"]["poster_roles"], ["5"])
        self.assertEqual(kept["tickets"]["language"], "en")

    def test_overlapping_refresh_rotates_once_after_discord_returns(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.session()
        code, _state = self.allow("keep")
        first = self.exchange(code)
        arrived = threading.Barrier(2)
        delay = REUSE_GRACE_SECONDS + 1

        def slow(guild_id, user_id):
            arrived.wait(timeout=5)
            time.sleep(delay)
            return {"roles": ["77"]}

        results = []

        def refresh():
            results.append(
                companion_auth._refresh({"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
            )

        with patch("ironkeep.discord_api.member_as_bot", side_effect=slow):
            workers = [threading.Thread(target=refresh) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=delay + 5)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sorted(result.status_code for result in results), [200, 401])
        winner = next(result for result in results if result.status_code == 200)
        issued = json.loads(winner.body)
        conn = sqlite3.connect(self.db_path)
        rotated_at = conn.execute(
            "SELECT rotated_at FROM companion_credentials WHERE kind = 'refresh' AND rotated_at IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        rotated = datetime.strptime(rotated_at, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        self.assertLess((datetime.now(timezone.utc) - rotated).total_seconds(), REUSE_GRACE_SECONDS)
        reused = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]},
        )
        self.assertEqual(reused.status_code, 401)
        follow = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": issued["refresh_token"]},
        )
        self.assertEqual(follow.status_code, 200, follow.text)


    def test_only_wow_guilds_stay_eligible_after_a_profile_change(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.guild("2", "albion", self.albion_settings(["77"]))
        unset = db.default_settings()
        unset.pop("game", None)
        unset["companion_roles"] = ["77"]
        self.guild("3", "unset", unset)
        for guild_id in ("1", "2", "3"):
            self.member_roles[("100", guild_id)] = ["77"]
            self.member_roles[(config.SUPERADMIN_ID, guild_id)] = []
        self.session()
        page = self.client.get("/companion/connect", params=self.connect_query(), cookies={"ik_session": self.website})
        self.assertEqual(page.status_code, 200)
        self.assertIn('value="keep"', page.text)
        self.assertNotIn('value="albion"', page.text)
        self.assertNotIn('value="unset"', page.text)
        csrf = cookie_value(page, "ik_companion_csrf")
        for slug in ("albion", "unset"):
            refused = self.client.post(
                "/companion/connect",
                data={"state": STATE, "csrf": csrf, "decision": "allow", "guild": slug},
                cookies={"ik_session": self.website, "ik_companion_csrf": csrf},
                follow_redirects=False,
            )
            self.assertEqual(refused.status_code, 403, slug)
            self.assertNotIn("code=", refused.headers.get("location", ""))
        self.session(config.SUPERADMIN_ID)
        admin = self.client.get(
            "/companion/connect",
            params=self.connect_query("state-value-admin-game"),
            cookies={"ik_session": self.website},
        )
        self.assertIn('value="keep"', admin.text)
        self.assertNotIn('value="albion"', admin.text)
        self.assertNotIn('value="unset"', admin.text)
        admin_csrf = cookie_value(admin, "ik_companion_csrf")
        admin_refused = self.client.post(
            "/companion/connect",
            data={"state": "state-value-admin-game", "csrf": admin_csrf, "decision": "allow", "guild": "albion"},
            cookies={"ik_session": self.website, "ik_companion_csrf": admin_csrf},
            follow_redirects=False,
        )
        self.assertEqual(admin_refused.status_code, 403)

        self.session()
        code, _state = self.allow("keep", state="state-value-game-exchange")
        switched = db.guild_by_slug("keep")["settings"]
        switched["game"] = "albion"
        db.save_settings("keep", switched)
        exchanged = self.client.post(
            "/api/companion/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": LOOPBACK,
            },
        )
        self.assertEqual(exchanged.status_code, 403)
        self.assertNotIn("access_token", exchanged.text)
        self.assertEqual(self.credential_rows(), [])

        switched["game"] = "wow"
        db.save_settings("keep", switched)
        code, _state = self.allow("keep", state="state-value-game-refresh")
        body = self.exchange(code)
        switched = db.guild_by_slug("keep")["settings"]
        switched["game"] = "albion"
        db.save_settings("keep", switched)
        refreshed = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 403)
        self.assertNotIn("access_token", refreshed.text)
        refreshed_again = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]},
        )
        self.assertEqual(refreshed_again.status_code, 401)
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(listed.status_code, 401)

        switched["game"] = "wow"
        db.save_settings("keep", switched)
        code, _state = self.allow("keep", state="state-value-game-access")
        body = self.exchange(code)
        switched = db.guild_by_slug("keep")["settings"]
        switched["game"] = "albion"
        db.save_settings("keep", switched)
        current = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(current.status_code, 403)
        self.assertNotIn("keep", current.text)
        current_again = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + body["access_token"]})
        self.assertEqual(current_again.status_code, 401)


class RoleLookupDefinitions(unittest.TestCase):
    def test_live_role_lookups_keep_separate_names(self):
        tree = ast.parse(Path(discord_api.__file__).read_text(encoding="utf-8"))
        defined = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(defined.count("bot_member"), 1)
        self.assertEqual(defined.count("member_as_bot"), 1)
        self.assertEqual(list(inspect.signature(discord_api.bot_member).parameters), ["guild_id"])
        self.assertEqual(list(inspect.signature(discord_api.member_as_bot).parameters), ["guild_id", "user_id"])
        self.assertIn("member_as_bot", companion_auth._member_roles.__code__.co_names)
        self.assertNotIn("bot_member", companion_auth._member_roles.__code__.co_names)
