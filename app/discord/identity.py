"""
Discord ↔ application identity resolution.

Resolves Discord guild IDs and Discord user snowflakes to application
workspace and user records using existing DB fields only.

Design rules:
- A Discord guild maps 1:1 to a GuildWorkspace via guild_workspaces.discord_guild_id.
- A Discord user maps to an app user via users.auth_provider='discord'
  and users.provider_user_id = discord_user_snowflake.
- Resolution failures raise typed errors so command handlers can return
  clear ephemeral messages to the Discord user.
- No Discord API calls, no SDK, no OAuth.

Resolution order (resolve_member_from_discord / get_discord_identity_context):
  1. Workspace from guild  — DiscordNotLinkedError        (infrastructure problem)
  2. User from Discord ID  — DiscordUserNotLinkedError    (user problem)
  3. Membership check      — DiscordUserNotWorkspaceMemberError (access problem)
"""

from __future__ import annotations

from app import repositories
from app.errors import IronkeepError


# ---------------------------------------------------------------------------
# Discord-specific errors
# ---------------------------------------------------------------------------

class DiscordNotLinkedError(IronkeepError):
    """The Discord guild is not linked to any GuildWorkspace."""


class DiscordUserNotLinkedError(IronkeepError):
    """The Discord user snowflake has no linked application user account."""


class DiscordUserNotWorkspaceMemberError(IronkeepError):
    """The Discord user is a valid app user but is not a member of the linked workspace."""


# ---------------------------------------------------------------------------
# Resolution functions
# ---------------------------------------------------------------------------

_DISCORD_PROVIDER = "discord"


def resolve_workspace_from_discord_guild(db, discord_guild_id: str) -> dict:
    """
    Return the GuildWorkspace linked to the given Discord guild ID.

    Raises DiscordNotLinkedError if no workspace has been linked to this
    Discord server (i.e. an owner has not yet set discord_guild_id via
    the Discord settings page).
    """
    workspace = repositories.get_workspace_by_discord_guild_id(db, discord_guild_id)
    if not workspace:
        raise DiscordNotLinkedError(
            "This Discord server is not linked to a workspace. "
            "A workspace owner must connect it from the web UI."
        )
    return workspace


def resolve_user_from_discord_id(db, discord_user_id: str) -> dict:
    """
    Return the application user whose Discord account matches discord_user_id.

    Looks up by auth_provider='discord' and provider_user_id=discord_user_id.
    Raises DiscordUserNotLinkedError if no such user exists.
    """
    user = repositories.get_user_by_provider_identity(db, _DISCORD_PROVIDER, discord_user_id)
    if not user:
        raise DiscordUserNotLinkedError(
            "Your Discord account is not linked to an IronkeepV2 user. "
            "Visit the workspace web UI to link your account."
        )
    return user


def resolve_member_from_discord(
    db,
    discord_guild_id: str,
    discord_user_id: str,
) -> dict:
    """
    Resolve and verify a Discord user's membership in the linked workspace.

    Resolution order (fails fast):
      1. discord_guild_id → workspace (DiscordNotLinkedError)
      2. discord_user_id  → user      (DiscordUserNotLinkedError)
      3. membership check             (DiscordUserNotWorkspaceMemberError)

    Returns the workspace_members row for the user in the linked workspace.
    Membership in any other workspace does not satisfy this check.
    """
    workspace = resolve_workspace_from_discord_guild(db, discord_guild_id)
    user = resolve_user_from_discord_id(db, discord_user_id)

    membership = repositories.get_workspace_membership(db, workspace["id"], user["id"])
    if not membership:
        raise DiscordUserNotWorkspaceMemberError(
            f"You are not a member of the workspace linked to this Discord server "
            f"({workspace['name']}). Contact an officer to be added."
        )
    return membership


def get_discord_identity_context(
    db,
    discord_guild_id: str,
    discord_user_id: str,
) -> dict:
    """
    Primary entry point for Discord command handlers.

    Resolves all three entities in a single call and returns a context dict
    suitable for passing directly to use cases or formatters.

    Returns:
        {
            "workspace":  GuildWorkspace dict,
            "user":       app user dict,
            "membership": workspace_members dict (role, etc.),
        }

    Raises DiscordNotLinkedError, DiscordUserNotLinkedError, or
    DiscordUserNotWorkspaceMemberError on the first resolution failure.
    """
    workspace = resolve_workspace_from_discord_guild(db, discord_guild_id)
    user = resolve_user_from_discord_id(db, discord_user_id)

    membership = repositories.get_workspace_membership(db, workspace["id"], user["id"])
    if not membership:
        raise DiscordUserNotWorkspaceMemberError(
            f"You are not a member of the workspace linked to this Discord server "
            f"({workspace['name']}). Contact an officer to be added."
        )

    return {
        "workspace":  workspace,
        "user":       user,
        "membership": membership,
    }
