"""Discord gateway bot. Stays quiet until a guild is approved and its setup is complete.

Run with: python -m ironkeep.bot
Requires DISCORD_BOT_TOKEN and the Server Members intent in the Discord developer portal.
"""

import asyncio
import logging
import threading
import time
from datetime import date, timedelta

import discord

from . import config, db, forever_companion, tickets, warcraft_forever
from . import wow
from .discord_api import fill, replace_guild_commands

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


def _interaction_fields(data):
    """Values from a submitted form. Shared by every guided slash command."""
    fields = {}
    for row in (data or {}).get("components") or []:
        if not hasattr(row, "get"):
            continue
        nested = row.get("component")
        pieces = [nested] if isinstance(nested, dict) else []
        pieces.extend(row.get("components") or [])
        for component in pieces:
            if not hasattr(component, "get") or not component.get("custom_id"):
                continue
            chosen = component.get("values") or []
            if chosen:
                fields[component["custom_id"]] = chosen[0]
            elif "value" in component:
                fields[component["custom_id"]] = component.get("value") or ""
    return fields


def _observed(trial):
    return any(item.get("type") == "observation" for item in trial.get("timeline") or [])


def consider_member(guild_row, member, *, known_new, before_ids=None):
    if member.bot:
        return
    settings = guild_row["settings"]
    if db.guild_game(settings) == "wow":
        return
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
    db.sync_trial_identity(guild_row["id"], member.id, member.display_name, member.name, settings)
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


def _role_records(guild):
    me = guild.me
    records = []
    for role in guild.roles:
        records.append(
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
    return records


def _remember_roles(guild):
    db.replace_roles(guild.id, _role_records(guild))


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
    roles = _role_records(guild)
    channels = []
    for channel in guild.text_channels:
        channels.append(
            {
                "id": str(channel.id),
                "name": channel.name,
                "category": channel.category.name if channel.category else "Channels",
                "kind": "text",
                "bot_can_send": channel.permissions_for(me).send_messages,
                "trial_visible": all(channel.permissions_for(role).view_channel for role in trial_roles) if trial_roles else True,
            }
        )
    for category in guild.categories:
        channels.append(
            {
                "id": str(category.id),
                "name": category.name,
                "category": "",
                "kind": "category",
                "bot_can_send": False,
                "bot_can_manage": category.permissions_for(me).manage_channels,
                "trial_visible": True,
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
        icon_hash=guild.icon.key if guild.icon else "",
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
        if db.guild_game(guild_row["settings"]) == "wow":
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


async def _sync_wow_members(guild):
    """Replace the saved member list for a WoW server. Join, leave and rename keep it current after this."""
    row = db.guild_by_id(guild.id)
    if row is None or row["approval"] != "approved" or db.guild_game(row["settings"]) != "wow":
        return
    try:
        people = []
        async for member in guild.fetch_members(limit=None):
            if not member.bot:
                people.append(_member_record(member))
        db.replace_members(guild.id, people)
    except discord.HTTPException as error:
        log.warning("Could not sync members for %s: %s", guild.name, error)


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


def temp_voice_snapshot(client):
    """Channels the bot can see, and how many people are in each. Bots do not count."""
    snapshot = {}
    for guild in client.guilds:
        channels = {str(channel.id) for channel in getattr(guild, "voice_channels", ())}
        counts = {}
        for user_id, state in getattr(guild, "_voice_states", {}).items():
            channel = getattr(state, "channel", None)
            if channel is None:
                continue
            member = guild.get_member(user_id)
            if member is not None and member.bot:
                continue
            channel_id = str(channel.id)
            channels.add(channel_id)
            counts[channel_id] = counts.get(channel_id, 0) + 1
        snapshot[str(guild.id)] = {"channels": channels, "counts": counts}
    return snapshot


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if not config.BOT_TOKEN:
        log.error("DISCORD_BOT_TOKEN is not set. The bot stays stopped.")
        return
    db.init()
    warcraft_forever.refresh_if_stale()
    forever_companion.refresh_if_stale()
    albion_after = 0.0
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    client = discord.Client(intents=intents)
    refreshed_posts = False
    command_guilds = None
    command_lock = threading.Lock()
    command_retry_at = 0.0

    def _register_commands():
        nonlocal command_guilds, command_retry_at
        with command_lock:
            if time.time() < command_retry_at:
                return
            rows = []
            for guild in list(client.guilds):
                row = db.guild_by_id(guild.id)
                if row and row.get("approval") == "approved" and db.guild_game(row.get("settings")) == "wow":
                    rows.append(row)
            signature = tuple(sorted(str(row["id"]) for row in rows))
            if signature == command_guilds:
                return
            payload = wow.guild_commands()
            for row in rows:
                try:
                    replace_guild_commands(row["id"], payload)
                except Exception as error:
                    status = getattr(error, "status", None)
                    log.warning("Could not register slash commands for guild %s (HTTP %s)", row["id"], status)
                    command_retry_at = time.time() + 600
                    return
            command_guilds = signature
            command_retry_at = 0.0
            if signature:
                log.info("Registered slash commands in %s guilds", len(signature))

    @client.event
    async def on_ready():
        nonlocal refreshed_posts
        log.info("Logged in as %s in %s guilds", client.user, len(client.guilds))
        for guild in client.guilds:
            _sync_guild(guild)
        db.mark_missing_guilds([guild.id for guild in client.guilds])
        if not refreshed_posts:
            refreshed_posts = True
            asyncio.create_task(asyncio.to_thread(wow.refresh_posted))
        for guild in client.guilds:
            asyncio.create_task(_sync_wow_members(guild))
        asyncio.create_task(asyncio.to_thread(_register_commands))
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
    async def on_voice_state_update(member, before, after):
        if member.bot:
            return
        left = str(before.channel.id) if before.channel else None
        joined = str(after.channel.id) if after.channel else None
        if left == joined:
            return
        wow.note_voice(member.guild.id, member.id, wow.clean_name(member.display_name), left, joined)
        remaining = 0
        if before.channel is not None:
            remaining = len([
                person for person in before.channel.members
                if person.id != member.id and not person.bot
            ])
        role_ids = [str(role.id) for role in member.roles if not role.is_default()]
        await asyncio.to_thread(
            wow.handle_temp_voice,
            member.guild.id,
            member.id,
            wow.clean_name(member.display_name),
            role_ids,
            left,
            joined,
            remaining,
        )

    @client.event
    async def on_guild_channel_create(channel):
        _sync_guild(channel.guild)

    @client.event
    async def on_guild_channel_update(before, after):
        _sync_guild(after.guild)

    @client.event
    async def on_guild_channel_delete(channel):
        _sync_guild(channel.guild)

    @client.event
    async def on_member_join(member):
        if member.bot:
            return
        row = db.guild_by_id(member.guild.id)
        if row is None or row["approval"] != "approved" or not row["setup_complete"]:
            return
        db.upsert_member(row["id"], _member_record(member))
        if db.guild_game(row["settings"]) == "wow":
            return
        _open_welcome_thread(row, member, _send_template(row, "welcome", member))

    @client.event
    async def on_member_remove(member):
        row = db.guild_by_id(member.guild.id)
        if row is None:
            return
        db.remove_member(row["id"], member.id)
        if db.guild_game(row["settings"]) == "wow":
            for raid in db.drop_open_signups(row["id"], member.id):
                try:
                    wow.publish(row, raid)
                except Exception:
                    log.warning("Could not update raid %s after %s left", raid["id"], member.id)
            return
        db.mark_left(row["id"], member.id, row["settings"])

    @client.event
    async def on_member_update(before, after):
        roles_changed = before.roles != after.roles
        identity_changed = before.display_name != after.display_name or before.name != after.name or before.nick != after.nick
        if not roles_changed and not identity_changed:
            return
        row = db.guild_by_id(after.guild.id)
        if row is None or row["approval"] != "approved":
            return
        if db.guild_game(row["settings"]) == "wow":
            if after.bot:
                return
            db.upsert_member(row["id"], _member_record(after))
            if identity_changed:
                for raid in db.rename_wow_player(row["id"], after.id, wow.clean_name(after.display_name)):
                    try:
                        wow.publish(row, raid)
                    except Exception:
                        log.warning("Could not update raid %s after a nickname change", raid["id"])
            return
        if not after.bot:
            db.upsert_member(row["id"], _member_record(after))
        if roles_changed:
            consider_member(row, after, known_new=True, before_ids={str(role.id) for role in before.roles})
        elif identity_changed and not after.bot:
            db.sync_trial_identity(row["id"], after.id, after.display_name, after.name, row["settings"])

    @client.event
    async def on_guild_role_create(role):
        _remember_roles(role.guild)

    @client.event
    async def on_guild_role_update(before, after):
        _remember_roles(after.guild)

    @client.event
    async def on_guild_role_delete(role):
        _remember_roles(role.guild)

    @client.event
    async def on_interaction(interaction):
        data = interaction.data or {}
        if not hasattr(data, "get"):
            return
        if interaction.type in (discord.InteractionType.application_command, discord.InteractionType.autocomplete):
            person = interaction.user
            role_ids = [str(role_id) for role_id in getattr(person, "_roles", []) or []]
            try:
                if interaction.type == discord.InteractionType.autocomplete:
                    await asyncio.to_thread(
                        wow.answer_character_autocomplete,
                        str(interaction.id),
                        interaction.token,
                        data,
                    )
                elif (data or {}).get("name") == "raid":
                    await asyncio.to_thread(
                        wow.answer_create_raid,
                        str(interaction.guild_id or ""),
                        str(person.id),
                        person.display_name if person is not None else "Officer",
                        role_ids,
                        str(interaction.id),
                        interaction.token,
                        data,
                    )
                elif (data or {}).get("name") in ("character", "createchar"):
                    await asyncio.to_thread(
                        wow.answer_create_character,
                        str(interaction.guild_id or ""),
                        str(person.id),
                        str(interaction.id),
                        interaction.token,
                        data,
                    )
            except Exception:
                log.exception("Slash command failed")
            return
        custom_id = data.get("custom_id") or ""
        if not str(custom_id).startswith("ik"):
            if interaction.type == discord.InteractionType.component:
                log.info("Ignored button %s", custom_id or type(data).__name__)
            return
        person = interaction.user
        name = person.display_name if person is not None else "Unknown"
        role_ids = [str(role_id) for role_id in getattr(person, "_roles", []) or []]
        guild_id = str(interaction.guild_id or "")
        user_id = str(interaction.user.id)
        if str(custom_id).startswith("ikt"):
            try:
                await asyncio.to_thread(
                    tickets.answer,
                    guild_id,
                    user_id,
                    name,
                    role_ids,
                    custom_id,
                    list(data.get("values") or []),
                    str(interaction.id),
                    interaction.token,
                    _interaction_fields(data) if interaction.type == discord.InteractionType.modal_submit else {},
                    person.name if person is not None else "",
                )
            except Exception:
                log.exception("Ticket action failed")
            return
        if str(custom_id).startswith("ikr"):
            try:
                await asyncio.to_thread(
                    wow.answer_raid_prompt,
                    guild_id,
                    user_id,
                    role_ids,
                    str(interaction.id),
                    interaction.token,
                    custom_id,
                    list(data.get("values") or []),
                    _interaction_fields(data) if interaction.type == discord.InteractionType.modal_submit else {},
                )
            except Exception:
                log.exception("Raid prompt failed")
            return
        if str(custom_id).startswith("iky"):
            try:
                await asyncio.to_thread(
                    wow.answer_character_prompt,
                    guild_id,
                    user_id,
                    str(interaction.id),
                    interaction.token,
                    custom_id,
                    list(data.get("values") or []),
                    _interaction_fields(data) if interaction.type == discord.InteractionType.modal_submit else {},
                )
            except Exception:
                log.exception("Character prompt failed")
            return
        if str(custom_id).startswith("ike") and interaction.type == discord.InteractionType.modal_submit:
            fields = _interaction_fields(data)
            try:
                await asyncio.to_thread(
                    wow.answer_raid_settings,
                    guild_id,
                    user_id,
                    role_ids,
                    str(interaction.id),
                    interaction.token,
                    custom_id,
                    fields,
                )
            except Exception:
                log.exception("Raid settings failed")
            return
        if interaction.type == discord.InteractionType.modal_submit:
            reason = ""
            for row in data.get("components") or []:
                for component in (row.get("components") or []) if hasattr(row, "get") else []:
                    if component.get("custom_id") == "reason":
                        reason = component.get("value") or ""
            await asyncio.to_thread(
                wow.handle_absence,
                guild_id,
                user_id,
                name,
                custom_id,
                reason,
                str(interaction.id),
                interaction.token,
                role_ids,
            )
            return
        if interaction.type != discord.InteractionType.component:
            return
        log.info("Button %s from %s", custom_id, user_id)
        values = list(data.get("values") or [])
        await asyncio.to_thread(
            wow.handle_component,
            guild_id,
            user_id,
            name,
            custom_id,
            values,
            str(interaction.id),
            interaction.token,
            role_ids,
        )

    async def _hourly():
        nonlocal albion_after
        while not client.is_closed():
            try:
                for guild in list(client.guilds):
                    row = db.guild_by_id(guild.id)
                    if row and row["needs_scan"]:
                        await _scan(guild)
                await asyncio.to_thread(_register_commands)
                await asyncio.to_thread(_reminders)
                await asyncio.to_thread(wow.run_schedule, None, temp_voice_snapshot(client))
                if time.time() >= albion_after:
                    from .albion import refresh_open_trials

                    await asyncio.to_thread(refresh_open_trials)
                    albion_after = time.time() + 3600
            except Exception:
                log.exception("Background pass failed")
                if time.time() >= albion_after:
                    albion_after = time.time() + 600
            await asyncio.sleep(10)

    try:
        client.run(config.BOT_TOKEN, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        log.error("Turn on the Server Members Intent for this bot in the Discord developer portal, then restart ironkeep-bot.")
    except discord.LoginFailure:
        log.error("Discord rejected the bot token.")


if __name__ == "__main__":
    main()
