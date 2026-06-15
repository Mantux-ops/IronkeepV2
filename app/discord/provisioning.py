"""
Discord bot guild lifecycle — workspace bootstrap.

This module is the ONLY app-layer entry point for bot join/leave events.
It accepts plain string values extracted from discord.Guild by the bot
entrypoint and delegates entirely to application use cases.

Rules:
- No Discord SDK imports.  No discord.py objects accepted or returned.
- No business logic — resolve values → call use case → log result.
- Never raises: exceptions are caught and logged so the bot stays alive.
- No secrets are included in log messages (guild IDs and names are not secrets).
"""

from __future__ import annotations

import logging

from app.application import use_cases

_log = logging.getLogger(__name__)


def handle_guild_join(
    discord_guild_id: str,
    guild_name: str,
    discord_guild_owner_id: str | None = None,
) -> None:
    """
    Called by bot.on_guild_join after extracting str values from discord.Guild.

    Ensures a workspace exists for the given Discord guild and records the guild
    owner's Discord snowflake so the web setup flow can verify ownership claims.
    If the workspace already exists (re-join after bot removal) the call is a
    safe no-op that only updates the install audit record.

    All exceptions are caught: a provisioning failure must never crash the bot.
    """
    try:
        workspace = use_cases.ensure_workspace_for_discord_guild(
            discord_guild_id=discord_guild_id,
            guild_name=guild_name,
            discord_guild_owner_id=discord_guild_owner_id,
        )
        _log.info(
            "[provisioning] Guild joined: guild_id=%s name=%r → workspace id=%s slug=%r",
            discord_guild_id,
            guild_name,
            workspace["id"],
            workspace["slug"],
        )
    except Exception as exc:  # noqa: BLE001
        _log.error(
            "[provisioning] Workspace bootstrap failed: guild_id=%s error=%s",
            discord_guild_id,
            exc,
        )
