"""Read the group list the Ironkeep addon saved on this computer.

WoW writes WTF/Account/<account>/SavedVariables/Ironkeep.lua when you log out
or /reload. This program turns that file back into the same text as Copy list.
It does not start the game and it does not send the list anywhere.
"""

import argparse
import sys
import time
from pathlib import Path

ROLE_ORDER = {"TANK": 1, "HEALER": 2, "DAMAGER": 3}
ROLE_LABEL = {"TANK": "Tank", "HEALER": "Healer", "DAMAGER": "Damage"}
SAMPLE = Path(__file__).with_name("sample-Ironkeep.lua")


class SavedError(Exception):
    """The file is missing, unreadable, or not an Ironkeep saved list."""


class _Reader:
    """SavedVariables is a data-only Lua file. Calls and chunks are refused."""

    def __init__(self, text):
        self.text = text.lstrip("\ufeff")
        self.n = len(self.text)
        self.i = 0

    def parse_file(self):
        found = {}
        while True:
            self._skip()
            if self.i >= self.n:
                break
            name = self._ident()
            self._skip()
            self._expect("=")
            found[name] = self._value()
        db = found.get("IronkeepDB")
        if not isinstance(db, dict):
            raise SavedError("This file has no Ironkeep list.")
        return db

    def _peek(self):
        return self.text[self.i] if self.i < self.n else ""

    def _starts(self, token):
        return self.text.startswith(token, self.i)

    def _skip(self):
        while self.i < self.n:
            if self.text[self.i] in " \t\r\n":
                self.i += 1
                continue
            if self._starts("--"):
                self.i += 2
                if self._starts("["):
                    mark = self.i
                    self.i += 1
                    equals = 0
                    while self._peek() == "=":
                        equals += 1
                        self.i += 1
                    if self._peek() == "[":
                        self.i += 1
                        close = "]" + ("=" * equals) + "]"
                        end = self.text.find(close, self.i)
                        if end < 0:
                            raise SavedError("This saved file is cut off.")
                        self.i = end + len(close)
                        continue
                    self.i = mark
                end = self.text.find("\n", self.i)
                self.i = self.n if end < 0 else end + 1
                continue
            break

    def _expect(self, token):
        self._skip()
        if not self._starts(token):
            raise SavedError("This saved file could not be read.")
        self.i += len(token)

    def _eat(self, token):
        self._skip()
        if self._starts(token):
            self.i += len(token)
            return True
        return False

    def _ident(self):
        self._skip()
        start = self.i
        if not (self._peek().isalpha() or self._peek() == "_"):
            raise SavedError("This saved file could not be read.")
        self.i += 1
        while self._peek().isalnum() or self._peek() == "_":
            self.i += 1
        return self.text[start:self.i]

    def _value(self):
        self._skip()
        char = self._peek()
        if char == "{":
            return self._table()
        if char in "\"'":
            return self._quote()
        if char == "[":
            return self._long_string()
        if char == "-" or char.isdigit():
            return self._number()
        if self._peek().isalpha() or self._peek() == "_":
            word = self._ident()
            if word == "true":
                return True
            if word == "false":
                return False
            if word == "nil":
                return None
            raise SavedError("This saved file could not be read.")
        raise SavedError("This saved file could not be read.")

    def _table(self):
        self._expect("{")
        data = {}
        index = 1
        while True:
            self._skip()
            if self._eat("}"):
                return data
            if self._eat("["):
                key = self._value()
                self._expect("]")
                self._expect("=")
                data[key] = self._value()
            else:
                mark = self.i
                if self._peek().isalpha() or self._peek() == "_":
                    name = self._ident()
                    if self._eat("="):
                        data[name] = self._value()
                    else:
                        self.i = mark
                        data[index] = self._value()
                        index += 1
                else:
                    data[index] = self._value()
                    index += 1
            self._skip()
            self._eat(",")
            self._eat(";")

    def _quote(self):
        quote = self._peek()
        self.i += 1
        chars = []
        while self.i < self.n:
            char = self.text[self.i]
            if char == quote:
                self.i += 1
                return "".join(chars)
            if char == "\\":
                chars.append(self._escape())
                continue
            if char == "\n":
                raise SavedError("This saved file could not be read.")
            chars.append(char)
            self.i += 1
        raise SavedError("This saved file is cut off.")

    def _escape(self):
        self.i += 1
        if self.i >= self.n:
            raise SavedError("This saved file is cut off.")
        char = self.text[self.i]
        self.i += 1
        simple = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "\"": "\"", "'": "'", "\n": "\n"}
        if char in simple:
            return simple[char]
        if char.isdigit():
            digits = char
            for _ in range(2):
                if self.i < self.n and self.text[self.i].isdigit():
                    digits += self.text[self.i]
                    self.i += 1
                else:
                    break
            return chr(int(digits))
        raise SavedError("This saved file could not be read.")

    def _long_string(self):
        self._expect("[")
        equals = 0
        while self._eat("="):
            equals += 1
        self._expect("[")
        if self._peek() == "\n":
            self.i += 1
        close = "]" + ("=" * equals) + "]"
        end = self.text.find(close, self.i)
        if end < 0:
            raise SavedError("This saved file is cut off.")
        text = self.text[self.i:end]
        self.i = end + len(close)
        return text

    def _number(self):
        start = self.i
        if self._peek() == "-":
            self.i += 1
        saw_digit = False
        while self._peek().isdigit():
            saw_digit = True
            self.i += 1
        if self._peek() == ".":
            self.i += 1
            while self._peek().isdigit():
                saw_digit = True
                self.i += 1
        if not saw_digit:
            raise SavedError("This saved file could not be read.")
        token = self.text[start:self.i]
        return float(token) if "." in token else int(token)


def load_saved(text):
    return _Reader(text).parse_file()


def load_path(path):
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SavedError(f"Could not open {file}.") from exc
    except UnicodeError as exc:
        raise SavedError(f"Could not read {file}.") from exc
    return load_saved(text)


def saved_files(wow_dir):
    root = Path(wow_dir) / "WTF" / "Account"
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*/SavedVariables/Ironkeep.lua") if path.is_file())


def newest(files):
    return max(files, key=lambda path: path.stat().st_mtime)


def _rows(session):
    people = session.get("people") or {}
    rows = list(people.values()) if isinstance(people, dict) else []
    rows = [row for row in rows if isinstance(row, dict)]

    def key(person):
        present = 0 if person.get("present") else 1
        subgroup = person.get("subgroup") if isinstance(person.get("subgroup"), (int, float)) else 99
        role = ROLE_ORDER.get(person.get("role"), 9)
        return (present, subgroup, role, person.get("name") or "")

    return sorted(rows, key=key)


def _seen(person):
    first, last = person.get("first"), person.get("last")
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
        return ""
    minutes = int((last - first) // 60)
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60}m"


def report(session, started_at=None):
    """The same text Copy list puts on the clipboard."""
    if not isinstance(session, dict):
        return "Ironkeep group\n\nNobody recorded yet."
    started = session.get("started")
    if started_at is None and isinstance(started, (int, float)):
        started_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(started))
    lines = [
        "Ironkeep group",
        "Place: " + str(session.get("place") or "Unknown"),
        "Started: " + (started_at or ""),
        "",
        "Name | Class | Role | Time | Status",
    ]
    rows = _rows(session)
    for person in rows:
        status = "here" if person.get("present") else "left"
        klass = person.get("className") or person.get("classFile") or ""
        lines.append(" | ".join([
            str(person.get("name") or "Unknown"),
            str(klass),
            ROLE_LABEL.get(person.get("role"), ""),
            _seen(person),
            status,
        ]))
    if not rows:
        lines.append("Nobody recorded yet.")
    lines.append("")
    lines.append("format: ironkeep-group 1")
    return "\n".join(lines)


def text_for(db):
    session = db.get("session") if isinstance(db, dict) else None
    if isinstance(session, dict):
        return report(session)
    previous = db.get("lastReport") if isinstance(db, dict) else None
    if isinstance(previous, str) and previous.strip():
        return previous
    return "Ironkeep group\n\nNobody recorded yet."


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ironkeep_companion.py",
        description="Read the Ironkeep group list saved by the WoW: Forever addon.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--sample", action="store_true", help="Read the bundled example instead of a game file.")
    source.add_argument("--file", type=Path, help="Path to SavedVariables/Ironkeep.lua.")
    source.add_argument("--wow", type=Path, help="WoW: Forever folder, for example G:\\World of Warcraft\\_forever_.")
    args = parser.parse_args(argv)

    try:
        if args.sample:
            path = SAMPLE
            db = load_path(path)
        elif args.file:
            path = args.file
            db = load_path(path)
        elif args.wow:
            files = saved_files(args.wow)
            if not files:
                raise SavedError(f"No Ironkeep.lua under {args.wow}. Log out once so the addon can write it.")
            path = newest(files)
            account = path.parents[1].name
            print(f"Account: {account}", file=sys.stderr)
            db = load_path(path)
        else:
            parser.print_help()
            return 2
    except SavedError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Read from: {path}", file=sys.stderr)
    print(text_for(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
