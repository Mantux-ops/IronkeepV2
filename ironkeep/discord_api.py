"""Small Discord HTTP helpers used by the website. The gateway bot lives in bot.py."""

import json
import urllib.error
import urllib.parse
import urllib.request

from . import config


class DiscordError(Exception):
    def __init__(self, status, body):
        super().__init__(f"Discord HTTP {status}")
        self.status = status
        self.body = body


def _request(method, url, *, headers, body=None, form=None):
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
    elif body is not None:
        data = json.dumps(body).encode()
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw}
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


def add_role(guild_id, user_id, role_id):
    _api("PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token=config.BOT_TOKEN, bot=True)


def remove_role(guild_id, user_id, role_id):
    _api("DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token=config.BOT_TOKEN, bot=True)


def send_message(channel_id, content):
    return _api("POST", f"/channels/{channel_id}/messages", token=config.BOT_TOKEN, bot=True, body={"content": content})


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
