# Phase 2 deployment package

This package adds Companion attendance upload to a server that already runs Companion Phase 1, including the membership fix `858f983` and the WoW-only filter from PR #39 (`8cc056c`). It does not set `IRONKEEP_COMPANION_AUTH`. It does not open the database, restart a service, or change the Discord bot.

Do not copy `production/ironkeep/` onto the server. Do not run the Phase 1 installer again after this package: that installer still carries the Phase 1 `companion_auth.py` and would remove the upload route.

## Files

| File in this package | Target |
|---|---|
| `new/companion_reports.py` | `/opt/ironkeep/ironkeep/companion_reports.py` (new, or replace the first Phase 2 copy) |
| `new/db.py` | `/opt/ironkeep/ironkeep/db.py` (replace) |
| `new/companion_auth.py` | `/opt/ironkeep/ironkeep/companion_auth.py` (replace) |
| `MANIFEST.txt` | Expected hashes |
| `install.sh` | Dry-run or install |
| `check_imports.py` | Import check without the production database |
| `DEPLOY.md` | This procedure |
| `test_install.sh` | Local only. Do not copy it to the server. |

The live `companion_auth.py` must be the Phase 1 file `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4` or this package's copy. The live `db.py` must be `74f41dbc2c55f87143ad37fa987e8c35657ab8e325611dc36c53f6948b9cae54`, the previous Phase 2 file `5763c4de000dae2fe1aae0e567014a9ac886290f12dfcd67567ac81dd5315502`, or this package's copy. Any other hash is refused. `install.sh` does not patch `main.py`.

## Hashes

| File | Before | After |
|---|---|---|
| `companion_auth.py` | `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4` | `8799e163f0db6123605671c8b5db4b12d472af130c845b64f5523cbcf20ef6ca` |
| `companion_reports.py` | absent, or `51726eed1fa54aa0c05d395d671a1160400b5ae5c864d5c6ea6f5f6824ee42b2` | `9029173db99e1a2921f710b279529e7fe94a768852025617146d40d0efb7bab4` |
| `db.py` | `74f41dbc2c55f87143ad37fa987e8c35657ab8e325611dc36c53f6948b9cae54`, or `5763c4de000dae2fe1aae0e567014a9ac886290f12dfcd67567ac81dd5315502` | `98a2ec96be0ef3db7e35134f265c784a649568e54547e2da678571d0e90a4b80` |

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

`companion_reports.py` is copied first, then `db.py`, then `companion_auth.py`. The new files keep the owner, group, and mode of the previous `companion_auth.py`. If a new hash does not match, the previous files are restored and a `companion_reports.py` created by this run is removed.

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

- `companion_reports` stores the parsed place, start time, receipt time, people, and body hash. Accepted reports are kept.
- `companion_report_hashes` stores every accepted hash. The same normalized text returns `{"ok":true,"duplicate":true}` and the stored report stays in place.

`CREATE TABLE IF NOT EXISTS` is safe on a database that does not have these tables. There is no migration of existing rows. Raid tables, including `raid_attendance`, are not read or written by an upload. The tables are not created while the Companion flag is off, and they are not created for a rejected upload. Deleting a guild deletes that guild's rows from both tables in the same transaction as the guild row. The same delete removes `companion_connect` and `companion_credentials` for that guild when those tables exist. If the tables were never created, guild deletion still removes the guild and does not create them.

A database that already ran the earlier 20-row trim cannot get those removed report bodies back. That trim was not deployed. Hashes left without a report row would still count as duplicates; this package does not rewrite existing hash rows.

## Rollback

Restore the saved module and remove the new parser, then restart only `ironkeep.service`:

```bash
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/db.py /opt/ironkeep/ironkeep/db.py
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/companion_auth.py /opt/ironkeep/ironkeep/companion_auth.py
if [[ -f /home/ironadmin/companion-phase2-files-20261106/companion_reports.py ]]; then
  sudo cp -p /home/ironadmin/companion-phase2-files-20261106/companion_reports.py /opt/ironkeep/ironkeep/companion_reports.py
else
  sudo rm -f /opt/ironkeep/ironkeep/companion_reports.py
fi
sudo systemctl restart ironkeep.service
```

Confirm `db.py` is again `74f41dbc2c55f87143ad37fa987e8c35657ab8e325611dc36c53f6948b9cae54` and `companion_auth.py` is again `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4` when rolling all the way back to Phase 1.

Leave `companion_reports` and `companion_report_hashes` in place. Nothing else reads them, so the rolled-back site ignores them. Drop them only if the uploaded reports themselves must be discarded:

```sql
DROP TABLE IF EXISTS companion_reports;
DROP TABLE IF EXISTS companion_report_hashes;
```

Take a database backup before that drop. Dropping them does not affect raids.

## Manual check with Windows Companion 2.0.0

Use a guild whose profile is World of Warcraft, with the signed-in Discord account in the guild and holding a Companion role. No Companion or addon update is required.

1. Confirm the running site is this package: `companion_auth.py` hash `8799e163f0db6123605671c8b5db4b12d472af130c845b64f5523cbcf20ef6ca`, `companion_reports.py` hash `9029173db99e1a2921f710b279529e7fe94a768852025617146d40d0efb7bab4`, and `db.py` hash `98a2ec96be0ef3db7e35134f265c784a649568e54547e2da678571d0e90a4b80`.
2. Open the Companion, signed in with Discord, and select that guild. The site address stays `https://ironkeep.gg` unless settings say otherwise.
3. Log out of WoW once so `WTF/Account/<account>/SavedVariables/Ironkeep.lua` contains a group. Click **Sync now**.
4. The client posts `text/plain; charset=utf-8` to `POST /api/companion/guilds/<slug>/attendance` with `Authorization: Bearer ika.…`. A new report is HTTP 200 and `{"ok":true}`. The Failed count stays at 0. Pending returns to 0.
5. Click **Sync now** again without changing the group. The response is `{"ok":true,"duplicate":true}`. The client still treats that as confirmed.
6. A report that previously failed with HTTP 404 stays in Failed until **Retry failed** in settings. After this route is live, that retry posts the same saved text.
7. Do not expect the raid attendance page to gain these players. The upload is stored only as a Companion report.

Stop if Sync now returns HTTP 404. That means this process is still on the Phase 1 module or the website was not restarted.
