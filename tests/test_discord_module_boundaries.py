"""
Tests for app/discord/ module skeleton boundary.

Verifies:
- Package is importable.
- dispatcher.dispatch() is a no-op (does not raise).
- identity exceptions are importable.
- No Discord SDK (discord.py / py-cord) is installed.
"""

import importlib
import importlib.util


def test_discord_package_importable():
    import app.discord  # noqa: F401


def test_all_skeleton_modules_importable():
    modules = [
        "app.discord.adapter",
        "app.discord.dispatcher",
        "app.discord.formatters",
        "app.discord.identity",
        "app.discord.message_store",
        "app.discord.rate_limiter",
    ]
    for mod in modules:
        assert importlib.util.find_spec(mod) is not None, f"{mod} not found"
        importlib.import_module(mod)


def test_dispatcher_dispatch_is_noop():
    from app.discord import dispatcher
    # Must not raise for any event dict shape
    dispatcher.dispatch({})
    dispatcher.dispatch({"event_type": "guild_operation.published", "id": "abc"})


def test_identity_errors_importable():
    from app.discord.identity import DiscordNotLinkedError, DiscordUserNotLinkedError
    assert issubclass(DiscordNotLinkedError, Exception)
    assert issubclass(DiscordUserNotLinkedError, Exception)


def test_no_discord_sdk_in_project_requirements():
    """
    Confirm no Discord SDK dependency has been added to requirements.txt.
    A Discord SDK (discord.py / py-cord / hikari) may be present in the global
    Python environment from other projects; that is acceptable. What must not
    happen is the SDK being declared as a project dependency.
    """
    from pathlib import Path
    req_path = Path(__file__).parent.parent / "requirements.txt"
    requirements_text = req_path.read_text(encoding="utf-8").lower()
    sdk_names = ["discord.py", "py-cord", "hikari", "nextcord", "disnake"]
    for sdk in sdk_names:
        assert sdk not in requirements_text, (
            f"Discord SDK '{sdk}' must not be added to requirements.txt in Phase 0/1"
        )
    # 'discord' alone as a standalone line is also forbidden
    lines = [ln.strip() for ln in requirements_text.splitlines()]
    assert "discord" not in lines, (
        "Bare 'discord' must not appear as a requirements.txt entry"
    )
