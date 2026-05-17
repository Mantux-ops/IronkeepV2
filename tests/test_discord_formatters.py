"""
Tests for app/discord/formatters.py

All formatters are pure functions: plain dicts in, plain dicts out.
No database access, no Discord SDK, no side effects.

Readiness dict shape matches readiness_snapshots DB row:
  total_slots, assigned_slots, open_slots, readiness_state,
  missing_roles_json (JSON str), missing_builds_json (JSON str),
  attendance_marked_count, attendance_unmarked_count,
  scout_count, support_count
"""

from __future__ import annotations

import inspect
import json
import uuid

import pytest

from app.discord.formatters import (
    STATUS_COLORS,
    format_operation_announcement,
    format_readiness_summary,
    format_roster,
    format_signup_confirmation,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _operation(**overrides) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "title": "Saturday ZvZ",
        "operation_type": "zvz",
        "status": "planning",
        "scheduled_start_at": "2026-06-07T20:00:00+00:00",
    }
    return {**base, **overrides}


def _readiness(**overrides) -> dict:
    base = {
        "total_slots": 20,
        "assigned_slots": 12,
        "open_slots": 8,
        "readiness_state": "forming",
        "missing_roles_json": json.dumps({"DPS": 4, "Tank": 2, "Healer": 2}),
        "missing_builds_json": json.dumps({"Bow": 2, "1H Mace": 1}),
        "attendance_marked_count": 8,
        "attendance_unmarked_count": 4,
        "scout_count": 2,
        "support_count": 1,
    }
    return {**base, **overrides}


def _slots(n_parties: int = 2, slots_per_party: int = 5) -> list[dict]:
    result = []
    idx = 0
    for party in range(1, n_parties + 1):
        for slot_i in range(1, slots_per_party + 1):
            idx += 1
            result.append({
                "id": f"slot-{idx}",
                "party_number": party,
                "slot_index": slot_i,
                "role": ["Tank", "Healer", "DPS", "Support", "DPS"][(slot_i - 1) % 5],
                "build_name": ["1H Mace", "Hallowfall", "Daggers", "Locus", "Bow"][(slot_i - 1) % 5],
            })
    return result


def _assignments(slot_ids: list[str], names: list[str]) -> list[dict]:
    return [{"slot_id": sid, "display_name": name} for sid, name in zip(slot_ids, names)]


def _signup(**overrides) -> dict:
    base = {
        "preferred_role": "Tank",
        "preferred_build_name": "1H Mace",
        "willingness": "specific",
        "availability": "confirmed",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _embed(payload: dict) -> dict:
    """Extract the first embed from a message payload."""
    return payload["embeds"][0]


def _field_names(embed: dict) -> list[str]:
    return [f["name"] for f in embed.get("fields", [])]


def _field_value(embed: dict, name: str) -> str:
    for f in embed.get("fields", []):
        if f["name"] == name:
            return f["value"]
    raise KeyError(f"Field '{name}' not found. Available: {_field_names(embed)}")


# ---------------------------------------------------------------------------
# 1. format_operation_announcement
# ---------------------------------------------------------------------------

class TestFormatOperationAnnouncement:
    def test_returns_embeds_key(self):
        result = format_operation_announcement(_operation())
        assert "embeds" in result
        assert len(result["embeds"]) == 1

    def test_embed_has_title(self):
        result = format_operation_announcement(_operation(title="Midweek HG"))
        assert _embed(result)["title"] == "Midweek HG"

    def test_embed_has_footer(self):
        result = format_operation_announcement(_operation())
        assert _embed(result)["footer"]["text"] == "IronkeepV2"

    def test_embed_has_color(self):
        result = format_operation_announcement(_operation())
        assert isinstance(_embed(result)["color"], int)

    def test_color_for_planning(self):
        result = format_operation_announcement(_operation(status="planning"))
        assert _embed(result)["color"] == STATUS_COLORS["planning"]

    def test_color_for_locked(self):
        result = format_operation_announcement(_operation(status="locked"))
        assert _embed(result)["color"] == STATUS_COLORS["locked"]

    def test_color_for_completed(self):
        result = format_operation_announcement(_operation(status="completed"))
        assert _embed(result)["color"] == STATUS_COLORS["completed"]

    def test_color_for_draft(self):
        result = format_operation_announcement(_operation(status="draft"))
        assert _embed(result)["color"] == STATUS_COLORS["draft"]

    def test_color_for_archived(self):
        result = format_operation_announcement(_operation(status="archived"))
        assert _embed(result)["color"] == STATUS_COLORS["archived"]

    def test_all_statuses_produce_distinct_colors(self):
        colors = [
            format_operation_announcement(_operation(status=s))["embeds"][0]["color"]
            for s in ("draft", "planning", "locked", "completed", "archived")
        ]
        assert len(set(colors)) == 5, "every status should map to a distinct color"

    def test_standard_fields_present(self):
        result = format_operation_announcement(_operation())
        embed = _embed(result)
        names = _field_names(embed)
        assert "Type" in names
        assert "Status" in names
        assert "When" in names

    def test_with_readiness_adds_roster_field(self):
        result = format_operation_announcement(_operation(), readiness=_readiness())
        assert "Roster" in _field_names(_embed(result))

    def test_roster_field_shows_fill_numbers(self):
        result = format_operation_announcement(_operation(), readiness=_readiness())
        value = _field_value(_embed(result), "Roster")
        assert "12" in value
        assert "20" in value

    def test_without_readiness_no_roster_field(self):
        result = format_operation_announcement(_operation(), readiness=None)
        assert "Roster" not in _field_names(_embed(result))

    def test_without_readiness_no_crash(self):
        # Must not raise even with minimal operation dict
        result = format_operation_announcement(
            {"title": "X", "operation_type": "zvz", "status": "planning",
             "scheduled_start_at": "2026-01-01T00:00:00+00:00"}
        )
        assert "embeds" in result

    def test_when_field_contains_date(self):
        result = format_operation_announcement(
            _operation(scheduled_start_at="2026-06-07T20:00:00+00:00")
        )
        when = _field_value(_embed(result), "When")
        assert "2026-06-07" in when
        assert "20:00" in when

    def test_json_serializable(self):
        result = format_operation_announcement(_operation(), readiness=_readiness())
        json.dumps(result)  # must not raise


# ---------------------------------------------------------------------------
# 2. format_readiness_summary
# ---------------------------------------------------------------------------

class TestFormatReadinessSummary:
    def test_returns_embeds_key(self):
        result = format_readiness_summary(_operation(), _readiness())
        assert "embeds" in result

    def test_title_includes_operation_name(self):
        result = format_readiness_summary(_operation(title="Big ZvZ"), _readiness())
        assert "Big ZvZ" in _embed(result)["title"]

    def test_roster_field_shows_counts(self):
        result = format_readiness_summary(_operation(), _readiness())
        value = _field_value(_embed(result), "Roster")
        assert "12" in value
        assert "20" in value
        assert "60%" in value

    def test_state_field_present(self):
        result = format_readiness_summary(_operation(), _readiness(readiness_state="forming"))
        assert _field_value(_embed(result), "State") == "forming"

    def test_role_gaps_shown_when_present(self):
        result = format_readiness_summary(
            _operation(), _readiness(missing_roles_json=json.dumps({"DPS": 2, "Tank": 1}))
        )
        value = _field_value(_embed(result), "Role Gaps")
        assert "DPS" in value
        assert "Tank" in value

    def test_role_gaps_omitted_when_empty(self):
        result = format_readiness_summary(
            _operation(), _readiness(missing_roles_json=json.dumps({}))
        )
        assert "Role Gaps" not in _field_names(_embed(result))

    def test_build_gaps_shown_when_present(self):
        result = format_readiness_summary(
            _operation(), _readiness(missing_builds_json=json.dumps({"Bow": 2}))
        )
        value = _field_value(_embed(result), "Build Gaps")
        assert "Bow" in value

    def test_build_gaps_omitted_when_empty(self):
        result = format_readiness_summary(
            _operation(), _readiness(missing_builds_json=json.dumps({}))
        )
        assert "Build Gaps" not in _field_names(_embed(result))

    def test_attendance_counts_shown(self):
        result = format_readiness_summary(
            _operation(),
            _readiness(attendance_marked_count=8, attendance_unmarked_count=4)
        )
        value = _field_value(_embed(result), "Attendance")
        assert "8" in value
        assert "4" in value

    def test_scout_support_shown(self):
        result = format_readiness_summary(
            _operation(), _readiness(scout_count=2, support_count=1)
        )
        value = _field_value(_embed(result), "Scout / Support")
        assert "2" in value
        assert "1" in value

    def test_fully_filled_roster_omits_both_gap_fields(self):
        result = format_readiness_summary(
            _operation(),
            _readiness(
                total_slots=5, assigned_slots=5, open_slots=0,
                readiness_state="ready",
                missing_roles_json=json.dumps({}),
                missing_builds_json=json.dumps({}),
            )
        )
        names = _field_names(_embed(result))
        assert "Role Gaps" not in names
        assert "Build Gaps" not in names

    def test_malformed_gaps_json_does_not_crash(self):
        result = format_readiness_summary(
            _operation(),
            _readiness(missing_roles_json="INVALID_JSON", missing_builds_json=None)
        )
        assert "embeds" in result

    def test_json_serializable(self):
        result = format_readiness_summary(_operation(), _readiness())
        json.dumps(result)


# ---------------------------------------------------------------------------
# 3. format_roster
# ---------------------------------------------------------------------------

class TestFormatRoster:
    def test_returns_embeds_key(self):
        result = format_roster(_operation(), _slots(), [])
        assert "embeds" in result

    def test_title_includes_operation_name(self):
        result = format_roster(_operation(title="HG Run"), _slots(), [])
        assert "HG Run" in _embed(result)["title"]

    def test_groups_by_party(self):
        result = format_roster(_operation(), _slots(n_parties=2), [])
        names = _field_names(_embed(result))
        assert "Party 1" in names
        assert "Party 2" in names

    def test_single_party(self):
        result = format_roster(_operation(), _slots(n_parties=1), [])
        names = _field_names(_embed(result))
        assert "Party 1" in names
        assert "Party 2" not in names

    def test_open_slots_marked(self):
        slots = _slots(n_parties=1, slots_per_party=3)
        result = format_roster(_operation(), slots, [])  # no assignments
        value = _field_value(_embed(result), "Party 1")
        assert "*(open)*" in value

    def test_assigned_slots_show_display_name(self):
        slots = _slots(n_parties=1, slots_per_party=2)
        assignments = _assignments(
            [slots[0]["id"], slots[1]["id"]],
            ["Arthas", "Sylvanas"]
        )
        result = format_roster(_operation(), slots, assignments)
        value = _field_value(_embed(result), "Party 1")
        assert "Arthas" in value
        assert "Sylvanas" in value

    def test_assigned_name_bolded(self):
        slots = _slots(n_parties=1, slots_per_party=1)
        assignments = _assignments([slots[0]["id"]], ["Arthas"])
        result = format_roster(_operation(), slots, assignments)
        value = _field_value(_embed(result), "Party 1")
        assert "**Arthas**" in value

    def test_unassigned_slot_not_bolded(self):
        slots = _slots(n_parties=1, slots_per_party=1)
        result = format_roster(_operation(), slots, [])
        value = _field_value(_embed(result), "Party 1")
        assert "*(open)*" in value
        assert "**" not in value

    def test_footer_shows_fill_count(self):
        slots = _slots(n_parties=1, slots_per_party=5)
        assignments = _assignments(
            [s["id"] for s in slots[:3]],
            ["P1", "P2", "P3"]
        )
        result = format_roster(_operation(), slots, assignments)
        footer = _embed(result)["footer"]["text"]
        assert "3" in footer
        assert "5" in footer

    def test_empty_slots_list(self):
        result = format_roster(_operation(), [], [])
        assert "embeds" in result

    def test_parties_in_ascending_order(self):
        # Shuffle slots so party 2 appears first in the input list
        slots = _slots(n_parties=3)
        slots_shuffled = sorted(slots, key=lambda s: -s["party_number"])
        result = format_roster(_operation(), slots_shuffled, [])
        names = _field_names(_embed(result))
        party_names = [n for n in names if n.startswith("Party")]
        assert party_names == sorted(party_names)

    def test_json_serializable(self):
        slots = _slots()
        assignments = _assignments([s["id"] for s in slots[:4]], ["A", "B", "C", "D"])
        result = format_roster(_operation(), slots, assignments)
        json.dumps(result)


# ---------------------------------------------------------------------------
# 4. format_signup_confirmation
# ---------------------------------------------------------------------------

class TestFormatSignupConfirmation:
    def test_returns_embeds_and_flags(self):
        result = format_signup_confirmation(_operation(), _signup())
        assert "embeds" in result
        assert result["flags"] == 64

    def test_title_is_confirmed(self):
        result = format_signup_confirmation(_operation(), _signup())
        assert "Confirmed" in _embed(result)["title"]

    def test_description_includes_operation_title(self):
        result = format_signup_confirmation(_operation(title="Saturday ZvZ"), _signup())
        assert "Saturday ZvZ" in _embed(result)["description"]

    def test_role_field_present(self):
        result = format_signup_confirmation(_operation(), _signup(preferred_role="Healer"))
        assert _field_value(_embed(result), "Role") == "Healer"

    def test_build_field_present_when_set(self):
        result = format_signup_confirmation(_operation(), _signup(preferred_build_name="Hallowfall"))
        assert _field_value(_embed(result), "Build") == "Hallowfall"

    def test_build_field_absent_when_none(self):
        result = format_signup_confirmation(_operation(), _signup(preferred_build_name=None))
        assert "Build" not in _field_names(_embed(result))

    def test_availability_field_present(self):
        result = format_signup_confirmation(_operation(), _signup(availability="tentative"))
        assert _field_value(_embed(result), "Availability") == "tentative"

    def test_willingness_field_present(self):
        result = format_signup_confirmation(_operation(), _signup(willingness="fill"))
        assert _field_value(_embed(result), "Willingness") == "fill"

    def test_willingness_specific(self):
        result = format_signup_confirmation(_operation(), _signup(willingness="specific"))
        assert _field_value(_embed(result), "Willingness") == "specific"

    def test_willingness_flexible(self):
        # 'flexible' is a valid domain willingness value (VALID_WILLINGNESS in operation_plans.py)
        result = format_signup_confirmation(_operation(), _signup(willingness="flexible"))
        assert _field_value(_embed(result), "Willingness") == "flexible"

    def test_when_field_present(self):
        result = format_signup_confirmation(
            _operation(scheduled_start_at="2026-06-07T20:00:00+00:00"), _signup()
        )
        when = _field_value(_embed(result), "When")
        assert "2026-06-07" in when

    def test_color_is_green_regardless_of_operation_status(self):
        from app.discord.formatters import STATUS_COLORS
        result = format_signup_confirmation(_operation(status="locked"), _signup())
        assert _embed(result)["color"] == STATUS_COLORS["completed"]  # always green confirmation

    def test_json_serializable(self):
        result = format_signup_confirmation(_operation(), _signup())
        json.dumps(result)


# ---------------------------------------------------------------------------
# 5. No Discord SDK, JSON-serializable
# ---------------------------------------------------------------------------

def test_no_discord_sdk_imported():
    """formatters.py must not import any Discord SDK package."""
    import importlib.util
    from pathlib import Path

    src = Path(__file__).parent.parent / "app" / "discord" / "formatters.py"
    text = src.read_text()

    forbidden = ["import discord", "from discord"]
    for pattern in forbidden:
        assert pattern not in text, (
            f"formatters.py contains '{pattern}' — Discord SDK must not be imported"
        )


def test_all_outputs_are_json_serializable():
    """Every formatter must return a JSON-serialisable dict."""
    slots = _slots()
    assignments = _assignments([s["id"] for s in slots[:3]], ["P1", "P2", "P3"])

    payloads = [
        format_operation_announcement(_operation()),
        format_operation_announcement(_operation(), readiness=_readiness()),
        format_readiness_summary(_operation(), _readiness()),
        format_roster(_operation(), slots, assignments),
        format_signup_confirmation(_operation(), _signup()),
        format_signup_confirmation(_operation(), _signup(preferred_build_name=None)),
    ]
    for payload in payloads:
        json.dumps(payload)  # raises TypeError if not serialisable


def test_formatters_are_pure_no_side_effects():
    """Calling a formatter twice with the same input returns equal outputs."""
    op = _operation()
    r  = _readiness()

    out1 = format_operation_announcement(op, r)
    out2 = format_operation_announcement(op, r)
    assert out1 == out2

    out1 = format_readiness_summary(op, r)
    out2 = format_readiness_summary(op, r)
    assert out1 == out2


def test_scheduled_time_format_readable():
    """_format_scheduled_time produces a human-readable string."""
    from app.discord.formatters import _format_scheduled_time

    result = _format_scheduled_time("2026-06-07T20:00:00+00:00")
    assert "2026-06-07" in result
    assert "20:00" in result
    assert "UTC" in result


def test_scheduled_time_format_invalid_does_not_crash():
    from app.discord.formatters import _format_scheduled_time

    result = _format_scheduled_time("not-a-date")
    assert result == "not-a-date"


# ---------------------------------------------------------------------------
# 6. Component buttons
# ---------------------------------------------------------------------------

class TestComponentButtons:
    """
    format_operation_announcement and format_roster must include a top-level
    'components' array containing check-in buttons and an optional link button.
    """

    def _announcement(self, **kwargs) -> dict:
        op = _operation()
        return format_operation_announcement(op, **kwargs)

    def _roster(self, **kwargs) -> dict:
        op   = _operation()
        s    = _slots()
        asmt = _assignments([s[0]["id"]], ["Alpha"])
        return format_roster(op, s, asmt, **kwargs)

    # --- components array exists -----------------------------------------

    def test_announcement_has_components(self):
        result = self._announcement()
        assert "components" in result

    def test_roster_has_components(self):
        result = self._roster()
        assert "components" in result

    # --- action row shape ------------------------------------------------

    def _action_row(self, result: dict) -> dict:
        rows = result["components"]
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == 1
        return row

    def test_announcement_single_action_row(self):
        self._action_row(self._announcement())

    def test_roster_single_action_row(self):
        self._action_row(self._roster())

    # --- check-in buttons ------------------------------------------------

    def _buttons(self, result: dict) -> list[dict]:
        return self._action_row(result)["components"]

    def test_announcement_scout_button_present(self):
        btns = self._buttons(self._announcement())
        labels = [b["label"] for b in btns]
        assert "Scout Check-in" in labels

    def test_announcement_support_button_present(self):
        btns = self._buttons(self._announcement())
        labels = [b["label"] for b in btns]
        assert "Support Check-in" in labels

    def test_roster_scout_button_present(self):
        btns = self._buttons(self._roster())
        labels = [b["label"] for b in btns]
        assert "Scout Check-in" in labels

    def test_roster_support_button_present(self):
        btns = self._buttons(self._roster())
        labels = [b["label"] for b in btns]
        assert "Support Check-in" in labels

    # --- custom_ids contain operation_id ---------------------------------

    def test_announcement_scout_custom_id_contains_operation_id(self):
        op     = _operation()
        result = format_operation_announcement(op)
        btns   = self._buttons(result)
        scout  = next(b for b in btns if b["label"] == "Scout Check-in")
        assert f"checkin:scout:{op['id']}" == scout["custom_id"]

    def test_announcement_support_custom_id_contains_operation_id(self):
        op      = _operation()
        result  = format_operation_announcement(op)
        btns    = self._buttons(result)
        support = next(b for b in btns if b["label"] == "Support Check-in")
        assert f"checkin:support:{op['id']}" == support["custom_id"]

    def test_roster_scout_custom_id_contains_operation_id(self):
        op   = _operation()
        s    = _slots()
        asmt = _assignments([], [])
        result = format_roster(op, s, asmt)
        btns   = self._buttons(result)
        scout  = next(b for b in btns if b["label"] == "Scout Check-in")
        assert f"checkin:scout:{op['id']}" == scout["custom_id"]

    # --- link button (signup_url) ----------------------------------------

    def test_announcement_no_link_button_without_signup_url(self):
        btns   = self._buttons(self._announcement())
        labels = [b["label"] for b in btns]
        assert "Open Signup Page" not in labels

    def test_announcement_link_button_present_with_signup_url(self):
        url    = "https://ironkeep.example.com/workspaces/w1/operations/op1/signup"
        btns   = self._buttons(self._announcement(signup_url=url))
        labels = [b["label"] for b in btns]
        assert "Open Signup Page" in labels

    def test_announcement_link_button_style_is_5(self):
        url  = "https://ironkeep.example.com/workspaces/w1/operations/op1/signup"
        btns = self._buttons(self._announcement(signup_url=url))
        link = next(b for b in btns if b["label"] == "Open Signup Page")
        assert link["style"] == 5
        assert link["url"] == url
        assert "custom_id" not in link

    def test_announcement_check_in_buttons_have_no_url(self):
        url  = "https://ironkeep.example.com/workspaces/w1/operations/op1/signup"
        btns = self._buttons(self._announcement(signup_url=url))
        for btn in btns:
            if btn["label"] in ("Scout Check-in", "Support Check-in"):
                assert "url" not in btn
                assert "custom_id" in btn

    def test_roster_link_button_present_with_signup_url(self):
        url    = "https://ironkeep.example.com/workspaces/w1/operations/op1/signup"
        btns   = self._buttons(self._roster(signup_url=url))
        labels = [b["label"] for b in btns]
        assert "Open Signup Page" in labels

    # --- serialisability -------------------------------------------------

    def test_announcement_with_components_json_serializable(self):
        url    = "https://ironkeep.example.com/workspaces/w1/operations/op1/signup"
        result = self._announcement(signup_url=url)
        json.dumps(result)

    def test_roster_with_components_json_serializable(self):
        url    = "https://ironkeep.example.com/workspaces/w1/operations/op1/signup"
        result = self._roster(signup_url=url)
        json.dumps(result)
