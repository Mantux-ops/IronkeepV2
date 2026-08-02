"""
IronkeepV2 Discord bot — proof-of-life entry point.

This module is the ONLY place that imports the Discord SDK.
All bot identity comes from environment variables via config.py.
Swapping the bot application requires only changing environment variables.

Current commands:
  /ikv2_ping  — health-check; confirms the bot is alive and shows latency

Gateway events:
  on_guild_join  — delegates to app.discord.provisioning.handle_guild_join

Component interactions (all routed to adapter.handle_component_interaction):
  checkin:scout:{operation_id}   — button
  checkin:support:{operation_id} — button
  signup:{operation_id}          — roster role picker; the adapter answers the
                                   member and hands back a follow-up instruction
                                   for the thread notice and build DM

Future operational commands (/signup, /readiness, /roster, /checkin) will be
added here and MUST delegate to app.discord.adapter handlers directly.
No adapter, formatter, identity, or dispatcher logic should be duplicated
in this file.
"""

from __future__ import annotations

import asyncio
import sys

# Load .env if present so the bot can be started without manually exporting vars.
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

import discord
from discord import app_commands

from app import database
from app.application import use_cases
from app.discord import adapter, provisioning
from bot.config import BotConfig, load_config


class IronkeepBot(discord.Client):
    """
    Minimal Discord client for IronkeepV2.

    Commands are registered in _register_commands(), which is called from
    __init__ so they are available when setup_hook syncs the command tree.
    """

    def __init__(self, *, config: BotConfig) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    def _register_commands(self) -> None:
        """Register all slash commands on the command tree."""

        @self.tree.command(
            name="ikv2_ping",
            description="IronkeepV2 bot health check — confirms the bot is alive.",
        )
        async def ikv2_ping(interaction: discord.Interaction) -> None:
            latency_ms = round(self.latency * 1000)
            await interaction.response.send_message(
                f"🏓 **IronkeepV2** is alive.\n"
                f"Latency: `{latency_ms}ms`  ·  Client: `{self.config.client_id}`",
                ephemeral=True,
            )

    async def setup_hook(self) -> None:
        """
        Called by discord.py before the bot logs in.
        Syncs the command tree to the configured target (guild or global).
        """
        if self.config.dev_guild_id:
            guild = discord.Object(id=int(self.config.dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            sync_mode = f"guild {self.config.dev_guild_id} (instant)"
        else:
            await self.tree.sync()
            sync_mode = "global (may take up to 1 hour)"

        command_count = len(self.tree.get_commands())
        print(
            f"[IronkeepV2] Commands synced — mode: {sync_mode} "
            f"| {command_count} command(s) registered"
        )

    async def on_ready(self) -> None:
        """Log bot identity and sync status on successful gateway connection."""
        print(
            f"[IronkeepV2] Bot ready\n"
            f"  User    : {self.user} (id={self.user.id})\n"
            f"  Client  : {self.config.client_id}\n"
            f"  Sync    : {'guild ' + self.config.dev_guild_id if self.config.dev_guild_id else 'global'}\n"
            f"  Commands: {len(self.tree.get_commands())}"
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """
        Called when the bot is added to a Discord server (or rejoins after removal).

        Delegates workspace provisioning to the app layer.  No business logic
        lives here — only value extraction and delegation.  Exceptions are
        handled inside provisioning.handle_guild_join so the bot stays alive.
        """
        provisioning.handle_guild_join(
            discord_guild_id=str(guild.id),
            guild_name=guild.name,
            discord_guild_owner_id=str(guild.owner_id) if guild.owner_id else None,
        )

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """
        Gateway glue for non-slash interactions (button clicks, select menus).

        Component interactions are dispatched to the adapter layer, which calls
        existing application use cases.  No business logic lives here.
        """
        if interaction.type != discord.InteractionType.component:
            return

        data_in = interaction.data or {}
        payload = {
            "discord_guild_id": str(interaction.guild_id or ""),
            "discord_user_id":  str(interaction.user.id),
            "custom_id":        data_in.get("custom_id", ""),
            # Present only for select menus; Discord sends the chosen option
            # values separately from the component's custom_id.
            "values":           list(data_in.get("values") or []),
        }

        try:
            with database.transaction() as db:
                response = adapter.handle_component_interaction(payload, db)
        except Exception as exc:  # noqa: BLE001
            print(f"[IronkeepV2] Component interaction error: {exc}", file=sys.stderr)
            await interaction.response.send_message(
                "❌ An unexpected error occurred. Please try again later.",
                ephemeral=True,
            )
            return

        data = response.get("data", {})
        content  = data.get("content")
        flags    = data.get("flags", 0)
        ephemeral = bool(flags & 64)

        await interaction.response.send_message(content=content, ephemeral=ephemeral)

        # Answer first, then do the slow part.  Discord invalidates an
        # interaction that goes unacknowledged for three seconds, and the
        # follow-up work below is several REST round-trips.
        follow_up = response.get("follow_up")
        if follow_up:
            await self._run_follow_up(interaction, follow_up)

    async def _run_follow_up(
        self,
        interaction: discord.Interaction,
        follow_up: dict,
    ) -> None:
        """
        Carry out the outbound Discord work a component interaction asked for.

        Runs after the member already has their confirmation, so nothing here may
        raise: a thread or DM that does not arrive is reported to the member, not
        turned into a failed interaction.
        """
        if follow_up.get("kind") != "role_choice":
            return

        try:
            result = await asyncio.to_thread(
                use_cases.deliver_role_choice_notifications,
                guild_workspace_id=follow_up["guild_workspace_id"],
                guild_operation_id=follow_up["guild_operation_id"],
                operation=follow_up["operation"],
                slot=follow_up["slot"],
                choice=follow_up["choice"],
                display_name=follow_up["display_name"],
                discord_user_id=follow_up["discord_user_id"],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[IronkeepV2] Role choice follow-up error: {exc}", file=sys.stderr)
            return

        if result["dm"] == "sent":
            return

        # The DM did not land — most often because the member blocks DMs from
        # server members.  The build is what they actually came for, so it is
        # delivered in the interaction itself instead.
        payload = result["build_payload"]
        note = (
            "Your DMs are closed, so here is your build:"
            if result["dm"] == "blocked"
            else "I could not DM you, so here is your build:"
        )
        try:
            await interaction.followup.send(
                content=note,
                embeds=[discord.Embed.from_dict(e) for e in payload.get("embeds", [])],
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            print(f"[IronkeepV2] Build fallback failed: {exc}", file=sys.stderr)


def main() -> None:
    try:
        config = load_config()
    except RuntimeError as exc:
        print(f"[IronkeepV2] Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"[IronkeepV2] Starting bot\n"
        f"  Client ID : {config.client_id}\n"
        f"  Dev guild : {config.dev_guild_id or '(none — global sync)'}"
    )

    bot = IronkeepBot(config=config)
    bot.run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
