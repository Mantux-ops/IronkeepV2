"""Roster names accept Unicode letters and reject misplaced or unsafe characters.

Run from the repository root:

    python3 -m unittest tests.test_roster_text
"""

import json
import unittest

from ironkeep.roster import RosterError, parse_body


def member(name, token="MAGE", class_name="Mage", rank="Member", guid="Player-1", level=70):
    return {
        "guid": guid,
        "name": name,
        "level": level,
        "classToken": token,
        "className": class_name,
        "rankName": rank,
    }


def body(members, guild="Herberg", captured_at=1794011429):
    return json.dumps(
        {
            "schema": 1,
            "wowGuildName": guild,
            "capturedAt": captured_at,
            "members": members,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


def parsed(members, **kwargs):
    snapshot, text, digest = parse_body(body(members, **kwargs))
    return snapshot, text, digest


class RosterTextTests(unittest.TestCase):
    def test_dutch_class_names_are_stored_from_companion_escapes(self):
        raw = (
            '{"capturedAt":1794011429,"members":['
            '{"className":"Magi\\u00ebr","classToken":"MAGE","guid":"Player-1","level":70,'
            '"name":"Ada Smith","rankName":"Member"},'
            '{"className":"Dru\\u00efde","classToken":"DRUID","guid":"Player-2","level":70,'
            '"name":"Cara Quinn","rankName":"Officer 2"}'
            '],"schema":1,"wowGuildName":"Herberg"}'
        )
        snapshot, _text, _digest = parse_body(raw)
        classes = {row["name"]: (row["classToken"], row["className"]) for row in snapshot["members"]}
        self.assertEqual(
            classes,
            {"Ada Smith": ("MAGE", "Magiër"), "Cara Quinn": ("DRUID", "Druïde")},
        )

    def test_international_names_are_accepted(self):
        rows = [
            member("Łukasz", guid="Player-1", token="WARRIOR", class_name="Krijger"),
            member("José", guid="Player-2", token="MAGE", class_name="Magiër"),
            member("Иван", guid="Player-3", token="DRUID", class_name="Druïde"),
            member("李明", guid="Player-4", token="PRIEST", class_name="Priester", rank="Рыцарь"),
        ]
        snapshot, _text, _digest = parsed(rows)
        self.assertEqual(
            [row["name"] for row in snapshot["members"]],
            ["Łukasz", "José", "Иван", "李明"],
        )

    def test_nfc_equivalent_names_are_one_player_and_one_body(self):
        composed, composed_body, composed_digest = parsed([member("José")])
        decomposed, decomposed_body, decomposed_digest = parsed([member("Jose\u0301")])
        self.assertEqual(composed["members"][0]["name"], "José")
        self.assertEqual(decomposed["members"][0]["name"], "José")
        self.assertEqual(composed_body, decomposed_body)
        self.assertEqual(composed_digest, decomposed_digest)
        with self.assertRaises(RosterError) as error:
            parsed(
                [
                    member("José", guid="Player-1"),
                    member("Jose\u0301", guid="Player-2", token="DRUID", class_name="Druïde"),
                ]
            )
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(str(error.exception), "This roster could not be read.")

    def test_a_combining_mark_on_a_base_is_kept_after_nfc(self):
        snapshot, _text, _digest = parsed([member("q\u0308", class_name="a\u0301\u0301\u0301")])
        row = snapshot["members"][0]
        self.assertEqual(row["name"], "q\u0308")
        self.assertEqual(row["className"], "\u00e1\u0301\u0301")
        self.assertGreater(len(row["className"]), 2)

    def test_a_decomposed_class_name_is_stored_composed_within_the_limit(self):
        snapshot, _text, _digest = parsed([member("Ada Smith", class_name="e\u0308" * 48)])
        self.assertEqual(snapshot["members"][0]["className"], "ë" * 48)
        with self.assertRaises(RosterError):
            parsed([member("ë" * 49)])

    def test_leading_and_misplaced_combining_marks_are_rejected(self):
        for name in ("\u0301Ada", "Ada \u0301", "\u093e", " \u0308"):
            with self.assertRaises(RosterError):
                parsed([member(name)])

    def test_controls_format_characters_whitespace_emoji_and_symbols_are_rejected(self):
        rejected = (
            "Ada\nSmith",
            "Ada\x00Smith",
            "Ada\u200bSmith",
            "Ada\u202eSmith",
            "Ma\u00adgiër",
            "Ada\u00a0Smith",
            "Ada\u2003Smith",
            "Ada😀",
            "A\u00d7",
        )
        for name in rejected:
            with self.assertRaises(RosterError) as error:
                parsed([member(name, rank=name, class_name="Magiër")])
            self.assertEqual(str(error.exception), "This roster could not be read.")

    def test_printable_ascii_names_classes_and_tokens_stay_valid(self):
        snapshot, _text, _digest = parsed(
            [member("Ada Smith", token="WARRIOR", class_name="Death Knight", rank="Officer 2")]
        )
        row = snapshot["members"][0]
        self.assertEqual(row["name"], "Ada Smith")
        self.assertEqual(row["classToken"], "WARRIOR")
        self.assertEqual(row["className"], "Death Knight")
        self.assertEqual(row["rankName"], "Officer 2")
        self.assertEqual(snapshot["wowGuildName"], "Herberg")

    def test_unicode_in_a_class_token_or_guid_is_rejected(self):
        with self.assertRaises(RosterError):
            parsed([member("Ada Smith", token="Magiër")])
        with self.assertRaises(RosterError):
            parsed([member("Ada Smith", guid="Player-ë")])
        with self.assertRaises(RosterError):
            parsed([member("Ada Smith")], guild="Hërberg")


if __name__ == "__main__":
    unittest.main()
