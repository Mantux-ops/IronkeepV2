#!/usr/bin/env python3
"""Regression checks for the live sidebar's two Members links."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import patch_layout


MEMBERS = (
    '<a class="nav__item {% if nav == \'members\' %}is-active{% endif %}" '
    'href="/{{ guild.slug }}/members">{{ icon("users") }}<span>Members</span></a>'
)


def wow_block():
    return (
        '{% if access.raids %}\n'
        '      <a class="nav__item {% if nav == \'raids\' %}is-active{% endif %}" '
        'href="/{{ guild.slug }}/raids">{{ icon("calendar") }}<span>Raids</span></a>\n'
        "      {% endif %}\n"
        "      {% if access.members %}\n"
        "      " + MEMBERS + "\n"
        "      {% endif %}\n"
        "      {% if access.settings %}\n"
        '      <a class="nav__item {% if nav == \'settings\' %}is-active{% endif %}" '
        'href="/{{ guild.slug }}/settings">{{ icon("settings") }}<span>Settings</span></a>\n'
        "      {% endif %}\n"
    )


def albion_block():
    return (
        "      {% if access.trials %}\n"
        '      <a class="nav__item {% if nav == \'trials\' %}is-active{% endif %}" '
        'href="/{{ guild.slug }}/trial">{{ icon("scale") }}<span>Trials</span></a>\n'
        "      " + MEMBERS + "\n"
        "      {% endif %}\n"
    )


def wow_first():
    return (
        '{% if guild.game == "wow" %}\n'
        + wow_block()
        + '{% elif guild.game == "albion" or not live %}\n'
        + albion_block()
        + "{% endif %}\n"
    )


def albion_first():
    return (
        '{% if guild.game == "albion" or not live %}\n'
        + albion_block()
        + '{% elif guild.game == "wow" %}\n'
        + wow_block()
        + "{% endif %}\n"
    )


def albion_body(text):
    frames = patch_layout._parse_frames(text)
    branch = patch_layout._branch(patch_layout._game_frame(frames), "albion")
    return text[branch["body_start"]:branch["body_end"]]


class PatchLayoutTests(unittest.TestCase):
    def assert_wow_only(self, source):
        original_albion = albion_body(source)
        updated = patch_layout.patch_text(source)
        self.assertEqual(albion_body(updated), original_albion)
        self.assertEqual(updated.count("nav == 'roster'"), 1)
        self.assertNotIn("nav == 'roster'", albion_body(updated))
        wow = updated.split('guild.game == "wow"', 1)[1]
        gate = wow.split("{% if access.members %}", 1)[1].split("{% if access.settings %}", 1)[0]
        self.assertIn("nav == 'roster'", gate)
        self.assertIn('href="/{{ guild.slug }}/members"', gate)
        self.assertIn("{% if access.roster %}", gate)
        self.assertEqual(patch_layout.patch_text(updated), updated)
        return updated

    def test_wow_before_albion_inserts_only_in_wow(self):
        self.assert_wow_only(wow_first())

    def test_albion_before_wow_inserts_only_in_wow(self):
        source = albion_first()
        updated = self.assert_wow_only(source)
        self.assertLess(updated.find('guild.game == "albion"'), updated.find("nav == 'roster'"))

    def test_a_second_patch_does_not_change_the_file(self):
        once = patch_layout.patch_text(wow_first())
        self.assertEqual(patch_layout.patch_text(once), once)

    def test_missing_wow_branch_is_refused(self):
        source = (
            '{% if guild.game == "albion" or not live %}\n'
            "      {% if access.trials %}\n      " + MEMBERS + "\n      {% endif %}\n"
            "{% endif %}\n"
        )
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_missing_albion_branch_is_refused(self):
        source = '{% if guild.game == "wow" %}\n' + wow_block() + "{% endif %}\n"
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_missing_wow_members_link_is_refused(self):
        source = wow_first().replace(MEMBERS, '<a href="/{{ guild.slug }}/raids">Raids</a>', 1)
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_two_wow_members_links_are_refused(self):
        source = wow_first().replace(
            "{% if access.members %}\n      " + MEMBERS + "\n      {% endif %}",
            "{% if access.members %}\n      " + MEMBERS + "\n      " + MEMBERS + "\n      {% endif %}",
            1,
        )
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_members_outside_the_permission_gate_is_refused(self):
        loose = wow_block().replace("{% if access.members %}\n", "").replace("      {% endif %}\n      {% if access.settings %}", "      {% if access.settings %}")
        source = (
            '{% if guild.game == "wow" %}\n'
            + loose
            + '{% elif guild.game == "albion" or not live %}\n'
            + albion_block()
            + "{% endif %}\n"
        )
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_unclosed_if_is_refused(self):
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text('{% if guild.game == "wow" %}\n' + MEMBERS)

    def test_extra_endif_is_refused(self):
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(wow_first() + "{% endif %}\n")

    def test_unclosed_members_anchor_is_refused(self):
        broken = MEMBERS.replace("</a>", "")
        source = wow_first().replace(MEMBERS, broken, 1)
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_two_wow_branches_are_refused(self):
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(wow_first() + wow_first())

    def test_a_roster_link_already_in_albion_is_refused(self):
        source = albion_first().replace(
            MEMBERS,
            MEMBERS + "\n      <a class=\"nav__item {% if nav == 'roster' %}is-active{% endif %}\" href=\"/{{ guild.slug }}/roster\">Roster</a>",
            1,
        )
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)

    def test_separate_wow_and_albion_ifs_are_refused(self):
        source = (
            '{% if guild.game == "wow" %}\n' + wow_block() + "{% endif %}\n"
            '{% if guild.game == "albion" or not live %}\n' + albion_block() + "{% endif %}\n"
        )
        with self.assertRaises(patch_layout.LayoutError):
            patch_layout.patch_text(source)


if __name__ == "__main__":
    unittest.main()
