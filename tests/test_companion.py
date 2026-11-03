import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from companion.ironkeep_companion import SavedError, load_path, load_saved, main, newest, report, saved_files, text_for

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "companion" / "sample-Ironkeep.lua"


class SavedReadTests(unittest.TestCase):
    def test_sample_matches_the_copy_list(self):
        db = load_path(SAMPLE)
        text = report(db["session"], started_at="2026-11-01 12:00")
        self.assertEqual(
            text,
            "\n".join([
                "Ironkeep group",
                "Place: Hall of Thanes",
                "Started: 2026-11-01 12:00",
                "",
                "Name | Class | Role | Time | Status",
                "Ada Smith | Warrior | Tank | 20m | here",
                "Bram Holt | Priest | Healer | 10m | here",
                "Dain Frost | Mage | Damage | 5m | left",
                "",
                "format: ironkeep-group 1",
            ]),
        )

    def test_previous_report_is_kept_when_the_session_was_cleared(self):
        db = load_saved('IronkeepDB = { ["lastReport"] = "Ironkeep group\\n\\nformat: ironkeep-group 1" }\n')
        self.assertEqual(text_for(db), "Ironkeep group\n\nformat: ironkeep-group 1")

    def test_a_call_in_the_file_is_refused(self):
        with self.assertRaises(SavedError):
            load_saved('IronkeepDB = { ["session"] = os.execute("rm") }\n')

    def test_missing_list_is_refused(self):
        with self.assertRaises(SavedError):
            load_saved("SomethingElse = {}\n")

    def test_newest_account_file_is_chosen(self):
        with tempfile.TemporaryDirectory() as folder:
            wow = Path(folder)
            older = wow / "WTF" / "Account" / "Old" / "SavedVariables" / "Ironkeep.lua"
            newer = wow / "WTF" / "Account" / "New" / "SavedVariables" / "Ironkeep.lua"
            older.parent.mkdir(parents=True)
            newer.parent.mkdir(parents=True)
            older.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            newer.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            import os
            os.utime(older, (1_000, 1_000))
            os.utime(newer, (2_000, 2_000))
            files = saved_files(wow)
            self.assertEqual(newest(files), newer)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--wow", str(wow)])
            self.assertEqual(code, 0)
            self.assertIn("Account: New", stderr.getvalue())
            self.assertIn("Ada Smith | Warrior | Tank | 20m | here", stdout.getvalue())
            self.assertIn("format: ironkeep-group 1", stdout.getvalue())

    def test_sample_command_prints_the_group(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--sample"])
        self.assertEqual(code, 0)
        self.assertIn("Hall of Thanes", stdout.getvalue())
        self.assertIn("Dain Frost | Mage | Damage | 5m | left", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
