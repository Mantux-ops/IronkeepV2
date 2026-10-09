"""Runtime configuration. The dashboard stays on sample data until the Discord values are set."""

import os

SUPERADMIN_ID = "268813802391207937"
PUBLIC_URL = "https://ironkeep.gg"

# View channel, send messages, embed links, read history, view audit log, manage roles.
INVITE_PERMISSIONS = (1 << 7) + (1 << 10) + (1 << 11) + (1 << 14) + (1 << 16) + (1 << 28)

RESERVED_SLUGS = {
    "admin", "api", "auth", "login", "logout", "privacy", "prototype", "static", "trial",
}


def _load_env_file():
    path = os.environ.get("IRONKEEP_ENV_FILE", "/etc/ironkeep.env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
PUBLIC_URL = os.environ.get("IRONKEEP_PUBLIC_URL", PUBLIC_URL).rstrip("/")


def live() -> bool:
    return bool(BOT_TOKEN and CLIENT_ID and CLIENT_SECRET)


DB_PATH = os.environ.get("IRONKEEP_DB") or ("/var/lib/ironkeep/ironkeep.db" if live() else "")


def redirect_uri() -> str:
    return f"{PUBLIC_URL}/auth/callback"


def invite_url() -> str:
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}&permissions={INVITE_PERMISSIONS}&scope=bot%20applications.commands"
    )
