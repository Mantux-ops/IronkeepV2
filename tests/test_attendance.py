import os
import shutil
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from ironkeep import attendance, config, db, main


REPORT = "\n".join(
    [
        "Ironkeep group",
        "Place: Hall of Thanes",
        "Started: 2026-11-01 12:00",
        "",
        "Name | Class | Role | Time | Status",
        "Ada Smith | Warrior | Tank | 20m | here",
        "Bram Holt | Priest | Healer | 10m | here",
        "Dain Frost | Mage | Damage | 5m | left",
        "",
        "format: ironkeep-group 1",
    ]
)


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        attendance._TOKENS.clear()
        attendance._REPORTS.clear()
        self.client = TestClient(main.app)

    def token(self, slug="dutchchaos"):
        page = self.client.get(f"/{slug}/raids")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="companion-key"', page.text)
        start = page.text.index('id="companion-key"')
        value = page.text.index('value="', start) + len('value="')
        end = page.text.index('"', value)
        return page.text[value:end]

    def test_the_companion_text_is_the_report(self):
        parsed = attendance.parse_text(REPORT)
        self.assertEqual(parsed["place"], "Hall of Thanes")
        self.assertEqual(
            [person["name"] for person in parsed["people"]],
            ["Ada Smith", "Bram Holt", "Dain Frost"],
        )
        self.assertFalse(parsed["people"][2]["here"])
        self.assertEqual(attendance.digest(REPORT), attendance.digest(REPORT.replace("\n", "\r\n")))
        with self.assertRaises(attendance.ReportError):
            attendance.parse_text('IronkeepDB = { ["session"] = os.execute("rm") }\n')

    def test_a_missing_key_is_rejected(self):
        self.assertEqual(self.client.post("/api/dutchchaos/attendance", content=REPORT).status_code, 401)
        rejected = self.client.post(
            "/api/dutchchaos/attendance",
            content=REPORT,
            headers={"Authorization": "Bearer wrong-key"},
        )
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(rejected.json()["ok"], False)
        missing = self.client.post(
            "/api/no-such-guild/attendance",
            content=REPORT,
            headers={"Authorization": "Bearer anything"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"], "Unknown guild.")

    def test_a_key_from_another_guild_is_rejected(self):
        key = self.token("dutchchaos")
        self.token("ironlegion")
        rejected = self.client.post(
            "/api/ironlegion/attendance",
            content=REPORT,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.assertEqual(rejected.status_code, 401)

    def test_the_same_report_is_stored_once(self):
        key = self.token()
        headers = {"Authorization": f"Bearer {key}"}
        first = self.client.post("/api/dutchchaos/attendance", content=REPORT, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"ok": True, "duplicate": False, "place": "Hall of Thanes", "people": 3})
        again = self.client.post("/api/dutchchaos/attendance", content=REPORT.replace("\n", "\r\n"), headers=headers)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["duplicate"])
        self.assertEqual(len(attendance._REPORTS[self._guild_id("dutchchaos")]), 1)

        page = self.client.get("/dutchchaos/raids")
        self.assertIn("Hall of Thanes", page.text)
        self.assertIn("Ada Smith", page.text)
        self.assertIn("Bram Holt", page.text)
        self.assertIn("Dain Frost", page.text)
        self.assertIn("here", page.text)
        self.assertIn("left", page.text)

        broken = self.client.post("/api/dutchchaos/attendance", content=b"not a report", headers=headers)
        self.assertEqual(broken.status_code, 400)
        self.assertEqual(broken.json()["ok"], False)

        huge = b"x" * (attendance.MAX_BYTES + 1)
        oversized = self.client.post("/api/dutchchaos/attendance", content=huge, headers=headers)
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()["error"], "This report is too large.")

    def test_rotating_the_key_rejects_the_old_one(self):
        key = self.token()
        rotated = self.client.post("/api/dutchchaos/attendance/token", follow_redirects=False)
        self.assertEqual(rotated.status_code, 303)
        self.assertNotIn(key, self.client.get("/dutchchaos/raids").text)
        stale = self.client.post(
            "/api/dutchchaos/attendance",
            content=REPORT,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.assertEqual(stale.status_code, 401)

    def test_settings_save_keeps_the_key_off_the_page(self):
        tmp = tempfile.mkdtemp()
        old = (config.BOT_TOKEN, config.CLIENT_ID, config.CLIENT_SECRET, config.DB_PATH)
        try:
            config.BOT_TOKEN = "bot"
            config.CLIENT_ID = "id"
            config.CLIENT_SECRET = "secret"
            config.DB_PATH = os.path.join(tmp, "ik.db")
            self.assertTrue(config.live())
            db.init()
            db.upsert_guild("4242", "Forever Guild", [], [])
            guild = db.guild_by_slug("foreverguild")
            self.assertIsNotNone(guild)
            key = attendance.token_for(guild)
            session = db.create_session(config.SUPERADMIN_ID, "Officer", "officer", "a", "r", 3600)
            client = TestClient(main.app)
            client.cookies.set("ik_session", session)

            page = client.get("/foreverguild/settings")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(key, page.text)
            self.assertNotIn("attendance_token", page.text)
            trial = client.get("/foreverguild/trial")
            self.assertEqual(trial.status_code, 200)
            self.assertNotIn(key, trial.text)

            saved = client.post(
                "/api/foreverguild/settings",
                json={"timezone": "Europe/Amsterdam", "trial_roles": [], "attendance_token": "from-the-browser"},
            )
            self.assertEqual(saved.status_code, 200)
            stored = db.guild_by_slug("foreverguild")
            self.assertTrue(attendance.token_matches(stored, key))
            self.assertFalse(attendance.token_matches(stored, "from-the-browser"))

            headers = {"Authorization": f"Bearer {key}"}
            first = client.post("/api/foreverguild/attendance", content=REPORT, headers=headers)
            second = client.post("/api/foreverguild/attendance", content=REPORT, headers=headers)
            self.assertEqual(first.status_code, 200)
            self.assertFalse(first.json()["duplicate"])
            self.assertTrue(second.json()["duplicate"])
            self.assertEqual(db.count_attendance(stored["id"]), 1)
            self.assertEqual(db.count_attendance_hashes(stored["id"]), 1)
            self.assertIn("Hall of Thanes", client.get("/foreverguild/raids").text)

            for index in range(20):
                report = REPORT.replace("Ada Smith", "Ada Smith %s" % index)
                posted = client.post("/api/foreverguild/attendance", content=report, headers=headers)
                self.assertEqual(posted.status_code, 200)
                self.assertFalse(posted.json()["duplicate"])
            self.assertEqual(db.count_attendance(stored["id"]), 20)
            self.assertEqual(db.count_attendance_hashes(stored["id"]), 21)
            oldest = client.post("/api/foreverguild/attendance", content=REPORT, headers=headers)
            self.assertEqual(oldest.status_code, 200)
            self.assertTrue(oldest.json()["duplicate"])
            self.assertEqual(oldest.json()["place"], "Hall of Thanes")
            self.assertEqual(oldest.json()["people"], 3)
            self.assertEqual(db.count_attendance(stored["id"]), 20)
            self.assertEqual(db.count_attendance_hashes(stored["id"]), 21)

            barrier = threading.Barrier(4)
            raced = []

            def post_same():
                barrier.wait()
                raced.append(db.add_attendance(stored["id"], {
                    "place": "Hall of Thanes",
                    "started": "2026-11-01 12:00",
                    "received_at": "2026-11-04T19:00:00+00:00",
                    "people": [],
                    "digest": attendance.digest(REPORT.replace("Ada Smith", "Raced Smith")),
                }))

            threads = [threading.Thread(target=post_same) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(sum(1 for saved_row in raced if saved_row), 1)
            self.assertEqual(db.count_attendance_hashes(stored["id"]), 22)
        finally:
            config.BOT_TOKEN, config.CLIENT_ID, config.CLIENT_SECRET, config.DB_PATH = old
            shutil.rmtree(tmp)

    def _guild_id(self, slug):
        from ironkeep import mock_data as data

        return data.guild_by_slug(slug)["id"]


if __name__ == "__main__":
    unittest.main()
