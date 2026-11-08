#!/usr/bin/env python3
"""Local read of the consenting user's WoW Forever account profile.

This script is not part of the Ironkeep application. It does not import
Ironkeep, open its database, call an Ironkeep server, or change Discord OAuth.
It does not modify the guild client in fetch_herberg.py.

Credentials come from the environment:

    BLIZZARD_CLIENT_ID       Battle.net application client id
    BLIZZARD_CLIENT_SECRET   Battle.net application client secret

The Battle.net client must already have this exact redirect:

    http://127.0.0.1:8765/callback

The script listens on 127.0.0.1:8765, opens the authorization page for
scope wow.profile, exchanges the returned code once, and requests

    GET https://eu.api.blizzard.com/profile/user/wow?namespace=profile-forever-eu&locale=en_GB

The access token is sent only in the Authorization header. The client secret,
authorization code, access token, and refresh token are never printed or
written to disk. The profile body is not saved.

    python test_account_profile.py --check-config

validates the environment and exits without opening a browser or calling
Battle.net.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 8765
REDIRECT_URI = "http://127.0.0.1:8765/callback"
CALLBACK_PATH = "/callback"
TIMEOUT_SECONDS = 600
AUTHORIZE_URL = "https://oauth.battle.net/authorize"
TOKEN_URL = "https://oauth.battle.net/token"
PROFILE_URL = (
    "https://eu.api.blizzard.com/profile/user/wow"
    "?namespace=profile-forever-eu&locale=en_GB"
)
SCOPE = "wow.profile"
HTTP_TIMEOUT_SECONDS = 20

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_TIMEOUT = 2
EXIT_STATE = 3
EXIT_DENIED = 4
EXIT_CODE = 5
EXIT_TOKEN = 6
EXIT_PROFILE = 7
EXIT_NETWORK = 8
EXIT_UNEXPECTED = 9


class ApiFailure(Exception):
    def __init__(self, message, exit_code=EXIT_UNEXPECTED):
        super().__init__(message)
        self.exit_code = exit_code

    def __str__(self):
        return super().__str__()


class Decision:
    """Outcome of the local callback. __str__ never includes the code."""

    def __init__(self, kind, code="", page="You can close this window.", status=200):
        self.kind = kind
        self.code = code if kind == "ok" else ""
        self.page = page
        self.status = status

    def __str__(self):
        return self.kind


def redact(text, secrets):
    cleaned = "" if text is None else str(text)
    for secret in secrets:
        if secret and len(str(secret)) >= 4:
            cleaned = cleaned.replace(str(secret), "[redacted]")
    cleaned = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Basic\s+\S+", "Basic [redacted]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"(access_token|refresh_token|code)\"?\s*[:=]\s*\"[^\"]+\"",
        lambda match: match.group(1) + ":[redacted]",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"(code|access_token|refresh_token)=[^&\s]+", r"\1=[redacted]", cleaned, flags=re.IGNORECASE)
    return cleaned


def guarded(text, secrets):
    """Return text only when redaction would not have to change it."""
    if redact(text, secrets) != text:
        return None
    return text


def load_settings(environ=None):
    source = os.environ if environ is None else environ
    return {
        "client_id": (source.get("BLIZZARD_CLIENT_ID") or "").strip(),
        "client_secret": (source.get("BLIZZARD_CLIENT_SECRET") or "").strip(),
    }


def validate_settings(settings):
    problems = []
    if not settings["client_id"]:
        problems.append("BLIZZARD_CLIENT_ID is not set.")
    if not settings["client_secret"]:
        problems.append("BLIZZARD_CLIENT_SECRET is not set.")
    return problems


def config_help():
    return "\n".join(
        [
            "Battle.net application credentials are required.",
            "",
            "Set both environment variables and run this script again:",
            "  BLIZZARD_CLIENT_ID",
            "  BLIZZARD_CLIENT_SECRET",
            "",
            "The existing client must use this exact redirect:",
            f"  {REDIRECT_URI}",
            "",
            "Do not reuse DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET.",
        ]
    )


def build_authorize_url(client_id, state):
    query = urllib.parse.urlencode(
        (
            ("client_id", client_id),
            ("redirect_uri", REDIRECT_URI),
            ("response_type", "code"),
            ("scope", SCOPE),
            ("state", state),
        )
    )
    return f"{AUTHORIZE_URL}?{query}"


def states_match(expected, received):
    if not isinstance(expected, str) or not isinstance(received, str):
        return False
    if not expected or not received or len(expected) != len(received):
        return False
    try:
        return hmac.compare_digest(expected, received)
    except (TypeError, ValueError):
        return False


def _first(params, name):
    values = params.get(name) if isinstance(params, dict) else None
    if not isinstance(values, list) or not values:
        return ""
    value = values[0]
    return value if isinstance(value, str) else ""


def interpret_callback(expected_state, path, params):
    """Classify one callback. A wrong path is ignored so the wait can continue."""
    if path != CALLBACK_PATH:
        return Decision("ignore", page="Not found.", status=404)
    received_state = _first(params, "state")
    if not states_match(expected_state, received_state):
        return Decision(
            "invalid_state",
            page="This callback did not match the login that was started.",
            status=400,
        )
    if _first(params, "error"):
        return Decision(
            "denied",
            page="Battle.net did not grant access. You can close this window.",
            status=200,
        )
    if not _first(params, "code"):
        return Decision(
            "missing_code",
            page="The callback did not include an authorization code. You can close this window.",
            status=400,
        )
    return Decision(
        "ok",
        code=_first(params, "code"),
        page="Authorization received. You can close this window.",
        status=200,
    )


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        decision = interpret_callback(self.server.expected_state, parsed.path, params)
        self.server.hold.decision = decision
        self.server.hold.received = True
        self._send(decision.status, decision.page)

    def do_POST(self):
        self._send(405, "Not found.")

    def log_message(self, format, *args):
        return

    def _send(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class _Hold:
    def __init__(self):
        self.received = False
        self.decision = None


def make_server(port=PORT):
    try:
        server = HTTPServer((HOST, port), CallbackHandler)
    except OSError:
        raise ApiFailure("The callback port is already in use.", EXIT_UNEXPECTED) from None
    bound = server.server_address[0]
    if bound != HOST:
        server.server_close()
        raise ApiFailure("The callback listener was not bound to 127.0.0.1.", EXIT_UNEXPECTED)
    server.hold = _Hold()
    return server


def run_callback_loop(server, expected_state, timeout_seconds, now=time.monotonic):
    server.expected_state = expected_state
    deadline = now() + timeout_seconds
    while True:
        remaining = deadline - now()
        if remaining <= 0:
            return Decision("timeout", page="", status=0)
        server.timeout = remaining
        server.handle_request()
        if not server.hold.received:
            continue
        decision = server.hold.decision
        server.hold.received = False
        server.hold.decision = None
        if decision is None or decision.kind == "ignore":
            continue
        return decision


def listen(state, ready, timeout_seconds=TIMEOUT_SECONDS, port=PORT):
    try:
        server = make_server(port)
    except ApiFailure:
        ready.set()
        raise
    ready.set()
    try:
        return run_callback_loop(server, state, timeout_seconds)
    finally:
        server.server_close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener():
    return urllib.request.build_opener(_NoRedirect)


def _read(opener, request):
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            payload = response.read()
            return status, payload
    except urllib.error.HTTPError as error:
        payload = error.read() if error.fp is not None else b""
        return int(error.code), payload
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApiFailure("Could not reach Battle.net.", EXIT_NETWORK) from None


def _json_object(payload):
    if not payload:
        return None
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    return document


def scope_contains(value):
    if not isinstance(value, str):
        return False
    return SCOPE in value.split()


def exchange_code(opener, settings, code):
    pair = f"{settings['client_id']}:{settings['client_secret']}".encode("utf-8")
    encoded = base64.b64encode(pair).decode("ascii")
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }
    ).encode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    status, payload = _read(opener, request)
    if status != 200:
        return status, None
    return status, _json_object(payload)


def fetch_profile(opener, token):
    request = urllib.request.Request(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    status, payload = _read(opener, request)
    if status != 200:
        return status, None
    return status, _json_object(payload)


def _field_names(value):
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(sorted(str(key) for key in value))


def summarize(document):
    """Counts and field names only. Values are never copied into the result."""
    empty = {
        "accounts": "absent",
        "characters": "0",
        "account_fields": "none",
        "character_fields": "none",
        "has_id": False,
        "has_guid": False,
        "saw_character": False,
    }
    if not isinstance(document, dict):
        empty["accounts"] = "not readable"
        empty["characters"] = "not readable"
        return empty
    if "wow_accounts" not in document:
        return empty
    accounts = document["wow_accounts"]
    if not isinstance(accounts, list):
        empty["accounts"] = "present but not a list"
        empty["characters"] = "not readable"
        return empty
    empty["accounts"] = str(len(accounts))
    account = next((item for item in accounts if isinstance(item, dict)), None)
    empty["account_fields"] = _field_names(account)
    total = 0
    first = None
    for item in accounts:
        if not isinstance(item, dict):
            continue
        characters = item.get("characters")
        if not isinstance(characters, list):
            continue
        for character in characters:
            if not isinstance(character, dict):
                continue
            total += 1
            if first is None:
                first = character
    empty["characters"] = str(total)
    empty["character_fields"] = _field_names(first)
    empty["saw_character"] = first is not None
    empty["has_id"] = first is not None and "id" in first
    empty["has_guid"] = first is not None and "guid" in first
    return empty


def _yes_no(summary, key):
    if summary.get("characters") == "not readable" or not summary.get("saw_character"):
        return "not requested" if summary.get("characters") == "not requested" else "no"
    return "yes" if summary.get(key) else "no"


def report_lines(token_status, scope_ok, profile_status, summary):
    if summary is None:
        summary = {
            "accounts": "not requested",
            "characters": "not requested",
            "account_fields": "not requested",
            "character_fields": "not requested",
            "has_id": False,
            "has_guid": False,
            "saw_character": False,
        }
        identity = "not requested"
    else:
        identity = None
    lines = [
        f"OAuth token HTTP status: {token_status}",
        f"Scope includes wow.profile: {'yes' if scope_ok else 'no'}",
        f"Account profile HTTP status: {profile_status}",
        f"wow_accounts: {summary['accounts']}",
        f"Character objects: {summary['characters']}",
        f"Account field names: {summary['account_fields']}",
        f"Character field names: {summary['character_fields']}",
        f"Character has id field: {identity or _yes_no(summary, 'has_id')}",
        f"Character has guid field: {identity or _yes_no(summary, 'has_guid')}",
    ]
    return "\n".join(lines) + "\n"


def _early(kind):
    messages = {
        "timeout": (EXIT_TIMEOUT, "No callback arrived within 10 minutes."),
        "invalid_state": (EXIT_STATE, "The callback state did not match."),
        "denied": (EXIT_DENIED, "Authorization was denied."),
        "missing_code": (EXIT_CODE, "The callback did not include an authorization code."),
    }
    code, message = messages[kind]
    text = report_lines("not requested", False, "not requested", None)
    return text, code, message


def _checked(text, code, message, secrets):
    if guarded(text, secrets) is None or (message and guarded(message, secrets) is None):
        raise ApiFailure(
            "Refusing to print a summary that contains credential material.",
            EXIT_UNEXPECTED,
        )
    return text, code, message


def finish(settings, decision, opener):
    """Exchange one accepted code. The returned text never includes secrets."""
    if decision.kind != "ok":
        return _early(decision.kind)
    code = decision.code
    status, document = exchange_code(opener, settings, code)
    token = ""
    refresh = ""
    scope_ok = False
    if isinstance(document, dict):
        scope_ok = scope_contains(document.get("scope"))
        if document.get("access_token"):
            token = str(document["access_token"])
        if document.get("refresh_token"):
            refresh = str(document["refresh_token"])
    secrets = (settings["client_id"], settings["client_secret"], code, token, refresh)
    try:
        if status != 200 or not token:
            text = report_lines(status, scope_ok, "not requested", None)
            if status == 200:
                message = "The token response could not be read."
            else:
                message = "The token request did not succeed."
            return _checked(text, EXIT_TOKEN, message, secrets)
        profile_status, profile = fetch_profile(opener, token)
        if profile_status != 200:
            text = report_lines(status, scope_ok, profile_status, None)
            return _checked(text, EXIT_PROFILE, "The account profile request did not succeed.", secrets)
        if profile is None:
            text = report_lines(status, scope_ok, profile_status, summarize(None))
            return _checked(text, EXIT_PROFILE, "The account profile response could not be read.", secrets)
        text = report_lines(status, scope_ok, profile_status, summarize(profile))
        return _checked(text, EXIT_OK, "", secrets)
    finally:
        del token
        del refresh
        decision.code = ""


def execute(settings, opener, browser, listener):
    state = secrets.token_urlsafe(32)
    ready = threading.Event()
    holder = {}

    def target():
        try:
            holder["decision"] = listener(state, ready)
        except ApiFailure as failure:
            holder["error"] = failure
            ready.set()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    if not ready.wait(5):
        raise ApiFailure("The callback listener did not start.", EXIT_UNEXPECTED)
    if "error" in holder:
        raise holder["error"]
    url = build_authorize_url(settings["client_id"], state)
    opened = browser(url)
    if opened is False:
        print("The browser did not open. Open this authorization page:", file=sys.stderr)
        print(url, file=sys.stderr)
    thread.join(TIMEOUT_SECONDS + 30)
    if "error" in holder:
        raise holder["error"]
    decision = holder.get("decision") or Decision("timeout")
    return finish(settings, decision, opener)


def _secrets_from(settings):
    return (settings.get("client_id", ""), settings.get("client_secret", ""))


def main(argv=None, environ=None, opener_factory=None, listener=None, browser=None):
    parser = argparse.ArgumentParser(description="Read the consenting user's WoW Forever account profile.")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate the environment and exit without opening a browser or calling Battle.net.",
    )
    args = parser.parse_args(argv)
    settings = load_settings(environ)
    secrets_for_errors = _secrets_from(settings)
    if args.check_config:
        problems = validate_settings(settings)
        if problems:
            print(config_help(), file=sys.stderr)
            return EXIT_CONFIG
        print(
            "Credentials are present. "
            f"Callback is {REDIRECT_URI}. "
            "No browser was opened and no request was sent."
        )
        return EXIT_OK
    problems = validate_settings(settings)
    if problems:
        print(config_help(), file=sys.stderr)
        return EXIT_CONFIG
    opener_factory = opener_factory or build_opener
    listener = listener or listen
    browser = browser or webbrowser.open
    try:
        report, code, message = execute(settings, opener_factory(), browser, listener)
    except ApiFailure as failure:
        print(redact(str(failure), secrets_for_errors), file=sys.stderr)
        return failure.exit_code
    if guarded(report, secrets_for_errors) is None or (message and guarded(message, secrets_for_errors) is None):
        print("Refusing to print a summary that contains credential material.", file=sys.stderr)
        return EXIT_UNEXPECTED
    if message:
        print(message, file=sys.stderr)
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
