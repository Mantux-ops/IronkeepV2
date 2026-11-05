"""Small Discord HTTP helpers used by the website. The gateway bot lives in bot.py."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config


class DiscordError(Exception):
    def __init__(self, status, body):
        super().__init__(f"Discord HTTP {status}")
        self.status = status
        self.body = body


def _multipart(payload, files):
    import uuid

    boundary = f"ironkeep{uuid.uuid4().hex}"
    chunks = []

    def part(lines, content):
        chunks.append(f"--{boundary}\r\n".encode())
        for line in lines:
            chunks.append(f"{line}\r\n".encode())
        chunks.append(b"\r\n")
        chunks.append(content)
        chunks.append(b"\r\n")

    part(
        ['Content-Disposition: form-data; name="payload_json"', "Content-Type: application/json"],
        json.dumps(payload).encode(),
    )
    for index, (filename, content) in enumerate(files):
        part(
            [
                f'Content-Disposition: form-data; name="files[{index}]"; filename="{filename}"',
                "Content-Type: image/jpeg",
            ],
            content,
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _pause_for_rate_limit(error, parsed):
    """One pause after HTTP 429. Discord's retry_after is seconds."""
    retry_after = parsed.get("retry_after") if isinstance(parsed, dict) else None
    if retry_after is None and getattr(error, "headers", None) is not None:
        retry_after = error.headers.get("Retry-After")
    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        seconds = 0.2
    return min(max(seconds, 0.2), 3)


def _request(method, url, *, headers, body=None, form=None, raw=None, content_type=None):
    data = None
    if raw is not None:
        data = raw
        headers = {**headers, "Content-Type": content_type}
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
    elif body is not None:
        data = json.dumps(body).encode()
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read().decode()
                return response.status, json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            payload = error.read().decode()
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            if error.code == 429 and attempt == 0:
                time.sleep(_pause_for_rate_limit(error, parsed))
                continue
            raise DiscordError(error.code, parsed) from error


def _api(method, path, *, token, bot=False, body=None):
    kind = "Bot" if bot else "Bearer"
    status, payload = _request(
        method,
        "https://discord.com/api/v10" + path,
        headers={"Authorization": f"{kind} {token}", "User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)"},
        body=body,
    )
    return payload


def exchange_code(code):
    status, payload = _request(
        "POST",
        "https://discord.com/api/v10/oauth2/token",
        headers={"User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)"},
        form={
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri(),
        },
    )
    return payload


def refresh_access_token(refresh_token):
    status, payload = _request(
        "POST",
        "https://discord.com/api/v10/oauth2/token",
        headers={"User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)"},
        form={
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    return payload


def identify(access_token):
    return _api("GET", "/users/@me", token=access_token)


def guild_member(access_token, guild_id):
    return _api("GET", f"/users/@me/guilds/{guild_id}/member", token=access_token)


def member_as_bot(guild_id, user_id):
    """Current guild member, using the bot token. The Companion does not keep the user's Discord token."""
    return _api("GET", f"/guilds/{guild_id}/members/{user_id}", token=config.BOT_TOKEN, bot=True)


def list_roles(guild_id):
    return _api("GET", f"/guilds/{guild_id}/roles", token=config.BOT_TOKEN, bot=True)


def role_records(payload, guild_id):
    """The role list the setup page shows. Same shape the bot stores."""
    records = []
    for role in payload or []:
        tags = role.get("tags") or {}
        everyone = str(role.get("id")) == str(guild_id)
        color = int(role.get("color") or 0)
        records.append(
            {
                "id": str(role.get("id")),
                "name": "@everyone" if everyone else (role.get("name") or "Role"),
                "color": "#99aab5" if color == 0 else f"#{color:06x}",
                "position": int(role.get("position") or 0),
                "everyone": everyone,
                "managed": bool(role.get("managed")),
                "bot": str(tags.get("bot_id") or "") == str(config.CLIENT_ID),
            }
        )
    return records


def add_role(guild_id, user_id, role_id):
    _api("PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token=config.BOT_TOKEN, bot=True)


def remove_role(guild_id, user_id, role_id):
    _api("DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token=config.BOT_TOKEN, bot=True)


def send_message(channel_id, content):
    return _api("POST", f"/channels/{channel_id}/messages", token=config.BOT_TOKEN, bot=True, body={"content": content})


def channel_messages(channel_id, before=None):
    path = f"/channels/{channel_id}/messages?limit=100"
    if before:
        path += f"&before={before}"
    return _api("GET", path, token=config.BOT_TOKEN, bot=True)


def _with_files(method, path, payload, files):
    if not files:
        return _api(method, path, token=config.BOT_TOKEN, bot=True, body=payload)
    raw, content_type = _multipart(payload, files)
    _status, body = _request(
        method,
        "https://discord.com/api/v10" + path,
        headers={
            "Authorization": f"Bot {config.BOT_TOKEN}",
            "User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)",
        },
        raw=raw,
        content_type=content_type,
    )
    return body


def send_payload(channel_id, payload, files=None):
    return _with_files("POST", f"/channels/{channel_id}/messages", payload, files)


def matching_attachment_ids(attachments, files):
    """Ids of files already on the message. A different size means the picture changed."""
    by_name = {}
    for attachment in attachments or []:
        name = attachment.get("filename")
        attachment_id = attachment.get("id")
        if not name or not attachment_id or name in by_name:
            continue
        by_name[name] = attachment
    kept = []
    for filename, content in files or []:
        found = by_name.get(filename)
        if found is None:
            return None
        size = found.get("size")
        if size is not None and int(size) != len(content):
            return None
        kept.append({"id": str(found["id"])})
    return kept


def edit_message(channel_id, message_id, payload, files=None):
    if files:
        try:
            current = _api(
                "GET",
                f"/channels/{channel_id}/messages/{message_id}",
                token=config.BOT_TOKEN,
                bot=True,
            )
            kept = matching_attachment_ids((current or {}).get("attachments"), files)
        except (DiscordError, OSError):
            kept = None
        if kept is not None:
            body = dict(payload)
            body["attachments"] = kept
            return _api(
                "PATCH",
                f"/channels/{channel_id}/messages/{message_id}",
                token=config.BOT_TOKEN,
                bot=True,
                body=body,
            )
    return _with_files("PATCH", f"/channels/{channel_id}/messages/{message_id}", payload, files)


def message_with_text(messages, text):
    for message in messages or []:
        if (message.get("content") or "") == text and message.get("id"):
            return str(message["id"])
    return None


def replace_message_text(channel_id, old, new):
    """Edit the first recent message that still has the old text."""
    messages = _api(
        "GET",
        f"/channels/{channel_id}/messages?limit=50",
        token=config.BOT_TOKEN,
        bot=True,
    )
    message_id = message_with_text(messages, old)
    if not message_id:
        return False
    edit_message(channel_id, message_id, {"content": new, "allowed_mentions": {"parse": []}})
    return True


def delete_message(channel_id, message_id):
    _api(
        "DELETE",
        f"/channels/{channel_id}/messages/{message_id}",
        token=config.BOT_TOKEN,
        bot=True,
    )


def replace_guild_commands(guild_id, commands):
    """Replace this server's slash commands. An empty list removes them."""
    if not config.CLIENT_ID:
        raise DiscordError(0, {"message": "missing application id"})
    _api(
        "PUT",
        f"/applications/{config.CLIENT_ID}/guilds/{guild_id}/commands",
        token=config.BOT_TOKEN,
        bot=True,
        body=commands,
    )


def interaction_callback(interaction_id, token, *, kind, data=None):
    body = {"type": kind}
    if data is not None:
        body["data"] = data
    _request(
        "POST",
        f"https://discord.com/api/v10/interactions/{interaction_id}/{token}/callback",
        headers={"User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)"},
        body=body,
    )


def edit_original_interaction(token, payload):
    """Edit the ephemeral signup message from an earlier button click."""
    application_id = config.CLIENT_ID
    if not application_id:
        raise DiscordError(0, {"message": "missing application id"})
    _request(
        "PATCH",
        f"https://discord.com/api/v10/webhooks/{application_id}/{token}/messages/@original",
        headers={"User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)"},
        body=payload,
    )


def create_private_thread(channel_id, message_id, name):
    """Private thread hanging off a message. Type 12 is a private thread; invitable stays off."""
    return _api(
        "POST",
        f"/channels/{channel_id}/messages/{message_id}/threads",
        token=config.BOT_TOKEN,
        bot=True,
        body={
            "name": (name or "Welcome")[:100],
            "type": 12,
            "auto_archive_duration": 4320,
            "invitable": False,
        },
    )


def create_public_thread(channel_id, message_id, name):
    """Public thread on a channel message. A short archive window is the fallback when the server is not boosted."""
    label = (name or "Raid").replace("\n", " ").strip() or "Raid"
    last = None
    for minutes in (10080, 4320, 1440):
        try:
            return _api(
                "POST",
                f"/channels/{channel_id}/messages/{message_id}/threads",
                token=config.BOT_TOKEN,
                bot=True,
                body={"name": label[:100], "auto_archive_duration": minutes},
            )
        except DiscordError as error:
            last = error
            detail = json.dumps(error.body or {})
            if error.status != 400 or "auto_archive_duration" not in detail:
                raise
    raise last


def thread_notice_id(messages, name):
    """The channel line Discord adds when a thread starts. Type 18, content is the thread name."""
    label = (name or "").replace("\n", " ").strip()[:100]
    if not label:
        return None
    for message in messages or []:
        if message.get("type") != 18 or (message.get("content") or "") != label:
            continue
        notice_id = str(message.get("id") or "")
        if notice_id:
            return notice_id
    return None


def delete_thread_notice(channel_id, name):
    """Remove Discord's started-a-thread line. The thread on the raid message stays."""
    messages = _api(
        "GET",
        f"/channels/{channel_id}/messages?limit=25",
        token=config.BOT_TOKEN,
        bot=True,
    )
    notice_id = thread_notice_id(messages, name)
    if not notice_id:
        return False
    delete_message(channel_id, notice_id)
    return True


def archive_thread(thread_id):
    """Lock the thread and archive it, so a new message does not open it again."""
    return _api(
        "PATCH",
        f"/channels/{thread_id}",
        token=config.BOT_TOKEN,
        bot=True,
        body={"locked": True, "archived": True},
    )


def bot_user():
    return _api("GET", "/users/@me", token=config.BOT_TOKEN, bot=True)


def bot_member(guild_id):
    return _api(
        "GET",
        f"/guilds/{guild_id}/members/{bot_user()['id']}",
        token=config.BOT_TOKEN,
        bot=True,
    )


ADMINISTRATOR = 1 << 3
_permission_cache = {}
_bot_id = None


def bot_permissions(guild_id):
    """The bot's server-wide permission bits, cached for five minutes. None when Discord cannot be read."""
    global _bot_id
    guild_id = str(guild_id)
    now = time.monotonic()
    cached = _permission_cache.get(guild_id)
    if cached and now - cached[0] < 300:
        return cached[1]
    try:
        if _bot_id is None:
            _bot_id = str(bot_user()["id"])
        member = _api("GET", f"/guilds/{guild_id}/members/{_bot_id}", token=config.BOT_TOKEN, bot=True)
        roles = {str(role["id"]): int(role.get("permissions") or 0) for role in list_roles(guild_id)}
        bits = roles.get(guild_id, 0)
        for role_id in member.get("roles") or []:
            bits |= roles.get(str(role_id), 0)
        if bits & ADMINISTRATOR:
            bits = ~0
    except DiscordError:
        bits = None
    _permission_cache[guild_id] = (now, bits)
    return bits


def guild_channels(guild_id):
    return _api("GET", f"/guilds/{guild_id}/channels", token=config.BOT_TOKEN, bot=True)


def get_channel(channel_id):
    return _api("GET", f"/channels/{channel_id}", token=config.BOT_TOKEN, bot=True)


def edit_channel(channel_id, body):
    return _api("PATCH", f"/channels/{channel_id}", token=config.BOT_TOKEN, bot=True, body=body)


def create_text_channel(guild_id, name, category_id=None, overwrites=None):
    body = {"name": name[:100], "type": 0}
    if category_id:
        body["parent_id"] = str(category_id)
    if overwrites is not None:
        body["permission_overwrites"] = overwrites
    return _api(
        "POST",
        f"/guilds/{guild_id}/channels",
        token=config.BOT_TOKEN,
        bot=True,
        body=body,
    )


def create_voice_channel(guild_id, category_id, name, user_limit=None, overwrites=None, position=None):
    body = {"name": name[:100], "type": 2, "parent_id": str(category_id)}
    if user_limit is not None:
        body["user_limit"] = int(user_limit)
    if overwrites is not None:
        body["permission_overwrites"] = overwrites
    if position is not None:
        body["position"] = int(position)
    return _api(
        "POST",
        f"/guilds/{guild_id}/channels",
        token=config.BOT_TOKEN,
        bot=True,
        body=body,
    )


def move_member(guild_id, user_id, channel_id):
    """Move someone into a voice channel. No channel disconnects them."""
    return _api(
        "PATCH",
        f"/guilds/{guild_id}/members/{user_id}",
        token=config.BOT_TOKEN,
        bot=True,
        body={"channel_id": channel_id},
    )


def delete_channel(channel_id):
    _api("DELETE", f"/channels/{channel_id}", token=config.BOT_TOKEN, bot=True)


def add_thread_member(thread_id, user_id):
    _api("PUT", f"/channels/{thread_id}/thread-members/{user_id}", token=config.BOT_TOKEN, bot=True)


def leave_guild(guild_id):
    _api("DELETE", f"/users/@me/guilds/{guild_id}", token=config.BOT_TOKEN, bot=True)


def send_dm(user_id, content):
    channel = _api("POST", "/users/@me/channels", token=config.BOT_TOKEN, bot=True, body={"recipient_id": user_id})
    send_message(channel["id"], content)


def fill(template, values):
    import re

    def replace(match):
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)

    return re.sub(r"\{(\w+)\}", replace, template or "")
