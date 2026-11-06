"""Resolve the commit a Companion workflow is allowed to build."""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
TAG = re.compile(r"^companion-v[0-9]+\.[0-9]+\.[0-9]+$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def classify(requested, event_name):
    if event_name != "workflow_dispatch":
        return "push"
    requested = (requested or "").strip()
    if requested.lower() == "companion-latest":
        raise SystemExit("companion-latest is not a release source.")
    if COMMIT.fullmatch(requested):
        return "commit"
    if TAG.fullmatch(requested):
        return "tag"
    raise SystemExit("Pass a full commit SHA or an existing companion-vX.Y.Z tag.")


def read_version(root):
    session = (root / "companion/Ironkeep.Companion.Core/CompanionSession.cs").read_text(encoding="utf-8")
    project = (root / "companion/Ironkeep.Companion/Ironkeep.Companion.csproj").read_text(encoding="utf-8")
    displayed = re.search(r'const string Version = "([^"]+)"', session)
    packaged = re.search(r"<Version>([^<]+)</Version>", project)
    assembly = re.search(r"<AssemblyVersion>([^<]+)</AssemblyVersion>", project)
    file_version = re.search(r"<FileVersion>([^<]+)</FileVersion>", project)
    if displayed is None or packaged is None or assembly is None or file_version is None:
        raise SystemExit("The Companion version is missing.")
    version = displayed.group(1).strip()
    if not VERSION.fullmatch(version) or packaged.group(1).strip() != version:
        raise SystemExit("The displayed version and the project version disagree.")
    if assembly.group(1).strip() != version + ".0" or file_version.group(1).strip() != version + ".0":
        raise SystemExit("The assembly version does not match the displayed version.")
    return version


def resolve_head(requested, event_name):
    kind = classify(requested, event_name)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not COMMIT.fullmatch(head):
        raise SystemExit("HEAD is not a full commit SHA.")
    if kind == "commit" and head.lower() != requested.strip().lower():
        raise SystemExit("Checked out " + head + " instead of " + requested.strip() + ".")
    if kind == "tag":
        tag = requested.strip()
        shown = subprocess.check_output(["git", "rev-parse", "--verify", "refs/tags/" + tag], text=True).strip()
        if not shown:
            raise SystemExit(tag + " is not a tag.")
        resolved = subprocess.check_output(["git", "rev-parse", tag + "^{commit}"], text=True).strip()
        if resolved != head:
            raise SystemExit(tag + " points at " + resolved + ", not " + head + ".")
    return head


def main():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    requested = os.environ.get("SOURCE_REF", "")
    head = resolve_head(requested, event_name)
    version = read_version(ROOT)
    print("source " + head)
    print("version " + version)
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("commit=" + head + "\n")
            handle.write("version=" + version + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
