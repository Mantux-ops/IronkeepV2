"""Route-layer auth helpers. Redirect decisions stay in routes."""

from __future__ import annotations

from urllib.parse import quote_plus

from starlette.requests import Request

from app import repositories
from app.auth import superadmin, workspace_access
from app.auth.current_user import require_current_user
from app.domain.workspace_membership import (
    MUTATOR_ROLES,
    can_manage_workspace_members,
    can_mutate_workspace_operations,
    can_submit_signup,
)
from app.errors import NotFoundError, PermissionDenied


def login_url(request: Request, next_path: str | None = None) -> str:
    target = next_path or request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return f"/login?next={quote_plus(target)}"


def membership_context(membership: dict) -> dict[str, object]:
    role = membership["role"]
    return {
        "membership": membership,
        "can_mutate": can_mutate_workspace_operations(role),
        "can_submit_signup": can_submit_signup(role),
        "can_manage_members": can_manage_workspace_members(role),
    }


def visitor_context() -> dict[str, object]:
    """Access context for authenticated users with no workspace membership.

    Used on the signup page only.  Any authenticated user may view and
    submit signups; all officer/owner capabilities remain False.
    """
    return {
        "membership": None,
        "can_mutate": False,
        "can_submit_signup": True,
        "can_manage_members": False,
    }


def resolve_workspace_view(
    db,
    request: Request,
    slug: str,
) -> tuple[dict, dict, dict[str, object]]:
    user, workspace, membership = workspace_access.resolve_workspace_member_by_slug(
        db, request, slug
    )
    return user, workspace, membership_context(membership)


def resolve_workspace_for_signup(
    db,
    request: Request,
    slug: str,
) -> tuple[dict, dict, dict[str, object]]:
    """Auth for the operation signup page.

    Any authenticated user may view the page and submit signups regardless of
    workspace membership — alliance players should not need to be pre-added.
    Officer / owner capabilities are gated by the membership check as usual.

    Raises AuthenticationRequired if the user is not logged in.
    Raises NotFoundError if the workspace slug does not exist.
    """
    user = require_current_user(db, request)
    workspace = repositories.get_workspace_by_slug(db, slug)
    if not workspace:
        raise NotFoundError("Workspace not found.")
    membership = repositories.get_workspace_membership(db, workspace["id"], user["id"])
    if membership:
        return user, workspace, membership_context(membership)
    return user, workspace, visitor_context()


def require_workspace_mutator(db, user_id: str, guild_workspace_id: str) -> dict:
    # Super-admin god-mode: owner-level access to any workspace.
    user = repositories.get_user_by_id(db, user_id)
    if superadmin.is_superadmin(db, user):
        return superadmin.synthetic_owner_membership(guild_workspace_id, user_id)
    return workspace_access.require_workspace_role(
        db, user_id, guild_workspace_id, MUTATOR_ROLES
    )


def authorize_workspace_action(
    db,
    request: Request,
    slug: str,
    *,
    require_mutator: bool = True,
    allow_signup: bool = False,
) -> tuple[dict, dict, dict]:
    user = require_current_user(db, request)
    workspace = repositories.get_workspace_by_slug(db, slug)
    if not workspace:
        raise NotFoundError("Workspace not found.")

    # Super-admin god-mode: full owner access to any workspace, including
    # soft-deleted ones (so they can inspect before restoring/purging).
    if superadmin.is_superadmin(db, user):
        return user, workspace, superadmin.synthetic_owner_membership(
            workspace["id"], user["id"]
        )

    # Soft-deleted workspaces are invisible to normal users.
    if workspace.get("deleted_at"):
        raise NotFoundError("Workspace not found.")

    membership = repositories.get_workspace_membership(
        db, workspace["id"], user["id"]
    )
    if not membership:
        raise NotFoundError("Workspace not found.")
    if require_mutator:
        if not can_mutate_workspace_operations(membership["role"]):
            raise PermissionDenied("You do not have permission for this action.")
    elif allow_signup:
        if not can_submit_signup(membership["role"]):
            raise PermissionDenied("You do not have permission for this action.")
    return user, workspace, membership
