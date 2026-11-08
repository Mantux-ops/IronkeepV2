"""Offline tests for Forever character-id comparison. No browser and no Battle.net."""

import io
import json
import unittest
import urllib.error
from pathlib import Path

import compare_character_ids as compare
import test_account_profile as profile


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
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

    def open(self, request, timeout=None):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def settings():
    return {"client_id": "public-client-id", "client_secret": "super-secret-value"}


def token_body(token="user-token-should-not-leak"):
    return json.dumps({"access_token": token, "refresh_token": "refresh-should-not-leak", "scope": "wow.profile"})


def app_token_body():
    return json.dumps({"access_token": "app-token-should-not-leak", "expires_in": 86399})


def profile_document(characters):
    return {
        "id": 999001,
        "battletag": "Hidden#1234",
        "wow_accounts": [
            {
                "id": 888002,
                "characters": characters,
            }
        ],
    }


def character(character_id, **extra):
    row = {
        "character": {"href": "https://eu.api.blizzard.com/profile/wow/character/secretname-secretlast"},
        "faction": {"type": "ALLIANCE"},
        "gender": {"type": "MALE"},
        "id": character_id,
        "level": 22,
        "name": "Secretname",
        "playable_class": {"id": 1},
        "playable_race": {"id": 1},
        "protected_character": {"id": 777777, "href": "https://example.invalid/secret"},
        "surname": "Secretlast",
    }
    row.update(extra)
    return row


def roster_document(character_ids):
    return {
        "members": [
            {"character": {"id": character_id, "name": "Secretname", "surname": "Secretlast"}, "rank": 2}
            for character_id in character_ids
        ]
    }


def run_with(opener, decision):
    def listener(_state, ready):
        ready.set()
        return decision

    return compare.execute(settings(), opener, lambda _url: True, listener)


def leaked(text):
    for secret in (
        "Secretname",
        "Secretlast",
        "Hidden#1234",
        "424242",
        "515151",
        "616161",
        "777777",
        "888002",
        "999001",
        "super-secret-value",
        "user-token-should-not-leak",
        "app-token-should-not-leak",
        "refresh-should-not-leak",
        "LEAKED-CODE-VALUE",
        "secretname-secretlast",
    ):
        if secret in text:
            return secret
    return ""


class CompareTests(unittest.TestCase):
    def test_zero_matches_are_reported_without_identifiers(self):
        opener = FakeOpener(
            [
                FakeResponse(200, token_body()),
                FakeResponse(200, json.dumps(profile_document([character(424242), character(515151)]))),
                FakeResponse(200, app_token_body()),
                FakeResponse(200, json.dumps(roster_document([616161]))),
            ]
        )
        text, code, message = run_with(opener, profile.Decision("ok", code="LEAKED-CODE-VALUE"))
        self.assertEqual(code, compare.EXIT_OK)
        self.assertEqual(message, "")
        self.assertIn("OAuth token HTTP status: 200\n", text)
        self.assertIn("Account profile HTTP status: 200\n", text)
        self.assertIn("Guild token HTTP status: 200\n", text)
        self.assertIn("Guild roster HTTP status: 200\n", text)
        self.assertIn("Account characters: 2\n", text)
        self.assertIn("Guild characters: 1\n", text)
        self.assertIn("Matching character IDs: 0\n", text)
        self.assertIn("Unmatched account characters: 2\n", text)
        self.assertIn("Duplicate IDs: no\n", text)
        self.assertIn("Invalid IDs: no\n", text)
        self.assertEqual(leaked(text + message), "")
        self.assertEqual(opener.requests[3].full_url, compare.ROSTER_URL)
        self.assertEqual(opener.requests[3].get_header("Authorization"), "Bearer app-token-should-not-leak")
        self.assertNotEqual(opener.requests[1].get_header("Authorization"), opener.requests[3].get_header("Authorization"))

    def test_partial_and_full_matches_use_character_ids_only(self):
        partial = compare.compare_ids(
            compare.collect_account_ids(profile_document([character(424242), character(515151), character(616161)])),
            compare.collect_guild_ids(roster_document([515151, 717171])),
        )
        self.assertEqual(partial, {"matching": "1", "unmatched": "2", "duplicate": "no", "invalid": "no"})
        full = compare.compare_ids(
            compare.collect_account_ids(profile_document([character(424242), character(515151)])),
            compare.collect_guild_ids(roster_document([424242, 515151, 616161])),
        )
        self.assertEqual(full, {"matching": "2", "unmatched": "0", "duplicate": "no", "invalid": "no"})

    def test_account_id_and_protected_character_id_are_not_character_ids(self):
        account = profile_document([character(424242)])
        account["wow_accounts"][0]["id"] = 616161
        result = compare.compare_ids(
            compare.collect_account_ids(account),
            compare.collect_guild_ids(roster_document([616161, 777777])),
        )
        self.assertEqual(result["matching"], "0")
        self.assertEqual(result["unmatched"], "1")

    def test_duplicate_ids_are_not_counted_as_matches(self):
        account = compare.collect_account_ids(profile_document([character(424242), character(424242)]))
        guild = compare.collect_guild_ids(roster_document([424242]))
        result = compare.compare_ids(account, guild)
        self.assertEqual(result["matching"], "not comparable")
        self.assertEqual(result["unmatched"], "not comparable")
        self.assertEqual(result["duplicate"], "yes")
        self.assertEqual(result["invalid"], "no")
        guild_duplicate = compare.compare_ids(
            compare.collect_account_ids(profile_document([character(424242)])),
            compare.collect_guild_ids(roster_document([424242, 424242])),
        )
        self.assertEqual(guild_duplicate["duplicate"], "yes")
        self.assertEqual(guild_duplicate["matching"], "not comparable")

    def test_malformed_identifiers_are_not_nonmatches(self):
        cases = [
            character("424242"),
            character(True),
            character(0),
            character(-5),
            {"name": "Secretname", "surname": "Secretlast"},
            character(424242, character={"id": 515151}),
        ]
        for row in cases:
            result = compare.compare_ids(
                compare.collect_account_ids(profile_document([row, character(616161)])),
                compare.collect_guild_ids(roster_document([616161])),
            )
            self.assertEqual(result["matching"], "not comparable", row)
            self.assertEqual(result["unmatched"], "not comparable", row)
            self.assertEqual(result["invalid"], "yes", row)
        guild_cases = [
            {"rank": 2},
            {"character": {"name": "Secretname"}, "rank": 2},
            {"character": {"id": "424242"}, "rank": 2},
            {"id": 515151, "character": {"id": 424242}, "rank": 2},
            "not-a-member",
        ]
        for member in guild_cases:
            document = {"members": [member, {"character": {"id": 616161}, "rank": 2}]}
            result = compare.compare_ids(
                compare.collect_account_ids(profile_document([character(616161)])),
                compare.collect_guild_ids(document),
            )
            self.assertEqual(result["matching"], "not comparable", member)
            self.assertEqual(result["invalid"], "yes", member)

    def test_missing_collections_are_not_empty_matches(self):
        result = compare.compare_ids(compare.collect_account_ids({"battletag": "Hidden#1234"}), compare.collect_guild_ids({}))
        self.assertEqual(result["matching"], "not comparable")
        self.assertEqual(result["invalid"], "yes")
        self.assertNotIn("Hidden#1234", " ".join(result.values()))

    def test_denied_consent_makes_no_request(self):
        opener = FakeOpener([])
        text, code, message = run_with(opener, profile.Decision("denied"))
        self.assertEqual(code, profile.EXIT_DENIED)
        self.assertEqual(opener.requests, [])
        self.assertIn("Authorization was denied.", message)
        self.assertIn("Matching character IDs: not requested", text)
        self.assertNotIn("Matching character IDs: 0", text)

    def test_profile_http_error_does_not_fetch_the_roster_or_report_zero(self):
        opener = FakeOpener(
            [
                FakeResponse(200, token_body()),
                FakeResponse(401, b"user-token-should-not-leak Secretname"),
            ]
        )
        text, code, message = run_with(opener, profile.Decision("ok", code="LEAKED-CODE-VALUE"))
        self.assertEqual(code, profile.EXIT_PROFILE)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("Account profile HTTP status: 401", text)
        self.assertIn("Guild roster HTTP status: not requested", text)
        self.assertIn("Matching character IDs: not requested", text)
        self.assertNotIn("Matching character IDs: 0", text)
        self.assertEqual(leaked(text + message), "")

    def test_roster_http_error_is_not_a_zero_match(self):
        opener = FakeOpener(
            [
                FakeResponse(200, token_body()),
                FakeResponse(200, json.dumps(profile_document([character(424242)]))),
                FakeResponse(200, app_token_body()),
                FakeResponse(404, b"app-token-should-not-leak Secretname 424242"),
            ]
        )
        text, code, message = run_with(opener, profile.Decision("ok", code="LEAKED-CODE-VALUE"))
        self.assertEqual(code, compare.EXIT_ROSTER)
        self.assertIn("Guild roster HTTP status: 404", text)
        self.assertIn("Account characters: 1", text)
        self.assertIn("Matching character IDs: not requested", text)
        self.assertNotIn("Matching character IDs: 0", text)
        self.assertEqual(leaked(text + message), "")

    def test_malformed_json_does_not_print_the_body(self):
        opener = FakeOpener(
            [
                FakeResponse(200, b"not-json user-token-should-not-leak"),
            ]
        )
        text, code, message = run_with(opener, profile.Decision("ok", code="LEAKED-CODE-VALUE"))
        self.assertEqual(code, profile.EXIT_TOKEN)
        self.assertEqual(len(opener.requests), 1)
        self.assertIn("could not be read", message)
        self.assertEqual(leaked(text + message), "")

    def test_network_failure_hides_the_secret_and_code(self):
        opener = FakeOpener([urllib.error.URLError("lookup failed for super-secret-value and LEAKED-CODE-VALUE")])
        with self.assertRaises(profile.ApiFailure) as caught:
            run_with(opener, profile.Decision("ok", code="LEAKED-CODE-VALUE"))
        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertNotIn("LEAKED-CODE-VALUE", str(caught.exception))

    def test_check_config_makes_no_request(self):
        calls = []

        def forbid(*_args, **_kwargs):
            calls.append("called")
            raise AssertionError("check-config made a call")

        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_out, previous_err = compare.sys.stdout, compare.sys.stderr
        compare.sys.stdout, compare.sys.stderr = stdout, stderr
        try:
            code = compare.main(
                ["--check-config"],
                environ={"BLIZZARD_CLIENT_ID": "public-client-id", "BLIZZARD_CLIENT_SECRET": "super-secret-value"},
                opener_factory=forbid,
                listener=forbid,
                browser=forbid,
            )
        finally:
            compare.sys.stdout, compare.sys.stderr = previous_out, previous_err
        self.assertEqual(code, compare.EXIT_OK)
        self.assertEqual(calls, [])
        self.assertIn("Credentials are present.", stdout.getvalue())
        self.assertIn("Guild roster is Herberg on profile-forever-eu.", stdout.getvalue())
        self.assertIn("No browser was opened and no request was sent.", stdout.getvalue())
        self.assertNotIn("super-secret-value", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("public-client-id", stdout.getvalue() + stderr.getvalue())

    def test_script_does_not_touch_the_application_or_save_responses(self):
        source = Path(__file__).with_name("compare_character_ids.py").read_text(encoding="utf-8")
        self.assertNotIn("import ironkeep", source)
        self.assertNotIn("import fetch_herberg", source)
        self.assertNotIn("sqlite", source.lower())
        self.assertNotIn("write_text", source)
        self.assertNotIn("import discord", source)


if __name__ == "__main__":
    unittest.main()
