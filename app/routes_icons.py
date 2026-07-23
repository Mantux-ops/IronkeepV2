"""
Optional same-origin icon proxy routes (Phase 12.4, Fase D).

Serves item and spell icons from a disk cache fronting render.albiononline.com.
Only active when ITEM_ICON_PROXY_ENABLED is set; otherwise the endpoints return
404 and the app keeps using direct CDN URLs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.albion import icon_proxy

router = APIRouter(tags=["icons"])

# Cache-Control for successful icon responses: long-lived, immutable-ish.
_CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=604800"


def _serve(kind: str, item_id: str, size: int) -> Response:
    if not icon_proxy.is_enabled():
        raise HTTPException(status_code=404, detail="Icon proxy is disabled.")
    png, err = icon_proxy.get_cached_png(kind, item_id, size)
    if err == "invalid_id":
        raise HTTPException(status_code=400, detail="Invalid icon id.")
    if png is None:
        # Upstream unavailable and nothing cached — let the client fall back.
        raise HTTPException(status_code=502, detail="Icon unavailable.")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": _CACHE_CONTROL})


@router.get("/item-icons")
def item_icon(
    i: Annotated[str, Query(description="Albion item ID")] = "",
    s: Annotated[int, Query(description="Render size (16–217)")] = 128,
) -> Response:
    """Return an item icon PNG from the disk cache / CDN."""
    return _serve("item", i, s)


@router.get("/spell-icons")
def spell_icon(
    i: Annotated[str, Query(description="Spell uniquename or display name")] = "",
    s: Annotated[int, Query(description="Render size (16–217)")] = 40,
) -> Response:
    """Return a spell icon PNG from the disk cache / CDN."""
    return _serve("spell", i, s)
