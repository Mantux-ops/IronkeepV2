# IronkeepV2 — Pilot Guild Onboarding Guide

This guide is written for the guild officers setting up IronkeepV2 for the first
time. It assumes the application is already running (see `docs/deployment.md`)
and the launch checklist is complete (see `docs/launch_checklist.md`).

---

## What Guild Officers Need Before Setup

Before the first login, make sure you have:

- **A Discord server** where the guild operates
- **A Discord bot** created in the Discord Developer Portal and invited to the guild server with the correct permissions (see below)
- **An officer Discord account** to use for the first OAuth login (this account becomes the workspace owner)
- **The public URL** of the application — e.g. `https://ironkeep.example.com`
- **At least one Discord text channel** for operation announcements

---

## Discord Permissions and Scopes

### OAuth2 scopes (set in Discord Developer Portal)

The application needs these OAuth2 scopes to authenticate users:

| Scope | Purpose |
|-------|---------|
| `identify` | Read the user's Discord ID and username |
| `guilds` | Read the list of guilds the user is in (optional, for future use) |

### Bot permissions (set when inviting the bot)

| Permission | Purpose |
|-----------|---------|
| Send Messages | Post operation announcements and rosters |
| Embed Links | Send rich embed cards |
| Read Message History | Edit existing roster posts via Update Roster Post |
| Use External Emojis | Optional — for richer formatting |

> **Note:** Give the bot access only to the channels you want it to post in.
> There is no need for administrator permissions.

### Redirect URI

Add the following redirect URI in the Discord Developer Portal under
**OAuth2 → Redirects**:

```
https://your-domain.example.com/auth/discord/callback
```

This must match `DISCORD_OAUTH_REDIRECT_URI` exactly.

---

## First Workspace Setup

1. **First login** — The first officer navigates to the application URL and logs
   in with Discord OAuth. The first user to log in is automatically the workspace
   **owner** once a workspace is created.

2. **Create a workspace** — After login, click "Create workspace". Choose a
   short, memorable slug (e.g. `crimson-order`). This appears in all URLs.

3. **Configure Discord settings** — Go to
   `Settings → Discord` and enter:
   - The channel ID where announcements should be posted
   - The channel ID for roster posts (can be the same channel)
   - Whether to enable operation reminders

4. **Invite other officers** — Go to `Settings → Members`. Other officers log in
   via OAuth and appear as members. Assign the `officer` role to those who should
   manage operations.

5. **Create a composition** — Under `Compositions`, create your guild's standard
   role templates (e.g. "5-Man ZvZ — Tank/Healer/3xDPS"). These are reused
   across operations.

---

## First Operation Workflow

A complete operation lifecycle looks like this:

1. **Create** — Officer creates an operation: title, type (zvz/avalon/etc),
   scheduled start time.

2. **Attach a composition** — Select a composition to define the slot structure
   for this operation.

3. **Publish** — Publishing makes the operation visible to all guild members and
   enables signups.

4. **Members sign up** — Members open the operation URL and click "Sign up".
   They can specify a preferred role/build.

5. **Officer assigns slots** — On the planner board, drag/assign participants to
   slots. Use Quick Assign to auto-fill unassigned slots.

6. **Post announcement** — Click "Post to Discord" to send a rich embed
   announcement to the configured channel with a sign-up button.

7. **Update Roster Post** — After assignments are finalised, click "Update Roster
   Post" to push the confirmed roster to the Discord announcement.

8. **Mark attendance** — After the operation, officers mark each participant as
   attended/absent on the Attendance page.

9. **Complete the operation** — Set the operation status to "completed". This
   locks assignments and attendance.

---

## Readiness and Reminder Expectations

### Readiness snapshot

The readiness panel on the planner shows how many core slots are filled versus
empty. It updates as assignments are made. There is no live polling — refresh
the page to see the latest state.

### Operation reminders

If `discord_reminders_enabled` is checked in workspace Discord settings,
the scheduler automatically sends a reminder message to the announcement channel
before each published operation. The reminder window and exact timing is
controlled by the scheduler poll interval (`SCHEDULER_POLL_SECONDS`, default 5
minutes). Reminders are sent once per operation — a restart or re-poll will not
produce duplicates.

### Readiness thresholds

There is no automatic "operation starts now" trigger. Readiness is a planning
aid, not a gate. Officers decide when an operation is ready based on filled
slots and the visual readiness banner.

---

## Payout Ledger Workflow

The payout ledger is the record of regear costs, payout distributions, and
adjustments for a specific operation.

### Creating entries

1. Open an operation → **Ledger** tab.
2. Click "Add entry". Fill in:
   - **Type**: `regear` (gear replacement cost), `payout` (silver distribution),
     or `adjustment` (any signed correction)
   - **Participant**: the player receiving the entry
   - **Amount (silver)**: non-negative for regear/payout; signed for adjustments
   - **Note**: optional freetext context (visible in CSV export)

### Approval and payment flow

| Status | Meaning | Next step |
|--------|---------|-----------|
| `draft` | Created, not yet reviewed | Officer edits or approves |
| `approved` | Reviewed and confirmed | Officer marks as paid |
| `paid` | Payment confirmed, locked | No further changes possible |
| `voided` | Cancelled, excluded from totals | No further changes possible |

Once an entry is `paid` or `voided`, it cannot be modified. This is intentional
— the ledger is an immutable audit trail.

### Exporting

Click **Export CSV** on the Ledger page to download all entries for an operation.
The CSV includes all statuses (including voided) with a `status` column so you
can filter in a spreadsheet.

---

## Known Limitations

The following features are **not yet available** in this pilot version:

- **Alliance support** — no cross-guild or alliance operations
- **Bulk payout workflows** — no automatic silver split calculation; amounts are
  entered manually
- **Role/build variants** — each composition slot has a single role+build; no
  "Tank: Mace or Swords" multi-option
- **In-app Discord invite links** — officers must share the app URL directly
- **Mobile-optimised UI** — the interface is desktop-first; mobile use is possible
  but not polished
- **Email / non-Discord auth** — login requires Discord OAuth; no password login
- **Audit log export** — the operation timeline is viewable in-app but not
  currently exportable
- **Public operation pages** — all pages require login; no public sign-up URLs

If a feature is critical for your guild, provide feedback so it can be
prioritised for a future slice.

---

## Support and Debug Information to Collect

If you encounter a bug or unexpected behaviour, collect the following before
reporting:

1. **Application version** — check the top of `app/main.py` for `version=`
2. **Steps to reproduce** — exact sequence of actions that triggered the issue
3. **URL** — the full URL where the issue occurred
4. **Expected vs actual behaviour** — what you expected vs what happened
5. **Scheduler logs** — `journalctl -u ironkeep-scheduler -n 50`
6. **App logs** — `journalctl -u ironkeep-app -n 50`
7. **Health endpoint output** — `curl -s https://your-domain.example.com/health`
8. **Diagnostics page screenshot** — `/workspaces/<slug>/settings/diagnostics`
9. **Scheduler status page screenshot** — `/workspaces/<slug>/settings/scheduler`
10. **DB file size** — visible on the diagnostics page (do not share the DB file itself — it contains all guild data)

> Do not share `.env` files, `DISCORD_BOT_TOKEN`, `IRONKEEP_SESSION_SECRET`,
> or the database file when reporting issues.
