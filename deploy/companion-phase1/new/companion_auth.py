"""Companion authorization, separate from the website Discord login.

The website login at /login, the callback at /auth/callback, the logout at
/logout, the Discord redirect URI, the client id, the client secret, and the
scopes are not used here and are not changed.

A person who is already signed in to the website can approve a desktop
Companion in the browser. That approval is a different authorization layer:

- The Companion creates a PKCE S256 challenge and a state value.
- The browser opens /companion/connect with an exact loopback redirect URI.
- The page never approves on GET. The person submits a form that must carry
  the CSRF token for that state.
- The server redirects the one-time code to the loopback address only.
- The Companion exchanges the code and the PKCE verifier for a short-lived
  access token and a rotating refresh token.
- Only hashes of those tokens are stored.

Connect permission is ``companion_roles`` on the guild. It defaults to an empty
list. Recruitment roles, the person who added the bot, and World of Warcraft
poster roles do not grant this. The one administrator exception is the
Ironkeep superadmin (``config.SUPERADMIN_ID``). Token refresh and guild
lookup check the role again, through the bot's guild-member lookup, because
the Companion does not keep the user's Discord token.

The routes stay missing unless ``IRONKEEP_COMPANION_AUTH`` is set. No
deployment file sets it. Attendance upload is not part of this module.
"""

import base64
import hashlib
import re
import secrets
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import config, db, discord_api

ACCESS_SECONDS = 600
REFRESH_SECONDS = 30 * 86400
REQUEST_SECONDS = 600
CODE_SECONDS = 60
REUSE_GRACE_SECONDS = 2
CLIENT_ID = "ironkeep-companion"
ACCESS_PREFIX = "ika."
REFRESH_PREFIX = "ikr."
CODE_PREFIX = "ikn."
_STATE_RE = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PATH_RE = re.compile(r"/[A-Za-z0-9._~/-]{0,200}")
_EXACT = {
    "/companion/connect",
    "/api/companion/token",
    "/api/companion/revoke",
    "/api/companion/logout",
    "/api/companion/guilds",
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
    if path in _EXACT:
        return _disabled()
    return None


def _stamp(moment=None):
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_stamp(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_token(prefix):
    return prefix + secrets.token_urlsafe(32)


def pkce_s256(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def valid_loopback(uri):
    """Accept only an exact http loopback URI with an explicit port and no query."""
    if not isinstance(uri, str) or len(uri) > 300 or any(ord(char) < 33 or ord(char) > 126 for char in uri):
        return False
    try:
        parsed = urllib.parse.urlsplit(uri)
    except ValueError:
        return False
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    host = parsed.hostname
    if host not in ("127.0.0.1", "localhost"):
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is None or not 1 <= port <= 65535:
        return False
    if parsed.netloc != f"{host}:{port}":
        return False
    if _PATH_RE.fullmatch(parsed.path) is None or ".." in parsed.path.split("/"):
        return False
    return uri == f"http://{parsed.netloc}{parsed.path}"


def _ensure_tables(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companion_connect (
            state_hash TEXT PRIMARY KEY,
            code_challenge TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            csrf_hash TEXT NOT NULL,
            user_id TEXT,
            guild_id TEXT,
            guild_slug TEXT,
            code_hash TEXT,
            family_id TEXT,
            name TEXT,
            username TEXT,
            expires_at TEXT NOT NULL,
            code_expires_at TEXT,
            used INTEGER NOT NULL DEFAULT 0,
            used_at TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS companion_connect_code
           ON companion_connect(code_hash) WHERE code_hash IS NOT NULL"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companion_credentials (
            token_hash TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            username TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            guild_slug TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            rotated_at TEXT,
            revoked_at TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS companion_credentials_family ON companion_credentials(family_id)"
    )


class LookupFailed(Exception):
    """Discord did not answer the role check. The saved session stays as it is."""


def _member_roles(guild_id, user_id):
    try:
        member = discord_api.member_as_bot(guild_id, user_id)
    except discord_api.DiscordError as error:
        if error.status in (401, 403, 404):
            return set()
        raise LookupFailed from error
    return {str(role) for role in (member or {}).get("roles", [])}


def connect_allowed(user_id, guild):
    """Whether this person may connect the Companion for this guild right now.

    True or False is a definite answer. None means Discord could not be reached.
    The superadmin is the only exception to companion_roles.
    """
    if guild is None or guild.get("approval") == "rejected":
        return False
    if str(user_id) == str(config.SUPERADMIN_ID):
        return True
    wanted = set(db.companion_role_ids(guild.get("settings")))
    if not wanted:
        return False
    try:
        roles = _member_roles(guild["id"], user_id)
    except LookupFailed:
        return None
    return bool(wanted & roles)


def permitted_guilds(user_id):
    return [guild for guild in db.list_guilds() if connect_allowed(user_id, guild) is True]


def _website_session(request):
    from .main import SESSION_COOKIE

    return db.get_session(request.cookies.get(SESSION_COOKIE))


def _error_page(request, message, status_code):
    from .main import render

    return render(
        request,
        "companion_connect.html",
        status_code=status_code,
        error=message,
        guilds=[],
        state="",
        csrf="",
    )


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _json_error(message, status_code):
    return _no_store(JSONResponse({"ok": False, "error": message}, status_code=status_code))


def _form(request, raw):
    if len(raw) > 4096:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parsed = urllib.parse.parse_qs(text, keep_blank_values=False, strict_parsing=False)
    return {key: values[0] for key, values in parsed.items() if values}


@router.get("/companion/connect")
def connect_page(request: Request):
    if not _active():
        return _disabled()
    params = request.query_params
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    challenge = params.get("code_challenge", "")
    method = params.get("code_challenge_method", "")
    response_type = params.get("response_type", "")
    client_id = params.get("client_id", "")
    if (
        client_id != CLIENT_ID
        or response_type != "code"
        or method != "S256"
        or not _STATE_RE.fullmatch(state or "")
        or not _CHALLENGE_RE.fullmatch(challenge or "")
        or not valid_loopback(redirect_uri)
    ):
        return _error_page(request, "This Companion connection request is not valid.", 400)
    session = _website_session(request)
    if session is None:
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse("/login?next=" + urllib.parse.quote(target), status_code=303)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT used, code_hash FROM companion_connect WHERE state_hash = ?",
                (_hash(state),),
            ).fetchone()
            if current is not None and (current["used"] or current["code_hash"]):
                conn.rollback()
                return _error_page(request, "This Companion connection was already used.", 400)
            if current is None:
                conn.execute(
                    """INSERT INTO companion_connect
                       (state_hash, code_challenge, redirect_uri, csrf_hash, expires_at, used, created_at)
                       VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (
                        _hash(state),
                        challenge,
                        redirect_uri,
                        _hash(csrf),
                        _stamp(now + timedelta(seconds=REQUEST_SECONDS)),
                        _stamp(now),
                    ),
                )
            else:
                conn.execute(
                    """UPDATE companion_connect
                       SET code_challenge = ?, redirect_uri = ?, csrf_hash = ?, expires_at = ?
                       WHERE state_hash = ? AND used = 0 AND code_hash IS NULL""",
                    (
                        challenge,
                        redirect_uri,
                        _hash(csrf),
                        _stamp(now + timedelta(seconds=REQUEST_SECONDS)),
                        _hash(state),
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    from .main import render, _secure

    response = render(
        request,
        "companion_connect.html",
        error="",
        guilds=permitted_guilds(session["user_id"]),
        state=state,
        csrf=csrf,
    )
    response.set_cookie(
        "ik_companion_csrf",
        csrf,
        max_age=REQUEST_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure(),
        path="/companion/connect",
    )
    return _no_store(response)


@router.post("/companion/connect")
async def connect_submit(request: Request):
    if not _active():
        return _disabled()
    form = _form(request, await request.body())
    if form is None:
        return _error_page(request, "This Companion connection request is not valid.", 400)
    state = form.get("state", "")
    csrf = form.get("csrf", "")
    decision = form.get("decision", "")
    slug = form.get("guild", "")
    cookie = request.cookies.get("ik_companion_csrf", "")
    session = _website_session(request)
    if (
        session is None
        or decision not in ("allow", "deny")
        or not _STATE_RE.fullmatch(state or "")
        or not csrf
        or not cookie
        or not secrets.compare_digest(cookie, csrf)
    ):
        return _error_page(request, "This Companion connection request is not valid.", 403)
    guild = None
    if decision == "allow":
        guild = db.guild_by_slug(slug)
        allowed = connect_allowed(session["user_id"], guild)
        if allowed is None:
            return _error_page(request, "Discord could not be reached. Try the connection again.", 503)
        if not allowed:
            return _error_page(request, "You cannot connect the Companion for that guild.", 403)
    now = datetime.now(timezone.utc)
    stamp = _stamp(now)
    with _LOCK:
        conn = db.connect()
        started = False
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            started = True
            row = conn.execute(
                "SELECT * FROM companion_connect WHERE state_hash = ?",
                (_hash(state),),
            ).fetchone()
            if (
                row is None
                or row["used"]
                or row["code_hash"]
                or row["expires_at"] <= stamp
                or not secrets.compare_digest(row["csrf_hash"], _hash(csrf))
                or not valid_loopback(row["redirect_uri"])
            ):
                conn.rollback()
                return _error_page(request, "This Companion connection request is not valid.", 403)
            redirect_uri = row["redirect_uri"]
            if decision == "deny":
                conn.execute(
                    "UPDATE companion_connect SET used = 1, used_at = ? WHERE state_hash = ? AND used = 0 AND code_hash IS NULL",
                    (stamp, _hash(state)),
                )
                conn.commit()
                started = False
                denied = True
                code = None
            else:
                code = _new_token(CODE_PREFIX)
                updated = conn.execute(
                    """UPDATE companion_connect
                       SET user_id = ?, name = ?, username = ?, guild_id = ?, guild_slug = ?,
                           code_hash = ?, code_expires_at = ?
                       WHERE state_hash = ? AND used = 0 AND code_hash IS NULL""",
                    (
                        str(session["user_id"]),
                        session["name"],
                        session.get("username") or "",
                        str(guild["id"]),
                        guild["slug"],
                        _hash(code),
                        _stamp(now + timedelta(seconds=CODE_SECONDS)),
                        _hash(state),
                    ),
                )
                if updated.rowcount != 1:
                    conn.rollback()
                    return _error_page(request, "This Companion connection was already used.", 403)
                conn.commit()
                started = False
                denied = False
        except Exception:
            if started:
                conn.rollback()
            raise
        finally:
            conn.close()
    if denied:
        return _no_store(_redirect(redirect_uri, {"error": "access_denied", "state": state}))
    return _no_store(_redirect(redirect_uri, {"code": code, "state": state}))


def _redirect(uri, params):
    return RedirectResponse(uri + "?" + urllib.parse.urlencode(params), status_code=303)


def _revoke_family(conn, family_id, stamp):
    if not family_id:
        return
    conn.execute(
        "UPDATE companion_credentials SET revoked_at = ? WHERE family_id = ? AND revoked_at IS NULL",
        (stamp, family_id),
    )


def _issue(conn, row, stamp, now, family_id=None):
    family_id = family_id or secrets.token_urlsafe(18)
    access = _new_token(ACCESS_PREFIX)
    refresh = _new_token(REFRESH_PREFIX)
    conn.execute(
        """INSERT INTO companion_credentials
           (token_hash, family_id, kind, user_id, name, username, guild_id, guild_slug, created_at, expires_at)
           VALUES (?, ?, 'access', ?, ?, ?, ?, ?, ?, ?)""",
        (
            _hash(access),
            family_id,
            row["user_id"],
            row["name"],
            row["username"],
            row["guild_id"],
            row["guild_slug"],
            stamp,
            _stamp(now + timedelta(seconds=ACCESS_SECONDS)),
        ),
    )
    conn.execute(
        """INSERT INTO companion_credentials
           (token_hash, family_id, kind, user_id, name, username, guild_id, guild_slug, created_at, expires_at)
           VALUES (?, ?, 'refresh', ?, ?, ?, ?, ?, ?, ?)""",
        (
            _hash(refresh),
            family_id,
            row["user_id"],
            row["name"],
            row["username"],
            row["guild_id"],
            row["guild_slug"],
            stamp,
            _stamp(now + timedelta(seconds=REFRESH_SECONDS)),
        ),
    )
    return family_id, access, refresh


@router.post("/api/companion/token")
async def token(request: Request):
    if not _active():
        return _disabled()
    try:
        body = await request.json()
    except Exception:
        return _json_error("This Companion token request could not be read.", 400)
    if not isinstance(body, dict):
        return _json_error("This Companion token request could not be read.", 400)
    grant = body.get("grant_type")
    if grant == "authorization_code":
        return _exchange(body)
    if grant == "refresh_token":
        return _refresh(body)
    return _json_error("This Companion token request could not be read.", 400)


def _exchange(body):
    code = body.get("code")
    verifier = body.get("code_verifier")
    redirect_uri = body.get("redirect_uri")
    if not isinstance(code, str) or not code.startswith(CODE_PREFIX) or len(code) > 200:
        return _json_error("This Companion connection was refused.", 401)
    if not isinstance(verifier, str) or not _VERIFIER_RE.fullmatch(verifier) or not valid_loopback(redirect_uri):
        return _consume_failed(code)
    now = datetime.now(timezone.utc)
    stamp = _stamp(now)
    with _LOCK:
        conn = db.connect()
        started = False
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            started = True
            row = conn.execute(
                "SELECT * FROM companion_connect WHERE code_hash = ?",
                (_hash(code),),
            ).fetchone()
            if row is None or not secrets.compare_digest(str(row["code_hash"]), _hash(code)):
                conn.rollback()
                return _json_error("This Companion connection was refused.", 401)
            if row["used"]:
                if row["family_id"] and row["used_at"] and (now - _parse_stamp(row["used_at"])).total_seconds() > REUSE_GRACE_SECONDS:
                    _revoke_family(conn, row["family_id"], stamp)
                    conn.commit()
                else:
                    conn.rollback()
                return _json_error("This Companion connection was refused.", 401)
            challenge_ok = secrets.compare_digest(row["code_challenge"], pkce_s256(verifier))
            mismatch = (
                row["code_expires_at"] is None
                or row["code_expires_at"] <= stamp
                or row["redirect_uri"] != redirect_uri
                or not challenge_ok
            )
            if mismatch:
                conn.execute(
                    "UPDATE companion_connect SET used = 1, used_at = ? WHERE code_hash = ? AND used = 0",
                    (stamp, _hash(code)),
                )
                conn.commit()
                return _json_error("This Companion connection was refused.", 401)
            material = {
                "user_id": row["user_id"],
                "name": row["name"] or "Member",
                "username": row["username"] or "",
                "guild_id": row["guild_id"],
                "guild_slug": row["guild_slug"],
            }
            conn.rollback()
            started = False
        except Exception:
            if started:
                conn.rollback()
            raise
        finally:
            conn.close()
    guild = db.guild_by_slug(material["guild_slug"])
    same_guild = guild is not None and str(guild["id"]) == str(material["guild_id"])
    allowed = connect_allowed(material["user_id"], guild) if same_guild else False
    if allowed is None:
        return _json_error("Discord could not be reached. Try the connection again.", 503)
    if not allowed:
        _mark_code_used(code, stamp)
        return _json_error("You cannot connect the Companion for that guild.", 403)
    with _LOCK:
        conn = db.connect()
        started = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            started = True
            family_id, access, refresh = _issue(conn, material, stamp, now)
            updated = conn.execute(
                "UPDATE companion_connect SET used = 1, used_at = ?, family_id = ? WHERE code_hash = ? AND used = 0",
                (stamp, family_id, _hash(code)),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return _json_error("This Companion connection was refused.", 401)
            conn.commit()
            started = False
        except Exception:
            if started:
                conn.rollback()
            raise
        finally:
            conn.close()
    return _token_body(access, refresh, material)


def _mark_code_used(code, stamp):
    with _LOCK:
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE companion_connect SET used = 1, used_at = ? WHERE code_hash = ? AND used = 0",
                (stamp, _hash(code)),
            )
            conn.commit()
        finally:
            conn.close()


def _consume_failed(code):
    """A recognized code with a malformed verifier or redirect cannot be retried."""
    if not isinstance(code, str) or not code.startswith(CODE_PREFIX):
        return _json_error("This Companion connection was refused.", 401)
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.execute(
                "UPDATE companion_connect SET used = 1, used_at = ? WHERE code_hash = ? AND used = 0",
                (_stamp(), _hash(code)),
            )
            conn.commit()
        finally:
            conn.close()
    return _json_error("This Companion connection was refused.", 401)


def _token_body(access, refresh, material):
    return _no_store(
        JSONResponse(
            {
                "ok": True,
                "token_type": "Bearer",
                "access_token": access,
                "refresh_token": refresh,
                "expires_in": ACCESS_SECONDS,
                "refresh_expires_in": REFRESH_SECONDS,
                "guild_id": material["guild_id"],
                "guild_slug": material["guild_slug"],
            }
        )
    )


def _end_family(family_id):
    if not family_id:
        return
    stamp = _stamp()
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            _revoke_family(conn, family_id, stamp)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _refresh(body):
    token = body.get("refresh_token")
    if not isinstance(token, str) or not token.startswith(REFRESH_PREFIX) or len(token) > 200:
        return _json_error("Companion login is required.", 401)
    now = datetime.now(timezone.utc)
    stamp = _stamp(now)
    with _LOCK:
        conn = db.connect()
        started = False
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            started = True
            row = conn.execute(
                "SELECT * FROM companion_credentials WHERE token_hash = ? AND kind = 'refresh'",
                (_hash(token),),
            ).fetchone()
            if row is None or not secrets.compare_digest(str(row["token_hash"]), _hash(token)):
                conn.rollback()
                return _json_error("Companion login is required.", 401)
            if row["revoked_at"]:
                _revoke_family(conn, row["family_id"], stamp)
                conn.commit()
                return _json_error("Companion login is required.", 401)
            if row["rotated_at"]:
                age = (now - _parse_stamp(row["rotated_at"])).total_seconds()
                if age <= REUSE_GRACE_SECONDS:
                    conn.rollback()
                    return _json_error("Companion login is required.", 401)
                _revoke_family(conn, row["family_id"], stamp)
                conn.commit()
                return _json_error("Companion login is required.", 401)
            if row["expires_at"] <= stamp:
                conn.rollback()
                return _json_error("Companion login is required.", 401)
            material = {
                "user_id": row["user_id"],
                "name": row["name"],
                "username": row["username"],
                "guild_id": row["guild_id"],
                "guild_slug": row["guild_slug"],
            }
            family_id = row["family_id"]
            conn.rollback()
            started = False
        except Exception:
            if started:
                conn.rollback()
            raise
        finally:
            conn.close()
    guild = db.guild_by_id(material["guild_id"])
    same_guild = guild is not None and str(guild["id"]) == str(material["guild_id"])
    allowed = connect_allowed(material["user_id"], guild) if same_guild else False
    if allowed is None:
        return _json_error("Discord could not be reached. Try again.", 503)
    if not allowed:
        _end_family(family_id)
        return _json_error("You cannot connect the Companion for that guild.", 403)
    now = datetime.now(timezone.utc)
    stamp = _stamp(now)
    with _LOCK:
        conn = db.connect()
        started = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            started = True
            rotated = conn.execute(
                """UPDATE companion_credentials SET rotated_at = ?
                   WHERE token_hash = ? AND kind = 'refresh' AND rotated_at IS NULL AND revoked_at IS NULL""",
                (stamp, _hash(token)),
            )
            if rotated.rowcount != 1:
                current = conn.execute(
                    "SELECT * FROM companion_credentials WHERE token_hash = ? AND kind = 'refresh'",
                    (_hash(token),),
                ).fetchone()
                if current is not None and secrets.compare_digest(str(current["token_hash"]), _hash(token)):
                    if current["revoked_at"]:
                        _revoke_family(conn, current["family_id"], stamp)
                        conn.commit()
                        return _json_error("Companion login is required.", 401)
                    if current["rotated_at"]:
                        age = (now - _parse_stamp(current["rotated_at"])).total_seconds()
                        if age > REUSE_GRACE_SECONDS:
                            _revoke_family(conn, current["family_id"], stamp)
                            conn.commit()
                            return _json_error("Companion login is required.", 401)
                conn.rollback()
                return _json_error("Companion login is required.", 401)
            access_pair = _issue(conn, material, stamp, now, family_id)
            access, refresh = access_pair[1], access_pair[2]
            conn.commit()
            started = False
        except Exception:
            if started:
                conn.rollback()
            raise
        finally:
            conn.close()
    return _token_body(access, refresh, material)


def _credential(token, kind):
    if not token or not token.startswith(ACCESS_PREFIX if kind == "access" else REFRESH_PREFIX):
        return None
    now = _stamp()
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.commit()
            row = conn.execute(
                "SELECT * FROM companion_credentials WHERE token_hash = ? AND kind = ?",
                (_hash(token), kind),
            ).fetchone()
            if row is None or not secrets.compare_digest(str(row["token_hash"]), _hash(token)):
                return None
            if row["revoked_at"] or row["expires_at"] <= now:
                return None
            if kind == "refresh" and row["rotated_at"]:
                return None
            return dict(row)
        finally:
            conn.close()


def _bearer(request, prefix):
    header = request.headers.get("authorization", "")
    if len(header) < 7 or header[:7].lower() != "bearer ":
        return ""
    token = header[7:].strip()
    if not token.startswith(prefix) or len(token) > 200:
        return ""
    return token


def _revoke_token(raw):
    if not isinstance(raw, str) or len(raw) > 200:
        return False
    kind = "access" if raw.startswith(ACCESS_PREFIX) else "refresh" if raw.startswith(REFRESH_PREFIX) else ""
    if not kind:
        return False
    stamp = _stamp()
    with _LOCK:
        conn = db.connect()
        try:
            _ensure_tables(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT family_id, token_hash FROM companion_credentials WHERE token_hash = ? AND kind = ?",
                (_hash(raw), kind),
            ).fetchone()
            if row is None or not secrets.compare_digest(str(row["token_hash"]), _hash(raw)):
                conn.rollback()
                return False
            _revoke_family(conn, row["family_id"], stamp)
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@router.post("/api/companion/revoke")
async def revoke(request: Request):
    if not _active():
        return _disabled()
    raw = _bearer(request, ACCESS_PREFIX) or _bearer(request, REFRESH_PREFIX)
    if not raw:
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            raw = body.get("token")
    if not _revoke_token(raw):
        return _json_error("Companion login is required.", 401)
    return _no_store(JSONResponse({"ok": True}))


@router.post("/api/companion/logout")
def companion_logout(request: Request):
    if not _active():
        return _disabled()
    if not _revoke_token(_bearer(request, ACCESS_PREFIX)):
        return _json_error("Companion login is required.", 401)
    return _no_store(JSONResponse({"ok": True}))


@router.get("/api/companion/guilds")
def guilds(request: Request):
    if not _active():
        return _disabled()
    row = _credential(_bearer(request, ACCESS_PREFIX), "access")
    if row is None:
        return _json_error("Companion login is required.", 401)
    guild = db.guild_by_id(row["guild_id"])
    same_guild = guild is not None and str(guild["id"]) == str(row["guild_id"])
    allowed = connect_allowed(row["user_id"], guild) if same_guild else False
    if allowed is None:
        return _json_error("Discord could not be reached. Try again.", 503)
    if not allowed:
        _end_family(row["family_id"])
        return _json_error("You cannot connect the Companion for that guild.", 403)
    return _no_store(JSONResponse({"ok": True, "guilds": [{"id": guild["id"], "slug": guild["slug"], "name": guild["name"]}]}))
