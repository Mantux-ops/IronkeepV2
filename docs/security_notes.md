# IronkeepV2 — Security Notes

This document covers the security-sensitive aspects of running IronkeepV2.
Read it before deploying to production and before onboarding a real guild.

---

## Secrets Handling

### What counts as a secret

The following values are secrets and must never appear in source control,
log files, error messages, or screenshots shared externally:

| Secret | Why it is sensitive |
|--------|-------------------|
| `IRONKEEP_SESSION_SECRET` | Signs all user session cookies — leaking it allows session forgery |
| `DISCORD_BOT_TOKEN` | Full control over the Discord bot account — leaking it allows posting to all channels the bot can access |
| `DISCORD_CLIENT_SECRET` | OAuth2 secret — leaking it allows impersonating the application in OAuth flows |
| SQLite database file (`ironkeep_v2.db`) | Contains all guild data: user IDs, operation history, ledger entries, attendance records |
| Backup files (`.db`) | Same sensitivity as the live database |

### Where secrets go

- Store secrets in `/etc/ironkeep/ironkeep.env` (or equivalent), outside the
  project repository
- The file must be owned by the service user and `chmod 600`
- Reference the file in systemd units with `EnvironmentFile=`
- Never pass secrets as command-line arguments — they appear in process lists (`ps aux`)

### Generating the session secret

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Generate a new secret for each deployment. Do not reuse dev secrets in production.

---

## Private Repository Warning

> **If you fork or publish this repository, check your git history for secrets.**

Common mistakes to avoid:

- Committing a `.env` file, even temporarily, even in a private repo
- Committing `ironkeep_v2.db` or any backup `.db` file
- Hardcoding `DISCORD_BOT_TOKEN` or `DISCORD_CLIENT_SECRET` in any source file
- Including real secrets in test fixtures or test output

If a secret is accidentally committed:

1. Immediately rotate the secret (generate a new token, revoke the old one in
   Discord Developer Portal)
2. Remove the secret from git history using `git filter-repo` or equivalent
3. Force-push the cleaned history (coordinate with all collaborators)
4. Assume the secret is compromised even if the repo was private

---

## SQLite Database Security

The SQLite database file contains all application data. Treat it as sensitive
PII for any guild that uses the system.

- **Do not place the DB file inside the web root** or any publicly accessible
  directory
- **Restrict filesystem permissions**: the DB file should be readable/writable
  only by the service user account
- **Backup files have the same sensitivity** as the live database — encrypt them
  if stored off-host or in a shared backup location
- **Do not commit the DB file** to source control under any circumstances
- **WAL and SHM files** (`ironkeep_v2.db-wal`, `ironkeep_v2.db-shm`) contain
  live transaction data and have the same sensitivity as the main DB file

---

## Discord Token Handling

The `DISCORD_BOT_TOKEN` grants the following capabilities to anyone who holds it:

- Post messages to any channel the bot has access to
- Read messages in channels the bot can see
- Edit or delete the bot's own messages

If the token is leaked:

1. Immediately go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your application → "Bot" → "Reset Token"
3. Update `DISCORD_BOT_TOKEN` in `/etc/ironkeep/ironkeep.env`
4. Restart the web process and scheduler

The `DISCORD_CLIENT_SECRET` is separate from the bot token. If it is leaked,
reset it in the Discord Developer Portal under "OAuth2 → Client Secret".

---

## Do Not Commit: File Checklist

Add these patterns to `.gitignore` to prevent accidental commits:

```gitignore
# Secrets and environment
.env
*.env
!.env.example

# Database files
*.db
*.db-wal
*.db-shm

# Backup files
backups/
*.backup

# Python
__pycache__/
*.pyc
.venv/
```

Verify your `.gitignore` is in place and no untracked sensitive files appear in
`git status` before pushing to any remote.

---

## Session Security

- Session cookies are signed with `IRONKEEP_SESSION_SECRET`. Changing this
  secret invalidates all existing sessions (all users are logged out).
- In production (`IRONKEEP_ENV=production`), session cookies are set with
  `HttpOnly`, `SameSite=Lax`, and `Secure` (HTTPS-only) flags automatically.
- There is no "remember me" or persistent login. Sessions expire when the browser
  closes or the session cookie is cleared.
- There is no session revocation endpoint. If a user account is compromised,
  changing `IRONKEEP_SESSION_SECRET` logs out all active sessions.

---

## Network Exposure

- The web process should **not** be exposed directly on port 80/443. Use a
  reverse proxy (nginx, Caddy, Traefik) to handle TLS termination and forward
  to `localhost:8000`.
- The scheduler process makes **outbound** HTTPS calls to Discord APIs. It does
  not bind any port.
- The SQLite database is a local file. There is no database port to expose or
  firewall.
- The `/health` endpoint is unauthenticated by design — it exposes only
  operational state (scheduler status, retry count), not guild data.

---

## What the Application Does NOT Do

The following security concerns are outside the current scope and should be
addressed at the infrastructure level:

- **TLS/HTTPS** — handle via reverse proxy, not the application itself
- **DDoS protection** — handle via CDN or cloud provider rate limiting
- **Rate limiting on login** — no built-in brute-force protection on the OAuth
  callback; Discord OAuth handles the authentication strength
- **Audit logging of admin actions** — operation-level events are logged in the
  operational events table, but there is no separate security audit log
