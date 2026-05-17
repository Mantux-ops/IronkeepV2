"""
IronkeepV2 Discord bot — proof-of-life entry point.

This module is the ONLY place that imports the Discord SDK.
All bot identity comes from environment variables via config.py.
Swapping the bot application requires only changing environment variables.

Current commands:
  /ikv2_ping  — health-check; confirms the bot is alive and shows latency

Component interactions:
  checkin:scout:{operation_id}   — routes to adapter.handle_component_interaction
  checkin:support:{operation_id} — routes to adapter.handle_component_interaction

Future operational commands (/signup, /readiness, /roster, /checkin) will be
added here and MUST delegate to app.discord.adapter handlers directly.
No adapter, formatter, identity, or dispatcher logic should be duplicated
in this file.
"""

from __future__ import annotations

import sys

import discord
from discord import app_commands

from app import database
from app.discord import adapter
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

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """
        Gateway glue for non-slash interactions (e.g. button clicks).

        Component interactions are dispatched to the adapter layer, which calls
        existing application use cases.  No business logic lives here.
        """
        if interaction.type != discord.InteractionType.component:
            return

        payload = {
            "discord_guild_id": str(interaction.guild_id or ""),
            "discord_user_id":  str(interaction.user.id),
            "custom_id":        (interaction.data or {}).get("custom_id", ""),
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
