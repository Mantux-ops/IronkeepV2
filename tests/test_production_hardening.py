"""
Production readiness hardening tests.

All tests call _load_config() or database helpers directly with monkeypatched
environment variables.  No app restart or module reimport is required because:
  - _load_config() reads os.environ at call time (not at import time).
  - database.configure(None) re-reads IRONKEEP_DB_PATH at call time.

Banner tests temporarily patch templates.env.globals["ironkeep_env"] and
restore it after the assertion, keeping other tests unaffected.

Covers:
    1.  Dev env: weak secret allowed, no RuntimeError.
    2.  Production env: weak secret raises RuntimeError.
    3.  Production env: empty secret raises RuntimeError.
    4.  Production env: strong secret accepted.
    5.  is_production=False in dev.
    6.  is_production=True in production.
    7.  IRONKEEP_DB_PATH env var overrides configure(None).
    8.  Explicit configure(path) still works (existing tests unaffected).
    9.  WAL mode enabled after init_schema.
    10. Dev banner present when ironkeep_env != "production".
    11. Dev banner absent when ironkeep_env == "production".
    12. WEB_BASE_URL missing logs a warning.
    13. DISCORD_BOT_TOKEN missing logs a warning.
    14. WEB_BASE_URL present suppresses that warning.
    15. DISCORD_BOT_TOKEN present suppresses that warning.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import _load_config
from app.routes import templates
from app.main import app


# ---------------------------------------------------------------------------
# _load_config() — session secret and env detection
# ---------------------------------------------------------------------------

def test_dev_env_allows_weak_secret(monkeypatch):
    monkeypatch.setenv("IRONKEEP_ENV", "dev")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.setenv("WEB_BASE_URL", "http://localhost")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    env, secret, is_production = _load_config()
    assert env == "dev"
    assert not is_production
    assert secret == "dev-only-change-me"


def test_production_rejects_default_secret(monkeypatch):
    monkeypatch.setenv("IRONKEEP_ENV", "production")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    with pytest.raises(RuntimeError, match="IRONKEEP_SESSION_SECRET"):
        _load_config()


def test_production_rejects_empty_secret(monkeypatch):
    monkeypatch.setenv("IRONKEEP_ENV", "production")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "")
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    with pytest.raises(RuntimeError, match="IRONKEEP_SESSION_SECRET"):
        _load_config()


def test_production_accepts_strong_secret(monkeypatch):
    monkeypatch.setenv("IRONKEEP_ENV", "production")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "a" * 64)
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    env, secret, is_production = _load_config()
    assert is_production
    assert env == "production"
    assert secret == "a" * 64


def test_is_production_false_in_dev(monkeypatch):
    monkeypatch.setenv("IRONKEEP_ENV", "dev")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.setenv("WEB_BASE_URL", "http://localhost")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    _, _, is_production = _load_config()
    assert is_production is False


def test_is_production_true_in_production(monkeypatch):
    monkeypatch.setenv("IRONKEEP_ENV", "production")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "b" * 64)
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    _, _, is_production = _load_config()
    assert is_production is True


# ---------------------------------------------------------------------------
# database path env override
# ---------------------------------------------------------------------------

def test_configure_none_reads_env(monkeypatch, tmp_path):
    """configure(None) should re-read IRONKEEP_DB_PATH from the environment."""
    custom = str(tmp_path / "env_override.db")
    monkeypatch.setenv("IRONKEEP_DB_PATH", custom)
    database.configure(None)
    assert database._DB_PATH == custom
    # Restore to a usable test path so isolated_db cleanup doesn't break
    database.configure(str(tmp_path / "test_ironkeep.db"))


def test_configure_explicit_path_still_works(tmp_path):
    """Explicit configure(path) must still override as before."""
    explicit = str(tmp_path / "explicit.db")
    database.configure(explicit)
    assert database._DB_PATH == explicit


# ---------------------------------------------------------------------------
# WAL mode
# ---------------------------------------------------------------------------

def test_wal_mode_enabled_after_init_schema():
    """
    init_schema() must enable WAL journal mode.

    The isolated_db fixture (autouse) already called configure(tmp) +
    init_schema(), so database._DB_PATH is the test DB with WAL enabled.
    """
    conn = sqlite3.connect(database._DB_PATH)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode == "wal"


# ---------------------------------------------------------------------------
# Dev banner
# ---------------------------------------------------------------------------

def _get_login_page(env_value: str) -> str:
    """Request /login with ironkeep_env set to env_value in template globals."""
    original = templates.env.globals.get("ironkeep_env", "dev")
    templates.env.globals["ironkeep_env"] = env_value
    try:
        client = TestClient(app)
        resp = client.get("/login")
        return resp.text
    finally:
        templates.env.globals["ironkeep_env"] = original


def test_dev_banner_present_when_env_is_dev():
    html = _get_login_page("dev")
    # Check for the rendered element, not just the CSS class name in <style>
    assert 'class="dev-banner"' in html
    assert "Dev mode active" in html


def test_dev_banner_present_when_env_is_staging():
    """Any non-production env should show the banner."""
    html = _get_login_page("staging")
    assert 'class="dev-banner"' in html


def test_dev_banner_absent_when_env_is_production():
    html = _get_login_page("production")
    assert 'class="dev-banner"' not in html


# ---------------------------------------------------------------------------
# Startup warnings — WEB_BASE_URL and DISCORD_BOT_TOKEN
# ---------------------------------------------------------------------------

def test_missing_web_base_url_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("IRONKEEP_ENV", "dev")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _load_config()
    assert "WEB_BASE_URL" in caplog.text


def test_missing_discord_bot_token_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("IRONKEEP_ENV", "dev")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.setenv("WEB_BASE_URL", "http://localhost")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _load_config()
    assert "DISCORD_BOT_TOKEN" in caplog.text


def test_no_web_base_url_warning_when_set(monkeypatch, caplog):
    monkeypatch.setenv("IRONKEEP_ENV", "dev")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _load_config()
    assert "WEB_BASE_URL" not in caplog.text


def test_no_discord_token_warning_when_set(monkeypatch, caplog):
    monkeypatch.setenv("IRONKEEP_ENV", "dev")
    monkeypatch.setenv("IRONKEEP_SESSION_SECRET", "dev-only-change-me")
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "real-token")
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _load_config()
    assert "DISCORD_BOT_TOKEN" not in caplog.text
