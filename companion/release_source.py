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
REVIEWED_BRANCH = "cursor/companion-report-keep-f675"


def classify(requested, event_name):
    if event_name in ("", "push"):
        return "push"
    if event_name not in ("workflow_dispatch", "workflow_call"):
        raise SystemExit("This event cannot select a Companion source.")
    requested = (requested or "").strip()
    if requested.lower() == "companion-latest":
        raise SystemExit("companion-latest is not a release source.")
    if event_name == "workflow_call":
        if not COMMIT.fullmatch(requested):
            raise SystemExit("The release dispatch requires a full commit SHA.")
        return "commit"
    if COMMIT.fullmatch(requested):
        return "commit"
    if TAG.fullmatch(requested):
        return "tag"
    raise SystemExit("Pass a full commit SHA or an existing companion-vX.Y.Z tag.")


def read_version(root):
    session = (root / "companion/Ironkeep.Companion.Core/CompanionSession.cs").read_text(encoding="utf-8")
    project = (root / "companion/Ironkeep.Companion/Ironkeep.Companion.csproj").read_text(encoding="utf-8")
    return version_from_text(session, project)


def version_from_text(session, project):
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


def should_build(event_name, publish, confirm):
    if event_name in ("", "push"):
        return True
    return not (truthy(publish) and confirm != "publish")


def should_publish(event_name, publish, confirm):
    if event_name in ("", "push"):
        return False
    return truthy(publish) and confirm == "publish"


def truthy(value):
    return str(value).strip().lower() in ("true", "1")


def script_commit(event_name, github_sha, job_workflow_sha):
    """Return the commit whose release scripts this run may execute.

    A reusable workflow's github.sha is the caller, which on main is not the
    Companion commit and does not contain these scripts. job.workflow_sha is
    the commit of the workflow file that is actually running.
    """
    if event_name in ("", "push"):
        if not COMMIT.fullmatch(github_sha or ""):
            raise SystemExit("The pushed commit is not a full SHA.")
        return github_sha.lower()
    if not COMMIT.fullmatch(job_workflow_sha or ""):
        raise SystemExit("The workflow file commit is missing.")
    return job_workflow_sha.lower()


def require_script_pin(event_name, scripts_input, job_workflow_sha):
    if event_name != "workflow_call":
        return ""
    pinned = script_commit(event_name, "", job_workflow_sha)
    if not COMMIT.fullmatch(scripts_input or "") or scripts_input.lower() != pinned:
        raise SystemExit("The dispatcher pin does not match the workflow file that is running.")
    return pinned


def fetch_commit(commit):
    if not COMMIT.fullmatch(commit):
        raise SystemExit("A reviewed source must be a full commit SHA.")
    kind = subprocess.run(
        ["git", "cat-file", "-t", commit],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if kind.returncode == 0 and kind.stdout.strip() == "commit":
        return commit.lower()
    fetched = subprocess.run(
        ["git", "fetch", "origin", commit],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if fetched.returncode != 0:
        raise SystemExit(commit + " is not a commit in this repository.")
    return commit.lower()


def require_reviewed(commit, branch=REVIEWED_BRANCH):
    commit = fetch_commit(commit)
    fetched = subprocess.run(
        ["git", "fetch", "origin", branch],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if fetched.returncode != 0:
        raise SystemExit("Could not read " + branch + ".")
    check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/" + branch],
        check=False,
    )
    if check.returncode != 0:
        raise SystemExit(commit + " is not on " + branch + ".")
    return commit


def read_version_from_commit(commit):
    session = subprocess.check_output(
        ["git", "show", commit + ":companion/Ironkeep.Companion.Core/CompanionSession.cs"],
        text=True,
    )
    project = subprocess.check_output(
        ["git", "show", commit + ":companion/Ironkeep.Companion/Ironkeep.Companion.csproj"],
        text=True,
    )
    return version_from_text(session, project)


def selected_commit(requested, event_name):
    kind = classify(requested, event_name)
    if kind == "push":
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        if not COMMIT.fullmatch(head):
            raise SystemExit("HEAD is not a full commit SHA.")
        return head.lower(), read_version(ROOT)
    if kind == "tag":
        tag = requested.strip()
        subprocess.check_call(["git", "fetch", "origin", "tag", tag, "--force"])
        commit = subprocess.check_output(["git", "rev-parse", tag + "^{commit}"], text=True).strip()
    else:
        commit = requested.strip()
    commit = require_reviewed(commit)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head.lower() == commit:
        version = read_version(ROOT)
    else:
        version = read_version_from_commit(commit)
    return commit, version


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
    require_script_pin(event_name, os.environ.get("SCRIPTS_INPUT", ""), os.environ.get("JOB_WORKFLOW_SHA", ""))
    head, version = selected_commit(requested, event_name)
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
