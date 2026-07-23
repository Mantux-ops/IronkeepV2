"""
Phase 12.4 — Icon proxy tests (Fase D).

Covers item id / spell id validation, disk-cache hit/miss, stale-while-error
fallback, and the /item-icons + /spell-icons routes (disabled + enabled).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.albion import icon_proxy
from app.main import app

# A minimal but valid PNG payload (>= 32 bytes, correct magic).
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_valid_item_id():
    assert icon_proxy.is_valid_item_id("T7_MAIN_MACE")
    assert icon_proxy.is_valid_item_id("T8_ARMOR_PLATE_SET1@2")
    assert not icon_proxy.is_valid_item_id("../secret")
    assert not icon_proxy.is_valid_item_id("MAIN_MACE")  # missing tier prefix
    assert not icon_proxy.is_valid_item_id("")


def test_valid_spell_id():
    assert icon_proxy.is_valid_spell_id("DEFENSIVESLAM")
    assert icon_proxy.is_valid_spell_id("Defensive Slam")
    assert not icon_proxy.is_valid_spell_id("a/b")
    assert not icon_proxy.is_valid_spell_id("../x")
    assert not icon_proxy.is_valid_spell_id("")


# ---------------------------------------------------------------------------
# get_cached_png
# ---------------------------------------------------------------------------

def test_invalid_id_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    png, err = icon_proxy.get_cached_png("item", "../bad", 64)
    assert png is None and err == "invalid_id"


def test_cache_miss_then_hit(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def fake_fetch(kind, key, size):
        calls["n"] += 1
        return _PNG

    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", fake_fetch)

    png1, err1 = icon_proxy.get_cached_png("item", "T7_MAIN_MACE", 64)
    assert err1 == "" and png1 == _PNG
    assert calls["n"] == 1

    # Second call is served from disk cache — no extra CDN fetch.
    png2, err2 = icon_proxy.get_cached_png("item", "T7_MAIN_MACE", 64)
    assert err2 == "" and png2 == _PNG
    assert calls["n"] == 1


def test_fetch_failed_when_no_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: None)
    png, err = icon_proxy.get_cached_png("item", "T7_MAIN_MACE", 64)
    assert png is None and err == "fetch_failed"


def test_stale_served_when_cdn_down(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("ITEM_ICON_CACHE_TTL_SECONDS", "60")
    # Prime the cache.
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: _PNG)
    icon_proxy.get_cached_png("item", "T7_MAIN_MACE", 64)
    # Force staleness and make the CDN fail — stale bytes should still return.
    import os, time
    path = icon_proxy._cache_path("item", "T7_MAIN_MACE", 64)
    old = time.time() - 10_000
    os.utime(path, (old, old))
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: None)
    png, err = icon_proxy.get_cached_png("item", "T7_MAIN_MACE", 64)
    assert err == "" and png == _PNG


def test_spell_kind_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: _PNG)
    png, err = icon_proxy.get_cached_png("spell", "DEFENSIVESLAM", 40)
    assert err == "" and png == _PNG


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def test_route_disabled_returns_404(monkeypatch):
    monkeypatch.delenv("ITEM_ICON_PROXY_ENABLED", raising=False)
    client = TestClient(app)
    r = client.get("/item-icons", params={"i": "T7_MAIN_MACE", "s": 64})
    assert r.status_code == 404


def test_route_enabled_serves_png(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_PROXY_ENABLED", "1")
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: _PNG)
    client = TestClient(app)
    r = client.get("/item-icons", params={"i": "T7_MAIN_MACE", "s": 64})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _PNG


def test_route_enabled_invalid_id_400(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_PROXY_ENABLED", "1")
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    client = TestClient(app)
    r = client.get("/item-icons", params={"i": "not-an-id", "s": 64})
    assert r.status_code == 400


def test_route_enabled_upstream_down_502(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_PROXY_ENABLED", "1")
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: None)
    client = TestClient(app)
    r = client.get("/item-icons", params={"i": "T7_MAIN_MACE", "s": 64})
    assert r.status_code == 502


def test_spell_route_enabled_serves_png(monkeypatch, tmp_path):
    monkeypatch.setenv("ITEM_ICON_PROXY_ENABLED", "1")
    monkeypatch.setenv("ITEM_ICON_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(icon_proxy, "_fetch_from_cdn", lambda *a: _PNG)
    client = TestClient(app)
    r = client.get("/spell-icons", params={"i": "Defensive Slam", "s": 40})
    assert r.status_code == 200
    assert r.content == _PNG
