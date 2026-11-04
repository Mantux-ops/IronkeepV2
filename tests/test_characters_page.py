import unittest

from fastapi.testclient import TestClient

from ironkeep import main


class CharactersPageTests(unittest.TestCase):
    def setUp(self):
        main._CHARACTER_MEMORY.clear()
        main._CHARACTER_SEQ.clear()
        self.client = TestClient(main.app)

    def test_guild_opens_on_raids_and_hides_the_old_pages(self):
        home = self.client.get("/dutchchaos", follow_redirects=False)
        self.assertEqual(home.status_code, 303)
        self.assertEqual(home.headers["location"], "/dutchchaos/raids")

        characters = self.client.get("/dutchchaos/characters")
        self.assertEqual(characters.status_code, 200)
        self.assertIn("Sylasvoker", characters.text)
        self.assertIn(">Raids<", characters.text)
        self.assertIn(">Members<", characters.text)
        self.assertIn(">Characters<", characters.text)
        self.assertIn(">Settings<", characters.text)
        self.assertNotIn(">Trials<", characters.text)
        self.assertNotIn(">Payout<", characters.text)
        self.assertNotIn(">Lootsplit<", characters.text)

        raids = self.client.get("/dutchchaos/raids")
        self.assertIn("Sylasvoker", raids.text)
        self.assertIn('"main": null', raids.text)

        members = self.client.get("/dutchchaos/members")
        self.assertIn("Sylasvoker", members.text)
        self.assertIn("Add character", members.text)
        self.assertIn("1 alt", members.text)

    def test_add_alt_promote_and_remove(self):
        created = self.client.post(
            "/api/dutchchaos/characters",
            json={
                "user_id": "9003",
                "name": "Kaelentank",
                "class_id": "warrior",
                "spec_id": "protection",
                "role": "tank",
                "is_main": False,
            },
        )
        self.assertEqual(created.status_code, 200)
        kaelen = next(person for person in created.json()["people"] if person["id"] == "9003")
        self.assertEqual(kaelen["characters"][0]["name"], "Kaelentank")
        self.assertTrue(kaelen["characters"][0]["is_main"])
        self.assertEqual(kaelen["characters"][0]["role"], "tank")

        alt = self.client.post(
            "/api/dutchchaos/characters",
            json={
                "user_id": "9003",
                "name": "Kaelenmage",
                "class_id": "mage",
                "spec_id": "fire",
                "role": "dps",
                "is_main": False,
            },
        )
        self.assertEqual(alt.status_code, 200)
        kaelen = next(person for person in alt.json()["people"] if person["id"] == "9003")
        self.assertEqual([row["is_main"] for row in kaelen["characters"]], [True, False])
        alt_id = next(row["id"] for row in kaelen["characters"] if row["name"] == "Kaelenmage")

        promoted = self.client.post(f"/api/dutchchaos/characters/{alt_id}/main")
        self.assertEqual(promoted.status_code, 200)
        kaelen = next(person for person in promoted.json()["people"] if person["id"] == "9003")
        self.assertEqual([row["name"] for row in kaelen["characters"] if row["is_main"]], ["Kaelenmage"])

        duplicate = self.client.post(
            "/api/dutchchaos/characters",
            json={"user_id": "9002", "name": "kaelenmage", "class_id": "mage", "spec_id": "frost", "role": "dps"},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already", duplicate.json()["error"])

        removed = self.client.delete(f"/api/dutchchaos/characters/{alt_id}")
        self.assertEqual(removed.status_code, 200)
        kaelen = next(person for person in removed.json()["people"] if person["id"] == "9003")
        self.assertEqual([row["name"] for row in kaelen["characters"]], ["Kaelentank"])
        self.assertTrue(kaelen["characters"][0]["is_main"])

        stranger = self.client.post(
            "/api/dutchchaos/characters",
            json={"user_id": "missing", "name": "Nobody", "class_id": "mage", "spec_id": "frost", "role": "dps"},
        )
        self.assertEqual(stranger.status_code, 400)


if __name__ == "__main__":
    unittest.main()
