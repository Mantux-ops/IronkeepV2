#!/usr/bin/env python3
"""Import the Companion modules without opening the production database.

Run from the server after the files are in place:

    cd /opt/ironkeep
    .venv/bin/python /path/to/check_imports.py

The script does not read /etc/ironkeep.env and it does not execute
ironkeep.main, because that calls db.init().
"""

import inspect
import os
import py_compile
import sys

PRODUCTION_DB = "/var/lib/ironkeep/ironkeep.db"
for name in (
    "IRONKEEP_DB",
    "IRONKEEP_COMPANION_AUTH",
    "DISCORD_BOT_TOKEN",
    "DISCORD_CLIENT_ID",
    "DISCORD_CLIENT_SECRET",
    "DISCORD_TOKEN",
):
    os.environ.pop(name, None)
os.environ["IRONKEEP_ENV_FILE"] = "/tmp/ironkeep-phase2-no-such-env"

import ironkeep
import ironkeep.companion_auth as auth
import ironkeep.companion_reports as reports
import ironkeep.config as config

root = os.path.dirname(os.path.abspath(ironkeep.__file__))
if os.path.abspath(root).startswith("/var/lib/ironkeep"):
    sys.exit("Refusing to run inside the database directory")

for relative in ("config.py", "db.py", "main.py", "companion_auth.py", "companion_reports.py", "roster.py"):
    path = os.path.join(root, relative)
    if not os.path.isfile(path):
        sys.exit("Missing " + path)
    if path.endswith(".py"):
        py_compile.compile(path, doraise=True)

if config.companion_auth_enabled():
    sys.exit("IRONKEEP_COMPANION_AUTH is on in this process")
if config.DB_PATH == PRODUCTION_DB:
    sys.exit("This process resolved the production database")
if "guild_game" not in auth.connect_allowed.__code__.co_names:
    sys.exit("The WoW guild check is missing from connect_allowed")
names = auth.upload_attendance.__code__.co_names
if "connect_allowed" not in names or "_upload_guild" not in names:
    sys.exit("Upload does not recheck the guild bound to the token")
if not hasattr(reports, "parse_text") or not hasattr(reports, "store"):
    sys.exit("Report parser is missing")
import ironkeep.db as database
import ironkeep.roster as roster
deletion = inspect.getsource(database.delete_guild) + inspect.getsource(database._delete_companion_reports)
if "_delete_companion_reports" not in inspect.getsource(database.delete_guild):
    sys.exit("Guild deletion does not remove companion reports")
if "companion_reports" not in deletion or "companion_report_hashes" not in deletion:
    sys.exit("Guild deletion does not remove companion reports")
if "_delete_roster" not in inspect.getsource(database.delete_guild):
    sys.exit("Guild deletion does not remove a roster snapshot")
if not hasattr(roster, "parse_body") or not hasattr(roster, "store"):
    sys.exit("Roster parser is missing")
main_source = open(os.path.join(root, "main.py"), encoding="utf-8").read()
roster_page = main_source.split("def guild_roster", 1)
if len(roster_page) != 2 or "_away_from" not in roster_page[1].split("\ndef ", 1)[0]:
    sys.exit("Roster page is missing the game check")
if '"roster":' not in main_source:
    sys.exit("Roster is missing from page access")
if "LIMIT 20" in inspect.getsource(reports.store):
    sys.exit("Report storage still trims accepted reports")

routes = sorted(
    (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", None) or ())))
    for route in auth.router.routes
)
expected = [
    ("/api/companion/guilds", ("GET",)),
    ("/api/companion/guilds/{slug}/attendance", ("POST",)),
    ("/api/companion/guilds/{slug}/roster", ("POST",)),
    ("/api/companion/logout", ("POST",)),
    ("/api/companion/revoke", ("POST",)),
    ("/api/companion/token", ("POST",)),
    ("/companion/connect", ("GET",)),
    ("/companion/connect", ("POST",)),
]
if routes != expected:
    shown = ", ".join(" ".join(methods) + " " + path for path, methods in routes)
    sys.exit("Unexpected Companion routes: " + shown)

print("import check ok")
print("flag off")
print("routes " + ", ".join(" ".join(methods) + " " + path for path, methods in routes))
print("database " + (config.DB_PATH or "(unset)"))
