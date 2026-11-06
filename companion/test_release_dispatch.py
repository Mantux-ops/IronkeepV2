"""Protections for the manual Companion release dispatch."""

import subprocess
import unittest
from pathlib import Path

import publish_release
import release_source

ROOT = Path(__file__).resolve().parents[1]
REVIEWED = "4e6955dd24d79469612eabbba185a2eb160b4426"
MAIN = "a70c8363f6f5db3d299258c3ee354e2b57582705"
CALLER = "b" * 40


class SourceSelectionTest(unittest.TestCase):
    def test_dispatch_accepts_only_a_full_commit_sha(self):
        self.assertEqual(release_source.classify(REVIEWED, "workflow_call"), "commit")
        for requested in ("companion-latest", "main", "adbb07d", "companion-v2.0.1", "cursor/companion-report-keep-f675", ""):
            with self.assertRaises(SystemExit):
                release_source.classify(requested, "workflow_call")

    def test_reviewed_commit_is_on_the_development_branch_and_main_is_not(self):
        self.assertEqual(release_source.require_reviewed(REVIEWED), REVIEWED)
        with self.assertRaises(SystemExit) as raised:
            release_source.require_reviewed(MAIN)
        self.assertIn("is not on", str(raised.exception))

    def test_missing_commit_is_rejected_before_a_build(self):
        with self.assertRaises(SystemExit):
            release_source.require_reviewed("0" * 40)

    def test_selected_commit_can_differ_from_the_caller_checkout(self):
        commit, version = release_source.selected_commit(REVIEWED, "workflow_call")
        self.assertEqual(commit, REVIEWED)
        self.assertEqual(version, "2.0.1")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        self.assertNotEqual(head, "")


class DryRunTest(unittest.TestCase):
    def test_publish_is_off_unless_it_is_explicitly_confirmed(self):
        source = "a" * 40
        self.assertEqual(publish_release.publication_gate(source, source, False, ""), "dry-run")
        self.assertEqual(publish_release.publication_gate(source, source, "false", "publish"), "dry-run")
        self.assertFalse(release_source.should_publish("workflow_call", False, "publish"))
        self.assertTrue(release_source.should_build("workflow_call", False, ""))
        with self.assertRaises(SystemExit) as raised:
            publish_release.publication_gate(source, source, True, "")
        self.assertIn("confirm=publish", str(raised.exception))
        self.assertFalse(release_source.should_build("workflow_call", True, "no"))
        self.assertFalse(release_source.should_publish("push", True, "publish"))

    def test_publish_entrypoint_refuses_a_dry_run_without_calling_gh(self):
        with self.assertRaises(SystemExit) as raised:
            publish_release.main([])
        self.assertIn("Refusing to publish", str(raised.exception))


class PublicationSafeguardTest(unittest.TestCase):
    def test_caller_sha_may_differ_from_the_selected_source(self):
        source = "c" * 40
        self.assertNotEqual(source, CALLER)
        self.assertEqual(publish_release.publication_gate(source, source, True, "publish"), "publish")
        self.assertEqual(release_source.script_commit("workflow_call", CALLER, source), source)
        with self.assertRaises(SystemExit):
            release_source.script_commit("workflow_call", CALLER, "")

    def test_a_different_built_commit_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            publish_release.publication_gate("c" * 40, "d" * 40, True, "publish")
        self.assertIn("built commit", str(raised.exception))

    def test_script_pin_must_match_the_running_workflow_file(self):
        pin = "e" * 40
        self.assertEqual(release_source.require_script_pin("workflow_call", pin, pin.upper()), pin)
        with self.assertRaises(SystemExit):
            release_source.require_script_pin("workflow_call", pin, "f" * 40)
        self.assertEqual(release_source.require_script_pin("push", "", ""), "")

    def test_existing_companion_latest_and_versioned_tags_are_not_replaced(self):
        with self.assertRaises(SystemExit) as raised:
            publish_release.refuse_tag("companion-latest")
        self.assertIn("companion-latest", str(raised.exception))
        with self.assertRaises(SystemExit):
            publish_release.refuse_tag("latest")
        self.assertTrue(publish_release.release_already_published(0, ""))
        self.assertTrue(publish_release.release_already_published(1, "abc\trefs/tags/companion-v2.0.1\n"))
        self.assertFalse(publish_release.release_already_published(1, ""))
        text = Path(publish_release.__file__).read_text(encoding="utf-8")
        self.assertNotIn("gh release delete", text)
        self.assertIn('"--cleanup-tag" in command', text)

    def test_release_command_targets_the_source_commit_and_not_latest(self):
        plan = {
            "tag": "companion-v2.0.1",
            "commit": "a" * 40,
            "title": "Ironkeep Companion 2.0.1",
            "assets": [Path("release") / "IronkeepCompanion.exe"],
        }
        command = publish_release.release_command(plan, Path("notes.md"))
        self.assertEqual(command[0:4], ["gh", "release", "create", "companion-v2.0.1"])
        self.assertIn("a" * 40, command)
        self.assertIn("--latest=false", command)
        self.assertNotIn("companion-latest", command)
        self.assertNotIn("delete", command)


if __name__ == "__main__":
    unittest.main()
