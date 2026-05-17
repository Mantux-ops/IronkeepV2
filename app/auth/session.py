"""Signed session cookie helpers."""

from __future__ import annotations

from starlette.requests import Request

SESSION_USER_ID_KEY = "user_id"


def get_session_user_id(request: Request) -> str | None:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    if not user_id:
        return None
    return str(user_id)


def set_session_user(request: Request, user_id: str) -> None:
    request.session[SESSION_USER_ID_KEY] = user_id


def clear_session(request: Request) -> None:
    request.session.clear()
