"""
Tests for the roster role picker on a Discord announcement.

Covers the whole slice:
- roster_choices: collapsing slots to distinct role/build/weapon, stable keys
- formatters: the select row, the thread notice, the build DM
- use_cases.record_role_choice: signup preference created, changed, guarded
- use_cases.deliver_role_choice_notifications: thread + DM, and their failures
- adapter: routing a select interaction, and the follow-up instruction
- rest_client: thread creation/posting and DM channel opening

Discord itself is never contacted: rest_client functions are monkeypatched, in
line with the rest of the Discord test suite.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app import database, repositories
from app.application import use_cases
from app.discord import adapter, formatters, rest_client
from app.domain import roster_choices
from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
)

_GUILD_ID        = "900011112222333344"
_CHANNEL_ID      = "900055556666777788"
_MESSAGE_ID      = "900099990000111122"
_DISCORD_USER_ID = "900012345678901234"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slot(role, build_name, weapon_name=None, party=1, index=1, **extra) -> dict:
    return {
        "role":         role,
        "build_name":   build_name,
        "weapon_name":  weapon_name,
        "party_number": party,
        "slot_index":   index,
        **extra,
    }


# ---------------------------------------------------------------------------
# 1. Domain — collapsing a roster into pickable choices
# ---------------------------------------------------------------------------

class TestRoleChoices:
    def test_repeated_loadout_collapses_to_one_choice(self):
        slots = [
            _slot("DPS", "Fire", "Great Fire Staff", index=i)
            for i in range(1, 6)
        ]
        assert len(roster_choices.build_role_choices(slots)) == 1

    def test_same_role_with_different_weapon_stays_separate(self):
        choices = roster_choices.build_role_choices([
            _slot("DPS", "Fire", "Great Fire Staff", index=1),
            _slot("DPS", "Frost", "Great Frost Staff", index=2),
        ])
        assert len(choices) == 2

    def test_roster_order_is_preserved(self):
        choices = roster_choices.build_role_choices([
            _slot("Tank", "Mace", "Heron Spear", index=1),
            _slot("Healer", "Holy", "Fallen Staff", index=2),
        ])
        assert [c["role"] for c in choices] == ["Tank", "Healer"]

    def test_slot_without_role_is_skipped(self):
        choices = roster_choices.build_role_choices([
            _slot("", "Mace", "Heron Spear", index=1),
            _slot("Tank", "Mace", "Heron Spear", index=2),
        ])
        assert [c["role"] for c in choices] == ["Tank"]

    def test_key_is_stable_across_calls(self):
        first  = roster_choices.choice_key("Tank", "Mace", "Heron Spear")
        second = roster_choices.choice_key("Tank", "Mace", "Heron Spear")
        assert first == second

    def test_key_does_not_depend_on_position(self):
        """A digest must survive the roster being reordered or extended.

        This is the whole reason the picker stores a digest rather than an index:
        the message keeps its options until an officer re-posts.
        """
        target = _slot("Healer", "Holy", "Fallen Staff", index=2)
        before = roster_choices.build_role_choices([
            _slot("Tank", "Mace", "Heron Spear", index=1), target,
        ])
        after = roster_choices.build_role_choices([
            target, _slot("Tank", "Mace", "Heron Spear", index=1),
        ])
        healer_before = next(c for c in before if c["role"] == "Healer")
        healer_after  = next(c for c in after  if c["role"] == "Healer")
        assert healer_before["key"] == healer_after["key"]

    def test_field_boundaries_cannot_collide(self):
        """"Tan"+"kMace" must not digest the same as "Tank"+"Mace"."""
        assert roster_choices.choice_key("Tank", "Mace", "") != \
               roster_choices.choice_key("Tan", "kMace", "")

    def test_find_role_choice_resolves_a_key(self):
        slots  = [_slot("Tank", "Mace", "Heron Spear")]
        key    = roster_choices.build_role_choices(slots)[0]["key"]
        assert roster_choices.find_role_choice(slots, key)["role"] == "Tank"

    def test_find_role_choice_returns_none_for_a_stale_key(self):
        stale = roster_choices.choice_key("Healer", "Holy", "Fallen Staff")
        assert roster_choices.find_role_choice([_slot("Tank", "Mace")], stale) is None

    def test_find_matching_slots_returns_every_slot_of_that_role(self):
        slots = [
            _slot("DPS", "Fire", "Great Fire Staff", index=1),
            _slot("Tank", "Mace", "Heron Spear", index=2),
            _slot("DPS", "Fire", "Great Fire Staff", index=3),
        ]
        choice  = roster_choices.build_role_choices(slots)[0]
        matched = roster_choices.find_matching_slots(slots, choice)
        assert [s["slot_index"] for s in matched] == [1, 3]


# ---------------------------------------------------------------------------
# 2. Formatter — the select row on an announcement
# ---------------------------------------------------------------------------

def _select(payload: dict) -> dict | None:
    for row in payload.get("components", []):
        for component in row["components"]:
            if component["type"] == 3:
                return component
    return None


_OP = {
    "id":                 "op-1",
    "title":              "Saturday ZvZ",
    "operation_type":     "zvz",
    "status":             "planning",
    "scheduled_start_at": "2026-06-07T20:00:00+00:00",
}


class TestAnnouncementSelect:
    def test_no_select_without_a_roster(self):
        assert _select(formatters.format_operation_announcement(_OP)) is None

    def test_select_custom_id_carries_the_operation(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace", "Heron Spear")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        assert _select(payload)["custom_id"] == "signup:op-1"

    def test_option_label_shows_role_and_weapon(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace", "Heron Spear")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        option  = _select(payload)["options"][0]
        assert "Tank" in option["label"]
        assert "Heron Spear" in option["label"]

    def test_option_description_shows_the_build(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace", "Heron Spear")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        assert _select(payload)["options"][0]["description"] == "Mace"

    def test_option_value_is_the_choice_key(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace", "Heron Spear")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        assert _select(payload)["options"][0]["value"] == choices[0]["key"]

    def test_weaponless_role_still_renders(self):
        choices = roster_choices.build_role_choices([_slot("Scout", "Whatever")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        assert _select(payload)["options"][0]["label"] == "Scout"

    def test_options_are_capped_at_the_discord_limit(self):
        slots   = [_slot(f"Role {i}", f"Build {i}", index=i) for i in range(1, 40)]
        choices = roster_choices.build_role_choices(slots)
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        assert len(_select(payload)["options"]) == formatters.SELECT_MAX_OPTIONS

    def test_labels_are_truncated_to_the_discord_limit(self):
        choices = roster_choices.build_role_choices([_slot("R" * 200, "B" * 200, "W" * 200)])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        option  = _select(payload)["options"][0]
        assert len(option["label"]) <= 100
        assert len(option["description"]) <= 100

    def test_checkin_buttons_survive_alongside_the_select(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        ids = [
            c["custom_id"]
            for row in payload["components"]
            for c in row["components"]
            if c.get("custom_id", "").startswith("checkin:")
        ]
        assert ids == ["checkin:scout:op-1", "checkin:support:op-1"]

    def test_select_occupies_its_own_action_row(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        select_rows = [
            row for row in payload["components"]
            if any(c["type"] == 3 for c in row["components"])
        ]
        assert len(select_rows) == 1
        assert len(select_rows[0]["components"]) == 1

    def test_payload_is_json_serialisable(self):
        choices = roster_choices.build_role_choices([_slot("Tank", "Mace", "Heron Spear")])
        payload = formatters.format_operation_announcement(_OP, role_choices=choices)
        assert json.loads(json.dumps(payload))["components"]


class TestPickerIsOffered:
    """A menu whose every option errors is worse than no menu."""

    def test_planning_with_open_signups_is_offered(self):
        assert roster_choices.picker_is_offered("planning", {"signup_status": "open"})

    def test_no_plan_is_still_offered(self):
        assert roster_choices.picker_is_offered("planning", None)

    def test_draft_is_not_offered(self):
        """An announcement may be posted from draft, but signups cannot."""
        assert not roster_choices.picker_is_offered("draft", {"signup_status": "open"})

    def test_locked_is_not_offered(self):
        assert not roster_choices.picker_is_offered("locked", {"signup_status": "open"})

    def test_closed_signups_are_not_offered(self):
        assert not roster_choices.picker_is_offered("planning", {"signup_status": "closed"})


# ---------------------------------------------------------------------------
# 3. Formatter — thread notice and build DM
# ---------------------------------------------------------------------------

class TestRoleChoiceNotice:
    def test_mentions_the_member_when_the_snowflake_is_known(self):
        payload = formatters.format_role_choice_notice(
            "Emiel", {"role": "Tank", "weapon_name": "Heron Spear"}, _DISCORD_USER_ID
        )
        assert f"<@{_DISCORD_USER_ID}>" in payload["content"]

    def test_falls_back_to_the_display_name(self):
        payload = formatters.format_role_choice_notice(
            "Emiel", {"role": "Tank", "weapon_name": "Heron Spear"}
        )
        assert "Emiel" in payload["content"]
        assert "<@" not in payload["content"]

    def test_names_the_role_and_weapon(self):
        payload = formatters.format_role_choice_notice(
            "Emiel", {"role": "Tank", "weapon_name": "Heron Spear"}
        )
        assert "Tank" in payload["content"]
        assert "Heron Spear" in payload["content"]

    def test_pings_nobody(self):
        """A thread notice must never ping: it answers someone already present."""
        payload = formatters.format_role_choice_notice(
            "Emiel", {"role": "Tank"}, _DISCORD_USER_ID
        )
        assert payload["allowed_mentions"] == {"parse": [], "users": [], "roles": []}


class TestBuildDm:
    def _slot(self, **extra) -> dict:
        return {
            "role":        "Tank",
            "build_name":  "Heron Tank",
            "weapon_name": "T8.1 Heron Spear",
            "armor_name":  "T8.2 Guardian Armor",
            **extra,
        }

    def _fields(self, payload: dict) -> dict:
        return {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}

    def test_title_is_the_build_name(self):
        payload = formatters.format_build_dm(_OP, self._slot())
        assert payload["embeds"][0]["title"] == "Heron Tank"

    def test_names_the_operation(self):
        payload = formatters.format_build_dm(_OP, self._slot())
        assert "Saturday ZvZ" in payload["embeds"][0]["description"]

    def test_lists_the_equipment_it_has(self):
        fields = self._fields(formatters.format_build_dm(_OP, self._slot()))
        assert fields["Weapon"] == "T8.1 Heron Spear"
        assert fields["Armor"]  == "T8.2 Guardian Armor"

    def test_omits_equipment_it_does_not_have(self):
        """An empty cape is not information worth a line."""
        fields = self._fields(formatters.format_build_dm(_OP, self._slot(cape_name=None)))
        assert "Cape" not in fields

    def test_includes_the_doctrine_role(self):
        fields = self._fields(
            formatters.format_build_dm(_OP, self._slot(doctrine_role="Main Caller"))
        )
        assert fields["Assignment"] == "Main Caller"

    def test_spells_are_labelled_and_ordered_for_a_player(self):
        payload = formatters.format_build_dm(_OP, self._slot(), spells=[
            {"field_key": "head_passive",   "spell_name": "Aggression"},
            {"field_key": "weapon_spell_q", "spell_name": "Spirit Spear"},
        ])
        spells = self._fields(payload)["Spells"]
        assert "**Q** — Spirit Spear" in spells
        assert "**Head Passive** — Aggression" in spells
        assert spells.index("Spirit Spear") < spells.index("Aggression")

    def test_no_spell_field_without_spells(self):
        assert "Spells" not in self._fields(formatters.format_build_dm(_OP, self._slot()))

    def test_carries_no_components(self):
        """A DM has no guild context, so an operation button there is inert."""
        assert "components" not in formatters.format_build_dm(_OP, self._slot())

    def test_payload_is_json_serialisable(self):
        payload = formatters.format_build_dm(_OP, self._slot(), spells=[
            {"field_key": "weapon_spell_q", "spell_name": "Spirit Spear"},
        ])
        assert json.loads(json.dumps(payload))["embeds"]


# ---------------------------------------------------------------------------
# 4. REST client — threads and DM channels
# ---------------------------------------------------------------------------

class TestThreadAndDmRest:
    def test_start_message_thread_returns_the_thread_id(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setattr(
            rest_client.httpx, "post",
            lambda *a, **k: httpx.Response(201, json={"id": _MESSAGE_ID}),
        )
        assert rest_client.start_message_thread(
            _CHANNEL_ID, _MESSAGE_ID, "Signups"
        ) == _MESSAGE_ID

    def test_thread_name_is_truncated(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        seen: dict = {}

        def fake_post(url, **kwargs):
            seen.update(kwargs["json"])
            return httpx.Response(201, json={"id": _MESSAGE_ID})

        monkeypatch.setattr(rest_client.httpx, "post", fake_post)
        rest_client.start_message_thread(_CHANNEL_ID, _MESSAGE_ID, "N" * 200)
        assert len(seen["name"]) == 100

    def test_post_thread_message_posts_straight_into_an_existing_thread(self, monkeypatch):
        """The common path is one request: after the first post a thread exists."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        urls: list[str] = []

        def fake_post(url, **kwargs):
            urls.append(url)
            return httpx.Response(200, json={"id": "msg-1"})

        monkeypatch.setattr(rest_client.httpx, "post", fake_post)
        rest_client.post_thread_message(_CHANNEL_ID, _MESSAGE_ID, "Signups", {})
        assert len(urls) == 1
        assert urls[0].endswith(f"/channels/{_MESSAGE_ID}/messages")

    def test_post_thread_message_creates_the_thread_on_404(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        urls: list[str] = []

        def fake_post(url, **kwargs):
            urls.append(url)
            if url.endswith("/threads"):
                return httpx.Response(201, json={"id": _MESSAGE_ID})
            if len(urls) == 1:
                return httpx.Response(404, text="Unknown Channel")
            return httpx.Response(200, json={"id": "msg-1"})

        monkeypatch.setattr(rest_client.httpx, "post", fake_post)
        rest_client.post_thread_message(_CHANNEL_ID, _MESSAGE_ID, "Signups", {})
        assert any(u.endswith("/threads") for u in urls)
        assert len(urls) == 3

    def test_post_thread_message_does_not_retry_a_permission_error(self, monkeypatch):
        """403 means the bot may not post here; creating a thread will not help."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        urls: list[str] = []

        def fake_post(url, **kwargs):
            urls.append(url)
            return httpx.Response(403, text="Missing Permissions")

        monkeypatch.setattr(rest_client.httpx, "post", fake_post)
        with pytest.raises(rest_client.DiscordApiError):
            rest_client.post_thread_message(_CHANNEL_ID, _MESSAGE_ID, "Signups", {})
        assert len(urls) == 1

    def test_open_dm_channel_sends_the_recipient(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        seen: dict = {}

        def fake_post(url, **kwargs):
            seen["url"]  = url
            seen["json"] = kwargs["json"]
            return httpx.Response(200, json={"id": "dm-1"})

        monkeypatch.setattr(rest_client.httpx, "post", fake_post)
        assert rest_client.open_dm_channel(_DISCORD_USER_ID) == "dm-1"
        assert seen["url"].endswith("/users/@me/channels")
        assert seen["json"] == {"recipient_id": _DISCORD_USER_ID}

    def test_open_dm_channel_raises_on_failure(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setattr(
            rest_client.httpx, "post",
            lambda *a, **k: httpx.Response(400, text="Bad Request"),
        )
        with pytest.raises(rest_client.DiscordApiError):
            rest_client.open_dm_channel(_DISCORD_USER_ID)


# ---------------------------------------------------------------------------
# 5. Use case — recording a pick
# ---------------------------------------------------------------------------

def _make_discord_user(display_name: str, discord_user_id: str) -> dict:
    user = {
        "id":               str(uuid.uuid4()),
        "display_name":     display_name,
        "auth_provider":    "discord",
        "provider_user_id": discord_user_id,
        "created_at":       _now(),
        "updated_at":       _now(),
    }
    with database.transaction() as db:
        repositories.insert_user(db, user)
    return user


def _setup_operation_with_roster(suffix: str, *, publish: bool = True) -> dict:
    """Workspace linked to Discord, with a generated roster and a linked member."""
    owner = make_user(f"Owner-{suffix}")
    ws    = make_workspace(slug=f"rp-{suffix}", owner_user_id=owner["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=_CHANNEL_ID,
        officer_channel_id=None,
    )

    member = _make_discord_user(f"Player-{suffix}", _DISCORD_USER_ID)
    with database.transaction() as db:
        repositories.insert_workspace_member(db, {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "user_id":            member["id"],
            "role":               "member",
            "created_at":         _now(),
        })

    comp = make_composition(ws["id"], name=f"Comp-{suffix}", slots=[
        {"party_number": 1, "slot_index": 1, "role": "Tank",
         "build_name": "Heron Tank", "weapon_name": "T8.1 Heron Spear",
         "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer",
         "build_name": "Fallen Healer", "weapon_name": "T8.1 Fallen Staff",
         "priority": "core"},
    ])
    op = make_operation(ws["id"], title=f"Op {suffix}")
    use_cases.attach_operation_plan(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        albion_composition_id=comp["id"],
    )
    use_cases.generate_operation_slots(
        guild_workspace_id=ws["id"], guild_operation_id=op["id"]
    )
    if publish:
        use_cases.publish_operation(ws["id"], op["id"])

    with database.transaction() as db:
        slots = repositories.get_operation_slots(db, op["id"], ws["id"])
    choices = roster_choices.build_role_choices(slots)

    return {
        "owner": owner, "ws": ws, "member": member, "op": op,
        "slots": slots, "choices": choices,
        "tank":   next(c for c in choices if c["role"] == "Tank"),
        "healer": next(c for c in choices if c["role"] == "Healer"),
    }


def _signups(ws_id: str, op_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_signup_intents(db, op_id, ws_id)


class TestRecordRoleChoice:
    def test_creates_a_signup_with_the_picked_role(self):
        env = _setup_operation_with_roster("rec1")
        result = use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
            discord_user_id=_DISCORD_USER_ID,
        )
        assert result["action"] == "submitted"
        rows = _signups(env["ws"]["id"], env["op"]["id"])
        assert [r["preferred_role"] for r in rows] == ["Tank"]

    def test_stores_the_build_as_the_preference(self):
        env = _setup_operation_with_roster("rec2")
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
        )
        row = _signups(env["ws"]["id"], env["op"]["id"])[0]
        assert row["preferred_build_name"] == "Heron Tank"

    def test_records_the_discord_source(self):
        env = _setup_operation_with_roster("rec3")
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
        )
        assert _signups(env["ws"]["id"], env["op"]["id"])[0]["source"] == "discord"

    def test_stores_the_discord_user_on_the_participant(self):
        env = _setup_operation_with_roster("rec4")
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
            discord_user_id=_DISCORD_USER_ID,
        )
        with database.transaction() as db:
            participant = repositories.find_participant_by_display_name(
                db, env["ws"]["id"], "Emiel"
            )
        assert participant["discord_user_id"] == _DISCORD_USER_ID

    def test_returns_a_slot_matching_the_choice(self):
        env = _setup_operation_with_roster("rec5")
        result = use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["healer"]["key"],
        )
        assert result["slot"]["role"] == "Healer"
        assert result["slot"]["weapon_name"] == "T8.1 Fallen Staff"

    def test_repicking_changes_the_role_instead_of_failing(self):
        env = _setup_operation_with_roster("rec6")
        for key in (env["tank"]["key"], env["healer"]["key"]):
            result = use_cases.record_role_choice(
                guild_workspace_id=env["ws"]["id"],
                guild_operation_id=env["op"]["id"],
                display_name="Emiel",
                choice_key=key,
            )
        assert result["action"] == "changed"
        rows = _signups(env["ws"]["id"], env["op"]["id"])
        assert len(rows) == 1
        assert rows[0]["preferred_role"] == "Healer"

    def test_repicking_after_withdrawing_signs_the_member_back_up(self):
        env = _setup_operation_with_roster("rec7")
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
        )
        signup_id = _signups(env["ws"]["id"], env["op"]["id"])[0]["id"]
        use_cases.withdraw_signup_intent(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            actor_user_id=env["owner"]["id"],
            signup_id=signup_id,
        )
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["healer"]["key"],
        )
        rows = _signups(env["ws"]["id"], env["op"]["id"])
        assert [r["preferred_role"] for r in rows] == ["Healer"]

    def test_a_stale_key_is_rejected(self):
        env = _setup_operation_with_roster("rec8")
        with pytest.raises(Exception) as exc:
            use_cases.record_role_choice(
                guild_workspace_id=env["ws"]["id"],
                guild_operation_id=env["op"]["id"],
                display_name="Emiel",
                choice_key=roster_choices.choice_key("Ghost", "Nothing", ""),
            )
        assert "no longer part of this roster" in str(exc.value)

    def test_picking_never_assigns_a_slot(self):
        """A pick is a preference — the planner stays the officer's tool."""
        env = _setup_operation_with_roster("rec9")
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
        )
        with database.transaction() as db:
            assignments = repositories.get_assignments(
                db, env["op"]["id"], env["ws"]["id"]
            )
        assert assignments == []

    def test_two_members_may_pick_the_same_role(self):
        env = _setup_operation_with_roster("rec10")
        for name in ("Emiel", "Wesley"):
            use_cases.record_role_choice(
                guild_workspace_id=env["ws"]["id"],
                guild_operation_id=env["op"]["id"],
                display_name=name,
                choice_key=env["tank"]["key"],
            )
        rows = _signups(env["ws"]["id"], env["op"]["id"])
        assert [r["preferred_role"] for r in rows] == ["Tank", "Tank"]

    def test_an_assigned_member_cannot_repick(self):
        env = _setup_operation_with_roster("rec11")
        use_cases.record_role_choice(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            display_name="Emiel",
            choice_key=env["tank"]["key"],
        )
        with database.transaction() as db:
            participant = repositories.find_participant_by_display_name(
                db, env["ws"]["id"], "Emiel"
            )
            slot = next(s for s in env["slots"] if s["role"] == "Tank")
        use_cases.assign_participant_to_operation_slot(
            guild_workspace_id=env["ws"]["id"],
            guild_operation_id=env["op"]["id"],
            operation_slot_id=slot["id"],
            participant_id=participant["id"],
        )
        with pytest.raises(Exception) as exc:
            use_cases.record_role_choice(
                guild_workspace_id=env["ws"]["id"],
                guild_operation_id=env["op"]["id"],
                display_name="Emiel",
                choice_key=env["healer"]["key"],
            )
        assert "already assigned" in str(exc.value)

    def test_a_draft_operation_refuses_picks(self):
        env = _setup_operation_with_roster("rec12", publish=False)
        with pytest.raises(Exception):
            use_cases.record_role_choice(
                guild_workspace_id=env["ws"]["id"],
                guild_operation_id=env["op"]["id"],
                display_name="Emiel",
                choice_key=env["tank"]["key"],
            )

    def test_closed_signups_refuse_picks(self):
        env = _setup_operation_with_roster("rec13")
        with database.transaction() as db:
            db.execute(
                "UPDATE operation_plans SET signup_status = 'closed' "
                "WHERE guild_operation_id = ?",
                (env["op"]["id"],),
            )
        with pytest.raises(Exception) as exc:
            use_cases.record_role_choice(
                guild_workspace_id=env["ws"]["id"],
                guild_operation_id=env["op"]["id"],
                display_name="Emiel",
                choice_key=env["tank"]["key"],
            )
        assert "closed" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 6. Use case — delivering the notice and the build
# ---------------------------------------------------------------------------

def _seed_announcement(ws_id: str, op_id: str) -> None:
    with database.transaction() as db:
        repositories.upsert_discord_message(db, {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": ws_id,
            "guild_operation_id": op_id,
            "message_type":       "announcement",
            "discord_channel_id": _CHANNEL_ID,
            "discord_message_id": _MESSAGE_ID,
            "discord_guild_id":   _GUILD_ID,
            "posted_at":          _now(),
            "last_edited_at":     _now(),
            "is_deleted":         0,
        })


class _RestSpy:
    """Stands in for rest_client, recording calls and faking failures."""

    def __init__(self, *, thread_error=None, dm_open_error=None, dm_post_error=None):
        self.DiscordApiError = rest_client.DiscordApiError
        self.thread_calls: list[tuple] = []
        self.dm_channels:  list[str]   = []
        self.dm_messages:  list[tuple] = []
        self._thread_error  = thread_error
        self._dm_open_error = dm_open_error
        self._dm_post_error = dm_post_error

    def post_thread_message(self, channel_id, message_id, name, payload):
        self.thread_calls.append((channel_id, message_id, name, payload))
        if self._thread_error:
            raise self._thread_error
        return "thread-msg-1"

    def open_dm_channel(self, user_id):
        if self._dm_open_error:
            raise self._dm_open_error
        self.dm_channels.append(user_id)
        return "dm-1"

    def post_message(self, channel_id, payload):
        self.dm_messages.append((channel_id, payload))
        if self._dm_post_error:
            raise self._dm_post_error
        return "dm-msg-1"


def _deliver(env, spy, monkeypatch, *, discord_user_id=_DISCORD_USER_ID, slot=None):
    monkeypatch.setattr("app.discord.rest_client.post_thread_message", spy.post_thread_message)
    monkeypatch.setattr("app.discord.rest_client.open_dm_channel", spy.open_dm_channel)
    monkeypatch.setattr("app.discord.rest_client.post_message", spy.post_message)
    return use_cases.deliver_role_choice_notifications(
        guild_workspace_id=env["ws"]["id"],
        guild_operation_id=env["op"]["id"],
        operation=env["op"],
        slot=slot or next(s for s in env["slots"] if s["role"] == "Tank"),
        choice=env["tank"],
        display_name="Emiel",
        discord_user_id=discord_user_id,
    )


class TestDeliverRoleChoiceNotifications:
    def test_posts_the_notice_in_the_announcement_thread(self, monkeypatch):
        env = _setup_operation_with_roster("del1")
        _seed_announcement(env["ws"]["id"], env["op"]["id"])
        spy = _RestSpy()
        result = _deliver(env, spy, monkeypatch)
        assert result["thread"] == "posted"
        channel_id, message_id, _, payload = spy.thread_calls[0]
        assert (channel_id, message_id) == (_CHANNEL_ID, _MESSAGE_ID)
        assert "Tank" in payload["content"]

    def test_thread_is_named_after_the_operation(self, monkeypatch):
        env = _setup_operation_with_roster("del2")
        _seed_announcement(env["ws"]["id"], env["op"]["id"])
        spy = _RestSpy()
        _deliver(env, spy, monkeypatch)
        assert env["op"]["title"] in spy.thread_calls[0][2]

    def test_dms_the_build_to_the_member(self, monkeypatch):
        env = _setup_operation_with_roster("del3")
        _seed_announcement(env["ws"]["id"], env["op"]["id"])
        spy = _RestSpy()
        result = _deliver(env, spy, monkeypatch)
        assert result["dm"] == "sent"
        assert spy.dm_channels == [_DISCORD_USER_ID]
        channel_id, payload = spy.dm_messages[0]
        assert channel_id == "dm-1"
        assert payload["embeds"][0]["title"] == "Heron Tank"

    def test_without_an_announcement_there_is_no_thread(self, monkeypatch):
        env = _setup_operation_with_roster("del4")
        spy = _RestSpy()
        result = _deliver(env, spy, monkeypatch)
        assert result["thread"] == "no_announcement"
        assert spy.thread_calls == []

    def test_a_deleted_announcement_is_not_threaded(self, monkeypatch):
        env = _setup_operation_with_roster("del5")
        _seed_announcement(env["ws"]["id"], env["op"]["id"])
        with database.transaction() as db:
            db.execute(
                "UPDATE discord_messages SET is_deleted = 1 "
                "WHERE guild_operation_id = ?",
                (env["op"]["id"],),
            )
        spy = _RestSpy()
        assert _deliver(env, spy, monkeypatch)["thread"] == "no_announcement"

    def test_a_thread_failure_does_not_stop_the_dm(self, monkeypatch):
        env = _setup_operation_with_roster("del6")
        _seed_announcement(env["ws"]["id"], env["op"]["id"])
        spy = _RestSpy(
            thread_error=rest_client.DiscordApiError(403, "Missing Permissions")
        )
        result = _deliver(env, spy, monkeypatch)
        assert result["thread"] == "failed"
        assert result["dm"] == "sent"

    def test_blocked_dms_are_reported_as_blocked(self, monkeypatch):
        env = _setup_operation_with_roster("del7")
        _seed_announcement(env["ws"]["id"], env["op"]["id"])
        spy = _RestSpy(
            dm_post_error=rest_client.DiscordApiError(403, "Cannot send messages to this user")
        )
        result = _deliver(env, spy, monkeypatch)
        assert result["dm"] == "blocked"
        assert result["dm_error"]

    def test_other_dm_errors_are_reported_as_failed(self, monkeypatch):
        env = _setup_operation_with_roster("del8")
        spy = _RestSpy(dm_open_error=rest_client.DiscordApiError(500, "Server Error"))
        assert _deliver(env, spy, monkeypatch)["dm"] == "failed"

    def test_the_build_payload_comes_back_for_a_fallback(self, monkeypatch):
        """A refused DM still has to reach the player somehow."""
        env = _setup_operation_with_roster("del9")
        spy = _RestSpy(
            dm_post_error=rest_client.DiscordApiError(403, "Cannot send messages")
        )
        result = _deliver(env, spy, monkeypatch)
        assert result["build_payload"]["embeds"][0]["title"] == "Heron Tank"

    def test_an_unlinked_member_gets_no_dm_attempt(self, monkeypatch):
        env = _setup_operation_with_roster("del10")
        spy = _RestSpy()
        result = _deliver(env, spy, monkeypatch, discord_user_id=None)
        assert result["dm"] == "no_discord_user"
        assert spy.dm_channels == []


# ---------------------------------------------------------------------------
# 6b. Posting the announcement attaches the picker
# ---------------------------------------------------------------------------

def _posted_payload(env, monkeypatch) -> dict:
    """Post the announcement and return the payload that went to Discord."""
    sent: dict = {}

    def fake_post(channel_id, payload):
        sent.update(payload)
        return _MESSAGE_ID

    monkeypatch.setattr("app.discord.rest_client.post_message", fake_post)
    use_cases.post_discord_announcement(
        guild_workspace_id=env["ws"]["id"],
        guild_operation_id=env["op"]["id"],
        actor_id=env["owner"]["id"],
        signup_url=None,
    )
    return sent


class TestAnnouncementCarriesThePicker:
    def test_posting_attaches_the_roster_roles(self, monkeypatch):
        env     = _setup_operation_with_roster("post1")
        payload = _posted_payload(env, monkeypatch)
        options = _select(payload)["options"]
        assert {o["label"] for o in options} == {
            "Tank · T8.1 Heron Spear", "Healer · T8.1 Fallen Staff",
        }

    def test_a_draft_operation_posts_without_a_picker(self, monkeypatch):
        """Signups cannot be submitted from draft, so a menu there only errors."""
        env     = _setup_operation_with_roster("post2", publish=False)
        payload = _posted_payload(env, monkeypatch)
        assert _select(payload) is None

    def test_closed_signups_post_without_a_picker(self, monkeypatch):
        env = _setup_operation_with_roster("post3")
        with database.transaction() as db:
            db.execute(
                "UPDATE operation_plans SET signup_status = 'closed' "
                "WHERE guild_operation_id = ?",
                (env["op"]["id"],),
            )
        assert _select(_posted_payload(env, monkeypatch)) is None

    def test_check_in_buttons_are_still_posted(self, monkeypatch):
        env     = _setup_operation_with_roster("post4")
        payload = _posted_payload(env, monkeypatch)
        assert any(
            c.get("custom_id", "").startswith("checkin:")
            for row in payload["components"] for c in row["components"]
        )


# ---------------------------------------------------------------------------
# 7. Adapter — routing the select interaction
# ---------------------------------------------------------------------------

def _select_payload(op_id: str, value: str, custom_id: str | None = None) -> dict:
    return {
        "discord_guild_id": _GUILD_ID,
        "discord_user_id":  _DISCORD_USER_ID,
        "custom_id":        custom_id or f"signup:{op_id}",
        "values":           [value],
    }


def _call(payload: dict) -> dict:
    with database.transaction() as db:
        return adapter.handle_component_interaction(payload, db)


class TestAdapterRoleChoice:
    def test_confirms_the_pick_ephemerally(self):
        env  = _setup_operation_with_roster("ad1")
        resp = _call(_select_payload(env["op"]["id"], env["tank"]["key"]))
        assert resp["type"] == 4
        assert resp["data"]["flags"] & 64
        assert "Tank" in resp["data"]["content"]

    def test_records_the_signup(self):
        env = _setup_operation_with_roster("ad2")
        _call(_select_payload(env["op"]["id"], env["tank"]["key"]))
        rows = _signups(env["ws"]["id"], env["op"]["id"])
        assert [r["preferred_role"] for r in rows] == ["Tank"]

    def test_hands_back_a_follow_up_for_the_thread_and_dm(self):
        env  = _setup_operation_with_roster("ad3")
        resp = _call(_select_payload(env["op"]["id"], env["tank"]["key"]))
        follow_up = resp["follow_up"]
        assert follow_up["kind"] == "role_choice"
        assert follow_up["guild_operation_id"] == env["op"]["id"]
        assert follow_up["discord_user_id"] == _DISCORD_USER_ID
        assert follow_up["slot"]["role"] == "Tank"

    def test_a_second_pick_reads_as_a_move(self):
        env = _setup_operation_with_roster("ad4")
        _call(_select_payload(env["op"]["id"], env["tank"]["key"]))
        resp = _call(_select_payload(env["op"]["id"], env["healer"]["key"]))
        assert "Moved to" in resp["data"]["content"]

    def test_a_stale_key_answers_with_an_error(self):
        env  = _setup_operation_with_roster("ad5")
        resp = _call(_select_payload(
            env["op"]["id"], roster_choices.choice_key("Ghost", "None", "")
        ))
        assert resp["data"]["content"].startswith("❌")
        assert "follow_up" not in resp

    def test_a_malformed_custom_id_answers_with_an_error(self):
        env  = _setup_operation_with_roster("ad6")
        resp = _call(_select_payload(
            env["op"]["id"], env["tank"]["key"], custom_id="signup"
        ))
        assert resp["data"]["content"].startswith("❌")

    def test_an_empty_selection_answers_with_an_error(self):
        env     = _setup_operation_with_roster("ad7")
        payload = _select_payload(env["op"]["id"], env["tank"]["key"])
        payload["values"] = []
        assert _call(payload)["data"]["content"].startswith("❌")

    def test_an_unknown_operation_answers_with_an_error(self):
        env  = _setup_operation_with_roster("ad8")
        resp = _call(_select_payload(str(uuid.uuid4()), env["tank"]["key"]))
        assert "not found" in resp["data"]["content"].lower()

    def test_check_in_buttons_still_route(self):
        """The new prefix routing must not disturb the existing buttons."""
        env  = _setup_operation_with_roster("ad9")
        resp = _call({
            "discord_guild_id": _GUILD_ID,
            "discord_user_id":  _DISCORD_USER_ID,
            "custom_id":        f"checkin:scout:{env['op']['id']}",
        })
        assert "Checked in" in resp["data"]["content"]

    def test_an_unknown_prefix_is_rejected(self):
        env  = _setup_operation_with_roster("ad10")
        resp = _call({
            "discord_guild_id": _GUILD_ID,
            "discord_user_id":  _DISCORD_USER_ID,
            "custom_id":        f"nonsense:{env['op']['id']}",
        })
        assert resp["data"]["content"].startswith("❌")


# ---------------------------------------------------------------------------
# 8. Build version pinning — spells reach the player
# ---------------------------------------------------------------------------

def _make_versioned_build(ws_id: str, owner_id: str, name: str) -> tuple[str, str]:
    """A build whose loadout lives in a version. Returns (build_id, version_id)."""
    build_id   = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    with database.transaction() as db:
        repositories.insert_albion_build(db, {
            "id":                 build_id,
            "guild_workspace_id": ws_id,
            "name":               name,
            "role":               "Tank",
            "weapon_name":        "T8.1 Heron Spear",
            "offhand_name":       None, "head_name":  None,
            "armor_name":         None, "shoes_name": None,
            "cape_name":          None, "food_name":  None,
            "potion_name":        None, "notes":      None,
            "doctrine_role":      None, "retired_at": None,
            "created_at":         _now(),
            "updated_at":         _now(),
        })
        db.execute(
            "INSERT INTO albion_build_versions "
            "(id, build_id, guild_workspace_id, version_number, created_at, created_by) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (version_id, build_id, ws_id, _now(), owner_id),
        )
        db.execute(
            "UPDATE albion_builds SET current_version_id = ?, status = 'published' "
            "WHERE id = ?",
            (version_id, build_id),
        )
    return build_id, version_id


class TestBuildVersionPin:
    def test_attaching_a_build_pins_the_version_it_was_flattened_from(self):
        """Gear text and spells have to describe the same version of the build."""
        owner = make_user("PinOwner1")
        ws    = make_workspace(slug="pin-attach-1", owner_user_id=owner["id"])
        build_id, version_id = _make_versioned_build(ws["id"], owner["id"], "Pinned")
        comp = make_composition(ws["id"], name="PinComp", slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Pinned", "albion_build_id": build_id,
             "priority": "core"},
        ])
        with database.transaction() as db:
            template = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]
        assert template["albion_build_version_id"] == version_id

    def test_slot_generation_carries_the_pin_to_the_operation(self):
        owner = make_user("PinOwner2")
        ws    = make_workspace(slug="pin-attach-2", owner_user_id=owner["id"])
        build_id, version_id = _make_versioned_build(ws["id"], owner["id"], "Pinned")
        comp = make_composition(ws["id"], name="PinComp", slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Pinned", "albion_build_id": build_id,
             "priority": "core"},
        ])
        op = make_operation(ws["id"], title="Pinned Op")
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        slots = use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"], guild_operation_id=op["id"]
        )
        assert slots[0]["albion_build_version_id"] == version_id

    def test_a_manually_typed_slot_has_no_pin(self):
        env = _setup_operation_with_roster("pin2")
        assert env["slots"][0]["albion_build_version_id"] is None

    def test_spells_are_read_through_the_pinned_version(self, monkeypatch):
        env = _setup_operation_with_roster("pin3")
        build_id   = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        with database.transaction() as db:
            repositories.insert_albion_build(db, {
                "id":                 build_id,
                "guild_workspace_id": env["ws"]["id"],
                "name":               "Heron Tank",
                "role":               "Tank",
                "weapon_name":        "T8.1 Heron Spear",
                "offhand_name":       None, "head_name":  None,
                "armor_name":         None, "shoes_name": None,
                "cape_name":          None, "food_name":  None,
                "potion_name":        None, "notes":      None,
                "doctrine_role":      None, "retired_at": None,
                "created_at":         _now(),
                "updated_at":         _now(),
            })
            db.execute(
                "INSERT INTO albion_build_versions "
                "(id, build_id, guild_workspace_id, version_number, created_at, created_by) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (version_id, build_id, env["ws"]["id"], _now(), env["owner"]["id"]),
            )
            repositories.insert_build_spells(db, [{
                "id":                 str(uuid.uuid4()),
                "build_version_id":   version_id,
                "guild_workspace_id": env["ws"]["id"],
                "field_key":          "weapon_spell_q",
                "spell_name":         "Spirit Spear",
            }])

        slot = dict(next(s for s in env["slots"] if s["role"] == "Tank"))
        slot["albion_build_version_id"] = version_id

        spy = _RestSpy()
        result = _deliver(env, spy, monkeypatch, slot=slot)
        spells = next(
            f["value"] for f in result["build_payload"]["embeds"][0]["fields"]
            if f["name"] == "Spells"
        )
        assert "Spirit Spear" in spells

    def test_a_slot_without_a_version_still_delivers_gear(self, monkeypatch):
        env  = _setup_operation_with_roster("pin4")
        spy  = _RestSpy()
        result = _deliver(env, spy, monkeypatch)
        fields = {
            f["name"]: f["value"]
            for f in result["build_payload"]["embeds"][0]["fields"]
        }
        assert fields["Weapon"] == "T8.1 Heron Spear"
        assert "Spells" not in fields
