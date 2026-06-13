# IronkeepV2 — Pre-Weekend Live Trial Checklist

**Purpose:** Operational dry-run before the live alliance Discord test.
**Scope:** One test workspace, one test operation, one caller/officer role.
**Not a dev doc.** Every item is something you can execute and tick off.

---

## How to Use This Checklist

1. Work through each section in order.
2. Tick each box as you verify it.
3. Write notes under sections where something looks off.
4. If a step **fails and blocks the next step**, add it to [Blockers Found](#blockers-found) immediately.
5. Fill in [Post-Trial Observations](#post-trial-observations) after completing the full run.

---

## 1. Environment Preparation

> Goal: confirm the server, database, and config are in a working state before touching any feature.

- [x] Start the local server (`uvicorn app.main:app --reload` or equivalent)
- [x] Confirm server is running with no startup errors in the terminal
- [x] Open the app in a browser and confirm the home/login page loads
- [x] Log in as an officer/owner test account
- [x] Confirm the test workspace dashboard is accessible
- [x] Confirm the navigation links (Compositions, Builds, Operations) are all reachable
- [x] If Discord is configured: confirm `discord_guild_id` and `discord_announcement_channel_id` are set in workspace settings
- [/] If Discord is NOT configured: note that Discord workflow (section 8) will be skipped

**Notes / Issues:**

```
(write here)
```

---

## 2. Build Import Validation

> Goal: bulk-create a realistic set of builds from a pasted spreadsheet to simulate real caller prep.

### Prepare a test paste block

Copy the following into the import textarea (adjust names to your guild's doctrine):

```
name	role	weapon_name	offhand_name	armor_name	shoes_name	cape_name	food_name	potion_name	notes
Main Tank	Tank	Tombstone	Mistcaller	Royal Armor	Soldier Boots	Thetford Cape	Beef Stew	Healing Potion	Main MT
Off Tank	Tank	Carving Sword	Mistcaller	Knight Armor	Soldier Boots	Thetford Cape	Beef Stew	Healing Potion	OT
Healer A	Healer	Holy Staff	Lymhurst Cape	Cleric Robe	Scholar Sandals	Lymhurst Cape	Soup	Resistance Potion	Primary Healer
Healer B	Healer	Hallowfall	Lymhurst Cape	Cleric Robe	Scholar Sandals	Lymhurst Cape	Soup	Resistance Potion	Backup Healer
DPS Crossbow	DPS	Repeating Crossbow		Mercenary Jacket	Soldier Boots	Fort Sterling Cape	Pork Omelette	Poison Potion	
DPS Frost	DPS	Frost Staff		Scholar Robe	Scholar Sandals	Bridgewatch Cape	Soup	Energy Potion	
Battlemount	Support	Incubus Mace	Mistcaller	Cultist Robe	Soldier Boots	Thetford Cape	Beef Stew	Healing Potion	
Scout	DPS	Bow		Assassin Jacket	Cultist Sandals	Bridgewatch Cape	Pork Omelette	Poison Potion	
Backup Crossbow	DPS	Repeating Crossbow		Mercenary Jacket	Soldier Boots	Fort Sterling Cape	Pork Omelette	Poison Potion	2nd Crossbow
```

### Validation steps

- [x] Navigate to **Builds → Import CSV**
- [x] Paste the block above into the textarea and click **Preview**
- [x] Confirm 9 rows are shown in the preview table with no validation errors
- [x] Confirm column headers are detected automatically (no manual mapping needed)
- [x] Click **Confirm Import**
- [x] Confirm redirect to builds list with a success message
- [x] Confirm all 9 builds are listed on the builds page
- [x] Open one build with optional fields (e.g. Main Tank) and verify `offhand_name`, `armor_name`, `cape_name`, `notes` saved correctly
- [x] Open one build with a blank optional field (e.g. DPS Crossbow — no offhand) and confirm it is stored as empty/blank, not as an error
- [x] Attempt to re-import the same paste and confirm the duplicates are **accepted** (duplicate names are allowed by design)

**Notes / Issues:**

```
(write here)
```

---

## 3. Composition Workflow

> Goal: build a composition from the imported builds and verify the planning surface is usable.

- [x] Navigate to **Compositions → New Composition**
- [x] Give it a name (e.g. `Weekend ZvZ Test`)
- [x] Add at least 5 slots, each assigned to a build from the import (use the dropdown/datalist)
- [x] Add at least 1 free-typed slot (type a weapon name without selecting from the library)
- [x] Save the composition
- [x] Open the composition detail page
- [x] Confirm the **Tactical Preview** renders correctly — roles visible, colour bars present
- [x] Toggle **Compact view** — confirm equipment summaries disappear and the view is cleaner
- [x] Toggle back to **Full view** — confirm equipment summaries return
- [-] Open a slot's quick-edit panel and change a field; confirm it saves correctly
- [x] Optionally: fork an existing build via **Fork →** on any build detail page and verify the pre-fill works
- [x] Optionally: test **Promote to library →** on the free-typed slot if weapon name is set

**Notes / Issues:**

```
When selecting builds from datalist/dropdown 'Role' is selected but does not update after changing. Example: 1e selection 'Main Tank' change to 'DPS Crossbow' 'Role' Stays 'Tank' So far it seems to every role. 

Healer is seen as 'Support' not 'Healer'

"[ ] Open a slot's quick-edit panel and change a field; confirm it saves correctly"
    Doesn't seem to save also not after refreshing the page. 
```

---

## 4. Operation Workflow

> Goal: create a real operation from the composition and verify the pre-signup state.

- [x] Navigate to **Operations → New Operation**
- [x] Set a name (e.g. `Saturday ZvZ`), date/time, and type
- [x] Attach the composition created in section 3
- [x] Confirm operation overview shows the correct composition name and slot count
- [x] Confirm **slot count** matches the composition slot count
- [x] Confirm the **Signup URL block** is visible in the Signups card
- [x] Click inside the signup URL input — confirm the full URL is selected automatically
- [x] Click **Copy** — confirm button briefly shows "Copied!" and reverts to "Copy"
- [x] Paste the copied URL into a text editor and verify it contains the correct workspace slug and operation ID
- [x] Confirm the existing **Signup page →** link is still present and navigates correctly

**Notes / Issues:**

```
(write here)
```

---

## 5. Participant Signup Workflow

> Goal: simulate real alliance players submitting signups, including non-members and edge cases.

### Setup

| Account | Membership | Expected behaviour |
|---|---|---|
| Officer account | Owner/Officer | Can manage all |
| Member account | Member | Can sign up |
| External account A | Non-member | Can sign up (open signup) |
| External account B | Non-member | Can sign up (open signup) |

- [x] Log in as the **officer account** — confirm you can access the operation overview
- [x] In a second browser or incognito window, log in as **External account A**
- [x] Navigate directly to the signup URL (from the copy button above)
- [x] Confirm External account A **sees the signup form** (not a 404 or login wall)
- [x] Submit a signup as External account A (choose a role, optionally a build)
- [x] Log back in as officer — confirm External account A's signup appears in the signup list
- [x] Log in as **External account B** and submit a second signup
- [x] Attempt a **duplicate signup** as External account A — confirm a clear error is shown (not a silent failure)
- [-] Test the **Withdraw** flow as External account A — confirm their signup is removed
- [-] Submit again as External account A post-withdrawal — confirm it is accepted
- [x] Log in as **Member account** and submit a signup — confirm it works normally
- [x] As officer: confirm all active signups are visible in the signup list

**Notes / Issues:**

```
As a external account filling in all the stuff to signup takes a lot of time and i think we can make this way faster. 

The Withdraw button is missing — this looks like a bug.

What should happen: When testplayer1 views the signup page and is already signed up, the page should detect their existing signup and show a Withdraw button next to their row (or replace the form with a "you are signed up" confirmation).

What you're seeing instead: The signup form is still showing as if testplayer1 isn't signed up, even though their row appears in the "Signed up (2)" table below. There is no Withdraw button anywhere.

Likely cause: The page detects an existing signup by matching the current user's user_id against stored signups. For non-members (visitors like testplayer1) that match may not be working correctly — so the page doesn't recognise them as already signed up, and therefore never shows the Withdraw button.

Practical impact for the trial: A non-member cannot withdraw their own signup from the UI. An officer would have to do it manually. This is a real friction point but not a blocking one for the trial itself.

Log it under "Minor Annoyances" in the checklist for now, and we can look at the fix after you finish the dry run. Say the word when you're ready.
```

---

## 6. Planner Workflow

> Goal: confirm the tactical planner is usable under realistic sign-up volume and that scroll/readiness work.

### Pre-conditions

- Operation must have at least 4–6 signups and slots before starting this section.

### Assignment flow

- [x] Open the **Tactical Planner** for the operation
- [x] Confirm all composition slots are visible, grouped by party
- [x] Assign a participant manually via the slot dropdown — confirm the page scrolls back to the correct party after save
- [x] Assign a second participant to a different party — confirm the scroll anchor points to the correct party (not party 1 every time)
- [-] Use **Quick Assign** on an unassigned slot — confirm it assigns a suitable participant and scrolls correctly
- [x] Unassign a participant — confirm the slot returns to unassigned and scroll anchor is correct
- [x] Reassign a slot to a different participant — confirm the swap works and the anchor is correct

### Readiness

- [x] After several assignments, confirm the **readiness bar/percentage** updates automatically (no manual refresh needed)
- [x] Click **Refresh Readiness** manually — confirm it recalculates and updates
- [x] Confirm readiness does not block or interfere with assignment actions

### Gap indicators

- [x] Confirm **role gap badges** (e.g. "TANK ×2 needed") are visible when slots are unfilled
- [x] Fill all slots — confirm gap badges disappear

### Usability

- [x] Assign participants to 5+ slots in quick succession — confirm no unexpected errors
- [x] Confirm the planner page is navigable without excessive scrolling (anchor links working)

**Notes / Issues:**

```
[ ] Use **Quick Assign** on an unassigned slot — confirm it assigns a suitable participant and scrolls correctly
    Here it doesn't take into account to what someone has signed. 

I notice that by Unassigned signups you can do assign to slot to all of them but when you assign it you'll have to do it again it resets the information, i rather have it so that it doesn't reset or it assigns all of the selected assign to slot. 

```

---

## 7. Lock / Finalization

> Goal: verify the lock flow is safe, guarded, and irreversible from the UI as intended.

- [x] On the operation overview page, click **Lock Roster**
- [x] Confirm the **confirmation dialog** appears with the message: *"Lock the roster? Assignment mutations will be disabled and cannot be undone from the UI."*
- [x] Click **Cancel** — confirm the roster is NOT locked
- [x] Click **Lock Roster** again and this time confirm the lock
- [x] Confirm the operation status changes to **locked** (or equivalent)
- [ ] Open the **Tactical Planner** — confirm assignment controls are no longer visible or are disabled
- [ ] Confirm the roster overview still renders correctly in read-only state
- [x] Confirm the readiness snapshot is still visible after locking

**Notes / Issues:**

```
[ ] Open the **Tactical Planner** — confirm assignment controls are no longer visible or are disabled
    after locking i can still unasign/assign
[ ] Confirm the roster overview still renders correctly in read-only state
    Not read-only state, but renders correctly
```

---

## 8. Discord Workflow

> Skip this section if no Discord server is configured in workspace settings.

- [x] On the operation overview page, confirm the **Discord Announcement Preview** card is visible
- [x] Review the embed preview — confirm operation name, date, and readiness display correctly
- [ ] Click **Post Announcement** (or equivalent button) — confirm it posts to the configured channel without error
- [ ] Share the **signup URL** in the Discord channel via the Copy button — confirm the URL resolves correctly when opened from Discord
- [ ] In the Discord message, confirm players can open the signup link without being an existing workspace member

**Notes / Issues:**

```
 [ ] Click **Post Announcement** (or equivalent button) — confirm it posts to the configured channel without error
    Discord API error 0: DISCORD_BOT_TOKEN is not set. Configure the environment variable before posting to Discord.
[ ] Share the **signup URL** in the Discord channel via the Copy button — confirm the URL resolves correctly when opened from Discord
    This should not be a seperated action, when posting the link should be added.
```

---

## 9. Stress / Edge Cases

> Goal: deliberately break things before alliance players do.

- [ ] **Typo in imported build:** Import a build with a clearly wrong weapon name (e.g. `Frost Staf`). Confirm it imports without error (no item metadata validation — typos are allowed by design). Note the typo for manual correction.
- [ ] **Wrong signup role:** Sign up a participant for a role that has no matching slot. Confirm this is handled gracefully in the planner (participant appears as unassigned/unmatched, not lost).
- [ ] **Missing slots:** Attach an operation to a composition that has 0 slots. Confirm the planner opens without crashing and shows a clear empty state.
- [ ] **Duplicate build names:** Import two builds with the same name. Confirm both exist in the library and can be independently assigned to slots.
- [ ] **Duplicate participant names:** Sign up two different accounts with similar display names. Confirm the planner correctly distinguishes them.
- [ ] **Rapid assignment changes:** Assign and unassign the same slot 4–5 times quickly. Confirm the planner remains consistent and the readiness snapshot reflects the final state.
- [ ] **Operation locked too early (recovery):** No UI unlock exists — confirm this is noted as a known limitation and document the workaround (direct DB edit or re-create operation) for the trial.

**Notes / Issues:**

```
(write here)
```

---

## 10. Final Go / No-Go Assessment

> Complete this section after finishing all sections above.

### Summary Table

| Area | Status | Notes |
|---|---|---|
| Environment | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Build Import | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Composition Workflow | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Operation Workflow | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Signup (Non-member) | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Planner | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Lock / Finalization | ⬜ Pass / ⬜ Fail / ⬜ Partial | |
| Discord | ⬜ Pass / ⬜ Fail / ⬜ Partial / ⬜ Skipped | |
| Edge Cases | ⬜ Pass / ⬜ Fail / ⬜ Partial | |

---

### Major Blockers

> Items that would prevent live alliance usage entirely.

- [ ] *(none found — or list here)*

---

### Minor Annoyances

> Friction points worth logging but not blocking.

- [ ] *(none found — or list here)*

---

### Acceptable Risks

> Known limitations that the alliance should be briefed on before the trial.

- [ ] No UI unlock — a prematurely locked roster requires a direct DB edit or operation re-creation.
- [ ] Build typos from CSV import are silently accepted — officers should proof builds before the CTA.
- [ ] *(add others here)*

---

### Ready for Alliance Usage?

- [ ] **YES** — all critical workflows passed; no major blockers found.
- [ ] **YES with caveats** — see acceptable risks above; brief officers before usage.
- [ ] **NO** — one or more major blockers must be resolved first.

**Officer briefing notes for the trial:**

```
(write pre-trial notes for your officers here, e.g. known quirks, workarounds, what to avoid)
```

---

## Blockers Found

> Add any item here the moment it blocks a subsequent step.

| # | Section | Description | Severity | Resolved? |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

---

## Post-Trial Observations

> Fill in after the live trial weekend. Use this to inform the next development cycle.

**What worked well:**

```
(write here)
```

**What caused friction:**

```
(write here)
```

**Surprising failures:**

```
(write here)
```

**Features missing that players asked for:**

```
(write here)
```

**Priority fixes before next trial:**

```
(write here)
```
