"""Offline tests for the local account-profile script. No browser and no Battle.net."""

import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import test_account_profile as api


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
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        result = self.handler(request, len(self.requests))
        if isinstance(result, Exception):
            raise result
        return result


def settings():
    return {"client_id": "public-client-id", "client_secret": "super-secret-value"}


def json_response(status, document):
    return FakeResponse(status, json.dumps(document))


def scripted(responses):
    queue = list(responses)

    def handler(_request, _count):
        if not queue:
            raise AssertionError("unexpected extra request")
        return queue.pop(0)

    return FakeOpener(handler)


def capture(callback):
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_out = api.sys.stdout
    previous_err = api.sys.stderr
    api.sys.stdout = stdout
    api.sys.stderr = stderr
    try:
        code = callback()
    finally:
        api.sys.stdout = previous_out
        api.sys.stderr = previous_err
    return code, stdout.getvalue(), stderr.getvalue()


class CallbackTests(unittest.TestCase):
    def test_invalid_state_does_not_keep_the_code(self):
        decision = api.interpret_callback(
            "expected-state-value",
            "/callback",
            {"state": ["wrong-state"], "code": ["LEAKED-CODE-VALUE"]},
        )
        self.assertEqual(decision.kind, "invalid_state")
        self.assertEqual(decision.code, "")
        self.assertNotIn("LEAKED-CODE-VALUE", decision.page)

    def test_missing_code_stops_before_exchange(self):
        decision = api.interpret_callback("expected-state-value", "/callback", {"state": ["expected-state-value"]})
        self.assertEqual(decision.kind, "missing_code")
        text, code, message = api.finish(settings(), decision, scripted([]))
        self.assertEqual(code, api.EXIT_CODE)
        self.assertIn("not requested", text)
        self.assertIn("authorization code", message)

    def test_denied_consent_discards_a_code_and_does_not_call_battle_net(self):
        opener = scripted([])
        decision = api.interpret_callback(
            "expected-state-value",
            "/callback",
            {"state": ["expected-state-value"], "error": ["access_denied"], "code": ["LEAKED-CODE-VALUE"]},
        )
        self.assertEqual(decision.kind, "denied")
        self.assertEqual(decision.code, "")
        text, code, message = api.finish(settings(), decision, opener)
        self.assertEqual(code, api.EXIT_DENIED)
        self.assertEqual(opener.requests, [])
        self.assertIn("Authorization was denied.", message)
        self.assertNotIn("LEAKED-CODE-VALUE", text)
        self.assertNotIn("access_denied", text)

    def test_timeout_does_not_call_battle_net(self):
        clock = {"t": 0}

        class IdleServer:
            def __init__(self):
                self.hold = api._Hold()
                self.timeout = None

            def handle_request(self):
                clock["t"] = 601

        decision = api.run_callback_loop(IdleServer(), "expected-state-value", 600, now=lambda: clock["t"])
        self.assertEqual(decision.kind, "timeout")
        opener = scripted([])
        _text, code, message = api.finish(settings(), decision, opener)
        self.assertEqual(code, api.EXIT_TIMEOUT)
        self.assertEqual(opener.requests, [])
        self.assertIn("10 minutes", message)

    def test_a_wrong_path_is_ignored_until_a_real_callback(self):
        clock = {"t": 0}

        class ScriptedServer:
            def __init__(self):
                self.hold = api._Hold()
                self.timeout = None
                self.calls = 0

            def handle_request(self):
                self.calls += 1
                self.hold.received = True
                if self.calls == 1:
                    self.hold.decision = api.Decision("ignore", page="Not found.", status=404)
                    return
                self.hold.decision = api.Decision("missing_code")

        decision = api.run_callback_loop(ScriptedServer(), "expected-state-value", 600, now=lambda: clock["t"])
        self.assertEqual(decision.kind, "missing_code")

    def test_malformed_token_response_is_not_printed(self):
        opener = scripted([FakeResponse(200, b"super-secret-value LEAKED-CODE-VALUE")])
        decision = api.Decision("ok", code="LEAKED-CODE-VALUE")
        text, code, message = api.finish(settings(), decision, opener)
        self.assertEqual(code, api.EXIT_TOKEN)
        self.assertEqual(len(opener.requests), 1)
        self.assertIn("OAuth token HTTP status: 200", text)
        self.assertIn("could not be read", message)
        self.assertNotIn("super-secret-value", text + message)
        self.assertNotIn("LEAKED-CODE-VALUE", text + message)

    def test_rejected_token_body_is_discarded(self):
        opener = scripted([FakeResponse(401, b'{"access_token":"token-value-should-not-leak","client_secret":"super-secret-value"}')])
        text, code, message = api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(code, api.EXIT_TOKEN)
        self.assertIn("OAuth token HTTP status: 401", text)
        self.assertEqual(len(opener.requests), 1)
        self.assertNotIn("token-value-should-not-leak", text + message)
        self.assertNotIn("super-secret-value", text + message)

    def test_malformed_profile_does_not_print_the_token_or_body(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "scope": "wow.profile", "refresh_token": "refresh-value-should-not-leak"}),
                FakeResponse(200, b"not json token-value-should-not-leak refresh-value-should-not-leak"),
            ]
        )
        text, code, message = api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(code, api.EXIT_PROFILE)
        self.assertIn("Account profile HTTP status: 200", text)
        self.assertIn("wow_accounts: not readable", text)
        self.assertIn("could not be read", message)
        combined = text + message
        self.assertNotIn("token-value-should-not-leak", combined)
        self.assertNotIn("refresh-value-should-not-leak", combined)
        self.assertNotIn("LEAKED-CODE-VALUE", combined)

    def test_profile_error_status_does_not_include_the_body(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "scope": "wow.profile"}),
                FakeResponse(403, b"token-value-should-not-leak Hidden#1234"),
            ]
        )
        text, code, _message = api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(code, api.EXIT_PROFILE)
        self.assertIn("Account profile HTTP status: 403", text)
        self.assertIn("wow_accounts: not requested", text)
        self.assertNotIn("token-value-should-not-leak", text)
        self.assertNotIn("Hidden#1234", text)

    def test_network_failure_does_not_include_the_secret_or_code(self):
        opener = FakeOpener(lambda *_args: urllib.error.URLError("lookup failed for super-secret-value and LEAKED-CODE-VALUE"))
        with self.assertRaises(api.ApiFailure) as caught:
            api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(caught.exception.exit_code, api.EXIT_NETWORK)
        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertNotIn("LEAKED-CODE-VALUE", str(caught.exception))


class SummaryTests(unittest.TestCase):
    def test_success_prints_counts_and_field_names_only(self):
        profile = {
            "id": 999001,
            "battletag": "Hidden#1234",
            "wow_accounts": [
                {
                    "id": 888002,
                    "battletag": "Hidden#1234",
                    "characters": [
                        {
                            "id": 424242,
                            "name": "Secretname",
                            "surname": "Secretlast",
                            "guid": "Player-should-not-print",
                            "slug": "secretname-secretlast",
                        },
                        {"id": 7, "name": "Othername"},
                    ],
                },
                {"id": 3, "characters": [{"name": "Thirdname"}]},
            ],
        }
        opener = scripted(
            [
                json_response(
                    200,
                    {
                        "access_token": "token-value-should-not-leak",
                        "refresh_token": "refresh-value-should-not-leak",
                        "scope": "openid wow.profile",
                    },
                ),
                json_response(200, profile),
            ]
        )
        text, code, message = api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(code, api.EXIT_OK)
        self.assertEqual(message, "")
        self.assertIn("OAuth token HTTP status: 200\n", text)
        self.assertIn("Scope includes wow.profile: yes\n", text)
        self.assertIn("Account profile HTTP status: 200\n", text)
        self.assertIn("wow_accounts: 2\n", text)
        self.assertIn("Character objects: 3\n", text)
        self.assertIn("Account field names: battletag, characters, id\n", text)
        self.assertIn("Character field names: guid, id, name, slug, surname\n", text)
        self.assertIn("Character has id field: yes\n", text)
        self.assertIn("Character has guid field: yes\n", text)
        profile_request = opener.requests[1]
        self.assertEqual(profile_request.full_url, api.PROFILE_URL)
        self.assertEqual(profile_request.get_method(), "GET")
        self.assertEqual(profile_request.get_header("Authorization"), "Bearer token-value-should-not-leak")
        self.assertNotIn("access_token", profile_request.full_url)
        token_body = opener.requests[0].data.decode("ascii")
        self.assertIn("grant_type=authorization_code", token_body)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback", token_body)
        self.assertNotIn("super-secret-value", token_body)
        for leaked in (
            "Secretname",
            "Secretlast",
            "Othername",
            "Thirdname",
            "424242",
            "888002",
            "999001",
            "Hidden#1234",
            "Player-should-not-print",
            "secretname-secretlast",
            "super-secret-value",
            "token-value-should-not-leak",
            "refresh-value-should-not-leak",
            "LEAKED-CODE-VALUE",
        ):
            self.assertNotIn(leaked, text)

    def test_absent_wow_accounts_is_reported_without_values(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "scope": "wow.profileextra"}),
                json_response(200, {"id": 999001, "battletag": "Hidden#1234"}),
            ]
        )
        text, code, _message = api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(code, api.EXIT_OK)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("Scope includes wow.profile: no", text)
        self.assertIn("wow_accounts: absent", text)
        self.assertIn("Character objects: 0", text)
        self.assertIn("Character has id field: no", text)
        self.assertIn("Character has guid field: no", text)
        self.assertNotIn("Hidden#1234", text)
        self.assertNotIn("999001", text)

    def test_a_non_list_wow_accounts_value_is_not_printed(self):
        summary = api.summarize({"wow_accounts": "Hidden#1234"})
        self.assertEqual(summary["accounts"], "present but not a list")
        self.assertNotIn("Hidden#1234", summary["accounts"])
        self.assertNotIn("Hidden#1234", summary["account_fields"])
        self.assertNotIn("Hidden#1234", summary["character_fields"])

    def test_a_secret_used_as_a_field_name_is_not_printed(self):
        opener = scripted(
            [
                json_response(200, {"access_token": "token-value-should-not-leak", "scope": "wow.profile"}),
                json_response(200, {"wow_accounts": [{"super-secret-value": 1, "characters": [{"id": 1}]}]}),
            ]
        )
        with self.assertRaises(api.ApiFailure) as caught:
            api.finish(settings(), api.Decision("ok", code="LEAKED-CODE-VALUE"), opener)
        self.assertEqual(caught.exception.exit_code, api.EXIT_UNEXPECTED)
        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertNotIn("token-value-should-not-leak", str(caught.exception))


class LocalFlowTests(unittest.TestCase):
    def test_check_config_makes_no_request_and_hides_the_secret(self):
        calls = []

        def forbid(*_args, **_kwargs):
            calls.append("called")
            raise AssertionError("check-config made a call")

        code, stdout, stderr = capture(
            lambda: api.main(
                ["--check-config"],
                environ={"BLIZZARD_CLIENT_ID": "public-client-id", "BLIZZARD_CLIENT_SECRET": "super-secret-value"},
                opener_factory=forbid,
                listener=forbid,
                browser=forbid,
            )
        )
        self.assertEqual(code, api.EXIT_OK)
        self.assertEqual(calls, [])
        self.assertIn("Credentials are present.", stdout)
        self.assertIn(api.REDIRECT_URI, stdout)
        self.assertIn("No browser was opened and no request was sent.", stdout)
        self.assertNotIn("super-secret-value", stdout + stderr)
        self.assertNotIn("public-client-id", stdout + stderr)

    def test_missing_credentials_name_the_variable_only(self):
        code, stdout, stderr = capture(
            lambda: api.main(["--check-config"], environ={"BLIZZARD_CLIENT_SECRET": "super-secret-value"})
        )
        self.assertEqual(code, api.EXIT_CONFIG)
        self.assertIn("BLIZZARD_CLIENT_ID", stderr)
        self.assertNotIn("super-secret-value", stdout + stderr)
        self.assertEqual(stdout, "")

    def test_authorize_url_has_the_required_fields_and_not_the_secret(self):
        url = api.build_authorize_url("public-client-id", "expected-state-value")
        self.assertTrue(url.startswith(api.AUTHORIZE_URL + "?"))
        self.assertIn("response_type=code", url)
        self.assertIn("scope=wow.profile", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback", url)
        self.assertIn("state=expected-state-value", url)
        self.assertIn("client_id=public-client-id", url)
        self.assertNotIn("super-secret-value", url)

    def test_execute_timeout_does_not_request_a_token(self):
        opener = scripted([])
        seen = []

        def listener(_state, ready):
            ready.set()
            return api.Decision("timeout")

        def browser(url):
            seen.append(url)
            return False

        code, _stdout, stderr = capture(lambda: api.execute(settings(), opener, browser, listener)[1])
        self.assertEqual(code, api.EXIT_TIMEOUT)
        self.assertEqual(opener.requests, [])
        self.assertNotIn("super-secret-value", stderr)
        self.assertIn("oauth.battle.net/authorize", stderr)
        self.assertNotIn("code=", seen[0])

    def test_listener_binds_only_loopback_and_the_page_hides_the_code(self):
        server = api.make_server(0)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        port = server.server_address[1]
        holder = {}

        def run():
            holder["decision"] = api.run_callback_loop(server, "expected-state-value", 5)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            favicon = _get(port, "/favicon.ico")
            denied = _get(
                port,
                "/callback?state=expected-state-value&error=access_denied&code=LEAKED-CODE-VALUE",
            )
        finally:
            thread.join(5)
            server.server_close()
        self.assertIn("Not found.", favicon)
        self.assertIn("did not grant access", denied)
        self.assertNotIn("LEAKED-CODE-VALUE", favicon + denied)
        self.assertEqual(holder["decision"].kind, "denied")
        self.assertEqual(holder["decision"].code, "")

    def test_occupied_port_has_a_fixed_message(self):
        server = api.make_server(0)
        try:
            with self.assertRaises(api.ApiFailure) as caught:
                api.make_server(server.server_address[1])
        finally:
            server.server_close()
        self.assertEqual(str(caught.exception), "The callback port is already in use.")

    def test_callback_log_does_not_write_the_query(self):
        stderr = io.StringIO()
        previous = api.sys.stderr
        api.sys.stderr = stderr
        try:
            api.CallbackHandler.log_message(object(), 'GET %s HTTP/1.1', "/callback?code=LEAKED-CODE-VALUE")
        finally:
            api.sys.stderr = previous
        self.assertEqual(stderr.getvalue(), "")

    def test_script_does_not_import_the_application_or_the_guild_client(self):
        source = Path(__file__).with_name("test_account_profile.py").read_text(encoding="utf-8")
        self.assertNotIn("import ironkeep", source)
        self.assertNotIn("import fetch_herberg", source)
        self.assertNotIn("sqlite", source.lower())
        self.assertNotIn("import discord", source)
        self.assertNotIn("from discord", source)


def _get(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    last = None
    for _attempt in range(30):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
            time.sleep(0.05)
    raise AssertionError(last)


if __name__ == "__main__":
    unittest.main()
