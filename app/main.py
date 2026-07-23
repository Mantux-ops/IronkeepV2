"""
IronkeepV2 — FastAPI entry point.

Environment variables
---------------------
IRONKEEP_ENV
    "dev" (default) or "production".  Production enables strict startup
    checks and secure cookie flags.

IRONKEEP_SESSION_SECRET
    Required in production.  Must not equal the dev default.
    Generate with: python -c "import secrets; print(secrets.token_hex(32))"

IRONKEEP_DB_PATH
    Absolute path to the SQLite database file.  Defaults to
    "ironkeep_v2.db" relative to the process working directory (dev only).

DISCORD_BOT_TOKEN
    Required for web-side Discord posting (Post to Discord, Update Roster
    Post).  Missing → warning at startup, posting will fail at runtime.

WEB_BASE_URL
    Base URL of the web app used for Discord embed signup link buttons.
    Missing → warning at startup, link buttons will be omitted from embeds.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env if present (development convenience — no effect in production
# where variables are injected by the host environment).
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # env vars already set in the shell take priority
except ImportError:
    pass

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app import database, startup
from app.routes import router
from app.routes_admin import router as admin_router
from app.routes_catalog import router as catalog_router
from app.routes_icons import router as icons_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_DEV_SECRET = "dev-only-change-me"


def _load_config() -> tuple[str, str, bool]:
    """
    Read and validate startup configuration from environment variables.

    Returns (env, secret, is_production).

    Raises RuntimeError if IRONKEEP_ENV=production and the session secret is
    missing or still set to the insecure dev default.

    Logs warnings (but does not fail) when WEB_BASE_URL or DISCORD_BOT_TOKEN
    are absent — both are optional for local development.
    """
    env = os.getenv("IRONKEEP_ENV", "dev").strip().lower()
    secret = os.getenv("IRONKEEP_SESSION_SECRET", _DEV_SECRET).strip()
    is_production = env == "production"

    if is_production and (not secret or secret == _DEV_SECRET):
        raise RuntimeError(
            "IRONKEEP_SESSION_SECRET must be set to a strong random value in "
            "production.\n"
            "Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_hex(32))"'
        )

    if not os.getenv("WEB_BASE_URL", "").strip():
        logger.warning(
            "WEB_BASE_URL is not set — Discord embed signup links will be omitted."
        )
    if not os.getenv("DISCORD_BOT_TOKEN", "").strip():
        logger.warning(
            "DISCORD_BOT_TOKEN is not set — web-side Discord posting will fail."
        )
    # Discord OAuth is optional in dev; in production users cannot log in without it,
    # but a missing config should not crash the entire app — the login page will show
    # a clear error instead.
    _oauth_vars = ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_OAUTH_REDIRECT_URI"]
    _missing_oauth = [v for v in _oauth_vars if not os.getenv(v, "").strip()]
    if _missing_oauth:
        _msg = f"Discord OAuth vars not set: {', '.join(_missing_oauth)}."
        if is_production:
            logger.warning(
                "%s Users will see a 'Discord OAuth not configured' error on the login page.",
                _msg,
            )
        else:
            logger.info("%s Discord OAuth login will be unavailable; dev login is active.", _msg)

    return env, secret, is_production


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_schema()
    db_path = os.getenv("IRONKEEP_DB_PATH", "ironkeep_v2.db")
    try:
        warnings = startup.validate(db_path, _is_production)
        for w in warnings:
            logger.warning("Startup: %s", w)
    except RuntimeError as exc:
        logger.error("Startup validation failed: %s", exc)
        raise
    yield


_env, _secret, _is_production = _load_config()

app = FastAPI(
    title="IronkeepV2",
    description="Albion Online operational coordination system",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=_secret,
    session_cookie="ironkeep_session",
    same_site="lax",
    https_only=_is_production,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(router)
app.include_router(admin_router)
app.include_router(catalog_router)
app.include_router(icons_router)
