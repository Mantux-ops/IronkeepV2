"""
Shared pytest fixtures.

isolated_db is autouse=True so every test function gets:
  - a fresh temporary SQLite file
  - schema fully initialised
  - database module configured to point at that file

tmp_path is a pytest built-in that provides a per-test temporary directory
that is automatically cleaned up after the test.
"""

import pytest

from app import database


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db_path = str(tmp_path / "test_ironkeep.db")
    database.configure(db_path)
    database.init_schema()
    yield db_path


# ---------------------------------------------------------------------------
# Convenience builders shared across test modules
# ---------------------------------------------------------------------------

def make_user(display_name="Test Officer"):
    from app.application import use_cases
    return use_cases.dev_login_or_create_user(display_name)


def make_workspace(name="Orbie Gaming", slug="orbie", owner_user_id=None):
    from app.application import use_cases
    if owner_user_id is None:
        owner_user_id = make_user(display_name="Workspace Owner")["id"]
    return use_cases.create_guild_workspace(
        name=name,
        slug=slug,
        owner_user_id=owner_user_id,
    )


def make_operation(workspace_id, title="Saturday ZvZ", op_type="zvz",
                   start="2026-06-07T20:00:00+00:00"):
    from app.application import use_cases
    return use_cases.create_guild_operation(
        guild_workspace_id=workspace_id,
        title=title,
        operation_type=op_type,
        scheduled_start_at=start,
    )


def publish_operation(workspace_id, operation_id):
    from app.application import use_cases
    return use_cases.publish_operation(workspace_id, operation_id)


def make_composition(workspace_id, name="5-Man ZvZ", slots=None):
    from app.application import use_cases
    if slots is None:
        slots = [
            {"party_number": 1, "slot_index": i, "role": r, "build_name": b, "priority": "core"}
            for i, (r, b) in enumerate(
                [
                    ("Tank", "1H Mace"),
                    ("Healer", "Hallowfall"),
                    ("DPS", "Daggers"),
                    ("Support", "Locus"),
                    ("DPS", "Bow"),
                ],
                start=1,
            )
        ]
    return use_cases.create_albion_composition(
        guild_workspace_id=workspace_id,
        name=name,
        description=None,
        slots=slots,
    )
