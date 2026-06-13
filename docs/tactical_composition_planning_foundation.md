# IronkeepV2 — Tactical Composition Planning Foundation

## Current Status

**All 8 phases shipped.**

| Phase | Status | Summary |
|---|---|---|
| Phase 1 — Tactical Planning Workflow Foundation | ✅ Shipped | Composition-first language, navigation, prominent CTAs |
| Phase 2 — Slot Card System | ✅ Shipped | Party grids replace data tables; state-based border accents |
| Phase 3 — Visual Equipment Cognition | ✅ Shipped | Role identity system, weapon-first build representation |
| Phase 4 — Inline Build Workflow | ✅ Shipped | Inline build-edit disclosure; `POST /slots/{id}/build` route |
| Phase 5 — Tactical Composition Readability | ✅ Shipped | Role tallies, gap badges, comp overview strip, continuation hints |
| Phase 6 — Compositions as Tactical Asset Library | ✅ Shipped | Role mix + active-ops columns, name search, reuse framing |
| Phase 7 — Tactical Composition Detail Surface | ✅ Shipped | New detail page: party preview, health signals, continuation flow |
| Phase 8 — Frontend Technical Discipline | ✅ Shipped | `app/tactical.py` module; Jinja logic removed; 34 new unit tests |

> **Phase 7 was reinterpreted on implementation.** The original scope ("Responsive Tactical UX") covered tablet/mobile layout improvements and keyboard efficiency. The delivered Phase 7 focused instead on **tactical composition visibility** — creating a dedicated composition detail page that shows the projected party formation, role distribution, health signals, and links to active operations. Tablet/mobile layout work and keyboard shortcuts are deferred to Phase 8 or a future pass.

> **Phase 3 was reinterpreted on implementation.** The original scope ("Visual Equipment Selection") required CDN item icons and an icon-grid selection surface. The delivered Phase 3 focused instead on **visual equipment cognition** — role family colour coding, weapon-first build representation, and compact density improvements — without external icon dependencies. Full icon-grid item selection is deferred to a future slice once a local icon cache strategy is defined.

> **Phase 4 was scoped down on implementation.** The original scope ("Inline Build Creation") assumed a standalone build library entity. Since no separate build library exists yet, Phase 4 delivered **inline slot build editing** — officers can update `build_name` and `weapon_name` on an existing operation slot without leaving the planner, via a compact `<details>` disclosure in the slot card footer. Full quick-create (name a new build and have it appear in a library) is deferred until the build library surface is established.

> **Phase 6 was reinterpreted on implementation.** No standalone "Build Library" page or `builds` table exists in IronkeepV2. The compositions surface IS the tactical asset library. Phase 6 therefore repositioned the **Compositions page** as a reusable tactical asset store — adding role-mix tallies per composition, active-operation usage counts, name search, and updated framing copy. Concepts like private/shared/restricted build visibility, build versioning, and import/export remain deferred until a standalone build entity surface is introduced.

Read this document before modifying the composition builder, planner, build library, slot assignment system, or equipment selection workflows. It is the authoritative design reference for the tactical planning surface.

---

## Long-Term Vision

IronkeepV2 currently manages builds, compositions, and operations through functional CRUD forms. Officers can create builds, attach them to compositions, and assign roster slots — but the workflow is fragmented. Build creation lives in the library. Composition editing lives in the planner. Equipment management lives deep inside builds. Nothing feels connected.

The long-term vision is a **unified tactical planning surface** where an officer can:

1. Open a composition.
2. See every party slot with role, build, and equipment represented visually at a glance.
3. Fill missing slots by selecting or creating builds inline — without leaving the planner.
4. Identify readiness gaps instantly through visual hierarchy and status signals.
5. Commit the composition to an operation and lock it — all within a single coherent workflow.

The tactical planner should feel like **operational planning software**, not a form-heavy admin panel. Officers in Albion Online plan under time pressure. Every extra click, every detour to a separate page, and every wall of unstructured text adds friction that erodes confidence in the tool.

The guiding ambition: **IronkeepV2 should feel meaningfully more capable and tactically focused than IronkeepV1 — without sacrificing the operational speed that makes it usable under real guild conditions.**

---

## Core UX Principles

### Composition-First Workflow
The composition builder is the primary planning surface, not the build library. Officers start from a composition and pull builds in — not the other way around. The build library exists to support the planner, not to lead it.

### Tactical Readability
Every layout decision must answer: *can an officer read this comp at a glance?* Role distribution, slot fill status, build names, and readiness signals must be immediately visible without parsing a table row by row.

### Visual Loadout Planning
Equipment should be represented visually — icons, slot groupings, tier indicators — not as text-only lists. Officers recognise loadouts by pattern, not by reading item names character by character.

### Fast Officer Workflow
The most common actions must require the fewest steps. Assigning a known build to a slot should be two actions: click slot → select build. Creating a new build for a slot should not require navigating away from the composition.

### Operational Scan Speed
The planner layout must be scannable within 3–5 seconds. An officer should be able to assess a full 20-man comp — missing roles, fill rate, build coverage — without scrolling or drilling down.

### Low-Friction Editing
Editing an existing slot assignment, swapping a build, or adjusting a note should feel lightweight. No full-page reloads for single-field changes. No confirmation dialogs for non-destructive edits.

### Visual Immediacy
The first render of the planner must feel tactically useful. No loading spinners covering the composition. No empty states on every card while data loads. The full composition structure renders from the server on first paint.

### Icon-First Interaction
Equipment items, role archetypes, and build types should be represented by icons wherever possible. Text labels are secondary confirmation, not the primary recognition signal. This is especially critical for equipment selection where officers scan hundreds of items.

### Slot-Focused Orchestration
A slot is the atomic unit of composition planning. Every planning action — assign, unassign, swap, validate — operates at the slot level. Party groupings and role categories are organisational, not structural.

### Progressive Complexity
Simple slot assignments and build selections must be fast and frictionless. Advanced editing — notes, priorities, swap definitions, build versioning — should be accessible but never blocking the primary flow.

### Preserve Reusable Build Assets
Builds are first-class reusable entities. A build assigned to a slot is a reference, not a copy. When a build is updated in the library, the update propagates everywhere it is used. This is a core architectural invariant.

### Preserve Maintainability
The planner system must remain understandable, testable, and modifiable by a solo developer. Every feature added to the planner must justify its complexity cost. Visual polish is not a substitute for operational clarity.

### Avoid Spreadsheet Feeling
Tables of text with "Edit" buttons in every row are not acceptable for a composition planning surface. Tactical planners must feel spatial and visual, even within a server-rendered HTML architecture.

### Avoid CRUD-Heavy Interaction
Forms for each slot, modals for each build, and separate pages for each sub-action are signs of a failing UX model. The planner must feel continuous and immediate, not like navigating a relational database.

---

## Architecture Constraints

These constraints are non-negotiable. Every implementation decision must preserve them.

### Domain Model Boundaries
- **Composition** — the tactical plan; contains an ordered list of Slots grouped by party.
- **Slot** — one assignment position within a Composition; references a Build (optional) and carries metadata (role, notes, priority, status).
- **Build** — a reusable equipment loadout; exists independently of any Composition or Slot. A Build can be referenced by many Slots across many Compositions.
- **Operation** — the scheduled event; references a Composition as its plan. The Operation is not a planning surface.

```
Operation
  └── references Composition
        └── contains Slots (ordered, grouped by party)
              └── each Slot references a Build (nullable)
                    └── Build contains Equipment + Swaps + Notes
```

### Storage Rules
- [ ] Slot assignment state is stored in the `slots` relation — not inside a monolithic JSON blob on the composition row
- [ ] Build equipment is stored in the `build_equipment` relation — not as a serialised equipment array
- [ ] Swap definitions live in the `build_swaps` relation — not as inline JSON
- [ ] All schema changes must be additive — no destructive migrations

### Code Boundary Rules
- [ ] All business logic (slot assignment, validation, readiness calculation) lives in `use_cases.py`
- [ ] All data retrieval and persistence lives in `repositories.py`
- [ ] Route handlers in `routes.py` orchestrate use cases and render templates — no business logic
- [ ] Domain entities and validation rules live in `domain.py`
- [ ] Templates contain no business logic — only conditional rendering based on passed context

### Frontend Constraints
- [ ] No SPA architecture — all state rendered server-side on initial load
- [ ] No React, Vue, Alpine, or HTMX required for core planner functionality
- [ ] JavaScript permitted for: progressive enhancement, icon preloading, inline form submission without full-page reload
- [ ] All planner actions must degrade gracefully to a full-page reload if JavaScript is absent
- [ ] No build-step frontend toolchain (Vite, webpack, esbuild) required for the planner

### Testability Rules
- [ ] Every use case has at least one unit test covering the happy path and one covering a failure mode
- [ ] Every HTTP route has at least one integration test asserting correct HTML structure
- [ ] Template changes must not break existing test assertions on text anchors

---

## Phase 1 — Tactical Planning Workflow Foundation ✅ Shipped

This phase establishes the planning philosophy and workflow architecture before any UI changes are made. It is primarily a design, documentation, and structural work phase — not a visual overhaul.

### Composition-First Workflow Definition

- [x] Define the official composition planning workflow — defined through Phase 1 template changes; the five-step composition → planner flow is reflected in all updated templates
- [x] Document where the "start planning" entry point lives — prominent "Tactical Planner →" CTA added to `operation_detail.html` when slots exist; "Compositions →" link in planner action bar
- [x] Define the relationship between the composition builder, the operation planner, and the roster assignment surface — captured in navigation structure and page language across all three surfaces
- [ ] Audit and document the current state of the composition builder route, template, and use cases — informal audit done during implementation; no separate written document produced

### Tactical Planning Philosophy

- [x] Define what "tactical readability" means for IronkeepV2 — established as the guiding standard for Phase 2–4 visual work; role visibility, scan speed, and operational density are the accepted criteria
- [x] Document why the current planner does not meet this standard — addressed through the Phase 1 language overhaul and the Phase 2–4 implementation rationale
- [x] List the minimum acceptable improvements — slot cards (Phase 2), role identity (Phase 3), and inline build editing (Phase 4) defined as the minimum bar

### Workflow Fragmentation Reduction

- [x] Identify which workflow breaks can be addressed without a full planner rewrite — Phase 4 inline build edit, Phase 1 CTA improvements, Phase 3 weapon-first display address the most common breaks
- [ ] Formally audit the current number of page navigations required for each planning task — not formally documented; addressed implicitly through Phase 4
- [ ] Define explicit target navigation counts (target: ≤ 2 page transitions) — not yet defined as a tracked metric

### Inline Build Selection Strategy

- [x] Define how an officer selects an existing build for a slot — Phase 4 "Edit build" disclosure provides inline `build_name` + `weapon_name` update within the slot card footer
- [x] Define the empty-selection state — "No build" indicator (`.slot-card__weapon--empty`) added in Phase 4
- [ ] Define build search by name / role archetype / weapon type — deferred; requires a standalone build library surface
- [ ] Define what build metadata is visible during selection — partially addressed by weapon-first display in slot cards

### Inline Build Creation Strategy

- [x] Define the boundary between quick-update (planner-surface) and advanced editing — Phase 4 established: `build_name` + `weapon_name` inline in planner; full equipment editing deferred to a future build library page
- [x] Ensure quick-update preserves the reusable-build invariant — the Phase 4 route updates `operation_slots` only, not any shared build entity; reusable build architecture is preserved
- [ ] Full quick-create from the planner (name + weapon → new library build) — deferred until a standalone build library surface exists

### Slot Orchestration Principles

- [x] Define slot ordering: within a party, slots are ordered by `slot_index` — implemented via `ORDER BY party_number, slot_index` in slot queries
- [x] Define party grouping: cosmetic, not structural — implemented (parties are visual groups in the planner, no structural constraint on the operation)
- [x] Define slot status vocabulary — `slot-card--assigned`, `slot-card--open-core`, `slot-card--open`, `slot-card--empty` states implemented in Phase 2
- [ ] Formally define the relationship between comp slot status and operation readiness state — not yet formally defined; readiness snapshot handles this partially

### Party-Group Planning UX

- [x] Define visual party grouping — each party renders as a named `<section class="card party-panel">` with header and slot grid
- [x] Define party-level summary — fill count (`N/M`) displayed in party panel header with colour-coded fill class
- [ ] Define inter-party actions (move slot between parties) — deferred to Phase 5+
- [ ] Define the empty party state — not yet handled; parties with no slots render as empty panels

---

## Phase 2 — Slot Card System ✅ Shipped

The slot card replaces the current table-row model for composition slots. It is the core visual primitive of the tactical planner.

**Shipped primitives:**

| Class | Purpose |
|---|---|
| `.slot-card-grid` | Auto-fill responsive grid inside each party panel (`minmax(140px, 1fr)`) |
| `.slot-card` | Individual slot card with left-border state accent |
| `.slot-card--assigned` | Green left border — player assigned |
| `.slot-card--open-core` | Orange left border — core slot, no player |
| `.slot-card--open` | Accent-blue left border — open, candidates available |
| `.slot-card--empty` | Default border — no signups yet |
| `.slot-card__header` | Role label + slot index strip |
| `.slot-card__body` | Build/weapon name + player state |
| `.slot-card__footer` | Player assignment actions + build edit |
| `.slot-card__status` | Read-only status text for non-mutable states |
| `.party-panel` | Named party `<section>` card with fill count header |

### Replace Table-Heavy Comp Rows

- [x] Audit the current slot representation in the planner template
- [x] Define why the table-row model fails tactical readability — addressed: dense uniform rows provide no role/state visual hierarchy
- [x] Define the migration path — `<div class="slot-card-grid">` replaces `<div class="table-wrap"><table>` inside each party panel without changing the underlying data model

### Reusable Slot Card Component

- [x] Define slot card zones: Header (role + index), Body (weapon/build + player), Footer (actions) — implemented
- [x] Define slot card states: `--assigned`, `--open-core`, `--open`, `--empty` — implemented with left-border accents
- [x] Define slot card size: compact enough for 5 slots per party row at ~720px content width — achieved at `minmax(140px, 1fr)`
- [ ] Extract as a reusable Jinja2 include `_slot_card.html` — currently inlined in `operation_planner.html`; extraction deferred to Phase 8

### Compact Tactical Layout

- [x] Define the party grid layout — `auto-fill, minmax(140px, 1fr)`; gap `--space-2`
- [x] Define column behaviour — auto-fill handles ≥ 5 columns on desktop; responsive overrides at 768px and 480px
- [x] Ensure the full 20-man comp (4 parties × 5 slots) is scannable at a standard viewport — one party per horizontal row at ~720px right-column width
- [ ] `--space-3` gap between parties — using `--space-2` within grid; party separation handled by `.card` margin

### Role-Based Hierarchy

- [x] Define role archetypes: Tank, Healer, Support, DPS, Ranged + Default — defined in Phase 3
- [x] Define role colour tokens in `:root` — `--role-tank`, `--role-healer`, `--role-support`, `--role-dps`, `--role-ranged` added in Phase 3
- [x] Ensure role is the most immediately readable datum — role label in `slot-card__header` with role-family colour; header divider tinted to match
- [ ] Role icon assets (Albion Online icons or SVG set) — deferred; using text + colour only

### Slot-Level Actions

- [x] Define secondary slot actions: Remove (assigned), Quick assign + Manual assign (open with candidates), Edit build — all implemented
- [x] Define destructive action: "Remove" uses `btn-danger` but is not the primary visible CTA
- [ ] Primary slot action: click unassigned card to open inline build selection — not yet; build selection opens via `<details>` disclosure, not card click
- [ ] Keyboard accessibility for all slot actions — partial; form buttons are keyboard-focusable but no explicit tab-order optimisation

### Slot Status Indicators

- [x] Define visual status signals per state — left-border accent colour is the primary state signal
- [x] Define the difference between "no build assigned" vs "no player assigned" — `slot-card__weapon--empty` shows "No build"; `slot-card__player--empty` shows "Unassigned"
- [ ] Status badge in bottom-left corner — using left-border accent instead of a discrete badge

### Responsive Slot Layout

- [x] Define breakpoint behaviour — `minmax(140px)` desktop; `minmax(120px)` at 768px; `repeat(2, 1fr)` at 480px
- [x] Ensure cards do not overflow their container at any breakpoint — `overflow: hidden; text-overflow: ellipsis` on all text within cards
- [x] Ensure role label and build name remain legible at minimum card size — single-line ellipsis prevents height inflation

### Quick-Edit Workflow

- [x] Define what "quick edit" means for a slot card — update `build_name` + `weapon_name` inline via `<details class="slot-build-edit">` in the footer
- [x] Define the inline edit surface — compact `<details>` disclosure following the same pattern as "Manual assign"
- [x] Define what requires a full-page edit — full equipment management, build notes, swaps: deferred to a future build library page

---

## Phase 3 — Visual Equipment Cognition ✅ Shipped

> **Implementation note:** The original Phase 3 scope ("Visual Equipment Selection") required CDN-sourced Albion Online item icons and an icon-grid selection surface. This was deferred because no local icon cache strategy exists yet. Phase 3 was implemented as **Visual Equipment Cognition** instead — focusing on role identity colour coding, weapon-first build representation, and compact slot density improvements. These changes deliver the tactical readability goals without external asset dependencies. Full icon-grid item selection is the primary deferred scope.

**Shipped in Phase 3:**

| Addition | Location |
|---|---|
| `--role-tank/healer/support/dps/ranged` CSS custom properties | `:root` block in `base.html` |
| Role-family mapping (`data-role` attribute via Jinja) | `operation_planner.html` slot loop |
| Role label colour per family (`.slot-card[data-role="X"] .slot-card__role`) | `base.html` |
| Header divider tint per family (`.slot-card[data-role="X"] .slot-card__header`) | `base.html` |
| `slot.weapon_name` as primary build identifier; `slot.build_name` as secondary | `operation_planner.html` |
| `.slot-card__weapon` — primary build identifier CSS | `base.html` |
| Compact density pass (padding, font sizes, `text-overflow: ellipsis`) | `base.html` |
| Grid column minimum reduced 170 → 140 px | `base.html` |

### Role Identity System

- [x] Define role archetypes: Tank, Healer, Support, DPS, Ranged, Default — mapped from `slot.role | lower` via Jinja substring matching
- [x] Define role colour tokens in `:root` — five family tokens with muted dark-theme hues
- [x] Apply role colour to slot card role label (`slot-card__role`) — colour is the primary role identity signal
- [x] Apply role colour to slot card header divider (`slot-card__header` `border-bottom-color`) — secondary reinforcement of role family without requiring icons
- [x] Preserve Phase 2 state-based left-border accent — assignment state (green/orange/accent/plain) and role identity (header colour) are independently visible
- [ ] Role icon assets (Albion Online icons or SVG) — deferred; text + colour considered sufficient for Phase 3

### Compact Build Representation

- [x] Show `weapon_name` as primary build identifier when set; fall back to `build_name` — `slot.weapon_name or slot.build_name` logic in body template
- [x] Show `build_name` as a secondary, smaller, muted label below when it differs from `weapon_name` — `.slot-card__build` secondary class
- [x] Both identifiers use `text-overflow: ellipsis; white-space: nowrap` — single-line truncation prevents card height inflation
- [x] Title attribute provides full text on hover for truncated names

### Planner Density Pass

- [x] Header padding reduced to `0.15rem var(--space-2)`
- [x] Body padding reduced to `var(--space-1) var(--space-2)`; `min-height` reduced to `1.8rem`
- [x] Footer padding reduced to `var(--space-1) var(--space-2)`
- [x] Font sizes tightened: role label `0.7rem`, weapon `0.8rem`, build `0.7rem`, player `0.8rem`, index `0.68rem`
- [x] Grid gap reduced from `--space-3` to `--space-2`

### Deferred — Full Icon-Grid Equipment Selection

- [ ] Icon-grid selection surface (items as icon tiles, name on hover) — requires local asset cache
- [ ] Slot-filtered equipment lists (Head, Chest, MainHand, etc.) — requires equipment slot schema
- [ ] Tier and enchantment visual badges on item icons — requires structured item data
- [ ] CDN icon delivery strategy / local static cache — requires Slice 37 API cache integration
- [ ] Text search and category filter within item grid — requires icon-grid surface to exist first
- [ ] Favourite/recent items per slot type — deferred

---

## Phase 4 — Inline Build Workflow ✅ Shipped

> **Implementation note:** The original Phase 4 scope ("Inline Build Creation") assumed a standalone build library with a UI for creating named build entities from the planner. Since no separate build library surface exists yet, Phase 4 was scoped to **inline slot build editing** — officers can update `build_name` and `weapon_name` on an existing operation slot without leaving the planner, via a compact `<details>` disclosure in the slot card footer. A no-build indicator was also added. Full quick-create (spawn a new reusable build entity from the planner) is deferred.

**Shipped in Phase 4:**

| Addition | Location |
|---|---|
| `repositories.update_operation_slot_build()` — UPDATE build_name + weapon_name | `repositories.py` |
| `POST /workspaces/{slug}/operations/{op_id}/slots/{slot_id}/build` route | `routes.py` |
| `<details class="slot-build-edit">` disclosure in slot card footer (officers only) | `operation_planner.html` |
| `.slot-build-edit` CSS (mirrors `.slot-manual-assign` pattern) | `base.html` |
| `.slot-card__weapon--empty` indicator — "No build" shown when `build_name` is null | `base.html` + `operation_planner.html` |
| Unified single-`<div>` footer — player actions + build edit consolidated | `operation_planner.html` |

### Inline Slot Build Editor

- [x] Define the inline edit entry point — `<details class="slot-build-edit">` disclosure in the slot card footer, collapsed by default
- [x] Gate build edit on `can_mutate and can_mutate_assignments` — same status-based permission as player assignment
- [x] Fields: `build_name` (required text input) + `weapon_name` (optional text input) — pre-filled with current values
- [x] POST to `POST /slots/{slot_id}/build` — saves `build_name` and `weapon_name` to `operation_slots`; redirects to planner
- [x] Error handling: empty `build_name` rejected with a flash error; redirected back to planner
- [x] Reusable-build invariant preserved — this route updates `operation_slots` only; no shared build entity is touched

### No-Build Indicator

- [x] When `slot.weapon_name` and `slot.build_name` are both null/empty, show "No build" in `.slot-card__weapon--empty` (muted italic)
- [x] Visual differentiation from "Unassigned" player state — "No build" is in the body's weapon/build line; "Unassigned" is on the player line

### Deferred — Full Quick-Create Build Flow

- [ ] Create a new named build entity from the planner — requires a standalone build library surface
- [ ] Minimum required fields for quick-create: build name + primary weapon — requires a `builds` table with a library view
- [ ] After quick-create: slot is assigned to the new build; "Add equipment →" link leads to build library — deferred
- [ ] Quick-create fails gracefully on name conflict with inline error — deferred
- [ ] All quick-created builds visible and editable in the build library — deferred

### Deferred — Save Feedback

- [ ] Brief inline "Saved" or "Updated" confirmation on build edit — currently a flash message on the planner page; no inline signal

### Deferred — Slot Notes and Priority

- [ ] Slot notes (short text annotation per slot, e.g. "flanker", "solo engage") — requires a `notes` column on `operation_slots` (schema migration)
- [ ] Slot priority (numeric call priority within a party) — stored as `priority` field but not yet editable from the planner card
- [ ] Inline note click-to-edit on slot card — deferred until notes column exists

### Deferred — Inline Validation Visibility

- [ ] Slot validation errors (missing required equipment, tier below operation requirement) — deferred until equipment schema exists
- [ ] Warning indicator on slot card for validation errors — deferred
- [ ] Readiness contribution of validation errors — deferred

---

## Phase 5 — Tactical Composition Readability ✅ Shipped

This phase improves the planner's ability to communicate the tactical state of a composition at a glance.

**Shipped in Phase 5:**

| Addition | Location |
|---|---|
| `_role_family_py(role)` helper — mirrors Jinja role-family logic, used server-side | `routes.py` |
| `_derive_tactical_summaries(parties, assigned_map)` — per-party + comp-level tallies | `routes.py` |
| `party_summaries` + `comp_summary` injected into `get_planner` context | `routes.py` |
| `.comp-overview` — full-comp role tally + continuation hint strip above parties | `base.html` |
| `.party-summary` — compact role tally + gap badges strip between header and grid | `base.html` |
| `.role-tally` / `.role-tally__item[data-role]` — coloured T/H/D/S/R count tokens | `base.html` |
| `.role-tally__item--zero` — dimmed (opacity 0.35) when role count is 0 | `base.html` |
| `.tac-gap-badge--critical` — red: "⚠ No healer" / "⚠ No tank" | `base.html` |
| `.tac-gap-badge--warn` — orange: "N no builds" | `base.html` |
| Comp overview strip rendered above party panels when slots exist | `operation_planner.html` |
| Per-party summary strip rendered between party header and slot grid | `operation_planner.html` |

### Improve Party Scanning

- [x] Define party-level summary strip: compact row between party header and slot card grid — shows role tally + tactical gap badges
- [x] Ensure party summary is visible without scrolling into the slot cards — it sits directly below the party `h3`
- [x] Define the visual separation between parties — `<section class="card party-panel">` with margin, plus party summary `border-bottom`
- [ ] Define party status badge: `ready` / `forming` / `incomplete` — deferred; gap badges already communicate this implicitly

### Improve Role Distribution Visibility

- [x] Define the role tally: compact T:N H:N D:N S:N R:N tokens, both per-party and full-comp
- [x] Render full-comp role distribution above all parties — `.comp-overview` strip
- [x] Define colour coding — each token uses its role colour token from `:root`; zeros are dimmed
- [ ] Dynamic update without full-page reload — deferred; server-rendered on every planner render

### Improve Missing-Role Visibility

- [x] Define missing-role detection: `healer` count == 0 or `tank` count == 0 per party → `("critical", "No healer")` / `("critical", "No tank")` gaps
- [x] Define missing-role signalling: red `⚠ NO HEALER` / `⚠ NO TANK` badge tokens on the affected party's summary strip
- [x] Zero-count role tokens in the tally are dimmed to reinforce the gap visually
- [ ] Define expected role sets per operation type (ZvZ/GvG/HG) — deferred; current detection is role-family based, not operation-type gated
- [ ] Missing-role signals contributing to readiness state — deferred; readiness snapshot is recalculated separately

### Improve Tactical Readability

- [x] Composition overview strip (`.comp-overview`) shows full-comp role distribution + continuation hint — always visible above all party panels
- [x] Role tally uses role colour tokens — T is blue, H is green, D is orange, S is teal, R is purple
- [ ] Sticky "tactical overview" at composition header level — deferred; comp-overview is inside the scrollable right column

### Improve Readiness Visibility Inside Planner

- [x] Continuation hint communicates current state: "N slots missing builds", "All slots built · N still unassigned", "All slots built and assigned"
- [x] Hint colour-coded: `--warn` (orange) for incomplete, `--ok` (green) for complete
- [ ] Readiness recalculation on every slot action — deferred; requires explicit "Recalculate" button
- [ ] Expandable readiness detail breakdown — deferred; existing readiness sticky card already provides this

### Deferred — Comp Comparison and Post-Completion CTA

- [ ] Side-by-side composition comparison with diff highlighting — deferred
- [ ] "Attach to operation" CTA when all slots built and assigned — deferred to Phase 7+
- [ ] Planner → operation handoff as a single action — deferred

---

## Phase 6 — Compositions as Tactical Asset Library ✅ Shipped

> **Implementation note:** No standalone "Build Library" page or `builds` table exists in IronkeepV2. The compositions surface IS the reusable tactical asset library. Phase 6 repositioned the Compositions page as a proper tactical asset store and added contextual reuse data. Concepts requiring a standalone build entity (private/shared/restricted visibility, versioning, import/export) are deferred until a `builds` table is introduced.

**Shipped in Phase 6:**

| Addition | Location |
|---|---|
| `get_all_composition_slot_roles_for_workspace()` — batch query for role tallies | `repositories.py` |
| `count_active_operations_per_composition()` — active op count per composition | `repositories.py` |
| `get_compositions_list` updated — derives role tallies + op counts, supports `?q=` search | `routes.py` |
| Name search (`?q=`) — server-side filter, preserves `show_deleted` state | `compositions_list.html` |
| **Role mix column** — T:N H:N D:N S:N R:N tally per composition using Phase 5 `.role-tally` CSS | `compositions_list.html` |
| **Active ops column** — non-archived operation count per composition, linked to dashboard | `compositions_list.html` |
| Reuse framing copy — "Compositions are reusable. Update build assignments in the Tactical Planner." | `compositions_list.html` |
| Retire button downgraded from `btn-danger` to `btn-muted` — secondary action, not primary CTA | `compositions_list.html` |
| Build name field hint — clarifies that build_name defines tactical slot identity, editable from planner | `compositions_new.html` |

### Reposition Build Library (as Compositions Page)

- [x] No standalone "Build Library" nav item exists — compositions are the correct primary surface
- [x] "Compositions" is already the second item in workspace nav after Dashboard — appropriately positioned
- [x] Compositions page framing copy updated to describe compositions as reusable tactical planning assets
- [x] Retire action downgraded to a secondary `btn-muted` — not the dominant CTA
- [ ] Quick-access recent compositions section in the planner sidebar — deferred; full sidebar redesign needed

### Improve Search and Filtering

- [x] Name search via `?q=` — server-side, case-insensitive substring match, query parameter persisted
- [x] Clear search affordance — "✕ Clear" button when `q` is active
- [x] Show/hide retired toggle preserved and compatible with search state
- [ ] Role archetype filter (`?role=tank`) — deferred; role tally column already surfaces this visually
- [ ] Sort options (most recently used, alphabetical) — deferred; currently sorted by name

### Build Usage / Reuse Context

- [x] Role mix column shows T:N H:N D:N S:N R:N per composition — scanned at a glance without opening the composition
- [x] Active ops column shows how many non-archived operations are using each composition — reuse visibility
- [x] Compositions with zero active ops show "—" — distinguish planned vs. actively deployed assets
- [ ] Operations list on composition hover or detail — deferred (requires composition detail page)

### Preserve Operational Simplicity

- [x] Compositions page never becomes a required workflow step — tactical planning still starts from the planner or operation detail
- [x] Build assignments remain on slots, not embedded in compositions — reusable-build invariant preserved
- [ ] Quick-create build from the planner (name → library build) — deferred until `builds` table exists

### Deferred — Standalone Build Entity Features

- [ ] `builds` table with library CRUD — not yet implemented
- [ ] Private / shared / restricted build visibility — requires `builds` table
- [ ] Build versioning (`version_note`, `valid_from`, `valid_until`) — deferred
- [ ] Build import / export (JSON format) — deferred
- [ ] "Use in composition" quick-attach CTA from compositions list — deferred

---

## Phase 7 — Tactical Composition Detail Surface ✅ Shipped

> **Implementation note:** The original Phase 7 scope ("Responsive Tactical UX") covered tablet/mobile layout and keyboard efficiency. The delivered Phase 7 built the **composition detail page** — a tactical formation preview surface that lets officers understand a composition's party structure, role distribution, and health signals without opening the Tactical Planner. Responsive/tablet improvements are deferred.

**Shipped in Phase 7:**

| Addition | Location |
|---|---|
| `get_operations_using_composition()` — non-archived ops using a composition, ordered by date | `repositories.py` |
| `GET /workspaces/{slug}/compositions/{comp_id}` — new detail route | `routes.py` |
| `compositions_detail.html` — full tactical formation preview page | new template |
| Composition names in the list now link to the detail page | `compositions_list.html` |
| Composition name in the planner page-meta now links back to detail page | `operation_planner.html` |

### Tactical Composition Detail Surface

- [x] Create `GET /workspaces/{slug}/compositions/{comp_id}` route — registered after `/compositions/new` to preserve path matching
- [x] Page header: composition name, "N slots · N parties · N/M built" badge, Retire button (secondary `btn-muted`)
- [x] Composition description shown as muted sub-heading when present
- [x] `_derive_tactical_summaries` reused with `assigned_map={}` — build coverage and gap detection work correctly on slot templates
- [x] Each slot template annotated with `role_family` in the route (same `_role_family_py` logic as planner)

### Party Layout Preview

- [x] Full-composition overview strip (`.comp-overview`) — reuses Phase 5 CSS: `T:N H:N D:N S:N R:N` tally + health hint
- [x] Per-party panels — same `.party-panel`, `.party-panel__header`, `.fill-count` CSS; fill count shows "N/M built" (build coverage, not player assignment)
- [x] Per-party summary strip (`.party-summary`) — role tally + gap badges, identical to the planner view
- [x] Slot card grid (`.slot-card-grid`) — reuses all Phase 2/3 slot card CSS; read-only (no footer/action buttons)

### Tactical Slot Readability

- [x] Slot card state repurposed for template context: `--assigned` (green) = build defined; `--open-core` (orange) = core slot, no build; `--empty` (plain) = no build
- [x] Role-family colour coding via `data-role` attribute — same CSS rules as the planner
- [x] Weapon-first build display: `weapon_name` as primary, `build_name` as secondary if different; "No build" italic placeholder when both empty
- [x] Core slot marker (●) shown in slot index

### Composition Health Visibility

- [x] "N/M built" badge in page header — green when all built, amber when partial
- [x] Comp-level health hint: "N slots missing builds", "All slots built"
- [x] Party-level gap badges: `⚠ NO HEALER` (red), `⚠ NO TANK` (red), `N no builds` (orange)
- [x] Zero-count role tokens dimmed in all tallies

### Composition → Operation Continuation Flow

- [x] Active operations section — table of non-archived operations using this composition with direct "Planner →" links per operation
- [x] "New Operation →" CTA in action bar — links to operation creation form
- [x] Composition name in the list now links to its detail page
- [x] Composition name in the planner page-meta now links back to the detail page

### Deferred — Original Phase 7 Responsive UX

- [ ] Tablet planner layout (sidebar collapse, ≤ 960px) — deferred to Phase 8
- [ ] Compact card mode at tablet breakpoint — deferred
- [ ] Touch-friendly editing (44×44px targets, tap-to-edit) — deferred
- [ ] Keyboard navigation order and shortcut candidates — deferred
- [ ] Phone review-only mode (≤ 480px) — deferred

### Deferred — Composition Detail Editing

- [ ] Inline slot editing from the detail page — read-only preview only in Phase 7
- [ ] Composition cloning — deferred
- [ ] Side-by-side composition comparison — deferred
- [ ] Pre-selecting this composition on the New Operation form — deferred

---

## Phase 8 — Frontend Technical Discipline

**✅ Shipped.** Phase 8 was reinterpreted from its original CSS/template-organisation scope to focus on **tactical logic consolidation and testability** — the highest-priority technical discipline work before future feature growth.

### Reinterpretation note

The original Phase 8 scope described CSS organisation, planner primitives, and layout utilities. On implementation, the more urgent discipline need was the tactical interpretation logic — `role_family()` and `derive_tactical_summaries()` existed as private route helpers (`_role_family_py`, `_derive_tactical_summaries`) in `routes.py`, and were independently duplicated as a Jinja if-chain in `operation_planner.html`. These were the highest drift/inconsistency risk as the planner surfaces grew. The CSS organisation work remains valuable and is documented for a future maintenance pass.

### Shipped in Phase 8

| What | Where | Detail |
|---|---|---|
| `app/tactical.py` (new module) | `app/tactical.py` | Canonical `role_family()`, `derive_tactical_summaries()`, `ROLE_FAMILIES` — pure Python, no DB/Jinja dependencies |
| Removed `_role_family_py()` | `app/routes.py` | Private helper deleted; all call sites updated to `tactical.role_family()` |
| Removed `_derive_tactical_summaries()` | `app/routes.py` | Private helper deleted; all call sites updated to `tactical.derive_tactical_summaries()` |
| Imported `tactical` module | `app/routes.py` | `from app import … tactical` added to import block |
| `track_assignments` parameter | `app/tactical.py` | `derive_tactical_summaries(…, track_assignments=False)` suppresses player-assignment hints in template/preview mode |
| Fixed composition detail hint | `app/routes.py` | `get_composition_detail` now passes `track_assignments=False` — hint correctly shows "All slots built" instead of "All slots built · N players still unassigned" |
| Removed Jinja role-family if-chain | `app/templates/operation_planner.html` | 14-line `{% if 'tank' in role_lower … %}` block replaced with single `data-role="{{ slot.role_family }}"` |
| Slot `role_family` precomputed in planner | `app/routes.py` — `get_planner` | `slot_dict = {**slot, "role_family": tactical.role_family(slot.get("role"))}` injected when building `parties` |
| `tests/test_tactical_logic.py` (new) | `tests/test_tactical_logic.py` | 34 unit tests: role classification, tally derivation, gap detection, template mode, edge cases |

### Validated tactical consistency

After Phase 8, the following tactical interpretation guarantees hold:

- **One canonical source**: `app/tactical.py` is the only place role-family classification and tally derivation logic lives.
- **No Jinja classification**: Templates receive pre-annotated `slot.role_family`; no template derives tactical meaning from raw role strings.
- **No route-specific logic**: The planner route and the composition detail route use the same `tactical.derive_tactical_summaries()` call — their summaries are structurally identical.
- **Context-aware hints**: `track_assignments=False` separates build-coverage hints (composition previews) from player-assignment hints (live planner). The composition detail page no longer incorrectly reports "N players still unassigned".

### Deferred to future work

The following original Phase 8 items remain useful but were not the blocking priority:

- CSS organisation: grouping all planner/composition CSS into a labelled block in `base.html` and preparing it for extraction into `static/planner.css`
- Planner primitive naming conventions: `.planner-grid`, `.party-group`, `.role-badge` formalisation
- Inline `style` attribute audit
- BEM sub-element completeness audit for `.slot-card`

These are low-risk maintenance items and can be addressed in a dedicated CSS cleanup pass before or alongside future planner feature work.

### Preserve Semantic HTML

- [ ] Define that each party group uses a `<section>` element with an `aria-label` matching the party name
- [ ] Define that the slot card grid uses a `<ul>` / `<li>` structure for accessible list semantics
- [ ] Define that all interactive slot elements are `<button>` or `<a>` — no `<div onClick>` patterns
- [ ] Ensure heading hierarchy is strict: `h2` for composition title, `h3` for party group title, `h4` for slot card labels

### Preserve Testability

- [ ] Define that every slot card must render a stable test anchor: the build name or "Unassigned" placeholder text
- [ ] Define that every party group must render its party label as a stable test anchor
- [ ] Ensure all planner template changes include a test regression check before merging
- [ ] Define that inline edit success/error states render stable assertable messages

---

## Explicit Non-Goals

- **Do not remove reusable builds.** Builds are first-class entities, not embedded composition data.
- **Do not tightly couple builds to compositions.** A build change must not require a composition update. Slots reference builds by ID.
- **Do not create giant modal workflows.** Modals for slot assignment, equipment selection, or build creation add friction and fail on mobile.
- **Do not introduce SPA complexity.** The planner is and will remain server-rendered Jinja2 with optional JavaScript enhancement.
- **Do not build drag-and-drop initially.** Drag-and-drop is a Phase N+ concern. It is listed in Future Extensions but is explicitly deferred until the non-drag UX is excellent.
- **Do not sacrifice maintainability for visual polish.** A solo developer must be able to understand, modify, and test the planner without a frontend engineering background.
- **Do not create spreadsheet-style planning UX.** Text tables with edit buttons in every row are not acceptable for tactical planning. The slot card system is the minimum acceptable improvement.
- **Do not overload the planning surface with every field at once.** Quick-create / quick-assign must be fast and minimal. Advanced editing is opt-in.
- **Do not treat the mobile phone as a first-class planning device.** Phones are acceptable for reviewing compositions. Full editing is a tablet-and-above concern.
- **Do not redesign unrelated operational systems** (roster assignment, payout ledger, attendance marking) as part of planner improvements.

---

## Success Criteria

- [ ] Officers can create a 20-slot composition with builds assigned in under 5 minutes from a blank state — without navigating to the build library.
- [ ] A new build can be created and assigned to a slot without leaving the planner page.
- [ ] The role distribution of a composition (tank count, healer count, DPS count, etc.) is readable at a glance from the composition overview without drilling into individual slots.
- [ ] Missing or unassigned slots are immediately visible — no scrolling required to identify gaps in a 20-man comp.
- [ ] Equipment for a slot is selected via an icon grid where items are recognisable by appearance, not only by name.
- [ ] The planner operates at full capability on a 1280×768px laptop viewport without horizontal scrolling.
- [ ] The planner is reviewable (not necessarily editable) on a tablet viewport (768px wide) without layout breakage.
- [ ] IronkeepV2 feels meaningfully more tactically capable than IronkeepV1 — the composition workflow is faster, more visual, and less form-heavy.
- [ ] The planner template structure is understandable and modifiable by a solo developer without specialised frontend knowledge.
- [ ] All planner changes are covered by at least one integration test asserting correct HTML structure and content.
- [ ] The composition builder uses zero SPA dependencies — no JavaScript framework required for core functionality.

---

## Future Extension Ideas

These are post-Phase-8 possibilities. They are documented here to ensure current architecture decisions do not accidentally foreclose them. None of these are committed scope.

- **Composition templates.** A pre-defined starting composition (e.g. "Standard 20-man ZvZ") that can be cloned and customised. Requires the ability to duplicate a full composition with all slot assignments.
- **Build recommendations.** For a given operation type and missing role, the system suggests builds from the library that have been used in similar operations. Requires usage tracking data.
- **Composition duplication.** Clone a full composition with all slot assignments to a new draft composition. Useful for iterating between tactical options before an operation.
- **Season meta presets.** Pre-loaded build sets for the current Albion Online meta season. Requires a community-data input mechanism or manual officer curation.
- **Alliance-level composition sharing.** Export/import compositions between guild workspaces in the same alliance. Requires a workspace-to-workspace data transfer API.
- **Planner analytics.** Which compositions were used in which operations. Which builds had the highest fill rates. Which roles were most frequently unassigned. Requires operational event enrichment.
- **Role heatmaps.** A visualisation of role distribution across all recent operations — helps officers identify chronic planning gaps (e.g. healer shortage across the last 8 ZvZs).
- **Drag-and-drop slot reordering.** Move slots between parties by dragging. This is a post-Phase-8 improvement once the card-based UX is stable.
- **Import / export workflows.** Import a composition from a JSON file (e.g. exported from another tool). Export a composition for external review or archiving.
- **Loadout comparison view.** Side-by-side view of two compositions or two builds — useful for meta-analysing options before an operation.

---

## Open Design Questions

These questions are unresolved and should be revisited before implementing the relevant phase.

- **How much inline editing is too much?** There is a tension between making the planner feel fast (inline everything) and keeping the surface readable (too many edit states degrade readability). The current proposal is: inline for slot assignment and notes; full-page for equipment editing. Is this the right boundary?

- **Should builds autosave or require explicit save?** Autosave is fast but can cause surprising state for officers who are iterating. Explicit save is safer but adds a step. The current proposal is: slot assignments autosave; build content requires explicit save. Should there be a unified save model?

- **When should advanced build editing branch out of the planner?** The quick-create / advanced-edit split assumes officers are comfortable navigating between the planner and the build library. Is this acceptable, or should more of the build detail be accessible inline (even if it requires scrolling)?

- **Should visual equipment previews be lazy-loaded?** Loading all item icons for a composition on page load could cause a brief visual pop. Lazy-loading icons as slots are viewed reduces initial load time but introduces flicker. The current proposal is to preload icons for all assigned slots on initial load. Is this the right call?

- **Should mobile planner editing be intentionally limited?** The proposal is that phones are review-only devices for the planner. Does this create an unacceptable gap for officers who rely on mobile? Or is mobile editing genuinely too complex to support well?

- **What planner actions deserve keyboard shortcuts?** Keyboard efficiency matters for power users. Candidates: `N` = new build (when slot focused), `S` = save, `Esc` = cancel inline edit, `Tab` = next slot. What is the minimum viable shortcut set before shortcuts become noise?

- **How should comp cloning and versioning behave?** If an officer clones a composition and then edits the original, should the clone reflect those changes (reference semantics) or remain independent (copy semantics)? Copy semantics are simpler but create divergence. Reference semantics require a versioning model. What is acceptable for V1?
