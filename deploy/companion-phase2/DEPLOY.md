# Phase 2 deployment package

This package adds Companion attendance upload to a server that already runs Companion Phase 1, including the membership fix `858f983` and the WoW-only filter from PR #39 (`8cc056c`). It does not set `IRONKEEP_COMPANION_AUTH`. It does not open the database, restart a service, or change the Discord bot.

Do not copy `production/ironkeep/` onto the server. Do not run the Phase 1 installer again after this package: that installer still carries the Phase 1 `companion_auth.py` and would remove the upload route.

## Files

| File in this package | Target |
|---|---|
| `new/companion_reports.py` | `/opt/ironkeep/ironkeep/companion_reports.py` (new) |
| `new/companion_auth.py` | `/opt/ironkeep/ironkeep/companion_auth.py` (replace) |
| `MANIFEST.txt` | Expected hashes |
| `install.sh` | Dry-run or install |
| `check_imports.py` | Import check without the production database |
| `DEPLOY.md` | This procedure |
| `test_install.sh` | Local only. Do not copy it to the server. |

The live `companion_auth.py` must already be `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4`. Any other hash is refused. `install.sh` does not patch `db.py` or `main.py`.

## Hashes

| File | Before | After |
|---|---|---|
| `companion_auth.py` | `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4` | `8799e163f0db6123605671c8b5db4b12d472af130c845b64f5523cbcf20ef6ca` |
| `companion_reports.py` | does not exist yet | `51726eed1fa54aa0c05d395d671a1160400b5ae5c864d5c6ea6f5f6824ee42b2` |

## Dry-run

```bash
sudo bash /home/ironadmin/companion-phase2-package/install.sh --root /opt/ironkeep/ironkeep
```

Expected: `dry-run ok`, then the two files it would install. Nothing is written.

## Install

```bash
sudo bash /home/ironadmin/companion-phase2-package/install.sh \
  --root /opt/ironkeep/ironkeep \
  --apply \
  --backup-dir /home/ironadmin/companion-phase2-files-20261106
```

`companion_reports.py` is copied first. `companion_auth.py` is then replaced. Both files keep the owner, group, and mode of the previous `companion_auth.py`. If the new hashes do not match, the previous module is restored and a `companion_reports.py` created by this run is removed.

The import check does not open `/var/lib/ironkeep/ironkeep.db`:

```bash
cd /opt/ironkeep
/opt/ironkeep/.venv/bin/python /home/ironadmin/companion-phase2-package/check_imports.py
```

Expected: `import check ok` and `flag off`.

Restart only the website after the hashes match. Do not restart the bot. Do not change `/etc/ironkeep.env` in this step. The upload route stays hidden until `IRONKEEP_COMPANION_AUTH` is already on for Phase 1.

```bash
sudo systemctl restart ironkeep.service
```

## Database

No migration script runs. The first accepted upload creates two tables if they are absent:

- `companion_reports` stores the parsed place, start time, receipt time, people, and body hash. At most 20 rows per guild are kept.
- `companion_report_hashes` stores every accepted hash. A repeated report returns `{"ok":true,"duplicate":true}` even after its visible row was trimmed.

`CREATE TABLE IF NOT EXISTS` is safe on a database that does not have these tables. Raid tables, including `raid_attendance`, are not read or written. Existing guild, trial, and credential rows are not modified by the schema step. The tables are not created while the Companion flag is off, and they are not created for a rejected upload.

## Rollback

Restore the saved module and remove the new parser, then restart only `ironkeep.service`:

```bash
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/companion_auth.py /opt/ironkeep/ironkeep/companion_auth.py
sudo rm -f /opt/ironkeep/ironkeep/companion_reports.py
sudo systemctl restart ironkeep.service
```

Confirm `companion_auth.py` is again `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4`.

Leave `companion_reports` and `companion_report_hashes` in place. Nothing else reads them, so the rolled-back site ignores them. Drop them only if the uploaded reports themselves must be discarded:

```sql
DROP TABLE IF EXISTS companion_reports;
DROP TABLE IF EXISTS companion_report_hashes;
```

Take a database backup before that drop. Dropping them does not affect raids.

## Manual check with Windows Companion 2.0.0

Use a guild whose profile is World of Warcraft, with the signed-in Discord account in the guild and holding a Companion role. No Companion or addon update is required.

1. Confirm the running site is this package: `companion_auth.py` hash `8799e163f0db6123605671c8b5db4b12d472af130c845b64f5523cbcf20ef6ca` and `companion_reports.py` hash `51726eed1fa54aa0c05d395d671a1160400b5ae5c864d5c6ea6f5f6824ee42b2`.
2. Open the Companion, signed in with Discord, and select that guild. The site address stays `https://ironkeep.gg` unless settings say otherwise.
3. Log out of WoW once so `WTF/Account/<account>/SavedVariables/Ironkeep.lua` contains a group. Click **Sync now**.
4. The client posts `text/plain; charset=utf-8` to `POST /api/companion/guilds/<slug>/attendance` with `Authorization: Bearer ika.…`. A new report is HTTP 200 and `{"ok":true}`. The Failed count stays at 0. Pending returns to 0.
5. Click **Sync now** again without changing the group. The response is `{"ok":true,"duplicate":true}`. The client still treats that as confirmed.
6. A report that previously failed with HTTP 404 stays in Failed until **Retry failed** in settings. After this route is live, that retry posts the same saved text.
7. Do not expect the raid attendance page to gain these players. The upload is stored only as a Companion report.

Stop if Sync now returns HTTP 404. That means this process is still on the Phase 1 module or the website was not restarted.
