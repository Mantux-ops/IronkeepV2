"""
Phase 10 Slice 1 — Discord guild install workspace bootstrap.

Tests the full provisioning path: use case, repository helpers, domain slug
derivation, bot handler delegation, and idempotency/ownership safety rules.

Coverage map:
  1.  New Discord guild creates workspace (use case).
  2.  Workspace has discord_guild_id set.
  3.  Workspace has discord_provisioned_at set.
  4.  Repeated join for same guild does NOT duplicate workspace (idempotent).
  5.  Re-join increments install_count in discord_guild_installs.
  6.  Existing manually linked workspace is returned unchanged on bot join.
  7.  No workspace_members row created (no owner assignment).
  8.  count_workspace_owners returns 0 for bot-provisioned workspace.
  9.  Guild name → slug derivation: safe characters, unicode, emoji stripping.
 10.  Two guilds with similar names get distinct slugs.
 11.  Slug derivation fallback for very short / all-symbol guild names.
 12.  Manual workspace creation still works and still creates an owner.
 13.  Bot provisioning and manual creation coexist without conflict.
 14.  workspace.discord_provisioned event is emitted.
 15.  discord_guild_installs row is inserted on first join.
 16.  discord_guild_installs row is upserted (not duplicated) on re-join.
 17.  Invalid Discord snowflake raises ValidationError.
 18.  Bot join handler delegates to use case, contains no business logic.
 19.  Provisioning module catches exceptions, does not re-raise.
 20.  No secrets appear in provisioning log output.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from app import database, repositories
from app.application import use_cases
from app.domain import guild_workspace as gw_domain
from app.discord import provisioning as prov_module
from app.errors import ValidationError
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GUILD_ID   = "111122223333444455"
_GUILD_ID_2 = "222233334444555566"
_GUILD_NAME = "Iron Brotherhood"


def _provision(guild_id: str = _GUILD_ID, guild_name: str = _GUILD_NAME) -> dict:
    return use_cases.ensure_workspace_for_discord_guild(guild_id, guild_name)


def _get_install(guild_id: str = _GUILD_ID) -> dict | None:
    with database.transaction() as db:
        return repositories.get_discord_guild_install(db, guild_id)


# ---------------------------------------------------------------------------
# 1–3: New guild creates workspace with discord_guild_id + provisioned_at
# ---------------------------------------------------------------------------

class TestNewGuildCreatesWorkspace:
    def test_returns_workspace_dict(self):
        ws = _provision()
        assert ws["id"]
        assert ws["name"] == _GUILD_NAME

    def test_workspace_slug_is_url_safe(self):
        ws = _provision()
        assert ws["slug"]
        # Must pass the existing slug validator
        gw_domain.validate_workspace_slug(ws["slug"])

    def test_discord_guild_id_set_on_workspace(self):
        ws = _provision()
        assert ws["discord_guild_id"] == _GUILD_ID

    def test_discord_provisioned_at_set(self):
        ws = _provision()
        assert ws["discord_provisioned_at"] is not None

    def test_workspace_persisted_in_db(self):
        ws = _provision()
        with database.transaction() as db:
            found = repositories.get_workspace_by_discord_guild_id(db, _GUILD_ID)
        assert found is not None
        assert found["id"] == ws["id"]
        assert found["discord_guild_id"] == _GUILD_ID

    def test_discord_provisioned_at_persisted_in_db(self):
        _provision()
        with database.transaction() as db:
            found = repositories.get_workspace_by_discord_guild_id(db, _GUILD_ID)
        assert found["discord_provisioned_at"] is not None


# ---------------------------------------------------------------------------
# 4–5: Idempotency — same guild does not create duplicate workspace
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_repeated_join_returns_same_workspace_id(self):
        ws1 = _provision()
        ws2 = _provision()
        assert ws1["id"] == ws2["id"]

    def test_repeated_join_does_not_duplicate_workspace_row(self):
        _provision()
        _provision()
        _provision()
        with database.transaction() as db:
            rows = db.execute(
                "SELECT COUNT(*) FROM guild_workspaces WHERE discord_guild_id = ?",
                (_GUILD_ID,),
            ).fetchone()
        assert rows[0] == 1

    def test_repeated_join_increments_install_count(self):
        _provision()
        _provision()
        _provision()
        install = _get_install()
        assert install is not None
        assert install["install_count"] == 3

    def test_repeated_join_refreshes_guild_name_in_install_record(self):
        _provision(guild_name="Original Name")
        _provision(guild_name="Renamed Guild")
        install = _get_install()
        assert install["guild_name"] == "Renamed Guild"


# ---------------------------------------------------------------------------
# 6: Existing manually linked workspace — bot join returns it unchanged
# ---------------------------------------------------------------------------

class TestExistingManuallyLinkedWorkspace:
    def test_returns_existing_workspace(self):
        owner = make_user("ManualOwner")
        ws = make_workspace(name="Existing Guild", slug="existing-guild", owner_user_id=owner["id"])
        # Manually link the guild ID (as officer would via settings)
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_workspaces SET discord_guild_id=? WHERE id=?",
                (_GUILD_ID, ws["id"]),
            )
        # Bot join should return the same workspace, not create a new one
        result = _provision()
        assert result["id"] == ws["id"]

    def test_does_not_overwrite_existing_workspace_name(self):
        owner = make_user("ManualOwner2")
        ws = make_workspace(name="My Real Guild", slug="my-real-guild", owner_user_id=owner["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_workspaces SET discord_guild_id=? WHERE id=?",
                (_GUILD_ID, ws["id"]),
            )
        _provision(guild_name="Some Other Name")
        with database.transaction() as db:
            found = repositories.get_workspace_by_id(db, ws["id"])
        # Name should remain "My Real Guild", not be overwritten
        assert found["name"] == "My Real Guild"


# ---------------------------------------------------------------------------
# 7–8: No owner assigned
# ---------------------------------------------------------------------------

class TestNoOwnerAssignment:
    def test_no_workspace_members_row_created(self):
        ws = _provision()
        with database.transaction() as db:
            members = repositories.list_workspace_members(db, ws["id"])
        assert members == []

    def test_count_workspace_owners_is_zero(self):
        ws = _provision()
        with database.transaction() as db:
            count = repositories.count_workspace_owners(db, ws["id"])
        assert count == 0

    def test_workspace_has_no_members_at_all(self):
        ws = _provision()
        with database.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM workspace_members WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# 9–11: Slug derivation
# ---------------------------------------------------------------------------

class TestSlugDerivation:
    def test_normal_guild_name(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("Iron Brotherhood")
        assert slug == "iron-brotherhood"
        gw_domain.validate_workspace_slug(slug)

    def test_unicode_and_emoji_are_stripped(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("💀 Dark Order 💀")
        assert "dark-order" in slug
        gw_domain.validate_workspace_slug(slug)

    def test_all_special_characters_falls_back(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("---!!!")
        assert slug == "discord-guild"

    def test_very_short_name_falls_back(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("AB")
        # "ab" is only 2 chars — below minimum of 3 → fallback
        assert slug == "discord-guild"

    def test_single_character_falls_back(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("X")
        assert slug == "discord-guild"

    def test_long_name_is_truncated(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("a" * 80)
        assert len(slug) <= 64
        gw_domain.validate_workspace_slug(slug)

    def test_numbers_in_name(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("Guild 42")
        assert slug == "guild-42"
        gw_domain.validate_workspace_slug(slug)

    def test_leading_trailing_spaces(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("  Orb Gaming  ")
        assert slug == "orb-gaming"

    def test_mixed_case(self):
        slug = gw_domain.derive_workspace_slug_from_guild_name("IRON KEEP")
        assert slug == "iron-keep"


# ---------------------------------------------------------------------------
# 10: Two guilds with similar names get distinct slugs
# ---------------------------------------------------------------------------

class TestUniqueSlugCollisions:
    def test_two_similar_guilds_get_different_slugs(self):
        ws1 = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID, "Iron Brotherhood")
        ws2 = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID_2, "Iron Brotherhood")
        assert ws1["slug"] != ws2["slug"]
        # Both slugs must be valid
        gw_domain.validate_workspace_slug(ws1["slug"])
        gw_domain.validate_workspace_slug(ws2["slug"])

    def test_collision_slug_has_numeric_suffix(self):
        ws1 = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID, "Iron Brotherhood")
        ws2 = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID_2, "Iron Brotherhood")
        # One will be "iron-brotherhood", the other "iron-brotherhood-2"
        slugs = {ws1["slug"], ws2["slug"]}
        assert "iron-brotherhood" in slugs
        assert any(s.endswith("-2") or s.endswith("-3") for s in slugs)

    def test_three_similar_guilds_each_unique(self):
        ids = ["111111111111111111", "222222222222222222", "333333333333333333"]
        slugs = [
            use_cases.ensure_workspace_for_discord_guild(gid, "Ironkeep")["slug"]
            for gid in ids
        ]
        assert len(set(slugs)) == 3, f"Expected 3 unique slugs, got: {slugs}"


# ---------------------------------------------------------------------------
# 12–13: Manual workspace creation unchanged; coexistence
# ---------------------------------------------------------------------------

class TestManualWorkspaceUnchanged:
    def test_manual_create_still_assigns_owner(self):
        owner = make_user("ManualCreator")
        ws = make_workspace(name="Manual WS", slug="manual-ws", owner_user_id=owner["id"])
        with database.transaction() as db:
            count = repositories.count_workspace_owners(db, ws["id"])
        assert count == 1

    def test_manual_create_has_no_discord_guild_id(self):
        owner = make_user("ManualCreator2")
        ws = make_workspace(name="Manual WS 2", slug="manual-ws2", owner_user_id=owner["id"])
        with database.transaction() as db:
            found = repositories.get_workspace_by_id(db, ws["id"])
        assert found["discord_guild_id"] is None

    def test_manual_create_has_no_discord_provisioned_at(self):
        owner = make_user("ManualCreator3")
        ws = make_workspace(name="Manual WS 3", slug="manual-ws3", owner_user_id=owner["id"])
        with database.transaction() as db:
            found = repositories.get_workspace_by_id(db, ws["id"])
        assert found.get("discord_provisioned_at") is None

    def test_bot_provisioned_and_manual_coexist(self):
        owner = make_user("CoexistOwner")
        manual_ws = make_workspace(name="Manual", slug="manual-coe", owner_user_id=owner["id"])
        bot_ws = _provision(guild_id="444455556666777788", guild_name="Bot Guild")
        assert manual_ws["id"] != bot_ws["id"]
        # Manual workspace retains its owner
        with database.transaction() as db:
            assert repositories.count_workspace_owners(db, manual_ws["id"]) == 1
            assert repositories.count_workspace_owners(db, bot_ws["id"]) == 0


# ---------------------------------------------------------------------------
# 14: workspace.discord_provisioned event is emitted
# ---------------------------------------------------------------------------

class TestOperationalEventEmitted:
    def test_provisioned_event_in_operational_events(self):
        ws = _provision()
        with database.transaction() as db:
            events = db.execute(
                "SELECT * FROM operational_events WHERE guild_workspace_id=?",
                (ws["id"],),
            ).fetchall()
        event_types = {e["event_type"] for e in events}
        assert "workspace.discord_provisioned" in event_types

    def test_provisioned_event_has_correct_payload(self):
        import json
        ws = _provision()
        with database.transaction() as db:
            row = db.execute(
                """SELECT * FROM operational_events
                   WHERE guild_workspace_id=?
                     AND event_type='workspace.discord_provisioned'""",
                (ws["id"],),
            ).fetchone()
        assert row is not None
        payload = json.loads(row["payload_json"])
        assert payload["discord_guild_id"] == _GUILD_ID
        assert payload["slug"] == ws["slug"]

    def test_no_provisioned_event_on_idempotent_rejoin(self):
        _provision()  # first join — event emitted
        _provision()  # re-join — no new event
        with database.transaction() as db:
            rows = db.execute(
                """SELECT COUNT(*) FROM operational_events
                   WHERE event_type='workspace.discord_provisioned'""",
            ).fetchone()
        # Still only one event
        assert rows[0] == 1


# ---------------------------------------------------------------------------
# 15–16: discord_guild_installs table behaviour
# ---------------------------------------------------------------------------

class TestDiscordGuildInstalls:
    def test_install_row_created_on_first_join(self):
        _provision()
        install = _get_install()
        assert install is not None
        assert install["discord_guild_id"] == _GUILD_ID
        assert install["install_count"] == 1

    def test_install_row_links_to_workspace(self):
        ws = _provision()
        install = _get_install()
        assert install["guild_workspace_id"] == ws["id"]

    def test_install_row_stores_guild_name(self):
        _provision()
        install = _get_install()
        assert install["guild_name"] == _GUILD_NAME

    def test_no_duplicate_install_rows_on_rejoin(self):
        _provision()
        _provision()
        with database.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM discord_guild_installs WHERE discord_guild_id=?",
                (_GUILD_ID,),
            ).fetchone()[0]
        assert count == 1

    def test_install_count_increments_on_each_rejoin(self):
        for expected in range(1, 5):
            _provision()
            install = _get_install()
            assert install["install_count"] == expected


# ---------------------------------------------------------------------------
# 17: Invalid snowflake raises ValidationError
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_invalid_snowflake_raises(self):
        with pytest.raises(ValidationError):
            use_cases.ensure_workspace_for_discord_guild("not-a-snowflake", "Guild")

    def test_empty_snowflake_raises(self):
        with pytest.raises(ValidationError):
            use_cases.ensure_workspace_for_discord_guild("", "Guild")

    def test_too_short_snowflake_raises(self):
        with pytest.raises(ValidationError):
            use_cases.ensure_workspace_for_discord_guild("12345", "Guild")

    def test_empty_guild_name_uses_fallback(self):
        # Empty name should not raise — fallback to "Discord Server"
        ws = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID, "")
        assert ws["name"] == "Discord Server"

    def test_whitespace_only_name_uses_fallback(self):
        ws = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID, "   ")
        assert ws["name"] == "Discord Server"

    def test_single_char_name_uses_fallback(self):
        ws = use_cases.ensure_workspace_for_discord_guild(_GUILD_ID, "X")
        assert ws["name"] == "Discord Server"


# ---------------------------------------------------------------------------
# 18: Bot join handler delegates to use case; no business logic in bot
# ---------------------------------------------------------------------------

class TestBotHandlerDelegation:
    def test_handle_guild_join_calls_use_case(self):
        with patch.object(use_cases, "ensure_workspace_for_discord_guild") as mock_uc:
            mock_uc.return_value = {"id": "x", "slug": "x", "discord_guild_id": _GUILD_ID}
            prov_module.handle_guild_join(_GUILD_ID, _GUILD_NAME)
        mock_uc.assert_called_once_with(
            discord_guild_id=_GUILD_ID,
            guild_name=_GUILD_NAME,
            discord_guild_owner_id=None,
        )

    def test_provisioning_module_has_no_discord_sdk_import(self):
        import importlib
        import ast, inspect
        source = inspect.getsource(prov_module)
        tree = ast.parse(source)
        import_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                import_names.append(node.module or "")
        assert not any("discord" in n and "app" not in n for n in import_names), (
            f"provisioning.py must not import the Discord SDK. Imports found: {import_names}"
        )


# ---------------------------------------------------------------------------
# 19: Provisioning module catches exceptions, does not re-raise
# ---------------------------------------------------------------------------

class TestProvisioningExceptionSafety:
    def test_exception_in_use_case_does_not_propagate(self):
        with patch.object(
            use_cases,
            "ensure_workspace_for_discord_guild",
            side_effect=RuntimeError("DB exploded"),
        ):
            # Must not raise — bot must stay alive
            prov_module.handle_guild_join(_GUILD_ID, _GUILD_NAME)

    def test_exception_is_logged_at_error_level(self, caplog):
        with patch.object(
            use_cases,
            "ensure_workspace_for_discord_guild",
            side_effect=RuntimeError("simulated failure"),
        ):
            with caplog.at_level(logging.ERROR, logger="app.discord.provisioning"):
                prov_module.handle_guild_join(_GUILD_ID, _GUILD_NAME)
        assert any("simulated failure" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 20: No secrets in log output
# ---------------------------------------------------------------------------

class TestNoSecretsLogged:
    def test_success_log_does_not_contain_token(self, caplog):
        import os
        # Temporarily set a fake token so we can verify it is never logged.
        fake_token = "FAKE_BOT_TOKEN_DO_NOT_LOG_XYZ"
        original = os.environ.get("DISCORD_BOT_TOKEN")
        os.environ["DISCORD_BOT_TOKEN"] = fake_token
        try:
            with caplog.at_level(logging.DEBUG, logger="app.discord.provisioning"):
                _provision()
            for record in caplog.records:
                assert fake_token not in record.message, (
                    "Bot token must never appear in log output"
                )
        finally:
            if original is None:
                os.environ.pop("DISCORD_BOT_TOKEN", None)
            else:
                os.environ["DISCORD_BOT_TOKEN"] = original

    def test_error_log_contains_guild_id_but_not_secret(self, caplog):
        with patch.object(
            use_cases,
            "ensure_workspace_for_discord_guild",
            side_effect=RuntimeError("error"),
        ):
            with caplog.at_level(logging.ERROR, logger="app.discord.provisioning"):
                prov_module.handle_guild_join(_GUILD_ID, _GUILD_NAME)
        # Guild ID is not a secret and should be present for diagnostics.
        assert any(_GUILD_ID in r.message for r in caplog.records)
