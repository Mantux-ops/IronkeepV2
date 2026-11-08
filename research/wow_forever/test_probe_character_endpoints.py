"""Offline tests for the Forever character endpoint probe. No Battle.net calls."""

import io
import json
import unittest
import urllib.error
from pathlib import Path

import probe_character_endpoints as probe


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status = status
        self.headers = headers or {}
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def settings():
    return {"client_id": "public-client-id", "client_secret": "super-secret-value"}


def token_response():
    return FakeResponse(200, json.dumps({"access_token": "app-token-should-not-leak", "expires_in": 86399}))


def href(slug, namespace="profile-forever-eu", suffix=""):
    path = f"/profile/wow/character/{slug}"
    if suffix:
        path = f"{path}/{suffix}"
    return f"https://eu.api.blizzard.com{path}?namespace={namespace}&locale=en_GB"


def member(slug, level, rank=2, link=True, namespace="profile-forever-eu"):
    character = {
        "name": "Secretname",
        "surname": "Secretlast",
        "slug": slug,
        "id": 424242,
        "level": level,
        "playable_class": {"id": 8},
        "playable_race": {"id": 1},
    }
    if link:
        character["key"] = {"href": href(slug, namespace)}
    return {"character": character, "rank": rank}


def roster(*members):
    return {"members": list(members)}


def profile_document():
    return {
        "id": 424242,
        "name": "Secretname",
        "surname": "Secretlast",
        "name_search": "Secretname Secretlast",
        "level": 12,
        "character_class": {"id": 8, "name": "Mage"},
        "race": {"id": 1, "name": "Human"},
        "faction": {"type": "ALLIANCE", "name": "Alliance"},
        "average_item_level": 18,
        "last_login_timestamp": 1793900000000,
        "equipment": {"href": href("readyone-personyy", suffix="equipment")},
        "specializations": {"href": href("readyone-personyy", suffix="specializations")},
        "statistics": {"href": href("readyone-personyy", suffix="statistics")},
        "professions": {"href": href("readyone-personyy", suffix="professions")},
        "achievements": {"href": href("readyone-personyy", suffix="achievements")},
        "character_media": {"href": href("readyone-personyy", suffix="character-media")},
        "appearance": {"href": href("readyone-personyy", suffix="appearance")},
    }


def guild_document():
    return {"id": 39060, "name": "Herberg", "slug": "herberg", "member_count": 2}


def json_response(status, document, headers=None):
    return FakeResponse(status, json.dumps(document), headers)


def run(opener):
    delays = []
    text, code, message = probe.probe(settings(), opener, sleeper=delays.append)
    return text, code, message, delays


def leaked(text):
    for secret in (
        "Secretname",
        "Secretlast",
        "readyone-personyy",
        "lowlevel-personxx",
        "424242",
        "1793900000000",
        "app-token-should-not-leak",
        "super-secret-value",
        "Secretblade",
        "render.example/secret",
        "Ashbringer",
    ):
        if secret in text:
            return secret
    return ""


class ProbeTests(unittest.TestCase):
    def test_profile_link_must_be_an_eu_forever_character_url(self):
        self.assertIsNone(probe.canonical_character_url("https://us.api.blizzard.com/profile/wow/character/readyone-personyy"))
        self.assertIsNone(probe.canonical_character_url(href("readyone-personyy", namespace="profile-eu")))
        self.assertIsNone(probe.canonical_character_url(href("readyone-personyy", namespace="profile-forever-us")))
        self.assertIsNone(
            probe.canonical_character_url(
                "https://eu.api.blizzard.com/profile/wow/character/silvermoon/readyone-personyy?namespace=profile-forever-eu"
            )
        )
        self.assertIsNone(
            probe.canonical_character_url(href("readyone-personyy") + "&access_token=app-token-should-not-leak")
        )
        self.assertEqual(
            probe.canonical_character_url(href("readyone-personyy")),
            href("readyone-personyy"),
        )

    def test_selection_prefers_level_10_and_ignores_names(self):
        document = roster(
            member("lowlevel-personxx", 4),
            member("readyone-personyy", 12),
        )
        selected = probe.select_subject(document)
        self.assertEqual(selected["selection"], "level 10 or above")
        self.assertEqual(selected["links"], "2")
        self.assertEqual(selected["url"], href("readyone-personyy"))
        self.assertNotIn("Secretname", selected["selection"])

    def test_missing_profile_link_does_not_invent_a_url(self):
        document = roster(member("secretname-secretlast", 60, link=False))
        selected = probe.select_subject(document)
        self.assertIsNone(selected["url"])
        self.assertEqual(selected["selection"], "no Blizzard profile link")
        self.assertEqual(selected["links"], "0")

    def test_successful_probe_reports_categories_without_identifiers(self):
        equipment = {
            "equipped_items": [
                {"item": {"id": 515151}, "name": "Secretblade", "item_level": 20, "slot": {"type": "MAIN_HAND"}}
            ]
        }
        specializations = {"specializations": [{"specialization": {"name": "Fire"}, "talents": [{"id": 1}]}]}
        statistics = {"statistics": [{"name": "Health", "quantity": 100}]}
        professions = {"primaries": [{"profession": {"name": "Tailoring"}}], "secondaries": []}
        achievements = {"achievements": [{"id": 1}], "total_quantity": 1, "total_points": 10}
        media = {
            "assets": [
                {"key": "avatar", "value": "https://render.example/secret-portrait"},
                {"key": "main", "value": "https://render.example/secret-render"},
            ]
        }
        appearance = {"customizations": [{"option": {"name": "Hair"}}], "playable_race": {"id": 1}}
        opener = FakeOpener(
            [
                token_response(),
                json_response(200, roster(member("lowlevel-personxx", 4), member("readyone-personyy", 12))),
                json_response(200, guild_document()),
                json_response(200, profile_document(), headers={"last-modified": "Thu, 01 Jan 1970 00:00:00 GMT"}),
                json_response(200, equipment),
                json_response(200, specializations),
                json_response(200, statistics),
                json_response(200, professions),
                json_response(200, achievements),
                json_response(200, media),
                json_response(200, appearance),
            ]
        )
        text, code, message, delays = run(opener)
        self.assertEqual(code, probe.EXIT_OK, message)
        self.assertEqual(message, "")
        self.assertIn("OAuth token HTTP status: 200\n", text)
        self.assertIn("Guild roster HTTP status: 200\n", text)
        self.assertIn("Roster characters: 2\n", text)
        self.assertIn("Roster profile links: 2\n", text)
        self.assertIn("Selected character: level 10 or above\n", text)
        self.assertIn("Endpoint: character profile summary\n", text)
        self.assertIn("Data: name and surname, character id, level, class, race, faction, item level, equipment link\n", text)
        self.assertIn("Result: complete\n", text)
        self.assertIn("Endpoint: character equipment\n", text)
        self.assertIn("Data: equipped items, item level\n", text)
        self.assertIn("Source: profile link\n", text)
        self.assertIn("Endpoint: character specializations\n", text)
        self.assertIn("Data: specializations, talents\n", text)
        self.assertIn("Endpoint: character statistics\n", text)
        self.assertIn("Data: statistics\n", text)
        self.assertIn("Endpoint: character professions\n", text)
        self.assertIn("Data: professions\n", text)
        self.assertIn("Endpoint: character achievements\n", text)
        self.assertIn("Data: achievements\n", text)
        self.assertIn("Endpoint: character media\n", text)
        self.assertIn("Data: media assets, portrait, character render\n", text)
        self.assertIn("Endpoint: character appearance\n", text)
        self.assertIn("Data: appearance, race\n", text)
        self.assertIn("Endpoint: guild rank details\n", text)
        self.assertIn("Data: numeric rank\n", text)
        self.assertIn("Result: partial\n", text)
        self.assertIn("Endpoint: character last login\n", text)
        self.assertIn("Data: last login, logout header\n", text)
        self.assertEqual(leaked(text + message), "")
        self.assertNotIn("Herberg", text)
        self.assertNotIn("39060", text)
        requested = [request.full_url for request in opener.requests]
        self.assertNotIn(href("lowlevel-personxx"), requested)
        self.assertIn(href("readyone-personyy"), requested)
        self.assertIn(href("readyone-personyy", suffix="equipment"), requested)
        self.assertTrue(all(timeout == probe.TIMEOUT_SECONDS for timeout in opener.timeouts))
        self.assertNotIn(0, delays)
        self.assertIn(probe.REQUEST_INTERVAL_SECONDS, delays)

    def test_empty_equipment_is_partial_and_a_404_is_unavailable(self):
        partial = probe.assess_equipment(200, {"equipped_items": []}, "experimental suffix")
        self.assertEqual(partial["available"], "yes")
        self.assertEqual(partial["result"], "partial")
        self.assertEqual(partial["data"], "none")
        missing = probe.assess_equipment(404, None, "experimental suffix")
        self.assertEqual(missing["available"], "no")
        self.assertEqual(missing["result"], "unavailable")
        self.assertEqual(missing["fields"], "none")

    def test_no_profile_link_makes_no_character_request(self):
        opener = FakeOpener(
            [
                token_response(),
                json_response(200, roster(member("secretname-secretlast", 60, link=False))),
                json_response(200, guild_document()),
            ]
        )
        text, code, message, _delays = run(opener)
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(message, "")
        self.assertEqual(len(opener.requests), 3)
        self.assertIn("Selected character: no Blizzard profile link", text)
        self.assertIn("HTTP status: not requested", text)
        self.assertNotIn("Matching character IDs: 0", text)
        self.assertNotIn("Result: complete", text)
        self.assertIn("Data: numeric rank", text)
        self.assertEqual(leaked(text), "")
        self.assertTrue(all("secretname-secretlast" not in request.full_url for request in opener.requests))

    def test_profile_404_does_not_fan_out(self):
        opener = FakeOpener(
            [
                token_response(),
                json_response(200, roster(member("readyone-personyy", 12))),
                json_response(200, guild_document()),
                FakeResponse(404, b"Secretname readyone-personyy 424242"),
            ]
        )
        text, code, message, _delays = run(opener)
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(len(opener.requests), 4)
        self.assertIn("Endpoint: character profile summary\nHTTP status: 404\nAvailable: no\n", text)
        self.assertIn("Endpoint: character equipment\nHTTP status: not requested\n", text)
        self.assertEqual(leaked(text + message), "")

    def test_throttle_stops_later_endpoints(self):
        opener = FakeOpener(
            [
                token_response(),
                json_response(200, roster(member("readyone-personyy", 12))),
                json_response(200, guild_document()),
                json_response(200, profile_document()),
                FakeResponse(429, b"slow down"),
                FakeResponse(429, b"still slow"),
            ]
        )
        text, code, message, delays = run(opener)
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(message, "Stopped after HTTP 429.")
        self.assertIn("Endpoint: character equipment\nHTTP status: 429\n", text)
        self.assertIn("Endpoint: character specializations\nHTTP status: not requested\n", text)
        self.assertEqual(len(opener.requests), 6)
        self.assertIn(probe.RETRY_WAIT_CAP_SECONDS, delays)
        self.assertEqual(leaked(text + message), "")

    def test_unauthorized_roster_stops_before_character_requests(self):
        opener = FakeOpener([token_response(), FakeResponse(401, b"app-token-should-not-leak")])
        text, code, message, _delays = run(opener)
        self.assertEqual(code, probe.EXIT_ROSTER)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("Guild roster HTTP status: 401", text)
        self.assertIn("HTTP status: not requested", text)
        self.assertEqual(leaked(text + message), "")

    def test_network_failure_has_a_fixed_message(self):
        opener = FakeOpener([urllib.error.URLError("lookup failed for super-secret-value")])
        with self.assertRaises(probe.ApiFailure) as caught:
            run(opener)
        self.assertEqual(str(caught.exception), "Could not reach Battle.net.")
        self.assertNotIn("super-secret-value", str(caught.exception))

    def test_check_config_makes_no_request(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_out, previous_err = probe.sys.stdout, probe.sys.stderr
        probe.sys.stdout, probe.sys.stderr = stdout, stderr
        try:
            code = probe.main(
                ["--check-config"],
                environ={"BLIZZARD_CLIENT_ID": "public-client-id", "BLIZZARD_CLIENT_SECRET": "super-secret-value"},
                opener_factory=lambda: (_ for _ in ()).throw(AssertionError("opener built")),
                sleeper=lambda _delay: (_ for _ in ()).throw(AssertionError("sleeper called")),
            )
        finally:
            probe.sys.stdout, probe.sys.stderr = previous_out, previous_err
        self.assertEqual(code, probe.EXIT_OK)
        self.assertIn("Credentials are present.", stdout.getvalue())
        self.assertIn("Region is EU.", stdout.getvalue())
        self.assertIn("Namespace is profile-forever-eu.", stdout.getvalue())
        self.assertIn("No request was sent.", stdout.getvalue())
        self.assertNotIn("super-secret-value", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("public-client-id", stdout.getvalue() + stderr.getvalue())

    def test_script_does_not_save_responses_or_import_the_application(self):
        source = Path(__file__).with_name("probe_character_endpoints.py").read_text(encoding="utf-8")
        self.assertNotIn("import ironkeep", source)
        self.assertNotIn("import fetch_herberg", source)
        self.assertNotIn("import discord", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("sqlite", source.lower())


if __name__ == "__main__":
    unittest.main()
