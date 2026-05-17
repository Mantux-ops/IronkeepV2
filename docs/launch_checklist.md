# IronkeepV2 — Launch Readiness Checklist

Complete every item on this list before directing a real guild to the system.
Mark each item ✅ as you verify it. Do not skip items — each has caused issues
in testing or past deployments.

---

## 1. Environment Variables

- [ ] `IRONKEEP_ENV=production` is set
- [ ] `IRONKEEP_SESSION_SECRET` is set to a strong random value (not the dev default)
  - Verify: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] `IRONKEEP_DB_PATH` is an absolute path on a persistent volume
- [ ] `DISCORD_BOT_TOKEN` is set and the bot is in the guild's Discord server
- [ ] `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` are set
- [ ] `DISCORD_OAUTH_REDIRECT_URI` matches the URL registered in the Discord Developer Portal exactly (including trailing slash if any)
- [ ] `WEB_BASE_URL` is set to the public HTTPS URL of the application

---

## 2. Process Supervision

- [ ] Web process (`uvicorn app.main:app`) starts cleanly with no `RuntimeError` in logs
- [ ] Web process is supervised (systemd, screen, or similar) and restarts on failure
- [ ] Scheduler process (`python -m app.scheduler`) starts with `SCHEDULER_ENABLED=1`
- [ ] Scheduler process is supervised separately from the web process
- [ ] Both processes restart automatically after a server reboot
  - Verify: `systemctl is-enabled ironkeep-app ironkeep-scheduler`

---

## 3. Health Endpoint

- [ ] `GET /health` returns HTTP 200
- [ ] Response body contains `"status": "ok"`
- [ ] `"db_reachable": true` in response
- [ ] `"wal_mode": true` in response
- [ ] `"scheduler"` field is `"ok"` (not `"stale"` or `"stuck"`)
- [ ] Monitoring/uptime tool is pointed at `/health`

```bash
curl -s https://your-domain.example.com/health | python -m json.tool
```

---

## 4. Diagnostics Page

- [ ] Log in as an officer or owner and visit `/workspaces/<slug>/settings/diagnostics`
- [ ] "Database — Reachable ✓ yes" shown
- [ ] "WAL mode — enabled" shown
- [ ] DB file size is non-zero and plausible
- [ ] Scheduler health banner shows "✓ Healthy"
- [ ] Pending retries count is 0 (or explains any non-zero entries)
- [ ] Recent error count is 0

---

## 5. Backup Created and Verified

- [ ] A backup has been created using `scripts/backup_db.py`
  ```bash
  python scripts/backup_db.py --backup-dir /var/lib/ironkeep/backups/ --verify
  ```
- [ ] Backup reports `"ok"` from `--verify`
- [ ] Backup file exists in the expected directory
- [ ] Backup directory is on a different path than the live database (ideally different disk or host)

---

## 6. Restore Rehearsal Completed

- [ ] You have read the restore procedure in `docs/deployment.md`
- [ ] A restore rehearsal has been performed on a **non-production** copy of the database
  - Stop the test app, replace the DB file with the backup, restart, confirm data is present
- [ ] `startup.check_core_tables()` and `startup.check_integrity()` both pass on the restored file
- [ ] You know which command to run to stop both services before a real restore

---

## 7. Discord Configuration Tested

- [ ] In the workspace Discord settings, at least one announcement channel is configured
- [ ] "Post to Discord" button on a test operation produces a message in the expected channel
- [ ] "Update Roster Post" updates an existing announcement correctly
- [ ] Bot has the required permissions in the configured channel (Send Messages, Embed Links, Read Message History)
- [ ] `discord_reminders_enabled` checkbox tested: reminder message appears in the channel at the expected time (or scheduled for one)

---

## 8. OAuth Login Tested

- [ ] Discord OAuth login flow completes end-to-end for a test user
- [ ] User is assigned the correct role (owner for first login if no workspace exists yet)
- [ ] Logging out and back in works without errors
- [ ] Redirect URI mismatch error does not appear (check Discord Developer Portal)

---

## 9. Reminder Job Tested

- [ ] A test operation with a `scheduled_start_at` within the reminder window has been created
- [ ] The scheduler has run at least once since the operation was created (check scheduler logs)
- [ ] A reminder message appears in the Discord channel (or retry entry visible in `/settings/scheduler`)
- [ ] Re-running the scheduler does not send a duplicate reminder

---

## 10. Ledger Export Tested

- [ ] Create a test operation with at least one ledger entry (regear, payout, or adjustment)
- [ ] Export via "Export CSV" link on the ledger page
- [ ] CSV file opens correctly in a spreadsheet application
- [ ] All columns are present: `operation_id`, `participant_id`, `entry_type`, `status`, `amount_silver`, `note`, `created_by`, `created_at`, `updated_at`, `voided_at`, `voided_by`, `paid_at`, `paid_by`
- [ ] Signed adjustment amounts are preserved correctly (negative values not truncated)

---

## 11. Rollback Plan Known

- [ ] You have read the rollback procedure in `docs/deployment.md`
- [ ] You know which `git` command reverts to the previous release tag
- [ ] You know that schema migrations are additive-only (rollback does not require DB changes for standard releases)
- [ ] The pre-restore safety copy step is understood: `cp ironkeep_v2.db ironkeep_v2.db.pre-restore` before replacing

---

## Sign-off

When all items above are checked:

- [ ] Date verified: _______________
- [ ] Verified by: _______________
- [ ] Pilot guild name: _______________
- [ ] Initial workspace slug: _______________
