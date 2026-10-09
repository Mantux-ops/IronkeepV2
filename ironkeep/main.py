import secrets
import urllib.parse
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db, discord_api
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


def can_access(session, guild):
    if session is None:
        return False
    if session["user_id"] == config.SUPERADMIN_ID:
        return True
    if guild.get("added_by_id") and guild["added_by_id"] == session["user_id"]:
        return True
    recruitment = set(guild["settings"].get("recruitment_roles") or [])
    if not recruitment:
        return False
    return bool(recruitment & _member_roles(session, guild))


def visible_guilds(request: Request):
    if not config.live():
        return data.GUILDS
    person = viewer(request)
    rows = db.list_guilds(with_trials=True)
    if person["superadmin"]:
        return rows
    session = _session(request)
    return [guild for guild in rows if can_access(session, guild)]


def render(request: Request, template: str, status_code: int = 200, **context):
    context.setdefault("viewer", viewer(request))
    context.setdefault("guilds", visible_guilds(request))
    if config.live():
        context.setdefault("today", date.today().isoformat())
    else:
        context.setdefault("today", data.TODAY.isoformat())
    context.setdefault("albion_updated_at", data.ALBION_UPDATED_AT)
    context.setdefault("live", config.live())
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
        if not person["superadmin"] and not can_access(_session(request), guild):
            return None, forbidden(request, "You need a recruitment role in this Discord server to open this page.")
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
    slugs = [g["slug"] for g in visible_guilds(request)]
    if len(slugs) == 1:
        return RedirectResponse(f"/{slugs[0]}/trial", status_code=303)
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
        db.set_approval(slug, "rejected")
        try:
            discord_api.leave_guild(guild["id"])
        except discord_api.DiscordError:
            db.set_last_error(guild["id"], "Could not leave the Discord server")
        db.mark_bot_left(guild["id"])
        reason = (body.get("reason") or "").strip()
        if guild.get("added_by_id"):
            text = f"Ironkeep was not approved for {guild['name']} and has left the server."
            if reason:
                text += f"\n\n{reason}"
            try:
                discord_api.send_dm(guild["added_by_id"], text[:2000])
            except discord_api.DiscordError:
                pass
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
def guild_home(slug: str):
    return RedirectResponse(f"/{slug}/trial", status_code=303)


@app.get("/{slug}/trial", response_class=HTMLResponse)
def trials(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    today = db.guild_today(guild["settings"]).isoformat() if config.live() else None
    return render(request, "trials.html", guild=guild, nav="trials", **({"today": today} if today else {}))


@app.put("/api/{slug}/trials/{trial_id}")
async def save_trial(slug: str, trial_id: int, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return JSONResponse({"error": "forbidden"}, status_code=403)
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
        return JSONResponse({"error": "forbidden"}, status_code=403)
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


@app.post("/api/{slug}/settings")
async def save_settings(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return JSONResponse({"error": "forbidden"}, status_code=403)
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
    return render(request, "settings.html", guild=guild, nav="settings", setup_mode=False)


@app.get("/{slug}/setup", response_class=HTMLResponse)
def setup(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    return render(request, "settings.html", guild=guild, nav="settings", setup_mode=True)
