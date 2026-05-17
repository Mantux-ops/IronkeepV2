"""
HTTP routes — Slice A + Slice B + Attendance + Assignment lifecycle + Reserve
             + Quick assignment workflow.

Slice A: workspaces, compositions, operation create/detail (read-only).
Slice B: plan attach, generate slots, signup, planner board, assign, readiness,
         event timeline.
Attendance: attendance page, mark/update attendance per assignment.
Assignment lifecycle: remove assignment.
Reserve: mark participant as reserve, remove reserve.
Quick assignment: quick-assign single slot, quick-fill party.

Rules:
- Routes are thin: parse input, call use cases or repository reads, render or redirect.
- No business logic here.
- POST success  → PRG redirect (HTTP 303), optionally with ?success= flash.
- POST error    → redirect back with ?error= flash (no re-POST on browser refresh).
- GET detail    → reads ?error / ?success query params and passes to template.
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import backup, database, diagnostics as diag, repositories
from app.application import use_cases
from app.auth import session as auth_session
from app.auth.current_user import get_current_user, require_current_user
from app.domain import attendance as attendance_domain
from app.domain import guild_operations
from app.domain import scout_attendance as scout_attendance_domain
from app.domain.mass_planner import sort_participants_for_slot
from app.errors import (
    AuthenticationRequired,
    IronkeepError,
    NotFoundError,
    PermissionDenied,
)
from app import routes_auth as authz
from app.discord.formatters import format_operation_announcement, format_roster
from app.auth import discord_oauth

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Make IRONKEEP_ENV available to every template without threading it through
# every individual TemplateResponse context dict.
templates.env.globals["ironkeep_env"] = os.getenv("IRONKEEP_ENV", "dev").strip().lower()

def _is_production() -> bool:
    """Read IRONKEEP_ENV fresh on each call so test patches take effect."""
    return os.getenv("IRONKEEP_ENV", "dev").strip().lower() == "production"


def _enrich_discord_meta(meta_map: dict) -> dict:
    """
    Add an `is_stale` boolean to each row in a discord_metadata_map dict.

    Staleness is determined by comparing fetched_at (ISO-8601 UTC string) to
    now - _METADATA_CACHE_TTL_HOURS.  String comparison works because ISO-8601
    sorts lexicographically.
    """
    from datetime import datetime, timezone, timedelta  # noqa: PLC0415
    ttl_hours = use_cases._METADATA_CACHE_TTL_HOURS
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    ).isoformat()
    return {
        snowflake: {**row, "is_stale": row.get("fetched_at", "") < cutoff}
        for snowflake, row in meta_map.items()
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


def _safe_next(path: str | None) -> str:
    """
    Validate an internal redirect path.  Only allows safe relative paths that
    start with exactly one "/" and are not protocol-relative ("//...").
    Falls back to "/" if the value is absent or invalid.
    """
    if not path:
        return "/"
    path = path.strip()
    if path.startswith("/") and not path.startswith("//"):
        return path
    return "/"


def _err_redirect(base_url: str, error: str) -> RedirectResponse:
    return _redirect(f"{base_url}?error={quote_plus(error)}")


def _ok_redirect(base_url: str, msg: str = "") -> RedirectResponse:
    if msg:
        return _redirect(f"{base_url}?success={quote_plus(msg)}")
    return _redirect(base_url)


def _tomorrow_2000() -> str:
    """Return ISO datetime string for tomorrow at 20:00 local time."""
    t = (datetime.now() + timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    return t.strftime("%Y-%m-%dT%H:%M")


def _gap_counts_from_json(raw: str | None) -> dict[str, int]:
    """
    Parse readiness gap JSON for templates.

    Current snapshots store role/build gaps as dicts with counts. Older rows
    may still have a deduplicated list of names; convert those to count=1 each.
    """
    parsed = json.loads(raw or "{}")
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        counts: dict[str, int] = {}
        for name in parsed:
            counts[name] = counts.get(name, 0) + 1
        return counts
    return {}


def _enrich_readiness(r: dict | None) -> dict | None:
    """
    Parse gap JSON columns into Python dicts for template convenience.

    Adds:
      missing_roles  — dict of role → count, e.g. {"DPS": 2, "Tank": 1}
      missing_builds — dict of build_name → count, e.g. {"Bow": 1, "Daggers": 1}

    Both are empty dicts when all slots are assigned.
    """
    if r is None:
        return None
    return {
        **r,
        "missing_roles": _gap_counts_from_json(r.get("missing_roles_json")),
        "missing_builds": _gap_counts_from_json(r.get("missing_builds_json")),
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.get("/login")
def get_login(request: Request):
    next_path = _safe_next(request.query_params.get("next"))
    error = request.query_params.get("error")
    oauth_available = discord_oauth.is_oauth_configured()
    with database.transaction() as db:
        existing_users = repositories.list_users(db)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "workspace": None,
            "users": existing_users,
            "next_path": next_path,
            "error": error,
            "prev_display_name": "",
            "discord_oauth_available": oauth_available,
            "is_production": _is_production(),
        },
    )


@router.post("/login")
async def post_login(request: Request):
    # Dev login is not available in production — Discord OAuth is required.
    if _is_production():
        raise HTTPException(
            status_code=403,
            detail="Dev login is not available in production. Use Discord OAuth.",
        )
    form = await request.form()
    display_name = form.get("display_name", "").strip()
    next_path = _safe_next(form.get("next"))
    try:
        user = use_cases.dev_login_or_create_user(display_name)
    except IronkeepError as exc:
        with database.transaction() as db:
            existing_users = repositories.list_users(db)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "workspace": None,
                "users": existing_users,
                "next_path": next_path,
                "error": str(exc),
                "prev_display_name": display_name,
                "discord_oauth_available": discord_oauth.is_oauth_configured(),
                "is_production": _is_production(),
            },
        )
    auth_session.set_session_user(request, user["id"])
    return _redirect(next_path)


@router.post("/logout")
async def post_logout(request: Request):
    auth_session.clear_session(request)
    return _redirect("/")


# ---------------------------------------------------------------------------
# Discord OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/discord")
def get_auth_discord(request: Request):
    """
    Initiate the Discord OAuth2 flow.

    If OAuth is not configured, return a 503 with a user-visible error rather
    than crashing — the app must keep running even when OAuth vars are missing.
    """
    if not discord_oauth.is_oauth_configured():
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "workspace": None,
                "users": [],
                "next_path": "/",
                "error": (
                    "Discord OAuth is not configured on this server. "
                    "Contact the server administrator."
                ),
                "prev_display_name": "",
                "discord_oauth_available": False,
                "is_production": _is_production(),
            },
            status_code=503,
        )

    import secrets  # noqa: PLC0415
    state = secrets.token_urlsafe(32)
    next_path = _safe_next(request.query_params.get("next"))
    request.session["oauth_state"] = state
    request.session["oauth_next"]  = next_path

    try:
        auth_url = discord_oauth.build_authorization_url(state)
    except discord_oauth.DiscordOAuthError as exc:
        return _err_redirect("/login", str(exc))

    return _redirect(auth_url)


@router.get("/auth/discord/callback")
async def get_auth_discord_callback(request: Request):
    """
    Handle the Discord OAuth2 callback.

    Validates state, exchanges code for token, fetches identity, finds/creates
    application user, sets session, redirects to the original next path.
    """
    # --- CSRF state check ---
    session_state  = request.session.pop("oauth_state", None)
    callback_state = request.query_params.get("state", "")
    next_path      = _safe_next(request.session.pop("oauth_next", None))

    if not session_state or session_state != callback_state:
        return _err_redirect("/login", "Login session expired or invalid. Please try again.")

    # --- Error param from Discord (user denied, etc.) ---
    if request.query_params.get("error"):
        discord_error = request.query_params.get("error_description", "Discord login was cancelled.")
        return _err_redirect("/login", discord_error)

    code = request.query_params.get("code", "").strip()
    if not code:
        return _err_redirect("/login", "No authorization code received from Discord.")

    # --- Token exchange ---
    try:
        access_token = discord_oauth.exchange_code(code)
    except discord_oauth.DiscordOAuthError as exc:
        return _err_redirect("/login", f"Discord login failed. Please try again. ({exc})")

    # --- Identity fetch ---
    try:
        identity = discord_oauth.fetch_user_identity(access_token)
    except discord_oauth.DiscordOAuthError as exc:
        return _err_redirect("/login", f"Could not retrieve your Discord identity. ({exc})")

    discord_user_id = identity.get("id", "")
    # Prefer global_name (new Discord usernames) over legacy username.
    discord_username = (
        identity.get("global_name")
        or identity.get("username")
        or f"discord-{discord_user_id}"
    )

    # --- Find or create application user ---
    try:
        user = use_cases.discord_oauth_login(discord_user_id, discord_username)
    except IronkeepError as exc:
        return _err_redirect("/login", f"Login failed: {exc}")

    auth_session.set_session_user(request, user["id"])
    return _redirect(next_path)


# ---------------------------------------------------------------------------
# Account page + Discord identity linking
# ---------------------------------------------------------------------------

@router.get("/account")
def get_account(request: Request):
    """My Account page — shows linked identities, link button, and Albion claims."""
    try:
        with database.transaction() as db:
            user        = require_current_user(db, request)
            identities  = repositories.get_auth_identities_for_user(db, user["id"])
            memberships = repositories.get_workspaces_for_user(db, user["id"])
            claims      = repositories.list_player_game_identities_for_user(db, user["id"])
            player_ids  = [c["albion_player_id"] for c in claims]
            cache_rows  = repositories.get_albion_character_cache_many(db, player_ids)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))

    cache_by_player_id = {c["albion_player_id"]: c for c in cache_rows}
    claims_by_ws       = {c["guild_workspace_id"]: c for c in claims}

    workspaces_with_claims = [
        {
            "workspace": ws,
            "claim":     claims_by_ws.get(ws["id"]),
            "cache":     cache_by_player_id.get(
                             (claims_by_ws.get(ws["id"]) or {}).get("albion_player_id", ""), None
                         ),
        }
        for ws in memberships
    ]

    # Albion character search — user-initiated GET with search_q param.
    search_q       = request.query_params.get("search_q", "").strip()
    search_results = []
    search_error   = None
    if search_q:
        from app.albion.rest_client import AlbionApiError, search_albion_characters
        try:
            search_results = search_albion_characters(search_q)
        except AlbionApiError as exc:
            search_error = str(exc)

    error   = request.query_params.get("error")
    success = request.query_params.get("success")
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "workspace":             None,
            "user":                  user,
            "identities":            identities,
            "workspaces_with_claims": workspaces_with_claims,
            "search_q":              search_q,
            "search_results":        search_results,
            "search_error":          search_error,
            "error":                 error,
            "success":               success,
        },
    )


@router.post("/account/albion/claim")
async def post_albion_claim(request: Request):
    """Submit a pending Albion character claim for the current user."""
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))

    form               = await request.form()
    albion_player_id   = (form.get("albion_player_id") or "").strip()
    guild_workspace_id = (form.get("guild_workspace_id") or "").strip()

    if not albion_player_id or not guild_workspace_id:
        return _err_redirect("/account", "Invalid claim submission.")

    try:
        use_cases.claim_albion_character(
            user_id=user["id"],
            guild_workspace_id=guild_workspace_id,
            albion_player_id=albion_player_id,
        )
    except IronkeepError as exc:
        return _err_redirect("/account", str(exc))

    return _ok_redirect("/account", "Character claim submitted. Awaiting officer approval.")


@router.post("/account/albion/refresh")
async def post_albion_refresh(request: Request):
    """Refresh cached Albion character data for the current user's claim."""
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))

    form               = await request.form()
    guild_workspace_id = (form.get("guild_workspace_id") or "").strip()

    if not guild_workspace_id:
        return _err_redirect("/account", "Workspace not specified.")

    try:
        use_cases.refresh_albion_character_cache(
            user_id=user["id"],
            guild_workspace_id=guild_workspace_id,
        )
    except IronkeepError as exc:
        return _err_redirect("/account", str(exc))

    return _ok_redirect("/account", "Character data refreshed.")


def _user_has_dev_identity(user: dict, identities: list[dict]) -> bool:
    """True if the user has a dev identity (new table or legacy column)."""
    providers = {i["auth_provider"] for i in identities}
    return "dev" in providers or user.get("auth_provider") == "dev"


def _user_has_discord_identity(identities: list[dict]) -> bool:
    """True if the user already has a discord identity in user_auth_identities."""
    return any(i["auth_provider"] == "discord" for i in identities)


@router.get("/auth/discord/link")
def get_auth_discord_link(request: Request):
    """
    Initiate the Discord identity linking flow for an authenticated dev user.

    Requires:
    - User is authenticated.
    - User has a dev identity (not already a pure discord user).
    - User does not already have a discord identity linked.
    - OAuth is configured.
    """
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
            identities = repositories.get_auth_identities_for_user(db, user["id"])
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))

    if not _user_has_dev_identity(user, identities):
        return _err_redirect("/account", "Only dev-login accounts can initiate Discord linking.")

    if _user_has_discord_identity(identities):
        return _err_redirect("/account", "This account already has a Discord identity linked.")

    if not discord_oauth.is_oauth_configured():
        return _err_redirect("/account", "Discord OAuth is not configured on this server.")

    import secrets  # noqa: PLC0415
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"]  = state
    request.session["linking"]      = True

    link_redirect_uri = os.environ.get("DISCORD_OAUTH_LINK_REDIRECT_URI", "").strip()
    if not link_redirect_uri:
        return _err_redirect(
            "/account",
            "DISCORD_OAUTH_LINK_REDIRECT_URI is not configured. "
            "Add it to the Discord application and set the env var.",
        )

    try:
        from urllib.parse import urlencode  # noqa: PLC0415
        from app.auth.discord_oauth import _oauth_config  # noqa: PLC0415
        client_id, _secret, _unused_redirect = _oauth_config()
        params = urlencode({
            "client_id":     client_id,
            "redirect_uri":  link_redirect_uri,
            "response_type": "code",
            "scope":         "identify",
            "state":         state,
        })
        auth_url = f"https://discord.com/oauth2/authorize?{params}"
    except discord_oauth.DiscordOAuthError as exc:
        return _err_redirect("/account", str(exc))

    return RedirectResponse(url=auth_url, status_code=303)


@router.get("/auth/discord/link/callback")
async def get_auth_discord_link_callback(request: Request):
    """
    Complete the Discord identity linking flow.

    Validates CSRF state, exchanges code, fetches identity, calls
    link_discord_identity use case.  Session user_id is NOT changed —
    the user remains logged in as their existing account.
    """
    # Pop session linking context.
    session_state = request.session.pop("oauth_state", None)
    is_linking    = request.session.pop("linking", False)
    callback_state = request.query_params.get("state", "")

    # Must have been initiated as a link flow, not a login flow.
    if not is_linking:
        return _err_redirect("/account", "Invalid linking session. Please try again.")

    if not session_state or session_state != callback_state:
        return _err_redirect("/account", "Linking session expired or invalid. Please try again.")

    # User must still be authenticated.
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
            identities = repositories.get_auth_identities_for_user(db, user["id"])
    except AuthenticationRequired:
        return _err_redirect("/login", "You must be logged in to link your Discord account.")

    # Re-verify the user still qualifies to link.
    if not _user_has_dev_identity(user, identities):
        return _err_redirect("/account", "Only dev-login accounts can link to Discord.")

    if _user_has_discord_identity(identities):
        return _err_redirect("/account", "This account already has a Discord identity linked.")

    # Error from Discord (user denied, etc.).
    if request.query_params.get("error"):
        discord_error = request.query_params.get("error_description", "Discord linking was cancelled.")
        return _err_redirect("/account", discord_error)

    code = request.query_params.get("code", "").strip()
    if not code:
        return _err_redirect("/account", "No authorization code received from Discord.")

    link_redirect_uri = os.environ.get("DISCORD_OAUTH_LINK_REDIRECT_URI", "").strip()

    # Token exchange using the link redirect URI.
    try:
        access_token = discord_oauth.exchange_code_with_redirect(code, link_redirect_uri)
    except discord_oauth.DiscordOAuthError as exc:
        return _err_redirect("/account", f"Discord linking failed. Please try again. ({exc})")

    # Identity fetch.
    try:
        identity = discord_oauth.fetch_user_identity(access_token)
    except discord_oauth.DiscordOAuthError as exc:
        return _err_redirect("/account", f"Could not retrieve your Discord identity. ({exc})")

    discord_user_id = identity.get("id", "")

    # Link the account.
    try:
        use_cases.link_discord_identity(user["id"], discord_user_id)
    except IronkeepError as exc:
        return _err_redirect("/account", str(exc))

    # Session unchanged — user is still logged in as the same account.
    return _redirect("/account?success=discord_linked")


# ---------------------------------------------------------------------------
# Home — workspace list
# ---------------------------------------------------------------------------

@router.get("/")
def home(request: Request):
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
            workspaces = repositories.get_workspaces_for_user(db, user["id"])
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "workspace": None,
            "workspaces": workspaces,
            "current_user": user,
        },
    )


# ---------------------------------------------------------------------------
# Workspace routes
# ---------------------------------------------------------------------------

@router.get("/workspaces/new")
def get_new_workspace(request: Request):
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    return templates.TemplateResponse(
        request,
        "workspace_new.html",
        {
            "workspace": None,
            "current_user": user,
            "error": None,
            "prev_name": "",
            "prev_slug": "",
        },
    )


@router.post("/workspaces")
async def post_create_workspace(request: Request):
    form = await request.form()
    name = form.get("name", "").strip()
    slug = form.get("slug", "").strip()
    try:
        with database.transaction() as db:
            user = require_current_user(db, request)
        ws = use_cases.create_guild_workspace(
            name=name, slug=slug, owner_user_id=user["id"]
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except IronkeepError as exc:
        with database.transaction() as db:
            current = get_current_user(db, request)
        return templates.TemplateResponse(
            request,
            "workspace_new.html",
            {
                "workspace": None,
                "current_user": current,
                "error": str(exc),
                "prev_name": name,
                "prev_slug": slug,
            },
        )
    return _redirect(f"/workspaces/{ws['slug']}")


def _friendly_dt(iso: str | None) -> str:
    """
    Convert an ISO-8601 datetime string to a compact human-readable form.
    e.g. "2026-06-07T20:00:00+00:00" → "07 Jun 20:00 UTC"
    Falls back to the raw string if parsing fails.
    Passed directly into the template context — not registered as a global filter.
    """
    if not iso:
        return "—"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso)
        # Normalise to UTC for consistent display
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%-d %b %H:%M UTC")
    except Exception:
        # Safe fallback: strip sub-second / tz noise, replace T separator
        return iso[:16].replace("T", " ")


@router.get("/workspaces/{slug}")
def get_workspace_dashboard(request: Request, slug: str):
    show_archived = request.query_params.get("show_archived") == "1"
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            operations = repositories.get_guild_operations(
                db, ws["id"], include_archived=show_archived
            )
            archived_count = repositories.count_archived_guild_operations(db, ws["id"])
            readiness_by_op = repositories.get_latest_readiness_snapshots_for_workspace(
                db, ws["id"]
            )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return templates.TemplateResponse(
        request,
        "workspace_dashboard.html",
        {
            "workspace": ws,
            "operations": operations,
            "archived_count": archived_count,
            "show_archived": show_archived,
            "readiness_by_op": readiness_by_op,
            "friendly_dt": _friendly_dt,
            "current_user": user,
            **access,
        },
    )


@router.get("/workspaces/{slug}/members")
def get_workspace_members(request: Request, slug: str):
    error   = request.query_params.get("error")
    success = request.query_params.get("success")
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_manage_members"]:
                raise PermissionDenied("Only owners and officers can manage members.")
            members = repositories.list_workspace_members(db, ws["id"])
            # Reliability is keyed by participant_id.  The members list is
            # keyed by user_id.  Bridge them via display_name — accepted as a
            # dev-era limitation; participant identity is name-based today.
            reliability_scores = repositories.get_player_reliability_scores(
                db, ws["id"]
            )
            participants_ws = repositories.get_participants_for_workspace(db, ws["id"])
            # Albion identity claims for this workspace
            albion_claims   = repositories.list_player_game_identities_for_workspace(
                db, ws["id"]
            )
            albion_pids     = [c["albion_player_id"] for c in albion_claims]
            albion_cache    = repositories.get_albion_character_cache_many(db, albion_pids)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    # Build display_name → participant_id map for template lookups.
    participant_id_by_name: dict[str, str] = {
        p["display_name"]: p["id"] for p in participants_ws
    }
    claims_by_user_id  = {c["user_id"]: c for c in albion_claims}
    cache_by_player_id = {c["albion_player_id"]: c for c in albion_cache}

    return templates.TemplateResponse(
        request,
        "workspace_members.html",
        {
            "workspace":            ws,
            "members":              members,
            "reliability_scores":   reliability_scores,
            "participant_id_by_name": participant_id_by_name,
            "claims_by_user_id":    claims_by_user_id,
            "cache_by_player_id":   cache_by_player_id,
            "error":                error,
            "success":              success,
            "current_user":         user,
            **access,
        },
    )


@router.post("/workspaces/{slug}/members/{target_user_id}/albion/approve")
async def post_approve_albion_claim(request: Request, slug: str, target_user_id: str):
    """Approve a pending Albion character claim (officer/owner only)."""
    members_url = f"/workspaces/{slug}/members"
    try:
        with database.transaction() as db:
            reviewer, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(members_url, str(exc))

    try:
        use_cases.approve_albion_character_claim(
            reviewer_user_id=reviewer["id"],
            target_user_id=target_user_id,
            guild_workspace_id=ws["id"],
        )
    except NotFoundError as exc:
        return _err_redirect(members_url, str(exc))
    except PermissionDenied as exc:
        return _err_redirect(members_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(members_url, str(exc))

    return _ok_redirect(members_url, "Character claim approved.")


@router.post("/workspaces/{slug}/members/{target_user_id}/albion/reject")
async def post_reject_albion_claim(request: Request, slug: str, target_user_id: str):
    """Reject a pending Albion character claim (officer/owner only)."""
    members_url = f"/workspaces/{slug}/members"
    try:
        with database.transaction() as db:
            reviewer, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(members_url, str(exc))

    form        = await request.form()
    review_note = (form.get("review_note") or "").strip()

    try:
        use_cases.reject_albion_character_claim(
            reviewer_user_id=reviewer["id"],
            target_user_id=target_user_id,
            guild_workspace_id=ws["id"],
            review_note=review_note,
        )
    except NotFoundError as exc:
        return _err_redirect(members_url, str(exc))
    except PermissionDenied as exc:
        return _err_redirect(members_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(members_url, str(exc))

    return _ok_redirect(members_url, "Character claim rejected.")


@router.post("/workspaces/{slug}/members/{target_user_id}/remove")
async def post_remove_workspace_member(
    request: Request, slug: str, target_user_id: str
):
    members_url = f"/workspaces/{slug}/members"
    try:
        with database.transaction() as db:
            user, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.remove_workspace_member(
            guild_workspace_id=ws["id"],
            actor_user_id=user["id"],
            target_user_id=target_user_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError as exc:
        return _err_redirect(members_url, str(exc))
    except PermissionDenied as exc:
        return _err_redirect(members_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(members_url, str(exc))
    return _ok_redirect(members_url, "Member removed.")


@router.get("/workspaces/{slug}/members/add")
def get_add_workspace_member(request: Request, slug: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_manage_members"]:
                raise PermissionDenied("Only owners and officers can add members.")
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return templates.TemplateResponse(
        request,
        "workspace_members_add.html",
        {
            "workspace": ws,
            "current_user": user,
            **access,
            "error": None,
            "prev_display_name": "",
            "prev_role": "member",
        },
    )


@router.post("/workspaces/{slug}/members/add")
async def post_add_workspace_member(request: Request, slug: str):
    form = await request.form()
    display_name = form.get("display_name", "").strip()
    role = form.get("role", "member").strip() or "member"
    try:
        with database.transaction() as db:
            user, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.add_workspace_member(
            guild_workspace_id=ws["id"],
            actor_user_id=user["id"],
            display_name=display_name,
            role=role,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(f"/workspaces/{slug}/members/add", str(exc))
    except IronkeepError as exc:
        return _err_redirect(f"/workspaces/{slug}/members/add", str(exc))
    return _ok_redirect(f"/workspaces/{slug}", f"Added {display_name} as {role}.")


# ---------------------------------------------------------------------------
# Discord settings routes
# ---------------------------------------------------------------------------

_DISCORD_SETTINGS_URL = "/workspaces/{slug}/settings/discord"


@router.get("/workspaces/{slug}/settings/discord")
def get_discord_settings(request: Request, slug: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_mutate"]:
                raise PermissionDenied("Only owners and officers can manage Discord settings.")
            discord_meta = _enrich_discord_meta(
                repositories.get_discord_metadata_map(db, ws["id"])
            )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return templates.TemplateResponse(
        request,
        "workspace_discord_settings.html",
        {
            "workspace": ws,
            "current_user": user,
            "discord_meta": discord_meta,
            "metadata_ttl_hours": use_cases._METADATA_CACHE_TTL_HOURS,
            **access,
        },
    )


@router.post("/workspaces/{slug}/settings/discord")
async def post_discord_settings(request: Request, slug: str):
    form = await request.form()
    discord_guild_id = form.get("discord_guild_id", "").strip()
    announcement_channel_id = form.get("announcement_channel_id", "").strip()
    officer_channel_id = form.get("officer_channel_id", "").strip()
    # Checkbox: present = enabled, absent = disabled (standard HTML checkbox behaviour)
    auto_dispatch = form.get("discord_auto_dispatch") == "1"
    reminders_enabled = form.get("discord_reminders_enabled") == "1"
    settings_url = f"/workspaces/{slug}/settings/discord"
    try:
        with database.transaction() as db:
            user, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=user["id"],
            discord_guild_id=discord_guild_id or None,
            announcement_channel_id=announcement_channel_id or None,
            officer_channel_id=officer_channel_id or None,
            auto_dispatch=auto_dispatch,
            reminders_enabled=reminders_enabled,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except IronkeepError as exc:
        return _err_redirect(settings_url, str(exc))

    # Best-effort metadata refresh after the config save commits.
    # Failures are intentionally swallowed — never block or roll back the save.
    try:
        use_cases.refresh_discord_metadata(ws["id"])
    except Exception:  # noqa: BLE001
        pass

    return _ok_redirect(settings_url, "Discord settings saved.")


@router.post("/workspaces/{slug}/settings/discord/refresh-metadata")
async def post_discord_refresh_metadata(request: Request, slug: str):
    """Manual 'Refresh Discord Names' action on the settings page."""
    settings_url = f"/workspaces/{slug}/settings/discord"
    try:
        with database.transaction() as db:
            _user, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.refresh_discord_metadata(ws["id"])
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except IronkeepError as exc:
        return _err_redirect(settings_url, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _err_redirect(settings_url, f"Metadata refresh failed: {exc}")
    return _ok_redirect(settings_url, "Discord names refreshed.")


# ---------------------------------------------------------------------------
# Scheduler status route (read-only observability, owner/officer only)
# ---------------------------------------------------------------------------

# How long since the last scheduler run before we show a "stale" warning.
SCHEDULER_STALE_THRESHOLD_MINUTES: int = 15
# How long a "running" job must have been running (with no finished_at) before
# we consider it stuck / crashed.
SCHEDULER_STUCK_THRESHOLD_MINUTES: int = 10


def _format_utc(ts: str | None) -> str:
    """
    Format an ISO-8601 UTC timestamp for human-readable display.
    Returns '—' for None or unparseable values.
    """
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return ts


def _parse_result_summary(result_json: str | None) -> str:
    """
    Parse top-level primitive (int, float, str, bool) keys from result_json
    and return a compact display string like "checked: 3 · resolved: 2".

    Returns "(invalid result_json)" when the value is not parseable JSON or
    is not a dict.  Returns "" for empty/null input.
    """
    if not result_json:
        return ""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, ValueError):
        return "(invalid result_json)"
    if not isinstance(data, dict):
        return "(invalid result_json)"
    parts = [
        f"{k}: {v}"
        for k, v in data.items()
        if isinstance(v, (int, float, str, bool))
    ]
    return " · ".join(parts)


def _compute_duration(started_at: str | None, finished_at: str | None) -> str:
    """
    Compute a human-readable duration between two ISO-8601 timestamps.
    Returns '—' if either value is absent (unfinished / crashed job).
    """
    if not started_at or not finished_at:
        return "—"
    try:
        start = datetime.fromisoformat(started_at)
        end   = datetime.fromisoformat(finished_at)
        secs  = (end - start).total_seconds()
        return f"{secs:.1f}s" if secs < 60 else f"{secs / 60:.1f}m"
    except (ValueError, TypeError):
        return "—"


def _run_badge_status(run: dict, stuck_cutoff: str) -> str:
    """
    Map a scheduler_runs row to a display status string:
      "success" | "error" | "running" | "stuck"

    A job is "stuck" only when:
    - status == "running"
    - finished_at IS NULL
    - started_at is older than stuck_cutoff
    Recent running jobs (started within the stuck window) remain "running".
    """
    status = run.get("status", "")
    if status != "running":
        return status
    if run.get("finished_at") is not None:
        return "running"  # defensively: finished but status not updated
    if (run.get("started_at") or "") < stuck_cutoff:
        return "stuck"
    return "running"


def _enrich_scheduler_run(run: dict, stuck_cutoff: str) -> dict:
    """Add computed display fields to a raw scheduler_runs row."""
    return {
        **run,
        "duration":        _compute_duration(run.get("started_at"), run.get("finished_at")),
        "started_at_fmt":  _format_utc(run.get("started_at")),
        "finished_at_fmt": _format_utc(run.get("finished_at")),
        "result_summary":  _parse_result_summary(run.get("result_json")),
        "badge_status":    _run_badge_status(run, stuck_cutoff),
    }


def _scheduler_health(runs: list[dict], stale_cutoff: str, stuck_cutoff: str) -> dict:
    """
    Compute overall scheduler health from the recent run list.

    Returns:
      {"status": "never_run"|"ok"|"stale"|"stuck", "message": str}

    Priority: stuck > stale > ok.
    """
    if not runs:
        return {
            "status":  "never_run",
            "message": (
                "The scheduler has never run on this server. "
                "Start it with: SCHEDULER_ENABLED=1 python -m app.scheduler"
            ),
        }

    stuck = [
        r for r in runs
        if r.get("status") == "running"
        and not r.get("finished_at")
        and (r.get("started_at") or "") < stuck_cutoff
    ]
    if stuck:
        s = stuck[0]
        return {
            "status":  "stuck",
            "message": (
                f"A job appears stuck or the scheduler crashed — "
                f"'{s['job_name']}' started at {_format_utc(s.get('started_at'))} "
                f"and never finished."
            ),
        }

    latest_at = runs[0].get("started_at") or ""
    if latest_at < stale_cutoff:
        return {
            "status":  "stale",
            "message": (
                f"Scheduler may be stopped — last activity was at "
                f"{_format_utc(latest_at)}."
            ),
        }

    return {
        "status":  "ok",
        "message": f"Scheduler is active. Last run: {_format_utc(latest_at)}.",
    }


_ERROR_TRUNCATE_LEN: int = 120


def _truncate_error(msg: str | None, max_len: int = _ERROR_TRUNCATE_LEN) -> str:
    """
    Safely truncate an error string for display.
    Returns '—' for None/empty.  Appends '…' when truncated.
    """
    if not msg:
        return "—"
    msg = msg.strip()
    if not msg:
        return "—"
    if len(msg) <= max_len:
        return msg
    return msg[:max_len].rstrip() + "…"


def _enrich_dispatch_failure(row: dict) -> dict:
    """
    Add formatted display fields to a raw discord_dispatch_failures row.

    Added fields:
      attempted_at_fmt   — "YYYY-MM-DD HH:MM UTC" (last attempt / initial insert time)
      next_attempt_at_fmt — formatted next retry window, or "—" if blank
      error_summary      — truncated error_message safe for inline display
      payload_safe        — payload_json if non-empty / non-trivial, else None
                            (hidden behind a disclosure; never rendered inline)
    """
    payload = row.get("payload_json") or ""
    # Suppress trivially empty payloads ({} or whitespace)
    payload_safe = payload.strip() if payload.strip() not in ("", "{}") else None

    return {
        **row,
        "attempted_at_fmt":    _format_utc(row.get("attempted_at")),
        "next_attempt_at_fmt": _format_utc(row.get("next_attempt_at") or None),
        "error_summary":       _truncate_error(row.get("error_message")),
        "payload_safe":        payload_safe,
    }


@router.get("/health")
def get_health(request: Request):
    """
    Lightweight machine-readable health check.

    Returns JSON without requiring authentication.  Exposes only aggregate
    operational metrics — no secrets, no config values, no user data.

    Response shape::

        {
          "status":          "ok" | "degraded",
          "db_reachable":    bool,
          "wal_mode":        bool,
          "scheduler":       "ok" | "stale" | "stuck" | "never_run",
          "scheduler_last_seen_at": str | null,
          "pending_retries": int,
          "recent_error_runs_24h": int
        }
    """
    try:
        with database.transaction() as db:
            db_info          = diag.db_health(db)
            runs             = repositories.get_recent_scheduler_runs(db, limit=20)
            pending_retries  = repositories.get_global_pending_retry_count(db)
            recent_errors    = repositories.get_recent_error_run_count(db, hours=24)
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db_reachable": False},
        )

    sched = diag.scheduler_health(runs)
    degraded = (
        not db_info["reachable"]
        or sched["status"] in ("stuck",)
    )

    return JSONResponse(
        status_code=503 if degraded else 200,
        content={
            "status":                "degraded" if degraded else "ok",
            "db_reachable":         db_info["reachable"],
            "wal_mode":             db_info.get("wal_mode", False),
            "scheduler":            sched["status"],
            "scheduler_last_seen_at": sched["last_seen_at"],
            "pending_retries":      pending_retries,
            "recent_error_runs_24h": recent_errors,
        },
    )


@router.get("/workspaces/{slug}/settings/diagnostics")
def get_diagnostics(request: Request, slug: str):
    """
    Workspace-scoped operational diagnostics page.

    Officer/owner-gated.  Displays DB health, scheduler state, retry backlog,
    and recent error run count in a human-readable layout.  No charts.  No live
    polling.  No mutation side effects.
    """
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_mutate"]:
                raise PermissionDenied("Only officers and owners can view diagnostics.")
            runs            = repositories.get_recent_scheduler_runs(db, limit=20)
            pending_retries = repositories.get_global_pending_retry_count(db)
            ws_pending      = repositories.count_pending_dispatch_failures(db, ws["id"])
            recent_errors   = repositories.get_recent_error_run_count(db, hours=24)
            db_info         = diag.db_health(db)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    sched         = diag.scheduler_health(runs)
    db_file_info  = backup.get_db_file_info(database._DB_PATH)

    return templates.TemplateResponse(
        request,
        "workspace_diagnostics.html",
        {
            "workspace":         ws,
            "current_user":      user,
            "db_info":           db_info,
            "db_file_info":      db_file_info,
            "scheduler_health":  sched,
            "pending_retries":   pending_retries,
            "ws_pending":        ws_pending,
            "recent_errors":     recent_errors,
            "format_utc":        diag.format_utc,
            "workspace_nav_active": "diagnostics",
            **access,
        },
    )


@router.get("/workspaces/{slug}/settings/scheduler")
def get_scheduler_status(request: Request, slug: str):
    """
    Read-only scheduler health + run history page.

    Shows:
    - Health banner (never_run / ok / stale / stuck)
    - Pending Discord dispatch failures for this workspace
    - Recent scheduler_runs table (global, not workspace-scoped)

    No POST routes. No job execution. No retry buttons.
    """
    from datetime import timezone  # noqa: PLC0415

    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_mutate"]:
                raise PermissionDenied("Only owners and officers can view scheduler status.")
            runs              = repositories.get_recent_scheduler_runs(db, limit=60)
            pending_count     = repositories.count_pending_dispatch_failures(db, ws["id"])
            pending_failures  = repositories.list_pending_dispatch_failures_for_workspace(
                db, ws["id"], limit=50
            )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    now          = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(minutes=SCHEDULER_STALE_THRESHOLD_MINUTES)).isoformat()
    stuck_cutoff = (now - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES)).isoformat()

    health            = _scheduler_health(runs, stale_cutoff, stuck_cutoff)
    enriched          = [_enrich_scheduler_run(r, stuck_cutoff) for r in runs]
    enriched_failures = [_enrich_dispatch_failure(f) for f in pending_failures]

    return templates.TemplateResponse(
        request,
        "workspace_scheduler_status.html",
        {
            "workspace":          ws,
            "current_user":       user,
            "runs":               enriched,
            "pending_count":      pending_count,
            "pending_failures":   enriched_failures,
            "health":             health,
            **access,
        },
    )


# ---------------------------------------------------------------------------
# Composition routes
# ---------------------------------------------------------------------------

@router.get("/workspaces/{slug}/compositions")
def get_compositions_list(request: Request, slug: str):
    show_deleted = request.query_params.get("show_deleted") == "1"
    error   = request.query_params.get("error")
    success = request.query_params.get("success")
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            compositions = repositories.get_albion_compositions(
                db, ws["id"], include_deleted=show_deleted
            )
            deleted_count = repositories.count_deleted_albion_compositions(db, ws["id"])
            slot_counts = {
                c["id"]: len(
                    repositories.get_composition_slot_templates(db, c["id"], ws["id"])
                )
                for c in compositions
            }
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return templates.TemplateResponse(
        request,
        "compositions_list.html",
        {
            "workspace": ws,
            "current_user": user,
            "compositions": compositions,
            "slot_counts": slot_counts,
            "deleted_count": deleted_count,
            "show_deleted": show_deleted,
            "error": error,
            "success": success,
            **access,
        },
    )


@router.post("/workspaces/{slug}/compositions/{comp_id}/retire")
async def post_retire_composition(request: Request, slug: str, comp_id: str):
    compositions_url = f"/workspaces/{slug}/compositions"
    try:
        with database.transaction() as db:
            user, ws, _access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp_id,
            actor_user_id=user["id"],
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError as exc:
        return _err_redirect(compositions_url, str(exc))
    except PermissionDenied as exc:
        return _err_redirect(compositions_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(compositions_url, str(exc))
    return _ok_redirect(compositions_url, "Composition retired.")


@router.get("/workspaces/{slug}/compositions/new")
def get_new_composition(request: Request, slug: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_mutate"]:
                raise PermissionDenied("You do not have permission for this action.")
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return templates.TemplateResponse(
        request,
        "compositions_new.html",
        {
            "workspace": ws,
            "current_user": user,
            "error": None,
            "prev_name": "",
            "prev_description": "",
            **access,
        },
    )


@router.post("/workspaces/{slug}/compositions")
async def post_create_composition(request: Request, slug: str):
    form = await request.form()
    name        = form.get("name", "").strip()
    description = form.get("description", "").strip() or None

    party_numbers = form.getlist("party_number")
    slot_indices  = form.getlist("slot_index")
    roles         = form.getlist("role")
    build_names   = form.getlist("build_name")
    weapon_names  = form.getlist("weapon_name")
    priorities    = form.getlist("priority")

    slots: list[dict] = []
    for i in range(len(roles)):
        role  = roles[i].strip()       if i < len(roles)       else ""
        build = build_names[i].strip() if i < len(build_names) else ""
        if not role or not build:
            continue
        try:
            pn = int(party_numbers[i]) if i < len(party_numbers) else 1
            si = int(slot_indices[i])  if i < len(slot_indices)  else i + 1
        except (ValueError, TypeError):
            continue
        slots.append({
            "party_number": pn,
            "slot_index":   si,
            "role":         role,
            "build_name":   build,
            "weapon_name":  weapon_names[i].strip() or None if i < len(weapon_names) else None,
            "priority":     priorities[i] if i < len(priorities) else "normal",
        })

    try:
        with database.transaction() as db:
            user, ws, access = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name=name,
            description=description,
            slots=slots,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(f"/workspaces/{slug}/compositions/new", str(exc))
    except IronkeepError as exc:
        return templates.TemplateResponse(
            request,
            "compositions_new.html",
            {
                "workspace": ws,
                "current_user": user,
                "error": str(exc),
                "prev_name": name,
                "prev_description": description or "",
                **access,
            },
        )
    return _redirect(f"/workspaces/{slug}/compositions")


# ---------------------------------------------------------------------------
# Operation routes — create + detail
# ---------------------------------------------------------------------------

@router.get("/workspaces/{slug}/operations/new")
def get_new_operation(request: Request, slug: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            if not access["can_mutate"]:
                raise PermissionDenied("You do not have permission for this action.")
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return templates.TemplateResponse(
        request,
        "operation_new.html",
        {
            "workspace": ws,
            "current_user": user,
            "default_start": _tomorrow_2000(),
            "error": None,
            "prev_title": "",
            "prev_type": "zvz",
            **access,
        },
    )


@router.post("/workspaces/{slug}/operations")
async def post_create_operation(request: Request, slug: str):
    form = await request.form()
    title              = form.get("title", "").strip()
    operation_type     = form.get("operation_type", "zvz")
    scheduled_start_at = form.get("scheduled_start_at", "").strip()

    new_url = f"/workspaces/{slug}/operations/new"
    try:
        with database.transaction() as db:
            user, ws, mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        op = use_cases.create_guild_operation(
            guild_workspace_id=ws["id"],
            title=title,
            operation_type=operation_type,
            scheduled_start_at=scheduled_start_at,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(new_url, str(exc))
    except IronkeepError as exc:
        access_ctx = authz.membership_context(mem)
        return templates.TemplateResponse(
            request,
            "operation_new.html",
            {
                "workspace": ws,
                "current_user": user,
                "default_start": scheduled_start_at or _tomorrow_2000(),
                "error": str(exc),
                "prev_title": title,
                "prev_type": operation_type,
                **access_ctx,
            },
        )
    return _redirect(f"/workspaces/{slug}/operations/{op['id']}")


@router.get("/workspaces/{slug}/operations/{op_id}")
def get_operation_detail(request: Request, slug: str, op_id: str):
    error   = request.query_params.get("error")
    success = request.query_params.get("success")

    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise HTTPException(status_code=404, detail="Operation not found.")

            plan         = repositories.get_operation_plan(db, op_id, ws["id"])
            slot_count   = repositories.count_operation_slots(db, op_id, ws["id"])
            signups      = repositories.get_signup_intents(db, op_id, ws["id"])
            readiness    = _enrich_readiness(
                repositories.get_latest_readiness_snapshot(db, op_id, ws["id"])
            )
            # Active only — retired compositions must not appear in the dropdown.
            compositions = repositories.get_albion_compositions(db, ws["id"], include_deleted=False)

            composition = None
            if plan:
                # Single-row lookup intentionally bypasses the deleted filter so
                # retired compositions still display correctly on the detail page.
                composition = repositories.get_albion_composition(
                    db, plan["albion_composition_id"], ws["id"]
                )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Discord announcement preview + post button — owner/officer only, read-only.
    # No API calls; format_operation_announcement() is the single source of truth.
    discord_preview = None
    discord_config_gap = None
    discord_announcement_msg = None
    if access.get("can_mutate"):
        if not ws.get("discord_guild_id"):
            discord_config_gap = "no_guild"
        elif not ws.get("discord_announcement_channel_id"):
            discord_config_gap = "no_channel"
        else:
            raw_payload = format_operation_announcement(op, readiness)
            embed = raw_payload["embeds"][0]
            discord_preview = {
                **embed,
                "color_hex": "#{:06x}".format(embed.get("color", 0x95A5A6)),
            }
            # Check for an existing posted message to drive the button label.
            with database.transaction() as db:
                discord_announcement_msg = repositories.get_discord_message(
                    db, ws["id"], op["id"], "announcement"
                )

    with database.transaction() as db:
        discord_meta = _enrich_discord_meta(
            repositories.get_discord_metadata_map(db, ws["id"])
        )

    return templates.TemplateResponse(
        request,
        "operation_detail.html",
        {
            "workspace":                ws,
            "operation":                op,
            "plan":                     plan,
            "composition":              composition,
            "slot_count":               slot_count,
            "signup_count":             len(signups),
            "readiness":                readiness,
            "compositions":             compositions,
            "discord_preview":          discord_preview,
            "discord_config_gap":       discord_config_gap,
            "discord_announcement_msg": discord_announcement_msg,
            "discord_meta":             discord_meta,
            "active_tab":               "overview",
            "error":                    error,
            "success":                  success,
            "current_user":             user,
            **access,
            **_operation_mutation_flags(op),
        },
    )


# ---------------------------------------------------------------------------
# Discord announcement — explicit officer post action
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/discord/announce")
async def post_discord_announce(request: Request, slug: str, op_id: str):
    detail_url = f"/workspaces/{slug}/operations/{op_id}"
    try:
        with database.transaction() as db:
            user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        result = use_cases.post_discord_announcement(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            actor_id=user["id"],
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace or operation not found.")
    except PermissionDenied as exc:
        return _err_redirect(detail_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(detail_url, str(exc))

    action = result["action"]
    msg = (
        "Announcement posted to Discord."
        if action == "posted"
        else "Discord announcement updated."
    )
    return _ok_redirect(detail_url, msg)


# ---------------------------------------------------------------------------
# Discord roster — explicit officer post action
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/discord/roster")
async def post_discord_roster(request: Request, slug: str, op_id: str):
    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        result = use_cases.post_discord_roster(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            actor_id=user["id"],
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace or operation not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))

    action = result["action"]
    msg = "Roster posted to Discord." if action == "posted" else "Discord roster updated."
    return _ok_redirect(planner_url, msg)


# ---------------------------------------------------------------------------
# Operation — plan attach (Slice B)
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/plan")
async def post_attach_plan(request: Request, slug: str, op_id: str):
    form = await request.form()
    albion_composition_id = form.get("albion_composition_id", "").strip()
    signup_status         = form.get("signup_status", "open")
    notes                 = form.get("notes", "").strip() or None

    detail_url = f"/workspaces/{slug}/operations/{op_id}"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            albion_composition_id=albion_composition_id,
            signup_status=signup_status,
            notes=notes,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(detail_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(detail_url, str(exc))
    return _ok_redirect(detail_url, "Plan attached.")


# ---------------------------------------------------------------------------
# Operation — generate slots (Slice B)
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/generate-slots")
async def post_generate_slots(request: Request, slug: str, op_id: str):
    detail_url = f"/workspaces/{slug}/operations/{op_id}"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        slots = use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(detail_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(detail_url, str(exc))
    return _ok_redirect(detail_url, f"{len(slots)} slots generated.")


# ---------------------------------------------------------------------------
# Signup routes (Slice B)
# ---------------------------------------------------------------------------

def _operation_mutation_flags(op: dict) -> dict[str, bool]:
    status = op["status"]
    return {
        "can_attach_plan": status in guild_operations.PLAN_ATTACHMENT_ALLOWED_STATUSES,
        "can_generate_slots": status in guild_operations.SLOT_GENERATION_ALLOWED_STATUSES,
        "can_mutate_assignments": status in guild_operations.ASSIGNMENT_MUTATION_ALLOWED_STATUSES,
        "can_mutate_reserves": status in guild_operations.RESERVE_MUTATION_ALLOWED_STATUSES,
        "can_record_attendance": status in guild_operations.ATTENDANCE_RECORDING_ALLOWED_STATUSES,
        "can_record_scout_attendance": status in guild_operations.SCOUT_ATTENDANCE_RECORDING_ALLOWED_STATUSES,
        "can_recalculate_readiness": status in guild_operations.READINESS_RECALCULATION_ALLOWED_STATUSES,
    }


def _signup_page_state(op: dict, plan: dict | None) -> tuple[bool, str | None]:
    if op["status"] != "planning":
        if op["status"] == "draft":
            return False, (
                "Signups are not open yet. Publish the operation from Overview "
                "before accepting signups."
            )
        return False, (
            f"Signups are closed because the operation status is '{op['status']}'."
        )
    if plan and plan["signup_status"] == "closed":
        return False, "Signups are closed for this operation."
    return True, None


@router.get("/workspaces/{slug}/operations/{op_id}/signup")
def get_signup(request: Request, slug: str, op_id: str):
    error   = request.query_params.get("error")
    success = request.query_params.get("success")

    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise HTTPException(status_code=404, detail="Operation not found.")
            plan = repositories.get_operation_plan(db, op_id, ws["id"])
            signups = repositories.get_signups_with_display_names(db, op_id, ws["id"])
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    signup_open, signup_closed_reason = _signup_page_state(op, plan)

    return templates.TemplateResponse(
        request,
        "operation_signup.html",
        {
            "workspace": ws,
            "operation": op,
            "signups": signups,
            "error": error,
            "success": success,
            "active_tab": "signup",
            "signup_open": signup_open,
            "signup_closed_reason": signup_closed_reason,
            "prev_name": "",
            "prev_role": "",
            "prev_build": "",
            "current_user": user,
            **access,
        },
    )


@router.post("/workspaces/{slug}/operations/{op_id}/signup")
async def post_signup(request: Request, slug: str, op_id: str):
    form = await request.form()
    display_name   = form.get("display_name", "").strip()
    preferred_role = form.get("preferred_role", "").strip()
    preferred_build = form.get("preferred_build_name", "").strip() or None
    willingness    = form.get("willingness", "specific")
    availability   = form.get("availability", "confirmed")

    signup_url = f"/workspaces/{slug}/operations/{op_id}/signup"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=False, allow_signup=True
            )
        use_cases.submit_signup_intent(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            display_name=display_name,
            preferred_role=preferred_role,
            preferred_build_name=preferred_build,
            willingness=willingness,
            availability=availability,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(signup_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(signup_url, str(exc))
    return _ok_redirect(signup_url, f"Signup recorded for {display_name}.")


@router.post("/workspaces/{slug}/operations/{op_id}/signups/{signup_id}/withdraw")
async def post_withdraw_signup(request: Request, slug: str, op_id: str, signup_id: str):
    signup_url = f"/workspaces/{slug}/operations/{op_id}/signup"
    try:
        with database.transaction() as db:
            user, ws, _mem = authz.resolve_workspace_view(db, request, slug)
            if not user:
                raise AuthenticationRequired()
        use_cases.withdraw_signup_intent(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            actor_user_id=user["id"],
            signup_id=signup_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Not found.")
    except PermissionDenied as exc:
        return _err_redirect(signup_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(signup_url, str(exc))
    return _ok_redirect(signup_url, "Signup withdrawn.")


# ---------------------------------------------------------------------------
# Planner board (Slice B)
# ---------------------------------------------------------------------------

@router.get("/workspaces/{slug}/operations/{op_id}/planner")
def get_planner(request: Request, slug: str, op_id: str):
    error   = request.query_params.get("error")
    success = request.query_params.get("success")

    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise HTTPException(status_code=404, detail="Operation not found.")

            # Slot state comes from operation_slots + assignments only.
            # composition_slot_templates is never read here.
            slots        = repositories.get_operation_slots(db, op_id, ws["id"])
            assigned_map = repositories.get_assigned_participants_for_operation(db, op_id, ws["id"])
            participants = repositories.get_participants_for_operation(db, op_id, ws["id"])
            signups      = repositories.get_signups_with_display_names(db, op_id, ws["id"])
            reserves     = repositories.get_reserves_for_operation(db, op_id, ws["id"])
            readiness    = _enrich_readiness(
                repositories.get_latest_readiness_snapshot(db, op_id, ws["id"])
            )
            # Roster Discord message row — owner/officer only.
            discord_roster_msg = None
            if access.get("can_mutate"):
                discord_roster_msg = repositories.get_discord_message(
                    db, ws["id"], op_id, "roster"
                )
            # Reliability scores — officer planning context only.
            reliability_scores: dict = {}
            if access.get("can_mutate"):
                reliability_scores = repositories.get_player_reliability_scores(
                    db, ws["id"]
                )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Discord roster preview — pure formatting, owner/officer only, no API calls.
    discord_roster_preview = None
    discord_roster_config_gap = None
    if access.get("can_mutate"):
        if not ws.get("discord_guild_id"):
            discord_roster_config_gap = "no_guild"
        elif not ws.get("discord_announcement_channel_id"):
            discord_roster_config_gap = "no_channel"
        elif slots:
            roster_assignments = [
                {"slot_id": sid, "display_name": info["display_name"]}
                for sid, info in assigned_map.items()
            ]
            raw = format_roster(op, slots, roster_assignments)
            embed = raw["embeds"][0]
            discord_roster_preview = {
                **embed,
                "color_hex": "#{:06x}".format(embed.get("color", 0x95A5A6)),
            }

    # Group slots by party number for template iteration.
    parties: dict[int, list] = {}
    for slot in slots:
        parties.setdefault(slot["party_number"], []).append(slot)

    # Participants who are not yet assigned to any slot in this operation.
    # An open slot is shown only by the absence of an active assignment row.
    assigned_participant_ids = {v["participant_id"] for v in assigned_map.values()}
    unassigned_participants  = [p for p in participants if p["id"] not in assigned_participant_ids]

    # Build signup-preference lookup for sorting.
    signup_prefs = {s["participant_id"]: s for s in signups}

    # Mark which unassigned participants are on reserve so the dropdown can
    # show the [bench] indicator.  The is_reserve flag is passed through
    # sort_participants_for_slot unchanged.
    reserve_ids = {r["participant_id"] for r in reserves}
    unassigned_with_reserve_flag = [
        {**p, "is_reserve": p["id"] in reserve_ids}
        for p in unassigned_participants
    ]

    # Per-slot sorted participant list.  Every open slot with at least one
    # unassigned signer shows the full dropdown — matching participants first.
    # The caller may assign any participant regardless of role preference.
    slot_participants: dict[str, list] = {
        slot["id"]: sort_participants_for_slot(
            slot, unassigned_with_reserve_flag, signup_prefs
        )
        for slot in slots
    }

    # Per-slot quick-assign eligibility: non-reserved unassigned signers only.
    # Used by the template to decide whether to render the Quick ★ button.
    non_reserved_unassigned = [
        p for p in unassigned_participants if p["id"] not in reserve_ids
    ]
    slot_has_quick_candidates: dict[str, bool] = {
        slot["id"]: any(True for _ in non_reserved_unassigned)
        for slot in slots
        if slot["id"] not in assigned_map
    }

    # Participants eligible to be placed on reserve: signed up, not assigned,
    # not already on reserve.
    eligible_for_reserve = [
        p for p in unassigned_participants if p["id"] not in reserve_ids
    ]

    with database.transaction() as db:
        discord_meta = _enrich_discord_meta(
            repositories.get_discord_metadata_map(db, ws["id"])
        )

    return templates.TemplateResponse(
        request,
        "operation_planner.html",
        {
            "workspace":                  ws,
            "operation":                  op,
            "parties":                    parties,
            "assigned_map":               assigned_map,
            "participants":               participants,
            "unassigned_participants":    unassigned_participants,
            "signup_prefs":               signup_prefs,
            "slot_participants":          slot_participants,
            "slot_has_quick_candidates":  slot_has_quick_candidates,
            "reserves":                   reserves,
            "eligible_for_reserve":       eligible_for_reserve,
            "readiness":                  readiness,
            "discord_roster_preview":     discord_roster_preview,
            "discord_roster_config_gap":  discord_roster_config_gap,
            "discord_roster_msg":         discord_roster_msg,
            "discord_meta":               discord_meta,
            "reliability_scores":         reliability_scores,
            "active_tab":                 "planner",
            "error":                      error,
            "success":                    success,
            "current_user":               user,
            **access,
            **_operation_mutation_flags(op),
        },
    )


# ---------------------------------------------------------------------------
# Assign participant to slot (Slice B)
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/slots/{slot_id}/assign")
async def post_assign(request: Request, slug: str, op_id: str, slot_id: str):
    form = await request.form()
    participant_id = form.get("participant_id", "").strip()

    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.assign_participant_to_operation_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            operation_slot_id=slot_id,
            participant_id=participant_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))
    return _ok_redirect(planner_url)


# ---------------------------------------------------------------------------
# Remove assignment (Assignment lifecycle)
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/assignments/{assignment_id}/remove")
async def post_remove_assignment(
    request: Request, slug: str, op_id: str, assignment_id: str
):
    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.remove_assignment(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            assignment_id=assignment_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))
    return _ok_redirect(planner_url, "Assignment removed.")


# ---------------------------------------------------------------------------
# Quick assign — single slot
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/slots/{slot_id}/quick-assign")
async def post_quick_assign(request: Request, slug: str, op_id: str, slot_id: str):
    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.quick_assign_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            operation_slot_id=slot_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))
    return _ok_redirect(planner_url, f"Quick assigned: slot filled.")


# ---------------------------------------------------------------------------
# Quick fill — whole party
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/parties/{party_number}/quick-fill")
async def post_quick_fill_party(
    request: Request, slug: str, op_id: str, party_number: int
):
    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        result = use_cases.quick_fill_party(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            party_number=party_number,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))

    n = result["filled_count"]
    total = result["total_open"]
    if n == 0:
        msg = f"0 slots filled — no eligible candidates for Party {party_number}."
    else:
        msg = f"Filled {n}/{total} open slots in Party {party_number}."
    return _ok_redirect(planner_url, msg)


# ---------------------------------------------------------------------------
# Reserve (bench) management
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/reserves")
async def post_add_reserve(request: Request, slug: str, op_id: str):
    form           = await request.form()
    participant_id = (form.get("participant_id") or "").strip()
    notes          = (form.get("notes") or "").strip() or None

    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.mark_participant_as_reserve(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            participant_id=participant_id,
            notes=notes,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))
    return _ok_redirect(planner_url, "Participant added to reserve.")


@router.post("/workspaces/{slug}/operations/{op_id}/reserves/{participant_id}/remove")
async def post_remove_reserve(
    request: Request, slug: str, op_id: str, participant_id: str
):
    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.remove_reserve(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            participant_id=participant_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))
    return _ok_redirect(planner_url, "Participant removed from reserve.")


# ---------------------------------------------------------------------------
# Recalculate readiness (Slice B)
# ---------------------------------------------------------------------------

@router.post("/workspaces/{slug}/operations/{op_id}/readiness")
async def post_readiness(request: Request, slug: str, op_id: str):
    planner_url = f"/workspaces/{slug}/operations/{op_id}/planner"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        snap = use_cases.calculate_readiness_snapshot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(planner_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(planner_url, str(exc))

    state    = snap["readiness_state"].upper()
    assigned = snap["assigned_slots"]
    total    = snap["total_slots"]
    return _ok_redirect(planner_url, f"Readiness: {state} ({assigned}/{total} slots filled)")


# ---------------------------------------------------------------------------
# Operation status lifecycle
# ---------------------------------------------------------------------------

def _status_redirect(slug: str, op_id: str):
    return f"/workspaces/{slug}/operations/{op_id}"


@router.post("/workspaces/{slug}/operations/{op_id}/publish")
async def post_publish_operation(request: Request, slug: str, op_id: str):
    dest = _status_redirect(slug, op_id)
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.publish_operation(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(dest, str(exc))
    except IronkeepError as exc:
        return _err_redirect(dest, str(exc))
    return _ok_redirect(dest, "Operation published — signups are now open.")


@router.post("/workspaces/{slug}/operations/{op_id}/lock")
async def post_lock_operation(request: Request, slug: str, op_id: str):
    dest = _status_redirect(slug, op_id)
    # Allow the planner page to request a redirect back to itself after locking.
    # Only the exact planner URL for this operation is accepted — no open redirect.
    form = await request.form()
    next_val = form.get("next", "")
    _planner_next = f"/workspaces/{slug}/operations/{op_id}/planner"
    if next_val == _planner_next:
        dest = _planner_next
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.lock_operation(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(dest, str(exc))
    except IronkeepError as exc:
        return _err_redirect(dest, str(exc))
    return _ok_redirect(dest, "Operation locked — roster frozen.")


@router.post("/workspaces/{slug}/operations/{op_id}/complete")
async def post_complete_operation(request: Request, slug: str, op_id: str):
    dest = _status_redirect(slug, op_id)
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.complete_operation(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(dest, str(exc))
    except IronkeepError as exc:
        return _err_redirect(dest, str(exc))
    return _ok_redirect(dest, "Operation marked as completed.")


@router.post("/workspaces/{slug}/operations/{op_id}/archive")
async def post_archive_operation(request: Request, slug: str, op_id: str):
    dest = _status_redirect(slug, op_id)
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.archive_operation(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(dest, str(exc))
    except IronkeepError as exc:
        return _err_redirect(dest, str(exc))
    return _ok_redirect(dest, "Operation archived.")


# ---------------------------------------------------------------------------
# Event timeline (Slice B)
# ---------------------------------------------------------------------------

# Maps operation-level event_type → (group, human_label).
# Workspace-level events (workspace.created, workspace.member.removed, etc.)
# never appear on the operation timeline and are intentionally omitted.
_EVENT_LABELS: dict[str, tuple[str, str]] = {
    # Lifecycle
    "guild_operation.created":   ("lifecycle",   "Operation created"),
    "guild_operation.published": ("lifecycle",   "Published for planning"),
    "guild_operation.locked":    ("lifecycle",   "Roster locked"),
    "guild_operation.completed": ("lifecycle",   "Marked complete"),
    "guild_operation.archived":  ("lifecycle",   "Archived"),
    # Plan
    "operation_plan.attached":   ("plan",        "Composition plan attached"),
    "operation_slots.generated": ("plan",        "Operation slots generated"),
    # Signups
    "signup_intent.submitted":   ("signups",     "Signup submitted"),
    "signup_intent.withdrawn":   ("signups",     "Signup withdrawn"),
    # Assignments / reserves
    "assignment.created":        ("assignments", "Participant assigned"),
    "assignment.removed":        ("assignments", "Assignment removed"),
    "reserve.created":           ("assignments", "Added to reserve"),
    "reserve.removed":           ("assignments", "Removed from reserve"),
    # Readiness
    "readiness_snapshot.created":("readiness",   "Readiness snapshot recorded"),
    # Attendance
    "attendance.recorded":       ("attendance",  "Attendance marked"),
    "scout_attendance.recorded": ("attendance",  "Scout checked in"),
    "support_attendance.recorded":("attendance", "Support checked in"),
    # Discord
    "discord_announcement.posted":  ("discord", "Announcement posted to Discord"),
    "discord_announcement.updated": ("discord", "Discord announcement updated"),
    "discord_roster.posted":        ("discord", "Roster posted to Discord"),
    "discord_roster.updated":       ("discord", "Discord roster updated"),
    # Payout ledger
    "payout_ledger.entry.created":  ("ledger",  "Ledger entry created"),
    "payout_ledger.entry.updated":  ("ledger",  "Ledger entry updated"),
    "payout_ledger.entry.approved": ("ledger",  "Ledger entry approved"),
    "payout_ledger.entry.paid":     ("ledger",  "Ledger entry paid"),
    "payout_ledger.entry.voided":   ("ledger",  "Ledger entry voided"),
}


def _enrich_timeline_events(events: list[dict]) -> list[dict]:
    """
    Reverse to newest-first and attach _group / _label to each event.
    Unknown event types fall back to group 'other' with the raw event_type as label.
    Payout ledger events also get a _payout_detail dict for structured rendering.
    """
    result = []
    for e in reversed(events):
        group, label = _EVENT_LABELS.get(e["event_type"], ("other", e["event_type"]))
        enriched = {**e, "_group": group, "_label": label, "_payout_detail": None}
        if group == "ledger":
            enriched["_payout_detail"] = _parse_payout_event_detail(e)
        result.append(enriched)
    return result


def _parse_payout_event_detail(event: dict) -> dict | None:
    """
    Parse a payout ledger event's payload_json into a human-readable detail dict.

    Returns a dict with keys present in the payload:
      entry_type, amount_silver, participant_id, note
    All values are safely coerced; missing keys return None.
    Returns None if payload_json is absent or unparseable.
    """
    payload_raw = event.get("payload_json") or "{}"
    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "entry_type":    payload.get("entry_type"),
        "amount_silver": payload.get("amount_silver"),
        "note":          payload.get("note"),
        "participant_id": payload.get("participant_id"),
    }


def compute_ledger_totals(entries: list[dict]) -> dict:
    """
    Compute per-status aggregates from an already-loaded list of ledger entries.

    This is the route-layer twin of repositories.get_ledger_totals_for_operation.
    Use this when entries are already in memory (avoids an extra DB round-trip).
    Voided entries are counted but their amounts are excluded from active_total.

    Returns a dict with keys:
      draft_count, draft_total
      approved_count, approved_total
      paid_count, paid_total
      voided_count              (no voided_total — excluded by design)
      active_count              (draft + approved + paid)
      active_total              (sum of draft + approved + paid amounts)
    """
    totals: dict[str, int] = {
        "draft_count": 0,    "draft_total": 0,
        "approved_count": 0, "approved_total": 0,
        "paid_count": 0,     "paid_total": 0,
        "voided_count": 0,
        "active_count": 0,   "active_total": 0,
    }
    for e in entries:
        status = e.get("status", "")
        amount = e.get("amount_silver", 0) or 0
        if status == "draft":
            totals["draft_count"]    += 1
            totals["draft_total"]    += amount
            totals["active_count"]   += 1
            totals["active_total"]   += amount
        elif status == "approved":
            totals["approved_count"] += 1
            totals["approved_total"] += amount
            totals["active_count"]   += 1
            totals["active_total"]   += amount
        elif status == "paid":
            totals["paid_count"]     += 1
            totals["paid_total"]     += amount
            totals["active_count"]   += 1
            totals["active_total"]   += amount
        elif status == "voided":
            totals["voided_count"]   += 1
    return totals


@router.get("/workspaces/{slug}/operations/{op_id}/timeline")
def get_timeline(request: Request, slug: str, op_id: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise HTTPException(status_code=404, detail="Operation not found.")
            raw_events = repositories.get_operational_events(db, ws["id"], op_id)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    return templates.TemplateResponse(
        request,
        "operation_timeline.html",
        {
            "workspace": ws,
            "operation": op,
            "events": _enrich_timeline_events(raw_events),
            "active_tab": "timeline",
            "current_user": user,
            **access,
        },
    )


# ---------------------------------------------------------------------------
# Attendance (Attendance foundation slice)
# ---------------------------------------------------------------------------

@router.get("/workspaces/{slug}/operations/{op_id}/attendance")
def get_attendance(request: Request, slug: str, op_id: str):
    error   = request.query_params.get("error")
    success = request.query_params.get("success")

    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise HTTPException(status_code=404, detail="Operation not found.")
            assignments   = repositories.get_assignments_with_attendance(db, op_id, ws["id"])
            scout_records = repositories.get_scout_attendance_records_for_operation(
                db, op_id, ws["id"]
            )
            # Reliability scores — officer planning context, not shown to members.
            reliability_scores: dict = {}
            if access.get("can_mutate"):
                reliability_scores = repositories.get_player_reliability_scores(
                    db, ws["id"]
                )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    return templates.TemplateResponse(
        request,
        "operation_attendance.html",
        {
            "workspace": ws,
            "operation": op,
            "assignments":       assignments,
            "scout_records":     scout_records,
            "statuses":          attendance_domain.STATUS_ORDER,
            "role_types":        scout_attendance_domain.ROLE_TYPE_ORDER,
            "reliability_scores": reliability_scores,
            "active_tab": "attendance",
            "error": error,
            "success": success,
            "current_user": user,
            **access,
            **_operation_mutation_flags(op),
        },
    )


@router.post("/workspaces/{slug}/operations/{op_id}/attendance")
async def post_attendance(request: Request, slug: str, op_id: str):
    form          = await request.form()
    assignment_id = (form.get("assignment_id") or "").strip()
    status        = (form.get("status") or "").strip()
    notes         = (form.get("notes") or "").strip() or None

    attendance_url = f"/workspaces/{slug}/operations/{op_id}/attendance"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        use_cases.record_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            assignment_id=assignment_id,
            status=status,
            notes=notes,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(attendance_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(attendance_url, str(exc))

    return _ok_redirect(attendance_url, "Attendance recorded.")


@router.post("/workspaces/{slug}/operations/{op_id}/attendance/bulk-present")
async def post_bulk_mark_present(request: Request, slug: str, op_id: str):
    attendance_url = f"/workspaces/{slug}/operations/{op_id}/attendance"
    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
        count = use_cases.bulk_mark_present(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
        )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(attendance_url, str(exc))
    except IronkeepError as exc:
        return _err_redirect(attendance_url, str(exc))

    if count == 0:
        return _ok_redirect(attendance_url, "All participants are already marked.")
    return _ok_redirect(attendance_url, f"Marked {count} participant(s) as present.")


@router.post("/workspaces/{slug}/operations/{op_id}/attendance/scout")
async def post_scout_attendance(request: Request, slug: str, op_id: str):
    form         = await request.form()
    display_name = (form.get("display_name") or "").strip()
    role_type    = (form.get("role_type") or "").strip()
    notes        = (form.get("notes") or "").strip() or None

    attendance_url = f"/workspaces/{slug}/operations/{op_id}/attendance"

    try:
        with database.transaction() as db:
            _user, ws, _mem = authz.authorize_workspace_action(
                db, request, slug, require_mutator=True
            )
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except PermissionDenied as exc:
        return _err_redirect(attendance_url, str(exc))

    if not display_name:
        return _err_redirect(attendance_url, "Name is required.")

    try:
        use_cases.record_scout_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            display_name=display_name,
            role_type=role_type,
            notes=notes,
        )
    except IronkeepError as exc:
        return _err_redirect(attendance_url, str(exc))

    return _ok_redirect(attendance_url, f"{display_name} checked in as {role_type}.")


# ---------------------------------------------------------------------------
# Payout Ledger routes
# ---------------------------------------------------------------------------

@router.get("/workspaces/{slug}/operations/{op_id}/ledger")
def get_operation_ledger(request: Request, slug: str, op_id: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise NotFoundError("Operation not found.")
            if not access["can_mutate"]:
                raise PermissionDenied("Only officers and owners can view the ledger.")
            entries      = repositories.list_payout_ledger_entries_for_operation(
                db, op_id, ws["id"]
            )
            participants = repositories.get_participants_for_workspace(db, ws["id"])
            # Resolve display names for audit columns (creator + voider + payer)
            actor_ids = {
                e["created_by_user_id"] for e in entries if e.get("created_by_user_id")
            } | {
                e["voided_by_user_id"] for e in entries if e.get("voided_by_user_id")
            } | {
                e["paid_by_user_id"] for e in entries if e.get("paid_by_user_id")
            }
            actor_users = repositories.get_users_by_ids(db, list(actor_ids))
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    participant_map = {p["id"]: p for p in participants}
    user_map        = {u["id"]: u for u in actor_users}
    ledger_totals   = compute_ledger_totals(entries)

    return templates.TemplateResponse(
        request,
        "operation_ledger.html",
        {
            "workspace":       ws,
            "operation":       op,
            "current_user":    user,
            "entries":         entries,
            "participant_map": participant_map,
            "participants":    participants,
            "user_map":        user_map,
            "ledger_totals":   ledger_totals,
            "active_tab":      "ledger",
            **access,
        },
    )


_LEDGER_CSV_COLUMNS = [
    "operation_id",
    "participant_id",
    "entry_type",
    "status",
    "amount_silver",
    "note",
    "created_by",
    "created_at",
    "updated_at",
    "paid_at",
    "paid_by",
    "voided_at",
    "voided_by",
]


def _entry_to_csv_row(entry: dict, user_map: dict[str, dict]) -> dict:
    """Map a ledger entry dict to a flat CSV row dict."""
    def _display(uid: str | None) -> str:
        if not uid:
            return ""
        u = user_map.get(uid)
        return u["display_name"] if u else uid[:8]

    return {
        "operation_id":   entry.get("guild_operation_id", ""),
        "participant_id": entry.get("participant_id", ""),
        "entry_type":     entry.get("entry_type", ""),
        "status":         entry.get("status", ""),
        "amount_silver":  entry.get("amount_silver", ""),
        "note":           entry.get("note") or "",
        "created_by":     _display(entry.get("created_by_user_id")),
        "created_at":     entry.get("created_at", ""),
        "updated_at":     entry.get("updated_at", ""),
        "paid_at":        entry.get("paid_at") or "",
        "paid_by":        _display(entry.get("paid_by_user_id")),
        "voided_at":      entry.get("voided_at") or "",
        "voided_by":      _display(entry.get("voided_by_user_id")),
    }


@router.get("/workspaces/{slug}/operations/{op_id}/ledger/export.csv")
def get_ledger_export_csv(request: Request, slug: str, op_id: str):
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
            op = repositories.get_guild_operation(db, op_id, ws["id"])
            if not op:
                raise NotFoundError("Operation not found.")
            if not access["can_mutate"]:
                raise PermissionDenied("Only officers and owners can export the ledger.")
            entries = repositories.list_payout_ledger_entries_for_operation(
                db, op_id, ws["id"]
            )
            actor_ids = {
                e["created_by_user_id"] for e in entries if e.get("created_by_user_id")
            } | {
                e["voided_by_user_id"] for e in entries if e.get("voided_by_user_id")
            } | {
                e["paid_by_user_id"] for e in entries if e.get("paid_by_user_id")
            }
            actor_users = repositories.get_users_by_ids(db, list(actor_ids))
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Not found.")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    user_map = {u["id"]: u for u in actor_users}

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_LEDGER_CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for entry in entries:
        writer.writerow(_entry_to_csv_row(entry, user_map))

    safe_title = op["title"].replace(" ", "_").replace("/", "-")[:40]
    filename = f"ledger_{safe_title}_{op_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/workspaces/{slug}/operations/{op_id}/ledger/create")
async def post_create_ledger_entry(request: Request, slug: str, op_id: str):
    ledger_url = f"/workspaces/{slug}/operations/{op_id}/ledger"
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except (NotFoundError, PermissionDenied):
        raise HTTPException(status_code=403)

    form           = await request.form()
    participant_id = form.get("participant_id", "").strip()
    entry_type     = form.get("entry_type", "").strip()
    amount_str     = form.get("amount_silver", "0").strip()
    note           = form.get("note", "").strip() or None

    try:
        amount_silver = int(amount_str)
    except (ValueError, TypeError):
        return _err_redirect(ledger_url, "Amount must be an integer.")

    try:
        use_cases.create_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_id,
            participant_id=participant_id,
            entry_type=entry_type,
            amount_silver=amount_silver,
            note=note,
            actor_user_id=user["id"],
        )
    except IronkeepError as exc:
        return _err_redirect(ledger_url, str(exc))

    return _ok_redirect(ledger_url, "Ledger entry created.")


@router.post("/workspaces/{slug}/operations/{op_id}/ledger/{entry_id}/void")
def post_void_ledger_entry(request: Request, slug: str, op_id: str, entry_id: str):
    ledger_url = f"/workspaces/{slug}/operations/{op_id}/ledger"
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except (NotFoundError, PermissionDenied):
        raise HTTPException(status_code=403)

    try:
        use_cases.void_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry_id,
            actor_user_id=user["id"],
        )
    except IronkeepError as exc:
        return _err_redirect(ledger_url, str(exc))

    return _ok_redirect(ledger_url, "Entry voided.")


@router.post("/workspaces/{slug}/operations/{op_id}/ledger/{entry_id}/approve")
def post_approve_ledger_entry(request: Request, slug: str, op_id: str, entry_id: str):
    ledger_url = f"/workspaces/{slug}/operations/{op_id}/ledger"
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except (NotFoundError, PermissionDenied):
        raise HTTPException(status_code=403)

    try:
        use_cases.approve_payout_ledger_entry(
            guild_workspace_id=ws["id"],
            entry_id=entry_id,
            actor_user_id=user["id"],
        )
    except IronkeepError as exc:
        return _err_redirect(ledger_url, str(exc))

    return _ok_redirect(ledger_url, "Entry approved.")


@router.post("/workspaces/{slug}/operations/{op_id}/ledger/{entry_id}/mark-paid")
def post_mark_ledger_entry_paid(request: Request, slug: str, op_id: str, entry_id: str):
    ledger_url = f"/workspaces/{slug}/operations/{op_id}/ledger"
    try:
        with database.transaction() as db:
            user, ws, access = authz.resolve_workspace_view(db, request, slug)
    except AuthenticationRequired:
        return _redirect(authz.login_url(request))
    except (NotFoundError, PermissionDenied):
        raise HTTPException(status_code=403)

    try:
        use_cases.mark_payout_ledger_entry_paid(
            guild_workspace_id=ws["id"],
            entry_id=entry_id,
            actor_user_id=user["id"],
        )
    except IronkeepError as exc:
        return _err_redirect(ledger_url, str(exc))

    return _ok_redirect(ledger_url, "Entry marked as paid.")
