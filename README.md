# Ironkeep

Trial tracking for Discord guilds: a bot that follows joins and the trial role, and a dashboard at `ironkeep.gg/<guild>/trial` where recruiters see who needs attention, log observations and give a verdict.

Without Discord credentials this is the **clickable prototype**. Every page uses sample data from `ironkeep/mock_data.py` and a reload resets it.

With `DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` set (see `/etc/ironkeep.env` on the server), the same pages use the live bot: Discord login, an invite link, and one environment per server the bot joins. The bot process is `python -m ironkeep.bot`. It needs the Server Members intent enabled in the Discord developer portal, and the OAuth redirect URL must be `https://ironkeep.gg/auth/callback`.

## Run it with Docker

```bash
docker compose up --build
```

Open http://localhost:8000. The `ironkeep` folder is mounted into the container, so after `git pull` the changes show up without restarting. Only a change to `requirements.txt` needs `docker compose up --build` again. Stop it with Ctrl+C, or `docker compose down` if it runs in the background.

## Run it without Docker

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn ironkeep.main:app --reload
```

Open http://localhost:8000. The bar at the top switches between the superadmin view and a recruiter view.

## Pages

| Address | What it is |
| --- | --- |
| `/` | Landing page with "Add to Discord" |
| `/login` | Discord login (skipped in the prototype) |
| `/dutchchaos/trial` | Trials: needs-action list, all trials, side panel with timeline, observations, extend and verdict |
| `/dutchchaos/settings` | Guild settings: roles and channels by name, trial length, messages, verdict roles, permission checks |
| `/blackrose/setup` | Setup wizard for a newly added guild that is waiting for approval |
| `/admin` | Superadmin: all guilds, approval requests |
| `/admin/errors` | Superadmin: problems the bot ran into in Discord |
| `/admin/data` | Superadmin: export or delete everything stored about one Discord user |
| `/privacy` | Draft privacy policy |

## Layout

- `ironkeep/main.py`: routes
- `ironkeep/mock_data.py`: sample guilds, roles, channels and trials
- `ironkeep/templates/`: Jinja templates, `app_layout.html` is the shared sidebar layout
- `ironkeep/static/css/app.css`: the whole design system
- `ironkeep/static/js/`: `trials.js`, `settings.js` and `admin.js` for the interactive parts, `common.js` for shared helpers
