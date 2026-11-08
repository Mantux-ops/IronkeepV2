#!/usr/bin/env python3
"""Read-only probe of WoW Forever character endpoints for one Herberg member.

Blizzard's published profile reference documents these shapes for retail,
with a realm in the path. Forever is not in that reference. The suffixes
below are experimental candidates reported by community probes. This script
does not assume they work.

It requests an application token, reads the Herberg roster on
profile-forever-eu, and follows one character.key.href supplied by that
roster. It never builds a profile URL from a name, slug, or hardcoded id.
Raw bodies are not saved. Names, surnames, ids, tokens, and URLs are not
printed.

    python probe_character_endpoints.py --check-config

validates the environment and exits without calling Battle.net.
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
import urllib.parse
import urllib.request

HOST = "eu.api.blizzard.com"
NAMESPACE = "profile-forever-eu"
LOCALE = "en_GB"
TOKEN_URL = "https://oauth.battle.net/token"
ROSTER_URL = (
    "https://eu.api.blizzard.com/data/wow/guild/herberg/roster"
    "?namespace=profile-forever-eu&locale=en_GB"
)
GUILD_URL = (
    "https://eu.api.blizzard.com/data/wow/guild/herberg"
    "?namespace=profile-forever-eu&locale=en_GB"
)
TIMEOUT_SECONDS = 20
REQUEST_INTERVAL_SECONDS = 1.0
RETRY_WAIT_CAP_SECONDS = 2.0
LEVEL_READY = 10
SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,48}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_UNAUTHORIZED = 2
EXIT_ROSTER = 4
EXIT_NETWORK = 6
EXIT_UNEXPECTED = 7

# Retail-shaped suffixes. Each entry is (category, path suffix, source keys).
CHARACTER_RESOURCES = (
    ("character equipment", "equipment", ("equipment",)),
    ("character specializations", "specializations", ("specializations",)),
    ("character statistics", "statistics", ("statistics",)),
    ("character professions", "professions", ("professions",)),
    ("character achievements", "achievements", ("achievements",)),
    ("character media", "character-media", ("character_media", "media")),
    ("character appearance", "appearance", ("appearance",)),
)


class ApiFailure(Exception):
    def __init__(self, message, exit_code=EXIT_UNEXPECTED):
        super().__init__(message)
        self.exit_code = exit_code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener():
    return urllib.request.build_opener(_NoRedirect)


def redact(text, secrets):
    cleaned = "" if text is None else str(text)
    for secret in secrets:
        if secret and len(str(secret)) >= 4:
            cleaned = cleaned.replace(str(secret), "[redacted]")
    cleaned = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Basic\s+\S+", "Basic [redacted]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(access_token|refresh_token)=[^&\s]+", r"\1=[redacted]", cleaned, flags=re.IGNORECASE)
    return cleaned


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
            "Do not reuse DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET.",
            "This probe stays on eu.api.blizzard.com and profile-forever-eu.",
        ]
    )


def _read(opener, request):
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            payload = response.read()
            last_modified = bool(response.headers.get("last-modified")) if response.headers is not None else False
            return status, payload, last_modified
    except urllib.error.HTTPError as error:
        if error.fp is not None:
            error.read()
        return int(error.code), b"", False
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


def request_token(opener, settings):
    pair = f"{settings['client_id']}:{settings['client_secret']}".encode("utf-8")
    encoded = base64.b64encode(pair).decode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    status, payload, _last_modified = _read(opener, request)
    if status != 200:
        return status, ""
    document = _json_object(payload)
    if not isinstance(document, dict) or not document.get("access_token"):
        return status, ""
    return status, str(document["access_token"])


def fetch_json(opener, token, url, sleeper, retry=True):
    """GET one URL. On 429, wait at most two seconds and try once."""
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    status, payload, last_modified = _read(opener, request)
    if status == 429 and retry:
        sleeper(RETRY_WAIT_CAP_SECONDS)
        return fetch_json(opener, token, url, sleeper, retry=False)
    document = _json_object(payload) if status == 200 else None
    return status, document, last_modified


def canonical_character_url(href, suffix=""):
    """Accept only an EU Forever character URL. Return the canonical GET URL."""
    if not isinstance(href, str) or not href:
        return None
    parsed = urllib.parse.urlsplit(href.strip())
    if parsed.scheme != "https" or parsed.hostname != HOST:
        return None
    if parsed.username or parsed.password or parsed.fragment:
        return None
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    parts = path.split("/")
    if len(parts) < 5 or parts[0] != "" or parts[1:4] != ["profile", "wow", "character"]:
        return None
    if any(part in ("", ".", "..") for part in parts[1:]):
        return None
    slug = parts[4]
    if not SLUG_RE.fullmatch(slug):
        return None
    extra = parts[5:]
    if suffix:
        if extra != [suffix]:
            return None
    elif extra:
        return None
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    namespaces = query.get("namespace")
    if namespaces is not None and namespaces != [NAMESPACE]:
        return None
    if any(key not in ("namespace", "locale") for key in query):
        return None
    safe_path = "/".join(parts)
    return f"https://{HOST}{safe_path}?namespace={NAMESPACE}&locale={LOCALE}"


def _secret_strings(document, keys):
    found = []
    if not isinstance(document, dict):
        return found
    for key in keys:
        value = document.get(key)
        if isinstance(value, str) and len(value.strip()) >= 4:
            found.append(value.strip())
        elif type(value) is int and not isinstance(value, bool) and len(str(value)) >= 4:
            found.append(str(value))
    return found


def _identity_secrets(member):
    character = member.get("character") if isinstance(member, dict) else None
    return _secret_strings(character, ("name", "surname", "slug", "id"))


def character_profile_link(member):
    if not isinstance(member, dict):
        return None
    character = member.get("character")
    if not isinstance(character, dict):
        return None
    key = character.get("key")
    href = key.get("href") if isinstance(key, dict) else None
    return canonical_character_url(href)


def _level(member):
    character = member.get("character") if isinstance(member, dict) else None
    if not isinstance(character, dict):
        return None
    level = character.get("level")
    if type(level) is not int or isinstance(level, bool):
        return None
    return level


def select_subject(document):
    """Pick one roster member. Prefer level 10 or above. Never invent a URL."""
    if not isinstance(document, dict) or not isinstance(document.get("members"), list):
        return {
            "readable": False,
            "characters": "not readable",
            "links": "not readable",
            "selection": "not readable",
            "url": None,
            "member": None,
        }
    members = document["members"]
    ready = None
    fallback = None
    fallback_label = ""
    links = 0
    for member in members:
        url = character_profile_link(member)
        if url is None:
            continue
        links += 1
        level = _level(member)
        if level is not None and level >= LEVEL_READY and ready is None:
            ready = (url, member)
            continue
        if fallback is None:
            if level is None:
                fallback = (url, member)
                fallback_label = "level was not supplied"
            elif level < LEVEL_READY:
                fallback = (url, member)
                fallback_label = "below level 10"
    if ready is not None:
        url, member = ready
        label = "level 10 or above"
    elif fallback is not None:
        url, member = fallback
        label = fallback_label
    else:
        url, member = None, None
        label = "no Blizzard profile link"
    return {
        "readable": True,
        "characters": str(len(members)),
        "links": str(links),
        "selection": label,
        "url": url,
        "member": member if isinstance(member, dict) else None,
    }


def child_url(profile_url, suffix):
    parsed = urllib.parse.urlsplit(profile_url)
    return canonical_character_url(f"{parsed.scheme}://{parsed.netloc}{parsed.path}/{suffix}?{parsed.query}", suffix)


def resource_url(profile_document, profile_url, suffix, keys):
    """Use a profile href when it is the same EU Forever resource. Else the suffix."""
    expected = child_url(profile_url, suffix)
    if isinstance(profile_document, dict):
        for key in keys:
            value = profile_document.get(key)
            href = value.get("href") if isinstance(value, dict) else None
            if expected is not None and canonical_character_url(href, suffix) == expected:
                return expected, "profile link"
    return expected, "experimental suffix"


def field_names(document):
    if not isinstance(document, dict):
        return "none"
    keys = sorted(key for key in document if isinstance(key, str) and SAFE_KEY.fullmatch(key))
    return ", ".join(keys) if keys else "none"


def _dict_has(document, key):
    return isinstance(document, dict) and isinstance(document.get(key), dict)


def _nonempty_dicts(document, key):
    value = document.get(key) if isinstance(document, dict) else None
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)


def _positive_int(document, key):
    value = document.get(key) if isinstance(document, dict) else None
    return type(value) is int and not isinstance(value, bool) and value > 0


def _text(document, key):
    value = document.get(key) if isinstance(document, dict) else None
    return isinstance(value, str) and bool(value.strip())


def profile_data(document):
    labels = []
    if _text(document, "name") and _text(document, "surname"):
        labels.append("name and surname")
    if _positive_int(document, "id"):
        labels.append("character id")
    if _positive_int(document, "level") or (isinstance(document, dict) and type(document.get("level")) is int and document.get("level") == 0):
        labels.append("level")
    if _dict_has(document, "character_class") or _dict_has(document, "playable_class"):
        labels.append("class")
    if _dict_has(document, "race") or _dict_has(document, "playable_race"):
        labels.append("race")
    if _dict_has(document, "faction"):
        labels.append("faction")
    if _positive_int(document, "average_item_level"):
        labels.append("item level")
    if _dict_has(document, "equipment"):
        labels.append("equipment link")
    return labels


def profile_result(labels):
    required = ("name and surname", "character id", "level", "class", "race")
    if all(item in labels for item in required):
        return "complete"
    if labels:
        return "partial"
    return "partial"


def collection_labels(document, pairs):
    labels = []
    for key, label in pairs:
        if _nonempty_dicts(document, key) or _positive_int(document, key):
            labels.append(label)
    return list(dict.fromkeys(labels))


def equipment_labels(document):
    labels = []
    if _nonempty_dicts(document, "equipped_items"):
        labels.append("equipped items")
        items = document.get("equipped_items")
        if any(isinstance(item, dict) and (_positive_int(item, "item_level") or _positive_int(item, "level")) for item in items):
            labels.append("item level")
    return labels


def media_labels(document):
    labels = []
    if _nonempty_dicts(document, "assets"):
        labels.append("media assets")
        for item in document.get("assets"):
            if not isinstance(item, dict):
                continue
            kind = item.get("key") if isinstance(item.get("key"), str) else item.get("type")
            if kind in ("avatar", "inset"):
                labels.append("portrait")
            elif kind in ("main", "main-raw", "render"):
                labels.append("character render")
    for key, label in (("avatar", "portrait"), ("inset", "portrait"), ("main", "character render"), ("render", "character render")):
        if _text(document, key) or _dict_has(document, key):
            labels.append(label)
    return list(dict.fromkeys(labels))


def appearance_labels(document):
    labels = []
    if _nonempty_dicts(document, "customizations") or _nonempty_dicts(document, "items"):
        labels.append("appearance")
    if _dict_has(document, "playable_race") or _dict_has(document, "race"):
        labels.append("race")
    if _dict_has(document, "playable_class") or _dict_has(document, "character_class"):
        labels.append("class")
    return labels


def rank_labels(member, guild):
    labels = []
    rank = member.get("rank") if isinstance(member, dict) else None
    if type(rank) is int and not isinstance(rank, bool) and rank >= 0:
        labels.append("numeric rank")
    for source in (member, guild):
        if not isinstance(source, dict):
            continue
        for key in ("rank_name", "rank_title", "title"):
            if _text(source, key):
                labels.append("rank title")
        ranks = source.get("ranks")
        if isinstance(ranks, list) and any(isinstance(item, dict) and _text(item, "name") for item in ranks):
            labels.append("rank titles")
    return list(dict.fromkeys(labels))


def login_labels(document, last_modified):
    labels = []
    if _positive_int(document, "last_login_timestamp"):
        labels.append("last login")
    if last_modified:
        labels.append("logout header")
    return labels


def _row(category, status, available, fields, data, result, source):
    return {
        "category": category,
        "status": status,
        "available": available,
        "fields": fields,
        "data": data,
        "result": result,
        "source": source,
    }


def _unavailable(category, status, source):
    return _row(category, status, "no", "none", "none", "unavailable", source)


def _from_document(category, status, document, labels, source, complete_when):
    if status != 200 or not isinstance(document, dict):
        return _unavailable(category, status, source)
    data = ", ".join(labels) if labels else "none"
    result = "complete" if complete_when else "partial"
    return _row(category, str(status), "yes", field_names(document), data, result, source)


def assess_profile(status, document):
    labels = profile_data(document)
    return _from_document(
        "character profile summary",
        status,
        document,
        labels,
        "roster link",
        profile_result(labels) == "complete",
    )


def assess_equipment(status, document, source):
    labels = equipment_labels(document)
    return _from_document("character equipment", status, document, labels, source, "equipped items" in labels)


def specialization_labels(document):
    labels = collection_labels(
        document,
        (("specializations", "specializations"), ("talents", "talents"), ("selected_talents", "talents")),
    )
    specs = document.get("specializations") if isinstance(document, dict) else None
    if isinstance(specs, list) and any(
        isinstance(item, dict) and (_nonempty_dicts(item, "talents") or _nonempty_dicts(item, "loadouts"))
        for item in specs
    ):
        labels.append("talents")
    return list(dict.fromkeys(labels))


def assess_specializations(status, document, source):
    labels = specialization_labels(document)
    return _from_document("character specializations", status, document, labels, source, bool(labels))


def assess_statistics(status, document, source):
    labels = collection_labels(document, (("statistics", "statistics"), ("categories", "statistics")))
    return _from_document("character statistics", status, document, labels, source, bool(labels))


def assess_professions(status, document, source):
    labels = collection_labels(document, (("primaries", "professions"), ("secondaries", "professions")))
    return _from_document("character professions", status, document, labels, source, bool(labels))


def assess_achievements(status, document, source):
    labels = collection_labels(
        document,
        (("achievements", "achievements"), ("total_quantity", "achievements"), ("total_points", "achievements")),
    )
    return _from_document("character achievements", status, document, labels, source, "achievements" in labels)


def assess_media(status, document, source):
    labels = media_labels(document)
    return _from_document("character media", status, document, labels, source, bool(labels))


def assess_appearance(status, document, source):
    labels = appearance_labels(document)
    return _from_document("character appearance", status, document, labels, source, "appearance" in labels)


def roster_has_numeric_rank(document):
    members = document.get("members") if isinstance(document, dict) else None
    if not isinstance(members, list):
        return False
    for member in members:
        rank = member.get("rank") if isinstance(member, dict) else None
        if type(rank) is int and not isinstance(rank, bool) and rank >= 0:
            return True
    return False


def assess_rank(member, roster, guild_status, guild):
    labels = rank_labels(member, guild if guild_status == 200 else None)
    if "numeric rank" not in labels and roster_has_numeric_rank(roster):
        labels.insert(0, "numeric rank")
    source = "roster member and guild document"
    if guild_status != 200 and "numeric rank" not in labels and "rank title" not in labels and "rank titles" not in labels:
        return _unavailable("guild rank details", guild_status, source)
    if "rank title" in labels or "rank titles" in labels:
        result = "complete"
    elif labels:
        result = "partial"
    else:
        result = "unavailable"
    fields = field_names(guild) if guild_status == 200 and isinstance(guild, dict) else "none"
    status = str(guild_status)
    if guild_status != 200 and labels:
        status = "roster only"
        fields = "rank"
    return _row(
        "guild rank details",
        status,
        "yes" if labels else "no",
        fields,
        ", ".join(labels) if labels else "none",
        result,
        source,
    )


def assess_login(status, document, last_modified):
    labels = login_labels(document if status == 200 else None, last_modified if status == 200 else False)
    return _from_document("character last login", status, document if status == 200 else None, labels, "profile summary", bool(labels))


def skipped_character_rows(status="not requested"):
    categories = (
        "character profile summary",
        "character equipment",
        "character specializations",
        "character statistics",
        "character professions",
        "character achievements",
        "character media",
        "character appearance",
        "character last login",
    )
    return [_unavailable(category, status, "not requested") for category in categories]


ASSESSORS = {
    "character equipment": assess_equipment,
    "character specializations": assess_specializations,
    "character statistics": assess_statistics,
    "character professions": assess_professions,
    "character achievements": assess_achievements,
    "character media": assess_media,
    "character appearance": assess_appearance,
}


def render(header, rows):
    lines = [
        f"OAuth token HTTP status: {header['token_status']}",
        f"Guild roster HTTP status: {header['roster_status']}",
        f"Guild document HTTP status: {header['guild_status']}",
        f"Roster characters: {header['characters']}",
        f"Roster profile links: {header['links']}",
        f"Selected character: {header['selection']}",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"Endpoint: {row['category']}",
                f"HTTP status: {row['status']}",
                f"Available: {row['available']}",
                f"Fields: {row['fields']}",
                f"Data: {row['data']}",
                f"Result: {row['result']}",
                f"Source: {row['source']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _guard(text, secrets):
    if redact(text, secrets) != text:
        raise ApiFailure("Refusing to print a summary that contains credential material.", EXIT_UNEXPECTED)
    return text


def probe(settings, opener, sleeper=time.sleep):
    token_status, token = request_token(opener, settings)
    secrets = [settings["client_id"], settings["client_secret"], token]
    header = {
        "token_status": token_status,
        "roster_status": "not requested",
        "guild_status": "not requested",
        "characters": "not requested",
        "links": "not requested",
        "selection": "not requested",
    }
    try:
        if token_status != 200 or not token:
            message = "The token response could not be read." if token_status == 200 else "The token request did not succeed."
            text = render(header, skipped_character_rows() + [_unavailable("guild rank details", "not requested", "not requested")])
            return _guard(text, secrets), EXIT_UNAUTHORIZED if token_status == 401 else EXIT_UNEXPECTED, message
        sleeper(REQUEST_INTERVAL_SECONDS)
        roster_status, roster, _roster_modified = fetch_json(opener, token, ROSTER_URL, sleeper)
        header["roster_status"] = roster_status
        if roster_status != 200 or roster is None:
            message = "The guild roster request did not succeed." if roster_status != 200 else "The guild roster response could not be read."
            code = EXIT_ROSTER if roster_status != 200 else EXIT_UNEXPECTED
            text = render(header, skipped_character_rows() + [_unavailable("guild rank details", "not requested", "not requested")])
            return _guard(text, secrets), code, message
        subject = select_subject(roster)
        header["characters"] = subject["characters"]
        header["links"] = subject["links"]
        header["selection"] = subject["selection"]
        if subject["url"]:
            secrets.append(urllib.parse.urlsplit(subject["url"]).path.rsplit("/", 1)[-1])
        sleeper(REQUEST_INTERVAL_SECONDS)
        guild_status, guild, _guild_modified = fetch_json(opener, token, GUILD_URL, sleeper)
        header["guild_status"] = guild_status
        rows = []
        if not subject["readable"]:
            rows.extend(skipped_character_rows())
            rows.append(_unavailable("guild rank details", guild_status, "roster member and guild document"))
            text = render(header, rows)
            return _guard(text, secrets), EXIT_UNEXPECTED, "The guild roster response could not be read."
        secrets.extend(_identity_secrets(subject["member"]))
        if subject["url"] is None:
            rows.extend(skipped_character_rows())
            rows.append(assess_rank(None, roster, guild_status, guild))
            text = render(header, rows)
            return _guard(text, secrets), EXIT_OK, ""
        sleeper(REQUEST_INTERVAL_SECONDS)
        profile_status, profile, profile_modified = fetch_json(opener, token, subject["url"], sleeper)
        secrets.extend(_secret_strings(profile, ("name", "surname", "slug", "id", "name_search")))
        rows.append(assess_profile(profile_status, profile))
        if profile_status != 200 or profile is None:
            for category, _suffix, _keys in CHARACTER_RESOURCES:
                rows.append(_unavailable(category, "not requested", "not requested"))
            rows.append(assess_rank(subject["member"], roster, guild_status, guild))
            rows.append(assess_login(profile_status, profile, profile_modified))
            message = "" if profile_status != 200 else "The character profile response could not be read."
            text = render(header, rows)
            return _guard(text, secrets), EXIT_OK, message
        stop = None
        fetched = {}
        for category, suffix, keys in CHARACTER_RESOURCES:
            if stop is not None:
                fetched[category] = _unavailable(category, "not requested", "not requested")
                continue
            url, source = resource_url(profile, subject["url"], suffix, keys)
            sleeper(REQUEST_INTERVAL_SECONDS)
            if url is None:
                fetched[category] = _unavailable(category, "not requested", "not requested")
                continue
            try:
                status, document, _modified = fetch_json(opener, token, url, sleeper)
            except ApiFailure:
                fetched[category] = _unavailable(category, "network", source)
                stop = "network"
                continue
            fetched[category] = ASSESSORS[category](status, document, source)
            if status in (401, 429):
                stop = status
        for category, _suffix, _keys in CHARACTER_RESOURCES:
            rows.append(fetched[category])
        rows.append(assess_rank(subject["member"], roster, guild_status, guild))
        rows.append(assess_login(profile_status, profile, profile_modified))
        message = ""
        if stop == 429:
            message = "Stopped after HTTP 429."
        elif stop == 401:
            message = "Stopped after HTTP 401."
        elif stop == "network":
            message = "Could not reach Battle.net."
        text = render(header, rows)
        return _guard(text, secrets), EXIT_OK, message
    finally:
        del token


def main(argv=None, environ=None, opener_factory=None, sleeper=None):
    parser = argparse.ArgumentParser(description="Probe WoW Forever character endpoints for one Herberg roster link.")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate the environment and exit without calling Battle.net.",
    )
    args = parser.parse_args(argv)
    settings = load_settings(environ)
    secrets = (settings["client_id"], settings["client_secret"])
    if args.check_config:
        if validate_settings(settings):
            print(config_help(), file=sys.stderr)
            return EXIT_CONFIG
        print(
            "Credentials are present. "
            f"Region is EU. Namespace is {NAMESPACE}. Guild is Herberg. "
            "No request was sent."
        )
        return EXIT_OK
    if validate_settings(settings):
        print(config_help(), file=sys.stderr)
        return EXIT_CONFIG
    opener_factory = opener_factory or build_opener
    sleeper = sleeper or time.sleep
    try:
        report, code, message = probe(settings, opener_factory(), sleeper)
    except ApiFailure as failure:
        print(redact(str(failure), secrets), file=sys.stderr)
        return failure.exit_code
    if redact(report, secrets) != report or (message and redact(message, secrets) != message):
        print("Refusing to print a summary that contains credential material.", file=sys.stderr)
        return EXIT_UNEXPECTED
    if message:
        print(message, file=sys.stderr)
    print(report, end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
