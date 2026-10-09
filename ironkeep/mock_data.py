"""Sample data for the clickable prototype. Nothing here talks to Discord or Albion Online."""

import random
from datetime import date, timedelta

TODAY = date(2026, 9, 28)
ALBION_UPDATED_AT = f"{TODAY.isoformat()}T02:10:00"

SUPERADMIN = {"id": "268813802391207937", "name": "Mantux", "color": "#2dd4bf"}
RECRUITER = {"id": "402118830021345281", "name": "Sylas", "color": "#a78bfa"}


def _d(days_ago):
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _t(days_ago, hhmm):
    return f"{_d(days_ago)}T{hhmm}:00"


DUTCH_CHAOS_ROLES = [
    {"id": "1101", "name": "@everyone", "color": "#99aab5", "position": 0, "everyone": True},
    {"id": "1102", "name": "Guild Master", "color": "#e74c3c", "position": 20},
    {"id": "1103", "name": "Officer", "color": "#e67e22", "position": 18},
    {"id": "1199", "name": "Ironkeep", "color": "#2dd4bf", "position": 16, "managed": True},
    {"id": "1104", "name": "Recruiter", "color": "#1abc9c", "position": 15},
    {"id": "1105", "name": "Member", "color": "#3498db", "position": 12},
    {"id": "1106", "name": "Trial", "color": "#95a5a6", "position": 11},
    {"id": "1107", "name": "ZvZ", "color": "#c0392b", "position": 9},
    {"id": "1108", "name": "Gathering", "color": "#27ae60", "position": 8},
    {"id": "1109", "name": "Roads", "color": "#2980b9", "position": 7},
    {"id": "1110", "name": "Ganking", "color": "#8e44ad", "position": 6},
    {"id": "1111", "name": "Events", "color": "#f1c40f", "position": 5},
    {"id": "1112", "name": "Events", "color": "#f39c12", "position": 4},
    {"id": "1113", "name": "Guest", "color": "#7f8c8d", "position": 2},
]

DUTCH_CHAOS_CHANNELS = [
    {"id": "2201", "name": "welcome", "category": "Info", "bot_can_send": True, "trial_visible": True},
    {"id": "2202", "name": "perms", "category": "Info", "bot_can_send": True, "trial_visible": True},
    {"id": "2203", "name": "trial-info", "category": "Recruitment", "bot_can_send": True, "trial_visible": True},
    {"id": "2204", "name": "recruiters", "category": "Recruitment", "bot_can_send": True, "trial_visible": False},
    {"id": "2205", "name": "accepted", "category": "Recruitment", "bot_can_send": True, "trial_visible": True},
    {"id": "2206", "name": "general", "category": "Community", "bot_can_send": True, "trial_visible": True},
    {"id": "2207", "name": "announcements", "category": "Community", "bot_can_send": False, "trial_visible": True},
]

DEFAULT_MESSAGES = {
    "welcome": {
        "enabled": True,
        "channel": "2202",
        "text": "Welcome to {guild}, {member}! Tell us your in-game name and what content you play, and a recruiter will sort out your roles.",
    },
    "trial_started": {
        "enabled": True,
        "channel": "2203",
        "text": "{member} started their trial today. It runs for {days} days, until {end_date}. Join content and get to know the group!",
    },
    "reminder": {
        "enabled": True,
        "channel": "2203",
        "text": "Hey {member}, you're {day} days into your trial and don't have a content role yet. Pick ZvZ, Gathering or Roads so we know where to find you.",
    },
    "accepted": {
        "enabled": True,
        "channel": "2205",
        "text": "Welcome to the guild, {member}! Your trial is complete and you're now a full member of {guild}.",
    },
    "rejected": {
        "enabled": False,
        "channel": "2204",
        "text": "{member}'s trial in {guild} has ended without acceptance.",
    },
}


FAME_PROFILES = {
    "zvz": {"pvp": 140_000, "pve": 160_000, "gathering": 4_000, "crafting": 0, "active": 0.8},
    "pve": {"pvp": 25_000, "pve": 620_000, "gathering": 12_000, "crafting": 15_000, "active": 0.85},
    "gather": {"pvp": 2_000, "pve": 45_000, "gathering": 95_000, "crafting": 30_000, "active": 0.8},
    "mixed": {"pvp": 50_000, "pve": 260_000, "gathering": 20_000, "crafting": 8_000, "active": 0.75},
    "low": {"pvp": 8_000, "pve": 60_000, "gathering": 6_000, "crafting": 0, "active": 0.3},
}


def _fame(seed, since, until, profile):
    """Daily fame gained, as Ironkeep would compute it from consecutive lifetime snapshots."""
    rng = random.Random(seed)
    p = FAME_PROFILES[profile]
    days = []
    day = date.fromisoformat(since) + timedelta(days=1)
    while day <= until:
        active = rng.random() < p["active"]
        days.append({
            "date": day.isoformat(),
            **{k: int(p[k] * rng.uniform(0.3, 1.9)) if active else 0 for k in ("pvp", "pve", "gathering", "crafting")},
        })
        day += timedelta(days=1)
    return days


def _albion(tid, name, start, verdict_at, kw):
    albion_name = kw.pop("albion_name", name)
    if albion_name is None:
        return {"name": None, "link": None, "in_guild": None, "last_in_guild": None, "fame_since": None, "fame": []}
    since = start or kw.pop("tracking_since", _d(20))
    until = date.fromisoformat(verdict_at[:10]) if verdict_at else TODAY
    return {
        "name": albion_name,
        "link": kw.pop("albion_link", "nickname"),
        "in_guild": kw.pop("in_guild", True),
        "last_in_guild": kw.pop("last_in_guild", None),
        "fame_since": since,
        "fame": _fame(tid, since, until, kw.pop("fame_profile", "mixed")),
    }


def _trial(tid, name, username, color, start_days_ago, **kw):
    start = _d(start_days_ago) if start_days_ago is not None else None
    albion = _albion(tid, name, start, kw.get("verdict_at"), kw)
    return {
        "id": tid,
        "user_id": kw.pop("user_id", f"7{tid:017d}"),
        "name": name,
        "username": username,
        "color": color,
        "start": start,
        "extra_days": kw.pop("extra_days", 0),
        "content_roles": kw.pop("content_roles", []),
        "ping_sent_at": kw.pop("ping_sent_at", None),
        "lost_content_role": kw.pop("lost_content_role", False),
        "verdict": kw.pop("verdict", None),
        "verdict_at": kw.pop("verdict_at", None),
        "verdict_by": kw.pop("verdict_by", None),
        "action_error": kw.pop("action_error", None),
        "left_server": kw.pop("left_server", False),
        "timeline": kw.pop("timeline", []),
        "albion": albion,
    }


def _sys(at, text, kind="system"):
    return {"type": kind, "at": at, "text": text}


def _obs(at, author, category, rating, text):
    return {"type": "observation", "at": at, "author": author, "category": category, "rating": rating, "text": text}


DUTCH_CHAOS_TRIALS = [
    _trial(1, "Velorn", "velorn", "#b45309", 8, fame_profile="zvz", ping_sent_at=_t(1, "10:00"), timeline=[
        _sys(_t(9, "18:02"), "Joined the server"),
        _sys(_t(8, "20:14"), "Trial role given by Sylas"),
        _obs(_t(6, "22:40"), "Sylas", "Attendance", "positive", "Joined the Tuesday ZvZ and stayed until the end."),
        _obs(_t(3, "21:05"), "Mantux", "Communication", "neutral", "Quiet in voice, but follows calls."),
        _sys(_t(1, "10:00"), "Day-7 reminder sent in #trial-info"),
    ]),
    _trial(2, "Crylen", "crylen.albion", "#7c3aed", None, timeline=[
        _sys(_t(20, "15:30"), "Already had the Trial role when Ironkeep was installed. Start date unknown."),
    ]),
    _trial(3, "Orain", "orain", "#d97706", 15, fame_profile="zvz", content_roles=["1107"], timeline=[
        _sys(_t(16, "17:44"), "Joined the server"),
        _sys(_t(15, "19:01"), "Trial role given by Mantux"),
        _sys(_t(13, "21:12"), "Content role ZvZ added"),
        _obs(_t(11, "23:10"), "Sylas", "Attendance", "positive", "Showed up for three CTAs this week."),
        _obs(_t(8, "22:31"), "Sylas", "Group fit", "positive", "Gets along well with the ZvZ core."),
        _obs(_t(4, "20:02"), "Mantux", "Skill", "positive", "Solid on the Hallowfall, knows the rotations."),
        _obs(_t(2, "19:47"), "Sylas", "Behaviour", "negative", "Argued with the caller after a lost fight."),
        _sys(_t(1, "19:01"), "Trial period ended. Waiting for a verdict."),
    ]),
    _trial(4, "Kaelen", "kaelen", "#0891b2", 12, fame_profile="pve", content_roles=["1107", "1109"], timeline=[
        _sys(_t(13, "16:20"), "Joined the server"),
        _sys(_t(12, "18:45"), "Trial role given by Sylas"),
        _sys(_t(10, "20:30"), "Content role ZvZ added"),
        _sys(_t(7, "13:15"), "Content role Roads added"),
        _obs(_t(5, "22:00"), "Sylas", "Attendance", "positive", "Very active in roads groups."),
    ]),
    _trial(5, "Tharion", "tharion", "#5865f2", 4, fame_profile="gather", content_roles=["1108"], timeline=[
        _sys(_t(5, "11:00"), "Joined the server"),
        _sys(_t(4, "12:10"), "Trial role given by Sylas"),
        _sys(_t(4, "12:40"), "Content role Gathering added"),
    ]),
    _trial(6, "Nymeria", "nymeria", "#be123c", 6, fame_profile="low", content_roles=["1108"], timeline=[
        _sys(_t(7, "09:30"), "Joined the server"),
        _sys(_t(6, "10:05"), "Trial role given by Mantux"),
        _sys(_t(6, "10:50"), "Content role Gathering added"),
        _obs(_t(2, "18:30"), "Mantux", "Attendance", "negative", "Missed both gathering sessions she signed up for."),
    ]),
    _trial(7, "Brammm | NL", "brammm", "#15803d", 2, albion_name=None, timeline=[
        _sys(_t(3, "20:00"), "Joined the server"),
        _sys(_t(2, "21:15"), "Trial role given by Sylas"),
    ]),
    _trial(8, "ZilverStorm", "zilverstorm", "#64748b", 10, in_guild=False, last_in_guild=_d(2), ping_sent_at=_t(3, "10:00"), lost_content_role=True, timeline=[
        _sys(_t(11, "14:00"), "Joined the server"),
        _sys(_t(10, "15:20"), "Trial role given by Sylas"),
        _sys(_t(3, "10:00"), "Day-7 reminder sent in #trial-info"),
        _sys(_t(2, "18:00"), "Content role Roads added"),
        _sys(_t(1, "02:10"), "No longer in Dutch Chaos in-game"),
        _sys(_t(0, "08:12"), "Content role Roads removed"),
    ]),
    _trial(9, "Luna", "lunaquiet", "#db2777", 16, fame_profile="gather", albion_name="LunaQuiet", albion_link="manual", content_roles=["1108"], verdict_by="Sylas",
           action_error="Missing permission: Ironkeep could not remove the Trial role.", timeline=[
        _sys(_t(17, "12:00"), "Joined the server"),
        _sys(_t(16, "13:00"), "Trial role given by Sylas"),
        _sys(_t(15, "13:30"), "Content role Gathering added"),
        _obs(_t(5, "20:00"), "Sylas", "Group fit", "positive", "Great addition to the gathering crew."),
        _sys(_t(0, "09:14"), "Accepted by Sylas"),
        _sys(_t(0, "09:14"), "Role change failed: Missing permission to remove Trial", "error"),
    ]),
    _trial(10, "Ravenhold", "ravenhold", "#0f766e", 30, fame_profile="zvz", content_roles=["1107"], verdict="accepted",
           verdict_at=_t(14, "20:00"), verdict_by="Mantux", timeline=[
        _sys(_t(31, "10:00"), "Joined the server"),
        _sys(_t(30, "11:00"), "Trial role given by Mantux"),
        _sys(_t(14, "20:00"), "Accepted by Mantux"),
        _sys(_t(14, "20:00"), "Roles changed: + Member, − Trial"),
    ]),
    _trial(11, "Mordred", "mordrednl", "#991b1b", 25, fame_profile="low", verdict="rejected",
           verdict_at=_t(9, "21:00"), verdict_by="Sylas", timeline=[
        _sys(_t(26, "10:00"), "Joined the server"),
        _sys(_t(25, "11:00"), "Trial role given by Sylas"),
        _obs(_t(15, "20:00"), "Sylas", "Attendance", "negative", "Not seen at any content for two weeks."),
        _sys(_t(9, "21:00"), "Rejected by Sylas"),
        _sys(_t(9, "21:00"), "Roles changed: − Trial"),
    ]),
]


def _simple_guild_roles():
    return [dict(r) for r in DUTCH_CHAOS_ROLES]


GUILDS = [
    {
        "id": "806607423233327195",
        "slug": "dutchchaos",
        "name": "Dutch Chaos",
        "icon_color": "#d97706",
        "icon_letter": "DC",
        "approval": "approved",
        "bot_present": True,
        "setup_complete": True,
        "added_by": "Mantux",
        "added_at": _t(40, "12:00"),
        "last_error": None,
        "roles": DUTCH_CHAOS_ROLES,
        "channels": DUTCH_CHAOS_CHANNELS,
        "settings": {
            "timezone": "Europe/Amsterdam",
            "trial_days": 14,
            "reminder_day": 7,
            "recruitment_roles": ["1103", "1104"],
            "trial_role": "1106",
            "content_roles": ["1107", "1108", "1109"],
            "channels": {"perms": "2202", "trial_info": "2203", "recruiter_overview": "2204"},
            "messages": DEFAULT_MESSAGES,
            "accept": {"add": ["1105"], "remove": ["1106"]},
            "reject": {"remove": ["1106"]},
            "albion": {"region": "europe", "guild_name": "Dutch Chaos", "guild_members": 79, "name_source": "nickname", "guild_check": "dashboard", "track_fame": True},
        },
        "trials": DUTCH_CHAOS_TRIALS,
    },
    {
        "id": "912004458821133313",
        "slug": "ironlegion",
        "name": "Iron Legion",
        "icon_color": "#b91c1c",
        "icon_letter": "IL",
        "approval": "approved",
        "bot_present": True,
        "setup_complete": True,
        "added_by": "Garrick",
        "added_at": _t(21, "18:30"),
        "last_error": None,
        "roles": _simple_guild_roles(),
        "channels": [dict(c) for c in DUTCH_CHAOS_CHANNELS],
        "settings": {
            "timezone": "Europe/London",
            "trial_days": 21,
            "reminder_day": 7,
            "recruitment_roles": ["1104"],
            "trial_role": "1106",
            "content_roles": ["1107", "1110"],
            "channels": {"perms": "2202", "trial_info": "2203", "recruiter_overview": "2204"},
            "messages": DEFAULT_MESSAGES,
            "accept": {"add": ["1105"], "remove": ["1106"]},
            "reject": {"remove": ["1106"]},
            "albion": {"region": "europe", "guild_name": "Iron Legion", "guild_members": 112, "name_source": "nickname", "guild_check": "dashboard", "track_fame": True},
        },
        "trials": [
            _trial(101, "Garrow", "garrow", "#475569", 9, content_roles=["1107"]),
            _trial(102, "Isolde", "isolde", "#9333ea", 3, in_guild=False),
            _trial(103, "Brenn", "brenn", "#0369a1", 12, ping_sent_at=_t(5, "10:00")),
        ],
    },
    {
        "id": "934551209873420288",
        "slug": "blackrose",
        "name": "Black Rose",
        "icon_color": "#7e22ce",
        "icon_letter": "BR",
        "approval": "pending",
        "bot_present": True,
        "setup_complete": False,
        "added_by": "Rosalind",
        "added_at": _t(0, "11:02"),
        "last_error": None,
        "roles": _simple_guild_roles(),
        "channels": [dict(c) for c in DUTCH_CHAOS_CHANNELS],
        "settings": {
            "timezone": "Europe/Berlin",
            "trial_days": 14,
            "reminder_day": 7,
            "recruitment_roles": [],
            "trial_role": None,
            "content_roles": [],
            "channels": {"perms": None, "trial_info": None, "recruiter_overview": None},
            "messages": DEFAULT_MESSAGES,
            "accept": {"add": [], "remove": []},
            "reject": {"remove": []},
            "albion": {"region": "europe", "guild_name": "", "guild_members": 0, "name_source": "nickname", "guild_check": "dashboard", "track_fame": True},
        },
        "trials": [],
    },
    {
        "id": "955012887345123328",
        "slug": "northwind",
        "name": "Northwind",
        "icon_color": "#0284c7",
        "icon_letter": "NW",
        "approval": "approved",
        "bot_present": True,
        "setup_complete": True,
        "added_by": "Eirik",
        "added_at": _t(60, "09:00"),
        "last_error": {"at": _t(0, "07:41"), "text": "Can't send messages in #perms"},
        "roles": _simple_guild_roles(),
        "channels": [
            dict(c, bot_can_send=False) if c["name"] == "perms" else dict(c)
            for c in DUTCH_CHAOS_CHANNELS
        ],
        "settings": {
            "timezone": "Europe/Oslo",
            "trial_days": 14,
            "reminder_day": 7,
            "recruitment_roles": ["1103"],
            "trial_role": "1106",
            "content_roles": ["1107", "1108"],
            "channels": {"perms": "2202", "trial_info": "2203", "recruiter_overview": "2204"},
            "messages": DEFAULT_MESSAGES,
            "accept": {"add": ["1105"], "remove": ["1106"]},
            "reject": {"remove": ["1106"]},
            "albion": {"region": "europe", "guild_name": "Northwind", "guild_members": 54, "name_source": "nickname", "guild_check": "dashboard", "track_fame": True},
        },
        "trials": [
            _trial(201, "Sigrun", "sigrun", "#0e7490", 5, content_roles=["1108"]),
            _trial(202, "Halvard", "halvard", "#4d7c0f", 8, ping_sent_at=_t(1, "10:00")),
        ],
    },
]

ERRORS = [
    {"at": _t(0, "07:41"), "guild": "northwind", "text": "Can't send messages in #perms", "detail": "Welcome message for a new member was not posted. Missing permission: Send Messages.", "resolved": False},
    {"at": _t(0, "09:14"), "guild": "dutchchaos", "text": "Role change failed for Luna", "detail": "Accepting the trial could not remove the Trial role. Missing permission: Manage Roles.", "resolved": False},
    {"at": _t(4, "22:03"), "guild": "ironlegion", "text": "Discord rate limit", "detail": "Updating the recruiter overview was delayed by 12 seconds.", "resolved": True},
]


def guild_by_slug(slug):
    return next((g for g in GUILDS if g["slug"] == slug), None)


STATUS_META = {
    "accepted": ("Accepted", "green", "closed"),
    "rejected": ("Rejected", "grey", "closed"),
    "left": ("Left server", "grey", "closed"),
    "action_failed": ("Action failed", "red", "attention"),
    "no_start": ("No start date", "orange", "attention"),
    "verdict_due": ("Verdict due", "orange", "verdict"),
    "no_content": ("No content role", "red", "attention"),
    "lost_content": ("Lost content role", "red", "attention"),
    "ending_soon": ("Ending soon", "orange", "ending"),
    "active": ("Active", "green", "active"),
}


def trial_status(trial, settings, today=None):
    today = today or TODAY
    if trial["verdict"]:
        return trial["verdict"]
    if trial["action_error"]:
        return "action_failed"
    if trial["left_server"]:
        return "left"
    if not trial["start"]:
        return "no_start"
    start = date.fromisoformat(trial["start"])
    length = settings["trial_days"] + trial["extra_days"]
    day = (today - start).days + 1
    days_left = length - day
    if day > length:
        return "verdict_due"
    if not trial["content_roles"]:
        if trial["lost_content_role"]:
            return "lost_content"
        if day >= settings["reminder_day"]:
            return "no_content"
    if days_left <= 2:
        return "ending_soon"
    return "active"


def albion_flagged(trial, settings, today=None):
    """Mirrors albionFlags() in trials.js: no linked name, or not in the guild in-game after a day's grace."""
    today = today or TODAY
    albion, conf = trial["albion"], settings["albion"]
    if not albion["name"]:
        return True
    if conf["guild_check"] == "off" or not conf["guild_name"] or albion["in_guild"] is not False:
        return False
    return not trial["start"] or (today - date.fromisoformat(trial["start"])).days >= 1


def guild_summary(guild, today=None):
    counts = {"open": 0, "attention": 0}
    for t in guild["trials"]:
        group = STATUS_META[trial_status(t, guild["settings"], today)][2]
        if group != "closed":
            counts["open"] += 1
        if group in ("attention", "verdict", "ending") or (group != "closed" and albion_flagged(t, guild["settings"], today)):
            counts["attention"] += 1
    return counts
