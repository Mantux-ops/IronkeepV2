"""
Durable Discord message identity store.

Wraps discord_messages table operations so that posted message IDs survive
bot restarts and can be used to edit or delete existing Discord messages.

All functions open their own short transactions — suitable for use from the
bot process or any context that does not already hold a DB transaction.

For web use-case code that already manages its own transactions, call
repositories.get_discord_message / repositories.upsert_discord_message
directly inside the transaction instead.

Design rules:
- Before posting: call get() to check for an existing message_id to edit.
- After posting: call save() with the returned Discord message_id.
- If an edit returns 404 (message deleted externally): post fresh, call save().
- is_deleted flag allows tracking externally-deleted messages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def get(
    guild_workspace_id: str,
    guild_operation_id: str,
    message_type: str,
) -> dict | None:
    """Return the stored discord_messages row, or None if not found."""
    from app import database, repositories  # noqa: PLC0415

    with database.transaction() as db:
        return repositories.get_discord_message(
            db, guild_workspace_id, guild_operation_id, message_type
        )


def save(
    guild_workspace_id: str,
    guild_operation_id: str,
    message_type: str,
    discord_channel_id: str,
    discord_message_id: str,
    discord_guild_id: str,
) -> None:
    """
    Upsert a discord_messages row after successfully posting or editing.

    Calling save() again with the same (ws_id, op_id, message_type) key
    updates the existing row via INSERT OR REPLACE.
    """
    from app import database, repositories  # noqa: PLC0415

    now = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        repositories.upsert_discord_message(db, {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "message_type":       message_type,
            "discord_channel_id": discord_channel_id,
            "discord_message_id": discord_message_id,
            "discord_guild_id":   discord_guild_id,
            "posted_at":          now,
            "last_edited_at":     now,
            "is_deleted":         0,
        })
