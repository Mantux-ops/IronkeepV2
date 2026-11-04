import re
import unittest

from fastapi.testclient import TestClient

from ironkeep import attendance, main


REPORT = "\n".join(
    [
        "Ironkeep group",
        "Place: Barrow Deeps",
        "Started: 2026-11-04 20:00",
        "",
        "Name | Class | Role | Time | Status",
        "Sylasvoker | Mage | Damage | 30m | here",
        "Bramlight | Priest | Healer | 30m | here",
        "Ada Smith | Warrior | Tank | 5m | left",
        "",
        "format: ironkeep-group 1",
    ]
)


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        attendance._TOKENS.clear()
        attendance._REPORTS.clear()
        main._CHARACTER_MEMORY.clear()
        main._CHARACTER_SEQ.clear()
        main._RAID_MEMORY.clear()
        self.client = TestClient(main.app)

    def token(self):
        page = self.client.get("/dutchchaos/raids")
        self.assertEqual(page.status_code, 200)
        self.assertIn("No measurement yet", page.text)
        found = re.search(r'id="companion-key"[^>]*value="([^"]+)"', page.text)
        self.assertIsNotNone(found)
        return found.group(1)

    def test_the_copy_list_is_the_report(self):
        parsed = attendance.parse_text(REPORT)
        self.assertEqual(parsed["place"], "Barrow Deeps")
        self.assertEqual([person["name"] for person in parsed["people"]], ["Sylasvoker", "Bramlight", "Ada Smith"])
        self.assertFalse(parsed["people"][2]["here"])
        with self.assertRaises(attendance.ReportError):
            attendance.parse_text('IronkeepDB = { ["session"] = os.execute("rm") }\n')

    def test_the_companion_key_accepts_one_report(self):
        self.assertEqual(
            self.client.post("/api/dutchchaos/attendance", content=REPORT).status_code,
            401,
        )
        key = self.token()
        rejected = self.client.post(
            "/api/dutchchaos/attendance",
            content=REPORT,
            headers={"Authorization": "Bearer wrong-key"},
        )
        self.assertEqual(rejected.status_code, 401)

        accepted = self.client.post(
            "/api/dutchchaos/attendance",
            content=REPORT,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["people"], 3)

        page = self.client.get("/dutchchaos/raids")
        self.assertIn("Barrow Deeps", page.text)
        self.assertIn("Sylas · Mage · Damage · 30m · here", page.text)
        self.assertIn("Bram · Priest · Healer · 30m · here", page.text)
        self.assertIn("No character on the site · Warrior · Tank · 5m · left", page.text)
        self.assertIn("On the signup, not in this raid: Mira.", page.text)
        self.assertNotIn("On the signup, not in this raid: Sylas", page.text)

        rotated = self.client.post("/api/dutchchaos/attendance/token", follow_redirects=False)
        self.assertEqual(rotated.status_code, 303)
        self.assertNotIn(key, self.client.get("/dutchchaos/raids").text)
        stale = self.client.post(
            "/api/dutchchaos/attendance",
            content=REPORT,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.assertEqual(stale.status_code, 401)


if __name__ == "__main__":
    unittest.main()
