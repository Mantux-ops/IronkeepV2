# Ironkeep

Trial tracking for Discord guilds: a bot that follows joins and the trial role, and a dashboard at `ironkeep.gg/<guild>/trial` where recruiters see who needs attention, log observations and give a verdict.

This branch contains the **clickable prototype**. Every page uses sample data from `ironkeep/mock_data.py`. Nothing talks to Discord and nothing is saved: a reload resets everything.

## Run it locally

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
