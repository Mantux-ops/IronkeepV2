#!/usr/bin/env python3
"""Insert the Roster nav item into the live WoW sidebar only.

The live layout has two Members links. One is inside guild.game == "wow".
The other is inside guild.game == "albion" or not live. This script edits
only the WoW branch, and only inside its existing access.members gate.
"""

import argparse
import re
import sys

ROSTER_MARK = "nav == 'roster'"
ROSTER_MARK_DQ = 'nav == "roster"'
ANCHORS = (
    'href="/{{ guild.slug }}/members"',
    "href='/{{ guild.slug }}/members'",
    'href="/{{guild.slug}}/members"',
)
WOW = ('guild.game == "wow"', "guild.game == 'wow'")
ALBION = (
    'guild.game == "albion" or not live',
    "guild.game == 'albion' or not live",
)
MEMBERS_GATE = "access.members"
ROSTER_LINK = (
    "{% if access.roster %}\n"
    "      <a class=\"nav__item {% if nav == 'roster' %}is-active{% endif %}\" "
    'href="/{{ guild.slug }}/roster">{{ icon("list") }}<span>Roster</span></a>\n'
    "      {% endif %}"
)
TAG_RE = re.compile(r"\{%-?\s*(if|elif|else|endif)\b\s*(.*?)\s*-?%\}", re.DOTALL)


class LayoutError(Exception):
    pass


def _condition(raw):
    return " ".join(raw.split())


def _parse_frames(text):
    stack = []
    frames = []
    for match in TAG_RE.finditer(text):
        kind = match.group(1)
        cond = _condition(match.group(2))
        if kind == "if":
            stack.append({
                "start": match.start(),
                "branches": [{"kind": kind, "cond": cond, "body_start": match.end()}],
            })
            continue
        if kind in ("elif", "else"):
            if not stack:
                raise LayoutError("app_layout.html has a Jinja %s outside an if." % kind)
            if kind == "else" and cond:
                raise LayoutError("app_layout.html has a Jinja else with a condition.")
            current = stack[-1]["branches"][-1]
            current["body_end"] = match.start()
            current["next_start"] = match.start()
            stack[-1]["branches"].append({"kind": kind, "cond": cond, "body_start": match.end()})
            continue
        if not stack:
            raise LayoutError("app_layout.html has a Jinja endif without an if.")
        frame = stack.pop()
        current = frame["branches"][-1]
        current["body_end"] = match.start()
        current["next_start"] = match.start()
        frame["end"] = match.end()
        frames.append(frame)
    if stack:
        raise LayoutError("app_layout.html has an unclosed Jinja if.")
    return frames


def _role(branch):
    if branch["kind"] == "else":
        return "else"
    if branch["cond"] in WOW:
        return "wow"
    if branch["cond"] in ALBION:
        return "albion"
    return ""


def _game_frame(frames):
    """Return the one if/elif chain that is exactly WoW and Albion."""
    pairs = []
    wow_frames = []
    albion_frames = []
    for frame in frames:
        roles = [_role(branch) for branch in frame["branches"]]
        if "wow" in roles:
            wow_frames.append(frame)
        if "albion" in roles:
            albion_frames.append(frame)
        if roles.count("wow") == 1 and roles.count("albion") == 1 and roles.count("") == 0 and roles.count("else") == 0 and len(roles) == 2:
            pairs.append(frame)
    if len(pairs) > 1:
        raise LayoutError("app_layout.html has more than one WoW and Albion navigation branch.")
    if len(pairs) == 1:
        return pairs[0]
    if wow_frames and albion_frames:
        raise LayoutError("app_layout.html does not keep WoW and Albion in one navigation branch.")
    if not wow_frames:
        raise LayoutError("app_layout.html has no WoW navigation branch.")
    raise LayoutError("app_layout.html has no Albion navigation branch.")


def _branch(frame, role):
    found = [branch for branch in frame["branches"] if _role(branch) == role]
    if len(found) != 1:
        raise LayoutError("app_layout.html has an ambiguous %s navigation branch." % role)
    return found[0]


def _members_anchor(body, offset):
    found = []
    for anchor in ANCHORS:
        start = 0
        while True:
            at = body.find(anchor, start)
            if at < 0:
                break
            found.append(offset + at)
            start = at + len(anchor)
    if not found:
        raise LayoutError("app_layout.html WoW navigation has no Members link.")
    if len(found) != 1:
        raise LayoutError("app_layout.html WoW navigation has more than one Members link.")
    return found[0]


def _members_gate(frames, wow, href):
    containers = []
    for frame in frames:
        if frame["start"] < wow["body_start"] or frame["end"] > wow["body_end"]:
            continue
        for branch in frame["branches"]:
            if branch["body_start"] <= href < branch["body_end"]:
                containers.append((frame, branch))
    if not containers:
        raise LayoutError("app_layout.html WoW Members link is not inside {% if access.members %}.")
    frame, branch = min(containers, key=lambda item: item[1]["body_end"] - item[1]["body_start"])
    if len(frame["branches"]) != 1 or branch["cond"] != MEMBERS_GATE:
        raise LayoutError("app_layout.html WoW Members link is not gated by access.members.")
    return branch


def _closed_anchor(text, href, limit):
    close = text.find("</a>", href)
    if close < 0 or close + len("</a>") > limit:
        raise LayoutError("app_layout.html WoW Members link is not closed inside its permission gate.")
    return close + len("</a>")


def _roster_marks(body):
    return body.count(ROSTER_MARK) + body.count(ROSTER_MARK_DQ)


def patch_text(text):
    frames = _parse_frames(text)
    game = _game_frame(frames)
    wow = _branch(game, "wow")
    albion = _branch(game, "albion")
    wow_body = text[wow["body_start"]:wow["body_end"]]
    albion_body = text[albion["body_start"]:albion["body_end"]]
    if _roster_marks(albion_body):
        raise LayoutError("app_layout.html already has a Roster link in Albion navigation.")
    href = _members_anchor(wow_body, wow["body_start"])
    gate = _members_gate(frames, wow, href)
    if _roster_marks(wow_body):
        if _roster_marks(wow_body) != 1:
            raise LayoutError("app_layout.html WoW navigation has more than one Roster link.")
        mark_at = text.find(ROSTER_MARK, wow["body_start"], wow["body_end"])
        if mark_at < 0:
            mark_at = text.find(ROSTER_MARK_DQ, wow["body_start"], wow["body_end"])
        if not gate["body_start"] <= mark_at < gate["body_end"]:
            raise LayoutError("app_layout.html WoW Roster link is outside the Members permission gate.")
        return text
    insert_at = _closed_anchor(text, href, gate["body_end"])
    updated = text[:insert_at] + "\n" + ROSTER_LINK + text[insert_at:]
    # The Albion branch is outside the splice. Compare its body anyway.
    again = _parse_frames(updated)
    again_albion = _branch(_game_frame(again), "albion")
    if updated[again_albion["body_start"]:again_albion["body_end"]] != albion_body:
        raise LayoutError("app_layout.html Albion navigation would change.")
    return updated


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    try:
        with open(args.path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        print("Refusing to run: %s" % error, file=sys.stderr)
        return 1
    try:
        updated = patch_text(text)
    except LayoutError as error:
        print("Refusing to run: %s" % error, file=sys.stderr)
        return 1
    if args.check:
        print("ready" if updated == text else "needed")
        return 0
    if updated != text:
        with open(args.path, "w", encoding="utf-8") as handle:
            handle.write(updated)
        print("patched")
    else:
        print("unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
