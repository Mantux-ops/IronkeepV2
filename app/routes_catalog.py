"""
HTTP catalog routes — Phase 12.1.

Endpoints
---------
  GET /api/catalog/slots
  GET /api/catalog/items
  GET /api/catalog/items/{item_id}

Rules:
- No business logic here; all filtering is delegated to AlbionItemCatalog.
- 422 for invalid query parameter values (invalid slot, tier, enchantment).
- 404 for an item_id not present in the catalog.
- No session or workspace auth required: Albion item metadata is public data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.albion.item_catalog import (
    ALLOWED_TIERS,
    VALID_SLOTS,
    get_catalog,
)
from app.errors import NotFoundError

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/slots")
def list_slots() -> list[str]:
    """Return all valid equipment slot names in alphabetical order."""
    return sorted(VALID_SLOTS)


@router.get("/items/{item_id}")
def get_item(item_id: str) -> dict:
    """
    Return a single catalog item by its canonical Albion item ID.

    The *item_id* is matched case-insensitively.

    Raises 404 when the item is not present in the T7/T8 catalog.
    """
    cat = get_catalog()
    try:
        return cat.require(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/items")
def list_items(
    slot: Annotated[str | None, Query(description="Equipment slot")] = None,
    tier: Annotated[int | None, Query(description="Base tier (7 or 8)")] = None,
    enchantment: Annotated[int | None, Query(description="Enchantment level (0–3)")] = None,
    is_two_handed: Annotated[bool | None, Query(description="Two-handed weapons only")] = None,
    q: Annotated[str | None, Query(description="Case-insensitive name search")] = None,
) -> list[dict]:
    """
    List catalog items with optional combined filtering.

    All filters are ANDed together.  Omit a parameter to skip that filter.

    Raises 422 for invalid filter values (unknown slot, out-of-range tier or
    enchantment).  Never returns a silent empty list for a programming error
    in the query.
    """
    if slot is not None and slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid slot '{slot}'. "
                f"Must be one of: {sorted(VALID_SLOTS)}"
            ),
        )
    if tier is not None and tier not in ALLOWED_TIERS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid tier {tier}. "
                f"Must be one of: {sorted(ALLOWED_TIERS)}"
            ),
        )
    if enchantment is not None and not (0 <= enchantment <= 3):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid enchantment {enchantment}. "
                "Must be 0, 1, 2, or 3."
            ),
        )

    cat = get_catalog()
    return cat.filter(
        slot=slot,
        tier=tier,
        enchantment=enchantment,
        is_two_handed=is_two_handed,
        q=q or "",
    )
