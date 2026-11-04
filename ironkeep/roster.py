"""One Discord member, one main, and any number of alts."""

from . import wow


class RosterError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _key(name):
    return (name or "").casefold()


def _owned(rows, user_id):
    return [row for row in rows if str(row.get("user_id")) == str(user_id)]


def add(rows, user_id, fields):
    """Append a character. The first character on a person is always the main."""
    user_id = str(user_id)
    name = wow.clean_name(fields.get("name"))
    if name is None:
        raise RosterError("Use 2 to 12 letters for the character name.")
    if any(_key(row.get("name")) == _key(name) for row in rows):
        raise RosterError("That character name is already in this guild.")
    choice = wow.resolve(fields.get("class_id"), fields.get("spec_id"), fields.get("role"))
    if choice is None:
        raise RosterError("Pick a class, a spec and a role.")
    owned = _owned(rows, user_id)
    if len(owned) >= wow.MAX_PER_PERSON:
        raise RosterError("Twelve characters is the limit for one person.")
    wants_main = bool(fields.get("is_main")) or not owned
    if wants_main:
        for row in owned:
            row["is_main"] = False
    row = {
        "id": None,
        "user_id": user_id,
        "name": name,
        "class_id": choice["class_id"],
        "spec_id": choice["spec_id"],
        "role": choice["role"],
        "is_main": wants_main,
    }
    rows.append(row)
    return row


def update(rows, character_id, fields):
    """Change name, class, spec, role or which character is the main."""
    row = next((item for item in rows if item.get("id") == character_id), None)
    if row is None:
        raise RosterError("That character is gone.")
    name = wow.clean_name(fields.get("name"))
    if name is None:
        raise RosterError("Use 2 to 12 letters for the character name.")
    if any(_key(item.get("name")) == _key(name) and item.get("id") != row.get("id") for item in rows):
        raise RosterError("That character name is already in this guild.")
    choice = wow.resolve(fields.get("class_id"), fields.get("spec_id"), fields.get("role"))
    if choice is None:
        raise RosterError("Pick a class, a spec and a role.")
    wants_main = bool(fields.get("is_main"))
    owned = _owned(rows, row["user_id"])
    if row.get("is_main") and not wants_main:
        raise RosterError("Make another character the main first.")
    if wants_main:
        for item in owned:
            item["is_main"] = False
    row["name"] = name
    row["class_id"] = choice["class_id"]
    row["spec_id"] = choice["spec_id"]
    row["role"] = choice["role"]
    row["is_main"] = wants_main
    return row


def remove(rows, character_id):
    """Drop a character. When the main goes, the oldest alt becomes the main."""
    row = next((item for item in rows if item.get("id") == character_id), None)
    if row is None:
        raise RosterError("That character is gone.")
    rows.remove(row)
    if row.get("is_main"):
        rest = _owned(rows, row["user_id"])
        rest.sort(key=lambda item: item.get("id") or 0)
        for item in rest:
            item["is_main"] = False
        if rest:
            rest[0]["is_main"] = True
    return row


def set_main(rows, character_id):
    row = next((item for item in rows if item.get("id") == character_id), None)
    if row is None:
        raise RosterError("That character is gone.")
    for item in _owned(rows, row["user_id"]):
        item["is_main"] = item is row
    return row
