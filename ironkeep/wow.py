"""WoW: Forever classes. Nine classic classes, with the talent tree as the spec."""

CLASSES = (
    {
        "id": "warrior",
        "name": "Warrior",
        "color": "#C79C6E",
        "specs": (
            {"id": "arms", "name": "Arms", "role": "dps"},
            {"id": "fury", "name": "Fury", "role": "dps"},
            {"id": "protection", "name": "Protection", "role": "tank"},
        ),
    },
    {
        "id": "paladin",
        "name": "Paladin",
        "color": "#F58CBA",
        "specs": (
            {"id": "holy", "name": "Holy", "role": "healer"},
            {"id": "protection", "name": "Protection", "role": "tank"},
            {"id": "retribution", "name": "Retribution", "role": "dps"},
        ),
    },
    {
        "id": "hunter",
        "name": "Hunter",
        "color": "#ABD473",
        "specs": (
            {"id": "beast_mastery", "name": "Beast Mastery", "role": "dps"},
            {"id": "marksmanship", "name": "Marksmanship", "role": "dps"},
            {"id": "survival", "name": "Survival", "role": "dps"},
        ),
    },
    {
        "id": "rogue",
        "name": "Rogue",
        "color": "#FFF569",
        "specs": (
            {"id": "assassination", "name": "Assassination", "role": "dps"},
            {"id": "combat", "name": "Combat", "role": "dps"},
            {"id": "subtlety", "name": "Subtlety", "role": "dps"},
        ),
    },
    {
        "id": "priest",
        "name": "Priest",
        "color": "#FFFFFF",
        "specs": (
            {"id": "discipline", "name": "Discipline", "role": "healer"},
            {"id": "holy", "name": "Holy", "role": "healer"},
            {"id": "shadow", "name": "Shadow", "role": "dps"},
        ),
    },
    {
        "id": "shaman",
        "name": "Shaman",
        "color": "#0070DE",
        "specs": (
            {"id": "elemental", "name": "Elemental", "role": "dps"},
            {"id": "enhancement", "name": "Enhancement", "role": "dps"},
            {"id": "restoration", "name": "Restoration", "role": "healer"},
        ),
    },
    {
        "id": "mage",
        "name": "Mage",
        "color": "#69CCF0",
        "specs": (
            {"id": "arcane", "name": "Arcane", "role": "dps"},
            {"id": "fire", "name": "Fire", "role": "dps"},
            {"id": "frost", "name": "Frost", "role": "dps"},
        ),
    },
    {
        "id": "warlock",
        "name": "Warlock",
        "color": "#9482C9",
        "specs": (
            {"id": "affliction", "name": "Affliction", "role": "dps"},
            {"id": "demonology", "name": "Demonology", "role": "dps"},
            {"id": "destruction", "name": "Destruction", "role": "dps"},
        ),
    },
    {
        "id": "druid",
        "name": "Druid",
        "color": "#FF7D0A",
        "specs": (
            {"id": "balance", "name": "Balance", "role": "dps"},
            {"id": "feral", "name": "Feral", "role": "dps"},
            {"id": "restoration", "name": "Restoration", "role": "healer"},
        ),
    },
)

CLASS_BY_ID = {klass["id"]: klass for klass in CLASSES}

ROLES = (
    ("tank", "Tank"),
    ("healer", "Healer"),
    ("dps", "DPS"),
)
ROLE_NAMES = dict(ROLES)
MAX_PER_PERSON = 12


def catalog():
    """Class list for the character form."""
    return [
        {
            "id": klass["id"],
            "name": klass["name"],
            "color": klass["color"],
            "specs": [
                {"id": spec["id"], "name": spec["name"], "role": spec["role"]}
                for spec in klass["specs"]
            ],
        }
        for klass in CLASSES
    ]


def clean_name(value):
    """A Forever character name: 2 to 12 letters, no spaces."""
    name = str(value or "").strip()
    if len(name) < 2 or len(name) > 12 or not name.isalpha():
        return None
    return name


def resolve(class_id, spec_id, role=None):
    """Class, spec and role, or None when the combination is not a Forever class.

    The role defaults to the spec. An officer can still mark a feral druid as a tank.
    """
    klass = CLASS_BY_ID.get(str(class_id or ""))
    if klass is None:
        return None
    spec = next((item for item in klass["specs"] if item["id"] == str(spec_id or "")), None)
    if spec is None:
        return None
    chosen = str(role or spec["role"])
    if chosen not in ROLE_NAMES:
        return None
    return {"class_id": klass["id"], "spec_id": spec["id"], "role": chosen}


def present(row):
    """Add the labels the pages show. Unknown stored classes are skipped by the caller."""
    klass = CLASS_BY_ID.get(row.get("class_id"))
    if klass is None:
        return None
    spec = next((item for item in klass["specs"] if item["id"] == row.get("spec_id")), None)
    role = row.get("role") if row.get("role") in ROLE_NAMES else (spec["role"] if spec else "dps")
    return {
        "id": row.get("id"),
        "user_id": str(row.get("user_id") or ""),
        "name": row.get("name") or "",
        "class_id": klass["id"],
        "class_name": klass["name"],
        "color": klass["color"],
        "spec_id": spec["id"] if spec else row.get("spec_id") or "",
        "spec_name": spec["name"] if spec else "",
        "role": role,
        "role_name": ROLE_NAMES[role],
        "is_main": bool(row.get("is_main")),
    }
