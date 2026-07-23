"""
Optional on-disk cache/proxy for Albion Render API icons (items and spells).

Disabled by default. When enabled via the ITEM_ICON_PROXY_ENABLED environment
variable, item/spell icons are served same-origin from /item-icons and
/spell-icons, backed by a disk cache that fronts render.albiononline.com. This
gives faster, more robust icon loading (same-origin HTTP/2, long browser cache)
and shields the app from transient CDN failures via stale-while-error fallback.

Environment
-----------
ITEM_ICON_PROXY_ENABLED        "1"/"true"/"yes"/"on" to enable (default: off)
ITEM_ICON_CACHE_DIR            cache directory (default: data/icon_cache)
ITEM_ICON_CACHE_TTL_SECONDS    refresh interval in seconds (default: 604800 = 7d)

Ported from IronkeepV1 services/item_icon_cache.py.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_ITEM_RENDER_BASE = "https://render.albiononline.com/v1/item"
_SPELL_RENDER_BASE = "https://render.albiononline.com/v1/spell"

# Albion item IDs: T4_MAIN_MACE, T6_ARMOR_PLATE_SET1@2, etc.
_ITEM_ID_RE = re.compile(r"^T\d+_[A-Za-z0-9_]+(?:@[0-9]+)?$")
# Spell keys: uniquenames (UPPERCASE) or display names (letters/digits/space).
_SPELL_ID_RE = re.compile(r"^[A-Za-z0-9 _'()./-]{1,120}$")

_DEFAULT_CACHE_DIR = "data/icon_cache"
_DEFAULT_TTL = 7 * 86400


# ---------------------------------------------------------------------------
# Configuration (read fresh so tests can monkeypatch the environment)
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    val = (os.environ.get("ITEM_ICON_PROXY_ENABLED", "") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _cache_dir() -> Path:
    return Path(os.environ.get("ITEM_ICON_CACHE_DIR", _DEFAULT_CACHE_DIR))


def _ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("ITEM_ICON_CACHE_TTL_SECONDS", _DEFAULT_TTL)))
    except (TypeError, ValueError):
        return _DEFAULT_TTL


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _safe(key: str) -> bool:
    return not (".." in key or "/" in key or "\\" in key)


def is_valid_item_id(item_id: str) -> bool:
    if not item_id or len(item_id) > 160 or not _safe(item_id):
        return False
    return bool(_ITEM_ID_RE.match(item_id))


def is_valid_spell_id(spell_id: str) -> bool:
    if not spell_id or not _safe(spell_id):
        return False
    return bool(_SPELL_ID_RE.match(spell_id))


# ---------------------------------------------------------------------------
# Same-origin URL builders (used by the catalogs when the proxy is enabled)
# ---------------------------------------------------------------------------

def item_proxy_url(item_id: str, size: int) -> str:
    q = urllib.parse.urlencode({"i": item_id.strip().upper(), "s": size})
    return f"/item-icons?{q}"


def spell_proxy_url(spell_key: str, size: int) -> str:
    q = urllib.parse.urlencode({"i": spell_key.strip(), "s": size})
    return f"/spell-icons?{q}"


# ---------------------------------------------------------------------------
# Cache internals
# ---------------------------------------------------------------------------

def _cache_path(kind: str, key: str, render_size: int) -> Path:
    digest = hashlib.sha256(f"{kind}\0{key}\0{render_size}".encode()).hexdigest()
    return _cache_dir() / f"{digest}.png"


def _cdn_url(kind: str, key: str, render_size: int) -> str:
    base = _ITEM_RENDER_BASE if kind == "item" else _SPELL_RENDER_BASE
    path_id = urllib.parse.quote(key.strip(), safe="")
    return f"{base}/{path_id}.png?size={render_size}"


def _fetch_from_cdn(kind: str, key: str, render_size: int) -> bytes | None:
    url = _cdn_url(kind, key, render_size)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Ironkeep-IconProxy/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
            if len(data) < 32 or not data.startswith(b"\x89PNG"):
                log.warning("Unexpected icon payload for %s/%s", kind, key)
                return None
            return data
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning("CDN icon fetch failed %s: %s", url, e)
        return None


def _atomic_write_png(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".png", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_cached_png(kind: str, key: str, render_size: int) -> tuple[bytes | None, str]:
    """Return ``(png_bytes, error_code)``. ``error_code`` is empty on success.

    * ``invalid_id``   — bad item/spell id
    * ``fetch_failed`` — no CDN response and no stale cached file
    """
    if kind == "item":
        if not is_valid_item_id(key):
            return None, "invalid_id"
    elif kind == "spell":
        if not is_valid_spell_id(key):
            return None, "invalid_id"
    else:
        return None, "invalid_id"

    try:
        render_size = int(render_size)
    except (TypeError, ValueError):
        render_size = 128
    render_size = max(16, min(217, render_size))

    path = _cache_path(kind, key, render_size)
    ttl = _ttl_seconds()
    now = time.time()

    stale_bytes: bytes | None = None
    if path.is_file():
        try:
            age = now - path.stat().st_mtime
            data = path.read_bytes()
            if len(data) >= 32 and data.startswith(b"\x89PNG"):
                if age < ttl:
                    return data, ""
                stale_bytes = data
        except OSError:
            pass

    fresh = _fetch_from_cdn(kind, key, render_size)
    if fresh is not None:
        try:
            _atomic_write_png(path, fresh)
        except Exception:
            log.warning("Could not write icon cache %s", path, exc_info=True)
        return fresh, ""

    if stale_bytes is not None:
        return stale_bytes, ""

    return None, "fetch_failed"
