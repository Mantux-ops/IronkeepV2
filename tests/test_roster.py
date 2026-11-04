import os
import tempfile
import unittest

from ironkeep import config, db, roster


def fields(**overrides):
    payload = {
        "name": "Sylasvoker",
        "class_id": "mage",
        "spec_id": "frost",
        "role": "dps",
        "is_main": True,
    }
    payload.update(overrides)
    return payload


class RosterTests(unittest.TestCase):
    def test_first_character_is_the_main(self):
        rows = []
        roster.add(rows, "1", fields(is_main=False))
        self.assertTrue(rows[0]["is_main"])
        self.assertEqual(rows[0]["class_id"], "mage")

    def test_alt_can_become_the_main(self):
        rows = []
        main = roster.add(rows, "1", fields())
        main["id"] = 1
        alt = roster.add(rows, "1", fields(name="Sylasrogue", class_id="rogue", spec_id="combat", role="dps", is_main=False))
        alt["id"] = 2
        self.assertEqual([row["is_main"] for row in rows], [True, False])
        roster.set_main(rows, 2)
        self.assertEqual([row["is_main"] for row in rows], [False, True])

    def test_names_are_unique_ignoring_case(self):
        rows = []
        row = roster.add(rows, "1", fields(name="Sylas"))
        row["id"] = 1
        with self.assertRaises(roster.RosterError):
            roster.add(rows, "2", fields(name="sylas"))

    def test_name_must_be_two_to_twelve_letters(self):
        with self.assertRaises(roster.RosterError):
            roster.add([], "1", fields(name="A"))
        with self.assertRaises(roster.RosterError):
            roster.add([], "1", fields(name="Has Space"))
        with self.assertRaises(roster.RosterError):
            roster.add([], "1", fields(name="Name123"))

    def test_feral_can_be_a_tank(self):
        rows = []
        roster.add(rows, "1", fields(name="Mirabear", class_id="druid", spec_id="feral", role="tank"))
        self.assertEqual(rows[0]["role"], "tank")
        self.assertEqual(rows[0]["spec_id"], "feral")

    def test_unknown_class_is_refused(self):
        with self.assertRaises(roster.RosterError):
            roster.add([], "1", fields(class_id="deathknight", spec_id="frost"))

    def test_main_cannot_be_cleared_in_place(self):
        rows = []
        row = roster.add(rows, "1", fields())
        row["id"] = 1
        with self.assertRaises(roster.RosterError) as caught:
            roster.update(rows, 1, fields(is_main=False))
        self.assertIn("main", caught.exception.message)
        self.assertTrue(rows[0]["is_main"])

    def test_removing_the_main_promotes_the_oldest_alt(self):
        rows = []
        first = roster.add(rows, "1", fields())
        first["id"] = 1
        second = roster.add(rows, "1", fields(name="Sylasrogue", class_id="rogue", spec_id="combat", is_main=False))
        second["id"] = 2
        third = roster.add(rows, "1", fields(name="Sylaslock", class_id="warlock", spec_id="affliction", is_main=False))
        third["id"] = 3
        roster.remove(rows, 1)
        mains = [row["name"] for row in rows if row["is_main"]]
        self.assertEqual(mains, ["Sylasrogue"])
        self.assertEqual(len(rows), 2)


class CharacterStoreTests(unittest.TestCase):
    def test_database_keeps_one_main(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        previous = config.DB_PATH
        config.DB_PATH = path
        try:
            db.init()
            db.change_characters("guild", lambda rows: roster.add(rows, "9001", fields(is_main=False)))
            db.change_characters(
                "guild",
                lambda rows: roster.add(rows, "9001", fields(name="Sylasrogue", class_id="rogue", spec_id="combat", is_main=False)),
            )
            stored = db.list_characters("guild")
            self.assertEqual(len(stored), 2)
            self.assertEqual([row["name"] for row in stored if row["is_main"]], ["Sylasvoker"])
            alt_id = next(row["id"] for row in stored if row["name"] == "Sylasrogue")
            db.change_characters("guild", lambda rows: roster.set_main(rows, alt_id))
            stored = db.list_characters("guild")
            self.assertEqual([row["name"] for row in stored if row["is_main"]], ["Sylasrogue"])
            main_id = next(row["id"] for row in stored if row["is_main"])
            db.change_characters("guild", lambda rows: roster.remove(rows, main_id))
            stored = db.list_characters("guild")
            self.assertEqual([(row["name"], row["is_main"]) for row in stored], [("Sylasvoker", True)])
        finally:
            config.DB_PATH = previous
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
