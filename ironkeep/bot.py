"""Discord gateway bot. Stays quiet until a guild is approved and its setup is complete.

Run with: python -m ironkeep.bot
Requires DISCORD_BOT_TOKEN and the Server Members intent in the Discord developer portal.
"""

import asyncio
import logging
from datetime import date, timedelta

import discord

from . import config, db
from .discord_api import fill

log = logging.getLogger("ironkeep.bot")


def _content_ids(member, settings):
    wanted = set(settings.get("content_roles") or [])
    return [role_id for role_id in wanted if role_id in {str(role.id) for role in member.roles}]


def _member_record(member):
    joined = member.joined_at.isoformat() if member.joined_at else None
    return {
        "user_id": str(member.id),
        "name": member.display_name,
        "username": member.name,
        "nick": member.nick,
        "role_ids": [str(role.id) for role in member.roles if not role.is_default()],
        "joined_at": joined,
    }


def _observed(trial):
    return any(item.get("type") == "observation" for item in trial.get("timeline") or [])


def consider_member(guild_row, member, *, known_new, before_ids=None):
    if member.bot:
        return
    settings = guild_row["settings"]
    trial_ids = db.active_trial_role_ids(settings)
    full_ids = set(db.member_role_ids(settings))
    if not trial_ids:
        return
    member_ids = {str(role.id) for role in member.roles}
    has_trial = bool(member_ids & trial_ids)
    is_full_member = bool(member_ids & full_ids) and not has_trial
    before_ids = {str(role_id) for role_id in (before_ids or set())}
    just_added = known_new and has_trial and not any(role_id in before_ids for role_id in trial_ids)
    content = _content_ids(member, settings)
    existing = db.open_trial(guild_row["id"], member.id)
    nickname = member.nick if settings.get("albion", {}).get("name_source") != "manual" else None

    if is_full_member:
        if existing and not _observed(existing):
            db.delete_trial(existing["id"])
        return

    if has_trial and existing is None:
        start = db.guild_today(settings).isoformat() if just_added else None
        text = "A trial role was given" if just_added else "Already had a trial role when Ironkeep started following this server. Start date unknown."
        db.create_trial(
            guild_row,
            member.id,
            member.display_name,
            member.name,
            start=start,
            content_roles=content,
            albion_name=nickname,
            text=text,
        )
        if just_added:
            _send_template(guild_row, "trial_started", member, start)
        return

    if existing is None:
        return
    lost = bool(existing["content_roles"]) and not content
    note = None
    if content != existing["content_roles"]:
        names = ", ".join(content) if content else "none"
        note = "Content roles updated"
        if lost and existing["ping_sent_at"]:
            note = "Content role removed after the reminder"
    if note or lost != existing["lost_content_role"]:
        db.update_trial_roles(existing["id"], content, lost or existing["lost_content_role"], note, settings)


def welcome_thread_name(display_name):
    raw = (display_name or "").replace("\n", " ").strip()
    return raw[:100] or "Welcome"


def welcome_thread_url(guild_id, thread_id):
    return f"https://discord.com/channels/{guild_id}/{thread_id}"


def _send_template(guild_row, key, member, start=None):
    settings = guild_row["settings"]
    message = (settings.get("messages") or {}).get(key) or {}
    if not message.get("enabled") or not message.get("channel"):
        return None
    if not guild_row["approval"] == "approved" or not guild_row["setup_complete"]:
        return None
    today = db.guild_today(settings)
    length = int(settings.get("trial_days") or 14)
    start_date = start or today.isoformat()
    end = None
    if start_date:
        from datetime import date

        end = date.fromisoformat(start_date) + timedelta(days=length)
    values = {
        "member": f"<@{member.id}>",
        "guild": guild_row["name"],
        "days": length,
        "day": settings.get("reminder_day") or 7,
        "start_date": db.human_date(start_date),
        "end_date": db.human_date(end) if end else "",
    }
    try:
        from .discord_api import send_message

        return send_message(message["channel"], fill(message.get("text"), values)[:2000])
    except Exception as error:
        log.warning("Could not post %s in %s: %s", key, guild_row["name"], error)
        db.set_last_error(guild_row["id"], f"Could not post {key.replace('_', ' ')}")
        return None


def _open_welcome_thread(guild_row, member, posted):
    """Private thread on the welcome message, then a DM with the link. Closed DMs leave the thread in place."""
    from .discord_api import DiscordError, add_thread_member, create_private_thread, send_dm

    message_id = (posted or {}).get("id")
    channel_id = (posted or {}).get("channel_id")
    if not message_id or not channel_id:
        return
    try:
        thread = create_private_thread(channel_id, message_id, welcome_thread_name(member.display_name))
    except DiscordError as error:
        log.warning("Could not open welcome thread in %s: %s", guild_row["name"], error)
        db.set_last_error(
            guild_row["id"],
            "Could not open a private welcome thread. Ironkeep needs Create Private Threads and Send Messages in Threads in that channel.",
        )
        return
    thread_id = (thread or {}).get("id")
    if not thread_id:
        return
    try:
        add_thread_member(thread_id, member.id)
    except DiscordError as error:
        log.warning("Could not add %s to welcome thread: %s", member.id, error)
        db.set_last_error(guild_row["id"], "Could not add the new member to their welcome thread.")
        return
    try:
        send_dm(member.id, f"Typ je antwoorden in deze thread: {welcome_thread_url(guild_row['id'], thread_id)}")
    except DiscordError as error:
        log.warning("Welcome thread link was not delivered to %s: %s", member.id, error)


def _sync_guild(guild, *, rejoin=False, added_by=None, added_by_id=None):
    me = guild.me
    row = db.guild_by_id(guild.id)
    trial_roles = []
    if row:
        for role_id in db.trial_role_ids(row["settings"]):
            try:
                role = guild.get_role(int(role_id))
            except (TypeError, ValueError):
                role = None
            if role:
                trial_roles.append(role)
    roles = []
    for role in guild.roles:
        roles.append(
            {
                "id": str(role.id),
                "name": "@everyone" if role.is_default() else role.name,
                "color": "#99aab5" if role.color.value == 0 else f"#{role.color.value:06x}",
                "position": role.position,
                "everyone": role.is_default(),
                "managed": bool(role.managed),
                "bot": bool(role.tags and role.tags.bot_id == me.id),
            }
        )
    channels = []
    for channel in guild.text_channels:
        channels.append(
            {
                "id": str(channel.id),
                "name": channel.name,
                "category": channel.category.name if channel.category else "Channels",
                "bot_can_send": channel.permissions_for(me).send_messages,
                "trial_visible": all(channel.permissions_for(role).view_channel for role in trial_roles) if trial_roles else True,
            }
        )
    db.upsert_guild(
        guild.id,
        guild.name,
        roles,
        channels,
        added_by=added_by,
        added_by_id=added_by_id,
        rejoin=rejoin,
    )


async def _who_added(guild):
    try:
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.bot_add):
            if entry.target and entry.target.id == guild.me.id and entry.user:
                return entry.user.display_name, str(entry.user.id)
    except discord.HTTPException:
        log.info("No audit log access in %s", guild.name)
    return None, None


def _reminders():
    for guild_row in db.list_guilds(with_trials=True):
        if guild_row["approval"] != "approved" or not guild_row["setup_complete"] or not guild_row["bot_present"]:
            continue
        settings = guild_row["settings"]
        reminder = (settings.get("messages") or {}).get("reminder") or {}
        if not reminder.get("enabled"):
            continue
        today = db.guild_today(settings)
        for trial in guild_row["trials"]:
            if trial["verdict"] or trial["left_server"] or not trial["start"] or trial["content_roles"] or trial["ping_sent_at"]:
                continue
            day = (today - date.fromisoformat(trial["start"])).days + 1
            if day < int(settings.get("reminder_day") or 7):
                continue
            length = int(settings.get("trial_days") or 14) + int(trial["extra_days"] or 0)
            end = date.fromisoformat(trial["start"]) + timedelta(days=length)
            values = {
                "member": f"<@{trial['user_id']}>",
                "guild": guild_row["name"],
                "days": length,
                "day": day,
                "start_date": db.human_date(trial["start"]),
                "end_date": db.human_date(end),
            }
            try:
                from .discord_api import send_dm, send_message

                text = fill(reminder.get("text"), values)[:2000]
                if reminder.get("delivery") == "dm":
                    send_dm(trial["user_id"], text)
                    note = "Day reminder sent as a direct message"
                else:
                    send_message(reminder["channel"], text)
                    note = "Day reminder sent"
                db.mark_ping_sent(trial["id"], settings, note)
            except Exception as error:
                log.warning("Reminder failed for %s: %s", trial["name"], error)
                db.set_last_error(guild_row["id"], f"Could not send the reminder for {trial['name']}")


async def _scan(guild):
    row = db.guild_by_id(guild.id)
    if row is None or not row["needs_scan"] or row["approval"] != "approved":
        return
    _sync_guild(guild)
    row = db.guild_by_id(guild.id)
    if row is None:
        return
    people = []
    async for member in guild.fetch_members(limit=None):
        if not member.bot:
            people.append(_member_record(member))
        consider_member(row, member, known_new=False)
    db.replace_members(guild.id, people)
    db.clear_scan(guild.id)
    log.info("Synced members in %s", guild.name)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if not config.BOT_TOKEN:
        log.error("DISCORD_BOT_TOKEN is not set. The bot stays stopped.")
        return
    db.init()
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info("Logged in as %s in %s guilds", client.user, len(client.guilds))
        for guild in client.guilds:
            _sync_guild(guild)
        db.mark_missing_guilds([guild.id for guild in client.guilds])
        asyncio.create_task(_hourly())

    @client.event
    async def on_guild_join(guild):
        added_by, added_by_id = await _who_added(guild)
        _sync_guild(guild, rejoin=True, added_by=added_by, added_by_id=added_by_id)
        log.info("Joined %s", guild.name)

    @client.event
    async def on_guild_remove(guild):
        db.mark_bot_left(guild.id)
        log.info("Left %s", guild.name)

    @client.event
    async def on_member_join(member):
        if member.bot:
            return
        row = db.guild_by_id(member.guild.id)
        if row is None or row["approval"] != "approved" or not row["setup_complete"]:
            return
        db.upsert_member(row["id"], _member_record(member))
        _open_welcome_thread(row, member, _send_template(row, "welcome", member))

    @client.event
    async def on_member_remove(member):
        row = db.guild_by_id(member.guild.id)
        if row is None:
            return
        db.remove_member(row["id"], member.id)
        db.mark_left(row["id"], member.id, row["settings"])

    @client.event
    async def on_member_update(before, after):
        if before.roles == after.roles:
            return
        row = db.guild_by_id(after.guild.id)
        if row is None or row["approval"] != "approved":
            return
        if not after.bot:
            db.upsert_member(row["id"], _member_record(after))
        consider_member(row, after, known_new=True, before_ids={str(role.id) for role in before.roles})

    async def _hourly():
        while not client.is_closed():
            try:
                for guild in list(client.guilds):
                    row = db.guild_by_id(guild.id)
                    if row and row["needs_scan"]:
                        await _scan(guild)
                await asyncio.to_thread(_reminders)
            except Exception:
                log.exception("Background pass failed")
            await asyncio.sleep(10)

    try:
        client.run(config.BOT_TOKEN, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        log.error("Turn on the Server Members Intent for this bot in the Discord developer portal, then restart ironkeep-bot.")
    except discord.LoginFailure:
        log.error("Discord rejected the bot token.")


if __name__ == "__main__":
    main()
