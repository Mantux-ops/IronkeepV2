"""Phase 2 Companion attendance upload against the production backend.

Run from the repository root:

    PYTHONPATH=production python3 -m unittest production.tests.test_companion_phase2
"""

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["IRONKEEP_COMPANION_CACHE"] = str(ROOT / "tests" / "fixtures" / "forever.json")
os.environ["IRONKEEP_WOW_CATALOG"] = str(ROOT / "tests" / "fixtures" / "wow.json")
os.environ.pop("IRONKEEP_DB", None)
os.environ.pop("IRONKEEP_COMPANION_AUTH", None)

from fastapi.testclient import TestClient

from ironkeep import companion_reports, config, db
from production.tests import test_companion_phase1 as phase1


def report(people=None, place="Hall of Thanes", started="2026-11-01 12:00"):
    rows = people
    if rows is None:
        rows = [
            ("Theron Swiftblade", "Warrior", "Tank", "<1m", "here"),
            ("Ada Smith", "Priest", "Healer", "1h 5m", "left"),
        ]
    lines = [
        "Ironkeep group",
        "Place: " + place,
        "Started: " + started,
        "",
        "Name | Class | Role | Time | Status",
    ]
    for name, class_name, role, seen, status in rows:
        lines.append(" | ".join((name, class_name, role, seen, status)))
    lines.extend(["", "format: ironkeep-group 1"])
    return "\n".join(lines)


class ReportParserTests(unittest.TestCase):
    def test_forever_names_and_short_visits_match_the_companion_text(self):
        parsed = companion_reports.parse_text(report())
        self.assertEqual(parsed["place"], "Hall of Thanes")
        self.assertEqual(parsed["people"][0]["name"], "Theron Swiftblade")
        self.assertEqual(parsed["people"][0]["time"], "<1m")
        self.assertTrue(parsed["people"][0]["here"])
        self.assertFalse(parsed["people"][1]["here"])
        self.assertEqual(companion_reports.digest(report()), companion_reports.digest(report().replace("\n", "\r\n")))
        self.assertEqual(companion_reports.parse_text(report(place="Zul'Gurub"))["place"], "Zul'Gurub")

    def test_unknown_and_a_single_given_name_are_accepted(self):
        parsed = companion_reports.parse_text(
            report([("Unknown", "Mage", "", "20m", "here"), ("Bram", "Death Knight", "Damage", "", "left")])
        )
        self.assertEqual([person["name"] for person in parsed["people"]], ["Unknown", "Bram"])
        self.assertEqual(parsed["people"][1]["class_name"], "Death Knight")
        localized = companion_reports.parse_text(report([("Theron Swiftblade", "Jäger", "Damage", "4m", "here")]))
        self.assertEqual(localized["people"][0]["class_name"], "Jäger")
        self.assertEqual(parsed["people"][1]["role"], "Damage")

    def test_names_outside_the_forever_rule_are_rejected(self):
        for name in ("A", "Theron Swiftblade Junior", "O'Brien", "Ada<script>", "Ada Smith\nformat"):
            with self.assertRaises(companion_reports.ReportError):
                companion_reports.parse_text(report([(name, "Warrior", "Tank", "5m", "here")]))

    def test_a_report_without_the_format_line_is_rejected(self):
        with self.assertRaises(companion_reports.ReportError):
            companion_reports.parse_text("Ironkeep group\nPlace: Hall\n")


class UploadTests(unittest.TestCase):
    setUp = phase1.Phase1Tests.setUp
    enable = phase1.Phase1Tests.enable
    guild = phase1.Phase1Tests.guild
    albion_settings = phase1.Phase1Tests.albion_settings
    wow_settings = phase1.Phase1Tests.wow_settings
    session = phase1.Phase1Tests.session
    connect_query = phase1.Phase1Tests.connect_query
    allow = phase1.Phase1Tests.allow
    exchange = phase1.Phase1Tests.exchange

    def post_report(self, token, slug="keep", body=None, content_type="text/plain; charset=utf-8"):
        headers = {"Authorization": "Bearer " + token}
        if content_type is not None:
            headers["Content-Type"] = content_type
        return self.client.post(
            "/api/companion/guilds/%s/attendance" % slug,
            content=(report() if body is None else body).encode("utf-8"),
            headers=headers,
        )

    def issue(self, user_id="100", state=phase1.STATE):
        self.session(user_id)
        code, _state = self.allow("keep", state=state)
        return self.exchange(code)

    def report_count(self, guild_id="1"):
        conn = sqlite3.connect(self.db_path)
        try:
            reports = conn.execute("SELECT COUNT(*) FROM companion_reports WHERE guild_id = ?", (guild_id,)).fetchone()[0]
            hashes = conn.execute(
                "SELECT COUNT(*) FROM companion_report_hashes WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()[0]
            raids = conn.execute("SELECT COUNT(*) FROM raid_attendance").fetchone()[0]
            return reports, hashes, raids
        except sqlite3.OperationalError:
            return 0, 0, 0
        finally:
            conn.close()

    def test_a_wow_member_can_upload_and_a_repeat_is_a_duplicate(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        body = self.issue()
        first = self.post_report(body["access_token"])
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), {"ok": True})
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertNotIn(body["access_token"], first.text)
        self.assertEqual(self.report_count(), (1, 1, 0))
        stored = sqlite3.connect(self.db_path).execute("SELECT people_json FROM companion_reports").fetchone()[0]
        self.assertIn("Theron Swiftblade", stored)
        self.assertNotIn("format: ironkeep-group 1", stored)
        again = self.post_report(body["access_token"], body=report().replace("\n", "\r\n"))
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json(), {"ok": True, "duplicate": True})
        self.assertEqual(self.report_count(), (1, 1, 0))

    def test_invalid_format_oversized_body_and_storage_failure_store_nothing(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        token = self.issue()["access_token"]
        broken = self.post_report(token, body="not a report")
        self.assertEqual(broken.status_code, 400)
        self.assertEqual(broken.json()["ok"], False)
        self.assertNotIn(token, broken.text)
        huge = "x" * (companion_reports.MAX_BYTES + 1)
        oversized = self.post_report(token, body=huge)
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()["error"], "This report is too large.")
        self.assertEqual(self.report_count(), (0, 0, 0))
        with patch("ironkeep.companion_reports.store", side_effect=RuntimeError("Theron Swiftblade " + token)):
            failed = self.post_report(token)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json(), {"ok": False, "error": "The report could not be stored."})
        self.assertNotIn(token, failed.text)
        self.assertNotIn("Theron", failed.text)
        self.assertEqual(self.report_count(), (0, 0, 0))

    def test_the_url_slug_must_be_the_guild_bound_to_the_token(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.guild("2", "other", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.member_roles[("100", "2")] = ["77"]
        token = self.issue()["access_token"]
        wrong = self.post_report(token, slug="other")
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(self.report_count("2"), (0, 0, 0))
        listed = self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + token})
        self.assertEqual(listed.status_code, 200)
        saved = self.post_report(token, slug="KEEP")
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.report_count(), (1, 1, 0))

    def test_albion_and_an_unset_profile_are_rejected_and_the_family_ends(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        issued = self.issue()
        settings = db.guild_by_slug("keep")["settings"]
        settings["game"] = "albion"
        db.save_settings("keep", settings)
        refused = self.post_report(issued["access_token"])
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.report_count(), (0, 0, 0))
        self.assertEqual(
            self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + issued["access_token"]}).status_code,
            401,
        )

        settings["game"] = "wow"
        db.save_settings("keep", settings)
        self.member_roles[("100", "1")] = ["77"]
        issued = self.issue(state="state-value-upload-unset")
        unset = db.default_settings()
        unset.pop("game", None)
        unset["companion_roles"] = ["77"]
        db.save_settings("keep", unset)
        self.assertIsNone(db.guild_game(db.guild_by_slug("keep")["settings"]))
        missing = self.post_report(issued["access_token"])
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(self.report_count(), (0, 0, 0))
        refreshed = self.client.post(
            "/api/companion/token",
            json={"grant_type": "refresh_token", "refresh_token": issued["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 401)

    def test_a_non_member_and_a_missing_role_cannot_upload(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        self.member_roles[(config.SUPERADMIN_ID, "1")] = []
        token = self.issue()["access_token"]
        del self.member_roles[("100", "1")]
        missing = self.post_report(token)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(self.report_count(), (0, 0, 0))

        self.member_roles[("100", "1")] = ["77"]
        token = self.issue(state="state-value-upload-role")["access_token"]
        self.member_roles[("100", "1")] = ["10"]
        role = self.post_report(token)
        self.assertEqual(role.status_code, 403)
        self.assertEqual(self.report_count(), (0, 0, 0))

        self.session(config.SUPERADMIN_ID)
        code, _state = self.allow("keep", state="state-value-admin-upload")
        admin = self.exchange(code)
        del self.member_roles[(config.SUPERADMIN_ID, "1")]
        blocked = self.post_report(admin["access_token"])
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(self.report_count(), (0, 0, 0))

    def test_a_revoked_token_and_a_discord_outage_do_not_store_a_report(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        issued = self.issue()
        self.client.post("/api/companion/logout", headers={"Authorization": "Bearer " + issued["access_token"]})
        revoked = self.post_report(issued["access_token"])
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(self.report_count(), (0, 0, 0))

        issued = self.issue(state="state-value-upload-retry")
        self.member_roles[("100", "1")] = "down"
        outage = self.post_report(issued["access_token"])
        self.assertEqual(outage.status_code, 503)
        self.assertEqual(self.report_count(), (0, 0, 0))
        self.member_roles[("100", "1")] = ["77"]
        recovered = self.post_report(issued["access_token"])
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(self.report_count(), (1, 1, 0))

    def test_authorization_is_checked_again_after_a_successful_upload(self):
        self.enable()
        self.guild("1", "keep", self.wow_settings(["77"]))
        self.member_roles[("100", "1")] = ["77"]
        token = self.issue()["access_token"]
        self.assertEqual(self.post_report(token).status_code, 200)
        self.member_roles[("100", "1")] = ["10"]
        second = self.post_report(token, body=report([("Mira Stone", "Mage", "Damage", "8m", "here")]))
        self.assertEqual(second.status_code, 403)
        self.assertEqual(self.report_count(), (1, 1, 0))
        self.assertEqual(self.client.get("/api/companion/guilds", headers={"Authorization": "Bearer " + token}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
