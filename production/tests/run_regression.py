"""Run the local Ironkeep regression suites.

This is automated coverage only. It does not repeat isolated live validation,
and it does not contact production or the validation server.

The website suite imports the repository-root package. The publication suite
imports production/ironkeep. They have to run in separate processes.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    (
        "publication and close",
        [
            "production.tests.test_publication_claims",
            "production.tests.test_raid_close",
        ],
    ),
    (
        "signup and companion",
        [
            "production.tests.test_signup_routing",
            "production.tests.test_companion_phase1",
        ],
    ),
    (
        "website, attendance, authentication",
        [
            "tests.test_website_login",
            "tests.test_attendance",
            "tests.test_companion_auth",
        ],
    ),
)


def main():
    print("Automated regression. This does not repeat the completed live validation.")
    failed = False
    for label, modules in SUITES:
        print(f"\n== {label} ==")
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", *modules],
            cwd=ROOT,
        )
        if completed.returncode != 0:
            failed = True
            print(f"FAILED: {label}")
        else:
            print(f"PASSED: {label}")
    if failed:
        print("\nRegression failed.")
        return 1
    print("\nRegression passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
