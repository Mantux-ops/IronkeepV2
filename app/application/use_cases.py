"""
Application use cases â€” transactional commands.

Rules:
- Each function opens exactly one transaction.
- Every state-changing command emits at least one OperationalEvent within
  the same transaction (no event = no commit).
- All cross-workspace access is prevented by filtering with guild_workspace_id
  in every repository query.
- Business rule violations raise errors from app.errors, never raw exceptions.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app import database, repositories
from app.domain import (
    albion_builds as albion_builds_domain,
    albion_compositions,
    attendance as attendance_domain,
    guild_operations,
    guild_workspace,
    mass_planner,
    operation_plans,
    operational_events,
    payout_ledger as payout_ledger_domain,
    readiness,
    scout_attendance as scout_attendance_domain,
    users,
    workspace_membership,
)
from app.domain.mass_planner import select_best_candidate
from app.errors import (
    ConflictError,
    NotFoundError,
    PermissionDenied,
    ValidationError,
    WorkspaceBoundaryViolation,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor_is_superadmin(db, user_id: str) -> bool:
    """True when *user_id* resolves to a platform super-admin (god-mode).

    Lets support/god-mode actions bypass the normal workspace membership and
    role checks inside use cases, mirroring the route-layer bypass.
    """
    from app.auth import superadmin
    return superadmin.is_superadmin(db, repositories.get_user_by_id(db, user_id))


# ---------------------------------------------------------------------------
# 0. Dev auth user
# ---------------------------------------------------------------------------

def _make_auth_identity(user_id: str, auth_provider: str, provider_user_id: str, now: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "auth_provider": auth_provider,
        "provider_user_id": provider_user_id,
        "created_at": now,
    }


def discord_oauth_login(discord_user_id: str, discord_username: str) -> dict:
    """
    Find or create an application user for a Discord OAuth-authenticated user.

    Rules:
    - Looks up by (auth_provider='discord', provider_user_id=discord_user_id)
      via user_auth_identities (primary) then users legacy columns (fallback).
    - discord_user_id is the stable Discord snowflake; it never changes.
    - display_name auto-update: only for pure discord users (no linked dev
      identity). Linked users retain their guild display_name.
    - If no user exists, a new users row + user_auth_identities row are created.
    - No workspace membership is granted automatically.
    - No merging with existing dev-auth users; they remain separate records
      until the user explicitly links via /auth/discord/link.
    """
    users.validate_display_name(discord_username)
    if not discord_user_id or not discord_user_id.strip():
        raise ValidationError("Discord user ID must not be empty.")

    with database.transaction() as db:
        existing = repositories.get_user_by_provider_identity(
            db, users.DISCORD_AUTH_PROVIDER, discord_user_id
        )
        if existing:
            # Suppress display_name update for linked users (those who also
            # have a dev identity row â€” their display_name is their guild name).
            identities = repositories.get_auth_identities_for_user(db, existing["id"])
            providers = {i["auth_provider"] for i in identities}
            is_linked = users.DEV_AUTH_PROVIDER in providers
            # If a Discord server nickname has been synced for this user, it is
            # authoritative (members set it to their in-game name) — never revert
            # display_name back to the global Discord name on login.
            has_synced_nick = (
                repositories.get_discord_member_nick_for_user(db, existing["id"])
                is not None
            )
            if not is_linked and not has_synced_nick \
                    and existing["display_name"] != discord_username:
                now = _now()
                db.execute(
                    "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
                    (discord_username, now, existing["id"]),
                )
                existing = repositories.get_user_by_id(db, existing["id"])
            return existing

        now = _now()
        user = {
            "id": str(uuid.uuid4()),
            "display_name": discord_username,
            "auth_provider": users.DISCORD_AUTH_PROVIDER,
            "provider_user_id": discord_user_id,
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_user(db, user)
        repositories.insert_user_auth_identity(
            db,
            _make_auth_identity(user["id"], users.DISCORD_AUTH_PROVIDER, discord_user_id, now),
        )

    return user


def sync_discord_guild_memberships(
    *,
    user_id: str,
    discord_guild_ids: list[str],
) -> dict:
    """Auto-grant workspace membership based on the user's Discord servers.

    For every Discord server (guild) the user belongs to that is linked to an
    Ironkeep workspace, ensure the user has a ``workspace_members`` row. This is
    how "being in the Discord server = access to the workspace" is realised.

    Rules / safety:
    - Only active workspaces are considered (soft-deleted ones are skipped, since
      ``get_workspace_by_discord_guild_id`` returns them but we filter here).
    - Idempotent: users already having a membership are left untouched, including
      their existing role (owners/officers are never demoted to 'member').
    - New members are added with role='member'.
    - Each new membership emits a WORKSPACE_MEMBER_DISCORD_AUTOJOINED audit event
      in the same transaction.

    Returns ``{"joined": [<workspace dict>, ...]}`` listing workspaces newly
    joined during this call (empty when nothing changed).
    """
    joined: list[dict] = []
    # De-duplicate and drop empties without changing behaviour for the caller.
    unique_ids = {gid.strip() for gid in (discord_guild_ids or []) if gid and gid.strip()}
    if not unique_ids:
        return {"joined": joined}

    now = _now()
    with database.transaction() as db:
        for guild_id in unique_ids:
            ws = repositories.get_workspace_by_discord_guild_id(db, guild_id)
            if not ws or ws.get("deleted_at"):
                continue
            if repositories.get_workspace_membership(db, ws["id"], user_id):
                continue

            membership = {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": ws["id"],
                "user_id": user_id,
                "role": "member",
                "created_at": now,
            }
            repositories.insert_workspace_member(db, membership)

            event = operational_events.make_event(
                guild_workspace_id=ws["id"],
                guild_operation_id=None,
                event_type=operational_events.WORKSPACE_MEMBER_DISCORD_AUTOJOINED,
                entity_type="workspace_member",
                entity_id=membership["id"],
                actor_type="user",
                actor_id=user_id,
                payload={"discord_guild_id": guild_id},
            )
            repositories.insert_operational_event(db, event)
            joined.append(ws)

    return {"joined": joined}


def dev_login_or_create_user(display_name: str) -> dict:
    """Find or create a local dev auth user for the given display name."""
    users.validate_display_name(display_name)
    provider_user_id = users.dev_provider_user_id(display_name)

    with database.transaction() as db:
        existing = repositories.get_user_by_provider_identity(
            db, users.DEV_AUTH_PROVIDER, provider_user_id
        )
        if existing:
            return existing

        now = _now()
        user = {
            "id": str(uuid.uuid4()),
            "display_name": display_name.strip(),
            "auth_provider": users.DEV_AUTH_PROVIDER,
            "provider_user_id": provider_user_id,
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_user(db, user)
        repositories.insert_user_auth_identity(
            db,
            _make_auth_identity(user["id"], users.DEV_AUTH_PROVIDER, provider_user_id, now),
        )

    return user


def link_discord_identity(user_id: str, discord_user_id: str) -> dict:
    """
    Link an existing dev-auth user account to a Discord OAuth identity.

    Rules:
    - Only users with a dev identity (auth_provider='dev' in users_auth_identities
      or legacy users.auth_provider == 'dev') may initiate linking.
    - users.auth_provider, users.provider_user_id, and users.display_name are
      never mutated â€” the link is expressed only in user_auth_identities.
    - Idempotent: calling twice with the same snowflake is a no-op.
    - ConflictError if the user already has a different discord identity linked.
    - ConflictError if another user with references claims the same snowflake.
    - Orphaned discord user (no references, no memberships) is deleted atomically
      in the same transaction to free the UNIQUE constraint before inserting the
      new link row.
    - Emits user.discord_linked per workspace the user is a member of.
      Audit-only, not dispatchable.
    - No workspace membership is created.
    """
    if not discord_user_id or not discord_user_id.strip():
        raise ValidationError("Discord user ID must not be empty.")
    discord_user_id = discord_user_id.strip()

    with database.transaction() as db:
        user = repositories.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundError(f"User '{user_id}' not found.")

        # Confirm the user has a dev identity (via identities table or legacy column).
        identities = repositories.get_auth_identities_for_user(db, user_id)
        identity_providers = {i["auth_provider"] for i in identities}
        has_dev_identity = (
            users.DEV_AUTH_PROVIDER in identity_providers
            or user["auth_provider"] == users.DEV_AUTH_PROVIDER
        )
        if not has_dev_identity:
            raise ConflictError(
                "Only accounts that were created with dev login can be linked to Discord. "
                "This account is already a Discord account."
            )

        # Check if this user already has a discord identity.
        existing_discord = next(
            (i for i in identities if i["auth_provider"] == users.DISCORD_AUTH_PROVIDER),
            None,
        )
        if existing_discord:
            if existing_discord["provider_user_id"] == discord_user_id:
                return user  # idempotent
            raise ConflictError(
                "This account is already linked to a different Discord identity. "
                "Unlinking is not yet supported."
            )

        # Check for a collision in user_auth_identities (another user owns that snowflake).
        collision = repositories.get_auth_identity(
            db, users.DISCORD_AUTH_PROVIDER, discord_user_id
        )
        if collision and collision["user_id"] != user_id:
            _handle_orphan_or_block(db, collision["user_id"])

        # Check legacy users.auth_provider/provider_user_id for the same snowflake.
        legacy_user = db.execute(
            "SELECT * FROM users WHERE auth_provider = ? AND provider_user_id = ? AND id != ?",
            (users.DISCORD_AUTH_PROVIDER, discord_user_id, user_id),
        ).fetchone()
        if legacy_user:
            legacy_id = dict(legacy_user)["id"]
            _handle_orphan_or_block(db, legacy_id)

        # Insert the link.
        now = _now()
        repositories.insert_user_auth_identity(
            db,
            _make_auth_identity(user_id, users.DISCORD_AUTH_PROVIDER, discord_user_id, now),
        )

        # Emit one user.discord_linked event per workspace membership.
        memberships = db.execute(
            "SELECT guild_workspace_id FROM workspace_members WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        for row in memberships:
            ws_id = dict(row)["guild_workspace_id"]
            event = operational_events.make_event(
                guild_workspace_id=ws_id,
                guild_operation_id=None,
                event_type=operational_events.USER_DISCORD_LINKED,
                entity_type="user",
                entity_id=user_id,
                actor_type="user",
                actor_id=user_id,
                payload={"discord_user_id": discord_user_id},
            )
            repositories.insert_operational_event(db, event)

        refreshed = repositories.get_user_by_id(db, user_id)

    return refreshed or user


def _handle_orphan_or_block(db, orphan_user_id: str) -> None:
    """
    Check if orphan_user_id is safe to delete (no workspace_members, no
    operational_events.actor_id rows).  Delete if safe; raise ConflictError
    if not.  Called within an existing transaction.
    """
    ref_count = repositories.count_user_references(db, orphan_user_id)
    if ref_count > 0:
        raise ConflictError(
            "This Discord account is already associated with another user "
            "that has workspace memberships or history. "
            "A workspace owner must manually reconcile before linking."
        )
    repositories.delete_user_and_identity(db, orphan_user_id)


# ---------------------------------------------------------------------------
# 1. Create GuildWorkspace
# ---------------------------------------------------------------------------

def create_guild_workspace(
    name: str,
    slug: str,
    owner_user_id: str,
    primary_game: str = "albion",
) -> dict:
    """
    Create a new tenant workspace.  slug must be globally unique.
    The owner_user_id becomes workspace owner in the same transaction.
    Returns the full workspace row.
    """
    guild_workspace.validate_workspace_name(name)
    guild_workspace.validate_workspace_slug(slug)

    with database.transaction() as db:
        if not repositories.get_user_by_id(db, owner_user_id):
            raise NotFoundError(f"User '{owner_user_id}' not found.")

        if repositories.get_workspace_by_slug(db, slug):
            raise ConflictError(f"A workspace with slug '{slug}' already exists.")

        now = _now()
        workspace = {
            "id": str(uuid.uuid4()),
            "name": name.strip(),
            "slug": slug,
            "primary_game": primary_game,
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_workspace(db, workspace)

        repositories.insert_workspace_member(
            db,
            {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": workspace["id"],
                "user_id": owner_user_id,
                "role": "owner",
                "created_at": now,
            },
        )

        event = operational_events.make_event(
            guild_workspace_id=workspace["id"],
            guild_operation_id=None,
            event_type=operational_events.WORKSPACE_CREATED,
            entity_type="guild_workspace",
            entity_id=workspace["id"],
            payload={"name": name, "slug": slug, "owner_user_id": owner_user_id},
        )
        repositories.insert_operational_event(db, event)

    return workspace


# ---------------------------------------------------------------------------
# 1b. Ensure GuildWorkspace for Discord Guild  (bot join — no owner)
# ---------------------------------------------------------------------------

def ensure_workspace_for_discord_guild(
    discord_guild_id: str,
    guild_name: str,
    discord_guild_owner_id: str | None = None,
) -> dict:
    """
    Idempotent workspace bootstrap triggered by the bot joining a Discord guild.

    Behaviour:
    - If a workspace is already linked to discord_guild_id: upsert the install
      audit record (re-join counter, refresh owner_id) and return the existing
      workspace unchanged.
    - Otherwise: derive a URL-safe slug from guild_name, create the workspace
      with discord_guild_id and discord_provisioned_at set, insert a
      discord_guild_installs row, emit workspace.discord_provisioned event.

    discord_guild_owner_id: Discord snowflake of the guild owner at install
    time, used by complete_discord_workspace_setup for ownership verification.
    Optional so that existing callers and tests are not broken.

    Ownership: NO workspace_members row is created.  The workspace exists in an
    "unclaimed / setup-required" state until a verified Discord user completes
    the setup flow via complete_discord_workspace_setup.

    Name sanitisation: guild_name is truncated to 80 chars and falls back to
    "Discord Server" if the result is shorter than 2 characters.  The
    workspace_name validator is intentionally bypassed here because bot-join
    names originate from Discord (not user input) and failing silently would
    prevent the workspace from being created at all.

    Returns the workspace dict (always includes discord_guild_id).
    """
    if not (discord_guild_id or "").strip():
        raise ValidationError("Discord Guild ID must not be empty.")
    guild_workspace.validate_discord_snowflake(discord_guild_id, "Discord Guild ID")

    # Sanitise guild_name — Discord names can contain arbitrary Unicode.
    name = (guild_name or "").strip()[:80]
    if len(name) < 2:
        name = "Discord Server"

    with database.transaction() as db:
        # ---------------------------------------------------------------
        # Idempotency: workspace already linked to this guild?
        # ---------------------------------------------------------------
        existing = repositories.get_workspace_by_discord_guild_id(db, discord_guild_id)
        if existing:
            repositories.upsert_discord_guild_install(
                db,
                discord_guild_id=discord_guild_id,
                guild_name=guild_name[:255] if guild_name else "",
                guild_workspace_id=existing["id"],
                discord_guild_owner_id=discord_guild_owner_id,
            )
            return existing

        # ---------------------------------------------------------------
        # New workspace: derive slug with collision resolution
        # ---------------------------------------------------------------
        base_slug = guild_workspace.derive_workspace_slug_from_guild_name(name)

        def _slug_taken(s: str) -> bool:
            return repositories.get_workspace_by_slug(db, s) is not None

        slug = guild_workspace.make_unique_workspace_slug(base_slug, _slug_taken)

        now = _now()
        workspace = {
            "id": str(uuid.uuid4()),
            "name": name,
            "slug": slug,
            "primary_game": "albion",
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_workspace(db, workspace)
        repositories.set_workspace_discord_guild_id(
            db, workspace["id"], discord_guild_id, now
        )
        repositories.upsert_discord_guild_install(
            db,
            discord_guild_id=discord_guild_id,
            guild_name=guild_name[:255] if guild_name else "",
            guild_workspace_id=workspace["id"],
            discord_guild_owner_id=discord_guild_owner_id,
        )

        event = operational_events.make_event(
            guild_workspace_id=workspace["id"],
            guild_operation_id=None,
            event_type=operational_events.WORKSPACE_DISCORD_PROVISIONED,
            entity_type="guild_workspace",
            entity_id=workspace["id"],
            actor_type="system",
            payload={
                "discord_guild_id": discord_guild_id,
                "guild_name": guild_name,
                "slug": slug,
            },
        )
        repositories.insert_operational_event(db, event)

    # Reflect the discord_guild_id that was set inside the transaction.
    workspace["discord_guild_id"] = discord_guild_id
    workspace["discord_provisioned_at"] = now
    return workspace


def complete_discord_workspace_setup(
    discord_guild_id: str,
    user_id: str,
) -> dict:
    """
    Attempt to claim ownership of a Discord-provisioned workspace.

    Verification: the logged-in user must have a Discord identity whose
    snowflake matches the discord_guild_owner_id recorded in
    discord_guild_installs at install time.

    Returns a result dict:
      {'status': str, 'workspace': dict | None}

    Status values:
      'claimed'              — ownership granted; user is now owner
      'already_claimed'      — workspace already has one or more owners
      'not_found'            — no workspace found for this Discord guild ID
      'verification_failed'  — caller's Discord ID does not match the stored
                               guild owner ID, or no Discord identity exists
                               for the caller, or no owner ID was recorded

    Design invariants:
      - Only the verified Discord guild owner can claim.
      - Race safety: uses INSERT INTO ... SELECT WHERE NOT EXISTS so two
        concurrent requests cannot both succeed; only one INSERT lands.
      - No membership rows are created on any failure path.
      - Never raises for expected failure modes.
      - No secrets logged.
    """
    if not (discord_guild_id or "").strip():
        return {"status": "not_found", "workspace": None}

    with database.transaction() as db:
        # Step 1 — resolve workspace.
        workspace = repositories.get_workspace_by_discord_guild_id(db, discord_guild_id)
        if not workspace:
            return {"status": "not_found", "workspace": None}

        # Step 2 — early return if already claimed, regardless of verification.
        if repositories.count_workspace_owners(db, workspace["id"]) > 0:
            return {"status": "already_claimed", "workspace": workspace}

        # Step 3 — resolve calling user's Discord snowflake.
        discord_identity = repositories.get_discord_identity_for_user(db, user_id)
        if not discord_identity:
            return {"status": "verification_failed", "workspace": None}

        caller_discord_id = discord_identity["provider_user_id"]

        # Step 4 — match against the snowflake recorded at bot-join time.
        install_record  = repositories.get_discord_guild_install(db, discord_guild_id)
        stored_owner_id = (install_record or {}).get("discord_guild_owner_id")

        if not stored_owner_id or caller_discord_id != stored_owner_id:
            return {"status": "verification_failed", "workspace": None}

        # Step 5 — atomic conditional INSERT (race-safe, idempotent).
        now     = _now()
        granted = repositories.grant_workspace_owner_if_unclaimed(
            db, workspace["id"], user_id, now
        )

        if not granted:
            # Another request claimed the workspace in the race window.
            return {"status": "already_claimed", "workspace": workspace}

        # Step 6 — emit audit event.
        event = operational_events.make_event(
            guild_workspace_id=workspace["id"],
            guild_operation_id=None,
            event_type=operational_events.WORKSPACE_OWNER_CLAIMED,
            entity_type="guild_workspace",
            entity_id=workspace["id"],
            actor_type="user",
            actor_id=user_id,
            payload={
                "discord_guild_id": discord_guild_id,
            },
        )
        repositories.insert_operational_event(db, event)

    return {"status": "claimed", "workspace": workspace}


def add_workspace_member(
    guild_workspace_id: str,
    actor_user_id: str,
    display_name: str,
    role: str = "member",
) -> dict:
    """Add a workspace member by dev display name. Owner/officer actors only."""
    workspace_membership.validate_role(role)
    users.validate_display_name(display_name)
    provider_user_id = users.dev_provider_user_id(display_name)

    with database.transaction() as db:
        actor_membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_membership:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_membership["role"]):
            raise PermissionDenied("Only owners and officers can add members.")

        user = repositories.get_user_by_provider_identity(
            db, users.DEV_AUTH_PROVIDER, provider_user_id
        )
        if not user:
            now = _now()
            user = {
                "id": str(uuid.uuid4()),
                "display_name": display_name.strip(),
                "auth_provider": users.DEV_AUTH_PROVIDER,
                "provider_user_id": provider_user_id,
                "created_at": now,
                "updated_at": now,
            }
            repositories.insert_user(db, user)

        if repositories.get_workspace_membership(db, guild_workspace_id, user["id"]):
            raise ConflictError("User is already a member of this workspace.")

        now = _now()
        membership = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "user_id": user["id"],
            "role": role,
            "created_at": now,
        }
        repositories.insert_workspace_member(db, membership)

    return membership


def remove_workspace_member(
    guild_workspace_id: str,
    actor_user_id: str,
    target_user_id: str,
) -> None:
    """
    Remove a workspace member by deleting only their workspace_members row.

    Preserves: users, participants, signup_intents, assignments,
    attendance_records, and operational_events â€” historical data is untouched.

    Permission rules:
    - Actor must be owner or officer (can_manage_members).
    - Actor cannot remove themselves.
    - Officer can only remove members (not officers, not owners).
    - Owner can remove members and officers, but NOT other owners.

    Guard: removal is blocked when the target still has active (status='assigned')
    assignments in this workspace. The actor must remove those assignments first.
    """
    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")

        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can remove members.")

        if actor_user_id == target_user_id:
            raise PermissionDenied("You cannot remove yourself from the workspace.")

        target_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, target_user_id
        )
        if not target_mem:
            raise NotFoundError("Member not found in this workspace.")

        target_role = target_mem["role"]

        if target_role == "owner":
            raise PermissionDenied("Workspace owners cannot be removed.")

        if actor_mem["role"] == "officer" and target_role == "officer":
            raise PermissionDenied("Officers cannot remove other officers.")

        # Resolve the target user's display_name â†’ participant in this workspace.
        target_user = repositories.get_user_by_id(db, target_user_id)
        if target_user:
            participant = repositories.find_participant_by_display_name(
                db, guild_workspace_id, target_user["display_name"]
            )
            if participant:
                active = repositories.count_active_assignments_for_participant(
                    db, guild_workspace_id, participant["id"]
                )
                if active > 0:
                    raise ConflictError(
                        f"Cannot remove '{target_user['display_name']}': they have "
                        f"{active} active assignment(s). Remove those assignments first."
                    )

        repositories.delete_workspace_member(db, guild_workspace_id, target_user_id)

        # Resolve display_name for the event payload (may be None if user row missing).
        removed_display_name = target_user["display_name"] if target_user else None

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.WORKSPACE_MEMBER_REMOVED,
            entity_type="workspace_member",
            entity_id=target_mem["id"],
            actor_type="user",
            actor_id=actor_user_id,
            payload={
                "removed_user_id": target_user_id,
                "removed_user_display_name": removed_display_name,
                "removed_role": target_role,
            },
        )
        repositories.insert_operational_event(db, event)


def set_workspace_member_role(
    guild_workspace_id: str,
    actor_user_id: str,
    target_user_id: str,
    new_role: str,
) -> dict:
    """Promote a member to officer or demote an officer back to member.

    Permission rules:
    - Only a workspace **owner** (or a platform super-admin) may change roles.
      Officers cannot change roles — this prevents privilege escalation.
    - new_role must be 'officer' or 'member'. Ownership is transferred via a
      separate flow, never through this command.
    - The target must be an existing member and must not currently be an owner
      (owners are managed through ownership transfer only).
    - The actor cannot change their own role — EXCEPT a platform super-admin,
      who may grant themselves officer/member access (god-mode self-service). If
      the super-admin is not yet a member, a membership row is created.

    Emits a WORKSPACE_MEMBER_ROLE_CHANGED audit event. Idempotent: setting the
    role a member already has is a no-op that still returns successfully.

    Returns ``{"user_id": ..., "old_role": ..., "new_role": ...}``.
    """
    if new_role not in ("officer", "member"):
        raise ValidationError("Role must be either 'officer' or 'member'.")

    with database.transaction() as db:
        is_superadmin = _actor_is_superadmin(db, actor_user_id)

        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        # Owners (or super-admins via god-mode) only.
        if not is_superadmin and (not actor_mem or actor_mem["role"] != "owner"):
            raise PermissionDenied(
                "Only the workspace owner can change member roles."
            )

        # Self-change is blocked for everyone except super-admins.
        if actor_user_id == target_user_id and not is_superadmin:
            raise PermissionDenied("You cannot change your own role.")

        target_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, target_user_id
        )
        if not target_mem:
            # A super-admin promoting themselves in a workspace they aren't a
            # member of yet: create the membership on the fly.
            if is_superadmin and actor_user_id == target_user_id:
                membership = {
                    "id": str(uuid.uuid4()),
                    "guild_workspace_id": guild_workspace_id,
                    "user_id": target_user_id,
                    "role": new_role,
                    "created_at": _now(),
                }
                repositories.insert_workspace_member(db, membership)
                event = operational_events.make_event(
                    guild_workspace_id=guild_workspace_id,
                    guild_operation_id=None,
                    event_type=operational_events.WORKSPACE_MEMBER_ROLE_CHANGED,
                    entity_type="workspace_member",
                    entity_id=membership["id"],
                    actor_type="user",
                    actor_id=actor_user_id,
                    payload={"target_user_id": target_user_id,
                             "old_role": None, "new_role": new_role},
                )
                repositories.insert_operational_event(db, event)
                return {"user_id": target_user_id, "old_role": None, "new_role": new_role}
            raise NotFoundError("Member not found in this workspace.")

        old_role = target_mem["role"]
        if old_role == "owner":
            raise PermissionDenied(
                "The workspace owner's role cannot be changed here. Use "
                "ownership transfer instead."
            )

        if old_role != new_role:
            repositories.set_workspace_member_role(
                db, guild_workspace_id, target_user_id, new_role
            )
            event = operational_events.make_event(
                guild_workspace_id=guild_workspace_id,
                guild_operation_id=None,
                event_type=operational_events.WORKSPACE_MEMBER_ROLE_CHANGED,
                entity_type="workspace_member",
                entity_id=target_mem["id"],
                actor_type="user",
                actor_id=actor_user_id,
                payload={
                    "target_user_id": target_user_id,
                    "old_role": old_role,
                    "new_role": new_role,
                },
            )
            repositories.insert_operational_event(db, event)

    return {"user_id": target_user_id, "old_role": old_role, "new_role": new_role}


# ---------------------------------------------------------------------------
# 2. Create GuildOperation
# ---------------------------------------------------------------------------

def create_guild_operation(
    guild_workspace_id: str,
    title: str,
    operation_type: str,
    scheduled_start_at: str,
) -> dict:
    """
    Create a new operation inside a workspace.
    Returns the full guild_operations row.
    """
    guild_operations.validate_operation_title(title)
    guild_operations.validate_operation_type(operation_type)
    guild_operations.validate_scheduled_start_at(scheduled_start_at)

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError(f"GuildWorkspace '{guild_workspace_id}' not found.")

        now = _now()
        operation = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "title": title.strip(),
            "operation_type": operation_type,
            "scheduled_start_at": scheduled_start_at,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_guild_operation(db, operation)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=operation["id"],
            event_type=operational_events.GUILD_OPERATION_CREATED,
            entity_type="guild_operation",
            entity_id=operation["id"],
            payload={"title": title, "operation_type": operation_type},
        )
        repositories.insert_operational_event(db, event)

    return operation


# ---------------------------------------------------------------------------
# Internal helper â€” status transition (no transaction; caller owns it)
# ---------------------------------------------------------------------------

def _transition_operation(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    target_status: str,
    event_type: str,
) -> dict:
    """
    Validate and apply a single status transition inside the caller's transaction.

    Performs the workspace-boundary check, calls validate_status_transition,
    updates the row, and emits the event.  Returns the updated operation dict.
    """
    op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
    if not op:
        raise NotFoundError(
            f"GuildOperation '{guild_operation_id}' not found in this workspace."
        )

    guild_operations.validate_status_transition(op["status"], target_status)

    now = _now()
    repositories.update_operation_status(
        db, guild_operation_id, guild_workspace_id, target_status, now
    )

    event = operational_events.make_event(
        guild_workspace_id=guild_workspace_id,
        guild_operation_id=guild_operation_id,
        event_type=event_type,
        entity_type="guild_operation",
        entity_id=guild_operation_id,
        payload={
            "previous_status": op["status"],
            "new_status": target_status,
        },
    )
    repositories.insert_operational_event(db, event)

    return {**op, "status": target_status, "updated_at": now}


# ---------------------------------------------------------------------------
# 2a. Publish Operation  (draft â†’ planning)
# ---------------------------------------------------------------------------

def publish_operation(guild_workspace_id: str, guild_operation_id: str) -> dict:
    """
    Transition the operation from draft to planning.
    Signups are now open and roster assembly begins.
    """
    with database.transaction() as db:
        return _transition_operation(
            db, guild_workspace_id, guild_operation_id,
            target_status="planning",
            event_type=operational_events.GUILD_OPERATION_PUBLISHED,
        )


# ---------------------------------------------------------------------------
# 2b. Lock Operation  (planning â†’ locked)
# ---------------------------------------------------------------------------

def lock_operation(guild_workspace_id: str, guild_operation_id: str) -> dict:
    """
    Transition the operation from planning to locked.
    The roster is frozen; no further signups are expected.
    """
    with database.transaction() as db:
        return _transition_operation(
            db, guild_workspace_id, guild_operation_id,
            target_status="locked",
            event_type=operational_events.GUILD_OPERATION_LOCKED,
        )


# ---------------------------------------------------------------------------
# 2c. Complete Operation  (locked â†’ completed  or  planning â†’ completed)
# ---------------------------------------------------------------------------

def complete_operation(guild_workspace_id: str, guild_operation_id: str) -> dict:
    """
    Transition the operation to completed.
    Valid from both locked (normal path) and planning (small ops fast-path).
    Attendance can now be marked for assigned participants.
    """
    with database.transaction() as db:
        return _transition_operation(
            db, guild_workspace_id, guild_operation_id,
            target_status="completed",
            event_type=operational_events.GUILD_OPERATION_COMPLETED,
        )


# ---------------------------------------------------------------------------
# 2d. Archive Operation  (completed â†’ archived)
# ---------------------------------------------------------------------------

def archive_operation(guild_workspace_id: str, guild_operation_id: str) -> dict:
    """
    Transition the operation to archived.
    The operation becomes a historical record; no further changes are expected.
    """
    with database.transaction() as db:
        return _transition_operation(
            db, guild_workspace_id, guild_operation_id,
            target_status="archived",
            event_type=operational_events.GUILD_OPERATION_ARCHIVED,
        )


# ---------------------------------------------------------------------------
# 3a. AlbionBuild CRUD
# ---------------------------------------------------------------------------

def _resolve_build_for_slot(
    db,
    guild_workspace_id: str,
    slot: dict,
) -> dict:
    """Resolve albion_build_id FK within a slot dict.

    If the slot carries a non-empty ``albion_build_id`` that resolves to a
    valid, non-retired build in this workspace, the slot's doctrine fields
    (build_name, weapon_name, offhand_name, head_name, armor_name,
    shoes_name, cape_name, food_name, potion_name) are overwritten from the
    build record and the FK is kept.

    If the FK is absent, empty, or does not resolve (not found / retired /
    wrong workspace), the FK is cleared and the slot's existing text fields
    are used unchanged.  This ensures backward compatibility for manually
    typed builds and protects against stale or cross-workspace FKs.

    The Build Snapshot Invariant is preserved: operation_slots never carry
    the FK and are not affected by any build field changes.
    """
    bid = (slot.get("albion_build_id") or "").strip()
    if not bid:
        return {
            **slot,
            "albion_build_id": None,
            "offhand_name":  slot.get("offhand_name"),
            "head_name":     slot.get("head_name"),
            "armor_name":    slot.get("armor_name"),
            "shoes_name":    slot.get("shoes_name"),
            "cape_name":     slot.get("cape_name"),
            "food_name":     slot.get("food_name"),
            "potion_name":   slot.get("potion_name"),
            "doctrine_role": slot.get("doctrine_role"),
        }

    build = repositories.get_albion_build(db, bid, guild_workspace_id)
    if not build or build.get("retired_at"):
        return {
            **slot,
            "albion_build_id": None,
            "offhand_name":  slot.get("offhand_name"),
            "head_name":     slot.get("head_name"),
            "armor_name":    slot.get("armor_name"),
            "shoes_name":    slot.get("shoes_name"),
            "cape_name":     slot.get("cape_name"),
            "food_name":     slot.get("food_name"),
            "potion_name":   slot.get("potion_name"),
            "doctrine_role": slot.get("doctrine_role"),
        }

    return {
        **slot,
        "build_name":    build["name"],
        "weapon_name":   build["weapon_name"] or slot.get("weapon_name"),
        "offhand_name":  build.get("offhand_name"),
        "head_name":     build.get("head_name"),
        "armor_name":    build.get("armor_name"),
        "shoes_name":    build.get("shoes_name"),
        "cape_name":     build.get("cape_name"),
        "food_name":     build.get("food_name"),
        "potion_name":   build.get("potion_name"),
        # doctrine_role: build default propagated at attach; slot-level override preserved
        # if the slot already has a value (slot.get wins over build default only when non-empty).
        "doctrine_role": slot.get("doctrine_role") or build.get("doctrine_role"),
        "albion_build_id": build["id"],
    }


def create_albion_build(
    guild_workspace_id: str,
    actor_user_id: str,
    name: str,
    role: str,
    weapon_name: str,
    offhand_name: str | None = None,
    head_name: str | None = None,
    armor_name: str | None = None,
    shoes_name: str | None = None,
    cape_name: str | None = None,
    food_name: str | None = None,
    potion_name: str | None = None,
    notes: str | None = None,
    doctrine_role: str | None = None,
) -> dict:
    """Create a reusable build doctrine entity in a workspace.

    The actor must be an officer or owner.  Returns the full build row dict.
    """
    data = {
        "name":          (name or "").strip(),
        "role":          (role or "").strip(),
        "weapon_name":   (weapon_name or "").strip(),
        "offhand_name":  (offhand_name or "").strip() or None,
        "head_name":     (head_name or "").strip() or None,
        "armor_name":    (armor_name or "").strip() or None,
        "shoes_name":    (shoes_name or "").strip() or None,
        "cape_name":     (cape_name or "").strip() or None,
        "food_name":     (food_name or "").strip() or None,
        "potion_name":   (potion_name or "").strip() or None,
        "notes":         (notes or "").strip() or None,
        "doctrine_role": (doctrine_role or "").strip() or None,
    }
    albion_builds_domain.validate_build(data)

    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can create builds.")

        now = _now()
        build = {
            "id":                str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "retired_at":        None,
            "created_at":        now,
            "updated_at":        now,
            **data,
        }
        repositories.insert_albion_build(db, build)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_BUILD_CREATED,
            entity_type="albion_build",
            entity_id=build["id"],
            actor_type="user",
            actor_id=actor_user_id,
            payload={"name": build["name"], "role": build["role"]},
        )
        repositories.insert_operational_event(db, event)

    return build


def bulk_import_albion_builds(
    guild_workspace_id: str,
    actor_user_id: str,
    rows: list[dict],
) -> list[dict]:
    """Bulk-create builds from a pre-parsed list of field dicts.

    All rows are normalised and validated before any DB write.  If any row
    fails validation a ``ValidationError`` is raised with the row number
    prepended; nothing is inserted.  Returns the list of created build dicts.

    This is a single atomic transaction: either all builds are created or none.
    """
    from app.errors import ValidationError  # noqa: PLC0415 (avoid circular at module level)

    created: list[dict] = []
    with database.transaction() as db:
        # Permission check first — fail fast before touching any data.
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can import builds.")

        # Normalise and validate every row before inserting any of them.
        normalised: list[dict] = []
        for i, row in enumerate(rows, start=1):
            data = {
                "name":          (row.get("name") or "").strip(),
                "role":          (row.get("role") or "").strip(),
                "weapon_name":   (row.get("weapon_name") or "").strip(),
                "offhand_name":  (row.get("offhand_name") or "").strip() or None,
                "head_name":     (row.get("head_name") or "").strip() or None,
                "armor_name":    (row.get("armor_name") or "").strip() or None,
                "shoes_name":    (row.get("shoes_name") or "").strip() or None,
                "cape_name":     (row.get("cape_name") or "").strip() or None,
                "food_name":     (row.get("food_name") or "").strip() or None,
                "potion_name":   (row.get("potion_name") or "").strip() or None,
                "notes":         (row.get("notes") or "").strip() or None,
                "doctrine_role": (row.get("doctrine_role") or "").strip() or None,
            }
            try:
                albion_builds_domain.validate_build(data)
            except ValidationError as exc:
                raise ValidationError(f"Row {i}: {exc}") from exc
            normalised.append(data)

        now = _now()
        for data in normalised:
            build = {
                "id":                 str(uuid.uuid4()),
                "guild_workspace_id": guild_workspace_id,
                "retired_at":         None,
                "created_at":         now,
                "updated_at":         now,
                **data,
            }
            repositories.insert_albion_build(db, build)

            event = operational_events.make_event(
                guild_workspace_id=guild_workspace_id,
                guild_operation_id=None,
                event_type=operational_events.ALBION_BUILD_CREATED,
                entity_type="albion_build",
                entity_id=build["id"],
                actor_type="user",
                actor_id=actor_user_id,
                payload={"name": build["name"], "role": build["role"]},
            )
            repositories.insert_operational_event(db, event)
            created.append(build)

    return created


def update_albion_build(
    guild_workspace_id: str,
    build_id: str,
    actor_user_id: str,
    name: str,
    role: str,
    weapon_name: str,
    offhand_name: str | None = None,
    head_name: str | None = None,
    armor_name: str | None = None,
    shoes_name: str | None = None,
    cape_name: str | None = None,
    food_name: str | None = None,
    potion_name: str | None = None,
    notes: str | None = None,
    doctrine_role: str | None = None,
) -> None:
    """Update a build's fields.

    Build Snapshot Invariant: this does NOT retroactively update any slot
    templates or operation_slots that already reference this build.  Existing
    composition slot templates store independent text snapshots; they remain
    unchanged until an officer explicitly re-attaches the updated build.
    """
    data = {
        "name":          (name or "").strip(),
        "role":          (role or "").strip(),
        "weapon_name":   (weapon_name or "").strip(),
        "offhand_name":  (offhand_name or "").strip() or None,
        "head_name":     (head_name or "").strip() or None,
        "armor_name":    (armor_name or "").strip() or None,
        "shoes_name":    (shoes_name or "").strip() or None,
        "cape_name":     (cape_name or "").strip() or None,
        "food_name":     (food_name or "").strip() or None,
        "potion_name":   (potion_name or "").strip() or None,
        "notes":         (notes or "").strip() or None,
        "doctrine_role": (doctrine_role or "").strip() or None,
    }
    albion_builds_domain.validate_build(data)

    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can edit builds.")

        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        if not build:
            raise NotFoundError(f"Build '{build_id}' not found.")
        if build.get("retired_at"):
            raise ConflictError("Retired builds cannot be edited.")

        now = _now()
        repositories.update_albion_build_fields(
            db, build_id, guild_workspace_id, data, now
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_BUILD_UPDATED,
            entity_type="albion_build",
            entity_id=build_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"name": data["name"]},
        )
        repositories.insert_operational_event(db, event)


def retire_albion_build(
    guild_workspace_id: str,
    build_id: str,
    actor_user_id: str,
) -> None:
    """Soft-delete a build.

    Retired builds cannot be newly attached to slot templates.  Existing
    compositions and operation_slots that reference this build remain stable
    — the slot text snapshots are independent of build retirement.
    """
    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can retire builds.")

        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        if not build:
            raise NotFoundError(f"Build '{build_id}' not found.")
        if build.get("retired_at"):
            raise ConflictError("Build is already retired.")

        now = _now()
        repositories.retire_albion_build(db, build_id, guild_workspace_id, now)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_BUILD_RETIRED,
            entity_type="albion_build",
            entity_id=build_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"name": build["name"]},
        )
        repositories.insert_operational_event(db, event)


# ---------------------------------------------------------------------------
# Phase 12.3 — Versioned build system
# ---------------------------------------------------------------------------

def _can_manage_builds(membership: dict) -> bool:
    """Return True when the membership role may create/edit/archive builds."""
    return membership["role"] in ("owner", "officer")


def _parse_slot_items_json(raw: str) -> list[dict]:
    """Parse the slot_items_json string from the editor form.

    Returns a list of dicts with at minimum 'slot' and 'item_id' keys.
    Raises ValidationError on malformed JSON.
    """
    import json
    from app.errors import ValidationError as _VE
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _VE(f"slot_items_json is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise _VE("slot_items_json must be a JSON array.")
    return data


def _validate_and_resolve_slots(
    slot_items_raw: list[dict],
    status: str,
) -> list[dict]:
    """Look up each slot item in the catalog, validate and return enriched dicts.

    The catalog is the authoritative source for display_name, tier, enchantment,
    is_two_handed, and slot classification.  Client-supplied values for these
    fields are ignored.  Only item_id and slot are taken from the client.

    Raises ValidationError for unknown item IDs, slot mismatches, or
    failed invariants (duplicate primary, two-handed + off_hand, published
    minimum slots).
    """
    from app.albion.item_catalog import get_catalog, VALID_SLOTS
    from app.domain import build_version as bv_domain
    from app.errors import ValidationError as _VE

    catalog = get_catalog()
    resolved: list[dict] = []

    for raw in slot_items_raw:
        slot = (raw.get("slot") or "").strip()
        if not slot:
            raise _VE("A slot item is missing the 'slot' field.")
        if slot not in VALID_SLOTS:
            raise _VE(f"Unknown slot '{slot}'.")

        item_id = (raw.get("item_id") or "").strip().upper()
        if not item_id:
            raise _VE(f"Slot '{slot}' has an empty item_id.")

        cat_item = catalog.get_item(item_id)
        if cat_item is None:
            raise _VE(
                f"Item '{item_id}' is not in the T7/T8 catalog. "
                "Save rejected — only catalog-validated items are allowed."
            )

        # Catalog-authoritative: slot classification check
        if cat_item["slot"] != slot:
            raise _VE(
                f"Item '{item_id}' belongs to slot '{cat_item['slot']}', "
                f"but was submitted for slot '{slot}'."
            )

        resolved.append({
            "slot":         slot,
            "item_id":      cat_item["item_id"],
            "display_name": cat_item["display_name"],
            "tier":         cat_item["tier"],
            "enchantment":  cat_item["enchantment"],
            "is_two_handed": cat_item["is_two_handed"],
            "is_primary":   bool(raw.get("is_primary", True)),
        })

    bv_domain.validate_slot_items(resolved, status)
    return resolved


def create_build(
    guild_workspace_id: str,
    actor_user_id: str,
    name: str,
    description: str,
    role: str,
    event_type: str,
    minimum_ip: int,
    status: str,
    slot_items_json: str,
    change_summary: str = "",
) -> dict:
    """Create a new versioned build with version 1 atomically.

    Steps performed in one transaction:
    1. Validate metadata and slot items.
    2. INSERT albion_builds with current_version_id = NULL.
    3. INSERT albion_build_versions (version 1).
    4. INSERT albion_build_slot_items.
    5. UPDATE albion_builds SET current_version_id = version.id.
    6. Emit build_created and version_created events.

    Returns the new build dict.
    """
    from app.domain import build_version as bv_domain

    meta = {
        "name":           name,
        "description":    description,
        "role":           role,
        "event_type":     event_type,
        "minimum_ip":     minimum_ip,
        "status":         status,
        "change_summary": change_summary,
    }
    bv_domain.validate_build_meta(meta)

    slot_items_raw = _parse_slot_items_json(slot_items_json)
    resolved_slots = _validate_and_resolve_slots(slot_items_raw, status)

    with database.transaction() as db:
        member = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not member:
            raise NotFoundError("Workspace not found.")
        if not _can_manage_builds(member):
            raise PermissionDenied("Only owners and officers can create builds.")

        now = _now()
        build_id   = str(uuid.uuid4())
        version_id = str(uuid.uuid4())

        build_row = {
            "id":                 build_id,
            "guild_workspace_id": guild_workspace_id,
            "name":               name.strip(),
            "description":        description.strip() if description else None,
            "role":               role.strip(),
            "event_type":         event_type.strip(),
            "minimum_ip":         int(minimum_ip),
            "status":             status,
            "current_version_id": None,  # set after version insert
            "notes":              None,
            "doctrine_role":      None,
            # Legacy flat equipment fields — NULL for v2 builds (Phase 12.3b).
            # weapon_name is nullable post-migration; versioned builds never use
            # these fields.  The _migrate_albion_builds_rebuild migration also
            # backfills any existing "" sentinels to NULL.
            "weapon_name":        None,
            "offhand_name":       None,
            "head_name":          None,
            "armor_name":         None,
            "shoes_name":         None,
            "cape_name":          None,
            "food_name":          None,
            "potion_name":        None,
            "created_at":         now,
            "updated_at":         now,
            "created_by":         actor_user_id,
            "updated_by":         actor_user_id,
            "archived_at":        None,
            "archived_by":        None,
            "retired_at":         None,
        }
        repositories.insert_albion_build_v2(db, build_row)

        version_row = {
            "id":                 version_id,
            "build_id":           build_id,
            "guild_workspace_id": guild_workspace_id,
            "version_number":     1,
            "change_summary":     change_summary.strip() if change_summary else None,
            "created_at":         now,
            "created_by":         actor_user_id,
        }
        repositories.insert_build_version(db, version_row)

        slot_rows = [
            {
                "id":                    str(uuid.uuid4()),
                "build_version_id":      version_id,
                "guild_workspace_id":    guild_workspace_id,
                "slot":                  item["slot"],
                "item_id":               item["item_id"],
                "display_name_snapshot": item["display_name"],
                "tier":                  item["tier"],
                "enchantment":           item["enchantment"],
                "is_primary":            1 if item["is_primary"] else 0,
                "priority":              0,
                "notes":                 None,
                "minimum_enchantment":   0,
            }
            for item in resolved_slots
        ]
        if slot_rows:
            repositories.insert_build_slot_items(db, slot_rows)

        repositories.set_build_current_version(
            db, build_id, guild_workspace_id, version_id, now, actor_user_id
        )

        _emit(db, guild_workspace_id, None, "build_created", "albion_build",
              build_id, actor_user_id, {"name": name, "version": 1})
        _emit(db, guild_workspace_id, None, "build_version_created",
              "albion_build_version", version_id, actor_user_id,
              {"build_id": build_id, "version_number": 1})

    return repositories.get_albion_build(
        _get_db_direct(), build_id, guild_workspace_id
    ) or {"id": build_id}


def _get_db_direct():
    """Open a read-only connection for post-commit reads."""
    return database.get_connection()


def _emit(
    db,
    guild_workspace_id: str,
    guild_operation_id,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_user_id: str,
    payload: dict,
) -> None:
    """Helper to emit an operational event within an open transaction."""
    event = operational_events.make_event(
        guild_workspace_id=guild_workspace_id,
        guild_operation_id=guild_operation_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type="user",
        actor_id=actor_user_id,
        payload=payload,
    )
    repositories.insert_operational_event(db, event)


def create_build_version(
    guild_workspace_id: str,
    build_id: str,
    actor_user_id: str,
    slot_items_json: str,
    change_summary: str = "",
    intended_status: str = "draft",
    expected_current_version_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    role: str | None = None,
    event_type: str | None = None,
    minimum_ip: int | None = None,
) -> dict:
    """Save changes to an existing build as a new immutable version.

    Concurrency protection: if expected_current_version_id is provided and
    does not match build.current_version_id, raises ConflictError (409).

    No-change detection: if the metadata and slot state are identical to the
    current version, returns the existing version without creating a new one.

    Returns a dict with keys:
        build:    updated build row
        version:  the new (or unchanged) version row
        created:  True if a new version was created, False if unchanged
    """
    from app.domain import build_version as bv_domain

    slot_items_raw = _parse_slot_items_json(slot_items_json)

    with database.transaction() as db:
        member = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not member:
            raise NotFoundError("Workspace not found.")
        if not _can_manage_builds(member):
            raise PermissionDenied("Only owners and officers can save build versions.")

        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        if not build:
            raise NotFoundError(f"Build '{build_id}' not found.")
        if build.get("retired_at"):
            raise ConflictError("Legacy retired builds cannot receive new versions.")
        if build.get("status") == "archived":
            raise ConflictError(
                "Archived builds cannot be edited. Restore the build first."
            )

        # Optimistic concurrency check
        if (
            expected_current_version_id is not None
            and expected_current_version_id != ""
            and build.get("current_version_id") != expected_current_version_id
        ):
            raise ConflictError(
                "The build was modified by another save since you opened it. "
                "Please reload and reapply your changes."
            )

        # Resolve metadata (fall back to existing build values)
        new_name        = (name        or build["name"]).strip()
        new_description = (description or build.get("description") or "").strip()
        new_role        = (role        or build["role"]).strip()
        new_event_type  = (event_type  or build.get("event_type", "other")).strip()
        new_minimum_ip  = int(minimum_ip) if minimum_ip is not None else int(build.get("minimum_ip") or 0)
        new_status      = intended_status or build.get("status", "draft")

        meta = {
            "name":           new_name,
            "description":    new_description,
            "role":           new_role,
            "event_type":     new_event_type,
            "minimum_ip":     new_minimum_ip,
            "status":         new_status,
            "change_summary": change_summary,
        }
        bv_domain.validate_build_meta(meta)

        resolved_slots = _validate_and_resolve_slots(slot_items_raw, new_status)

        # No-change detection against current version
        current_version = repositories.get_current_build_version(
            db, build_id, guild_workspace_id
        )
        if current_version:
            current_items = repositories.get_build_slot_items(
                db, current_version["id"], guild_workspace_id
            )
            if _is_identical(build, current_items, meta, resolved_slots):
                return {
                    "build":   dict(build),
                    "version": dict(current_version),
                    "created": False,
                }

        now        = _now()
        version_id = str(uuid.uuid4())
        next_num   = repositories.get_next_version_number(
            db, build_id, guild_workspace_id
        )

        version_row = {
            "id":                 version_id,
            "build_id":           build_id,
            "guild_workspace_id": guild_workspace_id,
            "version_number":     next_num,
            "change_summary":     change_summary.strip() if change_summary else None,
            "created_at":         now,
            "created_by":         actor_user_id,
        }
        repositories.insert_build_version(db, version_row)

        slot_rows = [
            {
                "id":                    str(uuid.uuid4()),
                "build_version_id":      version_id,
                "guild_workspace_id":    guild_workspace_id,
                "slot":                  item["slot"],
                "item_id":               item["item_id"],
                "display_name_snapshot": item["display_name"],
                "tier":                  item["tier"],
                "enchantment":           item["enchantment"],
                "is_primary":            1 if item["is_primary"] else 0,
                "priority":              0,
                "notes":                 None,
                "minimum_enchantment":   0,
            }
            for item in resolved_slots
        ]
        if slot_rows:
            repositories.insert_build_slot_items(db, slot_rows)

        meta_fields = {
            "name":               new_name,
            "description":        new_description or None,
            "role":               new_role,
            "event_type":         new_event_type,
            "minimum_ip":         new_minimum_ip,
            "status":             new_status,
            "current_version_id": version_id,
            "updated_by":         actor_user_id,
        }
        repositories.update_albion_build_meta_v2(
            db, build_id, guild_workspace_id, meta_fields, now
        )

        _emit(db, guild_workspace_id, None, "build_version_created",
              "albion_build_version", version_id, actor_user_id,
              {"build_id": build_id, "version_number": next_num})

        updated_build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        return {
            "build":   dict(updated_build),
            "version": version_row,
            "created": True,
        }


def _is_identical(
    build: dict,
    current_items: list[dict],
    new_meta: dict,
    new_slots: list[dict],
) -> bool:
    """Return True when metadata and slot state are identical to the current version."""
    # Compare metadata
    if build.get("name") != new_meta["name"]:
        return False
    if (build.get("description") or "") != new_meta["description"]:
        return False
    if build.get("role") != new_meta["role"]:
        return False
    if build.get("event_type", "other") != new_meta["event_type"]:
        return False
    if int(build.get("minimum_ip") or 0) != int(new_meta["minimum_ip"]):
        return False
    if build.get("status") != new_meta["status"]:
        return False

    # Compare slot items (order-independent, primary only)
    current_set = frozenset(
        (i["slot"], i["item_id"])
        for i in current_items
        if i.get("is_primary")
    )
    new_set = frozenset(
        (i["slot"], i["item_id"])
        for i in new_slots
        if i.get("is_primary")
    )
    return current_set == new_set


def get_build(
    guild_workspace_id: str,
    build_id: str,
) -> dict:
    """Return a versioned build or raise NotFoundError."""
    with database.transaction() as db:
        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
    if not build or build.get("retired_at"):
        raise NotFoundError(f"Build '{build_id}' not found.")
    return build


def get_current_build_version(
    guild_workspace_id: str,
    build_id: str,
) -> dict | None:
    with database.transaction() as db:
        return repositories.get_current_build_version(db, build_id, guild_workspace_id)


def list_build_versions(
    guild_workspace_id: str,
    build_id: str,
) -> list[dict]:
    with database.transaction() as db:
        return repositories.list_build_versions(db, build_id, guild_workspace_id)


def get_build_version(
    guild_workspace_id: str,
    build_id: str,
    version_id: str,
) -> dict:
    with database.transaction() as db:
        v = repositories.get_build_version(db, version_id, build_id, guild_workspace_id)
    if not v:
        raise NotFoundError(f"Version '{version_id}' not found.")
    return v


def list_builds_v2(
    guild_workspace_id: str,
    include_archived: bool = False,
) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_v2_builds(db, guild_workspace_id, include_archived)


def archive_build(
    guild_workspace_id: str,
    build_id: str,
    actor_user_id: str,
) -> None:
    with database.transaction() as db:
        member = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not member:
            raise NotFoundError("Workspace not found.")
        if not _can_manage_builds(member):
            raise PermissionDenied("Only owners and officers can archive builds.")

        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        if not build:
            raise NotFoundError(f"Build '{build_id}' not found.")
        if build.get("status") == "archived":
            raise ConflictError("Build is already archived.")
        if not build.get("current_version_id"):
            raise ConflictError(
                "Only versioned builds (created via the visual editor) can be archived. "
                "Legacy builds use the 'retire' action."
            )

        now = _now()
        repositories.archive_albion_build_v2(
            db, build_id, guild_workspace_id, actor_user_id, now
        )
        _emit(db, guild_workspace_id, None, "build_archived", "albion_build",
              build_id, actor_user_id, {"name": build["name"]})


def restore_build(
    guild_workspace_id: str,
    build_id: str,
    actor_user_id: str,
) -> None:
    with database.transaction() as db:
        member = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not member:
            raise NotFoundError("Workspace not found.")
        if not _can_manage_builds(member):
            raise PermissionDenied("Only owners and officers can restore builds.")

        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        if not build:
            raise NotFoundError(f"Build '{build_id}' not found.")
        if build.get("status") != "archived":
            raise ConflictError("Build is not archived.")

        now = _now()
        repositories.restore_albion_build_v2(
            db, build_id, guild_workspace_id, actor_user_id, now
        )
        _emit(db, guild_workspace_id, None, "build_restored", "albion_build",
              build_id, actor_user_id, {"name": build["name"]})


def publish_build(
    guild_workspace_id: str,
    build_id: str,
    actor_user_id: str,
) -> None:
    """Transition a draft build to published status.

    Validates that published minimum slots are filled in the current version.
    """
    from app.domain import build_version as bv_domain

    with database.transaction() as db:
        member = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not member:
            raise NotFoundError("Workspace not found.")
        if not _can_manage_builds(member):
            raise PermissionDenied("Only owners and officers can publish builds.")

        build = repositories.get_albion_build(db, build_id, guild_workspace_id)
        if not build:
            raise NotFoundError(f"Build '{build_id}' not found.")
        if build.get("status") == "published":
            raise ConflictError("Build is already published.")
        if build.get("status") == "archived":
            raise ConflictError("Archived builds cannot be published. Restore first.")
        if not build.get("current_version_id"):
            raise ConflictError("Only versioned builds can be published.")

        # Validate published slot requirements against current version
        current_version = repositories.get_current_build_version(
            db, build_id, guild_workspace_id
        )
        if current_version:
            items = repositories.get_build_slot_items(
                db, current_version["id"], guild_workspace_id
            )
            slot_items_for_validation = [
                {
                    "slot":         i["slot"],
                    "item_id":      i["item_id"],
                    "tier":         i["tier"],
                    "enchantment":  i["enchantment"],
                    "is_primary":   bool(i.get("is_primary")),
                    "is_two_handed": False,
                }
                for i in items
            ]
            bv_domain.validate_slot_items(slot_items_for_validation, "published")

        now = _now()
        repositories.publish_albion_build_v2(
            db, build_id, guild_workspace_id, actor_user_id, now
        )
        _emit(db, guild_workspace_id, None, "build_published", "albion_build",
              build_id, actor_user_id, {"name": build["name"]})


def promote_composition_slot_to_build(
    guild_workspace_id: str,
    composition_id: str,
    slot_id: str,
    actor_user_id: str,
) -> dict:
    """Create a new library build from a free-typed composition slot template,
    then immediately backfill albion_build_id on that one slot.

    Both writes happen in a single transaction so the library never contains a
    "ghost" build that was created but not linked, and the slot never ends up
    with a dangling FK.

    Eligibility guards (all raise before any write):
    - Actor must be officer or owner.
    - Composition must not be retired (deleted_at).
    - Slot must belong to this composition and workspace.
    - Slot must have albion_build_id = NULL (already-linked slots are rejected).
    - Slot must have a non-empty build_name.
    - Slot must have a non-empty weapon_name (required by albion_builds schema).

    The slot's build_name and weapon_name text snapshots are preserved
    unchanged after the FK backfill — the new build's fields match them at
    creation time, so no visible change occurs on the composition.

    operation_slots are never touched.  Other composition_slot_templates rows
    in the same or other compositions are not affected.
    """
    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can promote slots.")

        comp = repositories.get_albion_composition(db, composition_id, guild_workspace_id)
        if not comp:
            raise NotFoundError(f"Composition '{composition_id}' not found.")
        if comp.get("deleted_at"):
            raise ConflictError("Cannot promote a slot on a retired composition.")

        slot = repositories.get_composition_slot_template_by_id(
            db, slot_id, guild_workspace_id
        )
        if not slot or slot.get("albion_composition_id") != composition_id:
            raise NotFoundError(f"Slot '{slot_id}' not found in composition '{composition_id}'.")

        if slot.get("albion_build_id"):
            raise ConflictError(
                "This slot is already linked to a library build. "
                "Detach the current build before promoting."
            )

        build_name = (slot.get("build_name") or "").strip()
        if not build_name:
            raise ValidationError("This slot has no build name — cannot promote an empty slot.")

        weapon_name = (slot.get("weapon_name") or "").strip()
        if not weapon_name:
            raise ValidationError(
                "This slot has no weapon name — add one in the quick-edit panel "
                "before promoting to the library."
            )

        now = _now()
        new_build = {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "name":               build_name,
            "role":               slot["role"],
            "weapon_name":        weapon_name,
            "offhand_name":       slot.get("offhand_name"),
            "head_name":          slot.get("head_name"),
            "armor_name":         slot.get("armor_name"),
            "shoes_name":         slot.get("shoes_name"),
            "cape_name":          slot.get("cape_name"),
            "food_name":          slot.get("food_name"),
            "potion_name":        slot.get("potion_name"),
            "notes":              None,
            "doctrine_role":      slot.get("doctrine_role"),
            "retired_at":         None,
            "created_at":         now,
            "updated_at":         now,
        }
        albion_builds_domain.validate_build(new_build)
        repositories.insert_albion_build(db, new_build)

        # Backfill the FK on this slot only — all text snapshot fields stay
        # exactly as they are; only albion_build_id changes.
        # role="" → SQL CASE expression preserves the existing role unchanged.
        backfill_fields = {
            "role":           "",
            "build_name":     slot["build_name"],
            "weapon_name":    slot.get("weapon_name"),
            "doctrine_role":  slot.get("doctrine_role"),
            "albion_build_id": new_build["id"],
            "offhand_name":   slot.get("offhand_name"),
            "head_name":      slot.get("head_name"),
            "armor_name":     slot.get("armor_name"),
            "shoes_name":     slot.get("shoes_name"),
            "cape_name":      slot.get("cape_name"),
            "food_name":      slot.get("food_name"),
            "potion_name":    slot.get("potion_name"),
        }
        repositories.update_composition_slot_fields(
            db, slot_id, composition_id, guild_workspace_id, backfill_fields, now
        )
        repositories.touch_albion_composition(db, composition_id, guild_workspace_id, now)

    return new_build


# ---------------------------------------------------------------------------
# 3b. Create AlbionComposition
# ---------------------------------------------------------------------------

def create_albion_composition(
    guild_workspace_id: str,
    name: str,
    description: str | None,
    slots: list[dict],
) -> dict:
    """
    Create a composition and its slot templates.
    slots must be a list of dicts with keys:
      party_number, slot_index, role, build_name, weapon_name (opt), priority (opt)
    Returns the full albion_compositions row.
    """
    albion_compositions.validate_composition_name(name)
    albion_compositions.validate_slot_templates(slots)

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError(f"GuildWorkspace '{guild_workspace_id}' not found.")

        now = _now()
        composition = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "name": name.strip(),
            "description": description,
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_albion_composition(db, composition)

        resolved = [_resolve_build_for_slot(db, guild_workspace_id, s) for s in slots]
        templates = [
            {
                "id": str(uuid.uuid4()),
                "guild_workspace_id":    guild_workspace_id,
                "albion_composition_id": composition["id"],
                "party_number":  s["party_number"],
                "slot_index":    s["slot_index"],
                "role":          s["role"].strip(),
                "build_name":    s["build_name"].strip(),
                "weapon_name":   s.get("weapon_name"),
                "offhand_name":  s.get("offhand_name"),
                "head_name":     s.get("head_name"),
                "armor_name":    s.get("armor_name"),
                "shoes_name":    s.get("shoes_name"),
                "cape_name":     s.get("cape_name"),
                "food_name":     s.get("food_name"),
                "potion_name":   s.get("potion_name"),
                "albion_build_id": s.get("albion_build_id"),
                "doctrine_role": s.get("doctrine_role"),
                "priority":      s.get("priority", "normal"),
                "created_at":    now,
                "updated_at":    now,
            }
            for s in resolved
        ]
        repositories.insert_composition_slot_templates(db, templates)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_COMPOSITION_CREATED,
            entity_type="albion_composition",
            entity_id=composition["id"],
            payload={"name": name, "slot_count": len(slots)},
        )
        repositories.insert_operational_event(db, event)

    return composition


def retire_composition(
    guild_workspace_id: str,
    composition_id: str,
    actor_user_id: str,
) -> None:
    """
    Soft-delete a composition by setting deleted_at.

    - Composition slot templates are untouched.
    - Existing operation plans and frozen OperationSlots are unaffected.
    - The composition row remains visible via get_albion_composition (single-row
      lookup) so that operation_detail can still display it as "(retired)".
    - Retired compositions are excluded from get_albion_compositions() by default
      and must not appear in attach-plan dropdowns.
    """
    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can retire compositions.")

        comp = repositories.get_albion_composition(db, composition_id, guild_workspace_id)
        if not comp:
            raise NotFoundError(f"Composition '{composition_id}' not found.")
        if comp.get("deleted_at"):
            raise ConflictError("Composition is already retired.")

        now = _now()
        repositories.soft_delete_albion_composition(
            db, composition_id, guild_workspace_id, now
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_COMPOSITION_DELETED,
            entity_type="albion_composition",
            entity_id=composition_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={
                "composition_id": composition_id,
                "composition_name": comp["name"],
                "actor_user_id": actor_user_id,
            },
        )
        repositories.insert_operational_event(db, event)


# ---------------------------------------------------------------------------
# 3c. Update composition slot templates (edit in-place)
# ---------------------------------------------------------------------------

def quick_update_composition_slot(
    guild_workspace_id: str,
    composition_id: str,
    actor_user_id: str,
    slot_id: str,
    build_name: str,
    weapon_name: str | None = None,
    doctrine_role: str | None = None,
    albion_build_id: str | None = None,
    role: str = "",
) -> None:
    """Update the mutable fields on a single composition slot template.

    Targeted in-place mutation: build_name, weapon_name, doctrine_role, role,
    and the equipment snapshot are changed.  Priority, party number, and slot
    index remain untouched.

    ``role`` is updated when a non-empty value is supplied; a blank string
    preserves the existing role so the caller need not fetch it first.

    Allows empty build_name to set a slot to "open" state — unlike the full
    update_composition_slots path which requires every slot to have a build.

    Build Snapshot Invariant: does NOT affect operation_slots or any live
    operation planner state.  Only the composition template is updated.
    """
    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(db, guild_workspace_id, actor_user_id)
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can edit composition slots.")

        comp = repositories.get_albion_composition(db, composition_id, guild_workspace_id)
        if not comp:
            raise NotFoundError(f"Composition '{composition_id}' not found.")
        if comp.get("deleted_at"):
            raise ConflictError("Cannot edit slots on a retired composition.")

        # Resolve build FK if provided; propagates all equipment fields from build.
        slot_data: dict = {
            "role":           (role or "").strip(),
            "build_name":     (build_name or "").strip(),
            "weapon_name":    (weapon_name or "").strip() or None,
            "doctrine_role":  (doctrine_role or "").strip() or None,
            "albion_build_id": albion_build_id or None,
            "offhand_name":   None, "head_name": None, "armor_name": None,
            "shoes_name":     None, "cape_name":  None, "food_name":  None,
            "potion_name":    None,
        }
        resolved = _resolve_build_for_slot(db, guild_workspace_id, slot_data)

        now = _now()
        fields = {
            "role":           resolved.get("role", ""),
            "build_name":     resolved["build_name"],
            "weapon_name":    resolved.get("weapon_name"),
            "doctrine_role":  resolved.get("doctrine_role"),
            "albion_build_id": resolved.get("albion_build_id"),
            "offhand_name":   resolved.get("offhand_name"),
            "head_name":      resolved.get("head_name"),
            "armor_name":     resolved.get("armor_name"),
            "shoes_name":     resolved.get("shoes_name"),
            "cape_name":      resolved.get("cape_name"),
            "food_name":      resolved.get("food_name"),
            "potion_name":    resolved.get("potion_name"),
        }
        updated = repositories.update_composition_slot_fields(
            db, slot_id, composition_id, guild_workspace_id, fields, now
        )
        if updated == 0:
            raise NotFoundError(f"Slot '{slot_id}' not found in composition '{composition_id}'.")

        repositories.touch_albion_composition(db, composition_id, guild_workspace_id, now)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_COMPOSITION_SLOTS_UPDATED,
            entity_type="albion_composition",
            entity_id=composition_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"slot_id": slot_id, "build_name": fields["build_name"]},
        )
        repositories.insert_operational_event(db, event)


def update_composition_slots(
    guild_workspace_id: str,
    composition_id: str,
    actor_user_id: str,
    slots: list[dict],
) -> None:
    """Atomically replace all slot templates for an existing composition.

    - Composition must exist and not be retired.
    - Actor must be an officer or owner in the workspace.
    - Validates the new slot set before applying any changes.
    - Operation slots generated from this composition are NOT affected —
      they are frozen snapshots and remain unchanged.

    Editing may NOT clear all slots to zero.  Zero-slot compositions may only
    be created via create_albion_composition — accidental blanking through the
    edit form is rejected here.  Use retire_composition to decommission.
    """
    if not slots:
        raise ValidationError(
            "Clearing all slots via Edit is not allowed. "
            "Use Retire to decommission a composition."
        )
    albion_compositions.validate_slot_templates(slots)

    with database.transaction() as db:
        actor_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not actor_mem:
            raise NotFoundError("Workspace not found.")
        if not workspace_membership.can_manage_workspace_members(actor_mem["role"]):
            raise PermissionDenied("Only owners and officers can edit composition slots.")

        comp = repositories.get_albion_composition(db, composition_id, guild_workspace_id)
        if not comp:
            raise NotFoundError(f"Composition '{composition_id}' not found.")
        if comp.get("deleted_at"):
            raise ConflictError("Cannot edit slots on a retired composition.")

        now = _now()
        repositories.delete_composition_slot_templates(db, composition_id, guild_workspace_id)
        resolved = [_resolve_build_for_slot(db, guild_workspace_id, s) for s in slots]
        new_templates = [
            {
                "id": str(uuid.uuid4()),
                "guild_workspace_id":    guild_workspace_id,
                "albion_composition_id": composition_id,
                "party_number":  s["party_number"],
                "slot_index":    s["slot_index"],
                "role":          s["role"].strip(),
                "build_name":    s["build_name"].strip(),
                "weapon_name":   s.get("weapon_name"),
                "offhand_name":  s.get("offhand_name"),
                "head_name":     s.get("head_name"),
                "armor_name":    s.get("armor_name"),
                "shoes_name":    s.get("shoes_name"),
                "cape_name":     s.get("cape_name"),
                "food_name":     s.get("food_name"),
                "potion_name":   s.get("potion_name"),
                "albion_build_id": s.get("albion_build_id"),
                "doctrine_role": s.get("doctrine_role"),
                "priority":      s.get("priority", "normal"),
                "created_at":    now,
                "updated_at":    now,
            }
            for s in resolved
        ]
        repositories.insert_composition_slot_templates(db, new_templates)
        repositories.touch_albion_composition(db, composition_id, guild_workspace_id, now)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_COMPOSITION_SLOTS_UPDATED,
            entity_type="albion_composition",
            entity_id=composition_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"slot_count": len(slots)},
        )
        repositories.insert_operational_event(db, event)


# ---------------------------------------------------------------------------
# 4. Attach OperationPlan
# ---------------------------------------------------------------------------

def attach_operation_plan(
    guild_workspace_id: str,
    guild_operation_id: str,
    albion_composition_id: str,
    signup_status: str = "open",
    max_participants: int | None = None,
    notes: str | None = None,
) -> dict:
    """
    Attach a composition to an operation as its OperationPlan.
    An operation can have only one plan.  Both the operation and composition
    must belong to the same workspace (enforced by repository queries).
    Returns the full operation_plans row.
    """
    operation_plans.validate_signup_status(signup_status)

    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_plan_attachment_allowed(op["status"])

        comp = repositories.get_albion_composition(db, albion_composition_id, guild_workspace_id)
        if not comp:
            raise NotFoundError(
                f"AlbionComposition '{albion_composition_id}' not found in this workspace."
            )

        if repositories.get_operation_plan(db, guild_operation_id, guild_workspace_id):
            raise ConflictError(
                f"GuildOperation '{guild_operation_id}' already has an OperationPlan."
            )

        now = _now()
        plan = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "albion_composition_id": albion_composition_id,
            "signup_status": signup_status,
            "max_participants": max_participants,
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        }
        repositories.insert_operation_plan(db, plan)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.OPERATION_PLAN_ATTACHED,
            entity_type="operation_plan",
            entity_id=plan["id"],
            payload={"albion_composition_id": albion_composition_id},
        )
        repositories.insert_operational_event(db, event)

    return plan


# ---------------------------------------------------------------------------
# 5. Generate OperationSlots  (frozen snapshot from composition templates)
# ---------------------------------------------------------------------------

def generate_operation_slots(
    guild_workspace_id: str,
    guild_operation_id: str,
) -> list[dict]:
    """
    Copy composition slot templates into frozen operation_slots rows for this
    operation.  This is a one-time, irreversible action per operation.
    Later edits to the composition do NOT affect existing operation slots.
    Returns the list of created operation_slot dicts.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_slot_generation_allowed(op["status"])

        plan = repositories.get_operation_plan(db, guild_operation_id, guild_workspace_id)
        if not plan:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' has no OperationPlan. "
                "Attach a plan before generating slots."
            )

        existing_count = repositories.count_operation_slots(db, guild_operation_id, guild_workspace_id)
        mass_planner.validate_slots_not_yet_generated(existing_count)

        templates = repositories.get_composition_slot_templates(
            db, plan["albion_composition_id"], guild_workspace_id
        )
        # Zero-slot compositions are valid named shells; generating from them
        # produces zero operation slots, which is a valid (empty) snapshot state.

        now = _now()
        slots = [
            {
                "id": str(uuid.uuid4()),
                "guild_workspace_id":                  guild_workspace_id,
                "guild_operation_id":                  guild_operation_id,
                "source_composition_slot_template_id": t["id"],
                "party_number": t["party_number"],
                "slot_index":   t["slot_index"],
                "role":         t["role"],
                "build_name":   t["build_name"],
                "weapon_name":  t["weapon_name"],
                "offhand_name": t.get("offhand_name"),
                "head_name":    t.get("head_name"),
                "armor_name":   t.get("armor_name"),
                "shoes_name":   t.get("shoes_name"),
                "cape_name":     t.get("cape_name"),
                "food_name":     t.get("food_name"),
                "potion_name":   t.get("potion_name"),
                "doctrine_role": t.get("doctrine_role"),
                "priority":      t["priority"],
                "created_at":    now,
            }
            for t in templates
        ]
        repositories.insert_operation_slots(db, slots)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.OPERATION_SLOTS_GENERATED,
            entity_type="guild_operation",
            entity_id=guild_operation_id,
            payload={"slot_count": len(slots)},
        )
        repositories.insert_operational_event(db, event)

    return slots


# ---------------------------------------------------------------------------
# 6. Submit SignupIntent
# ---------------------------------------------------------------------------

def submit_signup_intent(
    guild_workspace_id: str,
    guild_operation_id: str,
    display_name: str,
    preferred_role: str,
    preferred_build_name: str | None = None,
    willingness: str = "specific",
    availability: str = "confirmed",
    source: str = "web",
    actor_user_id: str | None = None,
    discord_user_id: str | None = None,
) -> dict:
    """
    Register a participant's intent to attend an operation.
    The participant row is created on first signup (find_or_create).
    Duplicate signups for the same operation raise ConflictError.
    Returns the full signup_intents row.

    source: 'web' (default) or 'discord' â€” audit-only, no domain effect.
    discord_user_id: when the signup originates from Discord, stored on the
      participant so roster posts can @mention the member (live server nickname).
    """
    operation_plans.validate_preferred_role(preferred_role)
    operation_plans.validate_willingness(willingness)
    operation_plans.validate_availability(availability)

    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_signup_submission_allowed(op["status"])

        plan = repositories.get_operation_plan(db, guild_operation_id, guild_workspace_id)
        if plan and plan["signup_status"] == "closed":
            raise ConflictError("Signups are closed for this operation.")

        participant = repositories.find_or_create_participant(
            db, guild_workspace_id, display_name, discord_user_id=discord_user_id
        )

        existing = repositories.get_signup_intent(
            db, guild_operation_id, participant["id"], guild_workspace_id
        )
        if existing:
            raise ConflictError(
                f"'{display_name}' has already submitted a signup for this operation."
            )

        # Encode the submitting user's ID into the source field so that
        # withdrawal ownership can be verified by user ID rather than
        # display_name — without requiring a schema change.
        # Format: "web:{user_id}" for authenticated web signups.
        # "discord" is unchanged; old "web" entries fall back to display_name.
        effective_source = source
        if source == "web" and actor_user_id:
            effective_source = f"web:{actor_user_id}"

        now = _now()
        signup = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "participant_id": participant["id"],
            "preferred_role": preferred_role.strip(),
            "preferred_build_name": preferred_build_name,
            "willingness": willingness,
            "availability": availability,
            "source": effective_source,
            "created_at": now,
        }
        repositories.insert_signup_intent(db, signup)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.SIGNUP_INTENT_SUBMITTED,
            entity_type="signup_intent",
            entity_id=signup["id"],
            payload={"participant_id": participant["id"], "preferred_role": preferred_role},
        )
        repositories.insert_operational_event(db, event)

    return signup


# Withdrawal is allowed while the roster is still being shaped (planning) or
# locked (cleanup of unassigned signups).  Completed and archived operations
# preserve their signup history intact â€” post-operation corrections belong
# in attendance recording, not signup withdrawal.
_SIGNUP_WITHDRAWAL_ALLOWED_STATUSES = frozenset({"planning", "locked"})


def withdraw_signup_intent(
    guild_workspace_id: str,
    guild_operation_id: str,
    actor_user_id: str,
    signup_id: str,
) -> None:
    """
    Soft-withdraw a signup intent by setting withdrawn_at.

    Permission rules:
    - owner / officer: may withdraw any signup.
    - member: may withdraw only their own signup.

    NOTE (dev-auth phase): member ownership is checked by comparing
    actor.display_name to participant.display_name.  This must be replaced
    with an explicit userâ†”participant identity link once Discord OAuth or
    another persistent identity system is in place.

    Raises:
        NotFoundError    â€” signup not found in this workspace/operation.
        ConflictError    â€” already withdrawn, or active assignment exists.
        PermissionDenied â€” member attempting to withdraw another's signup,
                           or operation status blocks withdrawal.
    """
    with database.transaction() as db:
        # Resolve actor.
        actor = repositories.get_user_by_id(db, actor_user_id)
        if not actor:
            raise NotFoundError("Actor user not found.")
        membership = repositories.get_workspace_membership(db, guild_workspace_id, actor_user_id)

        # Fetch and validate the signup before the permission check so that
        # 'not found' errors take priority over 'permission denied' errors.
        signup = repositories.get_signup_intent_by_id(db, signup_id, guild_workspace_id)
        if not signup or signup["guild_operation_id"] != guild_operation_id:
            raise NotFoundError("Signup not found.")

        # Operation status gate.
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError("Operation not found.")
        if op["status"] not in _SIGNUP_WITHDRAWAL_ALLOWED_STATUSES:
            status = op["status"]
            raise ConflictError(
                f"Signup withdrawal is not allowed when the operation status is '{status}'."
            )

        # Already withdrawn?
        if signup["withdrawn_at"] is not None:
            raise ConflictError("This signup has already been withdrawn.")

        # Permission check.
        # Officers and owners may withdraw any signup.
        # Members and non-members (visitors) may only withdraw their own.
        actor_role = membership["role"] if membership else None
        is_privileged = actor_role in workspace_membership.MUTATOR_ROLES

        if not is_privileged:
            # Ownership: use the mechanism that matches how this signup was created.
            # "web:{user_id}" signups — ID-only check, no display-name fallback.
            #   This makes display-name collisions harmless for any signup that
            #   carries an embedded user ID.
            # "web" / "discord" / legacy signups — display-name fallback only;
            #   these pre-date the ID-stamping change.
            source = signup.get("source") or ""
            if source.startswith("web:"):
                if source != f"web:{actor_user_id}":
                    raise PermissionDenied("You can only withdraw your own signup.")
            else:
                participant = repositories.get_participant(
                    db, signup["participant_id"], guild_workspace_id
                )
                if not participant or participant["display_name"] != actor["display_name"]:
                    raise PermissionDenied("You can only withdraw your own signup.")

        # Active assignment guard.
        active_count = repositories.count_active_assignments_for_participant_in_operation(
            db, guild_workspace_id, guild_operation_id, signup["participant_id"]
        )
        if active_count > 0:
            raise ConflictError(
                "Cannot withdraw this signup â€” the participant has an active slot "
                "assignment. Remove the assignment first."
            )

        now = _now()
        repositories.withdraw_signup_intent(db, signup_id, guild_workspace_id, now)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.SIGNUP_INTENT_WITHDRAWN,
            entity_type="signup_intent",
            entity_id=signup_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"participant_id": signup["participant_id"]},
        )
        repositories.insert_operational_event(db, event)


# ---------------------------------------------------------------------------
# Internal helper â€” single slot assignment (no transaction; caller owns it)
# ---------------------------------------------------------------------------

def _execute_single_assignment(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
    slot: dict,
    participant_id: str,
) -> tuple[dict, bool]:
    """
    Insert one assignment row, emit assignment.created, and handle reserve cleanup.

    Called by assign_participant_to_operation_slot (public, one-shot transaction)
    and by quick_assign_slot / quick_fill_party (bulk transaction, multiple calls).

    The slot must already be validated open by the caller.  This helper performs
    the double-assignment guard, the insert, the event emit, and reserve cleanup.

    Returns:
        (assignment dict, reserve_was_removed: bool)

    reserve_was_removed is True when the participant had a reserve row that was
    deleted as part of this assignment.  Callers use this to decide whether to
    recalculate readiness.
    """
    participant = repositories.get_participant(db, participant_id, guild_workspace_id)
    if not participant:
        raise NotFoundError(
            f"Participant '{participant_id}' not found in this workspace."
        )

    # Double-assignment guard: one active assignment per participant per op.
    existing_assignment = repositories.get_active_assignment_for_participant(
        db, guild_operation_id, participant_id, guild_workspace_id
    )
    if existing_assignment:
        raise ConflictError(
            "Participant already has an active assignment in this operation."
        )

    now = _now()
    assignment = {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": guild_workspace_id,
        "guild_operation_id": guild_operation_id,
        "operation_slot_id": slot["id"],
        "participant_id": participant_id,
        # Role and build copied from frozen slot â€” not from signup intent.
        "assigned_role": slot["role"],
        "assigned_build_name": slot["build_name"],
        "status": "assigned",
        "assigned_at": now,
    }
    repositories.insert_assignment(db, assignment)

    event = operational_events.make_event(
        guild_workspace_id=guild_workspace_id,
        guild_operation_id=guild_operation_id,
        event_type=operational_events.ASSIGNMENT_CREATED,
        entity_type="assignment",
        entity_id=assignment["id"],
        payload={
            "operation_slot_id": slot["id"],
            "participant_id": participant_id,
            "assigned_role": slot["role"],
            "assigned_build_name": slot["build_name"],
        },
    )
    repositories.insert_operational_event(db, event)

    # If the participant was on reserve, remove the row automatically so
    # reserve_count stays accurate.  No reserve.removed event is emitted â€”
    # this is a side-effect of assignment, not an independent caller decision.
    reserve_was_removed = False
    existing_reserve = repositories.get_reserve(
        db, guild_workspace_id, guild_operation_id, participant_id
    )
    if existing_reserve:
        repositories.delete_reserve(
            db, guild_workspace_id, guild_operation_id, participant_id
        )
        reserve_was_removed = True

    return assignment, reserve_was_removed


# ---------------------------------------------------------------------------
# 7. Assign Participant to OperationSlot
# ---------------------------------------------------------------------------

def assign_participant_to_operation_slot(
    guild_workspace_id: str,
    guild_operation_id: str,
    operation_slot_id: str,
    participant_id: str,
) -> dict:
    """
    Assign a participant to an operation slot.

    Slot assignment state is determined solely by the assignments table.
    A slot is open when get_active_assignment_for_slot() returns None.
    operation_slots carries no status column â€” it is a frozen snapshot.

    The assigned_role and assigned_build_name are copied from the operation
    slot (the frozen snapshot), not from the signup intent.

    Returns the full assignments row.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_assignment_mutation_allowed(op["status"])

        slot = repositories.get_operation_slot(db, operation_slot_id, guild_workspace_id)
        if not slot:
            raise NotFoundError(
                f"OperationSlot '{operation_slot_id}' not found in this workspace."
            )

        if slot["guild_operation_id"] != guild_operation_id:
            raise ValidationError(
                "OperationSlot does not belong to the specified GuildOperation."
            )

        # Canonical open-slot check: look in assignments table, not operation_slots.
        active = repositories.get_active_assignment_for_slot(db, operation_slot_id)
        mass_planner.validate_slot_is_open(active)

        assignment, _reserve_was_removed = _execute_single_assignment(
            db, guild_workspace_id, guild_operation_id, slot, participant_id
        )

        # Always recalculate — slot fill state changed regardless of reserve cleanup.
        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)

    return assignment


# ---------------------------------------------------------------------------
# 7a. Quick Assign Slot  (speed-assist; caller remains authoritative)
# ---------------------------------------------------------------------------

def quick_assign_slot(
    guild_workspace_id: str,
    guild_operation_id: str,
    operation_slot_id: str,
) -> dict:
    """
    Automatically assign the best-ranked eligible participant to an open slot.

    Ranking (4 tiers â€” see domain/mass_planner.py):
      1. specific willingness + role + build match (exact)
      2. role match (any willingness)
      3. fill willingness, no role match
      4. everyone else

    Tie-breaking within a tier: confirmed availability > tentative, then
    display_name alphabetically.

    Reserved participants are excluded from the candidate pool entirely.
    Raises ConflictError if no eligible candidates are available.

    Emits assignment.created and recalculates readiness within the same
    transaction.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_assignment_mutation_allowed(op["status"])

        slot = repositories.get_operation_slot(db, operation_slot_id, guild_workspace_id)
        if not slot:
            raise NotFoundError(
                f"OperationSlot '{operation_slot_id}' not found in this workspace."
            )

        if slot["guild_operation_id"] != guild_operation_id:
            raise ValidationError(
                "OperationSlot does not belong to the specified GuildOperation."
            )

        active = repositories.get_active_assignment_for_slot(db, operation_slot_id)
        mass_planner.validate_slot_is_open(active)

        # Build candidate pool: signed-up participants with no active assignment.
        all_participants = repositories.get_participants_for_operation(
            db, guild_operation_id, guild_workspace_id
        )
        assigned_ids = {
            v["participant_id"]
            for v in repositories.get_assigned_participants_for_operation(
                db, guild_operation_id, guild_workspace_id
            ).values()
        }
        reserve_ids = {
            r["participant_id"]
            for r in repositories.get_reserves_for_operation(
                db, guild_operation_id, guild_workspace_id
            )
        }
        unassigned = [p for p in all_participants if p["id"] not in assigned_ids]

        signups = repositories.get_signup_intents(db, guild_operation_id, guild_workspace_id)
        signup_prefs = {s["participant_id"]: s for s in signups}

        best = select_best_candidate(slot, unassigned, signup_prefs, reserve_ids)
        if best is None:
            raise ConflictError(
                f"No eligible participants available for slot '{operation_slot_id}'."
            )

        assignment, _ = _execute_single_assignment(
            db, guild_workspace_id, guild_operation_id, slot, best["id"]
        )

        # Always recalculate readiness â€” slot state and potentially reserve_count changed.
        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)

    return assignment


# ---------------------------------------------------------------------------
# 7b. Quick Fill Party  (speed-assist; caller remains authoritative)
# ---------------------------------------------------------------------------

def quick_fill_party(
    guild_workspace_id: str,
    guild_operation_id: str,
    party_number: int,
) -> dict:
    """
    Iterate all open slots in a party (slot_index order) and assign the best
    available candidate to each.  Candidate pool shrinks after each assignment
    so no participant is double-assigned.

    Reserved participants are excluded from the candidate pool entirely.

    If a slot has no eligible candidate it is skipped silently.
    If no slots are filled the return dict has filled_count=0 (no error raised).

    Emits one assignment.created per filled slot.  Readiness is recalculated
    once at the end of the transaction.

    Returns:
        {"filled_count": N, "total_open": M, "party_number": party_number}
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_assignment_mutation_allowed(op["status"])

        # Load all slots for this party, ordered by slot_index.
        all_slots = repositories.get_operation_slots(db, guild_operation_id, guild_workspace_id)
        party_slots = sorted(
            [s for s in all_slots if s["party_number"] == party_number],
            key=lambda s: s["slot_index"],
        )
        if not party_slots:
            raise NotFoundError(
                f"Party {party_number} has no slots in this operation."
            )

        assigned_map = repositories.get_assigned_participants_for_operation(
            db, guild_operation_id, guild_workspace_id
        )
        open_slots = [s for s in party_slots if s["id"] not in assigned_map]

        if not open_slots:
            return {"filled_count": 0, "total_open": 0, "party_number": party_number}

        # Build shared candidate pool: signed-up + unassigned + not reserved.
        all_participants = repositories.get_participants_for_operation(
            db, guild_operation_id, guild_workspace_id
        )
        assigned_ids: set[str] = {v["participant_id"] for v in assigned_map.values()}
        reserve_ids = {
            r["participant_id"]
            for r in repositories.get_reserves_for_operation(
                db, guild_operation_id, guild_workspace_id
            )
        }
        # Mutable pool: shrinks as candidates are assigned.
        available = [p for p in all_participants if p["id"] not in assigned_ids]

        signups = repositories.get_signup_intents(db, guild_operation_id, guild_workspace_id)
        signup_prefs = {s["participant_id"]: s for s in signups}

        filled_count = 0
        for slot in open_slots:
            best = select_best_candidate(slot, available, signup_prefs, reserve_ids)
            if best is None:
                continue  # No candidate for this slot â€” skip silently.

            _execute_single_assignment(
                db, guild_workspace_id, guild_operation_id, slot, best["id"]
            )
            filled_count += 1
            # Remove from pool so the same participant isn't assigned twice.
            available = [p for p in available if p["id"] != best["id"]]

        # Single readiness recalculation for the whole batch.
        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)

    return {
        "filled_count": filled_count,
        "total_open": len(open_slots),
        "party_number": party_number,
    }


# ---------------------------------------------------------------------------
# 9. Record Attendance
# ---------------------------------------------------------------------------

def record_attendance(
    guild_workspace_id: str,
    guild_operation_id: str,
    assignment_id: str,
    status: str,
    notes: str | None = None,
) -> dict:
    """
    Mark or update the attendance status for one assigned participant.

    Rules:
    - Only active assignments (status='assigned') are eligible.
    - Re-marking is an upsert: updates the existing row, does NOT insert a new one.
    - Every call emits an attendance.recorded event.
    - Re-marks include previous_status in the event payload.
    """
    attendance_domain.validate_attendance_status(status)

    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(f"GuildOperation {guild_operation_id!r} not found.")

        guild_operations.validate_attendance_recording_allowed(op["status"])

        assignment = repositories.get_assignment_by_id(db, assignment_id, guild_workspace_id)
        if not assignment:
            raise NotFoundError(f"Assignment {assignment_id!r} not found.")

        if assignment["guild_operation_id"] != guild_operation_id:
            raise WorkspaceBoundaryViolation("Assignment does not belong to this operation.")

        if assignment["status"] != "assigned":
            raise ConflictError(
                f"Cannot record attendance for an assignment with status '{assignment['status']}'."
            )

        now = _now()
        existing = repositories.get_attendance_record(
            db, guild_workspace_id, guild_operation_id, assignment_id
        )
        previous_status: str | None = None

        if existing:
            previous_status = existing["status"]
            repositories.update_attendance_record(db, existing["id"], status, notes, now)
            record: dict = {**existing, "status": status, "notes": notes, "updated_at": now}
        else:
            record = {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": guild_workspace_id,
                "guild_operation_id": guild_operation_id,
                "assignment_id": assignment_id,
                "participant_id": assignment["participant_id"],
                "status": status,
                "notes": notes,
                "recorded_at": now,
                "updated_at": now,
            }
            repositories.insert_attendance_record(db, record)

        payload: dict = {
            "assignment_id": assignment_id,
            "participant_id": assignment["participant_id"],
            "status": status,
        }
        if previous_status is not None:
            payload["previous_status"] = previous_status

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.ATTENDANCE_RECORDED,
            entity_type="attendance_record",
            entity_id=record["id"],
            payload=payload,
        )
        repositories.insert_operational_event(db, event)
        return record


def bulk_mark_present(
    guild_workspace_id: str,
    guild_operation_id: str,
) -> int:
    """
    Mark all active (status='assigned') assignments that have no attendance
    record yet as 'present'.

    Rules:
    - Uses the same status gate as record_attendance: only locked/completed.
    - Already-marked rows are skipped â€” existing records are never overwritten.
    - Non-active assignments (status != 'assigned') are excluded by the
      underlying query and are never touched.
    - Emits attendance.recorded for every newly-created record.
    - All inserts happen in a single transaction: failure rolls back entirely.

    Returns the number of records created (0 when all rows are already marked).
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(f"GuildOperation {guild_operation_id!r} not found.")

        guild_operations.validate_attendance_recording_allowed(op["status"])

        rows = repositories.get_assignments_with_attendance(
            db, guild_operation_id, guild_workspace_id
        )
        unmarked = [r for r in rows if r["attendance_status"] is None]

        now = _now()
        count = 0

        for asgn in unmarked:
            record_id = str(uuid.uuid4())
            record = {
                "id": record_id,
                "guild_workspace_id": guild_workspace_id,
                "guild_operation_id": guild_operation_id,
                "assignment_id": asgn["assignment_id"],
                "participant_id": asgn["participant_id"],
                "status": "present",
                "notes": None,
                "recorded_at": now,
                "updated_at": now,
            }
            repositories.insert_attendance_record(db, record)

            event = operational_events.make_event(
                guild_workspace_id=guild_workspace_id,
                guild_operation_id=guild_operation_id,
                event_type=operational_events.ATTENDANCE_RECORDED,
                entity_type="attendance_record",
                entity_id=record_id,
                payload={
                    "assignment_id": asgn["assignment_id"],
                    "participant_id": asgn["participant_id"],
                    "status": "present",
                },
            )
            repositories.insert_operational_event(db, event)
            count += 1

        return count


# ---------------------------------------------------------------------------
# Internal helper â€” readiness recalculation (no transaction; caller owns it)
# ---------------------------------------------------------------------------

def _recalculate_readiness(
    db: sqlite3.Connection,
    guild_workspace_id: str,
    guild_operation_id: str,
) -> dict:
    """
    Compute and persist a readiness snapshot inside the *caller's* transaction.

    Called by calculate_readiness_snapshot (public use case) and by
    remove_assignment so that both the removal and the new snapshot land in
    the same atomic commit.

    Returns the full readiness_snapshots dict.
    """
    all_slots = repositories.get_operation_slots(db, guild_operation_id, guild_workspace_id)
    if not all_slots:
        raise ConflictError(
            "Cannot recalculate readiness before operation slots have been generated."
        )

    assigned_ids = repositories.get_assigned_slot_ids(db, guild_operation_id, guild_workspace_id)
    unassigned_count = repositories.count_unassigned_signups(
        db, guild_operation_id, guild_workspace_id
    )
    att_marked = repositories.count_attendance_marked(
        db, guild_operation_id, guild_workspace_id
    )
    scout_counts = repositories.get_scout_attendance_counts(
        db, guild_operation_id, guild_workspace_id
    )
    reserve_count = repositories.count_reserves_for_operation(
        db, guild_operation_id, guild_workspace_id
    )

    snapshot_data = readiness.build_readiness_snapshot(
        slots=all_slots,
        assigned_slot_ids=assigned_ids,
        unassigned_signup_count=unassigned_count,
        attendance_marked_count=att_marked,
        scout_count=scout_counts["scout"],
        support_count=scout_counts["support"],
        reserve_count=reserve_count,
    )

    now = _now()
    snapshot = {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": guild_workspace_id,
        "guild_operation_id": guild_operation_id,
        **snapshot_data,
        "created_at": now,
    }
    repositories.insert_readiness_snapshot(db, snapshot)

    event = operational_events.make_event(
        guild_workspace_id=guild_workspace_id,
        guild_operation_id=guild_operation_id,
        event_type=operational_events.READINESS_SNAPSHOT_CREATED,
        entity_type="readiness_snapshot",
        entity_id=snapshot["id"],
        payload={
            "readiness_state": snapshot["readiness_state"],
            "total_slots": snapshot["total_slots"],
            "assigned_slots": snapshot["assigned_slots"],
        },
    )
    repositories.insert_operational_event(db, event)
    return snapshot


# ---------------------------------------------------------------------------
# 8. Calculate ReadinessSnapshot
# ---------------------------------------------------------------------------

def calculate_readiness_snapshot(
    guild_workspace_id: str,
    guild_operation_id: str,
) -> dict:
    """
    Compute and persist a point-in-time readiness snapshot.

    Slot assignment state is derived from the assignments table via
    get_assigned_slot_ids() â€” no status column on operation_slots.

    Returns the full readiness_snapshots row.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_readiness_recalculation_allowed(op["status"])
        return _recalculate_readiness(db, guild_workspace_id, guild_operation_id)


# ---------------------------------------------------------------------------
# 11. Remove Assignment
# ---------------------------------------------------------------------------

def remove_assignment(
    guild_workspace_id: str,
    guild_operation_id: str,
    assignment_id: str,
) -> dict:
    """
    Mark an active assignment as 'removed' (soft delete).

    The row is kept so historical records and attendance links remain valid.
    Readiness is recalculated within the same transaction so the snapshot
    immediately reflects the freed slot.

    Emits assignment.removed then readiness_snapshot.created in one commit.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_assignment_mutation_allowed(op["status"])

        # Load by id + workspace â€” first boundary check.
        assignment = repositories.get_assignment_by_id(db, assignment_id, guild_workspace_id)
        if not assignment:
            raise NotFoundError(f"Assignment {assignment_id!r} not found.")

        # Second boundary check: assignment must belong to the requested operation.
        if assignment["guild_operation_id"] != guild_operation_id:
            raise WorkspaceBoundaryViolation(
                "Assignment does not belong to this operation."
            )

        # Status guard: only active assignments may be removed.
        if assignment["status"] != "assigned":
            raise ConflictError(
                f"Cannot remove an assignment with status '{assignment['status']}'."
            )

        # UPDATE is scoped by id + workspace + operation â€” belt-and-suspenders.
        repositories.set_assignment_status(
            db, assignment_id, guild_operation_id, "removed", guild_workspace_id
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.ASSIGNMENT_REMOVED,
            entity_type="assignment",
            entity_id=assignment_id,
            payload={
                "operation_slot_id": assignment["operation_slot_id"],
                "participant_id":    assignment["participant_id"],
            },
        )
        repositories.insert_operational_event(db, event)

        # Recalculate readiness atomically â€” freed slot is reflected immediately.
        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)

    return {**assignment, "status": "removed"}


def reassign_slot(
    guild_workspace_id: str,
    guild_operation_id: str,
    operation_slot_id: str,
    new_participant_id: str,
) -> dict:
    """Atomic swap: soft-remove any active assignment then assign a new participant.

    Combines the remove + assign in a single transaction so the slot is never
    in an intermediate unassigned state visible to concurrent readers.

    If the slot already has no active assignment the remove step is skipped and
    this behaves as a plain assign.  This is intentional: calling reassign on
    an open slot is valid and produces the expected outcome.

    Snapshot invariant: operation_slots is never mutated — only the assignments
    table changes.  The frozen slot identity (role, build) is preserved.

    Returns the new assignment row.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_assignment_mutation_allowed(op["status"])

        slot = repositories.get_operation_slot(db, operation_slot_id, guild_workspace_id)
        if not slot:
            raise NotFoundError(
                f"OperationSlot '{operation_slot_id}' not found in this workspace."
            )
        if slot["guild_operation_id"] != guild_operation_id:
            raise ValidationError(
                "OperationSlot does not belong to the specified GuildOperation."
            )

        # Soft-remove the existing assignment if one is active.
        existing = repositories.get_active_assignment_for_slot(db, operation_slot_id)
        if existing:
            if existing.get("guild_workspace_id") not in (guild_workspace_id, None):
                raise WorkspaceBoundaryViolation(
                    "Existing assignment does not belong to this workspace."
                )
            repositories.set_assignment_status(
                db, existing["id"], guild_operation_id, "removed", guild_workspace_id
            )
            rm_event = operational_events.make_event(
                guild_workspace_id=guild_workspace_id,
                guild_operation_id=guild_operation_id,
                event_type=operational_events.ASSIGNMENT_REMOVED,
                entity_type="assignment",
                entity_id=existing["id"],
                payload={
                    "operation_slot_id": operation_slot_id,
                    "participant_id":    existing["participant_id"],
                    "reason":            "reassign",
                },
            )
            repositories.insert_operational_event(db, rm_event)

        # Assign the replacement participant.
        assignment, _reserve_removed = _execute_single_assignment(
            db, guild_workspace_id, guild_operation_id, slot, new_participant_id
        )

        # Single readiness recalculation covers both the remove and the assign.
        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)

    return assignment


# ---------------------------------------------------------------------------
# 12. Mark Participant as Reserve
# ---------------------------------------------------------------------------

def mark_participant_as_reserve(
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
    notes: str | None = None,
) -> dict:
    """
    Place a signed-up, unassigned participant on the reserve/bench list.

    Rejects if:
    - Participant has no signup intent for this operation.
    - Participant has an active assignment in this operation.
    - Participant is already on reserve.

    Reserve and assignment can overlap in one direction only:
    reserve â†’ assignment is allowed (assigning a reserved player keeps the
    reserve row).  assignment â†’ reserve is rejected by the active-assignment
    guard above.

    Emits reserve.created and recalculates readiness within the same
    transaction.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_reserve_mutation_allowed(op["status"])

        participant = repositories.get_participant(db, participant_id, guild_workspace_id)
        if not participant:
            raise NotFoundError(
                f"Participant '{participant_id}' not found in this workspace."
            )

        signup = repositories.get_signup_intent(
            db, guild_operation_id, participant_id, guild_workspace_id
        )
        if not signup:
            raise ConflictError(
                "Participant has no signup intent for this operation and cannot be placed on reserve."
            )

        active_assignment = repositories.get_active_assignment_for_participant(
            db, guild_operation_id, participant_id, guild_workspace_id
        )
        if active_assignment:
            raise ConflictError(
                "Participant has an active assignment and cannot be placed on reserve. "
                "Remove the assignment first."
            )

        existing_reserve = repositories.get_reserve(
            db, guild_workspace_id, guild_operation_id, participant_id
        )
        if existing_reserve:
            raise ConflictError(
                "Participant is already on reserve for this operation."
            )

        now = _now()
        reserve = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "participant_id": participant_id,
            "notes": notes,
            "created_at": now,
        }
        repositories.insert_reserve(db, reserve)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.RESERVE_CREATED,
            entity_type="operation_reserve",
            entity_id=reserve["id"],
            payload={
                "participant_id": participant_id,
                "display_name": participant["display_name"],
            },
        )
        repositories.insert_operational_event(db, event)

        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)

    return reserve


# ---------------------------------------------------------------------------
# 13. Remove Reserve
# ---------------------------------------------------------------------------

def remove_reserve(
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
) -> None:
    """
    Remove a participant from the reserve/bench list.

    Returns participant to normal unassigned signup state.  Does not affect
    any existing assignment â€” if the participant was later assigned while on
    reserve, the assignment remains.

    Emits reserve.removed and recalculates readiness within the same
    transaction.
    """
    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"GuildOperation '{guild_operation_id}' not found in this workspace."
            )

        guild_operations.validate_reserve_mutation_allowed(op["status"])

        reserve = repositories.get_reserve(
            db, guild_workspace_id, guild_operation_id, participant_id
        )
        if not reserve:
            raise NotFoundError(
                f"Participant '{participant_id}' is not on reserve for this operation."
            )

        repositories.delete_reserve(
            db, guild_workspace_id, guild_operation_id, participant_id
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.RESERVE_REMOVED,
            entity_type="operation_reserve",
            entity_id=reserve["id"],
            payload={"participant_id": participant_id},
        )
        repositories.insert_operational_event(db, event)

        _recalculate_readiness(db, guild_workspace_id, guild_operation_id)


# ---------------------------------------------------------------------------
# 10. Record Scout / Support Attendance
# ---------------------------------------------------------------------------

def record_scout_attendance(
    guild_workspace_id: str,
    guild_operation_id: str,
    display_name: str,
    role_type: str,
    notes: str | None = None,
) -> dict:
    """
    Check in a participant as scout or support for an operation.

    Rules:
    - Not linked to any assignment â€” any display_name may check in.
    - Participant is found-or-created by display_name within the workspace.
    - Re-checking-in is an upsert: updates the existing row, does NOT insert
      a second row.
    - Every call emits a scout_attendance.recorded or support_attendance.recorded
      event (chosen by role_type).
    - Re-checks include previous_role_type in the event payload (always).
    - Re-checks include previous_notes in the event payload only when notes changed.
    """
    scout_attendance_domain.validate_role_type(role_type)

    with database.transaction() as db:
        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(f"GuildOperation {guild_operation_id!r} not found.")

        guild_operations.validate_scout_attendance_recording_allowed(op["status"])

        participant = repositories.find_or_create_participant(
            db, guild_workspace_id, display_name.strip()
        )

        now = _now()
        existing = repositories.get_scout_attendance_record(
            db, guild_workspace_id, guild_operation_id, participant["id"]
        )
        previous_role_type: str | None = None
        previous_notes_value: str | None = None
        notes_changed = False

        if existing:
            previous_role_type = existing["role_type"]
            if existing["notes"] != notes:
                notes_changed = True
                previous_notes_value = existing["notes"]
            repositories.update_scout_attendance_record(
                db, existing["id"], role_type, notes, now
            )
            record: dict = {
                **existing,
                "role_type": role_type,
                "notes": notes,
                "updated_at": now,
            }
        else:
            record = {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": guild_workspace_id,
                "guild_operation_id": guild_operation_id,
                "participant_id": participant["id"],
                "role_type": role_type,
                "notes": notes,
                "recorded_at": now,
                "updated_at": now,
            }
            repositories.insert_scout_attendance_record(db, record)

        event_type = (
            operational_events.SCOUT_ATTENDANCE_RECORDED
            if role_type == "scout"
            else operational_events.SUPPORT_ATTENDANCE_RECORDED
        )

        payload: dict = {
            "participant_id": participant["id"],
            "display_name": participant["display_name"],
            "role_type": role_type,
        }
        if previous_role_type is not None:
            payload["previous_role_type"] = previous_role_type
        if notes_changed:
            payload["previous_notes"] = previous_notes_value

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=event_type,
            entity_type="scout_attendance_record",
            entity_id=record["id"],
            payload=payload,
        )
        repositories.insert_operational_event(db, event)
        return record


# ---------------------------------------------------------------------------
# Discord workspace configuration
# ---------------------------------------------------------------------------

def update_workspace_discord_config(
    guild_workspace_id: str,
    actor_id: str,
    discord_guild_id: str | None,
    announcement_channel_id: str | None,
    officer_channel_id: str | None,
    auto_dispatch: bool = False,
    reminders_enabled: bool = False,
) -> dict:
    """
    Update the Discord server, channel IDs, auto-dispatch flag, and reminders
    opt-in stored on a workspace.

    All channel fields are optional; passing None or empty string clears the
    stored value.  discord_guild_id must be unique across all workspaces.
    auto_dispatch enables automatic readiness summary posting (readiness_snapshot.created
    events only); announcements and rosters remain explicit officer actions.
    reminders_enabled enables the send_operation_reminders scheduler job for
    this workspace (T-2h and T-30m posts to announcement/officer channel).

    The route is responsible for enforcing owner/officer access before
    calling this use case.
    """
    guild_id, ann_id, off_id = guild_workspace.validate_discord_config(
        discord_guild_id, announcement_channel_id, officer_channel_id
    )

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        if guild_id and guild_id != ws.get("discord_guild_id"):
            existing = repositories.get_workspace_by_discord_guild_id(db, guild_id)
            if existing and existing["id"] != guild_workspace_id:
                raise ConflictError(
                    "This Discord server is already linked to another workspace."
                )

        repositories.update_workspace_discord_config(
            db, guild_workspace_id, guild_id, ann_id, off_id,
            auto_dispatch=auto_dispatch,
            reminders_enabled=reminders_enabled,
        )

        updated_ws = repositories.get_workspace_by_id(db, guild_workspace_id)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.WORKSPACE_DISCORD_CONFIG_UPDATED,
            entity_type="guild_workspace",
            entity_id=guild_workspace_id,
            actor_type="user",
            actor_id=actor_id,
            payload={
                "discord_guild_id": guild_id,
                "announcement_channel_id": ann_id,
                "officer_channel_id": off_id,
                "auto_dispatch": auto_dispatch,
                "reminders_enabled": reminders_enabled,
            },
        )
        repositories.insert_operational_event(db, event)

    return updated_ws


# ---------------------------------------------------------------------------
# Discord metadata cache â€” best-effort REST fetch, never blocks domain writes
# ---------------------------------------------------------------------------

_METADATA_CACHE_TTL_HOURS = 24


def refresh_discord_metadata(guild_workspace_id: str) -> dict:
    """
    Fetch guild and channel names from Discord REST and upsert into
    discord_metadata_cache.

    Design rules:
    - Called after Discord settings save or from the manual refresh route.
    - Each REST call is wrapped independently â€” a channel fetch failure does
      not abort the guild fetch, and vice versa.
    - Domain DB transactions (config saves) are never rolled back by this
      function: callers must invoke it AFTER their own transaction has
      committed.
    - DISCORD_BOT_TOKEN must be set; if missing, raises DiscordApiError before
      any fetch is attempted.
    - On 404 the stale cache row is preserved (not deleted) â€” a stale name
      is better than no name.  Only successful fetches write new rows.

    Returns a result summary dict:
      {
        "guild":    "ok" | "skipped" | "error:<message>",
        "channels": {"<snowflake>": "ok" | "skipped" | "error:<message>", ...},
      }
    """
    import json as _json  # noqa: PLC0415
    from app.discord import rest_client  # noqa: PLC0415

    result: dict = {"guild": "skipped", "channels": {}}

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
    if not ws:
        raise NotFoundError("Workspace not found.")

    now = _now()

    def _upsert(entity_type: str, discord_entity_id: str, name: str, extra: dict) -> None:
        with database.transaction() as db:
            repositories.upsert_discord_metadata(db, {
                "id":                 str(uuid.uuid4()),
                "guild_workspace_id": guild_workspace_id,
                "entity_type":        entity_type,
                "discord_entity_id":  discord_entity_id,
                "name":               name,
                "extra_json":         _json.dumps(extra),
                "fetched_at":         now,
            })

    # --- Guild ---
    guild_id = ws.get("discord_guild_id")
    if guild_id:
        try:
            guild_data = rest_client.fetch_guild_metadata(guild_id)
            _upsert("guild", guild_id, guild_data["name"], {"icon_hash": guild_data.get("icon_hash")})
            result["guild"] = "ok"
        except Exception as exc:  # noqa: BLE001
            result["guild"] = f"error:{exc}"

    # --- Channels ---
    for channel_id in filter(None, [
        ws.get("discord_announcement_channel_id"),
        ws.get("discord_officer_channel_id"),
    ]):
        if channel_id in result["channels"]:
            continue
        try:
            ch_data = rest_client.fetch_channel_metadata(channel_id)
            _upsert("channel", channel_id, ch_data["name"], {"channel_type": ch_data["channel_type"]})
            result["channels"][channel_id] = "ok"
        except Exception as exc:  # noqa: BLE001
            result["channels"][channel_id] = f"error:{exc}"

    return result


# ---------------------------------------------------------------------------
# Discord member nickname sync (system actor)
# ---------------------------------------------------------------------------

def sync_discord_member_nicknames_system(guild_workspace_id: str) -> dict:
    """Refresh cached Discord server nicknames for one workspace's guild.

    System actor (no RBAC). Reads GET /guilds/{id}/members (requires the
    privileged Server Members Intent) and:
      1. Upserts every member's nick/global_name/username into
         discord_member_cache.
      2. Updates users.display_name to the member's effective in-game name
         (nickname > global_name > username) for Ironkeep users whose ONLY
         auth identity is Discord — mirroring discord_oauth_login's rule that
         linked (dev+discord) users keep their guild display name.

    Two-phase: the REST call runs outside any DB transaction; DB writes happen
    afterwards. A missing guild link, missing bot token, or a Discord error
    (e.g. the intent is not enabled) is non-fatal and reported in the summary.

    Returns:
      {"members_fetched": N, "cached": N, "names_updated": N, "status": "ok"|"skipped:..."|"error:..."}
    """
    from app.discord import rest_client  # noqa: PLC0415

    result = {"members_fetched": 0, "cached": 0, "names_updated": 0, "status": "skipped"}

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
    if not ws:
        raise NotFoundError("Workspace not found.")

    guild_id = ws.get("discord_guild_id")
    if not guild_id:
        result["status"] = "skipped:no_discord_guild"
        return result

    # Phase 1: REST fetch (outside any DB transaction).
    try:
        members = rest_client.fetch_guild_members(guild_id)
    except Exception as exc:  # noqa: BLE001 — non-fatal, reported to caller
        result["status"] = f"error:{exc}"
        return result

    result["members_fetched"] = len(members)
    now = _now()

    # Phase 2: DB writes.
    with database.transaction() as db:
        for m in members:
            discord_uid = m["discord_user_id"]
            repositories.upsert_discord_member_nick(
                db,
                guild_workspace_id=guild_workspace_id,
                discord_user_id=discord_uid,
                nickname=m.get("nickname"),
                global_name=m.get("global_name"),
                username=m.get("username"),
                fetched_at=now,
            )
            result["cached"] += 1

            effective = m.get("nickname") or m.get("global_name") or m.get("username")
            if not effective:
                continue

            user = repositories.get_user_by_provider_identity(
                db, users.DISCORD_AUTH_PROVIDER, discord_uid
            )
            if not user:
                continue

            # Only auto-set the name for pure-Discord accounts (skip linked
            # dev+discord users, matching discord_oauth_login policy).
            identities = repositories.get_auth_identities_for_user(db, user["id"])
            providers = {i["auth_provider"] for i in identities}
            if users.DEV_AUTH_PROVIDER in providers:
                continue

            if user["display_name"] != effective:
                db.execute(
                    "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
                    (effective, now, user["id"]),
                )
                result["names_updated"] += 1

    result["status"] = "ok"
    return result


# ---------------------------------------------------------------------------
# Discord announcement â€” explicit officer post action
# ---------------------------------------------------------------------------

def post_discord_announcement(
    guild_workspace_id: str,
    guild_operation_id: str,
    actor_id: str,
    signup_url: str | None = None,
) -> dict:
    """
    Post (or update) the operation announcement message on Discord.

    This is an EXPLICIT officer action triggered from the web UI.
    It must NOT be called automatically from lifecycle events.

    Flow (two-phase to avoid holding a DB connection during the network call):

    Phase 1 â€” read:
      Validate actor permission, Discord config, operation existence.
      Check for an existing discord_messages row to decide post vs. edit.

    REST call (outside any transaction):
      post_message() for first post â†’ returns discord_message_id.
      edit_message() for subsequent updates.
      DiscordApiError propagates to caller on failure; Phase 2 is skipped.

    Phase 2 â€” write (only reached on REST success):
      Upsert discord_messages row.
      Emit discord_announcement.posted or discord_announcement.updated.

    Returns a dict with keys:
      action           â€” "posted" | "updated"
      discord_message_id â€” the Discord snowflake message ID
    """
    import os  # noqa: PLC0415
    from app.discord import rest_client  # noqa: PLC0415 â€” deferred to allow mocking in tests
    from app.discord.formatters import format_operation_announcement  # noqa: PLC0415

    # ------------------------------------------------------------------
    # Phase 1: read all needed data
    # ------------------------------------------------------------------
    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_id
        )
        if not membership or membership["role"] not in ("owner", "officer"):
            raise PermissionDenied(
                "Only workspace owners and officers can post Discord announcements."
            )

        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        channel_id = ws.get("discord_announcement_channel_id")
        discord_guild_id = ws.get("discord_guild_id")
        if not discord_guild_id or not channel_id:
            raise ValidationError(
                "Discord server and announcement channel must be configured "
                "in Workspace Settings before posting."
            )

        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"Operation '{guild_operation_id}' not found in this workspace."
            )

        readiness = repositories.get_latest_readiness_snapshot(
            db, guild_operation_id, guild_workspace_id
        )
        existing_msg = repositories.get_discord_message(
            db, guild_workspace_id, guild_operation_id, "announcement"
        )


    # ------------------------------------------------------------------
    # Format payload (pure, no DB or API)
    # signup_url links Discord users to the web signup page.
    # Prefer the caller-supplied URL (built from request.base_url at the
    # route layer); fall back to WEB_BASE_URL env var for non-HTTP callers
    # such as the Discord bot adapter.
    # ------------------------------------------------------------------
    if signup_url is None:
        web_base_url = os.environ.get("WEB_BASE_URL", "").rstrip("/")
        signup_url = (
            f"{web_base_url}/workspaces/{ws['slug']}/operations/{guild_operation_id}/signup"
            if web_base_url else None
        )
    payload = format_operation_announcement(op, readiness, signup_url=signup_url)
    # ------------------------------------------------------------------
    # REST call â€” outside any DB transaction
    # DiscordApiError propagates to the caller; Phase 2 is skipped entirely.
    # ------------------------------------------------------------------
    is_edit = bool(existing_msg and not existing_msg.get("is_deleted"))

    if is_edit:
        rest_client.edit_message(channel_id, existing_msg["discord_message_id"], payload)
        discord_message_id = existing_msg["discord_message_id"]
        event_type = operational_events.DISCORD_ANNOUNCEMENT_UPDATED
        action = "updated"
    else:
        discord_message_id = rest_client.post_message(channel_id, payload)
        event_type = operational_events.DISCORD_ANNOUNCEMENT_POSTED
        action = "posted"

    # ------------------------------------------------------------------
    # Phase 2: persist message identity + emit audit event
    # Reached only when the REST call succeeded.
    # ------------------------------------------------------------------
    now = _now()
    with database.transaction() as db:
        repositories.upsert_discord_message(db, {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "message_type":       "announcement",
            "discord_channel_id": channel_id,
            "discord_message_id": discord_message_id,
            "discord_guild_id":   discord_guild_id,
            "posted_at":          now,
            "last_edited_at":     now,
            "is_deleted":         0,
        })

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=event_type,
            entity_type="guild_operation",
            entity_id=guild_operation_id,
            actor_type="user",
            actor_id=actor_id,
            payload={
                "discord_message_id": discord_message_id,
                "channel_id":         channel_id,
            },
        )
        repositories.insert_operational_event(db, event)

    return {"action": action, "discord_message_id": discord_message_id}


def post_discord_roster(
    guild_workspace_id: str,
    guild_operation_id: str,
    actor_id: str,
) -> dict:
    """
    Post (or update) the operation roster message on Discord.

    Explicit officer action only â€” never called automatically on assignment changes.
    Reflects the current OperationSlots + active Assignments at call time.

    Two-phase DB pattern identical to post_discord_announcement:
    Phase 1 â†’ read, REST call (outside transaction), Phase 2 â†’ write.
    DiscordApiError propagates to caller; Phase 2 is skipped on failure.

    Returns {"action": "posted"|"updated", "discord_message_id": str}.
    """
    import os  # noqa: PLC0415
    from app.discord import rest_client  # noqa: PLC0415
    from app.discord.formatters import format_roster  # noqa: PLC0415

    # ------------------------------------------------------------------
    # Phase 1: read all needed data
    # ------------------------------------------------------------------
    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_id
        )
        if not membership or membership["role"] not in ("owner", "officer"):
            raise PermissionDenied(
                "Only workspace owners and officers can post Discord rosters."
            )

        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        channel_id = ws.get("discord_announcement_channel_id")
        discord_guild_id = ws.get("discord_guild_id")
        if not discord_guild_id or not channel_id:
            raise ValidationError(
                "Discord server and announcement channel must be configured "
                "in Workspace Settings before posting."
            )

        op = repositories.get_guild_operation(db, guild_operation_id, guild_workspace_id)
        if not op:
            raise NotFoundError(
                f"Operation '{guild_operation_id}' not found in this workspace."
            )

        slots = repositories.get_operation_slots(db, guild_operation_id, guild_workspace_id)
        assigned_map = repositories.get_assigned_participants_for_operation(
            db, guild_operation_id, guild_workspace_id
        )
        existing_msg = repositories.get_discord_message(
            db, guild_workspace_id, guild_operation_id, "roster"
        )

    # ------------------------------------------------------------------
    # Format payload (pure, no DB or API)
    # ------------------------------------------------------------------
    assignments = [
        {
            "slot_id": slot_id,
            "display_name": info["display_name"],
            "discord_user_id": info.get("discord_user_id"),
        }
        for slot_id, info in assigned_map.items()
    ]
    web_base_url = os.environ.get("WEB_BASE_URL", "").rstrip("/")
    signup_url = (
        f"{web_base_url}/workspaces/{ws['slug']}/operations/{guild_operation_id}/signup"
        if web_base_url else None
    )
    payload = format_roster(op, slots, assignments, signup_url=signup_url)

    # ------------------------------------------------------------------
    # REST call â€” outside any DB transaction
    # DiscordApiError propagates to the caller; Phase 2 is skipped entirely.
    # ------------------------------------------------------------------
    is_edit = bool(existing_msg and not existing_msg.get("is_deleted"))

    if is_edit:
        rest_client.edit_message(channel_id, existing_msg["discord_message_id"], payload)
        discord_message_id = existing_msg["discord_message_id"]
        event_type = operational_events.DISCORD_ROSTER_UPDATED
        action = "updated"
    else:
        discord_message_id = rest_client.post_message(channel_id, payload)
        event_type = operational_events.DISCORD_ROSTER_POSTED
        action = "posted"

    # ------------------------------------------------------------------
    # Phase 2: persist message identity + emit audit event
    # ------------------------------------------------------------------
    now = _now()
    with database.transaction() as db:
        repositories.upsert_discord_message(db, {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "message_type":       "roster",
            "discord_channel_id": channel_id,
            "discord_message_id": discord_message_id,
            "discord_guild_id":   discord_guild_id,
            "posted_at":          now,
            "last_edited_at":     now,
            "is_deleted":         0,
        })

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=event_type,
            entity_type="guild_operation",
            entity_id=guild_operation_id,
            actor_type="user",
            actor_id=actor_id,
            payload={
                "discord_message_id": discord_message_id,
                "channel_id":         channel_id,
            },
        )
        repositories.insert_operational_event(db, event)

    return {"action": action, "discord_message_id": discord_message_id}


# ---------------------------------------------------------------------------
# Albion Online identity — claim / approve / reject / cache refresh
# ---------------------------------------------------------------------------

def claim_albion_character(
    *,
    user_id: str,
    guild_workspace_id: str,
    albion_player_id: str,
) -> dict:
    """
    Submit a pending Albion character claim for the current user.

    Flow (two-phase):
    1. DB: validate membership, resolve any existing claim conflicts.
    2. HTTP: fetch fresh character data from the Albion API.
    3. DB: insert pending claim + upsert character cache + emit event.

    Conflict rules:
    - If the user already has an approved claim in this workspace: raise.
    - If the user has a pending/rejected claim: delete it (allow re-claim).
    - If another user in this workspace has a pending/approved claim for the
      same albion_player_id: raise.
    - If another user has a rejected claim for this albion_player_id in
      the same workspace: delete it so the new user can claim.
    """
    from app.domain import albion_identity as _aid

    pid = _aid.validate_albion_player_id(albion_player_id)

    # ------------------------------------------------------------------
    # Phase 1: DB checks
    # ------------------------------------------------------------------
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        membership = repositories.get_workspace_membership(db, guild_workspace_id, user_id)
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")

        existing_for_user = repositories.get_player_game_identity_for_user(
            db, user_id, guild_workspace_id
        )
        if existing_for_user:
            if existing_for_user["verification_status"] == "approved":
                raise ConflictError(
                    "You already have an approved character in this workspace. "
                    "Contact an officer to revoke it before claiming another."
                )
            repositories.delete_player_game_identity(db, existing_for_user["id"])

        existing_for_char = repositories.get_player_game_identity_by_albion_id(
            db, pid, guild_workspace_id
        )
        if existing_for_char:
            if existing_for_char["verification_status"] in ("pending", "approved"):
                raise ConflictError(
                    "This character is already claimed by another member in this workspace."
                )
            repositories.delete_player_game_identity(db, existing_for_char["id"])

    # ------------------------------------------------------------------
    # Phase 2: Albion API call (outside transaction)
    # ------------------------------------------------------------------
    from app.albion.rest_client import AlbionApiError, fetch_albion_character

    try:
        char_data = fetch_albion_character(pid)
    except AlbionApiError as exc:
        raise ValidationError(
            f"Could not verify character with Albion API: {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # Phase 3: DB write
    # ------------------------------------------------------------------
    now = _now()
    claim_id = str(uuid.uuid4())

    with database.transaction() as db:
        repositories.insert_player_game_identity(db, {
            "id":                  claim_id,
            "guild_workspace_id":  guild_workspace_id,
            "user_id":             user_id,
            "game":                "albion",
            "albion_player_id":    pid,
            "character_name":      char_data["character_name"],
            "verification_status": "pending",
            "claimed_at":          now,
            "reviewed_at":         None,
            "reviewed_by":         None,
            "review_note":         None,
            "created_at":          now,
        })
        repositories.upsert_albion_character_cache(db, {
            "id":               str(uuid.uuid4()),
            "albion_player_id": pid,
            "character_name":   char_data["character_name"],
            "guild_id":         char_data.get("guild_id"),
            "guild_name":       char_data.get("guild_name"),
            "kill_fame":        char_data.get("kill_fame"),
            "death_fame":       char_data.get("death_fame"),
            "extra_json":       char_data.get("extra_json", "{}"),
            "fetched_at":       now,
        })
        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_IDENTITY_CLAIMED,
            entity_type="player_game_identity",
            entity_id=claim_id,
            actor_type="user",
            actor_id=user_id,
            payload={
                "albion_player_id": pid,
                "character_name":   char_data["character_name"],
            },
        )
        repositories.insert_operational_event(db, event)

    return {"claim_id": claim_id, "character_name": char_data["character_name"]}


def approve_albion_character_claim(
    *,
    reviewer_user_id: str,
    target_user_id: str,
    guild_workspace_id: str,
) -> None:
    """
    Approve a pending Albion character claim.

    RBAC:
    - Owners may approve any claim, including their own.
    - Officers may approve any claim EXCEPT their own.
    - Members may not approve.
    """
    now = _now()

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        reviewer_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, reviewer_user_id
        )
        if not reviewer_mem or reviewer_mem["role"] not in ("owner", "officer"):
            raise PermissionDenied(
                "Only officers and owners can approve character claims."
            )

        claim = repositories.get_player_game_identity_for_user(
            db, target_user_id, guild_workspace_id
        )
        if not claim:
            raise NotFoundError("No character claim found for this member.")
        if claim["verification_status"] != "pending":
            raise ValidationError(
                f"Only pending claims can be approved (current status: "
                f"{claim['verification_status']})."
            )

        if claim["user_id"] == reviewer_user_id and reviewer_mem["role"] == "officer":
            raise PermissionDenied(
                "Officers cannot approve their own character claims."
            )

        repositories.update_player_game_identity_status(
            db,
            identity_id=claim["id"],
            status="approved",
            reviewed_by=reviewer_user_id,
            reviewed_at=now,
        )

        # Link the matching imported roster player row, if one exists.
        # Uses WHERE user_id IS NULL — never overwrites an existing link.
        repositories.link_workspace_albion_player_to_user(
            db,
            guild_workspace_id=guild_workspace_id,
            albion_player_id=claim["albion_player_id"],
            user_id=target_user_id,
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_IDENTITY_APPROVED,
            entity_type="player_game_identity",
            entity_id=claim["id"],
            actor_type="user",
            actor_id=reviewer_user_id,
            payload={
                "albion_player_id": claim["albion_player_id"],
                "approved_for":     target_user_id,
                "character_name":   claim["character_name"],
            },
        )
        repositories.insert_operational_event(db, event)


def reject_albion_character_claim(
    *,
    reviewer_user_id: str,
    target_user_id: str,
    guild_workspace_id: str,
    review_note: str = "",
) -> None:
    """
    Reject a pending Albion character claim.

    Officers and owners may reject any pending claim (including their own,
    unlike approve which blocks officer self-approval).
    """
    now = _now()

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        reviewer_mem = repositories.get_workspace_membership(
            db, guild_workspace_id, reviewer_user_id
        )
        if not reviewer_mem or reviewer_mem["role"] not in ("owner", "officer"):
            raise PermissionDenied(
                "Only officers and owners can reject character claims."
            )

        claim = repositories.get_player_game_identity_for_user(
            db, target_user_id, guild_workspace_id
        )
        if not claim:
            raise NotFoundError("No character claim found for this member.")
        if claim["verification_status"] != "pending":
            raise ValidationError(
                f"Only pending claims can be rejected (current status: "
                f"{claim['verification_status']})."
            )

        repositories.update_player_game_identity_status(
            db,
            identity_id=claim["id"],
            status="rejected",
            reviewed_by=reviewer_user_id,
            reviewed_at=now,
            review_note=review_note.strip() or None,
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_IDENTITY_REJECTED,
            entity_type="player_game_identity",
            entity_id=claim["id"],
            actor_type="user",
            actor_id=reviewer_user_id,
            payload={
                "albion_player_id": claim["albion_player_id"],
                "rejected_for":     target_user_id,
                "review_note":      review_note.strip() or None,
            },
        )
        repositories.insert_operational_event(db, event)


def refresh_albion_character_cache(
    *,
    user_id: str,
    guild_workspace_id: str,
) -> dict:
    """
    Refresh the cached Albion character data for the user's claim in this workspace.

    INVARIANT: only updates albion_character_cache.  NEVER mutates
    verification_status, reviewed_at, reviewed_by, or review_note on
    player_game_identities.
    """
    # Phase 1: DB read
    with database.transaction() as db:
        claim = repositories.get_player_game_identity_for_user(
            db, user_id, guild_workspace_id
        )
    if not claim:
        raise NotFoundError("No Albion character claim found for this workspace.")

    # Phase 2: API call (outside transaction)
    from app.albion.rest_client import AlbionApiError, fetch_albion_character

    try:
        char_data = fetch_albion_character(claim["albion_player_id"])
    except AlbionApiError as exc:
        raise ValidationError(
            f"Could not refresh character data from Albion API: {exc}"
        ) from exc

    # Phase 3: DB write — cache only, verification state never touched
    now = _now()
    with database.transaction() as db:
        repositories.upsert_albion_character_cache(db, {
            "id":               str(uuid.uuid4()),
            "albion_player_id": claim["albion_player_id"],
            "character_name":   char_data["character_name"],
            "guild_id":         char_data.get("guild_id"),
            "guild_name":       char_data.get("guild_name"),
            "kill_fame":        char_data.get("kill_fame"),
            "death_fame":       char_data.get("death_fame"),
            "extra_json":       char_data.get("extra_json", "{}"),
            "fetched_at":       now,
        })

    return {
        "refreshed":      True,
        "character_name": char_data["character_name"],
        "fetched_at":     now,
    }


# ---------------------------------------------------------------------------
# Payout ledger use cases
# ---------------------------------------------------------------------------

def create_payout_ledger_entry(
    guild_workspace_id: str,
    guild_operation_id: str,
    participant_id: str,
    entry_type: str,
    amount_silver: int,
    note: str | None,
    actor_user_id: str,
) -> dict:
    """
    Create a new payout ledger entry in status='draft'.

    Permission rules:
    - Officers and owners only.
    - participant_id must belong to the same workspace.
    - guild_operation_id must belong to the same workspace.

    Returns the created entry dict.

    Raises:
        PermissionDenied — caller is not an officer/owner.
        NotFoundError    — operation or participant not found in workspace.
        ValidationError  — invalid entry_type, amount, or note.
    """
    payout_ledger_domain.validate_entry_type(entry_type)
    payout_ledger_domain.validate_amount(entry_type, amount_silver)

    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied(
                "Only officers and owners can create payout ledger entries."
            )

        op = repositories.get_guild_operation(
            db, guild_operation_id, guild_workspace_id
        )
        if not op:
            raise NotFoundError("Operation not found.")

        participant = repositories.get_participant(
            db, participant_id, guild_workspace_id
        )
        if not participant:
            raise NotFoundError("Participant not found in this workspace.")

        now = _now()
        entry_id = str(uuid.uuid4())
        record = {
            "id":                 entry_id,
            "guild_workspace_id": guild_workspace_id,
            "guild_operation_id": guild_operation_id,
            "participant_id":     participant_id,
            "entry_type":         entry_type,
            "amount_silver":      amount_silver,
            "note":               note,
            "status":             "draft",
            "created_by_user_id": actor_user_id,
            "created_at":         now,
            "updated_at":         now,
            "voided_at":          None,
            "voided_by_user_id":  None,
        }
        repositories.insert_payout_ledger_entry(db, record)

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=guild_operation_id,
            event_type=operational_events.PAYOUT_LEDGER_ENTRY_CREATED,
            entity_type="payout_ledger_entry",
            entity_id=entry_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={
                "entry_id":       entry_id,
                "entry_type":     entry_type,
                "amount_silver":  amount_silver,
                "participant_id": participant_id,
                "note":           note,
            },
        )
        repositories.insert_operational_event(db, event)

    return record


def update_payout_ledger_entry(
    guild_workspace_id: str,
    entry_id: str,
    amount_silver: int,
    note: str | None,
    actor_user_id: str,
) -> None:
    """
    Update the amount_silver and/or note on a draft payout ledger entry.

    Only draft entries may be updated.  Approved, paid, and voided entries
    are immutable.

    Permission rules:
    - Officers and owners only.

    Raises:
        PermissionDenied — caller is not an officer/owner.
        NotFoundError    — entry not found in workspace.
        ValidationError  — entry is not draft, or amount is invalid.
    """
    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied(
                "Only officers and owners can update payout ledger entries."
            )

        entry = repositories.get_payout_ledger_entry(
            db, entry_id, guild_workspace_id
        )
        if not entry:
            raise NotFoundError("Payout ledger entry not found.")

        payout_ledger_domain.assert_mutable(entry)
        if entry["status"] != "draft":
            from app.errors import ValidationError as _VE
            raise _VE(
                f"Only draft entries can be updated; this entry is '{entry['status']}'."
            )

        payout_ledger_domain.validate_amount(entry["entry_type"], amount_silver)

        now = _now()
        repositories.update_payout_ledger_entry_draft(
            db, entry_id, guild_workspace_id, amount_silver, note, now
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=entry["guild_operation_id"],
            event_type=operational_events.PAYOUT_LEDGER_ENTRY_UPDATED,
            entity_type="payout_ledger_entry",
            entity_id=entry_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={
                "entry_id":      entry_id,
                "amount_silver": amount_silver,
                "note":          note,
            },
        )
        repositories.insert_operational_event(db, event)


def approve_payout_ledger_entry(
    guild_workspace_id: str,
    entry_id: str,
    actor_user_id: str,
) -> None:
    """
    Approve a draft payout ledger entry (draft → approved).

    Permission rules:
    - Officers and owners only.

    Raises:
        PermissionDenied — caller is not an officer/owner.
        NotFoundError    — entry not found in workspace.
        ValidationError  — entry is not in draft status.
    """
    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied(
                "Only officers and owners can approve payout ledger entries."
            )

        entry = repositories.get_payout_ledger_entry(
            db, entry_id, guild_workspace_id
        )
        if not entry:
            raise NotFoundError("Payout ledger entry not found.")

        payout_ledger_domain.validate_status_transition(entry["status"], "approved")

        now = _now()
        repositories.approve_payout_ledger_entry(
            db, entry_id, guild_workspace_id, now
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=entry["guild_operation_id"],
            event_type=operational_events.PAYOUT_LEDGER_ENTRY_APPROVED,
            entity_type="payout_ledger_entry",
            entity_id=entry_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"entry_id": entry_id},
        )
        repositories.insert_operational_event(db, event)


def void_payout_ledger_entry(
    guild_workspace_id: str,
    entry_id: str,
    actor_user_id: str,
) -> None:
    """
    Void a payout ledger entry.

    Any non-paid entry (draft or approved) may be voided.
    Paid entries are permanent and cannot be voided.
    Already-voided entries raise ValidationError.

    Permission rules:
    - Officers and owners only.

    Raises:
        PermissionDenied — caller is not an officer/owner.
        NotFoundError    — entry not found in workspace.
        ValidationError  — entry is paid or already voided.
    """
    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied(
                "Only officers and owners can void payout ledger entries."
            )

        entry = repositories.get_payout_ledger_entry(
            db, entry_id, guild_workspace_id
        )
        if not entry:
            raise NotFoundError("Payout ledger entry not found.")

        payout_ledger_domain.assert_voidable(entry)

        now = _now()
        repositories.void_payout_ledger_entry(
            db, entry_id, guild_workspace_id, now, actor_user_id
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=entry["guild_operation_id"],
            event_type=operational_events.PAYOUT_LEDGER_ENTRY_VOIDED,
            entity_type="payout_ledger_entry",
            entity_id=entry_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={"entry_id": entry_id},
        )
        repositories.insert_operational_event(db, event)


def mark_payout_ledger_entry_paid(
    guild_workspace_id: str,
    entry_id: str,
    actor_user_id: str,
) -> None:
    """
    Mark an approved payout ledger entry as paid (approved → paid).

    Records paid_at and paid_by_user_id.  Paid entries are terminal —
    no further edits, approvals, or voids are permitted.

    Permission rules:
    - Officers and owners only.

    Raises:
        PermissionDenied — caller is not an officer/owner.
        NotFoundError    — entry not found in workspace.
        ValidationError  — entry is not in 'approved' status (includes
                           draft, already-paid, and voided cases).
    """
    with database.transaction() as db:
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, actor_user_id
        )
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied(
                "Only officers and owners can mark payout ledger entries as paid."
            )

        entry = repositories.get_payout_ledger_entry(
            db, entry_id, guild_workspace_id
        )
        if not entry:
            raise NotFoundError("Payout ledger entry not found.")

        payout_ledger_domain.assert_payable(entry)

        now = _now()
        repositories.mark_payout_ledger_entry_paid(
            db, entry_id, guild_workspace_id, now, actor_user_id
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=entry["guild_operation_id"],
            event_type=operational_events.PAYOUT_LEDGER_ENTRY_PAID,
            entity_type="payout_ledger_entry",
            entity_id=entry_id,
            actor_type="user",
            actor_id=actor_user_id,
            payload={
                "entry_id":      entry_id,
                "entry_type":    entry["entry_type"],
                "amount_silver": entry["amount_silver"],
                "participant_id": entry["participant_id"],
            },
        )
        repositories.insert_operational_event(db, event)


# ---------------------------------------------------------------------------
# Guild roster import  (Phase 11)
# ---------------------------------------------------------------------------

def resolve_albion_guild_preview(
    *,
    guild_workspace_id: str,
    requesting_user_id: str,
    guild_name_or_id: str,
    server: str = "europe",
) -> dict:
    """
    Resolve an Albion guild by name (or direct ID) without writing to the DB.

    Intended for the preview step: call this before the officer confirms import.

    Returns a dict:
        {
          "albion_guild_id": str | None,
          "guild_name":      str,
          "server":          str,
          "alliance_id":     str | None,
          "alliance_name":   str | None,
          "member_count":    int,
          "error":           str | None,  # None on success
        }

    On success, error is None.
    On failure (API error, no match), error contains a user-safe message.

    Raises PermissionDenied if the caller is not an officer/owner.
    Raises NotFoundError if the workspace does not exist.
    """
    value = guild_name_or_id.strip()
    if not value:
        return {
            "albion_guild_id": None,
            "guild_name":      guild_name_or_id,
            "server":          server,
            "alliance_id":     None,
            "alliance_name":   None,
            "member_count":    0,
            "error":           "Guild name or ID must not be empty.",
        }

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, requesting_user_id
        )
        is_superadmin = _actor_is_superadmin(db, requesting_user_id)

    if not is_superadmin:
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied("Only officers and owners can import guild rosters.")

    from app.albion.rest_client import (
        AlbionApiError,
        fetch_albion_guild,
        looks_like_albion_id,
        search_albion_guilds,
    )

    # Direct guild-ID path: the Albion /search index does not return every guild
    # (small/new guilds, >10 matches, multi-word names).  When the input looks
    # like a raw guild ID, resolve it directly via /guilds/{id} — this always
    # works if the ID is valid.
    if looks_like_albion_id(value):
        try:
            g = fetch_albion_guild(value, server=server)
            return {
                "albion_guild_id": g["albion_guild_id"],
                "guild_name":      g["guild_name"],
                "server":          g.get("server", server),
                "alliance_id":     g.get("alliance_id"),
                "alliance_name":   g.get("alliance_name"),
                "member_count":    g.get("member_count", 0),
                "error":           None,
            }
        except AlbionApiError:
            # Fall through to name search as a safety net.
            pass

    try:
        results = search_albion_guilds(value, server=server)
    except AlbionApiError as exc:
        return {
            "albion_guild_id": None,
            "guild_name":      value,
            "server":          server,
            "alliance_id":     None,
            "alliance_name":   None,
            "member_count":    0,
            "error":           f"Albion API error: {exc}",
        }

    if not results:
        return {
            "albion_guild_id": None,
            "guild_name":      value,
            "server":          server,
            "alliance_id":     None,
            "alliance_name":   None,
            "member_count":    0,
            "error":           f"No guild found matching '{value}'.",
        }

    best = results[0]
    return {
        "albion_guild_id": best["albion_guild_id"],
        "guild_name":      best["guild_name"],
        "server":          best.get("server", server),
        "alliance_id":     best.get("alliance_id"),
        "alliance_name":   best.get("alliance_name"),
        "member_count":    best.get("member_count", 0),
        "error":           None,
    }


def import_albion_guild_roster(
    *,
    guild_workspace_id: str,
    requesting_user_id: str,
    albion_guild_id: str,
    guild_name_hint: str = "",
    alliance_id_hint: str | None = None,
    alliance_name_hint: str | None = None,
    server: str = "europe",
) -> dict:
    """
    Import all current members of an Albion guild into the workspace roster.

    Flow:
    1. Auth check: requesting_user_id must be officer or owner.
    2. HTTP: fetch guild members from Albion API (outside transaction).
    3. DB (single transaction):
       a. Upsert workspace_albion_guilds record.
       b. For each member: upsert workspace_albion_players.
          - character_name and source_guild_id are updated on re-import.
          - user_id (existing identity link) is preserved on conflict.
       c. Emit audit event.

    Returns:
        {
          "guild_name":   str,
          "total":        int,   # members returned by API
          "imported":     int,   # new rows inserted
          "updated":      int,   # existing rows updated
          "errors":       [],    # always empty in slice 1
        }

    Raises:
        PermissionDenied  — caller is not an officer/owner.
        NotFoundError     — workspace does not exist.
        ValidationError   — Albion API error or empty guild_id.
    """
    guild_id = albion_guild_id.strip()
    if not guild_id:
        raise ValidationError("Albion guild ID must not be empty.")

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, requesting_user_id
        )
        is_superadmin = _actor_is_superadmin(db, requesting_user_id)

    if not is_superadmin:
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied("Only officers and owners can import guild rosters.")

    # ------------------------------------------------------------------
    # Phase 2: API call (outside transaction)
    # ------------------------------------------------------------------
    from app.albion.rest_client import AlbionApiError, fetch_albion_guild_members

    try:
        members = fetch_albion_guild_members(guild_id, server=server)
    except AlbionApiError as exc:
        raise ValidationError(
            f"Could not fetch guild members from Albion API: {exc}"
        ) from exc

    # Derive guild metadata from member objects if available.
    resolved_guild_name    = guild_name_hint or guild_id
    resolved_alliance_id   = alliance_id_hint
    resolved_alliance_name = alliance_name_hint

    if members:
        first = members[0]
        if first.get("guild_name"):
            resolved_guild_name = first["guild_name"]

    # ------------------------------------------------------------------
    # Phase 3: DB write (single transaction)
    # ------------------------------------------------------------------
    now = _now()
    guild_row_id = str(uuid.uuid4())

    with database.transaction() as db:
        existing_ids = repositories.get_existing_albion_player_ids(
            db, guild_workspace_id
        )

        repositories.upsert_workspace_albion_guild(db, {
            "id":                guild_row_id,
            "guild_workspace_id": guild_workspace_id,
            "albion_guild_id":   guild_id,
            "guild_name":        resolved_guild_name,
            "server":            server,
            "alliance_id":       resolved_alliance_id,
            "alliance_name":     resolved_alliance_name,
            "last_imported_at":  now,
            "created_at":        now,
        })

        guild_rec = repositories.get_workspace_albion_guild(
            db, guild_workspace_id, guild_id
        )
        source_guild_row_id = guild_rec["id"] if guild_rec else guild_row_id

        imported = 0
        updated  = 0
        for member in members:
            player_id = member.get("albion_player_id", "")
            if not player_id:
                continue
            char_name = member.get("character_name", player_id)
            is_new = player_id not in existing_ids
            repositories.upsert_workspace_albion_player(db, {
                "id":                    str(uuid.uuid4()),
                "guild_workspace_id":    guild_workspace_id,
                "albion_player_id":      player_id,
                "character_name":        char_name,
                "user_id":               None,
                "source_guild_id":       source_guild_row_id,
                "last_seen_in_guild_at": now,
                "stale_at":              None,
                "created_at":            now,
                "updated_at":            now,
            })
            if is_new:
                imported += 1
            else:
                updated += 1

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_GUILD_ROSTER_IMPORTED,
            entity_type="workspace_albion_guild",
            entity_id=source_guild_row_id,
            actor_type="user",
            actor_id=requesting_user_id,
            payload={
                "albion_guild_id": guild_id,
                "guild_name":      resolved_guild_name,
                "total":           len(members),
                "imported":        imported,
                "updated":         updated,
            },
        )
        repositories.insert_operational_event(db, event)

    return {
        "guild_name": resolved_guild_name,
        "total":      len(members),
        "imported":   imported,
        "updated":    updated,
        "errors":     [],
    }


def refresh_all_guild_rosters(
    *,
    guild_workspace_id: str,
    requesting_user_id: str,
) -> dict:
    """
    Refresh all linked Albion guild rosters for the workspace and mark
    players not seen in any roster as stale.

    Flow (all-or-nothing safety model):
    1.  Auth check: requesting_user_id must be officer or owner.
    2.  DB: load all linked workspace_albion_guilds.
    3.  Validate: at least one linked guild must exist.
    4.  HTTP: fetch every guild member list.  If ANY fetch fails the
        function raises ValidationError before touching the DB.
    5.  DB (single transaction):
        a.  Upsert each guild row (updates last_imported_at).
        b.  Upsert each member (updates last_seen_in_guild_at; clears stale_at).
        c.  Mark stale any player absent from the global seen set.
        d.  Emit one audit event.

    Returns:
        {
          "guilds_refreshed": int,
          "active":           int,   # players present in at least one guild
          "updated":          int,   # existing rows refreshed (subset of active)
          "stale_marked":     int,   # newly stale rows
        }

    Raises:
        PermissionDenied  -- caller is not officer/owner.
        NotFoundError     -- workspace does not exist.
        ValidationError   -- no linked guilds; or any Albion API call fails.
    """
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        membership = repositories.get_workspace_membership(
            db, guild_workspace_id, requesting_user_id
        )
        if not membership:
            raise PermissionDenied("You are not a member of this workspace.")
        if not workspace_membership.can_manage_workspace_members(membership["role"]):
            raise PermissionDenied(
                "Only officers and owners can refresh guild rosters."
            )

    return _refresh_all_guild_rosters_core(
        guild_workspace_id=guild_workspace_id,
        actor_type="user",
        actor_id=requesting_user_id,
    )


def sync_workspace_rosters_system(guild_workspace_id: str) -> dict:
    """Refresh all linked Albion guild rosters for a workspace as the *system*
    actor, bypassing the officer/owner RBAC check.

    This is the entry point used by the scheduler's periodic roster-sync job.
    It must NEVER be wired directly to an HTTP route — user-triggered refreshes
    go through refresh_all_guild_rosters, which enforces permissions.

    Behaviour is otherwise identical to refresh_all_guild_rosters: it fetches
    every linked guild roster, aborts before any DB write if any fetch fails,
    upserts players, marks absent players stale, and emits one audit event
    (with actor_type='system').

    Raises ValidationError if the workspace has no linked guilds or any Albion
    API call fails; NotFoundError if the workspace does not exist.
    """
    return _refresh_all_guild_rosters_core(
        guild_workspace_id=guild_workspace_id,
        actor_type="system",
        actor_id=None,
    )


def _refresh_all_guild_rosters_core(
    *,
    guild_workspace_id: str,
    actor_type: str,
    actor_id: str | None,
) -> dict:
    """Shared roster-refresh implementation for the user- and system-triggered
    entry points.  Performs NO permission checks — the caller is responsible for
    authorization before invoking this function.
    """
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        linked_guilds = repositories.list_workspace_albion_guilds(db, guild_workspace_id)

    if not linked_guilds:
        raise ValidationError(
            "No linked guilds found. Import at least one guild roster first."
        )

    # Phase 2: fetch all guild rosters outside any transaction.
    # Abort before any DB writes if any fetch fails.
    from app.albion.rest_client import AlbionApiError, fetch_albion_guild_members

    fetched: list[tuple[dict, list[dict]]] = []  # (guild_row, members)
    for guild_row in linked_guilds:
        gname = guild_row["guild_name"]
        try:
            members = fetch_albion_guild_members(guild_row["albion_guild_id"])
        except AlbionApiError as exc:
            raise ValidationError(
                f"Failed to fetch roster for guild '{gname}': {exc}. "
                "Refresh aborted -- no changes were written."
            ) from exc
        fetched.append((guild_row, members))

    # Phase 3: single atomic DB write.
    now = _now()

    # Build global seen set across ALL guild rosters.
    seen_player_ids: set[str] = set()
    for _guild_row, members in fetched:
        for m in members:
            pid = m.get("albion_player_id", "")
            if pid:
                seen_player_ids.add(pid)

    active  = 0
    updated = 0

    with database.transaction() as db:
        existing_ids = repositories.get_existing_albion_player_ids(
            db, guild_workspace_id
        )

        for guild_row, members in fetched:
            repositories.upsert_workspace_albion_guild(db, {
                "id":                 guild_row["id"],
                "guild_workspace_id": guild_workspace_id,
                "albion_guild_id":    guild_row["albion_guild_id"],
                "guild_name":         guild_row["guild_name"],
                "server":             guild_row.get("server", "europe"),
                "alliance_id":        guild_row["alliance_id"],
                "alliance_name":      guild_row["alliance_name"],
                "last_imported_at":   now,
                "created_at":         guild_row["created_at"],
            })

            for member in members:
                player_id = member.get("albion_player_id", "")
                if not player_id:
                    continue
                char_name = member.get("character_name", player_id)
                is_existing = player_id in existing_ids
                repositories.upsert_workspace_albion_player(db, {
                    "id":                    str(uuid.uuid4()),
                    "guild_workspace_id":    guild_workspace_id,
                    "albion_player_id":      player_id,
                    "character_name":        char_name,
                    "user_id":               None,
                    "source_guild_id":       guild_row["id"],
                    "last_seen_in_guild_at": now,
                    "stale_at":              None,
                    "created_at":            now,
                    "updated_at":            now,
                })
                active += 1
                if is_existing:
                    updated += 1

        stale_marked = repositories.mark_workspace_albion_players_stale(
            db, guild_workspace_id, seen_player_ids, now
        )

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.ALBION_GUILD_ROSTER_REFRESHED,
            entity_type="guild_workspace",
            entity_id=guild_workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "guilds_refreshed": len(fetched),
                "active":           active,
                "updated":          updated,
                "stale_marked":     stale_marked,
            },
        )
        repositories.insert_operational_event(db, event)

    return {
        "guilds_refreshed": len(fetched),
        "active":           active,
        "updated":          updated,
        "stale_marked":     stale_marked,
    }


def join_workspace_via_roster_match(
    *,
    user_id: str,
    guild_workspace_id: str,
) -> dict:
    """Let a user self-join a workspace by matching their display name to an
    unlinked Albion guild roster character.

    Security model: the name match is re-verified server-side here (never
    trusted from the client).  A user may only join when EXACTLY ONE active,
    unlinked roster character in the workspace matches their display name
    case-insensitively.  Ambiguous (multiple) matches are refused so an officer
    can link the correct character manually.

    On success, atomically:
      1. Inserts a workspace_members row with role='member'.
      2. Links the roster player row to the user (workspace_albion_players.user_id).
      3. Inserts an 'approved' player_game_identities row when no identity yet
         exists for this user or this character in the workspace.
      4. Emits a WORKSPACE_MEMBER_SELF_JOINED audit event.

    Returns ``{"workspace": <workspace dict>, "character_name": str}``.

    Raises:
        NotFoundError   — workspace does not exist, or user does not exist.
        ConflictError   — the user is already a member of the workspace.
        ValidationError — no matching roster character, or the match is ambiguous.
    """
    now = _now()

    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, guild_workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")

        user = repositories.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundError("User not found.")

        if repositories.get_workspace_membership(db, guild_workspace_id, user_id):
            raise ConflictError("You are already a member of this workspace.")

        display_name = (user["display_name"] or "").strip()
        if not display_name:
            raise ValidationError("Your account has no display name to match against.")

        matches = repositories.find_unlinked_roster_players_by_name(
            db, guild_workspace_id, display_name
        )
        if not matches:
            raise ValidationError(
                f"No unlinked guild-roster character matches your name "
                f"'{display_name}'. Ask an officer to add you manually, or make "
                "sure your display name matches your in-game character name."
            )
        if len(matches) > 1:
            raise ValidationError(
                f"Multiple roster characters match the name '{display_name}'. "
                "Ask an officer to link the correct character to your account."
            )

        player = matches[0]

        membership = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": guild_workspace_id,
            "user_id": user_id,
            "role": "member",
            "created_at": now,
        }
        repositories.insert_workspace_member(db, membership)

        repositories.link_workspace_albion_player_to_user(
            db,
            guild_workspace_id=guild_workspace_id,
            albion_player_id=player["albion_player_id"],
            user_id=user_id,
        )

        # Create an approved identity claim only when none exists yet for this
        # user or this character in the workspace (avoids UNIQUE violations).
        existing_user_identity = repositories.get_player_game_identity_for_user(
            db, user_id, guild_workspace_id
        )
        existing_char_identity = repositories.get_player_game_identity_by_albion_id(
            db, player["albion_player_id"], guild_workspace_id
        )
        if not existing_user_identity and not existing_char_identity:
            repositories.insert_player_game_identity(db, {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": guild_workspace_id,
                "user_id": user_id,
                "game": "albion",
                "albion_player_id": player["albion_player_id"],
                "character_name": player["character_name"],
                "verification_status": "approved",
                "claimed_at": now,
                "reviewed_at": now,
                "reviewed_by": user_id,
                "review_note": "Auto-linked via guild roster name match.",
                "created_at": now,
            })

        event = operational_events.make_event(
            guild_workspace_id=guild_workspace_id,
            guild_operation_id=None,
            event_type=operational_events.WORKSPACE_MEMBER_SELF_JOINED,
            entity_type="workspace_member",
            entity_id=membership["id"],
            actor_type="user",
            actor_id=user_id,
            payload={
                "albion_player_id": player["albion_player_id"],
                "character_name":   player["character_name"],
            },
        )
        repositories.insert_operational_event(db, event)

    return {"workspace": ws, "character_name": player["character_name"]}


# ---------------------------------------------------------------------------
# Super-admin ("god-mode") workspace operations
#
# These use cases are only ever reached from super-admin routes, which enforce
# the Discord allowlist check before calling.  They perform NO membership-based
# permission checks themselves — access control lives at the route boundary.
# Every action is written to superadmin_audit_log.
# ---------------------------------------------------------------------------

def _log_superadmin_action(
    db,
    actor_user_id: str,
    action: str,
    workspace_id: str | None,
    workspace_name: str | None,
    detail: dict | None = None,
) -> None:
    ident = repositories.get_discord_identity_for_user(db, actor_user_id)
    repositories.insert_superadmin_audit_log(db, {
        "id": str(uuid.uuid4()),
        "actor_user_id": actor_user_id,
        "actor_discord_id": ident["provider_user_id"] if ident else None,
        "action": action,
        "target_workspace_id": workspace_id,
        "target_workspace_name": workspace_name,
        "detail_json": json.dumps(detail or {}),
        "created_at": _now(),
    })


def superadmin_soft_delete_workspace(
    *,
    actor_user_id: str,
    workspace_id: str,
) -> dict:
    """Soft-delete a workspace: hide it from all normal users, reversibly.

    Raises NotFoundError if the workspace does not exist; ConflictError if it
    is already soft-deleted.
    """
    now = _now()
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        if ws.get("deleted_at"):
            raise ConflictError("Workspace is already deleted.")
        repositories.soft_delete_workspace(db, workspace_id, now, actor_user_id)
        _log_superadmin_action(
            db, actor_user_id, "workspace.soft_delete", workspace_id, ws["name"], {}
        )
    return ws


def superadmin_restore_workspace(
    *,
    actor_user_id: str,
    workspace_id: str,
) -> dict:
    """Restore a soft-deleted workspace back to active.

    Raises NotFoundError if the workspace does not exist; ValidationError if it
    is not currently soft-deleted.
    """
    now = _now()
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        if not ws.get("deleted_at"):
            raise ValidationError("Workspace is not deleted.")
        repositories.restore_workspace(db, workspace_id, now)
        _log_superadmin_action(
            db, actor_user_id, "workspace.restore", workspace_id, ws["name"], {}
        )
    return ws


def superadmin_hard_delete_workspace(
    *,
    actor_user_id: str,
    workspace_id: str,
) -> dict:
    """Permanently delete a workspace and ALL of its data. Irreversible.

    Safety: the workspace must already be soft-deleted (two-step delete).  The
    audit log row is written after the delete in a separate transaction, since
    the destructive delete runs on its own connection.

    Raises NotFoundError if missing; ValidationError if not soft-deleted first.
    """
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        if not ws.get("deleted_at"):
            raise ValidationError(
                "Workspace must be soft-deleted before it can be permanently deleted."
            )
        ws_name = ws["name"]

    deleted_counts = database.hard_delete_workspace(workspace_id)

    with database.transaction() as db:
        _log_superadmin_action(
            db, actor_user_id, "workspace.hard_delete", workspace_id, ws_name,
            {"rows_deleted": deleted_counts},
        )
    return {"workspace_name": ws_name, "rows_deleted": deleted_counts}


def superadmin_rename_workspace(
    *,
    actor_user_id: str,
    workspace_id: str,
    name: str,
    slug: str,
) -> dict:
    """Rename a workspace (name + slug) as a support action.

    Raises NotFoundError if missing; ValidationError for invalid name/slug;
    ConflictError if the slug is already used by another workspace.
    """
    guild_workspace.validate_workspace_name(name)
    guild_workspace.validate_workspace_slug(slug)
    now = _now()
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        existing = repositories.get_workspace_by_slug(db, slug)
        if existing and existing["id"] != workspace_id:
            raise ConflictError(f"A workspace with slug '{slug}' already exists.")
        repositories.rename_workspace(db, workspace_id, name.strip(), slug, now)
        _log_superadmin_action(
            db, actor_user_id, "workspace.rename", workspace_id, name.strip(),
            {"old_name": ws["name"], "old_slug": ws["slug"],
             "new_name": name.strip(), "new_slug": slug},
        )
    return {"id": workspace_id, "name": name.strip(), "slug": slug}


def superadmin_transfer_workspace_ownership(
    *,
    actor_user_id: str,
    workspace_id: str,
    new_owner_user_id: str,
) -> dict:
    """Transfer workspace ownership to an existing member.

    The new owner must already be a member of the workspace.  Any other current
    owners are demoted to officer so there is a single owner after transfer.

    Raises NotFoundError if the workspace does not exist; ValidationError if the
    target user is not a member.
    """
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, workspace_id)
        if not ws:
            raise NotFoundError("Workspace not found.")
        target = repositories.get_workspace_membership(db, workspace_id, new_owner_user_id)
        if not target:
            raise ValidationError("The chosen user is not a member of this workspace.")
        repositories.demote_other_owners(db, workspace_id, new_owner_user_id, "officer")
        repositories.set_workspace_member_role(
            db, workspace_id, new_owner_user_id, "owner"
        )
        _log_superadmin_action(
            db, actor_user_id, "workspace.transfer_ownership", workspace_id, ws["name"],
            {"new_owner_user_id": new_owner_user_id},
        )
    return ws
