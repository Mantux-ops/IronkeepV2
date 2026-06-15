"""
Raw SQL repository functions.

Rules:
- Every function takes a sqlite3.Connection as its first argument.
- All queries that return entity data include guild_workspace_id in WHERE
  so cross-workspace leakage is impossible at the DB layer.
- Functions return plain dicts (or lists/sets thereof) — not sqlite3.Row.
- No business logic lives here.  Raise sqlite3 exceptions only; domain
  errors are raised by use cases.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _rows(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GuildWorkspace
# ---------------------------------------------------------------------------

def insert_workspace(db: sqlite3.Connection, workspace: dict) -> None:
    db.execute(
        """
        INSERT INTO guild_workspaces (id, name, slug, primary_game, created_at, updated_at)
        VALUES (:id, :name, :slug, :primary_game, :created_at, :updated_at)
        """,
        workspace,
    )


def get_workspace_by_id(db: sqlite3.Connection, workspace_id: str) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM guild_workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    )


def get_workspace_by_slug(db: sqlite3.Connection, slug: str) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM guild_workspaces WHERE slug = ?", (slug,)
        ).fetchone()
    )


def get_workspaces_for_user(db: sqlite3.Connection, user_id: str) -> list[dict]:
    return _rows(
        db.execute(
            """
            SELECT w.*
            FROM guild_workspaces w
            JOIN workspace_members m ON m.guild_workspace_id = w.id
            WHERE m.user_id = ?
            ORDER BY w.name
            """,
            (user_id,),
        ).fetchall()
    )


def get_unclaimed_discord_workspaces(db: sqlite3.Connection) -> list[dict]:
    """
    Return Discord-provisioned workspaces that have no owner member.

    These are workspaces created automatically by the bot (discord_provisioned_at
    IS NOT NULL) that are still in the "setup required" state because no verified
    guild owner has completed the web setup flow yet.

    Used to display setup-required notices on the workspace list page.
    The list is shown to all authenticated users so any guild officer can see
    that their server's workspace needs claiming.
    """
    return _rows(
        db.execute(
            """
            SELECT w.*
            FROM guild_workspaces w
            WHERE w.discord_provisioned_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM workspace_members m
                  WHERE m.guild_workspace_id = w.id AND m.role = 'owner'
              )
            ORDER BY w.name
            """,
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def insert_user(db: sqlite3.Connection, user: dict) -> None:
    db.execute(
        """
        INSERT INTO users
            (id, display_name, auth_provider, provider_user_id, created_at, updated_at)
        VALUES
            (:id, :display_name, :auth_provider, :provider_user_id, :created_at, :updated_at)
        """,
        user,
    )


def get_user_by_id(db: sqlite3.Connection, user_id: str) -> dict | None:
    return _row(
        db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    )


def get_users_by_ids(
    db: sqlite3.Connection,
    user_ids: list[str],
) -> list[dict]:
    """
    Batch-fetch users by a list of IDs.  Returns only rows that exist.
    Order is not guaranteed.  Deduplication is handled by the caller.
    """
    if not user_ids:
        return []
    placeholders = ", ".join("?" * len(user_ids))
    return _rows(
        db.execute(
            f"SELECT * FROM users WHERE id IN ({placeholders})",
            list(user_ids),
        ).fetchall()
    )


def get_user_by_provider_identity(
    db: sqlite3.Connection,
    auth_provider: str,
    provider_user_id: str,
) -> dict | None:
    """
    Resolve a user from a provider identity.

    Primary path: JOIN user_auth_identities (the new table, written for all
    users after the backfill migration).

    Fallback: legacy users.auth_provider / provider_user_id columns (catches
    any users created before the backfill ran — a narrow transition window).
    The fallback is permanent; it costs nothing and guards against edge cases.
    """
    row = db.execute(
        """
        SELECT u.* FROM users u
        JOIN user_auth_identities i ON i.user_id = u.id
        WHERE i.auth_provider = ? AND i.provider_user_id = ?
        """,
        (auth_provider, provider_user_id),
    ).fetchone()
    if row:
        return _row(row)
    # Fallback: pre-backfill or legacy users.
    return _row(
        db.execute(
            "SELECT * FROM users WHERE auth_provider = ? AND provider_user_id = ?",
            (auth_provider, provider_user_id),
        ).fetchone()
    )


def list_users(db: sqlite3.Connection) -> list[dict]:
    return _rows(
        db.execute(
            "SELECT * FROM users ORDER BY display_name"
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Auth identities
# ---------------------------------------------------------------------------

def insert_user_auth_identity(db: sqlite3.Connection, identity: dict) -> None:
    """
    Insert a row into user_auth_identities.

    identity must contain: id, user_id, auth_provider, provider_user_id, created_at.
    """
    db.execute(
        """
        INSERT INTO user_auth_identities
            (id, user_id, auth_provider, provider_user_id, created_at)
        VALUES
            (:id, :user_id, :auth_provider, :provider_user_id, :created_at)
        """,
        identity,
    )


def get_auth_identity(
    db: sqlite3.Connection,
    auth_provider: str,
    provider_user_id: str,
) -> dict | None:
    """Lookup in user_auth_identities only (not the legacy users columns)."""
    return _row(
        db.execute(
            """
            SELECT * FROM user_auth_identities
            WHERE auth_provider = ? AND provider_user_id = ?
            """,
            (auth_provider, provider_user_id),
        ).fetchone()
    )


def get_auth_identities_for_user(
    db: sqlite3.Connection, user_id: str
) -> list[dict]:
    """Return all user_auth_identities rows for a user, ordered by auth_provider."""
    return _rows(
        db.execute(
            """
            SELECT * FROM user_auth_identities
            WHERE user_id = ?
            ORDER BY auth_provider
            """,
            (user_id,),
        ).fetchall()
    )


def count_user_references(db: sqlite3.Connection, user_id: str) -> int:
    """
    Count rows that reference user_id across workspace_members and
    operational_events.actor_id.  Used to determine whether an orphaned
    discord user is safe to delete atomically during account linking.
    """
    (member_count,) = db.execute(
        "SELECT COUNT(*) FROM workspace_members WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    (event_count,) = db.execute(
        "SELECT COUNT(*) FROM operational_events WHERE actor_id = ?",
        (user_id,),
    ).fetchone()
    return member_count + event_count


def delete_user_and_identity(db: sqlite3.Connection, user_id: str) -> None:
    """
    Delete both the user_auth_identities rows and the users row for an orphaned
    discord-only user.

    MUST only be called after confirming count_user_references == 0.
    The caller is responsible for performing that check within the same
    transaction before calling this function.
    """
    db.execute(
        "DELETE FROM user_auth_identities WHERE user_id = ?", (user_id,)
    )
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Workspace members
# ---------------------------------------------------------------------------

def insert_workspace_member(db: sqlite3.Connection, membership: dict) -> None:
    db.execute(
        """
        INSERT INTO workspace_members
            (id, guild_workspace_id, user_id, role, created_at)
        VALUES
            (:id, :guild_workspace_id, :user_id, :role, :created_at)
        """,
        membership,
    )


def get_workspace_membership(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    user_id: str,
) -> dict | None:
    return _row(
        db.execute(
            """
            SELECT * FROM workspace_members
            WHERE guild_workspace_id = ? AND user_id = ?
            """,
            (guild_workspace_id, user_id),
        ).fetchone()
    )


def list_workspace_members(db: sqlite3.Connection, guild_workspace_id: str) -> list[dict]:
    return _rows(
        db.execute(
            """
            SELECT m.*, u.display_name
            FROM workspace_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.guild_workspace_id = ?
            ORDER BY m.role, u.display_name
            """,
            (guild_workspace_id,),
        ).fetchall()
    )


def delete_workspace_member(
    db: sqlite3.Connection, guild_workspace_id: str, user_id: str
) -> None:
    """
    Remove only the workspace_members row for this user.
    Does NOT touch users, participants, signup_intents, assignments, or
    attendance_records — historical data is preserved unchanged.
    """
    db.execute(
        "DELETE FROM workspace_members WHERE guild_workspace_id = ? AND user_id = ?",
        (guild_workspace_id, user_id),
    )


def count_workspace_owners(db: sqlite3.Connection, guild_workspace_id: str) -> int:
    """Return the number of members with role='owner' in this workspace."""
    row = db.execute(
        "SELECT COUNT(*) FROM workspace_members WHERE guild_workspace_id = ? AND role = 'owner'",
        (guild_workspace_id,),
    ).fetchone()
    return row[0] if row else 0


def count_active_assignments_for_participant(
    db: sqlite3.Connection, guild_workspace_id: str, participant_id: str
) -> int:
    """
    Count active (status='assigned') assignments for a participant across all
    operations in this workspace.  Used as a guard before member removal.
    """
    row = db.execute(
        """
        SELECT COUNT(*)
        FROM assignments
        WHERE guild_workspace_id = ? AND participant_id = ? AND status = 'assigned'
        """,
        (guild_workspace_id, participant_id),
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# GuildOperation
# ---------------------------------------------------------------------------

def insert_guild_operation(db: sqlite3.Connection, operation: dict) -> None:
    db.execute(
        """
        INSERT INTO guild_operations
            (id, guild_workspace_id, title, operation_type, scheduled_start_at,
             status, created_at, updated_at)
        VALUES
            (:id, :guild_workspace_id, :title, :operation_type, :scheduled_start_at,
             :status, :created_at, :updated_at)
        """,
        operation,
    )


def get_guild_operation(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM guild_operations WHERE id = ? AND guild_workspace_id = ?",
            (operation_id, guild_workspace_id),
        ).fetchone()
    )


def update_operation_status(
    db: sqlite3.Connection,
    operation_id: str,
    guild_workspace_id: str,
    new_status: str,
    updated_at: str,
) -> None:
    """
    Update the status and updated_at of a guild_operation row.

    The WHERE clause is scoped by both id and guild_workspace_id so the
    UPDATE cannot accidentally mutate an operation in a different workspace.
    """
    db.execute(
        """
        UPDATE guild_operations
        SET status = ?, updated_at = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (new_status, updated_at, operation_id, guild_workspace_id),
    )


def get_guild_operations(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    include_archived: bool = False,
) -> list[dict]:
    if include_archived:
        sql = "SELECT * FROM guild_operations WHERE guild_workspace_id = ? ORDER BY scheduled_start_at"
    else:
        sql = "SELECT * FROM guild_operations WHERE guild_workspace_id = ? AND status != 'archived' ORDER BY scheduled_start_at"
    return _rows(db.execute(sql, (guild_workspace_id,)).fetchall())


def count_archived_guild_operations(
    db: sqlite3.Connection, guild_workspace_id: str
) -> int:
    row = db.execute(
        "SELECT COUNT(*) FROM guild_operations WHERE guild_workspace_id = ? AND status = 'archived'",
        (guild_workspace_id,),
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# AlbionComposition
# ---------------------------------------------------------------------------

def insert_albion_composition(db: sqlite3.Connection, composition: dict) -> None:
    db.execute(
        """
        INSERT INTO albion_compositions (id, guild_workspace_id, name, description, created_at, updated_at)
        VALUES (:id, :guild_workspace_id, :name, :description, :created_at, :updated_at)
        """,
        composition,
    )


def get_albion_composition(
    db: sqlite3.Connection, composition_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM albion_compositions WHERE id = ? AND guild_workspace_id = ?",
            (composition_id, guild_workspace_id),
        ).fetchone()
    )


def get_albion_compositions(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    include_deleted: bool = False,
) -> list[dict]:
    if include_deleted:
        sql = "SELECT * FROM albion_compositions WHERE guild_workspace_id = ? ORDER BY name"
    else:
        sql = "SELECT * FROM albion_compositions WHERE guild_workspace_id = ? AND deleted_at IS NULL ORDER BY name"
    return _rows(db.execute(sql, (guild_workspace_id,)).fetchall())


def count_deleted_albion_compositions(
    db: sqlite3.Connection, guild_workspace_id: str
) -> int:
    row = db.execute(
        "SELECT COUNT(*) FROM albion_compositions WHERE guild_workspace_id = ? AND deleted_at IS NOT NULL",
        (guild_workspace_id,),
    ).fetchone()
    return row[0] if row else 0


def get_all_composition_slot_roles_for_workspace(
    db: sqlite3.Connection, guild_workspace_id: str
) -> list[dict]:
    """Fetch (albion_composition_id, role) pairs for all slot templates in the workspace.

    Returns only the fields needed for role-tally computation on the compositions list page.
    Avoids N individual queries by fetching all templates in one pass.
    """
    return _rows(
        db.execute(
            """
            SELECT albion_composition_id, role
            FROM composition_slot_templates
            WHERE guild_workspace_id = ?
            """,
            (guild_workspace_id,),
        ).fetchall()
    )


def get_operations_using_composition(
    db: sqlite3.Connection, composition_id: str, guild_workspace_id: str
) -> list[dict]:
    """Return non-archived operations that reference this composition via operation_plans.

    Used by the composition detail page to surface active operational context
    and provide direct Planner navigation links.
    Ordered by scheduled_start_at descending (most recent first).
    """
    return _rows(
        db.execute(
            """
            SELECT o.id, o.title, o.operation_type, o.status, o.scheduled_start_at
            FROM guild_operations o
            JOIN operation_plans p ON p.guild_operation_id = o.id
            WHERE p.albion_composition_id = ?
              AND p.guild_workspace_id = ?
              AND o.status != 'archived'
            ORDER BY o.scheduled_start_at DESC
            """,
            (composition_id, guild_workspace_id),
        ).fetchall()
    )


def count_active_operations_per_composition(
    db: sqlite3.Connection, guild_workspace_id: str
) -> dict[str, int]:
    """Return {albion_composition_id: count} of non-archived operations using each composition.

    An operation is counted as active when its status is not 'archived'.
    Used by the compositions list to show tactical reuse context.
    """
    rows = db.execute(
        """
        SELECT p.albion_composition_id, COUNT(p.guild_operation_id) AS cnt
        FROM operation_plans p
        JOIN guild_operations o ON o.id = p.guild_operation_id
        WHERE p.guild_workspace_id = ?
          AND o.status != 'archived'
        GROUP BY p.albion_composition_id
        """,
        (guild_workspace_id,),
    ).fetchall()
    return {row["albion_composition_id"]: row["cnt"] for row in rows}


def soft_delete_albion_composition(
    db: sqlite3.Connection,
    composition_id: str,
    guild_workspace_id: str,
    deleted_at: str,
) -> None:
    """
    Mark a composition as retired by setting deleted_at.
    Does NOT touch composition_slot_templates or operation_slots — those are
    preserved intact so existing operation plans continue to work.
    """
    db.execute(
        """
        UPDATE albion_compositions
        SET deleted_at = ?, updated_at = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (deleted_at, deleted_at, composition_id, guild_workspace_id),
    )


# ---------------------------------------------------------------------------
# AlbionBuild
# ---------------------------------------------------------------------------

def insert_albion_build(db: sqlite3.Connection, build: dict) -> None:
    db.execute(
        """
        INSERT INTO albion_builds
            (id, guild_workspace_id, name, role, weapon_name, offhand_name,
             head_name, armor_name, shoes_name, cape_name, food_name, potion_name,
             notes, doctrine_role, created_at, updated_at, retired_at)
        VALUES
            (:id, :guild_workspace_id, :name, :role, :weapon_name, :offhand_name,
             :head_name, :armor_name, :shoes_name, :cape_name, :food_name, :potion_name,
             :notes, :doctrine_role, :created_at, :updated_at, :retired_at)
        """,
        build,
    )


def get_albion_build(
    db: sqlite3.Connection, build_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM albion_builds WHERE id = ? AND guild_workspace_id = ?",
            (build_id, guild_workspace_id),
        ).fetchone()
    )


def get_albion_builds(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    include_retired: bool = False,
) -> list[dict]:
    if include_retired:
        sql = (
            "SELECT * FROM albion_builds WHERE guild_workspace_id = ? "
            "ORDER BY name"
        )
    else:
        sql = (
            "SELECT * FROM albion_builds "
            "WHERE guild_workspace_id = ? AND retired_at IS NULL "
            "ORDER BY name"
        )
    return _rows(db.execute(sql, (guild_workspace_id,)).fetchall())


def update_albion_build_fields(
    db: sqlite3.Connection,
    build_id: str,
    guild_workspace_id: str,
    fields: dict,
    updated_at: str,
) -> None:
    """Update mutable fields on an albion_build row."""
    db.execute(
        """
        UPDATE albion_builds
        SET name          = :name,
            role          = :role,
            weapon_name   = :weapon_name,
            offhand_name  = :offhand_name,
            head_name     = :head_name,
            armor_name    = :armor_name,
            shoes_name    = :shoes_name,
            cape_name     = :cape_name,
            food_name     = :food_name,
            potion_name   = :potion_name,
            notes         = :notes,
            doctrine_role = :doctrine_role,
            updated_at    = :updated_at
        WHERE id = :id AND guild_workspace_id = :guild_workspace_id
        """,
        {**fields, "id": build_id, "guild_workspace_id": guild_workspace_id, "updated_at": updated_at},
    )


def retire_albion_build(
    db: sqlite3.Connection,
    build_id: str,
    guild_workspace_id: str,
    retired_at: str,
) -> None:
    db.execute(
        """
        UPDATE albion_builds
        SET retired_at = ?, updated_at = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (retired_at, retired_at, build_id, guild_workspace_id),
    )


def get_build_usage_compositions(
    db: sqlite3.Connection,
    build_id: str,
    guild_workspace_id: str,
) -> list[dict]:
    """Return distinct active compositions that reference build_id via FK.

    A composition is counted when at least one of its composition_slot_templates
    rows carries albion_build_id = build_id.  Retired compositions
    (deleted_at IS NOT NULL) are excluded.  Results are ordered by name.

    This is a read-only query — it never touches slot templates or operation
    slots.  The FK is a traceability reference only; this query surfaces it.
    """
    return _rows(
        db.execute(
            """
            SELECT DISTINCT c.id, c.name, c.deleted_at
            FROM albion_compositions c
            JOIN composition_slot_templates cst
              ON cst.albion_composition_id = c.id
             AND cst.albion_build_id = ?
             AND cst.guild_workspace_id = ?
            WHERE c.deleted_at IS NULL
            ORDER BY c.name
            """,
            (build_id, guild_workspace_id),
        ).fetchall()
    )


def get_builds_with_usage_counts(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    include_retired: bool = False,
) -> list[dict]:
    """Return build rows augmented with a usage_count field.

    usage_count = number of distinct active compositions (deleted_at IS NULL)
    that have at least one composition_slot_templates row with
    albion_build_id = build.id.

    Builds with no FK references carry usage_count = 0.
    Ordering matches get_albion_builds: alphabetical by name.
    """
    retired_clause = "" if include_retired else "AND b.retired_at IS NULL"
    rows = _rows(
        db.execute(
            f"""
            SELECT b.*,
                   COUNT(DISTINCT CASE
                       WHEN c.deleted_at IS NULL THEN cst.albion_composition_id
                   END) AS usage_count
            FROM albion_builds b
            LEFT JOIN composition_slot_templates cst
              ON cst.albion_build_id = b.id
             AND cst.guild_workspace_id = b.guild_workspace_id
            LEFT JOIN albion_compositions c
              ON c.id = cst.albion_composition_id
            WHERE b.guild_workspace_id = ?
              {retired_clause}
            GROUP BY b.id
            ORDER BY b.name
            """,
            (guild_workspace_id,),
        ).fetchall()
    )
    # Ensure usage_count is always an int (sqlite returns it as int already,
    # but guard for None from an empty LEFT JOIN).
    for row in rows:
        row["usage_count"] = row.get("usage_count") or 0
    return rows


# ---------------------------------------------------------------------------
# CompositionSlotTemplate
# ---------------------------------------------------------------------------

def insert_composition_slot_templates(
    db: sqlite3.Connection, templates: list[dict]
) -> None:
    db.executemany(
        """
        INSERT INTO composition_slot_templates
            (id, guild_workspace_id, albion_composition_id, party_number, slot_index,
             role, build_name, weapon_name,
             offhand_name, head_name, armor_name, shoes_name, cape_name, food_name, potion_name,
             albion_build_id, doctrine_role, priority, created_at, updated_at)
        VALUES
            (:id, :guild_workspace_id, :albion_composition_id, :party_number, :slot_index,
             :role, :build_name, :weapon_name,
             :offhand_name, :head_name, :armor_name, :shoes_name, :cape_name, :food_name, :potion_name,
             :albion_build_id, :doctrine_role, :priority, :created_at, :updated_at)
        """,
        templates,
    )


def get_composition_slot_templates(
    db: sqlite3.Connection, composition_id: str, guild_workspace_id: str
) -> list[dict]:
    return _rows(
        db.execute(
            """
            SELECT * FROM composition_slot_templates
            WHERE albion_composition_id = ? AND guild_workspace_id = ?
            ORDER BY party_number, slot_index
            """,
            (composition_id, guild_workspace_id),
        ).fetchall()
    )


def get_composition_slot_template_by_id(
    db: sqlite3.Connection, template_id: str, guild_workspace_id: str
) -> dict | None:
    """Fetch a single composition_slot_templates row by primary key.

    Scoped to guild_workspace_id so cross-workspace reads are structurally
    impossible.  Returns None if the template does not exist or belongs to a
    different workspace.
    """
    return _row(
        db.execute(
            "SELECT * FROM composition_slot_templates WHERE id = ? AND guild_workspace_id = ?",
            (template_id, guild_workspace_id),
        ).fetchone()
    )


def update_composition_slot_fields(
    db: sqlite3.Connection,
    slot_id: str,
    composition_id: str,
    guild_workspace_id: str,
    fields: dict,
    updated_at: str,
) -> int:
    """Targeted UPDATE on a single composition_slot_templates row.

    Updates only the mutable doctrine fields (build, weapon, doctrine_role,
    equipment snapshot) without touching role, priority, party, or index.
    Returns the number of rows updated (1 on success, 0 if slot not found).

    The WHERE clause scopes the update to the correct workspace and composition
    so cross-workspace writes are structurally impossible.
    Does NOT touch operation_slots — those remain frozen snapshots.
    """
    cursor = db.execute(
        """
        UPDATE composition_slot_templates
        SET role            = CASE WHEN :role != '' THEN :role ELSE role END,
            build_name      = :build_name,
            weapon_name     = :weapon_name,
            doctrine_role   = :doctrine_role,
            albion_build_id = :albion_build_id,
            offhand_name    = :offhand_name,
            head_name       = :head_name,
            armor_name      = :armor_name,
            shoes_name      = :shoes_name,
            cape_name       = :cape_name,
            food_name       = :food_name,
            potion_name     = :potion_name,
            updated_at      = :updated_at
        WHERE id                      = :id
          AND albion_composition_id   = :albion_composition_id
          AND guild_workspace_id      = :guild_workspace_id
        """,
        {
            **fields,
            "id":                    slot_id,
            "albion_composition_id": composition_id,
            "guild_workspace_id":    guild_workspace_id,
            "updated_at":            updated_at,
        },
    )
    return cursor.rowcount


def delete_composition_slot_templates(
    db: sqlite3.Connection,
    composition_id: str,
    guild_workspace_id: str,
) -> int:
    """Delete all slot templates for a composition.

    Returns the number of rows deleted.
    Used by update_composition_slots to atomically replace the slot set.
    Does NOT touch operation_slots — those are frozen snapshots and are
    never modified by template changes.
    """
    cursor = db.execute(
        """
        DELETE FROM composition_slot_templates
        WHERE albion_composition_id = ? AND guild_workspace_id = ?
        """,
        (composition_id, guild_workspace_id),
    )
    return cursor.rowcount


def get_distinct_slot_build_suggestions(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> dict:
    """Return distinct, trimmed, alphabetically sorted build_name and weapon_name
    values from composition_slot_templates for this workspace.

    NULL, empty, and whitespace-only values are excluded.
    Safe to call on a workspace with no templates — both lists will be empty.
    Never raises; never mutates.
    """
    build_names = [
        row[0]
        for row in db.execute(
            """
            SELECT DISTINCT TRIM(build_name)
            FROM composition_slot_templates
            WHERE guild_workspace_id = ?
              AND build_name IS NOT NULL
              AND TRIM(build_name) != ''
            ORDER BY TRIM(build_name) ASC
            """,
            (guild_workspace_id,),
        ).fetchall()
    ]
    weapon_names = [
        row[0]
        for row in db.execute(
            """
            SELECT DISTINCT TRIM(weapon_name)
            FROM composition_slot_templates
            WHERE guild_workspace_id = ?
              AND weapon_name IS NOT NULL
              AND TRIM(weapon_name) != ''
            ORDER BY TRIM(weapon_name) ASC
            """,
            (guild_workspace_id,),
        ).fetchall()
    ]
    return {"build_names": build_names, "weapon_names": weapon_names}


def touch_albion_composition(
    db: sqlite3.Connection,
    composition_id: str,
    guild_workspace_id: str,
    updated_at: str,
) -> None:
    """Bump the updated_at timestamp on a composition row."""
    db.execute(
        """
        UPDATE albion_compositions
        SET updated_at = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (updated_at, composition_id, guild_workspace_id),
    )


# ---------------------------------------------------------------------------
# OperationPlan
# ---------------------------------------------------------------------------

def insert_operation_plan(db: sqlite3.Connection, plan: dict) -> None:
    db.execute(
        """
        INSERT INTO operation_plans
            (id, guild_workspace_id, guild_operation_id, albion_composition_id,
             signup_status, max_participants, notes, created_at, updated_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :albion_composition_id,
             :signup_status, :max_participants, :notes, :created_at, :updated_at)
        """,
        plan,
    )


def get_operation_plan(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM operation_plans WHERE guild_operation_id = ? AND guild_workspace_id = ?",
            (operation_id, guild_workspace_id),
        ).fetchone()
    )


# ---------------------------------------------------------------------------
# OperationSlot  (frozen snapshot — no status column)
# ---------------------------------------------------------------------------

def insert_operation_slots(db: sqlite3.Connection, slots: list[dict]) -> None:
    db.executemany(
        """
        INSERT INTO operation_slots
            (id, guild_workspace_id, guild_operation_id,
             source_composition_slot_template_id,
             party_number, slot_index, role, build_name, weapon_name,
             offhand_name, head_name, armor_name, shoes_name, cape_name, food_name, potion_name,
             doctrine_role, priority, created_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id,
             :source_composition_slot_template_id,
             :party_number, :slot_index, :role, :build_name, :weapon_name,
             :offhand_name, :head_name, :armor_name, :shoes_name, :cape_name, :food_name, :potion_name,
             :doctrine_role, :priority, :created_at)
        """,
        slots,
    )


def get_operation_slots(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> list[dict]:
    return _rows(
        db.execute(
            """
            SELECT * FROM operation_slots
            WHERE guild_operation_id = ? AND guild_workspace_id = ?
            ORDER BY party_number, slot_index
            """,
            (operation_id, guild_workspace_id),
        ).fetchall()
    )


def get_operation_slot(
    db: sqlite3.Connection, slot_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM operation_slots WHERE id = ? AND guild_workspace_id = ?",
            (slot_id, guild_workspace_id),
        ).fetchone()
    )


def update_operation_slot_build(
    db: sqlite3.Connection,
    slot_id: str,
    guild_workspace_id: str,
    build_name: str,
    weapon_name: str | None,
) -> None:
    """Update the build_name and weapon_name on an existing operation slot."""
    db.execute(
        """
        UPDATE operation_slots
        SET build_name = ?, weapon_name = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (build_name, weapon_name or None, slot_id, guild_workspace_id),
    )


def count_operation_slots(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM operation_slots WHERE guild_operation_id = ? AND guild_workspace_id = ?",
        (operation_id, guild_workspace_id),
    ).fetchone()
    return row["cnt"]


# ---------------------------------------------------------------------------
# Participant
# ---------------------------------------------------------------------------

def find_participant_by_display_name(
    db: sqlite3.Connection, guild_workspace_id: str, display_name: str
) -> dict | None:
    """Return the participant row for this display_name in the workspace, or None."""
    return _row(
        db.execute(
            "SELECT * FROM participants WHERE guild_workspace_id = ? AND display_name = ?",
            (guild_workspace_id, display_name),
        ).fetchone()
    )


def find_or_create_participant(
    db: sqlite3.Connection, guild_workspace_id: str, display_name: str
) -> dict:
    """
    Idempotent: returns existing participant if display_name is taken,
    otherwise inserts and returns the new one.  Must be called within a
    transaction to be safe against concurrent inserts (SQLite is single-writer,
    so this is fine in practice).
    """
    now = _now()
    pid = str(uuid.uuid4())
    db.execute(
        """
        INSERT OR IGNORE INTO participants
            (id, guild_workspace_id, display_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pid, guild_workspace_id, display_name, now, now),
    )
    row = db.execute(
        "SELECT * FROM participants WHERE guild_workspace_id = ? AND display_name = ?",
        (guild_workspace_id, display_name),
    ).fetchone()
    return dict(row)


def get_participant(
    db: sqlite3.Connection, participant_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM participants WHERE id = ? AND guild_workspace_id = ?",
            (participant_id, guild_workspace_id),
        ).fetchone()
    )


def get_participants_for_workspace(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> list[dict]:
    """Return all participant rows for a workspace, ordered by display_name."""
    return _rows(
        db.execute(
            "SELECT * FROM participants WHERE guild_workspace_id = ? ORDER BY display_name",
            (guild_workspace_id,),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# SignupIntent
# ---------------------------------------------------------------------------

def insert_signup_intent(db: sqlite3.Connection, signup: dict) -> None:
    db.execute(
        """
        INSERT INTO signup_intents
            (id, guild_workspace_id, guild_operation_id, participant_id,
             preferred_role, preferred_build_name, willingness, availability,
             source, created_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :participant_id,
             :preferred_role, :preferred_build_name, :willingness, :availability,
             :source, :created_at)
        """,
        signup,
    )


def get_signup_intent(
    db: sqlite3.Connection,
    operation_id: str,
    participant_id: str,
    guild_workspace_id: str,
) -> dict | None:
    return _row(
        db.execute(
            """
            SELECT * FROM signup_intents
            WHERE guild_operation_id = ? AND participant_id = ? AND guild_workspace_id = ?
            """,
            (operation_id, participant_id, guild_workspace_id),
        ).fetchone()
    )


def get_signup_intent_by_id(
    db: sqlite3.Connection,
    signup_id: str,
    guild_workspace_id: str,
) -> dict | None:
    """Fetch a signup_intent by primary key within a workspace."""
    return _row(
        db.execute(
            "SELECT * FROM signup_intents WHERE id = ? AND guild_workspace_id = ?",
            (signup_id, guild_workspace_id),
        ).fetchone()
    )


def withdraw_signup_intent(
    db: sqlite3.Connection,
    signup_id: str,
    guild_workspace_id: str,
    withdrawn_at: str,
) -> None:
    """Soft-delete a signup by recording the withdrawal timestamp."""
    db.execute(
        "UPDATE signup_intents SET withdrawn_at = ? WHERE id = ? AND guild_workspace_id = ?",
        (withdrawn_at, signup_id, guild_workspace_id),
    )


def count_active_assignments_for_participant_in_operation(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
) -> int:
    """
    Count active (status='assigned') assignments for a participant within a
    specific operation.  Used by withdraw_signup_intent to block withdrawal
    when the participant is currently assigned to a slot.
    """
    row = db.execute(
        """
        SELECT COUNT(*) FROM assignments
        WHERE guild_workspace_id = ?
          AND guild_operation_id = ?
          AND participant_id     = ?
          AND status             = 'assigned'
        """,
        (guild_workspace_id, guild_operation_id, participant_id),
    ).fetchone()
    return row[0] if row else 0


def get_signup_intents(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> list[dict]:
    """Return active (non-withdrawn) signup intents for an operation."""
    return _rows(
        db.execute(
            """
            SELECT * FROM signup_intents
            WHERE guild_operation_id = ? AND guild_workspace_id = ?
              AND withdrawn_at IS NULL
            ORDER BY created_at
            """,
            (operation_id, guild_workspace_id),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def get_active_assignment_for_slot(
    db: sqlite3.Connection, operation_slot_id: str
) -> dict | None:
    """
    Returns the active assignment for a slot, or None if the slot is open.
    This is the canonical check for 'is this slot assigned?'
    operation_slots carries no status column — assignment state lives here.
    """
    return _row(
        db.execute(
            "SELECT * FROM assignments WHERE operation_slot_id = ? AND status = 'assigned' LIMIT 1",
            (operation_slot_id,),
        ).fetchone()
    )


def insert_assignment(db: sqlite3.Connection, assignment: dict) -> None:
    db.execute(
        """
        INSERT INTO assignments
            (id, guild_workspace_id, guild_operation_id, operation_slot_id,
             participant_id, assigned_role, assigned_build_name, status, assigned_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :operation_slot_id,
             :participant_id, :assigned_role, :assigned_build_name, :status, :assigned_at)
        """,
        assignment,
    )


def get_assignments(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> list[dict]:
    return _rows(
        db.execute(
            """
            SELECT * FROM assignments
            WHERE guild_operation_id = ? AND guild_workspace_id = ?
            ORDER BY assigned_at
            """,
            (operation_id, guild_workspace_id),
        ).fetchall()
    )


def get_assigned_slot_ids(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> set[str]:
    """
    Returns the set of operation_slot_ids that have an active assignment.
    Used by readiness calculation to avoid a status column on operation_slots.
    """
    rows = db.execute(
        """
        SELECT DISTINCT operation_slot_id
        FROM assignments
        WHERE guild_operation_id = ? AND guild_workspace_id = ? AND status = 'assigned'
        """,
        (operation_id, guild_workspace_id),
    ).fetchall()
    return {row["operation_slot_id"] for row in rows}


def count_unassigned_signups(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> int:
    """
    Signups for this operation whose participant has no active assignment.
    Used in readiness snapshot: indicates bench depth.
    """
    row = db.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM signup_intents si
        WHERE si.guild_operation_id = ?
          AND si.guild_workspace_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM assignments a
              WHERE a.participant_id      = si.participant_id
                AND a.guild_operation_id  = si.guild_operation_id
                AND a.guild_workspace_id  = si.guild_workspace_id
                AND a.status              = 'assigned'
          )
        """,
        (operation_id, guild_workspace_id),
    ).fetchone()
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# ReadinessSnapshot
# ---------------------------------------------------------------------------

def count_attendance_marked(
    db: sqlite3.Connection, guild_operation_id: str, guild_workspace_id: str
) -> int:
    """Count active assignments that already have an attendance record."""
    row = db.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM attendance_records ar
        JOIN assignments a ON a.id = ar.assignment_id
        WHERE ar.guild_operation_id = ?
          AND ar.guild_workspace_id = ?
          AND a.status = 'assigned'
        """,
        (guild_operation_id, guild_workspace_id),
    ).fetchone()
    return row["cnt"]


def get_scout_attendance_counts(
    db: sqlite3.Connection, guild_operation_id: str, guild_workspace_id: str
) -> dict:
    """Return {"scout": n, "support": m} for this operation."""
    rows = db.execute(
        """
        SELECT role_type, COUNT(*) AS cnt
        FROM scout_attendance_records
        WHERE guild_operation_id = ?
          AND guild_workspace_id = ?
        GROUP BY role_type
        """,
        (guild_operation_id, guild_workspace_id),
    ).fetchall()
    counts: dict = {"scout": 0, "support": 0}
    for row in rows:
        counts[row["role_type"]] = row["cnt"]
    return counts


def insert_readiness_snapshot(db: sqlite3.Connection, snapshot: dict) -> None:
    db.execute(
        """
        INSERT INTO readiness_snapshots
            (id, guild_workspace_id, guild_operation_id,
             total_slots, assigned_slots, open_slots,
             unassigned_signup_count, missing_roles_json, missing_builds_json,
             attendance_marked_count, attendance_unmarked_count,
             scout_count, support_count,
             reserve_count,
             readiness_state, created_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id,
             :total_slots, :assigned_slots, :open_slots,
             :unassigned_signup_count, :missing_roles_json, :missing_builds_json,
             :attendance_marked_count, :attendance_unmarked_count,
             :scout_count, :support_count,
             :reserve_count,
             :readiness_state, :created_at)
        """,
        snapshot,
    )


def get_latest_readiness_snapshot(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> dict | None:
    return _row(
        db.execute(
            """
            SELECT * FROM readiness_snapshots
            WHERE guild_operation_id = ? AND guild_workspace_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (operation_id, guild_workspace_id),
        ).fetchone()
    )


def get_latest_readiness_snapshots_for_workspace(
    db: sqlite3.Connection, guild_workspace_id: str
) -> dict[str, dict]:
    """
    Return the most-recent readiness snapshot for every operation in the
    workspace, as a dict keyed by guild_operation_id.

    Uses a single JOIN query — no N+1 per operation.
    Operations that have no snapshot are simply absent from the returned dict.
    """
    rows = db.execute(
        """
        SELECT rs.*
        FROM readiness_snapshots rs
        JOIN (
            SELECT guild_operation_id, MAX(created_at) AS max_at
            FROM readiness_snapshots
            WHERE guild_workspace_id = ?
            GROUP BY guild_operation_id
        ) latest
          ON  rs.guild_operation_id = latest.guild_operation_id
          AND rs.created_at         = latest.max_at
        WHERE rs.guild_workspace_id = ?
        """,
        (guild_workspace_id, guild_workspace_id),
    ).fetchall()
    return {dict(r)["guild_operation_id"]: dict(r) for r in rows}


# ---------------------------------------------------------------------------
# OperationalEvent
# ---------------------------------------------------------------------------

def insert_operational_event(db, event: dict) -> None:
    """
    Persist an OperationalEvent row.

    If db is a TransactionContext (the normal case when called from within
    database.transaction()), also appends the event to db.pending_dispatch so
    the post-commit loop in database.transaction() can forward it to
    app.events.dispatch_event after a successful commit.

    Works unchanged with a bare sqlite3.Connection (e.g. in init_schema or
    direct test helpers) — getattr returns None and no dispatch is queued.
    """
    db.execute(
        """
        INSERT INTO operational_events
            (id, guild_workspace_id, guild_operation_id, event_type,
             actor_type, actor_id, entity_type, entity_id, payload_json, occurred_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :event_type,
             :actor_type, :actor_id, :entity_type, :entity_id, :payload_json, :occurred_at)
        """,
        event,
    )
    pending = getattr(db, "pending_dispatch", None)
    if pending is not None:
        pending.append(event)


# ---------------------------------------------------------------------------
# UI read helpers  (added for Slice A/B routes — no schema changes)
# ---------------------------------------------------------------------------

def get_workspaces(db: sqlite3.Connection) -> list[dict]:
    """Return all workspaces ordered by name.  Used by the home page."""
    return _rows(
        db.execute(
            "SELECT * FROM guild_workspaces ORDER BY name"
        ).fetchall()
    )


def get_participants_for_operation(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> list[dict]:
    """
    Return participants who have an active (non-withdrawn) signup_intent for
    this operation.  Used by the planner board assign dropdown.
    """
    return _rows(
        db.execute(
            """
            SELECT p.id, p.display_name, p.guild_workspace_id
            FROM participants p
            JOIN signup_intents si ON si.participant_id = p.id
            WHERE si.guild_operation_id = ?
              AND si.guild_workspace_id = ?
              AND si.withdrawn_at IS NULL
            ORDER BY p.display_name
            """,
            (operation_id, guild_workspace_id),
        ).fetchall()
    )


def get_assigned_participants_for_operation(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> dict[str, dict]:
    """
    Return {operation_slot_id: {operation_slot_id, participant_id, display_name}}
    for all active assignments in this operation.
    Used by the planner board to show who occupies each slot.
    Reads operation_slots + assignments only — never composition_slot_templates.
    """
    rows = db.execute(
        """
        SELECT a.id AS assignment_id, a.operation_slot_id, a.participant_id, p.display_name
        FROM assignments a
        JOIN participants p ON p.id = a.participant_id
        WHERE a.guild_operation_id = ?
          AND a.guild_workspace_id = ?
          AND a.status = 'assigned'
        """,
        (operation_id, guild_workspace_id),
    ).fetchall()
    return {row["operation_slot_id"]: dict(row) for row in rows}


def get_signups_with_display_names(
    db: sqlite3.Connection, operation_id: str, guild_workspace_id: str
) -> list[dict]:
    """
    Return active (non-withdrawn) signup_intents enriched with participant
    display_name.  Used by the signup page and planner to show signups.
    """
    return _rows(
        db.execute(
            """
            SELECT si.*, p.display_name
            FROM signup_intents si
            JOIN participants p ON p.id = si.participant_id
            WHERE si.guild_operation_id = ?
              AND si.guild_workspace_id = ?
              AND si.withdrawn_at IS NULL
            ORDER BY si.created_at
            """,
            (operation_id, guild_workspace_id),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Assignment helpers
# ---------------------------------------------------------------------------

def get_assignment_by_id(
    db: sqlite3.Connection, assignment_id: str, guild_workspace_id: str
) -> dict | None:
    """Fetch a single assignment scoped to the workspace."""
    return _row(
        db.execute(
            "SELECT * FROM assignments WHERE id = ? AND guild_workspace_id = ?",
            (assignment_id, guild_workspace_id),
        ).fetchone()
    )


def get_active_assignment_for_participant(
    db: sqlite3.Connection,
    guild_operation_id: str,
    participant_id: str,
    guild_workspace_id: str,
) -> dict | None:
    """Return the active (status='assigned') assignment for this participant in
    this operation, or None.  Used to guard against double-assignment."""
    return _row(
        db.execute(
            """
            SELECT * FROM assignments
            WHERE guild_operation_id = ?
              AND participant_id      = ?
              AND guild_workspace_id  = ?
              AND status             = 'assigned'
            """,
            (guild_operation_id, participant_id, guild_workspace_id),
        ).fetchone()
    )


def set_assignment_status(
    db: sqlite3.Connection,
    assignment_id: str,
    guild_operation_id: str,
    status: str,
    guild_workspace_id: str,
) -> None:
    """
    Update the status column of a single assignment row.

    The WHERE clause is scoped by assignment id, guild_workspace_id AND
    guild_operation_id so the UPDATE cannot accidentally mutate an assignment
    that belongs to a different operation even if the caller passes a correct
    assignment_id from another operation.
    """
    db.execute(
        """
        UPDATE assignments
        SET status = ?
        WHERE id                = ?
          AND guild_workspace_id = ?
          AND guild_operation_id = ?
        """,
        (status, assignment_id, guild_workspace_id, guild_operation_id),
    )


# ---------------------------------------------------------------------------
# AttendanceRecord
# ---------------------------------------------------------------------------

def insert_attendance_record(db: sqlite3.Connection, record: dict) -> None:
    db.execute(
        """
        INSERT INTO attendance_records
            (id, guild_workspace_id, guild_operation_id, assignment_id,
             participant_id, status, notes, recorded_at, updated_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :assignment_id,
             :participant_id, :status, :notes, :recorded_at, :updated_at)
        """,
        record,
    )


def update_attendance_record(
    db: sqlite3.Connection,
    record_id: str,
    status: str,
    notes: str | None,
    updated_at: str,
) -> None:
    db.execute(
        "UPDATE attendance_records SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
        (status, notes, updated_at, record_id),
    )


def get_attendance_record(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    assignment_id: str,
) -> dict | None:
    """Look up an existing attendance record for the given assignment (upsert guard)."""
    return _row(
        db.execute(
            """
            SELECT * FROM attendance_records
            WHERE guild_workspace_id = ?
              AND guild_operation_id = ?
              AND assignment_id = ?
            """,
            (guild_workspace_id, guild_operation_id, assignment_id),
        ).fetchone()
    )


def get_attendance_records_for_operation(
    db: sqlite3.Connection, guild_operation_id: str, guild_workspace_id: str
) -> list[dict]:
    return _rows(
        db.execute(
            """
            SELECT * FROM attendance_records
            WHERE guild_operation_id = ? AND guild_workspace_id = ?
            ORDER BY recorded_at
            """,
            (guild_operation_id, guild_workspace_id),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Player reliability read-model
# ---------------------------------------------------------------------------

#: Only display a score when the player has at least this many resolved
#: assignments (present or absent — excused excluded).  Below this threshold
#: the sample is too small to be meaningful.
RELIABILITY_MIN_OPS: int = 3

#: Rolling window in days.  Assignments on operations whose scheduled_start_at
#: is older than this are excluded from the calculation.
RELIABILITY_WINDOW_DAYS: int = 90

#: Attendance statuses that count as "attended" in the numerator.
_RELIABILITY_PRESENT_STATUSES: frozenset[str] = frozenset({"present", "late"})

#: Attendance statuses that count in the denominator (excused is excluded).
_RELIABILITY_COUNTED_STATUSES: frozenset[str] = frozenset(
    {"present", "late", "absent", "no_show"}
)


def get_player_reliability_scores(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    window_days: int = RELIABILITY_WINDOW_DAYS,
) -> dict[str, dict]:
    """
    Return a reliability score per participant for operations in the rolling
    window, keyed by participant_id.

    Only resolved assignments on operations in status 'locked' or 'completed'
    within the last `window_days` days are included.  'excused' attendance is
    excluded from both numerator and denominator.

    Each value in the returned dict is:
      {
        "present":    int,            # count of present/late marks
        "total":      int,            # count of present + absent + no_show marks
        "rate":       float | None,   # None when total < RELIABILITY_MIN_OPS
        "display":    str | None,     # "N/D" string, None below threshold
        "rate_class": str,            # CSS class: "rel-green" | "rel-amber" | "rel-red" | ""
      }

    Players with zero resolved assignments in the window are not included.
    """
    from datetime import datetime, timezone, timedelta  # noqa: PLC0415

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).isoformat()

    rows = db.execute(
        """
        SELECT
            ar.participant_id,
            COUNT(CASE WHEN ar.status IN ('present', 'late') THEN 1 END) AS present_count,
            COUNT(ar.id)                                                  AS total_count
        FROM attendance_records ar
        JOIN guild_operations go
            ON  go.id                 = ar.guild_operation_id
            AND go.guild_workspace_id = ar.guild_workspace_id
        WHERE ar.guild_workspace_id = ?
          AND go.status             IN ('locked', 'completed')
          AND go.scheduled_start_at >= ?
          AND ar.status             IN ('present', 'late', 'absent', 'no_show')
        GROUP BY ar.participant_id
        """,
        (guild_workspace_id, cutoff),
    ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        pid     = row["participant_id"]
        present = row["present_count"]
        total   = row["total_count"]

        if total < RELIABILITY_MIN_OPS:
            rate       = None
            display    = None
            rate_class = ""
        else:
            rate = present / total
            display = f"{present}/{total}"
            if rate >= 0.8:
                rate_class = "rel-green"
            elif rate >= 0.5:
                rate_class = "rel-amber"
            else:
                rate_class = "rel-red"

        result[pid] = {
            "present":    present,
            "total":      total,
            "rate":       rate,
            "display":    display,
            "rate_class": rate_class,
        }

    return result


def get_assignments_with_attendance(
    db: sqlite3.Connection, guild_operation_id: str, guild_workspace_id: str
) -> list[dict]:
    """
    Return one row per active assignment for this operation, LEFT-JOINed with
    attendance_records.  Attendance columns are NULL if not yet recorded.
    Ordered by party_number, slot_index so the attendance page matches the
    planner board order.

    Reads operation_slots, assignments, participants, and attendance_records.
    """
    return _rows(
        db.execute(
            """
            SELECT
                a.id              AS assignment_id,
                a.operation_slot_id,
                a.participant_id,
                a.assigned_role,
                a.assigned_build_name,
                a.status          AS assignment_status,
                p.display_name,
                os.party_number,
                os.slot_index,
                ar.id             AS attendance_record_id,
                ar.status         AS attendance_status,
                ar.notes          AS attendance_notes,
                ar.recorded_at    AS attendance_recorded_at
            FROM assignments a
            JOIN participants   p  ON p.id  = a.participant_id
            JOIN operation_slots os ON os.id = a.operation_slot_id
            LEFT JOIN attendance_records ar
                   ON ar.assignment_id      = a.id
                  AND ar.guild_workspace_id = a.guild_workspace_id
            WHERE a.guild_operation_id = ?
              AND a.guild_workspace_id = ?
              AND a.status = 'assigned'
            ORDER BY os.party_number, os.slot_index
            """,
            (guild_operation_id, guild_workspace_id),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# ScoutAttendanceRecord
# ---------------------------------------------------------------------------

def insert_scout_attendance_record(db: sqlite3.Connection, record: dict) -> None:
    db.execute(
        """
        INSERT INTO scout_attendance_records
            (id, guild_workspace_id, guild_operation_id, participant_id,
             role_type, notes, recorded_at, updated_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :participant_id,
             :role_type, :notes, :recorded_at, :updated_at)
        """,
        record,
    )


def update_scout_attendance_record(
    db: sqlite3.Connection,
    record_id: str,
    role_type: str,
    notes: str | None,
    updated_at: str,
) -> None:
    db.execute(
        "UPDATE scout_attendance_records SET role_type = ?, notes = ?, updated_at = ? WHERE id = ?",
        (role_type, notes, updated_at, record_id),
    )


def get_scout_attendance_record(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
) -> dict | None:
    """Look up an existing scout check-in for this participant in this operation."""
    return _row(
        db.execute(
            """
            SELECT * FROM scout_attendance_records
            WHERE guild_workspace_id = ?
              AND guild_operation_id = ?
              AND participant_id = ?
            """,
            (guild_workspace_id, guild_operation_id, participant_id),
        ).fetchone()
    )


def get_scout_attendance_records_for_operation(
    db: sqlite3.Connection, guild_operation_id: str, guild_workspace_id: str
) -> list[dict]:
    """All scout/support check-ins for an operation, with display_name from participants."""
    return _rows(
        db.execute(
            """
            SELECT
                sar.*,
                p.display_name
            FROM scout_attendance_records sar
            JOIN participants p ON p.id = sar.participant_id
            WHERE sar.guild_operation_id = ?
              AND sar.guild_workspace_id = ?
            ORDER BY sar.recorded_at
            """,
            (guild_operation_id, guild_workspace_id),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# OperationReserve
# ---------------------------------------------------------------------------

def insert_reserve(db: sqlite3.Connection, reserve: dict) -> None:
    db.execute(
        """
        INSERT INTO operation_reserves
            (id, guild_workspace_id, guild_operation_id, participant_id, notes, created_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :participant_id, :notes, :created_at)
        """,
        reserve,
    )


def delete_reserve(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
) -> None:
    """Hard-delete the reserve row.  No-ops silently if the row is already gone."""
    db.execute(
        """
        DELETE FROM operation_reserves
        WHERE guild_workspace_id = ?
          AND guild_operation_id = ?
          AND participant_id     = ?
        """,
        (guild_workspace_id, guild_operation_id, participant_id),
    )


def get_reserve(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
) -> dict | None:
    """Return the reserve row for a specific participant, or None."""
    return _row(
        db.execute(
            """
            SELECT * FROM operation_reserves
            WHERE guild_workspace_id = ?
              AND guild_operation_id = ?
              AND participant_id     = ?
            """,
            (guild_workspace_id, guild_operation_id, participant_id),
        ).fetchone()
    )


def get_reserves_for_operation(
    db: sqlite3.Connection,
    guild_operation_id: str,
    guild_workspace_id: str,
) -> list[dict]:
    """
    Return all reserve rows for an operation, enriched with display_name and
    an is_assigned flag (True when the participant also has an active assignment).
    Ordered by created_at so the most recent bench additions appear last.
    """
    return _rows(
        db.execute(
            """
            SELECT
                r.id,
                r.guild_workspace_id,
                r.guild_operation_id,
                r.participant_id,
                r.notes,
                r.created_at,
                p.display_name,
                CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END AS is_assigned
            FROM operation_reserves r
            JOIN participants p ON p.id = r.participant_id
            LEFT JOIN assignments a
                   ON a.participant_id      = r.participant_id
                  AND a.guild_operation_id  = r.guild_operation_id
                  AND a.guild_workspace_id  = r.guild_workspace_id
                  AND a.status             = 'assigned'
            WHERE r.guild_operation_id = ?
              AND r.guild_workspace_id = ?
            ORDER BY r.created_at
            """,
            (guild_operation_id, guild_workspace_id),
        ).fetchall()
    )


def count_reserves_for_operation(
    db: sqlite3.Connection,
    guild_operation_id: str,
    guild_workspace_id: str,
) -> int:
    """Count current reserve rows for this operation."""
    row = db.execute(
        """
        SELECT COUNT(*) AS cnt FROM operation_reserves
        WHERE guild_operation_id = ? AND guild_workspace_id = ?
        """,
        (guild_operation_id, guild_workspace_id),
    ).fetchone()
    return row["cnt"] if row else 0


def get_operational_events(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str | None = None,
) -> list[dict]:
    if guild_operation_id is not None:
        return _rows(
            db.execute(
                """
                SELECT * FROM operational_events
                WHERE guild_workspace_id = ? AND guild_operation_id = ?
                ORDER BY occurred_at
                """,
                (guild_workspace_id, guild_operation_id),
            ).fetchall()
        )
    return _rows(
        db.execute(
            "SELECT * FROM operational_events WHERE guild_workspace_id = ? ORDER BY occurred_at",
            (guild_workspace_id,),
        ).fetchall()
    )


# Event types surfaced in the dashboard recent-activity widget.
# Individual signups, slot assignments, and attendance records are excluded —
# they are high-frequency operations that would drown out meaningful activity.
_ACTIVITY_WIDGET_EVENT_TYPES: tuple[str, ...] = (
    "guild_operation.created",
    "guild_operation.published",
    "guild_operation.locked",
    "guild_operation.completed",
    "guild_operation.archived",
    "payout_ledger.entry.approved",
    "payout_ledger.entry.paid",
    "discord_announcement.posted",
    "discord_announcement.updated",
    "discord_roster.posted",
    "discord_roster.updated",
)


def get_recent_workspace_activity(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    limit: int = 5,
) -> list[dict]:
    """
    Return the most recent notable operational events for a workspace, newest first.

    Joins with guild_operations to include op_title for operation-level events.
    Only returns event types relevant for officer dashboard awareness: lifecycle
    transitions, payout actions, and Discord announcements.  Individual signups,
    slot assignments, and attendance records are excluded to keep the widget
    low-noise.
    """
    placeholders = ",".join("?" * len(_ACTIVITY_WIDGET_EVENT_TYPES))
    params = (guild_workspace_id, *_ACTIVITY_WIDGET_EVENT_TYPES, limit)
    return _rows(
        db.execute(
            f"""
            SELECT
                e.id,
                e.event_type,
                e.actor_id,
                e.actor_type,
                e.occurred_at,
                e.guild_operation_id,
                COALESCE(o.title, '') AS op_title
            FROM operational_events e
            LEFT JOIN guild_operations o ON e.guild_operation_id = o.id
            WHERE e.guild_workspace_id = ?
              AND e.event_type IN ({placeholders})
              AND (
                e.guild_operation_id IS NULL
                OR o.status IS NULL
                OR o.status != 'archived'
              )
            ORDER BY e.occurred_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Discord workspace config
# ---------------------------------------------------------------------------

def update_workspace_discord_config(
    db: sqlite3.Connection,
    workspace_id: str,
    discord_guild_id: str | None,
    announcement_channel_id: str | None,
    officer_channel_id: str | None,
    auto_dispatch: bool = False,
    reminders_enabled: bool = False,
) -> None:
    """Set Discord linking fields on a workspace. Pass None to clear a field."""
    db.execute(
        """
        UPDATE guild_workspaces
        SET discord_guild_id                = :discord_guild_id,
            discord_announcement_channel_id = :announcement_channel_id,
            discord_officer_channel_id      = :officer_channel_id,
            discord_auto_dispatch           = :auto_dispatch,
            discord_reminders_enabled       = :reminders_enabled,
            updated_at                      = :updated_at
        WHERE id = :id
        """,
        {
            "id": workspace_id,
            "discord_guild_id": discord_guild_id,
            "announcement_channel_id": announcement_channel_id,
            "officer_channel_id": officer_channel_id,
            "auto_dispatch": 1 if auto_dispatch else 0,
            "reminders_enabled": 1 if reminders_enabled else 0,
            "updated_at": _now(),
        },
    )


def get_workspace_by_discord_guild_id(
    db: sqlite3.Connection,
    discord_guild_id: str,
) -> dict | None:
    """Look up a workspace by its linked Discord server ID."""
    return _row(
        db.execute(
            "SELECT * FROM guild_workspaces WHERE discord_guild_id = ?",
            (discord_guild_id,),
        ).fetchone()
    )


def set_workspace_discord_guild_id(
    db: sqlite3.Connection,
    workspace_id: str,
    discord_guild_id: str,
    discord_provisioned_at: str,
) -> None:
    """
    Set discord_guild_id and discord_provisioned_at on a workspace row.

    Called from ensure_workspace_for_discord_guild within the same transaction
    as insert_workspace so the two writes are atomic.  discord_provisioned_at
    records that the workspace was created automatically by the bot.
    """
    db.execute(
        """
        UPDATE guild_workspaces
        SET discord_guild_id       = ?,
            discord_provisioned_at = ?,
            updated_at             = ?
        WHERE id = ?
        """,
        (discord_guild_id, discord_provisioned_at, discord_provisioned_at, workspace_id),
    )


# ---------------------------------------------------------------------------
# Discord guild installs  (audit log of bot join/rejoin events)
# ---------------------------------------------------------------------------

def get_discord_guild_install(
    db: sqlite3.Connection,
    discord_guild_id: str,
) -> dict | None:
    """Look up the install audit record for a given Discord guild snowflake."""
    return _row(
        db.execute(
            "SELECT * FROM discord_guild_installs WHERE discord_guild_id = ?",
            (discord_guild_id,),
        ).fetchone()
    )


def upsert_discord_guild_install(
    db: sqlite3.Connection,
    discord_guild_id: str,
    guild_name: str,
    guild_workspace_id: str,
    discord_guild_owner_id: str | None = None,
) -> None:
    """
    Insert a new install record or increment the re-join counter.

    ON CONFLICT(discord_guild_id): update guild_name (server may be renamed),
    increment install_count, refresh installed_at, and update owner_id using
    COALESCE so an existing non-null value is kept when the new value is NULL.
    created_at is never touched after the initial insert.
    """
    now = _now()
    db.execute(
        """
        INSERT INTO discord_guild_installs
            (id, discord_guild_id, guild_name, guild_workspace_id,
             discord_guild_owner_id, install_count, installed_at, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(discord_guild_id) DO UPDATE SET
            guild_name             = excluded.guild_name,
            install_count          = discord_guild_installs.install_count + 1,
            installed_at           = excluded.installed_at,
            discord_guild_owner_id = COALESCE(
                                         excluded.discord_guild_owner_id,
                                         discord_guild_installs.discord_guild_owner_id
                                     )
        """,
        (str(uuid.uuid4()), discord_guild_id, guild_name, guild_workspace_id,
         discord_guild_owner_id, now, now),
    )


def get_discord_identity_for_user(
    db: sqlite3.Connection,
    user_id: str,
) -> dict | None:
    """
    Return the user_auth_identities row for auth_provider='discord', or None.

    Primary: look up user_auth_identities (the normalised identity table).
    Fallback: check users.auth_provider for pure Discord users created before
    the user_auth_identities backfill migration (legacy path).
    """
    row = db.execute(
        """
        SELECT * FROM user_auth_identities
        WHERE user_id = ? AND auth_provider = 'discord'
        """,
        (user_id,),
    ).fetchone()
    if row:
        return _row(row)
    # Fallback: pure Discord user whose identity pre-dates the backfill.
    user_row = db.execute(
        "SELECT * FROM users WHERE id = ? AND auth_provider = 'discord'",
        (user_id,),
    ).fetchone()
    if user_row:
        u = dict(user_row)
        return {
            "user_id":          u["id"],
            "auth_provider":    "discord",
            "provider_user_id": u["provider_user_id"],
        }
    return None


def grant_workspace_owner_if_unclaimed(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    user_id: str,
    now: str,
) -> bool:
    """
    Atomically insert an owner membership only if no owner row exists.

    Uses INSERT INTO ... SELECT ... WHERE NOT EXISTS to avoid a read-then-write
    race.  The SELECT and INSERT are evaluated as a single atomic operation by
    SQLite, so two concurrent callers cannot both succeed.

    Returns True if the membership was inserted (caller is now owner).
    Returns False if an owner row already existed (safe idempotency / race guard).
    """
    cursor = db.execute(
        """
        INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at)
        SELECT ?, ?, ?, 'owner', ?
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_members
            WHERE guild_workspace_id = ? AND role = 'owner'
        )
        """,
        (str(uuid.uuid4()), guild_workspace_id, user_id, now, guild_workspace_id),
    )
    return cursor.rowcount == 1


# ---------------------------------------------------------------------------
# Discord messages  (durable message-ID store for bot edit/delete)
# ---------------------------------------------------------------------------

def upsert_discord_message(db: sqlite3.Connection, record: dict) -> None:
    """
    Insert or replace a discord_messages row.
    Key: (guild_workspace_id, guild_operation_id, message_type).
    """
    db.execute(
        """
        INSERT INTO discord_messages
            (id, guild_workspace_id, guild_operation_id, message_type,
             discord_channel_id, discord_message_id, discord_guild_id,
             posted_at, last_edited_at, is_deleted)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :message_type,
             :discord_channel_id, :discord_message_id, :discord_guild_id,
             :posted_at, :last_edited_at, :is_deleted)
        ON CONFLICT (guild_workspace_id, guild_operation_id, message_type)
        DO UPDATE SET
            discord_message_id = excluded.discord_message_id,
            discord_channel_id = excluded.discord_channel_id,
            discord_guild_id   = excluded.discord_guild_id,
            last_edited_at     = excluded.last_edited_at,
            is_deleted         = excluded.is_deleted
        """,
        record,
    )


def get_discord_message(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    message_type: str,
) -> dict | None:
    return _row(
        db.execute(
            """
            SELECT * FROM discord_messages
            WHERE guild_workspace_id = ?
              AND guild_operation_id = ?
              AND message_type = ?
            """,
            (guild_workspace_id, guild_operation_id, message_type),
        ).fetchone()
    )


def mark_discord_message_deleted(db: sqlite3.Connection, record_id: str) -> None:
    db.execute(
        "UPDATE discord_messages SET is_deleted = 1 WHERE id = ?",
        (record_id,),
    )


# ---------------------------------------------------------------------------
# Discord dispatch failures  (retry tracking for outbound Discord calls)
# ---------------------------------------------------------------------------

def upsert_discord_metadata(db: sqlite3.Connection, record: dict) -> None:
    """
    Insert or replace a discord_metadata_cache row.

    record must contain:
      id, guild_workspace_id, entity_type, discord_entity_id,
      name, extra_json, fetched_at

    The UNIQUE constraint (guild_workspace_id, entity_type, discord_entity_id)
    ensures only one row per entity per workspace.  On conflict the full row
    is replaced so fetched_at and name are always current.
    """
    db.execute(
        """
        INSERT INTO discord_metadata_cache
            (id, guild_workspace_id, entity_type, discord_entity_id,
             name, extra_json, fetched_at)
        VALUES
            (:id, :guild_workspace_id, :entity_type, :discord_entity_id,
             :name, :extra_json, :fetched_at)
        ON CONFLICT (guild_workspace_id, entity_type, discord_entity_id)
        DO UPDATE SET
            name       = excluded.name,
            extra_json = excluded.extra_json,
            fetched_at = excluded.fetched_at
        """,
        record,
    )


def get_discord_metadata(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    entity_type: str,
    discord_entity_id: str,
) -> dict | None:
    """Return a single discord_metadata_cache row, or None."""
    return _row(
        db.execute(
            """
            SELECT * FROM discord_metadata_cache
            WHERE guild_workspace_id = ?
              AND entity_type = ?
              AND discord_entity_id = ?
            """,
            (guild_workspace_id, entity_type, discord_entity_id),
        ).fetchone()
    )


def get_discord_metadata_map(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> dict[str, dict]:
    """
    Return all discord_metadata_cache rows for a workspace as a dict
    keyed by discord_entity_id (snowflake).

    Used by routes to build the `discord_meta` template context variable
    in a single query rather than N per-entity lookups.
    """
    rows = _rows(
        db.execute(
            """
            SELECT * FROM discord_metadata_cache
            WHERE guild_workspace_id = ?
            """,
            (guild_workspace_id,),
        ).fetchall()
    )
    return {r["discord_entity_id"]: r for r in rows}


def insert_discord_dispatch_failure(db: sqlite3.Connection, record: dict) -> None:
    db.execute(
        """
        INSERT INTO discord_dispatch_failures
            (id, guild_workspace_id, guild_operation_id, event_type,
             entity_id, error_code, error_message, attempted_at,
             retry_count, status, payload_json, next_attempt_at)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :event_type,
             :entity_id, :error_code, :error_message, :attempted_at,
             :retry_count, :status, :payload_json, :next_attempt_at)
        """,
        record,
    )


def get_pending_discord_dispatch_failures(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> list[dict]:
    """Workspace-scoped query — used by the settings UI / route layer."""
    return _rows(
        db.execute(
            """
            SELECT * FROM discord_dispatch_failures
            WHERE guild_workspace_id = ? AND status = 'pending_retry'
            ORDER BY attempted_at
            """,
            (guild_workspace_id,),
        ).fetchall()
    )


def get_pending_dispatch_failures_due(
    db: sqlite3.Connection,
    now_iso: str,
) -> list[dict]:
    """
    Return all pending_retry rows whose backoff window has expired.

    Cross-workspace query used by the scheduler job.
    next_attempt_at is compared lexicographically — valid because ISO-8601
    UTC strings sort correctly without parsing.
    An empty next_attempt_at (legacy rows before this slice) is treated as
    immediately due.
    """
    return _rows(
        db.execute(
            """
            SELECT * FROM discord_dispatch_failures
            WHERE status = 'pending_retry'
              AND (next_attempt_at = '' OR next_attempt_at <= ?)
            ORDER BY next_attempt_at
            """,
            (now_iso,),
        ).fetchall()
    )


def resolve_dispatch_failure(db: sqlite3.Connection, failure_id: str, note: str) -> None:
    """Mark a dispatch failure row as resolved."""
    db.execute(
        "UPDATE discord_dispatch_failures SET status = 'resolved', error_message = ? WHERE id = ?",
        (note[:500], failure_id),
    )


def bump_dispatch_failure(
    db: sqlite3.Connection,
    failure_id: str,
    new_retry_count: int,
    next_attempt_at: str,
    error_message: str,
) -> None:
    """Increment retry_count and schedule the next backoff window."""
    db.execute(
        """
        UPDATE discord_dispatch_failures
        SET retry_count     = ?,
            next_attempt_at = ?,
            error_message   = ?,
            attempted_at    = ?
        WHERE id = ?
        """,
        (new_retry_count, next_attempt_at, error_message[:500], next_attempt_at, failure_id),
    )


def exhaust_dispatch_failure(
    db: sqlite3.Connection,
    failure_id: str,
    final_retry_count: int,
    error_message: str,
) -> None:
    """Set status=exhausted after all retry attempts are spent."""
    db.execute(
        """
        UPDATE discord_dispatch_failures
        SET status      = 'exhausted',
            retry_count = ?,
            error_message = ?
        WHERE id = ?
        """,
        (final_retry_count, error_message[:500], failure_id),
    )


# ---------------------------------------------------------------------------
# Scheduler runs  (observability log)
# ---------------------------------------------------------------------------

def insert_scheduler_run(db: sqlite3.Connection, record: dict) -> None:
    """Write the initial 'running' row for a scheduler job execution."""
    db.execute(
        """
        INSERT INTO scheduler_runs
            (id, job_name, started_at, finished_at, status, result_json, error_message)
        VALUES
            (:id, :job_name, :started_at, :finished_at, :status, :result_json, :error_message)
        """,
        record,
    )


def update_scheduler_run_finished(
    db: sqlite3.Connection,
    run_id: str,
    finished_at: str,
    status: str,
    result_json: str,
    error_message: str | None,
) -> None:
    """Update a scheduler_runs row after the job completes or errors."""
    db.execute(
        """
        UPDATE scheduler_runs
        SET finished_at   = ?,
            status        = ?,
            result_json   = ?,
            error_message = ?
        WHERE id = ?
        """,
        (finished_at, status, result_json, error_message, run_id),
    )


def get_scheduler_run(db: sqlite3.Connection, run_id: str) -> dict | None:
    return _row(
        db.execute(
            "SELECT * FROM scheduler_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    )


def get_recent_scheduler_runs(db: sqlite3.Connection, limit: int = 60) -> list[dict]:
    """
    Return the most recent scheduler_runs rows ordered by started_at DESC, id DESC.

    Stable secondary ordering by id prevents non-deterministic results when two
    jobs start within the same second (unlikely but possible on fast hardware).
    limit=60 covers ~5 hours of history at the default 5-minute poll interval.
    """
    return _rows(
        db.execute(
            """
            SELECT * FROM scheduler_runs
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    )


def get_latest_scheduler_run(db: sqlite3.Connection) -> dict | None:
    """Return the single most recent scheduler_runs row, or None."""
    return _row(
        db.execute(
            "SELECT * FROM scheduler_runs ORDER BY started_at DESC, id DESC LIMIT 1",
        ).fetchone()
    )


def get_stuck_scheduler_runs(db: sqlite3.Connection, cutoff_ts: str) -> list[dict]:
    """
    Return rows that appear to be stuck: status='running', finished_at IS NULL,
    and started_at older than cutoff_ts.

    cutoff_ts is an ISO-8601 UTC string: now - SCHEDULER_STUCK_THRESHOLD_MINUTES.
    """
    return _rows(
        db.execute(
            """
            SELECT * FROM scheduler_runs
            WHERE status = 'running'
              AND finished_at IS NULL
              AND started_at < ?
            ORDER BY started_at DESC, id DESC
            """,
            (cutoff_ts,),
        ).fetchall()
    )


def list_pending_dispatch_failures_for_workspace(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    limit: int = 50,
) -> list[dict]:
    """
    Return pending_retry rows for one workspace, ordered for the UI:
      next_attempt_at ASC (soonest-due first),
      attempted_at ASC (oldest-first as tiebreak),
      id ASC (deterministic final tiebreak).

    Empty-string next_attempt_at (legacy rows written before the backoff
    column was added) sorts before any real ISO-8601 timestamp, so those
    rows appear first — they are already due.

    Limited to `limit` rows to keep the page fast.  The count badge always
    reflects the true total.
    """
    return _rows(
        db.execute(
            """
            SELECT * FROM discord_dispatch_failures
            WHERE guild_workspace_id = ? AND status = 'pending_retry'
            ORDER BY next_attempt_at ASC, attempted_at ASC, id ASC
            LIMIT ?
            """,
            (guild_workspace_id, limit),
        ).fetchall()
    )


def count_pending_dispatch_failures(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> int:
    """
    Count discord_dispatch_failures rows in status='pending_retry' for one
    workspace.  Used by the scheduler status page to show per-workspace backlog.
    """
    row = db.execute(
        """
        SELECT COUNT(*) FROM discord_dispatch_failures
        WHERE guild_workspace_id = ? AND status = 'pending_retry'
        """,
        (guild_workspace_id,),
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Global health / diagnostics queries
# ---------------------------------------------------------------------------

def get_global_pending_retry_count(db: sqlite3.Connection) -> int:
    """
    Count discord_dispatch_failures rows with status='pending_retry' across
    all workspaces.  Used by the /health endpoint.
    """
    row = db.execute(
        "SELECT COUNT(*) FROM discord_dispatch_failures WHERE status = 'pending_retry'"
    ).fetchone()
    return row[0] if row else 0


def get_recent_error_run_count(
    db: sqlite3.Connection,
    hours: int = 24,
) -> int:
    """
    Count scheduler_runs rows with status='error' in the last ``hours`` hours.
    Used by the /health endpoint and diagnostics page.
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat()
    row = db.execute(
        "SELECT COUNT(*) FROM scheduler_runs WHERE status = 'error' AND started_at >= ?",
        (cutoff,),
    ).fetchone()
    return row[0] if row else 0


def get_last_scheduler_run_at(db: sqlite3.Connection) -> str | None:
    """
    Return the started_at of the most recent scheduler_runs row, or None.
    Used by the /health endpoint as a lightweight heartbeat timestamp.
    """
    row = db.execute(
        "SELECT started_at FROM scheduler_runs ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Workspace helpers for scheduler jobs
# ---------------------------------------------------------------------------

def get_workspaces_needing_metadata_refresh(
    db: sqlite3.Connection,
    threshold_at: str,
) -> list[dict]:
    """
    Return workspaces where Discord metadata is stale or missing.

    A workspace qualifies if:
    - discord_guild_id IS NOT NULL (Discord is configured), AND
    - no cache rows exist, OR the oldest cache row is older than threshold_at.

    threshold_at is an ISO-8601 UTC string: now - METADATA_STALE_HOURS.
    ISO-8601 strings compare correctly as text in SQLite.
    """
    return _rows(
        db.execute(
            """
            SELECT w.*
            FROM guild_workspaces w
            WHERE w.discord_guild_id IS NOT NULL
              AND (
                  NOT EXISTS (
                      SELECT 1 FROM discord_metadata_cache c
                      WHERE c.guild_workspace_id = w.id
                  )
                  OR EXISTS (
                      SELECT 1 FROM discord_metadata_cache c
                      WHERE c.guild_workspace_id = w.id
                        AND c.fetched_at < ?
                  )
              )
            ORDER BY w.id
            """,
            (threshold_at,),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Operation reminder deliveries
# ---------------------------------------------------------------------------

def get_operations_eligible_for_reminders(
    db: sqlite3.Connection,
    now_iso: str,
) -> list[dict]:
    """
    Return operations eligible to receive reminder posts.

    Eligibility criteria:
    - status IN ('planning', 'locked')                — only active ops
    - scheduled_start_at > now_iso                    — never fire after start
    - workspace discord_guild_id IS NOT NULL          — Discord linked
    - workspace discord_reminders_enabled = 1         — workspace opted in
    - workspace has announcement OR officer channel   — somewhere to post

    Returns full guild_operations rows joined with workspace discord fields.
    """
    return _rows(
        db.execute(
            """
            SELECT o.*, w.discord_guild_id, w.discord_announcement_channel_id,
                   w.discord_officer_channel_id, w.discord_reminders_enabled
            FROM guild_operations o
            JOIN guild_workspaces w ON w.id = o.guild_workspace_id
            WHERE o.status IN ('planning', 'locked')
              AND o.scheduled_start_at > ?
              AND w.discord_guild_id IS NOT NULL
              AND w.discord_reminders_enabled = 1
              AND (
                  w.discord_announcement_channel_id IS NOT NULL
                  OR w.discord_officer_channel_id IS NOT NULL
              )
            ORDER BY o.scheduled_start_at
            """,
            (now_iso,),
        ).fetchall()
    )


def get_reminder_delivery(
    db: sqlite3.Connection,
    guild_operation_id: str,
    reminder_window: str,
    guild_workspace_id: str,
) -> dict | None:
    """Return the delivery row for (operation, window), or None."""
    return _row(
        db.execute(
            """
            SELECT * FROM operation_reminder_deliveries
            WHERE guild_operation_id = ?
              AND reminder_window = ?
              AND guild_workspace_id = ?
            """,
            (guild_operation_id, reminder_window, guild_workspace_id),
        ).fetchone()
    )


def try_claim_reminder_delivery(
    db: sqlite3.Connection,
    guild_operation_id: str,
    reminder_window: str,
    guild_workspace_id: str,
    now_iso: str,
    stale_cutoff_iso: str,
) -> str:
    """
    Ensure a delivery row exists for (operation, window), then attempt an
    atomic claim.

    Flow:
      1. INSERT OR IGNORE — creates the row in 'pending' if it doesn't exist.
      2. Read the current row state.
      3. If already 'sent' or 'skipped' → return 'already_done'.
      4. UPDATE status='claimed' WHERE (status='pending')
           OR (status='claimed' AND claimed_at <= stale_cutoff_iso)
         rowcount=1 → 'claimed'; rowcount=0 → 'busy'.

    Returns one of: 'claimed' | 'already_done' | 'busy'.
    """
    # Step 1: ensure row exists
    db.execute(
        """
        INSERT OR IGNORE INTO operation_reminder_deliveries
            (id, guild_workspace_id, guild_operation_id, reminder_window,
             status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (str(uuid.uuid4()), guild_workspace_id, guild_operation_id,
         reminder_window, now_iso),
    )

    # Step 2: read current state
    row = db.execute(
        """
        SELECT id, status FROM operation_reminder_deliveries
        WHERE guild_operation_id = ?
          AND reminder_window = ?
          AND guild_workspace_id = ?
        """,
        (guild_operation_id, reminder_window, guild_workspace_id),
    ).fetchone()

    if not row:
        return "busy"  # should not happen after INSERT OR IGNORE

    if row["status"] in ("sent", "skipped"):
        return "already_done"

    # Step 3: atomic claim (handles both fresh pending and stale claimed rows)
    cursor = db.execute(
        """
        UPDATE operation_reminder_deliveries
        SET status = 'claimed', claimed_at = ?
        WHERE id = ?
          AND (
              status = 'pending'
              OR (status = 'claimed' AND claimed_at <= ?)
          )
        """,
        (now_iso, row["id"], stale_cutoff_iso),
    )

    return "claimed" if cursor.rowcount > 0 else "busy"


def finalize_reminder_delivery(
    db: sqlite3.Connection,
    guild_operation_id: str,
    reminder_window: str,
    guild_workspace_id: str,
    sent_at: str,
) -> None:
    """Mark a claimed delivery row as sent."""
    db.execute(
        """
        UPDATE operation_reminder_deliveries
        SET status = 'sent', sent_at = ?
        WHERE guild_operation_id = ?
          AND reminder_window = ?
          AND guild_workspace_id = ?
          AND status = 'claimed'
        """,
        (sent_at, guild_operation_id, reminder_window, guild_workspace_id),
    )


def skip_reminder_delivery(
    db: sqlite3.Connection,
    guild_operation_id: str,
    reminder_window: str,
    guild_workspace_id: str,
    skipped_at: str,
    reason: str,
) -> None:
    """
    Mark a delivery row as skipped.

    Skipped rows are final — they are never retried.  This is called when:
    - The operation is no longer eligible (status changed, Discord unconfigured).
    - The operation start time has passed (grace window closed).
    - No Discord channel is available to post to.
    """
    db.execute(
        """
        INSERT OR IGNORE INTO operation_reminder_deliveries
            (id, guild_workspace_id, guild_operation_id, reminder_window,
             status, created_at)
        VALUES (?, ?, ?, ?, 'skipped', ?)
        """,
        (str(uuid.uuid4()), guild_workspace_id, guild_operation_id,
         reminder_window, skipped_at),
    )
    db.execute(
        """
        UPDATE operation_reminder_deliveries
        SET status = 'skipped', skipped_at = ?, skip_reason = ?
        WHERE guild_operation_id = ?
          AND reminder_window = ?
          AND guild_workspace_id = ?
          AND status != 'sent'
        """,
        (skipped_at, reason, guild_operation_id, reminder_window,
         guild_workspace_id),
    )


# ---------------------------------------------------------------------------
# Player game identities  (Albion character claims)
# ---------------------------------------------------------------------------

def insert_player_game_identity(db: sqlite3.Connection, record: dict) -> None:
    """Insert a new player_game_identities row."""
    db.execute(
        """
        INSERT INTO player_game_identities
            (id, guild_workspace_id, user_id, game, albion_player_id,
             character_name, verification_status, claimed_at,
             reviewed_at, reviewed_by, review_note, created_at)
        VALUES
            (:id, :guild_workspace_id, :user_id, :game, :albion_player_id,
             :character_name, :verification_status, :claimed_at,
             :reviewed_at, :reviewed_by, :review_note, :created_at)
        """,
        record,
    )


def get_player_game_identity_by_id(
    db: sqlite3.Connection,
    identity_id: str,
    guild_workspace_id: str,
) -> dict | None:
    """Return a claim row by primary key, scoped to workspace."""
    row = db.execute(
        """
        SELECT * FROM player_game_identities
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (identity_id, guild_workspace_id),
    ).fetchone()
    return _row(row)


def get_player_game_identity_for_user(
    db: sqlite3.Connection,
    user_id: str,
    guild_workspace_id: str,
    game: str = "albion",
) -> dict | None:
    """Return the claim row for a specific user+workspace+game (at most one)."""
    row = db.execute(
        """
        SELECT * FROM player_game_identities
        WHERE user_id = ? AND guild_workspace_id = ? AND game = ?
        """,
        (user_id, guild_workspace_id, game),
    ).fetchone()
    return _row(row)


def get_player_game_identity_by_albion_id(
    db: sqlite3.Connection,
    albion_player_id: str,
    guild_workspace_id: str,
) -> dict | None:
    """Return the claim row for a specific albion_player_id in a workspace."""
    row = db.execute(
        """
        SELECT * FROM player_game_identities
        WHERE albion_player_id = ? AND guild_workspace_id = ?
        """,
        (albion_player_id, guild_workspace_id),
    ).fetchone()
    return _row(row)


def list_player_game_identities_for_workspace(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> list[dict]:
    """Return all identity claims for a workspace, ordered by created_at."""
    rows = db.execute(
        """
        SELECT * FROM player_game_identities
        WHERE guild_workspace_id = ?
        ORDER BY created_at ASC
        """,
        (guild_workspace_id,),
    ).fetchall()
    return _rows(rows)


def list_player_game_identities_for_user(
    db: sqlite3.Connection,
    user_id: str,
) -> list[dict]:
    """Return all identity claims for a user across all workspaces."""
    rows = db.execute(
        """
        SELECT * FROM player_game_identities
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    ).fetchall()
    return _rows(rows)


def delete_player_game_identity(db: sqlite3.Connection, identity_id: str) -> None:
    """Hard-delete an identity claim row."""
    db.execute(
        "DELETE FROM player_game_identities WHERE id = ?",
        (identity_id,),
    )


def update_player_game_identity_status(
    db: sqlite3.Connection,
    identity_id: str,
    status: str,
    reviewed_by: str,
    reviewed_at: str,
    review_note: str | None = None,
) -> None:
    """
    Update verification_status, reviewed_by, reviewed_at, review_note.

    Only allowed transitions:
      pending  → approved
      pending  → rejected
    Business rule enforcement is the responsibility of the use case.
    """
    db.execute(
        """
        UPDATE player_game_identities
        SET verification_status = ?,
            reviewed_by         = ?,
            reviewed_at         = ?,
            review_note         = ?
        WHERE id = ?
        """,
        (status, reviewed_by, reviewed_at, review_note, identity_id),
    )


# ---------------------------------------------------------------------------
# Albion character cache
# ---------------------------------------------------------------------------

def upsert_albion_character_cache(db: sqlite3.Connection, record: dict) -> None:
    """
    Insert or update an Albion character cache row.

    Keyed by albion_player_id; the primary key `id` is ignored on conflict
    (the existing row's id is preserved).

    NEVER touches player_game_identities or verification state.
    """
    db.execute(
        """
        INSERT INTO albion_character_cache
            (id, albion_player_id, character_name, guild_id, guild_name,
             kill_fame, death_fame, extra_json, fetched_at)
        VALUES
            (:id, :albion_player_id, :character_name, :guild_id, :guild_name,
             :kill_fame, :death_fame, :extra_json, :fetched_at)
        ON CONFLICT (albion_player_id) DO UPDATE SET
            character_name = excluded.character_name,
            guild_id       = excluded.guild_id,
            guild_name     = excluded.guild_name,
            kill_fame      = excluded.kill_fame,
            death_fame     = excluded.death_fame,
            extra_json     = excluded.extra_json,
            fetched_at     = excluded.fetched_at
        """,
        record,
    )


def get_albion_character_cache(
    db: sqlite3.Connection,
    albion_player_id: str,
) -> dict | None:
    """Return a single cache row by albion_player_id."""
    row = db.execute(
        "SELECT * FROM albion_character_cache WHERE albion_player_id = ?",
        (albion_player_id,),
    ).fetchone()
    return _row(row)


def get_albion_character_cache_many(
    db: sqlite3.Connection,
    albion_player_ids: list[str],
) -> list[dict]:
    """Batch-fetch cache rows for a list of player IDs."""
    if not albion_player_ids:
        return []
    placeholders = ", ".join("?" * len(albion_player_ids))
    rows = db.execute(
        f"SELECT * FROM albion_character_cache WHERE albion_player_id IN ({placeholders})",
        albion_player_ids,
    ).fetchall()
    return _rows(rows)


# ---------------------------------------------------------------------------
# Payout ledger entries
# ---------------------------------------------------------------------------

def insert_payout_ledger_entry(db: sqlite3.Connection, record: dict) -> None:
    """Insert a new payout_ledger_entries row."""
    db.execute(
        """
        INSERT INTO payout_ledger_entries
            (id, guild_workspace_id, guild_operation_id, participant_id,
             entry_type, amount_silver, note, status,
             created_by_user_id, created_at, updated_at,
             voided_at, voided_by_user_id)
        VALUES
            (:id, :guild_workspace_id, :guild_operation_id, :participant_id,
             :entry_type, :amount_silver, :note, :status,
             :created_by_user_id, :created_at, :updated_at,
             :voided_at, :voided_by_user_id)
        """,
        record,
    )


def get_payout_ledger_entry(
    db: sqlite3.Connection,
    entry_id: str,
    guild_workspace_id: str,
) -> dict | None:
    """Fetch a single ledger entry, enforcing workspace scoping."""
    return _row(
        db.execute(
            """
            SELECT * FROM payout_ledger_entries
            WHERE id = ? AND guild_workspace_id = ?
            """,
            (entry_id, guild_workspace_id),
        ).fetchone()
    )


def list_payout_ledger_entries_for_operation(
    db: sqlite3.Connection,
    guild_operation_id: str,
    guild_workspace_id: str,
) -> list[dict]:
    """
    Return all non-voided ledger entries for an operation, ordered by
    created_at ASC (oldest first).  Voided entries are included so officers
    can see the full audit trail — callers may filter if needed.
    """
    return _rows(
        db.execute(
            """
            SELECT * FROM payout_ledger_entries
            WHERE guild_operation_id = ? AND guild_workspace_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (guild_operation_id, guild_workspace_id),
        ).fetchall()
    )


def list_payout_ledger_entries_for_participant(
    db: sqlite3.Connection,
    participant_id: str,
    guild_workspace_id: str,
) -> list[dict]:
    """
    Return all ledger entries for a participant across all operations
    in the workspace, ordered by created_at DESC (newest first).
    """
    return _rows(
        db.execute(
            """
            SELECT * FROM payout_ledger_entries
            WHERE participant_id = ? AND guild_workspace_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (participant_id, guild_workspace_id),
        ).fetchall()
    )


def update_payout_ledger_entry_draft(
    db: sqlite3.Connection,
    entry_id: str,
    guild_workspace_id: str,
    amount_silver: int,
    note: str | None,
    updated_at: str,
) -> int:
    """
    Update the amount_silver and note on a draft entry.
    Returns rowcount (0 = not found in workspace).
    Callers must verify status='draft' before calling.
    """
    cursor = db.execute(
        """
        UPDATE payout_ledger_entries
        SET amount_silver = ?,
            note          = ?,
            updated_at    = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (amount_silver, note, updated_at, entry_id, guild_workspace_id),
    )
    return cursor.rowcount


def approve_payout_ledger_entry(
    db: sqlite3.Connection,
    entry_id: str,
    guild_workspace_id: str,
    updated_at: str,
) -> int:
    """
    Transition status draft → approved.
    Returns rowcount (0 = not found or already past draft).
    Callers must validate current status before calling.
    """
    cursor = db.execute(
        """
        UPDATE payout_ledger_entries
        SET status     = 'approved',
            updated_at = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (updated_at, entry_id, guild_workspace_id),
    )
    return cursor.rowcount


def void_payout_ledger_entry(
    db: sqlite3.Connection,
    entry_id: str,
    guild_workspace_id: str,
    voided_at: str,
    voided_by_user_id: str,
) -> int:
    """
    Set status = 'voided' and record who voided it.
    Returns rowcount (0 = not found in workspace).
    Callers must verify the entry is voidable before calling.
    """
    cursor = db.execute(
        """
        UPDATE payout_ledger_entries
        SET status            = 'voided',
            voided_at         = ?,
            voided_by_user_id = ?,
            updated_at        = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (voided_at, voided_by_user_id, voided_at, entry_id, guild_workspace_id),
    )
    return cursor.rowcount


def mark_payout_ledger_entry_paid(
    db: sqlite3.Connection,
    entry_id: str,
    guild_workspace_id: str,
    paid_at: str,
    paid_by_user_id: str,
) -> int:
    """
    Transition status approved → paid and record paid_at / paid_by_user_id.
    Returns rowcount (0 = not found in workspace).
    Callers must verify the entry is in 'approved' status before calling.
    """
    cursor = db.execute(
        """
        UPDATE payout_ledger_entries
        SET status          = 'paid',
            paid_at         = ?,
            paid_by_user_id = ?,
            updated_at      = ?
        WHERE id = ? AND guild_workspace_id = ?
        """,
        (paid_at, paid_by_user_id, paid_at, entry_id, guild_workspace_id),
    )
    return cursor.rowcount


def get_ledger_totals_for_operation(
    db: sqlite3.Connection,
    guild_operation_id: str,
    guild_workspace_id: str,
) -> dict:
    """
    Return per-status aggregates for a single operation's ledger entries.

    All amounts are summed as integers (silver).  Voided rows are counted but
    their amounts are excluded from 'active_total'.

    Returns a dict with keys:
      draft_count, draft_total
      approved_count, approved_total
      paid_count, paid_total
      voided_count                 (no voided_total — excluded by design)
      active_count                 (draft + approved + paid)
      active_total                 (sum of draft + approved + paid amounts)
    """
    rows = db.execute(
        """
        SELECT status,
               COUNT(*)          AS cnt,
               COALESCE(SUM(amount_silver), 0) AS total
        FROM payout_ledger_entries
        WHERE guild_operation_id = ? AND guild_workspace_id = ?
        GROUP BY status
        """,
        (guild_operation_id, guild_workspace_id),
    ).fetchall()

    by_status: dict[str, dict] = {}
    for r in rows:
        by_status[r["status"]] = {"count": r["cnt"], "total": r["total"]}

    def _get(status: str) -> tuple[int, int]:
        s = by_status.get(status, {})
        return s.get("count", 0), s.get("total", 0)

    dc, dt = _get("draft")
    ac, at = _get("approved")
    pc, pt = _get("paid")
    vc, _  = _get("voided")

    return {
        "draft_count":    dc,
        "draft_total":    dt,
        "approved_count": ac,
        "approved_total": at,
        "paid_count":     pc,
        "paid_total":     pt,
        "voided_count":   vc,
        "active_count":   dc + ac + pc,
        "active_total":   dt + at + pt,
    }


def count_pending_ledger_entries_for_workspace(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> int:
    """
    Count payout_ledger_entries in 'draft' or 'approved' status across all
    operations in the workspace.  Used by the dashboard attention section to
    surface entries that still need officer action (approval or payment).
    Voided and paid entries are excluded — they require no further action.
    """
    row = db.execute(
        """
        SELECT COUNT(*)
        FROM payout_ledger_entries
        WHERE guild_workspace_id = ?
          AND status IN ('draft', 'approved')
        """,
        (guild_workspace_id,),
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Workspace Albion Guilds  (Phase 11 — roster import)
# ---------------------------------------------------------------------------

def upsert_workspace_albion_guild(
    db: sqlite3.Connection,
    record: dict,
) -> None:
    """
    Insert a workspace_albion_guilds row, or update guild_name / alliance fields
    and last_imported_at on conflict.

    created_at is preserved from the original insert (not updated on conflict).
    """
    db.execute(
        """
        INSERT INTO workspace_albion_guilds
            (id, guild_workspace_id, albion_guild_id, guild_name,
             alliance_id, alliance_name, last_imported_at, created_at)
        VALUES
            (:id, :guild_workspace_id, :albion_guild_id, :guild_name,
             :alliance_id, :alliance_name, :last_imported_at, :created_at)
        ON CONFLICT (guild_workspace_id, albion_guild_id) DO UPDATE SET
            guild_name       = excluded.guild_name,
            alliance_id      = excluded.alliance_id,
            alliance_name    = excluded.alliance_name,
            last_imported_at = excluded.last_imported_at
        """,
        record,
    )


def get_workspace_albion_guild(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    albion_guild_id: str,
) -> dict | None:
    """Return a workspace_albion_guilds row by (workspace, albion_guild_id), or None."""
    return _row(
        db.execute(
            """
            SELECT * FROM workspace_albion_guilds
            WHERE guild_workspace_id = ? AND albion_guild_id = ?
            """,
            (guild_workspace_id, albion_guild_id),
        ).fetchone()
    )


def list_workspace_albion_guilds(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> list[dict]:
    """Return all linked Albion guilds for a workspace, ordered by guild_name."""
    return _rows(
        db.execute(
            """
            SELECT * FROM workspace_albion_guilds
            WHERE guild_workspace_id = ?
            ORDER BY guild_name
            """,
            (guild_workspace_id,),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Workspace Albion Players  (Phase 11 — roster import)
# ---------------------------------------------------------------------------

def upsert_workspace_albion_player(
    db: sqlite3.Connection,
    record: dict,
) -> None:
    """
    Insert a workspace_albion_players row, or update character_name /
    source_guild_id / last_seen_in_guild_at / updated_at on conflict.

    user_id and created_at are preserved from the original insert — never
    overwritten on re-import.  This preserves existing Ironkeep identity links.
    """
    db.execute(
        """
        INSERT INTO workspace_albion_players
            (id, guild_workspace_id, albion_player_id, character_name,
             user_id, source_guild_id, last_seen_in_guild_at,
             created_at, updated_at)
        VALUES
            (:id, :guild_workspace_id, :albion_player_id, :character_name,
             :user_id, :source_guild_id, :last_seen_in_guild_at,
             :created_at, :updated_at)
        ON CONFLICT (guild_workspace_id, albion_player_id) DO UPDATE SET
            character_name        = excluded.character_name,
            source_guild_id       = excluded.source_guild_id,
            last_seen_in_guild_at = excluded.last_seen_in_guild_at,
            updated_at            = excluded.updated_at
        """,
        record,
    )


def get_workspace_albion_player(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    albion_player_id: str,
) -> dict | None:
    """Return a workspace_albion_players row by (workspace, albion_player_id), or None."""
    return _row(
        db.execute(
            """
            SELECT * FROM workspace_albion_players
            WHERE guild_workspace_id = ? AND albion_player_id = ?
            """,
            (guild_workspace_id, albion_player_id),
        ).fetchone()
    )


def list_workspace_albion_players(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> list[dict]:
    """Return all imported Albion players for a workspace, ordered by character_name."""
    return _rows(
        db.execute(
            """
            SELECT p.*, g.guild_name AS source_guild_name
            FROM workspace_albion_players p
            LEFT JOIN workspace_albion_guilds g ON g.id = p.source_guild_id
            WHERE p.guild_workspace_id = ?
            ORDER BY p.character_name
            """,
            (guild_workspace_id,),
        ).fetchall()
    )


def get_existing_albion_player_ids(
    db: sqlite3.Connection,
    guild_workspace_id: str,
) -> set[str]:
    """Return the set of albion_player_ids already imported for this workspace."""
    rows = db.execute(
        "SELECT albion_player_id FROM workspace_albion_players WHERE guild_workspace_id = ?",
        (guild_workspace_id,),
    ).fetchall()
    return {row["albion_player_id"] for row in rows}


def link_workspace_albion_player_to_user(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    albion_player_id: str,
    user_id: str,
) -> bool:
    """
    Set workspace_albion_players.user_id for the matching imported player row,
    but ONLY if user_id is currently NULL.

    Linking rules (all enforced by the WHERE clause):
    - If no row exists for (guild_workspace_id, albion_player_id): no-op, returns False.
    - If row exists with user_id IS NULL: links to user_id, returns True.
    - If row exists with user_id already set (same or different user): no-op, returns False.

    This means:
    - Idempotent if already linked (regardless of who it is linked to).
    - Never overwrites an existing link.
    - Callers should not rely on the return value for correctness — it is
      provided for observability only.
    """
    now = _now()
    cursor = db.execute(
        """
        UPDATE workspace_albion_players
        SET user_id    = ?,
            updated_at = ?
        WHERE guild_workspace_id = ?
          AND albion_player_id   = ?
          AND user_id IS NULL
        """,
        (user_id, now, guild_workspace_id, albion_player_id),
    )
    return cursor.rowcount > 0

