"""
Discord server-nickname sync + @mention roster test suite.

Feature: members set their Discord server nickname to their in-game Albion name.
A scheduler job reads the guild's members (Server Members Intent) and makes that
nickname the authoritative display name across the workspace. Discord roster
posts @mention members so Discord renders their live server nickname.

Test groups:
  1. rest_client.fetch_guild_members (parse / pagination / bot skip)
  2. Repository: upsert + get_discord_member_nick_for_user
  3. Repository: find_or_create_participant stores/backfills discord_user_id
  4. Use case: sync_discord_member_nicknames_system (update / linked / skip / error)
  5. Use case: discord_oauth_login does not revert a synced nick
  6. Formatter: format_roster renders @mention when discord_user_id present
  7. Scheduler job: sync_discord_member_nicknames
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app import database, repositories
from app.application import use_cases
from app.discord import rest_client
from app.discord.formatters import format_roster
from tests.conftest import make_user, make_workspace

_BOT_ENV = {"DISCORD_BOT_TOKEN": "test-bot-token"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _link_guild(ws_id: str, guild_id: str) -> None:
    with database.transaction() as db:
        repositories.set_workspace_discord_guild_id(db, ws_id, guild_id, _now_iso())


def _norm(uid: str, nickname=None, global_name=None, username=None) -> dict:
    """A normalized member dict as returned by rest_client.fetch_guild_members."""
    return {
        "discord_user_id": uid,
        "nickname": nickname,
        "global_name": global_name,
        "username": username,
    }


class _FakeResponse:
    def __init__(self, *, is_success=True, status_code=200, json_data=None, text=""):
        self.is_success = is_success
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


def _member(uid: str, nick=None, global_name=None, username=None, bot=False) -> dict:
    return {
        "nick": nick,
        "user": {
            "id": uid,
            "global_name": global_name,
            "username": username,
            "bot": bot,
        },
    }


# ---------------------------------------------------------------------------
# 1. rest_client.fetch_guild_members
# ---------------------------------------------------------------------------

class TestFetchGuildMembers:

    def test_parses_and_normalizes(self):
        page = [
            _member("100", nick="Kage", global_name="kage_g", username="kage_u"),
            _member("200", nick=None, global_name="Bob", username="bob99"),
        ]
        with patch.dict(os.environ, _BOT_ENV), \
             patch("app.discord.rest_client.httpx.get",
                   return_value=_FakeResponse(json_data=page)):
            members = rest_client.fetch_guild_members("guild-1")
        assert members == [
            {"discord_user_id": "100", "nickname": "Kage",
             "global_name": "kage_g", "username": "kage_u"},
            {"discord_user_id": "200", "nickname": None,
             "global_name": "Bob", "username": "bob99"},
        ]

    def test_skips_bots(self):
        page = [_member("1", username="RealUser"), _member("2", username="BotUser", bot=True)]
        with patch.dict(os.environ, _BOT_ENV), \
             patch("app.discord.rest_client.httpx.get",
                   return_value=_FakeResponse(json_data=page)):
            members = rest_client.fetch_guild_members("guild-1")
        assert [m["discord_user_id"] for m in members] == ["1"]

    def test_paginates_until_short_page(self):
        # First page is full (page_limit=2) → a second page is requested.
        full = [_member("10", username="a"), _member("30", username="b")]
        short = [_member("40", username="c")]
        calls = []

        def _fake_get(url, **kwargs):
            calls.append(kwargs["params"]["after"])
            return _FakeResponse(json_data=full if len(calls) == 1 else short)

        with patch.dict(os.environ, _BOT_ENV), \
             patch("app.discord.rest_client.httpx.get", side_effect=_fake_get):
            members = rest_client.fetch_guild_members("g", page_limit=2)
        assert [m["discord_user_id"] for m in members] == ["10", "30", "40"]
        # Second call's cursor is the max snowflake from page 1 (integer compare).
        assert calls == ["0", "30"]

    def test_non_2xx_raises(self):
        with patch.dict(os.environ, _BOT_ENV), \
             patch("app.discord.rest_client.httpx.get",
                   return_value=_FakeResponse(is_success=False, status_code=403,
                                              text="Missing Access / intent")):
            with pytest.raises(rest_client.DiscordApiError):
                rest_client.fetch_guild_members("g")


# ---------------------------------------------------------------------------
# 2. Repository: cache upsert + nick lookup
# ---------------------------------------------------------------------------

class TestNickCacheRepo:

    def test_upsert_and_lookup_for_user(self):
        ws = make_workspace(slug="nick-repo-1")
        user = use_cases.discord_oauth_login("discord-nick-1", "GlobalName")
        with database.transaction() as db:
            repositories.upsert_discord_member_nick(
                db, guild_workspace_id=ws["id"], discord_user_id="discord-nick-1",
                nickname="IngameName", global_name="GlobalName", username="uname",
                fetched_at=_now_iso(),
            )
            nick = repositories.get_discord_member_nick_for_user(db, user["id"])
        assert nick == "IngameName"

    def test_lookup_falls_back_to_global_then_username(self):
        ws = make_workspace(slug="nick-repo-2")
        user = use_cases.discord_oauth_login("discord-nick-2", "Xavier")
        with database.transaction() as db:
            repositories.upsert_discord_member_nick(
                db, guild_workspace_id=ws["id"], discord_user_id="discord-nick-2",
                nickname=None, global_name=None, username="only_username",
                fetched_at=_now_iso(),
            )
            nick = repositories.get_discord_member_nick_for_user(db, user["id"])
        assert nick == "only_username"

    def test_lookup_none_when_no_cache(self):
        user = use_cases.discord_oauth_login("discord-nick-3", "NoCache")
        with database.transaction() as db:
            assert repositories.get_discord_member_nick_for_user(db, user["id"]) is None

    def test_upsert_is_idempotent(self):
        ws = make_workspace(slug="nick-repo-4")
        use_cases.discord_oauth_login("discord-nick-4", "Yolanda")
        with database.transaction() as db:
            for nick in ("First", "Second"):
                repositories.upsert_discord_member_nick(
                    db, guild_workspace_id=ws["id"], discord_user_id="discord-nick-4",
                    nickname=nick, global_name=None, username=None,
                    fetched_at=_now_iso(),
                )
            rows = db.execute(
                "SELECT nickname FROM discord_member_cache WHERE discord_user_id = ?",
                ("discord-nick-4",),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["nickname"] == "Second"


# ---------------------------------------------------------------------------
# 3. Repository: participant discord_user_id
# ---------------------------------------------------------------------------

class TestParticipantDiscordId:

    def test_stores_discord_user_id_on_create(self):
        ws = make_workspace(slug="pdid-1")
        with database.transaction() as db:
            p = repositories.find_or_create_participant(
                db, ws["id"], "Kage", discord_user_id="disc-42"
            )
        assert p["discord_user_id"] == "disc-42"

    def test_backfills_existing_participant(self):
        ws = make_workspace(slug="pdid-2")
        with database.transaction() as db:
            repositories.find_or_create_participant(db, ws["id"], "Kage")  # no id
        with database.transaction() as db:
            p = repositories.find_or_create_participant(
                db, ws["id"], "Kage", discord_user_id="disc-99"
            )
        assert p["discord_user_id"] == "disc-99"

    def test_does_not_overwrite_existing_id(self):
        ws = make_workspace(slug="pdid-3")
        with database.transaction() as db:
            repositories.find_or_create_participant(
                db, ws["id"], "Kage", discord_user_id="original"
            )
        with database.transaction() as db:
            p = repositories.find_or_create_participant(
                db, ws["id"], "Kage", discord_user_id="different"
            )
        assert p["discord_user_id"] == "original"


# ---------------------------------------------------------------------------
# 4. Use case: sync_discord_member_nicknames_system
# ---------------------------------------------------------------------------

class TestSyncNicknamesSystem:

    def test_updates_pure_discord_user_display_name(self):
        ws = make_workspace(slug="sync-1")
        _link_guild(ws["id"], "guild-sync-1")
        user = use_cases.discord_oauth_login("disc-sync-1", "OldGlobalName")

        members = [_norm("disc-sync-1", nickname="IngameHero", global_name="OldGlobalName")]
        with patch("app.discord.rest_client.fetch_guild_members", return_value=members):
            result = use_cases.sync_discord_member_nicknames_system(ws["id"])

        assert result["status"] == "ok"
        assert result["names_updated"] == 1
        with database.transaction() as db:
            refreshed = repositories.get_user_by_id(db, user["id"])
        assert refreshed["display_name"] == "IngameHero"

    def test_does_not_update_linked_dev_discord_user(self):
        ws = make_workspace(slug="sync-2")
        _link_guild(ws["id"], "guild-sync-2")
        user = use_cases.discord_oauth_login("disc-sync-2", "KeepThisName")
        # Add a dev identity → user becomes "linked" and must be left alone.
        with database.transaction() as db:
            repositories.insert_user_auth_identity(db, {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "auth_provider": "dev",
                "provider_user_id": "dev-sync-2",
                "created_at": _now_iso(),
            })

        members = [_norm("disc-sync-2", nickname="ShouldNotApply")]
        with patch("app.discord.rest_client.fetch_guild_members", return_value=members):
            result = use_cases.sync_discord_member_nicknames_system(ws["id"])

        assert result["names_updated"] == 0
        with database.transaction() as db:
            refreshed = repositories.get_user_by_id(db, user["id"])
        assert refreshed["display_name"] == "KeepThisName"

    def test_skips_workspace_without_discord_guild(self):
        ws = make_workspace(slug="sync-3")
        result = use_cases.sync_discord_member_nicknames_system(ws["id"])
        assert result["status"] == "skipped:no_discord_guild"

    def test_rest_error_is_non_fatal(self):
        ws = make_workspace(slug="sync-4")
        _link_guild(ws["id"], "guild-sync-4")
        with patch("app.discord.rest_client.fetch_guild_members",
                   side_effect=rest_client.DiscordApiError(403, "intent not enabled")):
            result = use_cases.sync_discord_member_nicknames_system(ws["id"])
        assert result["status"].startswith("error:")

    def test_caches_members_even_without_ironkeep_user(self):
        ws = make_workspace(slug="sync-5")
        _link_guild(ws["id"], "guild-sync-5")
        members = [_norm("stranger-1", nickname="Nobody")]
        with patch("app.discord.rest_client.fetch_guild_members", return_value=members):
            result = use_cases.sync_discord_member_nicknames_system(ws["id"])
        assert result["cached"] == 1
        assert result["names_updated"] == 0


# ---------------------------------------------------------------------------
# 5. Use case: login guard
# ---------------------------------------------------------------------------

def test_login_does_not_revert_synced_nick():
    ws = make_workspace(slug="guard-1")
    _link_guild(ws["id"], "guild-guard-1")
    use_cases.discord_oauth_login("disc-guard-1", "OriginalGlobal")

    members = [_norm("disc-guard-1", nickname="SyncedIngame")]
    with patch("app.discord.rest_client.fetch_guild_members", return_value=members):
        use_cases.sync_discord_member_nicknames_system(ws["id"])

    # A later login with a *different* global name must NOT overwrite the nick.
    relogin = use_cases.discord_oauth_login("disc-guard-1", "ChangedGlobalName")
    assert relogin["display_name"] == "SyncedIngame"


# ---------------------------------------------------------------------------
# 6. Formatter: @mention rendering
# ---------------------------------------------------------------------------

def _slot(sid="slot-1", party=1, idx=1, role="Tank", build="1H Mace") -> dict:
    return {"id": sid, "party_number": party, "slot_index": idx,
            "role": role, "build_name": build}


class TestRosterMentions:

    def test_renders_mention_when_discord_id_present(self):
        op = {"id": "op-1", "title": "ZvZ", "status": "planning"}
        slots = [_slot("slot-1")]
        assignments = [{"slot_id": "slot-1", "display_name": "Kage",
                        "discord_user_id": "555"}]
        result = format_roster(op, slots, assignments)
        value = result["embeds"][0]["fields"][0]["value"]
        assert "<@555>" in value
        assert "**Kage**" not in value

    def test_falls_back_to_bold_name_without_discord_id(self):
        op = {"id": "op-1", "title": "ZvZ", "status": "planning"}
        slots = [_slot("slot-1")]
        assignments = [{"slot_id": "slot-1", "display_name": "Kage",
                        "discord_user_id": None}]
        result = format_roster(op, slots, assignments)
        value = result["embeds"][0]["fields"][0]["value"]
        assert "**Kage**" in value
        assert "<@" not in value

    def test_fill_count_still_correct_with_mentions(self):
        op = {"id": "op-1", "title": "ZvZ", "status": "planning"}
        slots = [_slot("slot-1"), _slot("slot-2", idx=2)]
        assignments = [{"slot_id": "slot-1", "display_name": "A", "discord_user_id": "1"}]
        result = format_roster(op, slots, assignments)
        footer = result["embeds"][0]["footer"]["text"]
        assert "1 / 2 assigned" in footer


# ---------------------------------------------------------------------------
# 7. Scheduler job
# ---------------------------------------------------------------------------

def test_scheduler_job_syncs_stale_workspaces():
    from app.scheduler import jobs

    ws = make_workspace(slug="job-1")
    _link_guild(ws["id"], "guild-job-1")
    use_cases.discord_oauth_login("disc-job-1", "OldName")

    members = [_norm("disc-job-1", nickname="JobIngame")]
    with patch("app.discord.rest_client.fetch_guild_members", return_value=members):
        result = jobs.sync_discord_member_nicknames()

    assert result["workspaces_checked"] >= 1
    assert result["synced"] >= 1
    assert result["names_updated"] >= 1
