"""Workspace membership and role checks."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from starlette.requests import Request

from app import repositories
from app.auth import superadmin
from app.auth.current_user import require_current_user
from app.domain.workspace_membership import validate_role
from app.errors import NotFoundError, PermissionDenied


def require_workspace_member(
    db: sqlite3.Connection,
    user_id: str,
    guild_workspace_id: str,
) -> dict:
    membership = repositories.get_workspace_membership(
        db, guild_workspace_id, user_id
    )
    if not membership:
        raise NotFoundError("Workspace not found.")
    return membership


def require_workspace_role(
    db: sqlite3.Connection,
    user_id: str,
    guild_workspace_id: str,
    allowed_roles: Iterable[str],
) -> dict:
    membership = require_workspace_member(db, user_id, guild_workspace_id)
    if membership["role"] not in set(allowed_roles):
        raise PermissionDenied("You do not have permission for this action.")
    return membership


def resolve_workspace_member_by_slug(
    db: sqlite3.Connection,
    request: Request,
    slug: str,
) -> tuple[dict, dict, dict]:
    user = require_current_user(db, request)
    workspace = repositories.get_workspace_by_slug(db, slug)
    if not workspace:
        raise NotFoundError("Workspace not found.")
    # Super-admin god-mode: owner-level view of any workspace (incl. soft-deleted).
    if superadmin.is_superadmin(db, user):
        return user, workspace, superadmin.synthetic_owner_membership(
            workspace["id"], user["id"]
        )
    # Soft-deleted workspaces are invisible to normal users.
    if workspace.get("deleted_at"):
        raise NotFoundError("Workspace not found.")
    membership = require_workspace_member(db, user["id"], workspace["id"])
    return user, workspace, membership
