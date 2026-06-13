# IronkeepV2 — Final Pre-Live Checklist

> Complete all sections before sharing the signup link with the alliance.

---

## 1. Database Backup

- [ ] Copy `ironkeep.db` to a safe location before the trial starts
- [ ] Confirm the copy is readable:
  ```
  python -c "import sqlite3; print(sqlite3.connect('backup.db').execute('SELECT 1').fetchone())"
  ```

**Notes / issues:**

---

## 2. Environment Variables

- [x] `DISCORD_BOT_TOKEN` — set and valid (bot must already be in the server)
- [x] `DISCORD_GUILD_ID` — your Discord server's snowflake ID (18 digits, configured in Workspace → Settings → Discord)
- [x] `DISCORD_ANNOUNCEMENT_CHANNEL_ID` — configured in Workspace → Settings → Discord
- [x] `WEB_BASE_URL` — set to your public URL if behind a reverse proxy or ngrok  
  _(e.g. `https://ironkeep.yourdomain.com` — skip if running fully local, the app builds URLs from the request automatically)_

**Notes / issues:**

---

## 3. Network / Public Access

- [x] Open the signup URL on a different device or browser (phone is fine):
  ```
  http://YOUR_HOST/workspaces/YOUR_SLUG/operations/OP_ID/signup
  ```
- [x] Confirm the page loads and the signup form is visible without an officer account
- [x] If behind a firewall or on localhost, confirm port forwarding / ngrok tunnel is active **before** sharing the link

**Notes / issues:**

---

## 4. Non-Member Smoke Test

_Takes ~2 minutes. Do this before the actual trial._

- [x] Log in as a non-officer test account (or ask a friend)
- [x] Navigate to the signup URL directly
- [x] Submit a signup — confirm it appears in the signed-up list
- [x] Withdraw the signup — confirm it disappears from the list
- [x] Confirm the **Withdraw** button appears only for your own row, not other players' rows

**Notes / issues:**
After withdraw and again sign up it states: 
  'Testplayer1' has already submitted a signup for this operation.

Signed in as Testplayer2 however the Withdraw option is available for every testplayer (2,3,4 and 5) but not on my dev account. 
---

## 5. Discord Announcement

- [x] Log in as officer account
- [x] Open the operation overview page
- [x] Check the **Discord Announcement Preview** card — confirm the signup URL appears in the description text
- [x] Click **Post Announcement** — confirm the message appears in the Discord channel
- [x] In Discord, click the **Open Signup Page** button — confirm it opens the correct URL on the correct device

**Notes / issues:**

---

## 6. Officer Planner Access

- [x] Log in as officer account
- [x] Open the **Planner** tab for the operation
- [x] Confirm assignment controls are visible: Assign / Quick Assign / Quick Fill Party
- [x] Assign one test participant — confirm the page scrolls back to the correct party after redirect
- [x] Confirm readiness updates automatically after assignment

**Notes / issues:**

---

## 7. Operational Discipline

- [x] Keep the operation in **planning** status until the final roster is confirmed
- [x] Only click **Lock Roster** when you are truly done assigning — this cannot be undone from the UI
- [x] After locking, confirm the planner shows read-only view before announcing the roster to the guild
- [x] Confirm the lock confirmation dialog appears before the lock goes through

**Notes / issues:**

---

## 8. Manual Fallback (prepare before going live)

- [ ] Draft a fallback Discord message or spreadsheet with the composition and role list
- [ ] If the app fails mid-session, paste the fallback immediately — do not leave players waiting
- [ ] Note the officer account credentials somewhere offline in case of session issues

**Fallback message draft location:**

---

## Final Go / No-Go

| Check | Status |
|---|---|
| Signup URL opens from outside device | |
| Non-member can submit and withdraw | |
| Discord announcement includes signup link | |
| Officer can access planner and assign | |
| Lock confirmation dialog works | |
| Manual fallback ready | |

**Ready for live trial? Yes / No**

**Blockers found:**

**Go time:**
