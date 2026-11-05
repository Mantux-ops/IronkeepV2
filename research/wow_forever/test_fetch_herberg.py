"""Local tests for the WoW Forever proof of concept. No network and no secrets."""

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import fetch_herberg as api


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status = status
        self.headers = headers or {}
        if isinstance(body, bytes):
            self._body = body
        else:
            self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        result = self.handler(request, len(self.requests))
        if isinstance(result, Exception):
            raise result
        return result


def settings(**overrides):
    base = {
        "client_id": "public-client-id",
        "client_secret": "super-secret-value",
        "region": "eu",
        "slug": "herberg",
        "locale": "en_GB",
        "sample_dir": "",
    }
    base.update(overrides)
    return base


def json_response(status, document, headers=None):
    return FakeResponse(status, json.dumps(document), headers)


def scripted(opener_responses):
    queue = list(opener_responses)

    def handler(_request, _count):
        if not queue:
            raise AssertionError("unexpected extra request")
        return queue.pop(0)

    return FakeOpener(handler)


class FetchHerbergTests(unittest.TestCase):
    def test_missing_credentials_do_not_call_battle_net(self):
        opener = FakeOpener(lambda *_args: AssertionError("network was used"))
        with self.assertRaises(api.ApiFailure) as caught:
            api.run(settings(client_id="", client_secret=""), opener=opener)
        self.assertEqual(caught.exception.exit_code, api.EXIT_CONFIG)
        self.assertIn("BLIZZARD_CLIENT_ID", str(caught.exception))
        self.assertIn("DISCORD_CLIENT_ID", str(caught.exception))
        self.assertEqual(opener.requests, [])

    def test_check_config_reports_the_gap_without_printing_a_secret(self):
        stderr = io.StringIO()
        real_stderr = api.sys.stderr
        real_environ = api.os.environ
        api.sys.stderr = stderr
        api.os.environ = {"BLIZZARD_CLIENT_SECRET": "super-secret-value"}
        try:
            code = api.main(["--check-config"])
        finally:
            api.sys.stderr = real_stderr
            api.os.environ = real_environ
        self.assertEqual(code, api.EXIT_CONFIG)
        self.assertNotIn("super-secret-value", stderr.getvalue())

    def test_rejected_credentials_are_a_401_and_the_secret_stays_out_of_the_message(self):
        opener = scripted([json_response(401, {"error": "unauthorized", "client_secret": "super-secret-value"})])
        with self.assertRaises(api.ApiFailure) as caught:
            api.run(settings(), opener=opener)
        self.assertEqual(caught.exception.exit_code, api.EXIT_UNAUTHORIZED)
        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0].get_method(), "POST")

    def test_successful_read_saves_a_truncated_roster_and_hides_the_token(self):
        token = "token-value-should-not-leak"
        members = [
            {"character": {"name": "One", "surname": "Alpha", "level": 10}, "rank": 0},
            {"character": {"name": "Two", "surname": "Beta", "level": 2}, "rank": 3},
            {"character": {"name": "Three", "surname": "Gamma", "level": 60}, "rank": 1},
            {"character": {"name": "Four", "surname": "Delta", "level": 9}, "rank": 2},
        ]
        opener = scripted(
            [
                json_response(200, {"access_token": token, "expires_in": 86400, "token_type": "bearer"}),
                json_response(
                    200,
                    {
                        "id": 42,
                        "name": "Herberg",
                        "member_count": 4,
                        "ruleset": {"id": 2, "name": "Normal"},
                    },
                    {"Battlenet-Namespace": "profile-forever-eu", "Battlenet-Schema": "guild"},
                ),
                json_response(200, {"members": members}, {"Battlenet-Schema": "guild-roster"}),
                json_response(200, {"activities": []}),
                json_response(200, {"achievements": []}),
            ]
        )
        waits = []
        with tempfile.TemporaryDirectory() as directory:
            report = api.run(settings(), opener=opener, sleeper=waits.append, sample_dir=directory)
            roster = json.loads(Path(directory, "roster.json").read_text(encoding="utf-8"))
            guild = json.loads(Path(directory, "guild.json").read_text(encoding="utf-8"))
            combined = "\n".join(path.read_text(encoding="utf-8") for path in Path(directory).iterdir())
        self.assertEqual(report["guild_name"], "Herberg")
        self.assertEqual(report["guild_id"], 42)
        self.assertEqual(report["ruleset"], "Normal")
        self.assertEqual(report["roster"], {"members": 4, "with_surname": 4, "with_level": 4})
        self.assertEqual(len(roster["body"]["members"]), 3)
        self.assertEqual(roster["body"]["_ironkeep_sample"]["members_total"], 4)
        self.assertEqual(guild["headers"]["battlenet-namespace"], "profile-forever-eu")
        self.assertNotIn(token, combined)
        self.assertNotIn("super-secret-value", combined)
        self.assertNotIn("Authorization", combined)
        guild_request = opener.requests[1]
        self.assertTrue(guild_request.full_url.startswith("https://eu.api.blizzard.com/data/wow/guild/herberg?"))
        self.assertIn("namespace=profile-forever-eu", guild_request.full_url)
        self.assertEqual(guild_request.get_header("Authorization"), f"Bearer {token}")
        self.assertEqual(waits, [])

    def test_throttling_retries_once_and_caps_the_wait(self):
        token = "token-value-should-not-leak"
        waits = []
        opener = scripted(
            [
                FakeResponse(429, b"", {"Retry-After": "30"}),
                json_response(200, {"access_token": token, "expires_in": 60}),
                FakeResponse(429, b"", {"Retry-After": "9"}),
                json_response(200, {"id": 1, "name": "Herberg", "member_count": 1, "ruleset": {"name": "Normal"}}),
                json_response(200, {"members": []}),
                json_response(200, {"activities": []}),
                json_response(200, {"achievements": []}),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            report = api.run(settings(), opener=opener, sleeper=waits.append, sample_dir=directory)
        self.assertEqual(report["guild_id"], 1)
        self.assertEqual(waits, [api.RETRY_WAIT_CAP_SECONDS, api.RETRY_WAIT_CAP_SECONDS])

    def test_a_second_429_stops_without_inventing_data(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "expires_in": 60}),
                FakeResponse(429, b"", {"Retry-After": "1"}),
                FakeResponse(429, b"", {"Retry-After": "1"}),
            ]
        )
        with self.assertRaises(api.ApiFailure) as caught:
            api.run(settings(), opener=opener, sleeper=lambda _seconds: None)
        self.assertEqual(caught.exception.exit_code, api.EXIT_THROTTLED)
        self.assertIn("429", str(caught.exception))

    def test_not_found_after_a_token_keeps_the_guild_sample(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "expires_in": 60}),
                json_response(200, {"id": 7, "name": "Herberg"}),
                FakeResponse(404, b""),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(api.ApiFailure) as caught:
                api.run(settings(), opener=opener, sample_dir=directory)
            self.assertTrue((Path(directory) / "guild.json").exists())
            self.assertFalse((Path(directory) / "roster.json").exists())
        self.assertEqual(caught.exception.exit_code, api.EXIT_NOT_FOUND)
        self.assertIn("guild.json", str(caught.exception))

    def test_forbidden_namespace_is_distinct_from_not_found(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "expires_in": 60}),
                FakeResponse(403, b""),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(api.ApiFailure) as caught:
                api.run(settings(), opener=opener, sample_dir=directory)
        self.assertEqual(caught.exception.exit_code, api.EXIT_FORBIDDEN)

    def test_network_failure_redacts_the_secret(self):
        opener = FakeOpener(
            lambda *_args: urllib.error.URLError("lookup failed for super-secret-value")
        )
        with self.assertRaises(api.ApiFailure) as caught:
            api.run(settings(), opener=opener)
        self.assertEqual(caught.exception.exit_code, api.EXIT_NETWORK)
        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))

    def test_script_does_not_import_the_application(self):
        source = Path(__file__).with_name("fetch_herberg.py").read_text(encoding="utf-8")
        self.assertNotIn("import ironkeep", source)
        self.assertNotIn("sqlite", source.lower())


if __name__ == "__main__":
    unittest.main()
