"""
Tests for signup_intents.source column.

Rules:
- Default source is 'web' for all web-originated signups.
- submit_signup_intent accepts source='discord' for future bot use.
- Source is stored and returned; it has no effect on domain rules.
"""

from app.application import use_cases
from tests.conftest import make_operation, make_workspace, publish_operation


def _open_operation():
    ws = make_workspace()
    op = make_operation(ws["id"])
    publish_operation(ws["id"], op["id"])
    return ws, op


def test_signup_default_source_is_web():
    ws, op = _open_operation()
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="PlayerOne",
        preferred_role="Healer",
    )
    assert signup["source"] == "web"


def test_signup_source_discord():
    ws, op = _open_operation()
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="PlayerOne",
        preferred_role="Healer",
        source="discord",
    )
    assert signup["source"] == "discord"


def test_signup_source_does_not_affect_domain_rules():
    """Source is audit-only: duplicate signups are still rejected regardless of source."""
    ws, op = _open_operation()
    use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="PlayerOne",
        preferred_role="Healer",
        source="web",
    )
    from app.errors import ConflictError
    import pytest
    with pytest.raises(ConflictError):
        use_cases.submit_signup_intent(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            display_name="PlayerOne",
            preferred_role="DPS",
            source="discord",
        )


def test_multiple_signups_can_have_different_sources():
    ws, op = _open_operation()
    s1 = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="PlayerOne",
        preferred_role="Healer",
        source="web",
    )
    s2 = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="PlayerTwo",
        preferred_role="Tank",
        source="discord",
    )
    assert s1["source"] == "web"
    assert s2["source"] == "discord"
