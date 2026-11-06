"""Check a scanned WPF build and describe the immutable release it can become.

Running this file does not publish anything. Publication happens only when the
workflow passes --publish, and even then an existing tag stops the command.
"""

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import release_source

COMMIT = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HASH = re.compile(r"^[0-9a-f]{64}$")
MIN_EXECUTABLE_BYTES = 10_000_000
RELEASE_FILES = ("IronkeepCompanionSetup.exe", "IronkeepCompanion.exe")


def _field(text, name):
    for line in text.splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(name + " is missing from the release metadata.")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_release(directory, expected_commit, expected_version):
    directory = Path(directory)
    build = (directory / "BUILD.txt").read_text(encoding="utf-8")
    scanned = (directory / "SCANNED.txt").read_text(encoding="utf-8")
    notes = (directory / "release-notes.md").read_text(encoding="utf-8").strip()
    version = _field(build, "version")
    commit = _field(build, "commit").lower()
    if version != expected_version or not VERSION.fullmatch(version):
        raise SystemExit("The built version does not match the reviewed source.")
    if commit != expected_commit.lower() or not COMMIT.fullmatch(commit):
        raise SystemExit("The built commit does not match the reviewed source.")
    if _field(scanned, "defender") != "pass" or _field(scanned, "commit").lower() != commit:
        raise SystemExit("Microsoft Defender did not pass for this commit.")
    if "Discord" not in notes or "SavedVariables" not in notes:
        raise SystemExit("The release notes are missing the required description.")
    sums = {}
    for line in (directory / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() == "":
            continue
        digest, name = line.split(None, 1)
        sums[name.strip()] = digest.strip().lower()
    assets = []
    for name in RELEASE_FILES:
        path = directory / name
        if not path.is_file():
            raise SystemExit(name + " is not in the release directory.")
        if path.stat().st_size < MIN_EXECUTABLE_BYTES:
            raise SystemExit(name + " is too small to be the self-contained WPF application.")
        actual = _sha256(path)
        if sums.get(name) != actual or not HASH.fullmatch(actual):
            raise SystemExit("SHA256 for " + name + " does not match the file.")
        assets.append(path)
    tag = "companion-v" + version
    if tag == "companion-latest":
        raise SystemExit("Refusing to publish companion-latest.")
    body = notes + "\n\nSource commit: " + commit + "\nVersion: " + version + "\n\nSHA256\n"
    body += "\n".join(sums[name] + "  " + name for name in RELEASE_FILES) + "\n"
    return {
        "tag": tag,
        "commit": commit,
        "version": version,
        "title": "Ironkeep Companion " + version,
        "notes": body,
        "assets": assets,
    }


def publication_gate(source, built_commit, publish, confirm):
    """Return dry-run or publish. The caller workflow SHA is intentionally absent.

    github.sha on a dispatch from main is main's commit. The built Companion
    commit is the selected source, and those two are not the same.
    """
    if not truthy(publish):
        return "dry-run"
    if confirm != "publish":
        raise SystemExit("Publication requires confirm=publish.")
    if not COMMIT.fullmatch(source or "") or not COMMIT.fullmatch(built_commit or ""):
        raise SystemExit("Publication requires the full source commit SHA.")
    if source.lower() != built_commit.lower():
        raise SystemExit("Refusing to publish because the built commit is not the requested source.")
    return "publish"


def truthy(value):
    return str(value).strip().lower() in ("true", "1")


def refuse_tag(tag):
    if tag == "companion-latest" or not str(tag).startswith("companion-v"):
        raise SystemExit("Refusing to publish " + str(tag) + ".")


def release_already_published(view_code, remote_text):
    return view_code == 0 or bool((remote_text or "").strip())


def ensure_absent(tag):
    refuse_tag(tag)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    view = ["gh", "release", "view", tag]
    remote = ["git", "ls-remote", "--tags", "origin", "refs/tags/" + tag]
    if repo:
        view.extend(["--repo", repo])
    existing = subprocess.run(view, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    listed = subprocess.run(remote, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if listed.returncode != 0:
        raise SystemExit("Could not check existing tags.")
    if release_already_published(existing.returncode, listed.stdout):
        raise SystemExit(tag + " already exists and will not be replaced.")


def release_command(plan, notes_path):
    command = [
        "gh", "release", "create", plan["tag"],
        *[str(path) for path in plan["assets"]],
        str(Path(plan["assets"][0]).parent / "SHA256SUMS.txt"),
        str(Path(plan["assets"][0]).parent / "BUILD.txt"),
        "--target", plan["commit"],
        "--title", plan["title"],
        "--notes-file", str(notes_path),
        "--latest=false",
    ]
    if "delete" in command or "companion-latest" in command or "--cleanup-tag" in command:
        raise SystemExit("The publish command is not safe.")
    return command


def publish(plan):
    ensure_absent(plan["tag"])
    notes = Path(tempfile.mkdtemp(prefix="ironkeep-release-")) / "notes.md"
    notes.write_text(plan["notes"], encoding="utf-8")
    subprocess.check_call(release_command(plan, notes))


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        payload = b"MZ" + (b"\0" * MIN_EXECUTABLE_BYTES)
        for name in RELEASE_FILES:
            (root / name).write_bytes(payload)
        sums = "".join(_sha256(root / name) + "  " + name + "\n" for name in RELEASE_FILES)
        (root / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
        commit = "a" * 40
        (root / "BUILD.txt").write_text("version=2.0.1\ncommit=" + commit + "\n", encoding="utf-8")
        (root / "SCANNED.txt").write_text("defender=pass\ncommit=" + commit + "\n", encoding="utf-8")
        (root / "release-notes.md").write_text("Discord authentication\nSavedVariables layout\n", encoding="utf-8")
        plan = plan_release(root, commit, "2.0.1")
        if publication_gate(commit, commit, False, "") != "dry-run":
            raise SystemExit("A dry run tried to publish.")
        if publication_gate(commit, commit, True, "publish") != "publish":
            raise SystemExit("An explicit confirmation did not publish.")
        if plan["tag"] != "companion-v2.0.1" or plan["commit"] != commit:
            raise SystemExit("The release plan did not use the immutable tag.")
        if commit not in plan["notes"] or "SHA256" not in plan["notes"]:
            raise SystemExit("The release notes do not include the source commit and checksums.")
        command = release_command(plan, root / "notes.md")
        if command[0:4] != ["gh", "release", "create", "companion-v2.0.1"] or command[-1] != "--latest=false":
            raise SystemExit("The publish command is not an immutable release.")
        (root / "IronkeepCompanion.exe").write_bytes(b"MZ")
        try:
            plan_release(root, commit, "2.0.1")
        except SystemExit as ex:
            if "too small" not in str(ex):
                raise
        else:
            raise SystemExit("A tiny executable was accepted.")
    print("publish plan ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--publish" not in argv:
        raise SystemExit("Refusing to publish. The workflow passes --publish after the checks.")
    source = os.environ.get("SOURCE_REF", "").strip()
    built = os.environ.get("EXPECTED_COMMIT", "").strip()
    release_source.require_script_pin(
        os.environ.get("GITHUB_EVENT_NAME", ""),
        os.environ.get("SCRIPTS_INPUT", ""),
        os.environ.get("JOB_WORKFLOW_SHA", ""),
    )
    if publication_gate(source, built, os.environ.get("PUBLISH_REQUESTED", "true"), os.environ.get("PUBLISH_CONFIRM", "")) != "publish":
        raise SystemExit("Refusing to publish.")
    directory = os.environ.get("RELEASE_DIR", "release")
    plan = plan_release(directory, built, os.environ["EXPECTED_VERSION"])
    if plan["commit"] != built.lower():
        raise SystemExit("Refusing to publish because the built commit is not the requested source.")
    publish(plan)
    print("published " + plan["tag"] + " " + plan["commit"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
