#!/usr/bin/env python3
"""Compare one consenting user's Forever characters with the Herberg roster.

The account profile id is the character object's own ``id``. The guild roster
id is ``members[].character.id``. A WoW account id is not a character id.
Names, surnames, and the numbers themselves are never printed or saved.

This script reuses the local OAuth callback in test_account_profile.py.
It does not import Ironkeep, open its database, or change Discord login or
the guild client. Nothing is written to disk.

    python compare_character_ids.py --check-config

validates the environment and exits without a browser or a Battle.net call.
"""

from __future__ import annotations

import argparse
import base64
import sys
import threading
import urllib.request

import test_account_profile as profile

ROSTER_URL = (
    "https://eu.api.blizzard.com/data/wow/guild/herberg/roster"
    "?namespace=profile-forever-eu&locale=en_GB"
)

EXIT_OK = 0
EXIT_GUILD_TOKEN = 10
EXIT_ROSTER = 11


def _blank_scan():
    return {"rows": 0, "ids": [], "invalid": False, "duplicate": False, "readable": True}


def _accept_id(scan, value):
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        scan["invalid"] = True
        return
    if value in scan["ids"]:
        scan["duplicate"] = True
    scan["ids"].append(value)


def _account_character_id(character):
    if "id" not in character:
        return None
    primary = character.get("id")
    nested = character.get("character")
    if isinstance(nested, dict) and "id" in nested and nested.get("id") != primary:
        return "conflict"
    return primary


def collect_account_ids(document):
    """Ids from wow_accounts[].characters[].id. Account ids are ignored."""
    scan = _blank_scan()
    if not isinstance(document, dict) or not isinstance(document.get("wow_accounts"), list):
        scan["readable"] = False
        scan["invalid"] = True
        return scan
    for account in document["wow_accounts"]:
        if not isinstance(account, dict) or not isinstance(account.get("characters"), list):
            scan["invalid"] = True
            continue
        for character in account["characters"]:
            scan["rows"] += 1
            if not isinstance(character, dict):
                scan["invalid"] = True
                continue
            found = _account_character_id(character)
            if found == "conflict":
                scan["invalid"] = True
                continue
            _accept_id(scan, found)
    return scan


def _guild_character_id(member):
    character = member.get("character")
    if not isinstance(character, dict) or "id" not in character:
        return None
    primary = character.get("id")
    if "id" in member and member.get("id") != primary:
        return "conflict"
    return primary


def collect_guild_ids(document):
    """Ids from members[].character.id. Rank is ignored."""
    scan = _blank_scan()
    if not isinstance(document, dict) or not isinstance(document.get("members"), list):
        scan["readable"] = False
        scan["invalid"] = True
        return scan
    for member in document["members"]:
        scan["rows"] += 1
        if not isinstance(member, dict):
            scan["invalid"] = True
            continue
        found = _guild_character_id(member)
        if found == "conflict":
            scan["invalid"] = True
            continue
        _accept_id(scan, found)
    return scan


def compare_ids(account_scan, guild_scan):
    """Return match counts only when every seen id is a unique positive integer."""
    duplicate = account_scan["duplicate"] or guild_scan["duplicate"]
    invalid = account_scan["invalid"] or guild_scan["invalid"]
    if (
        not account_scan["readable"]
        or not guild_scan["readable"]
        or duplicate
        or invalid
        or len(account_scan["ids"]) != account_scan["rows"]
        or len(guild_scan["ids"]) != guild_scan["rows"]
    ):
        return {
            "matching": "not comparable",
            "unmatched": "not comparable",
            "duplicate": "yes" if duplicate else "no",
            "invalid": "yes" if invalid else "no",
        }
    account_ids = set(account_scan["ids"])
    guild_ids = set(guild_scan["ids"])
    matching = len(account_ids & guild_ids)
    return {
        "matching": str(matching),
        "unmatched": str(len(account_ids - guild_ids)),
        "duplicate": "no",
        "invalid": "no",
    }


def report_lines(oauth_status, profile_status, guild_token_status, roster_status, account_rows, guild_rows, result):
    return "\n".join(
        [
            f"OAuth token HTTP status: {oauth_status}",
            f"Account profile HTTP status: {profile_status}",
            f"Guild token HTTP status: {guild_token_status}",
            f"Guild roster HTTP status: {roster_status}",
            f"Account characters: {account_rows}",
            f"Guild characters: {guild_rows}",
            f"Matching character IDs: {result['matching']}",
            f"Unmatched account characters: {result['unmatched']}",
            f"Duplicate IDs: {result['duplicate']}",
            f"Invalid IDs: {result['invalid']}",
        ]
    ) + "\n"


def _withheld():
    return {
        "matching": "not requested",
        "unmatched": "not requested",
        "duplicate": "not requested",
        "invalid": "not requested",
    }


def _checked(text, code, message, secrets):
    if profile.guarded(text, secrets) is None or (message and profile.guarded(message, secrets) is None):
        raise profile.ApiFailure(
            "Refusing to print a summary that contains credential material.",
            profile.EXIT_UNEXPECTED,
        )
    return text, code, message


def request_application_token(opener, settings):
    pair = f"{settings['client_id']}:{settings['client_secret']}".encode("utf-8")
    encoded = base64.b64encode(pair).decode("ascii")
    request = urllib.request.Request(
        profile.TOKEN_URL,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    status, payload = profile._read(opener, request)
    if status != 200:
        return status, ""
    document = profile._json_object(payload)
    if not isinstance(document, dict) or not document.get("access_token"):
        return status, ""
    return status, str(document["access_token"])


def fetch_roster(opener, token):
    request = urllib.request.Request(
        ROSTER_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    status, payload = profile._read(opener, request)
    if status != 200:
        return status, None
    return status, profile._json_object(payload)


def _callback_failure(decision):
    messages = {
        "timeout": (profile.EXIT_TIMEOUT, "No callback arrived within 10 minutes."),
        "invalid_state": (profile.EXIT_STATE, "The callback state did not match."),
        "denied": (profile.EXIT_DENIED, "Authorization was denied."),
        "missing_code": (profile.EXIT_CODE, "The callback did not include an authorization code."),
    }
    code, message = messages[decision.kind]
    text = report_lines("not requested", "not requested", "not requested", "not requested", "not requested", "not requested", _withheld())
    return text, code, message


def finish(settings, decision, opener):
    if decision.kind != "ok":
        return _callback_failure(decision)
    code = decision.code
    oauth_status, token_document = profile.exchange_code(opener, settings, code)
    user_token = ""
    refresh = ""
    if isinstance(token_document, dict):
        if token_document.get("access_token"):
            user_token = str(token_document["access_token"])
        if token_document.get("refresh_token"):
            refresh = str(token_document["refresh_token"])
    app_token = ""
    secrets = (settings["client_id"], settings["client_secret"], code, user_token, refresh, app_token)
    try:
        if oauth_status != 200 or not user_token:
            text = report_lines(oauth_status, "not requested", "not requested", "not requested", "not requested", "not requested", _withheld())
            message = "The token response could not be read." if oauth_status == 200 else "The token request did not succeed."
            return _checked(text, profile.EXIT_TOKEN, message, secrets)
        profile_status, profile_document = profile.fetch_profile(opener, user_token)
        if profile_status != 200:
            text = report_lines(oauth_status, profile_status, "not requested", "not requested", "not requested", "not requested", _withheld())
            return _checked(text, profile.EXIT_PROFILE, "The account profile request did not succeed.", secrets)
        if profile_document is None:
            withheld = _withheld()
            withheld["invalid"] = "yes"
            withheld["matching"] = "not comparable"
            withheld["unmatched"] = "not comparable"
            text = report_lines(oauth_status, profile_status, "not requested", "not requested", "not readable", "not requested", withheld)
            return _checked(text, profile.EXIT_PROFILE, "The account profile response could not be read.", secrets)
        account_scan = collect_account_ids(profile_document)
        guild_status, app_token = request_application_token(opener, settings)
        secrets = (settings["client_id"], settings["client_secret"], code, user_token, refresh, app_token)
        if guild_status != 200 or not app_token:
            text = report_lines(
                oauth_status,
                profile_status,
                guild_status,
                "not requested",
                account_scan["rows"] if account_scan["readable"] else "not readable",
                "not requested",
                _withheld(),
            )
            message = "The guild token response could not be read." if guild_status == 200 else "The guild token request did not succeed."
            return _checked(text, EXIT_GUILD_TOKEN, message, secrets)
        roster_status, roster_document = fetch_roster(opener, app_token)
        if roster_status != 200:
            text = report_lines(
                oauth_status,
                profile_status,
                guild_status,
                roster_status,
                account_scan["rows"] if account_scan["readable"] else "not readable",
                "not requested",
                _withheld(),
            )
            return _checked(text, EXIT_ROSTER, "The guild roster request did not succeed.", secrets)
        if roster_document is None:
            withheld = _withheld()
            withheld["invalid"] = "yes"
            withheld["matching"] = "not comparable"
            withheld["unmatched"] = "not comparable"
            text = report_lines(
                oauth_status,
                profile_status,
                guild_status,
                roster_status,
                account_scan["rows"] if account_scan["readable"] else "not readable",
                "not readable",
                withheld,
            )
            return _checked(text, EXIT_ROSTER, "The guild roster response could not be read.", secrets)
        guild_scan = collect_guild_ids(roster_document)
        result = compare_ids(account_scan, guild_scan)
        text = report_lines(
            oauth_status,
            profile_status,
            guild_status,
            roster_status,
            account_scan["rows"] if account_scan["readable"] else "not readable",
            guild_scan["rows"] if guild_scan["readable"] else "not readable",
            result,
        )
        return _checked(text, EXIT_OK, "", secrets)
    finally:
        del user_token
        del refresh
        del app_token
        decision.code = ""


def execute(settings, opener, browser, listener):
    state = profile.secrets.token_urlsafe(32)
    ready = threading.Event()
    holder = {}

    def target():
        try:
            holder["decision"] = listener(state, ready)
        except profile.ApiFailure as failure:
            holder["error"] = failure
            ready.set()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    if not ready.wait(5):
        raise profile.ApiFailure("The callback listener did not start.", profile.EXIT_UNEXPECTED)
    if "error" in holder:
        raise holder["error"]
    url = profile.build_authorize_url(settings["client_id"], state)
    if browser(url) is False:
        print("The browser did not open. Open this authorization page:", file=sys.stderr)
        print(url, file=sys.stderr)
    thread.join(profile.TIMEOUT_SECONDS + 30)
    if "error" in holder:
        raise holder["error"]
    decision = holder.get("decision") or profile.Decision("timeout")
    return finish(settings, decision, opener)


def main(argv=None, environ=None, opener_factory=None, listener=None, browser=None):
    parser = argparse.ArgumentParser(description="Compare Forever account character ids with the Herberg roster.")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate the environment and exit without opening a browser or calling Battle.net.",
    )
    args = parser.parse_args(argv)
    settings = profile.load_settings(environ)
    secret_values = (settings["client_id"], settings["client_secret"])
    if args.check_config:
        if profile.validate_settings(settings):
            print(profile.config_help(), file=sys.stderr)
            return profile.EXIT_CONFIG
        print(
            "Credentials are present. "
            f"Callback is {profile.REDIRECT_URI}. "
            "Guild roster is Herberg on profile-forever-eu. "
            "No browser was opened and no request was sent."
        )
        return EXIT_OK
    if profile.validate_settings(settings):
        print(profile.config_help(), file=sys.stderr)
        return profile.EXIT_CONFIG
    opener_factory = opener_factory or profile.build_opener
    listener = listener or profile.listen
    browser = browser or profile.webbrowser.open
    try:
        report, code, message = execute(settings, opener_factory(), browser, listener)
    except profile.ApiFailure as failure:
        print(profile.redact(str(failure), secret_values), file=sys.stderr)
        return failure.exit_code
    if profile.guarded(report, secret_values) is None or (message and profile.guarded(message, secret_values) is None):
        print("Refusing to print a summary that contains credential material.", file=sys.stderr)
        return profile.EXIT_UNEXPECTED
    if message:
        print(message, file=sys.stderr)
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
