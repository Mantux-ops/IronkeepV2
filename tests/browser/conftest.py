"""
Browser-test conftest.

Overrides the autouse function-scoped `isolated_db` from the parent conftest
with a session-scoped version so one database is shared for the entire browser
test session.

The uvicorn server fixture (live_server) and the workspace fixture
(browser_workspace) both depend on having stable data across the whole
session — they would break if the database were wiped between every test.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app import database

# ── Session-scoped database ─────────────────────────────────────────────────

@pytest.fixture(scope="session")
def isolated_db(tmp_path_factory):
    """Session-scoped override of the autouse parent fixture."""
    db_path = str(tmp_path_factory.mktemp("browser_db") / "browser_test.db")
    database.configure(db_path)
    database.init_schema()
    return db_path


# ── Free-port helper ────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Live uvicorn server ─────────────────────────────────────────────────────

class _ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        from app.main import app
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.port   = port

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


@pytest.fixture(scope="session")
def live_server(isolated_db):
    """Spin up a real uvicorn server for Playwright tests."""
    port   = _free_port()
    thread = _ServerThread(port)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{base_url}/health")
            break
        except Exception:
            time.sleep(0.25)

    yield base_url

    thread.stop()
    thread.join(timeout=3)


# ── Shared workspace ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_workspace(isolated_db, live_server):
    """One workspace shared across all browser tests."""
    import uuid
    from tests.conftest import make_user, make_workspace

    owner = make_user("BrowserSessionOwner")
    slug  = f"browser-{uuid.uuid4().hex[:8]}"
    ws    = make_workspace(
        name=f"Browser Test WS {slug}",
        slug=slug,
        owner_user_id=owner["id"],
    )
    return {
        "base_url":    live_server,
        "slug":        ws["slug"],
        "owner_name":  owner["display_name"],
    }
