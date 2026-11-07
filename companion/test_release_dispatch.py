"""Protections for the manual Companion release dispatch."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_release
import release_source

ROOT = Path(__file__).resolve().parents[1]
REVIEWED = "4e6955dd24d79469612eabbba185a2eb160b4426"
ROSTER = "73624d35efaf5b407d6ce5d8ddbf5f4725f8285b"
UNMERGED = "460875b3e2f81fae4a86f031c582da4c9650ac34"
CALLER = "b" * 40


class SourceSelectionTest(unittest.TestCase):
    def test_dispatch_accepts_only_a_full_commit_sha(self):
        self.assertEqual(release_source.classify(REVIEWED, "workflow_call"), "commit")
        for requested in ("companion-latest", "main", "adbb07d", "companion-v2.0.1", "cursor/companion-report-keep-f675", ""):
            with self.assertRaises(SystemExit):
                release_source.classify(requested, "workflow_call")

    def test_a_reviewed_commit_on_main_is_accepted(self):
        self.assertEqual(release_source.require_reviewed(ROSTER), ROSTER)
        self.assertEqual(release_source.require_reviewed(REVIEWED), REVIEWED)

    def test_a_commit_that_is_not_on_main_is_rejected(self):
        with self.assertRaises(SystemExit) as raised:
            release_source.require_reviewed(UNMERGED)
        self.assertIn("is not on main", str(raised.exception))

    def test_abbreviated_and_invalid_shas_are_rejected(self):
        for requested in ("73624d3", "adbb07d", "main", "0" * 39, "g" * 40):
            with self.assertRaises(SystemExit):
                release_source.require_reviewed(requested)

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

    def test_a_caller_dispatch_is_not_a_direct_dispatch(self):
        pin = "e" * 40
        self.assertEqual(release_source.invocation("workflow_dispatch", CALLER, pin), "workflow_call")
        self.assertEqual(release_source.invocation("push", CALLER, pin), "workflow_call")
        self.assertEqual(release_source.classify("c" * 40, "workflow_dispatch", CALLER, pin), "commit")
        with self.assertRaises(SystemExit):
            release_source.classify("companion-v2.0.1", "workflow_dispatch", CALLER, pin)
        self.assertEqual(release_source.require_script_pin("workflow_dispatch", pin, pin, CALLER), pin)
        with self.assertRaises(SystemExit):
            release_source.require_script_pin("workflow_dispatch", CALLER, pin, CALLER)
        with self.assertRaises(SystemExit):
            release_source.require_script_pin("workflow_dispatch", pin, "", CALLER)

    def test_a_direct_dispatch_can_still_select_a_version_tag(self):
        pin = "e" * 40
        self.assertEqual(release_source.invocation("workflow_dispatch", pin, pin.upper()), "workflow_dispatch")
        self.assertEqual(release_source.invocation("push", pin, pin), "push")
        self.assertEqual(release_source.classify("companion-v2.0.1", "workflow_dispatch", pin, pin), "tag")
        self.assertEqual(release_source.require_script_pin("workflow_dispatch", "", pin, pin), pin)

    def test_release_job_uses_the_workflow_file_and_not_the_source_commit(self):
        workflow = (ROOT / ".github/workflows/companion.yml").read_text(encoding="utf-8")
        self.assertNotIn("actions: write", workflow)
        release = workflow.split("  release:", 1)[1]
        checkout = release.split("uses: actions/checkout@v4", 1)[1].split("uses: actions/setup-python", 1)[0]
        self.assertIn("job.workflow_repository", checkout)
        self.assertIn("job.workflow_sha", checkout)
        self.assertNotIn("needs.guard.outputs.commit", checkout)
        self.assertNotIn("github.sha", checkout)
        self.assertIn("success()", release)
        self.assertLess(workflow.index("Scan with Microsoft Defender"), workflow.index("name: companion-wpf-release"))
        api = workflow.split("  api:", 1)[1].split("  windows:", 1)[0]
        trusted = api.split("- name: Check out the trusted release scripts", 1)[1].split("- name: Confirm the trusted release scripts", 1)[0]
        check = api.split("- name: Check the release workflow", 1)[1].split("- name: Test the attendance route", 1)[0]
        self.assertIn("path: trusted", trusted)
        self.assertIn("job.workflow_sha", trusted)
        self.assertNotIn("needs.guard.outputs.commit", trusted)
        self.assertIn("working-directory: trusted", check)
        self.assertIn("ref: ${{ needs.guard.outputs.commit }}", api)
        self.assertNotIn("working-directory: trusted", api.split("- name: Test the attendance route", 1)[1])

    def test_publish_entrypoint_stops_before_gh(self):
        pin = "e" * 40
        source = "c" * 40
        cases = [
            {"SCRIPTS_INPUT": "f" * 40, "SOURCE_REF": source, "EXPECTED_COMMIT": source, "PUBLISH_CONFIRM": "publish"},
            {"SCRIPTS_INPUT": pin, "SOURCE_REF": source, "EXPECTED_COMMIT": "d" * 40, "PUBLISH_CONFIRM": "publish"},
            {"SCRIPTS_INPUT": pin, "SOURCE_REF": source, "EXPECTED_COMMIT": source, "PUBLISH_CONFIRM": ""},
        ]
        for extra in cases:
            env = {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_SHA": CALLER,
                "JOB_WORKFLOW_SHA": pin,
                "PUBLISH_REQUESTED": "true",
                "EXPECTED_VERSION": "2.0.1",
            }
            env.update(extra)
            with patch.dict(os.environ, env, clear=False):
                with patch("publish_release.subprocess.run") as queried:
                    with patch("publish_release.subprocess.check_call") as created:
                        with self.assertRaises(SystemExit):
                            publish_release.main(["--publish"])
                        queried.assert_not_called()
                        created.assert_not_called()

    def test_publish_entrypoint_does_not_replace_an_existing_tag(self):
        pin = "e" * 40
        source = "c" * 40
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = b"MZ" + (b"\0" * publish_release.MIN_EXECUTABLE_BYTES)
            for name in publish_release.RELEASE_FILES:
                (root / name).write_bytes(payload)
            sums = "".join(publish_release._sha256(root / name) + "  " + name + "\n" for name in publish_release.RELEASE_FILES)
            (root / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
            (root / "BUILD.txt").write_text("version=2.0.1\ncommit=" + source + "\n", encoding="utf-8")
            (root / "SCANNED.txt").write_text("defender=pass\ncommit=" + source + "\n", encoding="utf-8")
            (root / "release-notes.md").write_text("Discord authentication\nSavedVariables layout\n", encoding="utf-8")
            env = {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_SHA": CALLER,
                "JOB_WORKFLOW_SHA": pin,
                "SCRIPTS_INPUT": pin,
                "SOURCE_REF": source,
                "EXPECTED_COMMIT": source,
                "PUBLISH_REQUESTED": "true",
                "PUBLISH_CONFIRM": "publish",
                "EXPECTED_VERSION": "2.0.1",
                "RELEASE_DIR": str(root),
            }
            view = subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="existing", stderr="")
            listed = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="abc\trefs/tags/companion-v2.0.1\n", stderr="")
            with patch.dict(os.environ, env, clear=False):
                with patch("publish_release.subprocess.run", side_effect=[view, listed]) as queried:
                    with patch("publish_release.subprocess.check_call") as created:
                        with self.assertRaises(SystemExit) as raised:
                            publish_release.main(["--publish"])
                        self.assertIn("will not be replaced", str(raised.exception))
                        created.assert_not_called()
                        for call in queried.call_args_list:
                            self.assertNotIn("delete", call.args[0])

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
