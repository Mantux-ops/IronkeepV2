"""Tank signup routing against the 740c91a production handler.

The Tank button and ticket controls share the ikt prefix. These tests call the
routing decision used by the production handler. They do not contact Discord.
"""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import discord

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ironkeep import bot, wow


def _interaction(kind=None):
    return SimpleNamespace(
        id="interaction-1",
        token="secret-token",
        type=kind or discord.InteractionType.component,
        user=SimpleNamespace(name="Ada"),
    )


def _run(custom_id, data=None, kind=None):
    return asyncio.run(
        bot.dispatch_ikt(
            _interaction(kind),
            custom_id,
            "guild",
            "user",
            "Ada",
            ["role"],
            data or {},
        )
    )


class TankRoutingTests(unittest.TestCase):
    def test_posted_button_ids_are_unchanged(self):
        ids = [
            component["custom_id"]
            for row in wow._action_rows(123)
            for component in row["components"]
        ]
        self.assertEqual(
            ids[:5],
            ["ikt:123", "ikm:123", "ikn:123", "ikh:123", "ike:123"],
        )

    def test_tank_id_is_classified_as_signup(self):
        self.assertEqual(bot.ikt_destination("ikt:123"), "signup")
        self.assertIsNone(bot.ikt_destination("ikm:123"))
        self.assertIsNone(bot.ikt_destination("ikn:123"))
        self.assertIsNone(bot.ikt_destination("ikh:123"))

    def test_tank_click_is_not_consumed_by_tickets(self):
        with patch("ironkeep.bot.tickets.answer") as answer, patch(
            "ironkeep.bot.interaction_callback"
        ) as callback, patch("ironkeep.bot.wow.handle_component") as signup:
            finished = _run("ikt:123")
        self.assertFalse(finished)
        answer.assert_not_called()
        callback.assert_not_called()
        signup.assert_not_called()

    def test_other_role_buttons_are_not_consumed(self):
        for custom_id in ("ikm:123", "ikn:123", "ikh:123"):
            with self.subTest(custom_id=custom_id):
                with patch("ironkeep.bot.tickets.answer") as answer:
                    finished = _run(custom_id)
                self.assertFalse(finished)
                answer.assert_not_called()

    def test_handler_still_reaches_signup_after_the_ikt_check(self):
        source = Path(bot.__file__).read_text(encoding="utf-8")
        start = source.index("async def on_interaction")
        handler = source[start:source.index("async def _hourly", start)]
        decision = handler.index("await dispatch_ikt(")
        signup = handler.index("wow.handle_component")
        self.assertLess(decision, signup)
        self.assertNotIn('startswith("ikt")', handler)
        self.assertIn("await asyncio.to_thread(wow.run_schedule)", source)
        self.assertNotIn("temp_voice_snapshot", source)


class TicketRoutingTests(unittest.TestCase):
    def test_ticket_actions_reach_tickets(self):
        samples = ("ikt:open", "ikt:form:0", "ikt:claim:abc", "ikt:close:abc")
        for custom_id in samples:
            with self.subTest(custom_id=custom_id):
                self.assertEqual(bot.ikt_destination(custom_id), "ticket")
                with patch("ironkeep.bot.tickets.answer") as answer, patch(
                    "ironkeep.bot.wow.handle_component"
                ) as signup:
                    finished = _run(custom_id, {"values": ["1"]})
                self.assertTrue(finished)
                answer.assert_called_once()
                self.assertEqual(answer.call_args.args[4], custom_id)
                signup.assert_not_called()

    def test_ticket_form_passes_modal_fields(self):
        data = {
            "components": [
                {"components": [{"custom_id": "subject", "value": "Help"}]}
            ]
        }
        with patch("ironkeep.bot.tickets.answer") as answer:
            finished = _run(
                "ikt:form:0",
                data,
                discord.InteractionType.modal_submit,
            )
        self.assertTrue(finished)
        self.assertEqual(answer.call_args.args[4], "ikt:form:0")
        self.assertEqual(answer.call_args.args[8], {"subject": "Help"})

    def test_malformed_ikt_is_rejected_without_signup_or_tickets(self):
        for custom_id in ("ikt:0", "ikt:0123", "ikt:12a", "ikt:123:9", "ikt:", "ikt:openextra"):
            with self.subTest(custom_id=custom_id):
                self.assertEqual(bot.ikt_destination(custom_id), "reject")
                with patch("ironkeep.bot.tickets.answer") as answer, patch(
                    "ironkeep.bot.wow.handle_component"
                ) as signup, patch("ironkeep.bot.interaction_callback") as callback:
                    finished = _run(custom_id)
                self.assertTrue(finished)
                answer.assert_not_called()
                signup.assert_not_called()
                self.assertEqual(callback.call_args.kwargs["kind"], 4)
                self.assertNotIn("secret-token", str(callback.call_args.kwargs["data"]))

    def test_failed_rejection_does_not_escape(self):
        with patch("ironkeep.bot.interaction_callback", side_effect=OSError("down")):
            finished = _run("ikt:12a")
        self.assertTrue(finished)

    def test_ticket_exception_does_not_reach_signup(self):
        with patch("ironkeep.bot.tickets.answer", side_effect=RuntimeError("boom")), patch(
            "ironkeep.bot.wow.handle_component"
        ) as signup:
            with self.assertLogs("ironkeep.bot", level="ERROR") as logs:
                finished = _run("ikt:open")
        self.assertTrue(finished)
        signup.assert_not_called()
        self.assertIn("Ticket action failed", "\n".join(logs.output))
        self.assertNotIn("secret-token", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
