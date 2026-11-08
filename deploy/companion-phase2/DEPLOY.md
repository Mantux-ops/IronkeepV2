# Phase 2 deployment package

This package adds Companion attendance upload to a server that already runs Companion Phase 1, including the membership fix `858f983` and the WoW-only filter from PR #39 (`8cc056c`). It does not set `IRONKEEP_COMPANION_AUTH`. It does not open the database, restart a service, or change the Discord bot.

Do not copy `production/ironkeep/` onto the server. Do not run the Phase 1 installer again after this package: that installer still carries the Phase 1 `companion_auth.py` and would remove the upload route.

## Files

| File in this package | Target |
|---|---|
| `new/companion_reports.py` | `/opt/ironkeep/ironkeep/companion_reports.py` (new, or replace the first Phase 2 copy) |
| `new/roster.py` | `/opt/ironkeep/ironkeep/roster.py` (new) |
| `new/db.py` | `/opt/ironkeep/ironkeep/db.py` (replace) |
| `new/companion_auth.py` | `/opt/ironkeep/ironkeep/companion_auth.py` (replace) |
| `new/main.py` | `/opt/ironkeep/ironkeep/main.py` (replace, only when it matches the accepted hash) |
| `new/templates/roster.html` | `/opt/ironkeep/ironkeep/templates/roster.html` (new) |
| `patch_layout.py` | Inserts the Roster link into the existing `templates/app_layout.html` |
| `MANIFEST.txt` | Expected hashes |
| `install.sh` | Dry-run or install |
| `check_imports.py` | Import check without the production database |
| `DEPLOY.md` | This procedure |
| `test_install.sh` | Local only. Do not copy it to the server. |

The live `companion_auth.py` must be the Phase 1 file `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4`, the attendance package `8799e163f0db6123605671c8b5db4b12d472af130c845b64f5523cbcf20ef6ca`, or this package's copy. The live `db.py` must be `74f41dbc2c55f87143ad37fa987e8c35657ab8e325611dc36c53f6948b9cae54`, the previous Phase 2 file `5763c4de000dae2fe1aae0e567014a9ac886290f12dfcd67567ac81dd5315502`, the credential-cleanup file `98a2ec96be0ef3db7e35134f265c784a649568e54547e2da678571d0e90a4b80`, or this package's copy. The live `main.py` must be `f527479bb12ba29fe296504360191f79885db62c4cd4704aca9dcd5077c8c126` or this package's copy. Any other hash is refused. `templates/app_layout.html` is not replaced. The installer inserts the Roster link inside the WoW branch's `{% if access.members %}` gate. It does not change the Albion or not-live Members link. It refuses when the WoW and Albion branches are missing, are not one `if` / `elif` chain, or the WoW Members link is not inside that permission gate.

## Hashes

| File | Before | After |
|---|---|---|
| `companion_auth.py` | `1d7002587fc4bfc92f1d340c71b955c33bd0038715c1e6f94489f1f018bc08d4`, or `8799e163f0db6123605671c8b5db4b12d472af130c845b64f5523cbcf20ef6ca` | `16ce7bec747d964b69b47190b20873e103c58918abc04b22583656646360206b` |
| `companion_reports.py` | absent, or `51726eed1fa54aa0c05d395d671a1160400b5ae5c864d5c6ea6f5f6824ee42b2` | `9029173db99e1a2921f710b279529e7fe94a768852025617146d40d0efb7bab4` |
| `db.py` | `74f41dbc2c55f87143ad37fa987e8c35657ab8e325611dc36c53f6948b9cae54`, `5763c4de000dae2fe1aae0e567014a9ac886290f12dfcd67567ac81dd5315502`, or `98a2ec96be0ef3db7e35134f265c784a649568e54547e2da678571d0e90a4b80` | `189145ec7b328cf387565cd1dd00e28abcaf360a23e37702a9f6e88bf5a9308a` |
| `main.py` | `f527479bb12ba29fe296504360191f79885db62c4cd4704aca9dcd5077c8c126` | `0738ed6ae99b1db01c08fb7bff5139dbf84fa70ab40e5d3b0fde98a633bab41a` |
| `roster.py` | absent, or `24c5d0cb2c9f51f9213f70fdb608910e15c376d018825e8681d40dcec52d4fa2` | `d7b0fcb2b526f8d6b42e09fbf417ed993d80572e43bd3e056ec6949258f16209` |
| `templates/roster.html` | absent, `fefc7eb77e68993c513f8efd16a4c3f050c745a3046b1a866efc98a178c8f4d8`, `4d9647f1131c51e652e591e84b47e573798da727da5cf5aa6a724965e24379f8`, or `bb443c9a5d5c27d489becf140a05f11ee2fa9c792efb0b01d07ef1ff7dae6656` | `ca798900d9fcb774320c04fabf7ae482b50f16e9a2902a3161f23cf72d7d688b` |

## Dry-run

```bash
sudo bash /home/ironadmin/companion-phase2-package/install.sh --root /opt/ironkeep/ironkeep
```

Expected: `dry-run ok`, then each file it would install and the Roster link it would add. Nothing is written.

## Install

```bash
sudo bash /home/ironadmin/companion-phase2-package/install.sh \
  --root /opt/ironkeep/ironkeep \
  --apply \
  --backup-dir /home/ironadmin/companion-phase2-files-20261106
```

`companion_reports.py` is copied first, then `roster.py`, `db.py`, `companion_auth.py`, `main.py`, and `templates/roster.html`. The Roster link is inserted after that, only inside the WoW Members gate. New files keep the owner, group, and mode of the previous `companion_auth.py`, and `main.py` keeps its own. If a new hash does not match, or the layout insert fails, the previous files are restored and a file created by this run is removed. `templates/app_layout.html` is restored from the backup as well. Do not copy the rest of `production/ironkeep/templates/` onto the server. The layout, icons, and forbidden page already there stay in place.

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

`CREATE TABLE IF NOT EXISTS` is safe on a database that does not have these tables. There is no migration of existing rows. Raid tables, including `raid_attendance`, are not read or written by an upload. The tables are not created while the Companion flag is off, and they are not created for a rejected upload. Deleting a guild deletes that guild's rows from both tables in the same transaction as the guild row. The same delete removes `companion_connect` and `companion_credentials` for that guild when those tables exist. It also removes `roster_snapshots` and `roster_hashes` when those tables exist. If the tables were never created, guild deletion still removes the guild and does not create them.

A database that already ran the earlier 20-row trim cannot get those removed report bodies back. That trim was not deployed. Hashes left without a report row would still count as duplicates; this package does not rewrite existing hash rows.

## Rollback

Restore the saved module and remove the new parser, then restart only `ironkeep.service`:

```bash
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/db.py /opt/ironkeep/ironkeep/db.py
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/companion_auth.py /opt/ironkeep/ironkeep/companion_auth.py
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/main.py /opt/ironkeep/ironkeep/main.py
sudo cp -p /home/ironadmin/companion-phase2-files-20261106/templates/app_layout.html /opt/ironkeep/ironkeep/templates/app_layout.html
if [[ -f /home/ironadmin/companion-phase2-files-20261106/companion_reports.py ]]; then
  sudo cp -p /home/ironadmin/companion-phase2-files-20261106/companion_reports.py /opt/ironkeep/ironkeep/companion_reports.py
else
  sudo rm -f /opt/ironkeep/ironkeep/companion_reports.py
fi
sudo rm -f /opt/ironkeep/ironkeep/roster.py /opt/ironkeep/ironkeep/templates/roster.html
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

1. Confirm the running site is this package: `companion_auth.py` hash `16ce7bec747d964b69b47190b20873e103c58918abc04b22583656646360206b`, `companion_reports.py` hash `9029173db99e1a2921f710b279529e7fe94a768852025617146d40d0efb7bab4`, `db.py` hash `189145ec7b328cf387565cd1dd00e28abcaf360a23e37702a9f6e88bf5a9308a`, `main.py` hash `0738ed6ae99b1db01c08fb7bff5139dbf84fa70ab40e5d3b0fde98a633bab41a`, and `roster.py` hash `d7b0fcb2b526f8d6b42e09fbf417ed993d80572e43bd3e056ec6949258f16209`.
2. Open the Companion, signed in with Discord, and select that guild. The site address stays `https://ironkeep.gg` unless settings say otherwise.
3. Log out of WoW once so `WTF/Account/<account>/SavedVariables/Ironkeep.lua` contains a group. Click **Sync now**.
4. The client posts `text/plain; charset=utf-8` to `POST /api/companion/guilds/<slug>/attendance` with `Authorization: Bearer ika.…`. A new report is HTTP 200 and `{"ok":true}`. The Failed count stays at 0. Pending returns to 0.
5. Click **Sync now** again without changing the group. The response is `{"ok":true,"duplicate":true}`. The client still treats that as confirmed.
6. A report that previously failed with HTTP 404 stays in Failed until **Retry failed** in settings. After this route is live, that retry posts the same saved text.
7. Do not expect the raid attendance page to gain these players. The upload is stored only as a Companion report.

Stop if Sync now returns HTTP 404. That means this process is still on the Phase 1 module or the website was not restarted.
