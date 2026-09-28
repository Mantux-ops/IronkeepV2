from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import mock_data as data

BASE_DIR = Path(__file__).parent
VIEW_COOKIE = "ik_view"

app = FastAPI(title="Ironkeep prototype", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def viewer(request: Request):
    if request.cookies.get(VIEW_COOKIE) == "recruiter":
        return {**data.RECRUITER, "superadmin": False, "role": "recruiter"}
    return {**data.SUPERADMIN, "superadmin": True, "role": "superadmin"}


def render(request: Request, template: str, status_code: int = 200, **context):
    context.setdefault("viewer", viewer(request))
    context.setdefault("guilds", data.GUILDS)
    context.setdefault("today", data.TODAY.isoformat())
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def forbidden(request: Request, message: str):
    return render(request, "forbidden.html", status_code=403, message=message, guild=None, nav=None)


def recruiter_guild_slugs():
    return ["dutchchaos"]


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render(request, "landing.html")


@app.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return render(request, "login.html")


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html")


@app.get("/prototype/view/{role}")
def switch_view(role: str, request: Request, next: str = "/"):
    target = next if next.startswith("/") else "/"
    if role == "recruiter" and target.startswith("/admin"):
        target = "/dutchchaos/trial"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(VIEW_COOKIE, "recruiter" if role == "recruiter" else "superadmin", samesite="lax")
    return response


@app.get("/trial")
def trial_redirect(request: Request):
    slugs = [g["slug"] for g in data.GUILDS] if viewer(request)["superadmin"] else recruiter_guild_slugs()
    if len(slugs) == 1:
        return RedirectResponse(f"/{slugs[0]}/trial", status_code=303)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if not viewer(request)["superadmin"]:
        return forbidden(request, "Only the Ironkeep superadmin can open this page.")
    rows = [{**g, **data.guild_summary(g)} for g in data.GUILDS]
    totals = {
        "guilds": len(rows),
        "open": sum(r["open"] for r in rows),
        "attention": sum(r["attention"] for r in rows),
        "errors": sum(1 for e in data.ERRORS if not e["resolved"]),
        "pending": sum(1 for r in rows if r["approval"] == "pending"),
    }
    return render(request, "admin.html", rows=rows, totals=totals, guild=None, nav="admin")


@app.get("/admin/errors", response_class=HTMLResponse)
def admin_errors(request: Request):
    if not viewer(request)["superadmin"]:
        return forbidden(request, "Only the Ironkeep superadmin can open this page.")
    names = {g["slug"]: g for g in data.GUILDS}
    return render(request, "admin_errors.html", errors=data.ERRORS, names=names, guild=None, nav="errors")


@app.get("/admin/data", response_class=HTMLResponse)
def admin_data(request: Request):
    if not viewer(request)["superadmin"]:
        return forbidden(request, "Only the Ironkeep superadmin can open this page.")
    records = []
    for g in data.GUILDS:
        for t in g["trials"]:
            records.append({"guild": g["name"], "slug": g["slug"], **t})
    return render(request, "admin_data.html", records=records, guild=None, nav="data")


def guild_or_404(request: Request, slug: str):
    guild = data.guild_by_slug(slug)
    if guild is None:
        return None, render(request, "forbidden.html", status_code=404,
                            message="There is no Ironkeep environment at this address.", guild=None, nav=None)
    v = viewer(request)
    if not v["superadmin"] and slug not in recruiter_guild_slugs():
        return None, forbidden(request, "You need a recruitment role in this Discord server to open this page.")
    return guild, None


@app.get("/{slug}")
def guild_home(slug: str):
    return RedirectResponse(f"/{slug}/trial", status_code=303)


@app.get("/{slug}/trial", response_class=HTMLResponse)
def trials(slug: str, request: Request):
    guild, error = guild_or_404(request, slug)
    if error:
        return error
    return render(request, "trials.html", guild=guild, nav="trials")


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
