"""Super-admin ("god-mode") identity resolution.

A super-admin is identified purely by their Discord account snowflake, matched
against an allowlist supplied via the ``IRONKEEP_SUPERADMIN_DISCORD_IDS``
environment variable (comma-separated).  This is intentionally NOT stored in the
database: super-admin status cannot be granted, escalated, or discovered through
the application UI — only by whoever controls the server environment.

Security properties:
* If the env var is unset or empty, NOBODY is a super-admin (secure default).
* Dev-login users (no linked Discord identity) are never super-admins.
* The check reads the user's Discord identity from user_auth_identities via
  repositories.get_discord_identity_for_user.
"""

from __future__ import annotations

import os
import sqlite3

from starlette.requests import Request

from app import repositories
from app.auth.current_user import get_current_user

_ENV_VAR = "IRONKEEP_SUPERADMIN_DISCORD_IDS"


def superadmin_discord_ids() -> set[str]:
    """Return the configured set of super-admin Discord snowflakes.

    Parsed fresh on each call so the value can be changed without a code reload
    (and so tests can monkeypatch the environment).  Empty set when unset.
    """
    raw = os.environ.get(_ENV_VAR, "") or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def discord_id_for_user(db: sqlite3.Connection, user: dict | None) -> str | None:
    """Return the user's Discord snowflake, or None if they have no Discord
    identity linked (e.g. a pure dev-login account)."""
    if not user:
        return None
    identity = repositories.get_discord_identity_for_user(db, user["id"])
    return identity["provider_user_id"] if identity else None


def is_superadmin(db: sqlite3.Connection, user: dict | None) -> bool:
    """True when *user* is logged in with a Discord account on the allowlist."""
    allow = superadmin_discord_ids()
    if not allow:
        return False
    discord_id = discord_id_for_user(db, user)
    return discord_id is not None and discord_id in allow


def is_superadmin_request(db: sqlite3.Connection, request: Request) -> bool:
    """Convenience: resolve the current session user and check super-admin."""
    return is_superadmin(db, get_current_user(db, request))


def synthetic_owner_membership(guild_workspace_id: str, user_id: str) -> dict:
    """A fabricated owner-role membership row used to grant super-admins
    god-mode (owner-level) access to any workspace.

    Not persisted to the database — it exists only to satisfy role checks and
    to populate template access context.  The ``is_superadmin_synthetic`` flag
    lets callers/templates detect god-mode access if they want to show a banner.
    """
    return {
        "id": None,
        "guild_workspace_id": guild_workspace_id,
        "user_id": user_id,
        "role": "owner",
        "created_at": None,
        "is_superadmin_synthetic": True,
    }
