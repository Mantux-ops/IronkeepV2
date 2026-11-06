"""Validate the Companion release workflow without publishing anything."""

import re
import sys
from pathlib import Path

import publish_release
import release_source

ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise SystemExit(message)


def main():
    workflow = (ROOT / ".github/workflows/companion.yml").read_text(encoding="utf-8")
    notes = (ROOT / "companion/release-notes.md").read_text(encoding="utf-8")
    installer = (ROOT / "companion/wpf-setup.iss").read_text(encoding="utf-8")
    legacy = (ROOT / "companion/setup.iss").read_text(encoding="utf-8")
    version = release_source.read_version(ROOT)
    if version != "2.0.1":
        fail("The prepared release version is " + version + ".")
    if "Discord" not in notes or "SavedVariables" not in notes:
        fail("The release notes do not describe Discord authentication and the SavedVariables layout.")
    if "companion-latest" not in notes:
        fail("The release notes do not say that companion-latest stays in place.")
    if 'Source: "out\\wpf\\IronkeepCompanion.exe"' not in installer:
        fail("The WPF installer does not package the published WPF executable.")
    if "IronkeepCompanion.exe.config" in installer:
        fail("The WPF installer still packages the legacy configuration file.")
    if "{#AppVersion}" not in installer:
        fail("The WPF installer does not take the application version from the build.")
    if 'Source: "out\\IronkeepCompanion.exe"' not in legacy:
        fail("The legacy installer script was changed.")
    if "gh release delete" in workflow or "cleanup-tag" in workflow:
        fail("The workflow can still delete a release.")
    if re.search(r"gh release create companion-latest", workflow):
        fail("The workflow still publishes companion-latest.")
    if "companion-v" not in workflow and "plan[\"tag\"]" not in workflow:
        if "publish_release.py --publish" not in workflow:
            fail("The workflow does not publish an immutable version tag.")
    if "workflow_dispatch:" not in workflow or "source:" not in workflow or "publish:" not in workflow:
        fail("The workflow does not require an explicit source.")
    if "needs: [api, windows]" not in workflow:
        fail("Publication does not wait for the tests and the Windows build.")
    if "Scan with Microsoft Defender" not in workflow or "SCANNED.txt" not in workflow:
        fail("Publication does not require a Defender scan.")
    if "companion-wpf-release" not in workflow:
        fail("The release artifact is not the WPF package.")
    if "out\\release\\IronkeepCompanion.exe" not in workflow:
        fail("Defender does not scan the WPF executable that would be published.")
    for requested in ("companion-latest", "main", "adbb07d", "companion-v2"):
        try:
            release_source.classify(requested, "workflow_dispatch")
        except SystemExit:
            continue
        fail(requested + " was accepted as a release source.")
    if release_source.classify("a" * 40, "workflow_dispatch") != "commit":
        fail("A full commit SHA was rejected.")
    if release_source.classify("companion-v2.0.1", "workflow_dispatch") != "tag":
        fail("An immutable version tag was rejected.")
    if release_source.classify("", "push") != "push":
        fail("A push build was treated as a release.")
    publish_release.self_test()
    print("release workflow check ok")
    print("version " + version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
