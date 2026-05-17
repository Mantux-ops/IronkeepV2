"""Resolve the authenticated user from the session."""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from app import repositories
from app.auth.session import get_session_user_id
from app.errors import AuthenticationRequired


def get_current_user(db: sqlite3.Connection, request: Request) -> dict | None:
    user_id = get_session_user_id(request)
    if not user_id:
        return None
    return repositories.get_user_by_id(db, user_id)


def require_current_user(db: sqlite3.Connection, request: Request) -> dict:
    user = get_current_user(db, request)
    if not user:
        raise AuthenticationRequired("Authentication required.")
    return user
