"""Discord tickets for a guild. The settings live beside the WoW config."""

import logging
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import db, discord_api

log = logging.getLogger("ironkeep.tickets")

MANAGE = 1 << 4
VIEW = 1 << 10
SEND = 1 << 11
HISTORY = 1 << 16
_COPY = {
    "en": {
        "panel_title": "Tickets",
        "panel_description": "Choose a topic, then describe what you need.",
        "placeholder": "Select a topic",
        "modal_label": "Information",
        "modal_placeholder": "Describe what you need.",
        "details_missing": "Write what the ticket is about.",
        "opened": "Your ticket is open: <#{channel_id}>",
        "already": "You already have an open ticket: <#{channel_id}>",
        "disabled": "Tickets are turned off on this server.",
        "unknown_topic": "That topic is no longer available.",
        "welcome_title": "Ticket #{number} — {topic}",
        "welcome_body": "{opener} opened this ticket.\n\n{details}\n\nA staff member can claim it. Close it when the conversation is finished.",
        "claim": "Claim",
        "close": "Close",
        "claimed": "You claimed this ticket.",
        "claimed_line": "{name} claimed this ticket.",
        "claim_denied": "Only staff can claim tickets.",
        "claim_own": "You can't claim your own ticket.",
        "already_claimed": "This ticket is already claimed by {name}.",
        "closed": "Ticket closed. The conversation is saved in Ironkeep.",
        "closed_line": "{name} closed this ticket.",
        "close_denied": "Only staff or the person who opened this ticket can close it.",
        "not_open": "This ticket is not open.",
        "channel_failed": "The ticket channel could not be created. Ironkeep needs permission to manage channels in the ticket category.",
    },
    "nl": {
        "panel_title": "Tickets",
        "panel_description": "Kies een onderwerp en beschrijf daarna waar het om gaat.",
        "placeholder": "Kies een onderwerp",
        "modal_label": "Informatie",
        "modal_placeholder": "Beschrijf waar het om gaat.",
        "details_missing": "Schrijf waar het ticket over gaat.",
        "opened": "Je ticket is geopend: <#{channel_id}>",
        "already": "Je hebt al een open ticket: <#{channel_id}>",
        "disabled": "Tickets staan op deze server uit.",
        "unknown_topic": "Dit onderwerp bestaat niet meer.",
        "welcome_title": "Ticket #{number} — {topic}",
        "welcome_body": "{opener} heeft dit ticket geopend.\n\n{details}\n\nEen stafflid kan het claimen. Sluit het als het gesprek klaar is.",
        "claim": "Claimen",
        "close": "Sluiten",
        "claimed": "Je hebt dit ticket geclaimd.",
        "claimed_line": "{name} heeft dit ticket geclaimd.",
        "claim_denied": "Alleen staff kan tickets claimen.",
        "claim_own": "Je kunt je eigen ticket niet claimen.",
        "already_claimed": "Dit ticket is al geclaimd door {name}.",
        "closed": "Ticket gesloten. Het gesprek staat in Ironkeep.",
        "closed_line": "{name} heeft dit ticket gesloten.",
        "close_denied": "Alleen staff of de opener kan dit ticket sluiten.",
        "not_open": "Dit ticket is niet open.",
        "channel_failed": "Het ticketkanaal kon niet worden aangemaakt. Ironkeep heeft recht nodig om kanalen te beheren in de ticketcategorie.",
    },
}


def _text(language, key, **kwargs):
    table = _COPY.get(language or "", _COPY["en"])
    return table[key].format(**kwargs)


def _clean_name(value):
    name = " ".join(str(value or "").split())
    name = re.sub(r"@(?=everyone\b|here\b)", "@\u200b", name, flags=re.IGNORECASE)
    return name[:80] or "Someone"


def _channel_name(number, display_name):
    folded = unicodedata.normalize("NFKD", display_name)
    ascii_name = folded.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40] or "member"
    return f"ticket-{number:04d}-{slug}"[:100]


def _grantable(guild):
    bits = discord_api.bot_permissions(guild["id"])
    return VIEW | SEND | HISTORY if bits is None else bits


def _apply(bits, row):
    return (bits & ~int(row.get("deny") or 0)) | int(row.get("allow") or 0)


def _can_manage_category(guild, category_id):
    """True when the bot may delete a channel in this category. Guild-wide bits miss a category grant."""
    bits = discord_api.bot_permissions(guild["id"])
    if not bits:
        return False
    if bits & ((1 << 3) | MANAGE):
        return True
    if not category_id:
        return False
    try:
        member = discord_api.bot_member(guild["id"])
        channels = discord_api.guild_channels(guild["id"])
    except discord_api.DiscordError:
        return False
    category = next((item for item in channels if str(item.get("id")) == str(category_id)), None)
    if category is None:
        return False
    bot_id = str(member["user"]["id"]) if member.get("user") else str(discord_api.bot_user()["id"])
    roles = {str(role_id) for role_id in member.get("roles") or []}
    perms = bits
    role_allow = role_deny = 0
    member_row = None
    for row in category.get("permission_overwrites") or []:
        row_id = str(row.get("id"))
        kind = int(row.get("type") or 0)
        if row_id == str(guild["id"]) and kind == 0:
            perms = _apply(perms, row)
        elif kind == 0 and row_id in roles:
            role_allow |= int(row.get("allow") or 0)
            role_deny |= int(row.get("deny") or 0)
        elif kind == 1 and row_id == bot_id:
            member_row = row
    perms = (perms & ~role_deny) | role_allow
    if member_row:
        perms = _apply(perms, member_row)
    return bool(perms & MANAGE)


def _utc():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _clean_body(value, limit=2000):
    text = str(value or "").replace("\r\n", "\n").strip()
    text = re.sub(r"@(?=everyone\b|here\b)", "@\u200b", text, flags=re.IGNORECASE)
    return text[:limit]


def _labels(topics):
    return [topic["label"] for topic in topics or []]


def _message_for(topics, label):
    for topic in topics or []:
        if topic["label"] == label:
            return topic["message"]
    return ""


def _claim_roles(setup, topic):
    """Roles that may claim this topic. An empty topic list uses the staff roles."""
    for item in setup["topics"]:
        if item["label"] == topic and item.get("roles"):
            return item["roles"]
    return setup["staff_roles"]


def _topic_from_value(topics, value):
    labels = _labels(topics)
    if str(value).isdigit() and int(value) < len(labels):
        return labels[int(value)], int(value)
    return None, None


def _topic_content(guild, setup, row, channel_id):
    """The topic's own message, with Discord mentions filled in. Falls back to mentioning the opener."""
    message = _message_for(setup["topics"], row["topic"]).strip()
    mention = f"<@{row['opener_id']}>"
    if not message:
        return mention
    staff = " ".join(f"<@&{role_id}>" for role_id in _claim_roles(setup, row["topic"]))
    filled = discord_api.fill(message, {
        "user": mention,
        "username": row["opener_name"],
        "topic": row["topic"],
        "server": _clean_name(guild.get("name")),
        "channel": f"<#{channel_id}>" if channel_id else "",
        "staff": staff,
    })
    return (filled or mention)[:2000]


def panel_payload(language, topics):
    options = []
    for index, label in enumerate(_labels(topics)[:25]):
        options.append({"label": label[:100], "value": str(index)})
    return {
        "embeds": [{
            "title": _text(language, "panel_title"),
            "description": _text(language, "panel_description"),
            "color": 0x14B8A6,
        }],
        "components": [{
            "type": 1,
            "components": [{
                "type": 3,
                "custom_id": "ikt:open",
                "placeholder": _text(language, "placeholder"),
                "min_values": 1,
                "max_values": 1,
                "options": options,
            }],
        }],
    }


def _modal(language, topic, index):
    return {
        "custom_id": f"ikt:form:{index}",
        "title": topic[:45],
        "components": [{
            "type": 1,
            "components": [{
                "type": 4,
                "custom_id": "details",
                "label": _text(language, "modal_label"),
                "style": 2,
                "min_length": 1,
                "max_length": 1000,
                "required": True,
                "placeholder": _text(language, "modal_placeholder"),
            }],
        }],
    }


def _welcome_payload(language, row, claimed_by=None, content=None):
    body = _text(
        language,
        "welcome_body",
        opener=row["opener_name"],
        details=_clean_body(row["details"], 1000) or "—",
    )
    if claimed_by:
        body = f"{body}\n\n{_text(language, 'claimed_line', name=claimed_by)}"
    return {
        "content": content if content is not None else f"<@{row['opener_id']}>",
        "embeds": [{
            "title": _text(language, "welcome_title", number=f"{int(row['number']):04d}", topic=row["topic"]),
            "description": body,
            "color": 0x14B8A6,
        }],
        "components": [{
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 1,
                    "label": _text(language, "claim"),
                    "custom_id": f"ikt:claim:{row['id']}",
                    "disabled": bool(claimed_by),
                },
                {
                    "type": 2,
                    "style": 4,
                    "label": _text(language, "close"),
                    "custom_id": f"ikt:close:{row['id']}",
                },
            ],
        }],
    }


def _remove_panel(channel_id, message_id):
    if not channel_id or not message_id:
        return
    try:
        discord_api.delete_message(channel_id, message_id)
    except discord_api.DiscordError as error:
        if getattr(error, "status", None) != 404:
            raise


def publish_panel(previous, desired):
    """Move the menu to the saved channel, or remove it when tickets are off.

    Returns the config to store. The message id points at the one menu that is left.
    """
    desired = dict(desired)
    old_channel = previous.get("panel_channel_id")
    old_message = previous.get("panel_message_id")
    if not desired.get("enabled"):
        _remove_panel(old_channel, old_message)
        desired["panel_message_id"] = None
        return desired
    if not desired.get("panel_channel_id") or not desired.get("topics") or not desired.get("staff_roles"):
        return desired
    payload = panel_payload(desired["language"], desired["topics"])
    if old_message and old_channel == desired.get("panel_channel_id"):
        try:
            discord_api.edit_message(old_channel, old_message, payload)
            desired["panel_message_id"] = str(old_message)
            return desired
        except discord_api.DiscordError as error:
            if getattr(error, "status", None) != 404:
                raise
    else:
        _remove_panel(old_channel, old_message)
    posted = discord_api.send_payload(desired["panel_channel_id"], payload)
    desired["panel_message_id"] = str(posted["id"])
    return desired


def _overwrites(guild, setup, opener_id, topic):
    grant = _grantable(guild)
    talk = (VIEW | SEND | HISTORY) & grant
    bot_allow = talk
    if _can_manage_category(guild, setup.get("category_id")):
        bot_allow |= MANAGE
    rows = [{
        "id": str(guild["id"]),
        "type": 0,
        "allow": "0",
        "deny": str(VIEW & grant),
    }, {
        "id": str(opener_id),
        "type": 1,
        "allow": str(talk),
        "deny": "0",
    }, {
        "id": str(discord_api.bot_user()["id"]),
        "type": 1,
        "allow": str(bot_allow),
        "deny": "0",
    }]
    for role_id in _claim_roles(setup, topic):
        if str(role_id) == str(guild["id"]):
            continue
        rows.append({"id": str(role_id), "type": 0, "allow": str(talk), "deny": "0"})
    return rows


def _reset_panel(guild):
    setup = db.ticket_settings(guild["settings"])
    if not setup.get("panel_message_id") or not setup.get("panel_channel_id") or not setup["topics"]:
        return
    try:
        discord_api.edit_message(
            setup["panel_channel_id"],
            setup["panel_message_id"],
            panel_payload(setup["language"], setup["topics"]),
        )
    except discord_api.DiscordError:
        log.warning("Could not reset the ticket menu")


def _active(conn, guild_id, opener_id):
    return conn.execute(
        "SELECT * FROM tickets WHERE guild_id = ? AND opener_id = ? AND status IN ('open', 'claimed')",
        (str(guild_id), str(opener_id)),
    ).fetchone()


def _next_number(conn, guild_id):
    row = conn.execute("SELECT MAX(number) AS n FROM tickets WHERE guild_id = ?", (str(guild_id),)).fetchone()
    return int(row["n"] or 0) + 1


def _reply(interaction_id, token, content):
    discord_api.interaction_callback(
        interaction_id,
        token,
        kind=4,
        data={"content": content, "flags": 64},
    )


def _prompt(guild, user_id, value, interaction_id, token):
    """Ask for the ticket text. A modal has to be the first reply, so this does not defer."""
    setup = db.ticket_settings(guild["settings"])
    language = setup["language"]
    topic, index = _topic_from_value(setup["topics"], value)
    if not setup["enabled"]:
        _reply(interaction_id, token, _text(language, "disabled"))
        _reset_panel(guild)
        return
    if topic is None:
        _reply(interaction_id, token, _text(language, "unknown_topic"))
        _reset_panel(guild)
        return
    with db._LOCK:
        conn = db.connect()
        existing = _active(conn, guild["id"], user_id)
        conn.close()
    if existing:
        _reply(interaction_id, token, _text(language, "already", channel_id=existing["channel_id"]))
        _reset_panel(guild)
        return
    discord_api.interaction_callback(
        interaction_id,
        token,
        kind=9,
        data=_modal(language, topic, index),
    )
    _reset_panel(guild)


def _open(guild, user_id, name, topic, details, username=""):
    setup = db.ticket_settings(guild["settings"])
    language = setup["language"]
    details = _clean_body(details, 1000)
    if not setup["enabled"]:
        return _text(language, "disabled")
    if topic not in _labels(setup["topics"]):
        return _text(language, "unknown_topic")
    if not details:
        return _text(language, "details_missing")
    with db._LOCK:
        conn = db.connect()
        existing = _active(conn, guild["id"], user_id)
        number = None if existing else _next_number(conn, guild["id"])
        conn.close()
    if existing:
        return _text(language, "already", channel_id=existing["channel_id"])
    try:
        created = discord_api.create_text_channel(
            guild["id"],
            _channel_name(number, name),
            setup.get("category_id"),
            _overwrites(guild, setup, user_id, topic),
        )
    except discord_api.DiscordError:
        log.exception("Could not create a ticket channel")
        return _text(language, "channel_failed")
    ticket_id = uuid.uuid4().hex
    opener = _clean_name(name)
    handle = " ".join(str(username or "").lstrip("@").split())[:80]
    stamp = _utc()
    with db._LOCK:
        conn = db.connect()
        try:
            conn.execute(
                """
                INSERT INTO tickets (
                    id, guild_id, number, topic, opener_id, opener_name, opener_username, status,
                    channel_id, welcome_id, claimed_by_id, claimed_by_name, opened_at, closed_at, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, NULL, NULL, NULL, ?, NULL, ?)
                """,
                (ticket_id, str(guild["id"]), number, topic, str(user_id), opener, handle, str(created["id"]), stamp, details),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            existing = _active(conn, guild["id"], user_id)
            conn.close()
            try:
                discord_api.delete_channel(created["id"])
            except discord_api.DiscordError:
                pass
            channel_id = existing["channel_id"] if existing and existing["channel_id"] else setup["panel_channel_id"]
            return _text(language, "already", channel_id=channel_id or "0")
        conn.close()
    row = {
        "id": ticket_id,
        "number": number,
        "topic": topic,
        "opener_id": str(user_id),
        "opener_name": opener,
        "details": details,
    }
    opening = _topic_content(guild, setup, row, created["id"])
    try:
        welcome = discord_api.send_payload(created["id"], _welcome_payload(language, row, content=opening))
    except discord_api.DiscordError:
        log.exception("Could not post the ticket welcome")
        welcome = None
    if welcome and welcome.get("id"):
        with db._LOCK:
            conn = db.connect()
            conn.execute("UPDATE tickets SET welcome_id = ? WHERE id = ?", (str(welcome["id"]), ticket_id))
            conn.commit()
            conn.close()
    if opening != f"<@{user_id}>":
        _add_message(ticket_id, (welcome or {}).get("id"), None, "Ironkeep", opening, "system", stamp)
    _add_message(ticket_id, None, user_id, opener, details, "member", stamp)
    return _text(language, "opened", channel_id=created["id"])


def _staff(setup, role_ids, topic):
    wanted = {str(role_id) for role_id in _claim_roles(setup, topic)}
    return any(str(role_id) in wanted for role_id in role_ids or [])


def _load(guild_id, ticket_id):
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM tickets WHERE id = ? AND guild_id = ?",
        (str(ticket_id), str(guild_id)),
    ).fetchone()
    conn.close()
    return row


def _claim(guild, user_id, name, role_ids, ticket_id, from_web=False):
    setup = db.ticket_settings(guild["settings"])
    language = setup["language"]
    row = _load(guild["id"], ticket_id)
    if row is None or row["status"] not in ("open", "claimed"):
        return _text(language, "not_open")
    if str(row["opener_id"]) == str(user_id):
        return _text(language, "claim_own")
    if not from_web and not _staff(setup, role_ids, row["topic"]):
        return _text(language, "claim_denied")
    if row["status"] == "claimed":
        if str(row["claimed_by_id"] or "") == str(user_id):
            return _text(language, "claimed")
        return _text(language, "already_claimed", name=row["claimed_by_name"] or "someone")
    claimer = _clean_name(name)
    with db._LOCK:
        conn = db.connect()
        conn.execute(
            "UPDATE tickets SET status = 'claimed', claimed_by_id = ?, claimed_by_name = ? WHERE id = ? AND status = 'open'",
            (str(user_id), claimer, row["id"]),
        )
        conn.commit()
        conn.close()
    fresh = dict(row)
    if row["channel_id"] and row["welcome_id"]:
        try:
            discord_api.edit_message(
                row["channel_id"],
                row["welcome_id"],
                _welcome_payload(
                    language,
                    fresh,
                    claimer,
                    content=_topic_content(guild, setup, fresh, row["channel_id"]),
                ),
            )
        except discord_api.DiscordError:
            log.warning("Could not update the claimed ticket")
    if row["channel_id"]:
        posted = None
        try:
            posted = discord_api.send_message(row["channel_id"], _text(language, "claimed_line", name=claimer))
        except discord_api.DiscordError:
            posted = None
        _add_message(
            row["id"],
            (posted or {}).get("id"),
            user_id,
            claimer,
            _text(language, "claimed_line", name=claimer),
            "system",
            _utc(),
        )
    return _text(language, "claimed")


def _close(guild, user_id, role_ids, ticket_id, name="Someone", from_web=False):
    setup = db.ticket_settings(guild["settings"])
    language = setup["language"]
    row = _load(guild["id"], ticket_id)
    if row is None or row["status"] not in ("open", "claimed"):
        return _text(language, "not_open")
    if not from_web and str(row["opener_id"]) != str(user_id) and not _staff(setup, role_ids, row["topic"]):
        return _text(language, "close_denied")
    sync_ticket(guild, row)
    stamp = _utc()
    closer = _clean_name(name)
    with db._LOCK:
        conn = db.connect()
        conn.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ? WHERE id = ?",
            (stamp, row["id"]),
        )
        conn.commit()
        conn.close()
    _add_message(row["id"], None, user_id, closer, _text(language, "closed_line", name=closer), "system", stamp)
    if row["channel_id"]:
        try:
            discord_api.delete_channel(row["channel_id"])
        except discord_api.DiscordError as error:
            if getattr(error, "status", None) != 404:
                log.warning("Could not delete ticket channel %s: %s", row["channel_id"], error)
    return _text(language, "closed")


def answer(guild_id, user_id, name, role_ids, custom_id, values, interaction_id, token, fields=None, username=""):
    """Reply to a ticket menu, the information form, or a button."""
    parts = str(custom_id or "").split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    if action == "open":
        guild = db.guild_by_id(guild_id)
        if guild is None:
            _reply(interaction_id, token, _text("en", "disabled"))
            return
        try:
            _prompt(guild, user_id, values[0] if values else "", interaction_id, token)
        except discord_api.DiscordError:
            log.exception("Could not open the ticket form")
        return
    try:
        discord_api.interaction_callback(interaction_id, token, kind=5, data={"flags": 64})
    except discord_api.DiscordError:
        return
    try:
        content = _answer(guild_id, user_id, name, role_ids, parts, fields or {}, username)
    except Exception:
        log.exception("Ticket action failed")
        content = "Something went wrong. Try again in a moment."
    try:
        discord_api.edit_original_interaction(token, {"content": content})
    except discord_api.DiscordError:
        log.exception("Ticket reply failed")


def _answer(guild_id, user_id, name, role_ids, parts, fields, username=""):
    if len(parts) < 2 or parts[0] != "ikt" or parts[1] not in ("form", "claim", "close"):
        return "Something went wrong. Try again in a moment."
    guild = db.guild_by_id(guild_id)
    if guild is None:
        return _text("en", "disabled")
    action = parts[1]
    target = parts[2] if len(parts) > 2 else ""
    if action == "form":
        setup = db.ticket_settings(guild["settings"])
        topic, _index = _topic_from_value(setup["topics"], target)
        try:
            if topic is None:
                return _text(setup["language"], "unknown_topic")
            return _open(guild, user_id, name, topic, fields.get("details") or "", username)
        finally:
            _reset_panel(guild)
    if action == "claim":
        return _claim(guild, user_id, name, role_ids, target)
    return _close(guild, user_id, role_ids, target, name)


def _add_message(ticket_id, discord_id, author_id, author_name, body, kind, created_at):
    body = _clean_body(body)
    if not body:
        return
    with db._LOCK:
        conn = db.connect()
        if discord_id:
            found = conn.execute(
                "SELECT id FROM ticket_messages WHERE discord_id = ?",
                (str(discord_id),),
            ).fetchone()
            if found:
                conn.close()
                return
        conn.execute(
            """
            INSERT INTO ticket_messages (
                ticket_id, discord_id, author_id, author_name, body, kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(ticket_id),
                str(discord_id) if discord_id else None,
                str(author_id) if author_id else None,
                _clean_name(author_name),
                body,
                kind,
                created_at or _utc(),
            ),
        )
        conn.commit()
        conn.close()


def when(value, settings):
    text = str(value or "")
    if not text:
        return ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if "T" in text and ("+" in text[10:] or text.count("-") > 2):
            moment = datetime.fromisoformat(text)
        else:
            moment = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return text[:16].replace("T", " ")
    zone = (settings or {}).get("timezone") or "Europe/Amsterdam"
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except Exception:
        local = moment
    return local.strftime("%d %b, %H:%M").lstrip("0")


def load(guild_id, ticket_id):
    row = _load(guild_id, ticket_id)
    return dict(row) if row else None


def matches_name(ticket, query):
    """A search hits the Discord username and the name shown on the server."""
    needle = " ".join(str(query or "").split()).casefold().lstrip("@")
    if not needle:
        return True
    haystack = " ".join([
        str(ticket.get("opener_name") or ""),
        str(ticket.get("opener_username") or ""),
    ]).casefold()
    return needle in haystack


def list_for_guild(guild_id):
    conn = db.connect()
    rows = conn.execute(
        """
        SELECT * FROM tickets WHERE guild_id = ?
        ORDER BY opened_at DESC
        """,
        (str(guild_id),),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def transcript(ticket_id, settings):
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY created_at, id",
        (str(ticket_id),),
    ).fetchall()
    conn.close()
    messages = []
    for row in rows:
        item = dict(row)
        item["when"] = when(item["created_at"], settings)
        messages.append(item)
    return messages


def sync_ticket(guild, ticket):
    """Copy human Discord messages into the transcript. Bot cards are stored separately."""
    channel_id = ticket["channel_id"] if ticket else None
    if not channel_id or ticket["status"] == "closed":
        return True
    try:
        bot_id = str(discord_api.bot_user()["id"])
        welcome_id = str(ticket["welcome_id"] or "")
        collected = []
        before = None
        for _ in range(5):
            batch = discord_api.channel_messages(channel_id, before)
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < 100:
                break
            before = batch[-1]["id"]
    except discord_api.DiscordError as error:
        if getattr(error, "status", None) == 404:
            return True
        log.warning("Could not read ticket %s", ticket["id"])
        return False
    collected.reverse()
    for message in collected:
        discord_id = str(message.get("id") or "")
        if not discord_id or discord_id == welcome_id:
            continue
        author = message.get("author") or {}
        if author.get("bot") or str(author.get("id") or "") == bot_id:
            continue
        body = message.get("content") or ""
        if not str(body).strip():
            continue
        author_id = str(author.get("id") or "")
        kind = "member" if author_id == str(ticket["opener_id"]) else "staff"
        name = author.get("global_name") or author.get("username") or "Member"
        _add_message(ticket["id"], discord_id, author_id, name, body, kind, message.get("timestamp") or _utc())
    return True


def post_reply(guild, ticket_id, officer_name, text):
    ticket = _load(guild["id"], ticket_id)
    if ticket is None or ticket["status"] not in ("open", "claimed"):
        return "This ticket is not open."
    if not ticket["channel_id"]:
        return "This ticket has no Discord channel."
    body = _clean_body(text)
    if not body:
        return "Write a reply first."
    sync_ticket(guild, ticket)
    try:
        posted = discord_api.send_message(
            ticket["channel_id"],
            f"**{_clean_name(officer_name)}:** {body}"[:2000],
        )
    except discord_api.DiscordError:
        log.exception("Could not post a ticket reply")
        return "Discord could not post the reply."
    _add_message(ticket["id"], (posted or {}).get("id"), None, officer_name, body, "staff", _utc())
    return ""


def claim_from_web(guild, ticket_id, officer_id, officer_name):
    result = _claim(guild, officer_id, officer_name, [], ticket_id, from_web=True)
    setup = db.ticket_settings(guild["settings"])
    if result == _text(setup["language"], "claimed"):
        return ""
    return result


def close_from_web(guild, ticket_id, officer_id, officer_name):
    result = _close(guild, officer_id, [], ticket_id, officer_name, from_web=True)
    setup = db.ticket_settings(guild["settings"])
    if result == _text(setup["language"], "closed"):
        return ""
    return result
