"""Super-admin ("god-mode") portal routes.

Access is restricted to Discord accounts on the IRONKEEP_SUPERADMIN_DISCORD_IDS
allowlist (see app/auth/superadmin.py).  Non-super-admins get a 404 so the
portal's existence is not revealed.  Every mutating action is recorded in
superadmin_audit_log by the use-case layer.

Owner-level access to any individual workspace is handled by the god-mode bypass
in app/routes_auth.py + app/auth/workspace_access.py, so support edits (settings,
members, builds, …) are done through the normal workspace UI via the
"Open workspace" link on the detail page.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import database, repositories
from app import routes_auth as authz
from app.application import use_cases
from app.auth import superadmin
from app.auth.current_user import require_current_user
from app.errors import AuthenticationRequired, IronkeepError
from app.routes import _err_redirect, _ok_redirect, _redirect, templates

router = APIRouter(prefix="/admin")


class _NotSuperadmin(Exception):
    """Internal signal that the current user is not a super-admin."""


def _require_superadmin(db, request: Request) -> dict:
    """Return the current user when they are a super-admin.

    Raises AuthenticationRequired if not logged in (caller redirects to login)
    and _NotSuperadmin otherwise (caller returns 404).
    """
    user = require_current_user(db, request)
    if not superadmin.is_superadmin(db, user):
        raise _NotSuperadmin()
    return user


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("")
def get_admin_dashboard(request: Request):
    try:
        with database.transaction() as db:
            user = _require_superadmin(db, request)
            workspaces = repositories.list_all_workspaces_admin(db)
            audit_log = repositories.list_superadmin_audit_log(db, limit=50)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except _NotSuperadmin:
        raise HTTPException(status_code=404, detail="Not found.")
    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "workspace": None,
            "current_user": user,
            "is_superadmin": True,
            "workspaces": workspaces,
            "audit_log": audit_log,
        },
    )


@router.get("/workspaces/{workspace_id}")
def get_admin_workspace_detail(request: Request, workspace_id: str):
    try:
        with database.transaction() as db:
            user = _require_superadmin(db, request)
            ws = repositories.get_workspace_by_id(db, workspace_id)
            if not ws:
                raise HTTPException(status_code=404, detail="Workspace not found.")
            members = repositories.list_workspace_members(db, workspace_id)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except _NotSuperadmin:
        raise HTTPException(status_code=404, detail="Not found.")
    return templates.TemplateResponse(
        request,
        "admin_workspace_detail.html",
        {
            "workspace": None,
            "current_user": user,
            "is_superadmin": True,
            "target_ws": ws,
            "members": members,
        },
    )


# ---------------------------------------------------------------------------
# Mutating actions
# ---------------------------------------------------------------------------

def _auth_or_redirect(request: Request):
    """Shared guard for POST actions. Returns (user, None) on success, or
    (None, response) when the caller should return that response instead."""
    try:
        with database.transaction() as db:
            user = _require_superadmin(db, request)
    except AuthenticationRequired:
        return None, _redirect(authz.login_url(request))
    except _NotSuperadmin:
        raise HTTPException(status_code=404, detail="Not found.")
    return user, None


@router.post("/workspaces/{workspace_id}/soft-delete")
async def post_soft_delete_workspace(request: Request, workspace_id: str):
    user, redirect = _auth_or_redirect(request)
    if redirect:
        return redirect
    try:
        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=user["id"], workspace_id=workspace_id
        )
    except IronkeepError as exc:
        return _err_redirect("/admin", str(exc))
    return _ok_redirect("/admin", "Workspace soft-deleted (hidden, recoverable).")


@router.post("/workspaces/{workspace_id}/restore")
async def post_restore_workspace(request: Request, workspace_id: str):
    user, redirect = _auth_or_redirect(request)
    if redirect:
        return redirect
    try:
        use_cases.superadmin_restore_workspace(
            actor_user_id=user["id"], workspace_id=workspace_id
        )
    except IronkeepError as exc:
        return _err_redirect("/admin", str(exc))
    return _ok_redirect("/admin", "Workspace restored.")


@router.post("/workspaces/{workspace_id}/hard-delete")
async def post_hard_delete_workspace(request: Request, workspace_id: str):
    user, redirect = _auth_or_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    confirm_slug = (form.get("confirm_slug") or "").strip()

    detail_url = f"/admin/workspaces/{workspace_id}"
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if confirm_slug != ws["slug"]:
        return _err_redirect(
            detail_url,
            "Confirmation failed: type the exact workspace slug to permanently delete.",
        )
    try:
        use_cases.superadmin_hard_delete_workspace(
            actor_user_id=user["id"], workspace_id=workspace_id
        )
    except IronkeepError as exc:
        return _err_redirect(detail_url, str(exc))
    return _ok_redirect("/admin", f"Workspace '{ws['name']}' permanently deleted.")


@router.post("/workspaces/{workspace_id}/rename")
async def post_rename_workspace(request: Request, workspace_id: str):
    user, redirect = _auth_or_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    name = (form.get("name") or "").strip()
    slug = (form.get("slug") or "").strip()
    detail_url = f"/admin/workspaces/{workspace_id}"
    try:
        use_cases.superadmin_rename_workspace(
            actor_user_id=user["id"], workspace_id=workspace_id, name=name, slug=slug
        )
    except IronkeepError as exc:
        return _err_redirect(detail_url, str(exc))
    return _ok_redirect(detail_url, "Workspace renamed.")


@router.post("/workspaces/{workspace_id}/transfer-owner")
async def post_transfer_owner(request: Request, workspace_id: str):
    user, redirect = _auth_or_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    new_owner_user_id = (form.get("new_owner_user_id") or "").strip()
    detail_url = f"/admin/workspaces/{workspace_id}"
    try:
        use_cases.superadmin_transfer_workspace_ownership(
            actor_user_id=user["id"],
            workspace_id=workspace_id,
            new_owner_user_id=new_owner_user_id,
        )
    except IronkeepError as exc:
        return _err_redirect(detail_url, str(exc))
    return _ok_redirect(detail_url, "Ownership transferred.")
