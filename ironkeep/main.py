import secrets
import urllib.parse
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import attendance, config, db, discord_api, roster, wow
from . import mock_data as data
from pathlib import Path

BASE_DIR = Path(__file__).parent
VIEW_COOKIE = "ik_view"
SESSION_COOKIE = "ik_session"

app = FastAPI(title="Ironkeep", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def asset(path: str) -> str:
    version = int((BASE_DIR / "static" / path).stat().st_mtime)
    return f"/static/{path}?v={version}"


templates.env.globals["asset"] = asset
db.init()


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


def viewer(request: Request, guild=None):
    if not config.live():
        if request.cookies.get(VIEW_COOKIE) == "recruiter":
            person = {**data.RECRUITER, "superadmin": False, "role": "recruiter"}
        else:
            person = {**data.SUPERADMIN, "superadmin": True, "role": "superadmin"}
        person["names"] = [person["name"]]
        return person
    session = _session(request)
    if not session:
        return {"id": "", "name": "Guest", "names": ["Guest"], "color": "#8d95a1", "superadmin": False, "role": "guest"}
    account = session["name"]
    name = account
    if guild is not None:
        server_name = db.member_server_name(guild["id"], session["user_id"])
        if server_name:
            name = server_name
    names = []
    for item in (name, account):
        if item and item not in names:
            names.append(item)
    superadmin = session["user_id"] == config.SUPERADMIN_ID
    return {
        "id": session["user_id"],
        "name": name,
        "names": names,
        "username": session["username"],
        "color": db.PALETTE[int(session["user_id"]) % len(db.PALETTE)],
        "superadmin": superadmin,
        "role": "superadmin" if superadmin else "recruiter",
    }


def _member_roles(session, guild):
    cached = db.cached_roles(session["user_id"], guild["id"])
    if cached is not None:
        return set(cached)
    token = session.get("access_token")
    try:
        member = discord_api.guild_member(token, guild["id"])
    except discord_api.DiscordError as error:
        if error.status != 401 or not session.get("refresh_token"):
            return set()
        try:
            refreshed = discord_api.refresh_access_token(session["refresh_token"])
        except discord_api.DiscordError:
            return set()
        db.update_session_tokens(
            session["token"],
            refreshed["access_token"],
            refreshed.get("refresh_token") or session["refresh_token"],
            refreshed.get("expires_in", 604800),
        )
        session["access_token"] = refreshed["access_token"]
        try:
            member = discord_api.guild_member(session["access_token"], guild["id"])
        except discord_api.DiscordError:
            return set()
    roles = {str(role) for role in member.get("roles", [])}
    db.store_roles(session["user_id"], guild["id"], sorted(roles))
    return roles


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
    """Raids, members, characters and settings."""
    if _staff(session, guild):
        return True
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


def can_open_guild(session, guild):
    return can_access(session, guild) or can_view_payout(session, guild) or can_book_lootsplit(session, guild)


def home_path(session, guild):
    slug = guild["slug"]
    if can_access(session, guild):
        return f"/{slug}/raids"
    if can_book_lootsplit(session, guild):
        return f"/{slug}/lootsplit"
    if can_view_payout(session, guild):
        return f"/{slug}/payout"
    return f"/{slug}/raids"


def page_access(request, guild):
    person = viewer(request)
    if not config.live():
        label = "Superadmin" if person["superadmin"] else "Recruiter"
        return {"trials": True, "payout": True, "lootsplit": True, "guild": True, "label": label}
    session = _session(request)
    trials = can_access(session, guild)
    payout = can_view_payout(session, guild)
    lootsplit = can_book_lootsplit(session, guild)
    if person["superadmin"]:
        label = "Superadmin"
    elif trials:
        label = "Recruiter"
    elif lootsplit:
        label = "Lootsplit"
    else:
        label = "Member"
    return {"trials": trials, "payout": payout, "lootsplit": lootsplit, "guild": trials, "label": label}


def deny_unless(request, guild, area):
    if not config.live():
        return None
    session = _session(request)
    allowed = {"trials": can_access, "payout": can_view_payout, "lootsplit": can_book_lootsplit}[area]
    if allowed(session, guild):
        return None
    return forbidden(request, "Your roles don't include this page.")


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
    context.setdefault("viewer", viewer(request, context.get("guild")))
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
        target = "/dutchchaos/raids"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(VIEW_COOKIE, "recruiter" if role == "recruiter" else "superadmin", samesite="lax")
    return response


@app.get("/trial")
def trial_redirect(request: Request):
    if config.live() and not viewer(request)["id"]:
        return login_redirect(request)
    slugs = [g["slug"] for g in visible_guilds(request)]
    if len(slugs) == 1:
        guild = next(item for item in visible_guilds(request) if item["slug"] == slugs[0])
        return RedirectResponse(guild.get("home") or f"/{slugs[0]}/raids", status_code=303)
    if viewer(request)["superadmin"]:
        return RedirectResponse("/admin", status_code=303)
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
    return RedirectResponse(home_path(session, guild) if config.live() else f"/{slug}/raids", status_code=303)


@app.get("/{slug}/trial", response_class=HTMLResponse)
def trials(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
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
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    source = db.list_members(guild["id"]) if config.live() else data.DEMO_MEMBERS.get(guild["slug"], [])
    prepared = prepare_members(guild, source)
    attach_characters(guild, prepared["people"])
    return render(request, "members.html", guild=guild, nav="members", **prepared)


# Sample mains and alts for the prototype. Live guilds start empty.
_CHARACTER_SEED = (
    ("9001", "Sylasvoker", "mage", "frost", "dps", True),
    ("9001", "Sylasrogue", "rogue", "combat", "dps", False),
    ("9002", "Bramlight", "priest", "holy", "healer", True),
    ("9004", "Mirabear", "druid", "feral", "tank", True),
    ("9004", "Miramoon", "druid", "balance", "dps", False),
    ("9006", "Noorfrost", "mage", "frost", "dps", True),
)
_CHARACTER_MEMORY = {}
_CHARACTER_SEQ = {}


def _seed_characters(guild_id):
    if guild_id in _CHARACTER_MEMORY:
        return _CHARACTER_MEMORY[guild_id]
    rows = []
    if str(guild_id) == "806607423233327195":
        for index, (user_id, name, class_id, spec_id, role, is_main) in enumerate(_CHARACTER_SEED, start=1):
            rows.append(
                {
                    "id": index,
                    "user_id": user_id,
                    "name": name,
                    "class_id": class_id,
                    "spec_id": spec_id,
                    "role": role,
                    "is_main": is_main,
                }
            )
    _CHARACTER_MEMORY[guild_id] = rows
    _CHARACTER_SEQ[guild_id] = len(rows) + 1
    return rows


def _character_rows(guild):
    if config.live():
        return db.list_characters(guild["id"])
    return _seed_characters(guild["id"])


def _change_characters(guild, fn):
    if config.live():
        return db.change_characters(guild["id"], fn)
    rows = _seed_characters(guild["id"])
    result = fn(rows)
    seq = _CHARACTER_SEQ[guild["id"]]
    for row in rows:
        if row.get("id") is None:
            row["id"] = seq
            seq += 1
    _CHARACTER_SEQ[guild["id"]] = seq
    return result


def _presented_characters(guild):
    presented = []
    for row in _character_rows(guild):
        item = wow.present(row)
        if item:
            presented.append(item)
    return presented


def attach_characters(guild, people):
    """Main and alt count for each Discord member on the members page."""
    grouped = {}
    for row in _presented_characters(guild):
        grouped.setdefault(row["user_id"], []).append(row)
    for person in people:
        rows = grouped.get(str(person.get("user_id")), [])
        person["main"] = next((row for row in rows if row["is_main"]), None)
        person["alt_count"] = sum(1 for row in rows if not row["is_main"])
        person["character_search"] = " ".join(row["name"] for row in rows)


def character_board(guild):
    """Discord members with their main and alts, plus the class list for the form."""
    grouped = {}
    for row in _presented_characters(guild):
        grouped.setdefault(row["user_id"], []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: (not item["is_main"], item["name"].casefold()))
    people = []
    known = set()
    for person in directory_members(guild):
        known.add(person["id"])
        people.append({**person, "characters": grouped.get(person["id"], [])})
    for user_id, rows in grouped.items():
        if user_id in known:
            continue
        people.append(
            {
                "id": user_id,
                "name": "Left the server",
                "username": "",
                "label": "Left the server",
                "color": "#8d95a1",
                "gone": True,
                "characters": rows,
            }
        )
    return {"people": people, "classes": wow.catalog()}


def _character_fields(body):
    if not isinstance(body, dict):
        return None
    return {
        "name": body.get("name"),
        "class_id": body.get("class_id"),
        "spec_id": body.get("spec_id"),
        "role": body.get("role"),
        "is_main": bool(body.get("is_main")),
    }


FOREVER_RAIDS = [
    {"id": "barrow", "name": "Barrow Deeps", "size": 10, "opens": "9 Dec 2026", "detail": "The 10-player raid. About eight bosses."},
    {"id": "hyjal", "name": "Hyjal Summit", "size": 20, "opens": "9 Dec 2026", "detail": "The 20-player raid. Same tier as the 10."},
    {"id": "onyxia", "name": "Onyxia's Lair", "size": 40, "opens": "9 Dec 2026", "detail": "The 40-player guild night."},
]
_RAID_MEMORY = {}


def _raid_by_id(raid_id):
    return next((raid for raid in FOREVER_RAIDS if raid["id"] == raid_id), None)


def _seed_raid_memory(guild_id):
    if guild_id in _RAID_MEMORY:
        return _RAID_MEMORY[guild_id]
    sample = [
        ("barrow", "9001", "Sylas", "roster"),
        ("barrow", "9002", "Bram", "roster"),
        ("barrow", "9004", "Mira", "roster"),
        ("barrow", "9003", "Kaelen", "reserve"),
        ("hyjal", "9001", "Sylas", "roster"),
        ("hyjal", "9006", "Noor", "roster"),
        ("hyjal", "9005", "Pim", "reserve"),
    ]
    _RAID_MEMORY[guild_id] = [
        {"raid_id": raid_id, "user_id": user_id, "name": name, "seat": seat} for raid_id, user_id, name, seat in sample
    ]
    return _RAID_MEMORY[guild_id]


def raid_signups(guild):
    if config.live():
        return db.list_raid_signups(guild["id"])
    return list(_seed_raid_memory(guild["id"]))


def raid_people(guild):
    source = db.list_members(guild["id"]) if config.live() else data.DEMO_MEMBERS.get(guild["slug"], [])
    mains = {row["user_id"]: row for row in _presented_characters(guild) if row["is_main"]}
    people = []
    for person in source:
        user_id = str(person.get("user_id") or "").strip()
        name = str(person.get("name") or "").strip()
        if user_id and name:
            main = mains.get(user_id)
            people.append(
                {
                    "id": user_id,
                    "name": name,
                    "main": (
                        {
                            "name": main["name"],
                            "class_name": main["class_name"],
                            "spec_name": main["spec_name"],
                            "color": main["color"],
                            "role_name": main["role_name"],
                        }
                        if main
                        else None
                    ),
                }
            )
    people.sort(key=lambda item: item["name"].casefold())
    return people


def save_raid_seat(guild, raid, user_id, name, seat):
    """Put someone on the raid, on the reserve, or take them off. A full raid stays full."""
    current = [row for row in raid_signups(guild) if row["raid_id"] == raid["id"]]
    others = [row for row in current if row["user_id"] != user_id]
    if seat == "roster" and sum(1 for row in others if row["seat"] == "roster") >= raid["size"]:
        return "This raid is full. Put them on the reserve."
    if config.live():
        db.set_raid_signup(guild["id"], raid["id"], user_id, name, seat)
    else:
        stored = [row for row in _seed_raid_memory(guild["id"]) if not (row["raid_id"] == raid["id"] and row["user_id"] == user_id)]
        if seat is not None:
            stored.append({"raid_id": raid["id"], "user_id": user_id, "name": name, "seat": seat})
        _RAID_MEMORY[guild["id"]] = stored
    return None


@app.get("/{slug}/raids", response_class=HTMLResponse)
def raids(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    people = raid_people(guild)
    signups = raid_signups(guild)
    stored = attendance.latest(guild)
    report = (
        attendance.present(stored, _presented_characters(guild), people, FOREVER_RAIDS, signups, guild.get("settings"))
        if stored
        else None
    )
    return render(
        request,
        "raids.html",
        guild=guild,
        nav="raids",
        raids=FOREVER_RAIDS,
        signups=signups,
        people=people,
        report=report,
        companion_key=attendance.token_for(guild),
    )


def _guild_by_slug(slug):
    if config.live():
        return db.guild_by_slug(slug)
    return data.guild_by_slug(slug)


@app.post("/api/{slug}/attendance")
async def receive_attendance(slug: str, request: Request):
    """The companion posts the Copy list here. The key is the only login it has."""
    guild = _guild_by_slug(slug)
    if guild is None:
        return JSONResponse({"error": "Unknown guild."}, status_code=404)
    header = request.headers.get("authorization", "")
    if len(header) < 7 or header[:7].lower() != "bearer ":
        return JSONResponse({"error": "Unknown companion key."}, status_code=401)
    if not attendance.token_matches(guild, header[7:].strip()):
        return JSONResponse({"error": "Unknown companion key."}, status_code=401)
    raw = await request.body()
    if len(raw) > attendance.MAX_BYTES:
        return JSONResponse({"error": "This report is too large."}, status_code=413)
    try:
        report = attendance.parse_text(raw.decode("utf-8"))
    except (UnicodeDecodeError, attendance.ReportError) as error:
        message = error.args[0] if isinstance(error, attendance.ReportError) else "This report could not be read."
        return JSONResponse({"error": message}, status_code=400)
    stored = attendance.store(guild, report)
    return {"ok": True, "place": stored["place"], "people": len(stored["people"])}


@app.post("/api/{slug}/attendance/token")
def rotate_attendance_token(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    attendance.token_for(guild, rotate=True)
    return RedirectResponse(f"/{slug}/raids", status_code=303)


@app.post("/api/{slug}/raids/{raid_id}")
async def save_raid(slug: str, raid_id: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    raid = _raid_by_id(raid_id)
    if raid is None:
        return JSONResponse({"error": "Unknown raid."}, status_code=404)
    body = await request.json()
    seat = body.get("seat")
    if seat not in ("roster", "reserve", None):
        return JSONResponse({"error": "Pick the raid or the reserve."}, status_code=400)
    user_id = str(body.get("user_id") or "")
    person = next((item for item in raid_people(guild) if item["id"] == user_id), None)
    if person is None:
        return JSONResponse({"error": "That person is not on the member list."}, status_code=400)
    message = save_raid_seat(guild, raid, user_id, person["name"], seat)
    if message:
        return JSONResponse({"error": message}, status_code=400)
    signups = [row for row in raid_signups(guild) if row["raid_id"] == raid_id]
    return {"signups": signups}


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


def _roster_result(guild, fn):
    try:
        _change_characters(guild, fn)
    except roster.RosterError as exc:
        return JSONResponse({"error": exc.message}, status_code=400)
    return character_board(guild)


@app.get("/{slug}/characters", response_class=HTMLResponse)
def characters(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    board = character_board(guild)
    return render(request, "characters.html", guild=guild, nav="characters", **board)


@app.post("/api/{slug}/characters")
async def add_character(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    body = await request.json()
    fields = _character_fields(body)
    if fields is None:
        return JSONResponse({"error": "bad body"}, status_code=400)
    user_id = str((body or {}).get("user_id") or "")
    if user_id not in {person["id"] for person in directory_members(guild)}:
        return JSONResponse({"error": "That person is not on the member list."}, status_code=400)
    return _roster_result(guild, lambda rows: roster.add(rows, user_id, fields))


@app.post("/api/{slug}/characters/{character_id}")
async def edit_character(slug: str, character_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    fields = _character_fields(await request.json())
    if fields is None:
        return JSONResponse({"error": "bad body"}, status_code=400)
    return _roster_result(guild, lambda rows: roster.update(rows, character_id, fields))


@app.post("/api/{slug}/characters/{character_id}/main")
def make_main(slug: str, character_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    return _roster_result(guild, lambda rows: roster.set_main(rows, character_id))


@app.delete("/api/{slug}/characters/{character_id}")
def delete_character(slug: str, character_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    return _roster_result(guild, lambda rows: roster.remove(rows, character_id))


@app.get("/{slug}/payout", response_class=HTMLResponse)
def payout_mock(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "payout")
    if blocked:
        return blocked
    return render(request, "payout.html", guild=guild, nav="payout", payout=payout_page(request))


@app.get("/{slug}/lootsplit", response_class=HTMLResponse)
def lootsplit_mock(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
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
        by=viewer(request, guild)["name"],
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
    db.save_settings(slug, saved, new_slug)
    target = new_slug or slug
    if db.setup_complete(saved):
        db.request_scan(target)
    return {"ok": True, "slug": target}


@app.get("/{slug}/settings", response_class=HTMLResponse)
def settings(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    return render(request, "settings.html", guild=guild, nav="settings", setup_mode=False, members=directory_members(guild))


@app.get("/{slug}/setup", response_class=HTMLResponse)
def setup(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    blocked = deny_unless(request, guild, "trials")
    if blocked:
        return blocked
    return render(request, "settings.html", guild=guild, nav="settings", setup_mode=True, members=directory_members(guild))
