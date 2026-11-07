#!/usr/bin/env python3
"""Insert the Roster nav item into the live site layout.

The installer does not replace app_layout.html. It adds one link beside
Members, and only when that Members link is already there.
"""

import argparse
import sys

ROSTER_MARK = "nav == 'roster'"
ROSTER_MARK_DQ = 'nav == "roster"'
ANCHORS = (
    'href="/{{ guild.slug }}/members"',
    "href='/{{ guild.slug }}/members'",
    'href="/{{guild.slug}}/members"',
)
ROSTER_LINK = (
    "{% if access.roster %}\n"
    "      <a class=\"nav__item {% if nav == 'roster' %}is-active{% endif %}\" "
    'href="/{{ guild.slug }}/roster">{{ icon("list") }}<span>Roster</span></a>\n'
    "      {% endif %}"
)


class LayoutError(Exception):
    pass


def already_linked(text):
    return ROSTER_MARK in text or ROSTER_MARK_DQ in text


def patch_text(text):
    if already_linked(text):
        return text
    start = -1
    for anchor in ANCHORS:
        start = text.find(anchor)
        if start >= 0:
            break
    if start < 0:
        raise LayoutError("app_layout.html has no Members link to place Roster beside.")
    close = text.find("</a>", start)
    if close < 0:
        raise LayoutError("app_layout.html Members link is not closed.")
    insert_at = close + len("</a>")
    return text[:insert_at] + "\n" + ROSTER_LINK + text[insert_at:]


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
