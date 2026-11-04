"""Companion authorization, kept separate from the website Discord login.

The website already signs recruiters in. That flow is reused only to decide
whether the signed-in person may mint a one-time link for one guild. The
companion then exchanges the link for its own credential. Nothing here changes
the Discord redirect URI, client id, client secret, scopes, or the website
session.

Reused as they already work:

- ``config.live`` and ``config.DB_PATH``
- ``guild_or_404`` in ``main``, which applies the website ``ik_session`` cookie,
  the superadmin check, the "person who added the bot" check, and the
  recruitment-role check in ``can_access``
- the guild row (id and slug) the website already stored

Not used for a companion credential:

- ``/login``, ``/auth/callback``, and ``/logout``
- the Discord authorize URL, ``config.redirect_uri``, and ``config.invite_url``
- ``discord_api.exchange_code``, ``identify``, and ``refresh_access_token``
- the ``sessions`` table and the ``ik_oauth``, ``ik_next``, and ``ik_session`` cookies
- the attendance guild key

Companion rows do not store Discord access or refresh tokens, so a companion
credential cannot be turned back into a website session. The website cookie is
not read by ``/api/companion/*``.

The routes stay absent unless ``IRONKEEP_COMPANION_AUTH`` is set on the
process. No deployment file sets it. The desktop companion still uploads with
the attendance guild key; it does not call these routes.
"""

import re
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import config, db

PAIRING_SECONDS = 300
SESSION_SECONDS = 7 * 86400
TOKEN_PREFIX = "ikc."
_LINK = re.compile(r"^/api/[^/]+/companion-link$")
_COMPANION_PATHS = {
    "/api/companion/exchange",
    "/api/companion/session",
    "/api/companion/logout",
}
_LOCK = threading.Lock()
router = APIRouter()


def _active():
    return config.companion_auth_enabled() and config.live() and bool(config.DB_PATH)


def _disabled():
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def hidden(request: Request):
    """Make the new routes look missing while companion auth is off."""
    if _active():
        return None
    path = request.url.path
    if path in _COMPANION_PATHS or _LINK.match(path):
        return _disabled()
    return None


def _stamp(moment=None):
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S")


def _ensure_tables(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companion_pairings (
            code TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            username TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            guild_slug TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companion_sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            username TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            guild_slug TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )"""
    )


def _bearer(request: Request):
    header = request.headers.get("authorization", "")
    if len(header) < 7 or header[:7].lower() != "bearer ":
        return ""
    token = header[7:].strip()
    if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return ""
    return token


def _public(row):
    return {
        "user_id": row["user_id"],
        "name": row["name"],
        "username": row["username"],
        "guild_id": row["guild_id"],
        "guild_slug": row["guild_slug"],
    }


def _session(token, consume=False):
    if not token:
        return None
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.commit()
            row = conn.execute("SELECT * FROM companion_sessions WHERE token = ?", (token,)).fetchone()
            if row is None or not secrets.compare_digest(str(row["token"]), token):
                return None
            expired = row["expires_at"] <= _stamp()
            if consume or expired:
                conn.execute("DELETE FROM companion_sessions WHERE token = ?", (token,))
                conn.commit()
            if expired:
                return None
            return dict(row)
        finally:
            conn.close()


@router.post("/api/{slug}/companion-link")
def companion_link(slug: str, request: Request):
    """Website route. The ik_session cookie is checked the same way as settings."""
    if not _active():
        return _disabled()
    from .main import guild_or_404

    guild, error = guild_or_404(request, slug)
    if error or not config.live():
        return JSONResponse({"error": "forbidden"}, status_code=403)
    session = db.get_session(request.cookies.get("ik_session"))
    if session is None:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    code = secrets.token_urlsafe(32)
    expires = _stamp(datetime.now(timezone.utc) + timedelta(seconds=PAIRING_SECONDS))
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute(
                """INSERT INTO companion_pairings
                   (code, user_id, name, username, guild_id, guild_slug, expires_at, used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    code,
                    str(session["user_id"]),
                    session["name"],
                    session.get("username") or "",
                    str(guild["id"]),
                    guild["slug"],
                    expires,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return {"code": code, "expires_in": PAIRING_SECONDS, "guild": guild["slug"]}


@router.post("/api/companion/exchange")
async def exchange(request: Request):
    if not _active():
        return _disabled()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "This link could not be read."}, status_code=400)
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str) or not code.strip() or len(code) > 200:
        return JSONResponse({"ok": False, "error": "This link could not be read."}, status_code=400)
    code = code.strip()
    now = datetime.now(timezone.utc)
    stamp = _stamp(now)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires = _stamp(now + timedelta(seconds=SESSION_SECONDS))
    with _LOCK:
        conn = db.connect()
        started = False
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            started = True
            row = conn.execute(
                "SELECT * FROM companion_pairings WHERE code = ? AND used = 0 AND expires_at > ?",
                (code, stamp),
            ).fetchone()
            if row is None or not secrets.compare_digest(str(row["code"]), code):
                conn.rollback()
                started = False
                public = None
            else:
                updated = conn.execute(
                    "UPDATE companion_pairings SET used = 1 WHERE code = ? AND used = 0",
                    (code,),
                )
                if updated.rowcount != 1:
                    conn.rollback()
                    started = False
                    public = None
                else:
                    conn.execute(
                        """INSERT INTO companion_sessions
                           (token, user_id, name, username, guild_id, guild_slug, created_at, expires_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            token,
                            row["user_id"],
                            row["name"],
                            row["username"],
                            row["guild_id"],
                            row["guild_slug"],
                            stamp,
                            expires,
                        ),
                    )
                    conn.commit()
                    started = False
                    public = _public(row)
        except Exception:
            if started:
                conn.rollback()
            raise
        finally:
            conn.close()
    if public is None:
        return JSONResponse({"ok": False, "error": "This link has expired."}, status_code=401)
    return {"ok": True, "token": token, "expires_in": SESSION_SECONDS, **public}


@router.get("/api/companion/session")
def companion_session(request: Request):
    if not _active():
        return _disabled()
    row = _session(_bearer(request))
    if row is None:
        return JSONResponse({"ok": False, "error": "Companion login is required."}, status_code=401)
    return {"ok": True, **_public(row)}


@router.post("/api/companion/logout")
def companion_logout(request: Request):
    if not _active():
        return _disabled()
    row = _session(_bearer(request), consume=True)
    if row is None:
        return JSONResponse({"ok": False, "error": "Companion login is required."}, status_code=401)
    return {"ok": True}
