import base64
import json
import logging
import re
import secrets
import urllib.parse
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import companion_auth, config, db, discord_api, forever_companion, roster, tickets, warcraft_forever, wow
from . import mock_data as data
from pathlib import Path

BASE_DIR = Path(__file__).parent
VIEW_COOKIE = "ik_view"
SESSION_COOKIE = "ik_session"
RAID_FORM_COOKIE = "ik_raid_form"
_RAID_DRAFT_ERRORS = {"title", "name", "loot", "when", "end", "caps", "over", "many", "channel"}

app = FastAPI(title="Ironkeep", docs_url=None, redoc_url=None)
log = logging.getLogger("ironkeep.web")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def asset(path: str) -> str:
    version = int((BASE_DIR / "static" / path).stat().st_mtime)
    return f"/static/{path}?v={version}"


templates.env.globals["asset"] = asset
db.init()
warcraft_forever.refresh_if_stale()
forever_companion.refresh_if_stale()


def _secure():
    return config.PUBLIC_URL.startswith("https")


def _safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/trial"
    return value


def _session(request: Request):
    if not config.live():
        return None
    return db.get_session(request.cookies.get(SESSION_COOKIE))


def viewer(request: Request):
    if not config.live():
        if request.cookies.get(VIEW_COOKIE) == "recruiter":
            return {**data.RECRUITER, "superadmin": False, "role": "recruiter"}
        return {**data.SUPERADMIN, "superadmin": True, "role": "superadmin"}
    session = _session(request)
    if not session:
        return {"id": "", "name": "Guest", "color": "#8d95a1", "superadmin": False, "role": "guest"}
    superadmin = session["user_id"] == config.SUPERADMIN_ID
    return {
        "id": session["user_id"],
        "name": session["name"],
        "username": session["username"],
        "color": db.PALETTE[int(session["user_id"]) % len(db.PALETTE)],
        "superadmin": superadmin,
        "role": "superadmin" if superadmin else "recruiter",
    }


def _load_member(session, guild):
    """Discord membership for this login. A failed lookup is not stored, so the next page can try again."""
    if session is None:
        return {"member": False, "roles": []}
    cached = db.cached_member(session["user_id"], guild["id"])
    if cached is not None:
        return cached
    token = session.get("access_token")
    if not token:
        return {"member": False, "roles": []}

    def fetch(access_token):
        return discord_api.guild_member(access_token, guild["id"])

    try:
        member = fetch(token)
    except discord_api.DiscordError as error:
        if error.status == 401 and session.get("refresh_token"):
            try:
                refreshed = discord_api.refresh_access_token(session["refresh_token"])
            except discord_api.DiscordError:
                return {"member": False, "roles": []}
            db.update_session_tokens(
                session["token"],
                refreshed["access_token"],
                refreshed.get("refresh_token") or session["refresh_token"],
                refreshed.get("expires_in", 604800),
            )
            session["access_token"] = refreshed["access_token"]
            try:
                member = fetch(session["access_token"])
            except discord_api.DiscordError as retry:
                if retry.status == 404:
                    db.store_member(session["user_id"], guild["id"], False, [])
                    return {"member": False, "roles": []}
                return {"member": False, "roles": []}
        elif error.status == 404:
            db.store_member(session["user_id"], guild["id"], False, [])
            return {"member": False, "roles": []}
        else:
            return {"member": False, "roles": []}
    roles = sorted(str(role) for role in member.get("roles", []))
    db.store_member(session["user_id"], guild["id"], True, roles)
    return {"member": True, "roles": roles}


def _member_roles(session, guild):
    loaded = _load_member(session, guild)
    return set(loaded["roles"]) if loaded["member"] else set()


def _staff(session, guild):
    if session is None:
        return False
    if session["user_id"] == config.SUPERADMIN_ID:
        return True
    return bool(guild.get("added_by_id") and guild["added_by_id"] == session["user_id"])


def _holds(session, guild, role_ids):
    if session is None or not role_ids:
        return False
    return bool(set(role_ids) & _member_roles(session, guild))


def can_access(session, guild):
    """Trials, members and settings. A World of Warcraft server uses the raid-poster roles."""
    if _staff(session, guild):
        return True
    if db.guild_game(guild["settings"]) == "wow":
        return _holds(session, guild, db.wow_settings(guild["settings"])["poster_roles"])
    return _holds(session, guild, guild["settings"].get("recruitment_roles") or [])


def can_view_payout(session, guild):
    """Own payout page. An empty setting keeps this with the recruitment roles."""
    if _staff(session, guild):
        return True
    chosen = db.payout_view_role_ids(guild["settings"])
    if chosen:
        return _holds(session, guild, chosen)
    return _holds(session, guild, guild["settings"].get("recruitment_roles") or [])


def can_book_lootsplit(session, guild):
    """Lootsplit page. An empty role list keeps this with the recruitment roles.

    Named people are extra: they can open the page even without one of those roles.
    """
    if _staff(session, guild):
        return True
    chosen = db.lootsplit_access_role_ids(guild["settings"])
    roles = chosen or (guild["settings"].get("recruitment_roles") or [])
    if _holds(session, guild, roles):
        return True
    people = set(db.lootsplit_access_user_ids(guild["settings"]))
    return bool(session and str(session["user_id"]) in people)


def can_correct_attendance(session, guild):
    """Empty attendance roles keep this with the people who can open Raids."""
    if _staff(session, guild):
        return True
    if db.guild_game(guild["settings"]) != "wow":
        return False
    chosen = db.wow_settings(guild["settings"])["attendance_roles"]
    if chosen:
        return _holds(session, guild, chosen)
    return can_access(session, guild)


def can_view_tickets(session, guild):
    """Settings access can always open the log. Chosen roles can open it too."""
    if can_edit_settings(session, guild):
        return True
    if db.guild_game(guild["settings"]) != "wow":
        return False
    return _holds(session, guild, db.ticket_settings(guild["settings"])["log_roles"])


def can_edit_settings(session, guild):
    """Poster roles can already open Settings. Chosen roles can view and change them as well."""
    if can_access(session, guild):
        return True
    if db.guild_game(guild["settings"]) != "wow":
        return False
    return _holds(session, guild, db.wow_settings(guild["settings"])["settings_roles"])


def can_open_guild(session, guild):
    if can_access(session, guild) or can_edit_settings(session, guild) or can_view_payout(session, guild) or can_book_lootsplit(session, guild):
        return True
    return guild.get("game") == "wow" and _load_member(session, guild)["member"]


def home_path(session, guild):
    slug = guild["slug"]
    game = db.guild_game(guild["settings"])
    if can_access(session, guild):
        if game is None:
            return f"/{slug}/setup"
        if game == "wow":
            return f"/{slug}/raids"
        return f"/{slug}/trial"
    if game == "wow" and _holds(session, guild, db.wow_settings(guild["settings"])["settings_roles"]):
        return f"/{slug}/settings"
    if game == "wow" and _load_member(session, guild)["member"]:
        return f"/{slug}/characters"
    if can_book_lootsplit(session, guild):
        return f"/{slug}/lootsplit"
    if can_view_payout(session, guild):
        return f"/{slug}/payout"
    return f"/{slug}/trial"


def page_access(request, guild):
    person = viewer(request)
    if not config.live():
        label = "Superadmin" if person["superadmin"] else "Recruiter"
        return {"trials": True, "payout": True, "lootsplit": True, "characters": False, "label": label}
    session = _session(request)
    wow_server = db.guild_game(guild["settings"]) == "wow"
    staff_area = can_access(session, guild)
    member = wow_server and _load_member(session, guild)["member"]
    trials = staff_area and not wow_server
    payout = can_view_payout(session, guild) and not wow_server
    lootsplit = can_book_lootsplit(session, guild) and not wow_server
    if person["superadmin"]:
        label = "Superadmin"
    elif wow_server and staff_area:
        label = "Officer"
    elif trials:
        label = "Recruiter"
    elif lootsplit:
        label = "Lootsplit"
    else:
        label = "Member"
    return {
        "trials": trials,
        "payout": payout,
        "lootsplit": lootsplit,
        "raids": staff_area and wow_server,
        "members": can_edit_settings(session, guild) if wow_server else staff_area,
        "settings": can_edit_settings(session, guild) if wow_server else staff_area,
        "tickets": can_view_tickets(session, guild) if wow_server else False,
        "characters": member or (staff_area and wow_server),
        "label": label,
    }


def deny_unless(request, guild, area):
    if not config.live():
        return None
    session = _session(request)
    allowed = {"trials": can_access, "payout": can_view_payout, "lootsplit": can_book_lootsplit, "settings": can_edit_settings}[area]
    if allowed(session, guild):
        return None
    return forbidden(request, "Your roles don't include this page.")


def _away_from(guild, *games):
    """Send a server to its own home when the page belongs to another game."""
    if not config.live():
        return None
    game = guild.get("game")
    if game in games:
        return None
    if game == "wow":
        return RedirectResponse(f"/{guild['slug']}/raids", status_code=303)
    if game is None:
        return RedirectResponse(f"/{guild['slug']}/setup", status_code=303)
    return RedirectResponse(f"/{guild['slug']}/trial", status_code=303)


WOW_ERRORS = {
    "channel": "Choose a channel Ironkeep can send messages in.",
    "roles": "Choose who can post a raid.",
    "title": "Choose a dungeon, raid or event.",
    "name": "Give the event a title.",
    "when": "Choose a date and time.",
    "end": "The end time has to be after the start.",
    "caps": "Set the spots for tank, healer and DPS. At least one spot in total.",
    "over": "Those spots add up to more than the size of this dungeon or raid.",
    "discord": "Saved here. Discord could not post the next raid.",
    "closed": "The raid is closed here. The Discord message could not be updated.",
    "thread": "The raid is closed here. The thread could not be locked.",
    "removed": "The Discord message is still there, so this raid was kept.",
    "pending": "This server is still waiting for approval.",
    "setup": "Finish the setup before posting a raid.",
    "refresh": "Saved here. The Discord message could not be updated.",
    "many": "Eight raids at a time is the limit.",
    "loot": "Choose the loot rule for this raid.",
    "move": "That person cannot take that role.",
    "banner": "Use a JPG or PNG under 8 MB.",
    "voice": "Choose a category Ironkeep can manage channels in.",
    "hub": "Saved. Discord could not create the join channel. Ironkeep needs permission to manage channels in that category.",
    "tickets": "Choose a panel channel, at least one staff role, and one topic before turning tickets on.",
    "panel": "Discord could not update the ticket menu in that channel.",
}


def visible_guilds(request: Request):
    if not config.live():
        return data.GUILDS
    person = viewer(request)
    rows = db.list_guilds(with_trials=True)
    rows = [guild for guild in rows if guild["approval"] != "rejected"]
    if person["superadmin"]:
        return rows
    session = _session(request)
    visible = []
    for guild in rows:
        if can_open_guild(session, guild):
            guild["home"] = home_path(session, guild)
            visible.append(guild)
    return visible


def render(request: Request, template: str, status_code: int = 200, **context):
    context.setdefault("viewer", viewer(request))
    context.setdefault("guilds", visible_guilds(request))
    if config.live():
        context.setdefault("today", date.today().isoformat())
    else:
        context.setdefault("today", data.TODAY.isoformat())
    context.setdefault("albion_updated_at", data.ALBION_UPDATED_AT)
    context.setdefault("live", config.live())
    if context.get("guild"):
        context.setdefault("access", page_access(request, context["guild"]))
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def forbidden(request: Request, message: str):
    return render(request, "forbidden.html", status_code=403, message=message, guild=None, nav=None)


def login_redirect(request: Request):
    target = _safe_next(request.url.path)
    return RedirectResponse(f"/login?next={urllib.parse.quote(target)}", status_code=303)


def recruiter_guild_slugs():
    return ["dutchchaos"]


def guild_or_404(request: Request, slug: str):
    if config.live() and not viewer(request)["id"]:
        return None, login_redirect(request)
    if config.live():
        guild = db.guild_by_slug(slug, with_trials=True)
    else:
        guild = data.guild_by_slug(slug)
    if guild is None:
        return None, render(
            request,
            "forbidden.html",
            status_code=404,
            message="There is no Ironkeep environment at this address.",
            guild=None,
            nav=None,
        )
    person = viewer(request)
    if config.live():
        if not person["superadmin"] and not can_open_guild(_session(request), guild):
            return None, forbidden(request, "You need a role in this Discord server to open this page.")
    elif not person["superadmin"] and slug not in recruiter_guild_slugs():
        return None, forbidden(request, "You need a recruitment role in this Discord server to open this page.")
    return guild, None


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render(request, "landing.html")


@app.get("/login")
def login(request: Request, add: str = "", next: str = "/trial", error: str = ""):
    if error:
        return render(request, "login.html", error=error)
    if add and config.CLIENT_ID:
        return RedirectResponse(config.invite_url(), status_code=303)
    if config.live():
        state = secrets.token_urlsafe(24)
        query = urllib.parse.urlencode(
            {
                "client_id": config.CLIENT_ID,
                "redirect_uri": config.redirect_uri(),
                "response_type": "code",
                "scope": "identify guilds guilds.members.read",
                "state": state,
            }
        )
        response = RedirectResponse(f"https://discord.com/oauth2/authorize?{query}", status_code=303)
        response.set_cookie("ik_oauth", state, max_age=600, httponly=True, samesite="lax", secure=_secure())
        response.set_cookie("ik_next", _safe_next(next), max_age=600, httponly=True, samesite="lax", secure=_secure())
        return response
    return render(request, "login.html")


@app.get("/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code or state != request.cookies.get("ik_oauth"):
        return render(request, "login.html", error="Discord login was cancelled or expired. Try again.")
    try:
        tokens = discord_api.exchange_code(code)
        user = discord_api.identify(tokens["access_token"])
    except discord_api.DiscordError:
        return render(
            request,
            "login.html",
            error="Discord didn't accept the login. The redirect URL in the developer portal must be exactly https://ironkeep.gg/auth/callback.",
        )
    token = db.create_session(
        user["id"],
        user.get("global_name") or user["username"],
        user["username"],
        tokens["access_token"],
        tokens.get("refresh_token", ""),
        tokens.get("expires_in", 604800),
    )
    response = RedirectResponse(_safe_next(request.cookies.get("ik_next")), status_code=303)
    response.set_cookie(SESSION_COOKIE, token, max_age=30 * 86400, httponly=True, samesite="lax", secure=_secure())
    response.delete_cookie("ik_oauth")
    response.delete_cookie("ik_next")
    return response


@app.get("/logout")
def logout(request: Request):
    db.delete_session(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(VIEW_COOKIE)
    return response


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html")


@app.get("/prototype/view/{role}")
def switch_view(role: str, request: Request, next: str = "/"):
    if config.live():
        return RedirectResponse("/", status_code=303)
    target = next if next.startswith("/") else "/"
    if role == "recruiter" and target.startswith("/admin"):
        target = "/dutchchaos/trial"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(VIEW_COOKIE, "recruiter" if role == "recruiter" else "superadmin", samesite="lax")
    return response


@app.get("/trial")
def trial_redirect(request: Request):
    if config.live() and not viewer(request)["id"]:
        return login_redirect(request)
    rows = visible_guilds(request)
    if len(rows) == 1:
        return RedirectResponse(rows[0].get("home") or f"/{rows[0]['slug']}/trial", status_code=303)
    if viewer(request)["superadmin"]:
        return RedirectResponse("/admin", status_code=303)
    if len(rows) > 1:
        return render(request, "servers.html", guild=None, nav=None)
    return render(request, "forbidden.html", status_code=404, message="Ironkeep isn't in any of your servers yet.", guild=None, nav=None)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if config.live() and not viewer(request)["id"]:
        return login_redirect(request)
    if not viewer(request)["superadmin"]:
        return forbidden(request, "Only the Ironkeep superadmin can open this page.")
    if config.live():
        rows = [{**g, **data.guild_summary(g, date.today())} for g in db.list_guilds(with_trials=True)]
        error_rows = db.list_errors()
    else:
        rows = [{**g, **data.guild_summary(g)} for g in data.GUILDS]
        error_rows = data.ERRORS
    rows = [row for row in rows if row["approval"] != "rejected"]
    totals = {
        "guilds": len(rows),
        "open": sum(r["open"] for r in rows),
        "attention": sum(r["attention"] for r in rows),
        "errors": sum(1 for e in error_rows if not e["resolved"]),
        "pending": sum(1 for r in rows if r["approval"] == "pending"),
    }
    return render(request, "admin.html", rows=rows, totals=totals, guild=None, nav="admin")


@app.post("/api/admin/guilds/{slug}/decision")
async def guild_decision(slug: str, request: Request):
    if not config.live() or not viewer(request)["superadmin"]:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    guild = db.guild_by_slug(slug)
    if guild is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    decision = body.get("decision")
    if decision == "approve":
        db.set_approval(slug, "approved", needs_scan=True)
        if guild.get("added_by_id"):
            try:
                discord_api.send_dm(
                    guild["added_by_id"],
                    f"Ironkeep is approved for {guild['name']}. Open {config.PUBLIC_URL}/{guild['slug']}/setup to finish, if you haven't yet.",
                )
            except discord_api.DiscordError:
                db.set_last_error(guild["id"], "Could not message the person who added the bot")
    elif decision == "reject":
        try:
            discord_api.leave_guild(guild["id"])
        except discord_api.DiscordError as error:
            if error.status != 404:
                db.set_last_error(guild["id"], "Could not leave the Discord server")
                return JSONResponse({"error": "could not leave"}, status_code=502)
        reason = (body.get("reason") or "").strip()
        if guild.get("added_by_id"):
            text = f"Ironkeep was not approved for {guild['name']} and has left the server."
            if reason:
                text += f"\n\n{reason}"
            try:
                discord_api.send_dm(guild["added_by_id"], text[:2000])
            except discord_api.DiscordError:
                pass
        db.delete_guild(slug)
    else:
        return JSONResponse({"error": "bad decision"}, status_code=400)
    return {"ok": True}


@app.get("/admin/errors", response_class=HTMLResponse)
def admin_errors(request: Request):
    if config.live() and not viewer(request)["id"]:
        return login_redirect(request)
    if not viewer(request)["superadmin"]:
        return forbidden(request, "Only the Ironkeep superadmin can open this page.")
    if config.live():
        errors = db.list_errors()
        names = {g["slug"]: g for g in db.list_guilds()}
        errors = [e for e in errors if e["guild"] in names]
    else:
        errors = data.ERRORS
        names = {g["slug"]: g for g in data.GUILDS}
    return render(request, "admin_errors.html", errors=errors, names=names, guild=None, nav="errors")


@app.post("/api/admin/errors/{error_id}/status")
async def set_admin_error_status(error_id: int, request: Request):
    if not config.live() or not viewer(request)["superadmin"]:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await request.json()
    status = (body or {}).get("status")
    if not db.set_error_status(error_id, status):
        missing = status not in db.ERROR_STATUSES
        return JSONResponse({"error": "bad status" if missing else "not found"}, status_code=400 if missing else 404)
    return {"ok": True, "status": status}


@app.get("/admin/data", response_class=HTMLResponse)
def admin_data(request: Request):
    if config.live() and not viewer(request)["id"]:
        return login_redirect(request)
    if not viewer(request)["superadmin"]:
        return forbidden(request, "Only the Ironkeep superadmin can open this page.")
    records = []
    source = db.list_guilds(with_trials=True) if config.live() else data.GUILDS
    for guild in source:
        for trial in guild["trials"]:
            records.append({"guild": guild["name"], "slug": guild["slug"], **trial})
    return render(request, "admin_data.html", records=records, guild=None, nav="data")


@app.get("/{slug}")
def guild_home(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    session = _session(request) if config.live() else None
    return RedirectResponse(home_path(session, guild) if config.live() else f"/{slug}/trial", status_code=303)


@app.get("/{slug}/trial", response_class=HTMLResponse)
def trials(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "albion")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    if config.live():
        pure = db.active_trial_role_ids(guild["settings"])
        on_trial = {
            person["user_id"]
            for person in db.list_members(guild["id"])
            if pure & set(person["role_ids"])
        }
        if on_trial:
            guild["trials"] = [trial for trial in guild["trials"] if trial["user_id"] in on_trial]
    today = db.guild_today(guild["settings"]).isoformat() if config.live() else None
    extra = {"today": today} if today else {}
    if config.live():
        stamps = [
            (trial.get("albion") or {}).get("updated_at")
            for trial in guild["trials"]
            if (trial.get("albion") or {}).get("updated_at")
        ]
        extra["albion_updated_at"] = max(stamps) if stamps else ""
    return render(request, "trials.html", guild=guild, nav="trials", **extra)


def _shown_role(role, content_ids):
    """Roles worth listing on Members: skip @everyone, bots, and content roles."""
    if not role or role.get("everyone") or role.get("managed") or role.get("bot"):
        return False
    return str(role.get("id")) not in content_ids


def prepare_members(guild, people):
    """Status, role labels, and filter chips for the members page."""
    settings = guild["settings"]
    trial_ids = {str(role_id) for role_id in db.active_trial_role_ids(settings)}
    member_ids = {str(role_id) for role_id in db.member_role_ids(settings)}
    content_ids = {str(role_id) for role_id in (settings.get("content_roles") or []) if role_id}
    roles = {str(role["id"]): role for role in guild["roles"]}
    counts = {}
    prepared = []
    for person in people:
        person = dict(person)
        held = {str(role_id) for role_id in person.get("role_ids") or []}
        is_member = bool(held & member_ids)
        if held & trial_ids:
            person["status"], person["tone"] = "Trial", "orange"
        elif is_member:
            person["status"], person["tone"] = "Member", "green"
        else:
            person["status"], person["tone"] = "Other", "grey"
        shown = [roles[role_id] for role_id in held if _shown_role(roles.get(role_id), content_ids)]
        shown.sort(key=lambda role: role.get("position") or 0, reverse=True)
        person["labels"] = [role["name"] for role in shown]
        person["filter_roles"] = sorted(held)
        for role_id in held:
            counts[role_id] = counts.get(role_id, 0) + 1
        person["color"] = db.PALETTE[int(person["user_id"]) % len(db.PALETTE)]
        prepared.append(person)
    role_filters = []
    seen = set()
    for role_id in db.member_filter_ids(settings):
        if role_id in seen:
            continue
        seen.add(role_id)
        role = roles.get(role_id)
        if not role or role.get("everyone") or role.get("managed") or role.get("bot"):
            continue
        role_filters.append({"id": role_id, "name": role["name"], "count": counts.get(role_id, 0)})
    return {
        "people": prepared,
        "role_filters": role_filters,
    }


@app.get("/{slug}/members", response_class=HTMLResponse)
def members(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "albion", "wow")
    if moved:
        return moved
    if guild.get("game") == "wow":
        if config.live() and not can_edit_settings(_session(request), guild):
            return forbidden(request, "Your roles don't include this page.")
    else:
        blocked = deny_unless(request, guild, "trials")
        if blocked:
            return blocked
    if guild.get("game") == "wow":
        people = []
        if config.live():
            signups, marks = db.member_activity(guild["id"])
            people = wow.member_rows(db.list_members(guild["id"]), db.wow_characters(guild["id"]))
            charts = wow.attendance_charts(
                [person["user_id"] for person in people],
                db.closed_raids(guild["id"]),
                signups,
                marks,
                guild.get("settings"),
            )
            for person in people:
                chart = charts[person["user_id"]]
                person["chart"] = chart
                there = chart["present"] + chart["late"]
                person["attendance"] = f"{there}/{chart['total']}" if chart["total"] else "—"
                person["summary"] = f"{there} of {chart['total']} raids" if chart["total"] else "No closed raids yet"
        return render(
            request,
            "wow_members.html",
            guild=guild,
            nav="members",
            people=people,
            role_counts=wow.member_filter_counts(people),
            removed=request.query_params.get("removed") == "1",
        )
    source = db.list_members(guild["id"]) if config.live() else data.DEMO_MEMBERS.get(guild["slug"], [])
    prepared = prepare_members(guild, source)
    return render(request, "members.html", guild=guild, nav="members", **prepared)


@app.get("/{slug}/roster", response_class=HTMLResponse)
def guild_roster(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    if db.guild_game(guild.get("settings")) != "wow":
        return render(
            request,
            "forbidden.html",
            status_code=404,
            message="This guild has no roster page.",
            guild=None,
            nav=None,
        )
    if config.live() and not can_edit_settings(_session(request), guild):
        return forbidden(request, "Your roles don't include this page.")
    return render(
        request,
        "roster.html",
        guild=guild,
        nav="roster",
        roster=roster.current(guild["id"]),
    )


CHARACTER_ERRORS = {
    "name": "Use 2 to 12 letters for the first name and the last name.",
    "choice": "Choose a class and specialization.",
    "duplicate": "You already have a character with that name.",
    "limit": "You can save up to 9 characters.",
    "missing": "That character is no longer on your list.",
    "wish_limit": "You can mark up to 10 items.",
}


def _can_characters(request, guild):
    if guild.get("game") != "wow":
        return False
    session = _session(request)
    if can_access(session, guild):
        return True
    return _load_member(session, guild)["member"]


def _character_fields(form):
    first = (form.get("first_name") or [""])[0]
    last = (form.get("last_name") or [""])[0]
    name = wow.clean_character_name(f"{first} {last}")
    if name is None:
        return None, "name"
    class_id, separator, spec_id = (form.get("choice") or [""])[0].partition(":")
    if not separator or wow.find_spec(class_id, spec_id)[1] is None:
        return None, "choice"
    return {
        "name": name,
        "class_id": class_id,
        "spec_id": spec_id,
        "role": wow.role_for(class_id, spec_id) or "",
    }, None


def _decorate_characters(rows):
    people = []
    for person in rows:
        class_name, spec_name = wow.choice_names(person["class_id"], person["spec_id"])
        person["class_name"] = class_name
        person["class_color"] = wow.class_color(person["class_id"])
        person["spec_name"] = spec_name
        people.append(person)
    return people


@app.get("/{slug}/characters", response_class=HTMLResponse)
def characters_page(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    if config.live() and not _can_characters(request, guild):
        return forbidden(request, "Your roles don't include this page.")
    session = _session(request)
    user_id = session["user_id"] if session else ""
    people = _decorate_characters(db.wow_characters_for(guild["id"], user_id)) if config.live() else []
    counts = db.wish_counts([person["id"] for person in people]) if people else {}
    for person in people:
        person["wish_count"] = counts.get(person["id"], 0)
    editing = None
    edit_id = request.query_params.get("edit") or ""
    if edit_id.isdigit():
        editing = next((person for person in people if str(person["id"]) == edit_id), None)
        if editing:
            editing["first_name"], editing["last_name"] = wow.character_name_parts(editing["name"])
            editing["wishes"] = [
                f"{row['instance_id']}|{row['item_key']}" for row in db.character_wishes(editing["id"])
            ]
    code = request.query_params.get("error") or ""
    return render(
        request,
        "characters.html",
        guild=guild,
        nav="characters",
        people=people,
        classes=wow.class_choices(),
        editing=editing,
        loot_groups=wow.loot_for_class(editing["class_id"]) if editing else [],
        loot_source=wow.instance_source(),
        error=CHARACTER_ERRORS.get(code, ""),
        saved=request.query_params.get("saved") == "1",
    )


@app.post("/{slug}/characters")
async def create_character_page(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    if not _can_characters(request, guild):
        return forbidden(request, "Your roles don't include this page.")
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    fields, code = _character_fields(form)
    target = f"/{slug}/characters"
    if code:
        return RedirectResponse(f"{target}?error={code}", status_code=303)
    session = _session(request)
    result = db.save_wow_character(guild["id"], session["user_id"], **fields)
    if isinstance(result, str):
        return RedirectResponse(f"{target}?error={result}", status_code=303)
    return RedirectResponse(f"{target}?saved=1", status_code=303)


@app.post("/{slug}/characters/{character_id}")
async def update_character_page(slug: str, character_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    if not _can_characters(request, guild):
        return forbidden(request, "Your roles don't include this page.")
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    fields, code = _character_fields(form)
    target = f"/{slug}/characters"
    if code:
        return RedirectResponse(f"{target}?edit={character_id}&error={code}", status_code=303)
    session = _session(request)
    result = db.save_wow_character(guild["id"], session["user_id"], character_id=character_id, **fields)
    if isinstance(result, str):
        return RedirectResponse(f"{target}?edit={character_id}&error={result}", status_code=303)
    return RedirectResponse(f"{target}?saved=1", status_code=303)


def _wish_choices(form, class_id):
    known = {
        (group["id"], item["key"])
        for group in wow.loot_catalog()
        for item in group["items"]
        if wow.usable_by(class_id, item)
    }
    chosen = []
    seen = set()
    for raw in form.get("wish") or []:
        instance_id, separator, item_key = str(raw).partition("|")
        pair = (instance_id, item_key)
        if not separator or pair not in known or pair in seen:
            continue
        seen.add(pair)
        chosen.append(pair)
    return chosen


@app.post("/{slug}/characters/{character_id}/wishes")
async def save_wishes_page(slug: str, character_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    if not _can_characters(request, guild):
        return forbidden(request, "Your roles don't include this page.")
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    target = f"/{slug}/characters?edit={character_id}"
    session = _session(request)
    owned = db.wow_character_owned(guild["id"], session["user_id"], character_id)
    class_id = owned["class_id"] if owned else ""
    result = db.save_character_wishes(guild["id"], session["user_id"], character_id, _wish_choices(form, class_id))
    if result:
        return RedirectResponse(f"{target}&error={result}", status_code=303)
    return RedirectResponse(f"{target}&saved=1", status_code=303)


@app.post("/{slug}/characters/{character_id}/delete")
def delete_character_page(slug: str, character_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    session = _session(request)
    if request.query_params.get("next") == "members":
        if not can_edit_settings(session, guild):
            return forbidden(request, "Your roles don't include this page.")
        db.delete_wow_character(guild["id"], session["user_id"], character_id, any_owner=True)
        return RedirectResponse(f"/{slug}/members?removed=1", status_code=303)
    if not _can_characters(request, guild):
        return forbidden(request, "Your roles don't include this page.")
    db.delete_wow_character(guild["id"], session["user_id"], character_id)
    return RedirectResponse(f"/{slug}/characters?saved=1", status_code=303)


def payout_page(request: Request):
    """Sample figures stay on the local prototype. The live site shows the layout only."""
    if config.live() or request.query_params.get("preview") == "empty":
        return {
            "member": "",
            "threshold": None,
            "pct": {"niet": 70, "repaired": 80},
            "fine_pct": 10,
            "mutations": [],
            "roster": [],
            "splits": [],
            "sample": False,
        }
    return {**data.PAYOUT_MOCK, "sample": True}


def directory_members(guild):
    """People on the member list, ready for a settings picker."""
    if config.live():
        people = db.list_members(guild["id"])
    else:
        people = data.DEMO_MEMBERS.get(guild["slug"], [])
    rows = []
    for person in people:
        user_id = str(person.get("user_id") or "").strip()
        name = str(person.get("name") or "").strip()
        if not user_id or not name:
            continue
        try:
            color = db.PALETTE[int(user_id) % len(db.PALETTE)]
        except ValueError:
            color = "#8d95a1"
        rows.append(
            {
                "id": user_id,
                "name": name,
                "username": str(person.get("username") or ""),
                "color": color,
            }
        )
    counts = {}
    for row in rows:
        key = row["name"].casefold()
        counts[key] = counts.get(key, 0) + 1
    for row in rows:
        if counts[row["name"].casefold()] > 1 and row["username"]:
            row["label"] = row["name"] + " (@" + row["username"] + ")"
        else:
            row["label"] = row["name"]
    rows.sort(key=lambda item: item["label"].casefold())
    return rows


def lootsplit_names(guild):
    """Display names from the member list, limited to the roles chosen in settings."""
    chosen = db.lootsplit_role_ids(guild["settings"])
    if not chosen:
        return [], "Choose the roles for this list under Settings → Roles → Lootsplit names."
    wanted = set(chosen)
    if config.live():
        people = db.list_members(guild["id"])
    else:
        people = data.DEMO_MEMBERS.get(guild["slug"], [])
    rows = []
    for person in people:
        held = {str(role_id) for role_id in person.get("role_ids") or []}
        if not held & wanted:
            continue
        label = str(person.get("name") or "").strip()
        if not label:
            continue
        rows.append({"id": str(person.get("user_id") or label), "name": label, "username": str(person.get("username") or "")})
    counts = {}
    for row in rows:
        key = row["name"].casefold()
        counts[key] = counts.get(key, 0) + 1
    named = []
    for row in rows:
        label = row["name"]
        if counts[label.casefold()] > 1 and row["username"]:
            label = label + " (@" + row["username"] + ")"
        named.append({"id": row["id"], "name": label})
    named.sort(key=lambda item: item["name"].casefold())
    if not named:
        return [], "Nobody with those roles is on the member list yet."
    return named, ""


@app.get("/{slug}/payout", response_class=HTMLResponse)
def payout_mock(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "albion")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "payout")
    if blocked:
        return blocked
    return render(request, "payout.html", guild=guild, nav="payout", payout=payout_page(request))


@app.get("/{slug}/lootsplit", response_class=HTMLResponse)
def lootsplit_mock(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "albion")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "lootsplit")
    if blocked:
        return blocked
    payout = payout_page(request)
    if not payout["sample"]:
        names, hint = lootsplit_names(guild)
        payout["roster"] = names
        payout["rosterHint"] = hint
    return render(request, "lootsplit.html", guild=guild, nav="lootsplit", payout=payout)


@app.put("/api/{slug}/trials/{trial_id}")
async def save_trial(slug: str, trial_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    trial = db.get_trial(trial_id)
    if trial is None or not any(item["id"] == trial_id for item in guild["trials"]):
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad body"}, status_code=400)
    return db.save_trial(trial_id, body)


@app.post("/api/{slug}/trials/{trial_id}/verdict")
async def give_verdict(slug: str, trial_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    trial = db.get_trial(trial_id)
    if trial is None or not any(item["id"] == trial_id for item in guild["trials"]):
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    kind = body.get("kind")
    if kind not in ("accepted", "rejected"):
        return JSONResponse({"error": "bad kind"}, status_code=400)
    settings = guild["settings"]
    plan = settings["accept"] if kind == "accepted" else settings["reject"]
    add = plan.get("add", []) if kind == "accepted" else []
    remove = plan.get("remove", [])
    names = {role["id"]: role["name"] for role in guild["roles"]}
    action_error = None
    try:
        for role_id in add:
            discord_api.add_role(guild["id"], trial["user_id"], role_id)
        for role_id in remove:
            discord_api.remove_role(guild["id"], trial["user_id"], role_id)
    except discord_api.DiscordError:
        action_error = "Missing permission: move the Ironkeep role above the roles it should change."
    role_note = ""
    message_note = ""
    if action_error is None:
        changes = [f"+ {names.get(role_id, role_id)}" for role_id in add] + [f"− {names.get(role_id, role_id)}" for role_id in remove]
        if changes:
            role_note = "Roles changed: " + ", ".join(changes)
        message = (settings.get("messages") or {}).get(kind) or {}
        channel_id = message.get("channel")
        if message.get("enabled") and channel_id:
            channel_name = next((c["name"] for c in guild["channels"] if c["id"] == channel_id), "channel")
            from datetime import timedelta

            length = int(settings.get("trial_days") or 14) + int(trial.get("extra_days") or 0)
            end_value = ""
            if trial.get("start"):
                end_value = db.human_date(date.fromisoformat(trial["start"]) + timedelta(days=length))
            values = {
                "member": f"<@{trial['user_id']}>",
                "guild": guild["name"],
                "days": length,
                "day": length,
                "start_date": db.human_date(trial.get("start")),
                "end_date": end_value,
            }
            try:
                discord_api.send_message(channel_id, discord_api.fill(message.get("text"), values)[:2000])
                message_note = f"Message posted in #{channel_name}"
            except discord_api.DiscordError:
                db.set_last_error(guild["id"], f"Could not post the {kind} message")
    updated = db.record_verdict(
        trial_id,
        kind=kind,
        by=viewer(request)["name"],
        reason=(body.get("reason") or "").strip(),
        role_note=role_note,
        message_note=message_note,
        action_error=action_error,
        settings=settings,
    )
    return JSONResponse(updated, status_code=502 if action_error else 200)


@app.post("/api/{slug}/sync")
def request_member_sync(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    if guild["approval"] != "approved":
        return JSONResponse({"error": "This guild is not approved yet."}, status_code=400)
    if not db.trial_role_ids(guild["settings"]):
        return JSONResponse({"error": "Choose a trial role first."}, status_code=400)
    db.request_scan(slug)
    return {"ok": True}


@app.post("/api/{slug}/settings")
async def save_settings(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad body"}, status_code=400)
    if db.guild_game(guild["settings"]) == "wow":
        return JSONResponse({"error": "This server uses World of Warcraft."}, status_code=400)
    new_slug = (body.get("slug") or "").strip().lower()
    if new_slug and new_slug != slug:
        if not db.valid_slug(new_slug) or db.slug_taken(new_slug, slug):
            return JSONResponse({"error": "That address is not available."}, status_code=400)
    else:
        new_slug = None
    saved = dict(body)
    saved.pop("slug", None)
    saved["trial_roles"] = db.trial_role_ids(saved)
    saved.pop("trial_role", None)
    saved["member_filters"] = db.member_filter_ids(saved)
    saved["lootsplit_roles"] = db.lootsplit_role_ids(saved)
    saved["payout_view_roles"] = db.payout_view_role_ids(saved)
    saved["lootsplit_access_roles"] = db.lootsplit_access_role_ids(saved)
    saved["lootsplit_access_users"] = db.lootsplit_access_user_ids(saved)
    if "companion_roles" not in body:
        saved["companion_roles"] = db.companion_role_ids(guild.get("settings"))
    else:
        chosen_companion = body.get("companion_roles")
        if chosen_companion is None:
            chosen_companion = []
        if not isinstance(chosen_companion, list) or any(not isinstance(item, str) or not item.strip() for item in chosen_companion):
            return JSONResponse({"error": "bad companion roles"}, status_code=400)
        saved["companion_roles"] = [item.strip() for item in chosen_companion]
    saved["game"] = "albion"
    db.save_settings(slug, saved, new_slug)
    target = new_slug or slug
    if db.setup_complete(saved):
        db.request_scan(target)
    return {"ok": True, "slug": target}


def _with_current_roles(guild):
    """Read the server's roles now, so a role added or renamed in Discord shows up on the next open."""
    if not config.live() or not guild:
        return guild
    try:
        payload = discord_api.list_roles(guild["id"])
    except discord_api.DiscordError:
        return guild
    roles = discord_api.role_records(payload, guild["id"])
    if not roles:
        return guild
    db.replace_roles(guild["id"], roles)
    guild["roles"] = roles
    return guild


@app.get("/{slug}/settings", response_class=HTMLResponse)
def settings(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    guild = _with_current_roles(guild)
    if config.live() and guild.get("game") is None:
        return RedirectResponse(f"/{slug}/setup", status_code=303)
    blocked = deny_unless(request, guild, "settings")
    if blocked:
        return blocked
    if config.live() and guild.get("game") == "wow":
        return _wow_setup_page(request, guild, setup_mode=False)
    return render(request, "settings.html", guild=guild, nav="settings", setup_mode=False, members=directory_members(guild))


@app.post("/{slug}/settings")
async def save_wow_settings_page(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "settings")
    if blocked:
        return blocked
    if guild.get("game") != "wow":
        return RedirectResponse(f"/{slug}/settings", status_code=303)
    return await _save_wow_form(request, slug, _with_current_roles(guild), setup_mode=False)


def _instance_groups(guild):
    groups = []
    for group in wow.instance_groups():
        choices = []
        for item in group["choices"]:
            src, custom = wow.banner_preview(guild, item["id"])
            choices.append({**item, "src": src, "custom": custom})
        groups.append({"label": group["label"], "choices": choices})
    return groups


async def _form_parts(request):
    """Read one uploaded file without python-multipart. Other fields stay text."""
    content_type = request.headers.get("content-type") or ""
    found = re.search(r"boundary=([^;]+)", content_type, re.IGNORECASE)
    if "multipart/form-data" not in content_type.lower() or found is None:
        return {}, b""
    boundary = found.group(1).strip().strip('"')
    body = await request.body()
    fields = {}
    upload = b""
    for part in body.split(b"--" + boundary.encode("utf-8", "replace")):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_blob, separator, data = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        header = header_blob.decode("utf-8", "replace")
        name = re.search(r'name="([^"]+)"', header)
        if name is None:
            continue
        filename = re.search(r'filename="([^"]*)"', header)
        if filename is not None and filename.group(1):
            if name.group(1) == "banner":
                upload = data
            continue
        fields.setdefault(name.group(1), []).append(data.decode("utf-8", "replace"))
    return fields, upload


def _repaint_banners(guild, instance_id):
    fresh = db.guild_by_slug(guild["slug"]) or guild
    failed = False
    for raid in db.raids_for_guild(fresh["id"]):
        if raid.get("instance_id") != instance_id or not raid.get("message_id"):
            continue
        try:
            wow.publish(fresh, raid)
        except discord_api.DiscordError:
            failed = True
    return failed


@app.get("/{slug}/banners/{instance_id}")
def banner_image(slug: str, instance_id: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "settings")
    if blocked:
        return blocked
    if guild.get("game") != "wow" or wow.instance_by_id(instance_id) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = wow.custom_banner_path(guild["id"], instance_id)
    if path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@app.post("/{slug}/settings/banners")
async def save_banner(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "settings")
    if blocked:
        return blocked
    if guild.get("game") != "wow":
        return RedirectResponse(f"/{slug}/settings", status_code=303)
    fields, upload = await _form_parts(request)
    instance_id = (fields.get("instance") or [""])[0]
    action = (fields.get("action") or [""])[0]
    target = f"/{slug}/settings?saved=1#posts"
    if wow.instance_by_id(instance_id) is None or action not in ("upload", "default", "hide", "show"):
        return RedirectResponse(f"/{slug}/settings?error=banner#posts", status_code=303)
    if action == "upload":
        try:
            wow.save_custom_banner(guild["id"], instance_id, upload)
        except ValueError:
            return RedirectResponse(f"/{slug}/settings?error=banner#posts", status_code=303)
        db.set_banner_hidden(slug, instance_id, False)
    elif action == "default":
        wow.remove_custom_banner(guild["id"], instance_id)
        db.set_banner_hidden(slug, instance_id, False)
    else:
        db.set_banner_hidden(slug, instance_id, action == "hide")
    if _repaint_banners(guild, instance_id):
        return RedirectResponse(f"/{slug}/settings?error=refresh#posts", status_code=303)
    return RedirectResponse(target, status_code=303)


@app.get("/{slug}/setup", response_class=HTMLResponse)
def setup(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    guild = _with_current_roles(guild)
    if config.live() and guild.get("game") is None:
        return render(request, "game_choice.html", guild=guild, nav="settings", games=wow.GAMES)
    if config.live() and guild.get("game") == "wow":
        return _wow_setup_page(request, guild, setup_mode=True)
    return render(request, "settings.html", guild=guild, nav="settings", setup_mode=True, members=directory_members(guild))


@app.post("/{slug}/setup")
async def setup_choice(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    if guild.get("game") is None and "game" in form:
        choice = (form.get("game") or [""])[0]
        if choice in ("albion", "wow"):
            db.set_game(slug, choice)
        return RedirectResponse(f"/{slug}/setup", status_code=303)
    if guild.get("game") == "wow":
        return await _save_wow_form(request, slug, _with_current_roles(guild), setup_mode=True, form=form)
    return RedirectResponse(f"/{slug}/setup", status_code=303)


def _wow_roles(guild):
    roles = [role for role in guild["roles"] if not role.get("everyone") and not role.get("managed")]
    roles.sort(key=lambda role: role.get("position") or 0, reverse=True)
    return roles


def _role_catalog(guild):
    """Same role records the Albion picker uses, for every game's settings page."""
    catalog = []
    for role in guild.get("roles") or []:
        catalog.append(
            {
                "id": str(role.get("id") or ""),
                "name": role.get("name") or "Role",
                "color": role.get("color") or "#99aab5",
                "position": int(role.get("position") or 0),
                "everyone": bool(role.get("everyone")),
                "managed": bool(role.get("managed")),
                "bot": bool(role.get("bot")),
            }
        )
    return catalog


def _voice_categories(guild):
    return [
        {"id": channel["id"], "name": channel["name"]}
        for channel in guild["channels"]
        if channel.get("kind") == "category" and channel.get("bot_can_manage")
    ]


def _wow_channel_groups(guild):
    groups = []
    buckets = {}
    for channel in guild["channels"]:
        if not channel.get("bot_can_send"):
            continue
        category = channel.get("category") or "Channels"
        if category not in buckets:
            buckets[category] = []
            groups.append({"name": category, "channels": buckets[category]})
        buckets[category].append(channel)
    return groups


def _wow_setup_page(request, guild, *, setup_mode):
        code = request.query_params.get("error") or ""
        return render(
        request,
        "wow_setup.html",
        companion_roles=db.companion_role_ids(guild.get("settings")),
        guild=guild,
        nav="settings",
        setup_mode=setup_mode,
        roles=_wow_roles(guild),
        role_catalog=_role_catalog(guild),
        channel_groups=_wow_channel_groups(guild),
        categories=_voice_categories(guild),
        timezones=wow.TIMEZONES,
        instances=_instance_groups(guild),
        mention_catalog={
            "chosen": db.wow_settings(guild["settings"])["mentions"],
            "roles": {role["id"]: role["name"] for role in _wow_roles(guild)},
            "instances": {
                item["id"]: item["name"] for group in wow.instance_groups() for item in group["choices"]
            },
        },
        wow_config=db.wow_settings(guild["settings"]),
        ticket_config=db.ticket_settings(guild["settings"]),
        error=WOW_ERRORS.get(code, ""),
        saved=request.query_params.get("saved") == "1",
    )


async def _save_wow_form(request, slug, guild, *, setup_mode, form=None):
    if form is None:
        form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    channel_mode = (form.get("channel_mode") or ["one"])[0]
    if channel_mode not in ("one", "split"):
        channel_mode = "one"
    channel = (form.get("raid_channel") or [""])[0]
    dungeon_channel = (form.get("dungeon_channel") or [""])[0]
    chosen = [role_id for role_id in (form.get("poster_roles") or []) if role_id]
    timezone = (form.get("timezone") or [""])[0]
    allowed_channels = {item["id"] for group in _wow_channel_groups(guild) for item in group["channels"]}
    allowed_roles = {role["id"] for role in _wow_roles(guild)}
    chosen = [role_id for role_id in chosen if role_id in allowed_roles]
    if timezone not in wow.TIMEZONES:
        timezone = (guild["settings"] or {}).get("timezone") or "Europe/Amsterdam"
    target = f"/{slug}/setup" if setup_mode else f"/{slug}/settings"
    if channel not in allowed_channels:
        return RedirectResponse(f"{target}?error=channel", status_code=303)
    if channel_mode == "split" and dungeon_channel not in allowed_channels:
        return RedirectResponse(f"{target}?error=channel", status_code=303)
    if not chosen:
        return RedirectResponse(f"{target}?error=roles", status_code=303)
    current = db.wow_settings(guild["settings"])
    reminder_2 = None
    if setup_mode:
        mentions = current["mentions"]
        signup_roles = current["signup_roles"]
        attendance_roles = None
        settings_roles = None
        reminder = current["reminder"]
        close_at_start = current["close_at_start"]
        posted_ahead = None
        question_thread = None
    else:
        mentions = _mention_choices(form, allowed_roles)
        signup_roles = [role_id for role_id in (form.get("signup_roles") or []) if role_id in allowed_roles]
        attendance_roles = [role_id for role_id in (form.get("attendance_roles") or []) if role_id in allowed_roles]
        settings_roles = [role_id for role_id in (form.get("settings_roles") or []) if role_id in allowed_roles]
        reminder = (form.get("reminder") or ["off"])[0]
        reminder_2 = (form.get("reminder_2") or ["off"])[0]
        close_at_start = (form.get("close_at_start") or [""])[0] == "1"
        posted_ahead = 2 if (form.get("posted_ahead") or ["1"])[0] == "2" else 1
        question_thread = (form.get("question_thread") or [""])[0] == "1"
    if setup_mode:
        voice_category = None
        temp_voice = None
        temp_voice_category = None
        temp_voice_limit = None
        temp_voice_hub = None
        temp_voice_prefix = None
        temp_voice_roles = None
        temp_voice_empty = None
        temp_voice_max = None
        event_channel = None
        log_channel = None
        tickets_payload = None
    else:
        voice_category = (form.get("voice_category") or [""])[0]
        allowed_categories = {item["id"] for item in _voice_categories(guild)}
        if voice_category and voice_category not in allowed_categories and voice_category != current["voice_category"]:
            voice_category = None
        temp_voice = (form.get("temp_voice") or [""])[0] == "1"
        temp_voice_category = (form.get("temp_voice_category") or [""])[0]
        temp_voice_limit = (form.get("temp_voice_limit") or ["0"])[0]
        temp_voice_hub = (form.get("temp_voice_hub") or [""])[0]
        temp_voice_prefix = (form.get("temp_voice_prefix") or [""])[0]
        temp_voice_roles = [role_id for role_id in (form.get("temp_voice_roles") or []) if role_id in allowed_roles]
        temp_voice_empty = (form.get("temp_voice_empty") or ["2"])[0]
        temp_voice_max = (form.get("temp_voice_max") or ["10"])[0]
        if temp_voice and temp_voice_category not in allowed_categories and temp_voice_category != current["temp_voice_category"]:
            return RedirectResponse(f"{target}?error=voice#discord", status_code=303)
        event_channel = (form.get("event_channel") or [""])[0]
        if event_channel and event_channel not in allowed_channels and event_channel != current["event_channel"]:
            return RedirectResponse(f"{target}?error=channel#discord", status_code=303)
        log_channel = (form.get("log_channel") or [""])[0]
        if log_channel and log_channel not in allowed_channels and log_channel != current["log_channel"]:
            return RedirectResponse(f"{target}?error=channel#discord", status_code=303)
        existing_tickets = db.ticket_settings(guild["settings"])
        topics = []
        seen_topics = set()
        labels = form.get("ticket_topic_label") or []
        messages = form.get("ticket_topic_message") or []
        topic_roles = form.get("ticket_topic_roles") or []
        for index, label in enumerate(labels):
            label = " ".join(str(label or "").split())
            if not label or label in seen_topics:
                continue
            seen_topics.add(label)
            message = messages[index] if index < len(messages) else ""
            message = str(message or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            roles = []
            raw_roles = str(topic_roles[index] if index < len(topic_roles) else "")
            for role_id in raw_roles.split(","):
                role_id = role_id.strip()
                if role_id in allowed_roles and role_id not in roles:
                    roles.append(role_id)
            topics.append({"label": label[:100], "message": message[:2000], "roles": roles[:20]})
            if len(topics) >= 25:
                break
        language = (form.get("ticket_language") or ["en"])[0]
        if language not in ("en", "nl"):
            language = "en"
        staff_roles = [role_id for role_id in (form.get("ticket_staff_roles") or []) if role_id in allowed_roles]
        log_roles = [role_id for role_id in (form.get("ticket_log_roles") or []) if role_id in allowed_roles]
        category_id = (form.get("ticket_category") or [""])[0]
        panel_channel_id = (form.get("ticket_panel_channel") or [""])[0]
        enabled = (form.get("tickets_enabled") or [""])[0] == "1"
        if category_id and category_id not in allowed_categories:
            category_id = existing_tickets["category_id"] or ""
        if panel_channel_id and panel_channel_id not in allowed_channels:
            panel_channel_id = existing_tickets["panel_channel_id"] or ""
        if enabled and (not panel_channel_id or not staff_roles or not topics):
            return RedirectResponse(f"{target}?error=tickets#tickets", status_code=303)
        tickets_payload = {
            "enabled": enabled,
            "language": language,
            "category_id": category_id or None,
            "panel_channel_id": panel_channel_id or None,
            "staff_roles": staff_roles,
            "log_roles": log_roles,
            "topics": topics,
            "panel_message_id": existing_tickets.get("panel_message_id"),
        }
        try:
            tickets_payload = tickets.publish_panel(existing_tickets, tickets_payload)
        except discord_api.DiscordError:
            return RedirectResponse(f"{target}?error=panel#tickets", status_code=303)
    db.save_wow_settings(
        slug,
        channel,
        chosen,
        timezone,
        channel_mode,
        dungeon_channel if channel_mode == "split" else None,
        mentions,
        signup_roles,
        reminder,
        close_at_start,
        posted_ahead,
        question_thread,
        voice_category,
        attendance_roles,
        settings_roles,
        reminder_2=reminder_2,
        temp_voice=temp_voice,
        temp_voice_category=temp_voice_category,
        temp_voice_limit=temp_voice_limit,
        temp_voice_hub=temp_voice_hub,
        temp_voice_prefix=temp_voice_prefix,
        temp_voice_roles=temp_voice_roles,
        temp_voice_empty=temp_voice_empty,
        temp_voice_max=temp_voice_max,
        event_channel=event_channel,
        log_channel=log_channel,
        tickets=tickets_payload,
        companion_roles=None if "companion_roles" not in form else [role_id for role_id in (form.get("companion_roles") or []) if role_id in allowed_roles],
    )
    fresh = db.guild_by_slug(slug)
    if not setup_mode and fresh and db.wow_settings(fresh["settings"]).get("temp_voice"):
        try:
            wow.ensure_temp_hub(fresh)
        except discord_api.DiscordError:
            db.set_last_error(fresh["id"], "Could not create the join channel.")
            return RedirectResponse(f"{target}?error=hub#discord", status_code=303)
    if not setup_mode and fresh:
        try:
            problem = wow.release_raids(fresh)
        except discord_api.DiscordError:
            db.set_last_error(fresh["id"], "Could not post the next raid.")
            problem = "discord"
        if problem:
            return RedirectResponse(f"/{slug}/raids?error={problem}", status_code=303)
    if setup_mode and fresh and fresh["setup_complete"]:
        return RedirectResponse(f"/{slug}/raids", status_code=303)
    tab = (form.get("settings_tab") or [""])[0]
    if tab not in ("general", "discord", "posts", "tickets"):
        tab = ""
    return RedirectResponse(f"{target}?saved=1" + (f"#{tab}" if tab else ""), status_code=303)


def _mention_choices(form, allowed_roles):
    known = {item["id"] for item in wow.instances()}
    chosen = {}
    for raw in form.get("mentions") or []:
        instance_id, separator, role_id = str(raw).partition(":")
        if not separator or instance_id not in known or role_id not in allowed_roles:
            continue
        roles = chosen.setdefault(instance_id, [])
        if role_id not in roles and len(roles) < 20:
            roles.append(role_id)
    return chosen


def _channel_names(guild):
    return {channel["id"]: channel["name"] for channel in guild["channels"]}


def _raid_view(guild):
    raids = db.raids_for_guild(guild["id"]) if config.live() else []
    for raid in raids:
        raid["when"] = wow.format_span(raid["starts_at"], raid.get("ends_at"), guild["settings"])
        raid["starts_input"] = wow.input_when(raid["starts_at"], guild["settings"])
        raid["ends_input"] = wow.input_when(raid["ends_at"], guild["settings"]) if raid.get("ends_at") else ""
        raid["groups"] = wow.roster_groups(raid, raid["signups"])
        raid["discord_url"] = wow.discord_url(guild["id"], raid["channel_id"], raid["message_id"])
        raid["loot_label"] = wow.loot_label(raid.get("loot_rule"))
        raid["wants"] = wow.raid_wants(raid.get("instance_id"), raid.get("signups") or [])
        raid["voice_done"] = raid.get("voice_state") == "done"
    raids = wow.raid_list(raids, guild["settings"])
    for raid in raids:
        if not wow.raid_is_archived(raid):
            continue
        present = [row["name"] for row in db.attendance_for(raid["id"]) if row["present"]]
        raid["present_label"] = (
            f"{len(present)} present · {', '.join(present)}" if present else "Nobody marked present"
        )
    config_wow = db.wow_settings(guild["settings"])
    names = _channel_names(guild)
    raid_name = names.get(config_wow["raid_channel"], "")
    event_name = names.get(config_wow["event_channel"], "")
    if config_wow["channel_mode"] == "split":
        dungeon_name = names.get(config_wow["dungeon_channel"], "")
        parts = [f"#{name}" for name in (dungeon_name, raid_name) if name]
    else:
        parts = [f"#{raid_name}"] if raid_name else []
    if event_name and f"#{event_name}" not in parts:
        parts.append(f"#{event_name}")
    channel_label = " · ".join(parts)
    return raids, channel_label


@app.get("/{slug}/raids", response_class=HTMLResponse)
def raids_page(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    raids, channel_label = _raid_view(guild)
    active = [raid for raid in raids if not wow.raid_is_archived(raid)]
    code = request.query_params.get("error") or ""
    draft = _load_raid_draft(request) if code in _RAID_DRAFT_ERRORS else None
    form_draft = draft if draft and not draft.get("raid_id") else None
    edit_draft = draft if draft and draft.get("raid_id") else None
    note_roles, note_people = wow.note_tag_choices(guild)
    response = render(
        request,
        "raids.html",
        guild=guild,
        nav="raids",
        raids=active,
        has_archive=any(wow.raid_is_archived(raid) for raid in raids),
        channel_label=channel_label,
        instances=wow.instance_groups(),
        instance_source=wow.instance_source(),
        error=WOW_ERRORS.get(code, ""),
        saved=request.query_params.get("saved") == "1",
        posted_ahead=db.wow_settings(guild["settings"])["posted_ahead"],
        default_reminder=db.parse_reminder_minutes(db.wow_settings(guild["settings"])["reminder"]),
        default_reminder_2=db.parse_second_reminder(
            db.wow_settings(guild["settings"])["reminder_2"],
            db.parse_reminder_minutes(db.wow_settings(guild["settings"])["reminder"]),
        ),
        loot_rules=wow.LOOT_RULES,
        note_roles=note_roles,
        note_people=note_people,
        can_attendance=(not config.live()) or can_correct_attendance(_session(request), guild),
        form_draft=form_draft,
        edit_draft=edit_draft,
    )
    if request.cookies.get(RAID_FORM_COOKIE) and code not in _RAID_DRAFT_ERRORS:
        _clear_raid_draft(response)
    return response


@app.get("/{slug}/archive", response_class=HTMLResponse)
def archive_page(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    raids, _channel_label = _raid_view(guild)
    return render(
        request,
        "archive.html",
        guild=guild,
        nav="archive",
        raids=[raid for raid in raids if wow.raid_is_archived(raid)],
        can_attendance=(not config.live()) or can_correct_attendance(_session(request), guild),
    )


def _ticket_status(ticket):
    if ticket["status"] == "claimed":
        return f"Claimed by {ticket.get('claimed_by_name') or 'staff'}"
    if ticket["status"] == "closed":
        return "Closed"
    return "Open"


def _ticket_guard(request, slug):
    guild, error = guild_or_404(request, slug)
    if error:
        return None, error
    moved = _away_from(guild, "wow")
    if moved:
        return None, moved
    if config.live() and not can_view_tickets(_session(request), guild):
        return None, forbidden(request, "Your roles don't include this page.")
    return guild, None


@app.get("/{slug}/tickets", response_class=HTMLResponse)
def tickets_page(slug: str, request: Request):
    guild, error = _ticket_guard(request, slug)
    if error:
        return error
    view = request.query_params.get("status") or "open"
    if view not in ("open", "closed"):
        view = "open"
    query = " ".join((request.query_params.get("q") or "").split())[:80]
    rows = []
    open_count = 0
    closed_count = 0
    for ticket in tickets.list_for_guild(guild["id"]):
        closed = ticket["status"] == "closed"
        if closed:
            closed_count += 1
        else:
            open_count += 1
        if (view == "closed") != closed or not tickets.matches_name(ticket, query):
            continue
        rows.append({
            **ticket,
            "when": tickets.when(ticket["opened_at"], guild["settings"]),
            "status_label": _ticket_status(ticket),
        })
    return render(
        request,
        "tickets.html",
        guild=guild,
        nav="tickets",
        tickets=rows,
        open_count=open_count,
        closed_count=closed_count,
        status=view,
        query=query,
    )


@app.get("/{slug}/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_page(slug: str, ticket_id: str, request: Request):
    guild, error = _ticket_guard(request, slug)
    if error:
        return error
    ticket = tickets.load(guild["id"], ticket_id)
    if ticket is None:
        return RedirectResponse(f"/{slug}/tickets", status_code=303)
    synced = True
    if ticket["status"] != "closed":
        synced = tickets.sync_ticket(guild, ticket)
    ticket["when"] = tickets.when(ticket["opened_at"], guild["settings"])
    ticket["status_label"] = _ticket_status(ticket)
    discord_url = ""
    if ticket["status"] != "closed" and ticket.get("channel_id"):
        discord_url = f"https://discord.com/channels/{guild['id']}/{ticket['channel_id']}"
    code = request.query_params.get("error") or ""
    return render(
        request,
        "ticket.html",
        guild=guild,
        nav="tickets",
        ticket=ticket,
        messages=tickets.transcript(ticket["id"], guild["settings"]),
        discord_url=discord_url,
        synced=synced,
        error=code,
    )


@app.post("/{slug}/tickets/{ticket_id}/reply")
async def ticket_reply(slug: str, ticket_id: str, request: Request):
    guild, error = _ticket_guard(request, slug)
    if error:
        return error
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    body = (form.get("body") or [""])[0]
    problem = tickets.post_reply(guild, ticket_id, viewer(request)["name"], body)
    if problem:
        return RedirectResponse(
            f"/{slug}/tickets/{ticket_id}?error={urllib.parse.quote(problem)}",
            status_code=303,
        )
    return RedirectResponse(f"/{slug}/tickets/{ticket_id}", status_code=303)


@app.post("/{slug}/tickets/{ticket_id}/claim")
async def ticket_claim(slug: str, ticket_id: str, request: Request):
    guild, error = _ticket_guard(request, slug)
    if error:
        return error
    person = viewer(request)
    problem = tickets.claim_from_web(guild, ticket_id, person["id"], person["name"])
    if problem:
        return RedirectResponse(
            f"/{slug}/tickets/{ticket_id}?error={urllib.parse.quote(problem)}",
            status_code=303,
        )
    return RedirectResponse(f"/{slug}/tickets/{ticket_id}", status_code=303)


@app.post("/{slug}/tickets/{ticket_id}/close")
async def ticket_close(slug: str, ticket_id: str, request: Request):
    guild, error = _ticket_guard(request, slug)
    if error:
        return error
    person = viewer(request)
    problem = tickets.close_from_web(guild, ticket_id, person["id"], person["name"])
    target = f"/{slug}/tickets/{ticket_id}"
    if problem:
        return RedirectResponse(f"{target}?error={urllib.parse.quote(problem)}", status_code=303)
    return RedirectResponse(target, status_code=303)


def _clean_raid_draft(form, raid_id=None):
    """The fields an officer just typed. Kept when the save is rejected."""

    def one(key, limit):
        return ((form.get(key) or [""])[0] or "")[:limit]

    repeat = one("repeat", 16)
    if repeat not in ("once", "week"):
        repeat = "once"
    first = db.parse_reminder_minutes(one("reminder", 8))
    second = db.parse_second_reminder(one("reminder_2", 8), first)
    extras = []
    for value in form.get("extra_at") or []:
        text = str(value or "").strip()[:16]
        if text:
            extras.append(text)
        if len(extras) >= 8:
            break
    draft = {
        "instance": one("instance", 80),
        "title": one("title", 80),
        "note": one("note", 400),
        "loot_rule": one("loot_rule", 40),
        "starts_at": one("starts_at", 16),
        "ends_at": one("ends_at", 16),
        "reminder": first,
        "reminder_2": second,
        "tank_cap": one("tank_cap", 4),
        "healer_cap": one("healer_cap", 4),
        "dps_cap": one("dps_cap", 4),
        "repeat": repeat,
        "repeat_count": one("repeat_count", 2) or "4",
        "extra_at": extras,
    }
    if raid_id is not None:
        draft["raid_id"] = int(raid_id)
    return draft


def _stash_raid_draft(response, draft):
    raw = base64.urlsafe_b64encode(json.dumps(draft, separators=(",", ":")).encode()).decode()
    if len(raw) > 3500:
        return
    response.set_cookie(
        RAID_FORM_COOKIE,
        raw,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=_secure(),
        path="/",
    )


def _load_raid_draft(request):
    raw = request.cookies.get(RAID_FORM_COOKIE) or ""
    if not raw:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    form = {key: ["" if data.get(key) is None else str(data.get(key))] for key in (
        "instance", "title", "note", "loot_rule", "starts_at", "ends_at", "reminder", "reminder_2",
        "tank_cap", "healer_cap", "dps_cap", "repeat", "repeat_count",
    )}
    form["extra_at"] = [str(value) for value in (data.get("extra_at") or []) if value]
    raid_id = data.get("raid_id")
    try:
        raid_id = int(raid_id) if raid_id is not None else None
    except (TypeError, ValueError):
        raid_id = None
    return _clean_raid_draft(form, raid_id)


def _raid_error(target, code, form, raid_id=None):
    """Send the officer back to the form with what they typed still in it."""
    anchor = f"#raid-{int(raid_id)}" if raid_id else ""
    response = RedirectResponse(f"{target}?error={code}{anchor}", status_code=303)
    if code in _RAID_DRAFT_ERRORS:
        _stash_raid_draft(response, _clean_raid_draft(form, raid_id))
    return response


def _clear_raid_draft(response):
    response.delete_cookie(RAID_FORM_COOKIE, path="/", samesite="lax", secure=_secure(), httponly=True)


def _chosen_reminders(form, settings):
    config = db.wow_settings(settings)
    first_raw = form.get("reminder")
    second_raw = form.get("reminder_2")
    first = db.parse_reminder_minutes((first_raw or [config["reminder"]])[0])
    second_value = (second_raw or [config["reminder_2"]])[0]
    return first, db.parse_second_reminder(second_value, first)


def _raid_numbers(form, settings, limit, event=False, guild=None):
    raw_note = (form.get("note") or [""])[0]
    note = wow.note_clean(raw_note, guild) if guild is not None else (raw_note.strip()[:400] or None)
    reminder_minutes, reminder_2_minutes = _chosen_reminders(form, settings)
    try:
        starts_at = wow.parse_starts((form.get("starts_at") or [""])[0], settings)
    except ValueError:
        return None, "when"
    try:
        ends_at = wow.parse_ends((form.get("ends_at") or [""])[0], settings, starts_at)
    except ValueError as error:
        code = str(error)
        return None, code if code in ("when", "end") else "when"
    if event:
        return {
            "starts_at": starts_at,
            "ends_at": ends_at,
            "note": note,
            "caps": [0, 0, 0],
            "reminder_minutes": reminder_minutes,
            "reminder_2_minutes": reminder_2_minutes,
        }, None
    try:
        caps = [int((form.get(key) or [""])[0]) for key in ("tank_cap", "healer_cap", "dps_cap")]
    except (TypeError, ValueError):
        return None, "caps"
    if any(cap < 0 or cap > limit for cap in caps) or sum(caps) < 1:
        return None, "caps"
    if sum(caps) > limit:
        return None, "over"
    return {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "note": note,
        "caps": caps,
        "reminder_minutes": reminder_minutes,
        "reminder_2_minutes": reminder_2_minutes,
    }, None


@app.post("/{slug}/raids")
async def create_raid_page(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    target = f"/{slug}/raids"
    if guild["approval"] != "approved":
        return RedirectResponse(f"{target}?error=pending", status_code=303)
    if not guild["setup_complete"]:
        return RedirectResponse(f"{target}?error=setup", status_code=303)
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    instance = wow.instance_by_id((form.get("instance") or [""])[0])
    if instance is None:
        return _raid_error(target, "title", form)
    event = wow.is_event(instance)
    title = (form.get("title") or [""])[0].strip()[:80]
    if event:
        if not title:
            return _raid_error(target, "name", form)
        rule_id = None
        size = 0
    else:
        title = title or instance["name"]
        rule = wow.loot_rule((form.get("loot_rule") or [""])[0])
        if rule is None:
            return _raid_error(target, "loot", form)
        rule_id = rule["id"]
        size = instance["size"]
    numbers, code = _raid_numbers(form, guild["settings"], instance["size"], event=event, guild=guild)
    if code:
        return _raid_error(target, code, form)
    repeat = (form.get("repeat") or ["once"])[0]
    extras = []
    for raw in form.get("extra_at") or []:
        if not str(raw).strip():
            continue
        try:
            extras.append(wow.parse_starts(raw, guild["settings"]))
        except ValueError:
            return _raid_error(target, "when", form)
    starts = wow.collect_starts(numbers["starts_at"], repeat, (form.get("repeat_count") or ["2"])[0], extras)
    if not starts:
        return _raid_error(target, "many", form)
    wow_config = db.wow_settings(guild["settings"])
    channel_id = wow.event_channel(wow_config, instance)
    allowed = {item["id"] for group in _wow_channel_groups(guild) for item in group["channels"]}
    if channel_id not in allowed:
        return _raid_error(target, "channel", form)
    for starts_at in starts:
        db.create_raid(
            guild["id"],
            title,
            starts_at,
            numbers["caps"][0],
            numbers["caps"][1],
            numbers["caps"][2],
            channel_id,
            viewer(request)["name"],
            size,
            instance["id"],
            numbers["note"],
            "scheduled",
            rule_id,
            wow.shift_end(numbers["starts_at"], numbers["ends_at"], starts_at),
            numbers["reminder_minutes"],
            numbers["reminder_2_minutes"],
        )
    try:
        problem = wow.release_raids(guild)
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not post a raid message.")
        problem = "discord"
    if problem:
        return RedirectResponse(f"{target}?error={problem}", status_code=303)
    return RedirectResponse(target, status_code=303)


@app.post("/{slug}/raids/{raid_id}")
async def update_raid_page(slug: str, raid_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    target = f"/{slug}/raids"
    raid = db.raid_by_id(raid_id)
    if raid is None or str(raid["guild_id"]) != str(guild["id"]) or raid["status"] not in ("open", "scheduled"):
        return RedirectResponse(target, status_code=303)
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    event = wow.is_event(raid)
    numbers, code = _raid_numbers(form, guild["settings"], int(raid.get("size") or 40), event=event, guild=guild)
    if code:
        return _raid_error(target, code, form, raid_id)
    if event:
        rule_id = None
    else:
        rule = wow.loot_rule((form.get("loot_rule") or [""])[0])
        rule_id = None if rule is None else rule["id"]
    db.update_raid(
        raid_id,
        guild["id"],
        numbers["starts_at"],
        numbers["caps"][0],
        numbers["caps"][1],
        numbers["caps"][2],
        numbers["note"],
        rule_id,
        numbers["ends_at"],
        numbers["reminder_minutes"],
        numbers["reminder_2_minutes"],
    )
    fresh = db.raid_by_id(raid_id)
    if fresh and fresh.get("message_id"):
        try:
            wow.publish(db.guild_by_id(guild["id"]), fresh)
        except discord_api.DiscordError:
            db.set_last_error(guild["id"], "Could not update a raid message.")
            return RedirectResponse(f"{target}?error=refresh", status_code=303)
    try:
        problem = wow.release_raids(db.guild_by_id(guild["id"]))
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not post the next raid.")
        problem = "discord"
    if problem:
        return RedirectResponse(f"{target}?error={problem}", status_code=303)
    return RedirectResponse(f"{target}?saved=1", status_code=303)


def _roster_html(guild, raid_id):
    raid = db.raid_by_id(raid_id)
    raid["signups"] = db.signups_for(raid_id)
    raid["groups"] = wow.roster_groups(raid, raid["signups"])
    return templates.get_template("_raid_roster.html").render(raid=raid, guild=guild)


def _publish_move(guild_id, raid_id, signup, plan):
    guild = db.guild_by_id(guild_id)
    raid = db.raid_by_id(raid_id)
    if guild is None or raid is None:
        return
    try:
        wow.publish(guild, raid)
    except discord_api.DiscordError as error:
        log.warning(
            "Could not update raid message after a move (raid %s, HTTP %s): %s",
            raid_id,
            error.status,
            error.body,
        )
        db.set_last_error(guild_id, "Could not update the raid message after a move.")
        return
    try:
        wow.announce_move(raid, signup, plan)
    except discord_api.DiscordError as error:
        log.warning(
            "Could not post the move notice (raid %s, HTTP %s): %s",
            raid_id,
            error.status,
            error.body,
        )
        db.set_last_error(guild_id, "Could not post the move notice.")
        return
    db.clear_last_error(guild_id, ("Could not post the move notice.",))


@app.post("/{slug}/raids/{raid_id}/move")
async def move_signup_page(slug: str, raid_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    target = f"/{slug}/raids"
    fetch = request.headers.get("x-requested-with") == "fetch"
    raid = db.raid_by_id(raid_id)
    if raid is None or str(raid["guild_id"]) != str(guild["id"]):
        if fetch:
            return JSONResponse({"ok": False, "error": WOW_ERRORS["move"]}, status_code=404)
        return RedirectResponse(target, status_code=303)
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    user_id = (form.get("user_id") or [""])[0]
    lane = (form.get("lane") or [""])[0]
    signups = db.signups_for(raid_id)
    signup = next((row for row in signups if row["user_id"] == user_id), None)
    plan = wow.move_plan(raid, signup, signups, lane) if signup else None
    if plan is None or not db.set_signup_lane(raid_id, user_id, plan["role"], plan["state"], plan.get("party", 1)):
        if fetch:
            return JSONResponse({"ok": False, "error": WOW_ERRORS["move"]}, status_code=400)
        return RedirectResponse(f"{target}?error=move", status_code=303)
    if fetch:
        return JSONResponse(
            {"ok": True, "html": _roster_html(guild, raid_id)},
            background=BackgroundTask(_publish_move, guild["id"], raid_id, signup, plan),
        )
    fresh = db.guild_by_id(guild["id"])
    updated = db.raid_by_id(raid_id)
    try:
        wow.publish(fresh, updated)
    except discord_api.DiscordError as error:
        log.warning(
            "Could not update raid message after a move (raid %s, HTTP %s): %s",
            raid_id,
            error.status,
            error.body,
        )
        db.set_last_error(guild["id"], "Could not update the raid message after a move.")
        return RedirectResponse(f"{target}?error=refresh", status_code=303)
    try:
        wow.announce_move(updated, signup, plan)
    except discord_api.DiscordError as error:
        log.warning(
            "Could not post the move notice (raid %s, HTTP %s): %s",
            raid_id,
            error.status,
            error.body,
        )
        db.set_last_error(guild["id"], "Could not post the move notice.")
        return RedirectResponse(f"{target}?error=refresh", status_code=303)
    db.clear_last_error(guild["id"], ("Could not post the move notice.",))
    return RedirectResponse(target, status_code=303)


@app.post("/{slug}/raids/{raid_id}/close")
def close_raid_page(slug: str, raid_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    target = f"/{slug}/raids"
    raid = db.raid_by_id(raid_id)
    if raid is None or str(raid["guild_id"]) != str(guild["id"]):
        return RedirectResponse(target, status_code=303)
    db.close_raid(raid_id)
    close_error = False
    thread_error = False
    try:
        wow.publish(db.guild_by_id(guild["id"]), db.raid_by_id(raid_id))
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not close the raid message in Discord.")
        close_error = True
    try:
        wow.archive_question_thread(raid)
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not lock the question thread.")
        thread_error = True
    try:
        problem = wow.release_raids(db.guild_by_id(guild["id"]))
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not post the next raid.")
        problem = "discord"
    if problem:
        return RedirectResponse(f"{target}?error={problem}", status_code=303)
    if close_error:
        return RedirectResponse(f"{target}?error=closed", status_code=303)
    if thread_error:
        return RedirectResponse(f"{target}?error=thread", status_code=303)
    return RedirectResponse(target, status_code=303)


def _attendance_raid(slug, raid_id, request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return None, error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return None, moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return None, blocked
    if not can_correct_attendance(_session(request), guild):
        return None, forbidden(request, "Your roles don't include this page.")
    raid = db.raid_by_id(raid_id)
    ready = raid and (raid.get("voice_state") in ("open", "done") or raid.get("status") == "closed")
    if raid is None or str(raid["guild_id"]) != str(guild["id"]) or not ready:
        return None, RedirectResponse(f"/{slug}/raids", status_code=303)
    return (guild, raid), None


@app.get("/{slug}/raids/{raid_id}/attendance", response_class=HTMLResponse)
def raid_attendance_page(slug: str, raid_id: int, request: Request):
    found, error = _attendance_raid(slug, raid_id, request)
    if error:
        return error
    guild, raid = found
    raid["when"] = wow.format_span(raid["starts_at"], raid.get("ends_at"), guild["settings"])
    sheet = wow.attendance_sheet(db.signups_for(raid_id), db.attendance_for(raid_id), db.list_members(guild["id"]))
    preview = [] if raid.get("voice_state") == "done" else wow.attendance_preview(raid)
    code = request.query_params.get("error") or ""
    return render(
        request,
        "wow_attendance.html",
        guild=guild,
        nav="archive" if wow.raid_is_archived(raid) else "raids",
        raid=raid,
        sheet=sheet,
        back_href=f"/{slug}/archive" if wow.raid_is_archived(raid) else f"/{slug}/raids",
        back_label="Back to archive" if wow.raid_is_archived(raid) else "Back to raids",
        preview=preview,
        error="The voice channel could not be removed, so attendance was not saved." if code == "voice" else "",
    )


@app.post("/{slug}/raids/{raid_id}/attendance")
async def save_raid_attendance(slug: str, raid_id: int, request: Request):
    found, error = _attendance_raid(slug, raid_id, request)
    if error:
        return error
    guild, raid = found
    target = f"/{slug}/raids/{raid_id}/attendance"
    form = urllib.parse.parse_qs((await request.body()).decode(), keep_blank_values=True)
    if (form.get("process") or [""])[0] == "1":
        problem = wow.settle_attendance(guild, raid)
        if problem == "channel":
            return RedirectResponse(f"{target}?error=voice", status_code=303)
        return RedirectResponse(target, status_code=303)
    user_id = (form.get("user_id") or [""])[0]
    present = (form.get("present") or ["0"])[0] == "1"
    member = next((person for person in db.list_members(guild["id"]) if person["user_id"] == user_id), None)
    if member is not None:
        name = member.get("nick") or member.get("name") or "Discord member"
    elif present:
        signup = next(
            (row for row in db.signups_for(raid_id) if row["user_id"] == user_id and row["state"] in ("main", "late", "reserve")),
            None,
        )
        if signup is None:
            return RedirectResponse(target, status_code=303)
        name = signup["name"]
    else:
        existing = next((row for row in db.attendance_for(raid_id) if row["user_id"] == user_id), None)
        if existing is None:
            return RedirectResponse(target, status_code=303)
        name = existing["name"]
    db.set_attendance(raid_id, user_id, name, present)
    return RedirectResponse(target, status_code=303)


@app.post("/{slug}/raids/{raid_id}/delete")
def delete_raid_page(slug: str, raid_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return error or JSONResponse({"error": "forbidden"}, status_code=403)
    moved = _away_from(guild, "wow")
    if moved:
        return moved
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    target = f"/{slug}/archive" if request.query_params.get("back") == "archive" else f"/{slug}/raids"
    raid = db.raid_by_id(raid_id)
    if raid is None or str(raid["guild_id"]) != str(guild["id"]):
        return RedirectResponse(target, status_code=303)
    wow.discard_voice(raid)
    try:
        wow.remove_discord_raid(raid)
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not delete the raid message in Discord.")
        return RedirectResponse(f"{target}?error=removed", status_code=303)
    db.delete_raid(raid_id)
    try:
        problem = wow.release_raids(db.guild_by_id(guild["id"]))
    except discord_api.DiscordError:
        db.set_last_error(guild["id"], "Could not post the next raid.")
        problem = "discord"
    if problem:
        return RedirectResponse(f"{target}?error={problem}", status_code=303)
    return RedirectResponse(target, status_code=303)


@app.middleware("http")
async def _companion_routes_stay_off(request: Request, call_next):
    # Companion routes answer 404 until IRONKEEP_COMPANION_AUTH is set.
    hidden = companion_auth.hidden(request)
    if hidden is not None:
        return hidden
    return await call_next(request)


app.include_router(companion_auth.router)
