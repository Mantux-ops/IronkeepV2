"""
Bot configuration — loaded entirely from environment variables.

No defaults are provided for required variables. The bot will refuse to start
with a clear RuntimeError if a required variable is missing, so misconfigured
deployments fail loudly at startup rather than silently at runtime.

Swapping bot identity is done by changing environment variables only.
No code changes are needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    token: str
    client_id: str
    dev_guild_id: str | None  # None → global command sync


def load_config() -> BotConfig:
    """
    Read bot configuration from environment variables.

    Raises RuntimeError with an actionable message if a required variable
    is missing or empty.
    """
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is required but not set. "
            "Set it in your environment or in a .env file before starting the bot."
        )

    client_id = os.environ.get("DISCORD_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "DISCORD_CLIENT_ID is required but not set. "
            "Find it in the Discord Developer Portal → Your Application → General Information."
        )

    dev_guild_id = os.environ.get("DISCORD_DEV_GUILD_ID", "").strip() or None

    return BotConfig(
        token=token,
        client_id=client_id,
        dev_guild_id=dev_guild_id,
    )
