#!/usr/bin/env python3
"""Import the Companion module without opening the production database.

Run from the server after the files are in place:

    cd /opt/ironkeep
    .venv/bin/python /path/to/check_imports.py

The script drops Discord and database settings from its own process before
importing. It does not read /etc/ironkeep.env and it does not execute
ironkeep.main, because that calls db.init() and may refresh catalogs.
main.py, db.py, and the other patched files are compiled instead.
"""

import importlib
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
os.environ["IRONKEEP_ENV_FILE"] = "/tmp/ironkeep-phase1-no-such-env"

import ironkeep
import ironkeep.companion_auth as auth
import ironkeep.config as config
import ironkeep.discord_api as discord_api

root = os.path.dirname(os.path.abspath(ironkeep.__file__))
if os.path.abspath(root).startswith("/var/lib/ironkeep"):
    sys.exit("Refusing to run inside the database directory")

for relative in (
    "config.py",
    "discord_api.py",
    "db.py",
    "main.py",
    "companion_auth.py",
    "templates/companion_connect.html",
    "templates/settings.html",
    "static/js/settings.js",
):
    path = os.path.join(root, relative)
    if not os.path.isfile(path):
        sys.exit("Missing " + path)
    if path.endswith(".py"):
        py_compile.compile(path, doraise=True)

if config.companion_auth_enabled():
    sys.exit("IRONKEEP_COMPANION_AUTH is on in this process")
if config.DB_PATH == PRODUCTION_DB:
    sys.exit("This process resolved the production database")

bot_params = list(inspect.signature(discord_api.bot_member).parameters)
member_params = list(inspect.signature(discord_api.member_as_bot).parameters)
if bot_params != ["guild_id"]:
    sys.exit("bot_member signature changed: " + ",".join(bot_params))
if member_params != ["guild_id", "user_id"]:
    sys.exit("member_as_bot signature changed: " + ",".join(member_params))
if "member_as_bot" not in auth._member_roles.__code__.co_names:
    sys.exit("Companion role check does not call member_as_bot")
if "bot_member" in auth._member_roles.__code__.co_names:
    sys.exit("Companion role check calls bot_member")

routes = sorted(
    (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", None) or ())))
    for route in auth.router.routes
)
expected = [
    ("/api/companion/guilds", ("GET",)),
    ("/api/companion/logout", ("POST",)),
    ("/api/companion/revoke", ("POST",)),
    ("/api/companion/token", ("POST",)),
    ("/companion/connect", ("GET",)),
    ("/companion/connect", ("POST",)),
]
if routes != expected:
    shown = ", ".join(" ".join(methods) + " " + path for path, methods in routes)
    sys.exit("Unexpected Companion routes: " + shown)

required = {
    "config": ["companion_auth_enabled", "live", "DB_PATH", "SUPERADMIN_ID"],
    "db": ["connect", "companion_role_ids", "list_guilds", "get_session", "guild_by_slug", "guild_by_id"],
    "discord_api": ["member_as_bot", "DiscordError", "bot_member"],
    "main": ["SESSION_COOKIE", "render", "_secure"],
}
main_source = open(os.path.join(root, "main.py"), encoding="utf-8").read()
for name in required["main"]:
    if name not in main_source:
        sys.exit("main.py is missing " + name)
db_mod = importlib.import_module("ironkeep.db")
for name in required["db"]:
    if not hasattr(db_mod, name):
        sys.exit("db.py is missing " + name)

print("import check ok")
print("flag off")
print("routes " + ", ".join(" ".join(methods) + " " + path for path, methods in routes))
print("database " + (config.DB_PATH or "(unset)"))
