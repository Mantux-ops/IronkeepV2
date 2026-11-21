#!/usr/bin/env python3
"""Read-only WoW Forever lookup for one guild.

This script is not part of the Ironkeep application. It does not import
Ironkeep, open its database, or change Discord OAuth.

Credentials come from the environment:

    BLIZZARD_CLIENT_ID       Battle.net application client id
    BLIZZARD_CLIENT_SECRET   Battle.net application client secret

Optional:

    BLIZZARD_REGION          eu, us, kr, or tw. Default: eu
    BLIZZARD_GUILD_SLUG      Default: herberg
    BLIZZARD_LOCALE          Default: en_GB
    BLIZZARD_SAMPLE_DIR      Where sanitized JSON is written.
                             Default: samples/live next to this file

Create the client at https://develop.battle.net/access/clients. These are
not Discord credentials. DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET will
not work here.

The script asks for an application token with the client-credentials grant,
then reads the guild, roster, activity, and achievements documents. It never
prints the token or the client secret. A request with no Authorization
header gets an empty 404 from the Battle.net host, so a 404 is only treated
as "not found" after a token was sent.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_URL = "https://oauth.battle.net/token"
REGIONS = ("eu", "us", "kr", "tw")
LOCALE_RE = re.compile(r"^[a-z]{2}_[A-Z]{2}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEADER_KEEP = ("battlenet-namespace", "battlenet-schema", "last-modified", "date", "retry-after")
TIMEOUT_SECONDS = 20
RETRY_WAIT_CAP_SECONDS = 2
ROSTER_SAMPLE_LIMIT = 3

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_UNAUTHORIZED = 2
EXIT_FORBIDDEN = 3
EXIT_NOT_FOUND = 4
EXIT_THROTTLED = 5
EXIT_NETWORK = 6
EXIT_UNEXPECTED = 7


class ApiFailure(Exception):
    def __init__(self, exit_code, message, status=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.status = status


def redact(text, secrets):
    cleaned = "" if text is None else str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"access_token\"?\s*[:=]\s*\"[^\"]+\"", "access_token:[redacted]", cleaned)
    return cleaned


def load_settings(environ=None):
    source = os.environ if environ is None else environ
    region = (source.get("BLIZZARD_REGION") or "eu").strip().lower()
    slug = (source.get("BLIZZARD_GUILD_SLUG") or "herberg").strip().lower()
    locale = (source.get("BLIZZARD_LOCALE") or "en_GB").strip()
    sample_dir = (source.get("BLIZZARD_SAMPLE_DIR") or "").strip()
    return {
        "client_id": (source.get("BLIZZARD_CLIENT_ID") or "").strip(),
        "client_secret": (source.get("BLIZZARD_CLIENT_SECRET") or "").strip(),
        "region": region,
        "slug": slug,
        "locale": locale,
        "sample_dir": sample_dir,
    }


def validate_settings(settings):
    problems = []
    if not settings["client_id"]:
        problems.append("BLIZZARD_CLIENT_ID is not set.")
    if not settings["client_secret"]:
        problems.append("BLIZZARD_CLIENT_SECRET is not set.")
    if settings["region"] not in REGIONS:
        problems.append("BLIZZARD_REGION must be one of: eu, us, kr, tw.")
    if not SLUG_RE.fullmatch(settings["slug"]):
        problems.append("BLIZZARD_GUILD_SLUG must be a lowercase guild slug such as herberg.")
    if not LOCALE_RE.fullmatch(settings["locale"]):
        problems.append("BLIZZARD_LOCALE must look like en_GB.")
    return problems


def missing_credentials_help():
    return "\n".join(
        [
            "Battle.net application credentials are required.",
            "",
            "Set both environment variables and run this script again:",
            "  BLIZZARD_CLIENT_ID",
            "  BLIZZARD_CLIENT_SECRET",
            "",
            "Create them at https://develop.battle.net/access/clients",
            "with a Battle.net account that has an authenticator attached.",
            "The client-credentials grant does not need a redirect URI.",
            "Do not reuse DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET.",
            "",
            "Optional overrides: BLIZZARD_REGION (default eu),",
            "BLIZZARD_GUILD_SLUG (default herberg), BLIZZARD_LOCALE (default en_GB).",
        ]
    )


def _secrets_from(settings, token=""):
    return (settings.get("client_id", ""), settings.get("client_secret", ""), token or "")


def _header_map(headers):
    if headers is None:
        return {}
    if hasattr(headers, "items"):
        pairs = headers.items()
    else:
        pairs = headers
    return {str(key).lower(): str(value) for key, value in pairs}


def _kept_headers(headers):
    mapped = _header_map(headers)
    return {name: mapped[name] for name in HEADER_KEEP if mapped.get(name)}


class Response:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body


def http_exchange(opener, request, timeout, secrets):
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read()
            status = getattr(response, "status", None) or response.getcode()
            return Response(int(status), _header_map(response.headers), payload)
    except urllib.error.HTTPError as error:
        payload = error.read() if error.fp is not None else b""
        return Response(int(error.code), _header_map(error.headers), payload)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = redact(getattr(error, "reason", error), secrets)
        raise ApiFailure(EXIT_NETWORK, f"Could not reach Battle.net: {reason}") from None


def decode_json(response, secrets):
    if not response.body:
        return None
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        excerpt = redact(response.body[:180].decode("utf-8", errors="replace"), secrets)
        raise ApiFailure(
            EXIT_UNEXPECTED,
            f"Battle.net returned HTTP {response.status} with a body that is not JSON: {excerpt}",
            status=response.status,
        ) from None


def failure_for_status(response, secrets, what):
    status = response.status
    retry_after = _header_map(response.headers).get("retry-after", "")
    if status == 401:
        return ApiFailure(
            EXIT_UNAUTHORIZED,
            f"Battle.net rejected the credentials for {what} (401).",
            status=401,
        )
    if status == 403:
        return ApiFailure(
            EXIT_FORBIDDEN,
            f"Battle.net refused {what} (403). A Forever namespace that does not exist returns 403.",
            status=403,
        )
    if status == 404:
        return ApiFailure(
            EXIT_NOT_FOUND,
            f"Battle.net returned 404 for {what} after a token was sent. "
            "The slug may be wrong, or that document is not published.",
            status=404,
        )
    if status == 429:
        extra = f" Retry-After: {retry_after}." if retry_after else ""
        return ApiFailure(
            EXIT_THROTTLED,
            f"Battle.net throttled {what} (429).{extra} The previous guild data was left untouched.",
            status=429,
        )
    excerpt = ""
    if response.body:
        excerpt = " " + redact(response.body[:180].decode("utf-8", errors="replace"), secrets)
    return ApiFailure(
        EXIT_UNEXPECTED,
        f"Battle.net returned HTTP {status} for {what}.{excerpt}",
        status=status,
    )


def request_token(opener, settings, sleeper=time.sleep):
    secrets = _secrets_from(settings)
    pair = f"{settings['client_id']}:{settings['client_secret']}".encode("utf-8")
    encoded = base64.b64encode(pair).decode("ascii")
    def build_request():
        return urllib.request.Request(
            TOKEN_URL,
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )

    response = _exchange_with_one_retry(opener, build_request, secrets, "the token request", sleeper)
    document = decode_json(response, secrets)
    if response.status != 200:
        if response.status == 401:
            raise ApiFailure(
                EXIT_UNAUTHORIZED,
                "Battle.net rejected the client credentials (401). "
                "Check BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET from "
                "https://develop.battle.net/access/clients. Discord OAuth credentials will not work.",
                status=401,
            )
        raise failure_for_status(response, secrets, "the token request")
    if not isinstance(document, dict) or not document.get("access_token"):
        raise ApiFailure(EXIT_UNEXPECTED, "Battle.net did not return an access token.")
    token = str(document["access_token"])
    expires = document.get("expires_in")
    return token, expires


def _exchange_with_one_retry(opener, build_request, secrets, what, sleeper):
    """Send one request. On 429, wait at most two seconds and try once more.

    A production sync should honor the full Retry-After. This proof of concept
    caps the wait so a research run cannot sit on a long throttle window.
    The request is built again for the second attempt because urllib may have
    consumed the first body.
    """
    response = http_exchange(opener, build_request(), TIMEOUT_SECONDS, secrets)
    if response.status != 429:
        return response
    retry_after = _header_map(response.headers).get("retry-after", "")
    try:
        delay = float(retry_after)
    except ValueError:
        delay = 1
    if delay < 0:
        delay = 0
    sleeper(min(delay, RETRY_WAIT_CAP_SECONDS))
    retried = http_exchange(opener, build_request(), TIMEOUT_SECONDS, secrets)
    if retried.status == 429:
        raise failure_for_status(retried, secrets, what)
    return retried


def api_url(settings, suffix):
    namespace = f"profile-forever-{settings['region']}"
    query = urllib.parse.urlencode({"namespace": namespace, "locale": settings["locale"]})
    base = f"https://{settings['region']}.api.blizzard.com/data/wow/guild/{settings['slug']}"
    if suffix:
        base = f"{base}/{suffix}"
    return f"{base}?{query}"


def fetch_document(opener, settings, token, suffix, sleeper=time.sleep):
    secrets = _secrets_from(settings, token)
    url = api_url(settings, suffix)

    def build_request():
        return urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )

    label = suffix or "guild"
    response = _exchange_with_one_retry(opener, build_request, secrets, label, sleeper)
    if response.status != 200:
        raise failure_for_status(response, secrets, label)
    document = decode_json(response, secrets)
    if not isinstance(document, dict):
        raise ApiFailure(EXIT_UNEXPECTED, f"The {label} document was not a JSON object.", status=response.status)
    return url, response, document


def sample_body(kind, document):
    if kind != "roster":
        return document
    members = document.get("members")
    if not isinstance(members, list):
        return document
    copied = dict(document)
    copied["members"] = members[:ROSTER_SAMPLE_LIMIT]
    copied["_ironkeep_sample"] = {
        "note": "Roster members after the first three were omitted from this file.",
        "members_saved": len(copied["members"]),
        "members_total": len(members),
    }
    return copied


def envelope(url, response, document, kind):
    return {
        "request_url": url.split("?")[0],
        "status": response.status,
        "headers": _kept_headers(response.headers),
        "body": sample_body(kind, document),
    }


def write_sample(directory, name, payload, secrets):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if redact(text, secrets) != text:
        raise ApiFailure(EXIT_UNEXPECTED, "Refusing to write a sample that contains credential material.")
    path.write_text(text, encoding="utf-8")
    return path


def list_lengths(document):
    lengths = {}
    for key, value in document.items():
        if isinstance(value, list):
            lengths[key] = len(value)
    return lengths


def roster_counts(document):
    members = document.get("members")
    if not isinstance(members, list):
        return {"members": None, "with_surname": None, "with_level": None}
    with_surname = 0
    with_level = 0
    for member in members:
        character = member.get("character") if isinstance(member, dict) else None
        if not isinstance(character, dict):
            continue
        if character.get("surname"):
            with_surname += 1
        if isinstance(character.get("level"), int):
            with_level += 1
    return {"members": len(members), "with_surname": with_surname, "with_level": with_level}


def default_sample_dir():
    return Path(__file__).resolve().parent / "samples" / "live"


def run(settings, opener=None, sleeper=time.sleep, sample_dir=None):
    problems = validate_settings(settings)
    credential_gaps = [item for item in problems if item.startswith("BLIZZARD_CLIENT_")]
    if credential_gaps and len(credential_gaps) == len(problems):
        raise ApiFailure(EXIT_CONFIG, missing_credentials_help())
    if problems:
        raise ApiFailure(EXIT_CONFIG, "\n".join(problems))

    opener = opener or urllib.request.build_opener()
    token, expires = request_token(opener, settings, sleeper=sleeper)
    secrets = _secrets_from(settings, token)
    directory = Path(settings["sample_dir"]) if settings.get("sample_dir") else Path(sample_dir or default_sample_dir())
    documents = {}
    written = []
    try:
        for suffix in ("", "roster", "activity", "achievements"):
            url, response, document = fetch_document(opener, settings, token, suffix, sleeper=sleeper)
            kind = suffix or "guild"
            documents[kind] = document
            path = write_sample(directory, f"{kind}.json", envelope(url, response, document, kind), secrets)
            written.append(path)
    except ApiFailure as failure:
        saved = ", ".join(path.name for path in written)
        if saved:
            raise ApiFailure(
                failure.exit_code,
                f"{failure} Samples already written: {saved}.",
                status=failure.status,
            ) from None
        raise
    finally:
        del token

    guild = documents["guild"]
    roster = documents["roster"]
    report = {
        "region": settings["region"],
        "slug": settings["slug"],
        "token_expires_in": expires,
        "guild_name": guild.get("name"),
        "guild_id": guild.get("id"),
        "member_count": guild.get("member_count"),
        "ruleset": (guild.get("ruleset") or {}).get("name") if isinstance(guild.get("ruleset"), dict) else None,
        "roster": roster_counts(roster),
        "activity_lists": list_lengths(documents["activity"]),
        "achievement_lists": list_lengths(documents["achievements"]),
        "samples": [str(path) for path in written],
    }
    blob = json.dumps(report, indent=2, ensure_ascii=False)
    if redact(blob, secrets) != blob:
        raise ApiFailure(EXIT_UNEXPECTED, "Refusing to print a summary that contains credential material.")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read a WoW Forever guild with a Battle.net application token.")
    parser.add_argument("--check-config", action="store_true", help="Validate the environment and exit without calling Battle.net.")
    args = parser.parse_args(argv)
    settings = load_settings()
    if args.check_config:
        problems = validate_settings(settings)
        if problems:
            print(missing_credentials_help() if any(item.startswith("BLIZZARD_CLIENT_") for item in problems) else "\n".join(problems), file=sys.stderr)
            return EXIT_CONFIG
        print(
            f"Credentials are present for region {settings['region']}, "
            f"guild slug {settings['slug']}, locale {settings['locale']}."
        )
        return EXIT_OK
    try:
        report = run(settings)
    except ApiFailure as failure:
        print(redact(str(failure), _secrets_from(settings)), file=sys.stderr)
        return failure.exit_code
    print("Application token received. It was not printed or saved.")
    if report.get("token_expires_in") is not None:
        print(f"Token lifetime reported by Battle.net: {report['token_expires_in']} seconds.")
    print(json.dumps({key: value for key, value in report.items() if key != "token_expires_in"}, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
