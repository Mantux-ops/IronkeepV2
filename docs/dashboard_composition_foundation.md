# IronkeepV2 — Dashboard Composition Foundation

## Status

**Complete — all 7 phases shipped**

| Phase | Status | Slice |
|---|---|---|
| Phase 1 — Layout Foundations | ✅ Complete | Slice 48a |
| Phase 2 — Operational Summary Cards | ✅ Mostly complete (table→card grid deferred to Phase 4) | Slice 48b |
| Phase 3 — Information Hierarchy | ✅ Complete | Slice 48c |
| Phase 4 — Dashboard UX Improvements | ✅ Complete | Slice 48d |
| Phase 5 — Responsive Behavior | ✅ Complete | Slice 48e |
| Phase 6 — Operational Widgets | ✅ Mostly complete (recent activity widget shipped; other widgets deferred) | Slice 48f |
| Phase 7 — Consistency / Technical Discipline | ✅ Complete | Slice 48g |

This document defines the long-term operational UX direction for IronkeepV2 dashboards and information layouts. It is a structural and compositional roadmap — not a visual effects document.

Read this before restructuring any dashboard, workspace, or operation overview page.

---

## Goal

Transform IronkeepV2 from a collection of functional admin tables into a cohesive operational platform where officers can scan, act, and understand the state of their guild in seconds — not minutes.

The goal is not visual decoration. The goal is **operational scanning speed** and **meaningful information density** built on top of stable, server-rendered, maintainable layout primitives.

Every dashboard decision must answer: *does this help an officer act faster on the right information?*

---

## Core Principles

- **Operational clarity first.** Layout decisions serve the user's job, not the developer's convenience. An officer opening the dashboard should immediately see what needs attention.
- **Dashboard over CRUD.** The workspace home page is a command center, not a table of records. Actions are prominent. Status is glanceable. Navigation is secondary.
- **High scan speed.** Officers are in a hurry before an operation. The most important signal (readiness state, pending actions, active operations) must be visible without scrolling.
- **Meaningful information density.** Surfaces should be dense enough to be useful without being cluttered. No padding-heavy empty cards. No walls of muted text with no hierarchy.
- **Restrained visual hierarchy.** There is one primary action per page section. Secondary information is visually subdued. Tertiary information is collapsed or absent until needed.
- **Reusable layout primitives.** New pages must be composable from a small set of documented layout components. One-off layout hacks for specific pages are not acceptable.
- **Responsive design without mobile clutter.** Mobile layouts stack and simplify gracefully. They do not add mobile-specific UI that diverges from the desktop structure.
- **Preserve server-rendered simplicity.** No client-side data fetching for dashboard content. No live-polling. No hydration. All state is rendered on first load and refreshed by the browser.
- **Additive and non-destructive.** Layout improvements are additive. Existing routes, templates, and Python logic are not redesigned unless there is a clear operational UX reason.
- **Test-friendly structure.** Semantic HTML, predictable class names, and stable text anchors are non-negotiable. Dashboard changes must not break existing test assertions.

---

## Phase 1 — Dashboard Layout Foundations

### Max-Width and Container Strategy

- [x] Audit all existing `max-width` usage across templates and consolidate to `--max-width` and `--max-width-wide` tokens
- [x] Define a third container width: `--max-width-narrow` (760px) for settings/form pages — added as `--max-width-narrow` token and `.page--narrow` class
- [x] Document when each container width is appropriate:
  - Narrow: account, settings, forms, diagnostics, home workspace list
  - Standard: dashboard, operation detail, ledger, timeline
  - Wide: planner, composition editor, large data tables
- [ ] Audit remaining page shells for inline `max-width` overrides — deferred to Phase 7 consistency audit

### Multi-Column Layout System

- [x] Define a `dashboard-grid` layout primitive: two-column (`1fr + 300px sidebar`) on wide screens, single-column below 960 px
- [x] Define a `sidebar-panel` primitive: flex-column container for stacked sidebar cards
- [x] Define a `three-col-metrics` primitive: `auto-fit, minmax(160px, 1fr)` responsive grid
- [x] Ensure all grid primitives collapse to single-column on mobile without layout breakage
- [x] Document grid primitive classes and their intended use cases (CSS comments in `base.html`)

### Spacing Rhythm

- [ ] Full audit of section spacing across all templates — deferred to Phase 7 consistency audit
- [x] Define section spacing standards:
  - Between major page sections: `--space-6` (32px) via `.dashboard-section`
  - Between cards within a section: `--space-4` (16px) via `.card` margin
  - Between items within a card: `--space-3` (12px) via `.card-body` padding
- [x] Applied consistent spacing to workspace dashboard
- [x] Define `.dashboard-section` utility that applies `--space-6` bottom margin

### Section Grouping

- [x] Define a standard for grouping related content into named sections with a visible section heading
- [x] Establish a `.section-header` pattern: `h2`/`h3` title + optional trailing action link in a flex row
- [x] Section headings use `h2` for page sections, `h3` for sidebar/card sub-sections

### Dashboard Container Standards

- [x] Define what constitutes a "dashboard page" vs a "settings page" vs a "detail page"
- [x] Dashboard pages use the standard `--max-width` container and `dashboard-grid`
- [x] Detail pages (operation, ledger, timeline) use standard container with vertical sections
- [x] Settings/form pages use `--max-width-narrow` — applied to `home.html`; remaining settings pages deferred to Phase 7

### Shipped primitives (`app/templates/base.html`)

| Class | Description |
|---|---|
| `.page--narrow` | 760 px max-width for focused/form pages |
| `.dashboard-grid` | Two-column grid with 300 px sidebar; collapses at 960 px |
| `.sidebar-panel` | Flex-column container for stacked sidebar cards |
| `.dashboard-section` | Section wrapper with `--space-6` bottom margin |
| `.section-header` | Title + optional trailing action in a flex row |
| `.three-col-metrics` | Responsive auto-fit metric tile row |
| `.metric-card` | Compact KPI tile with `__value`, `__label`, `__sub` |
| `.action-group` | Full-width stacked button list for sidebars |

> **Phase 7 note:** `.three-col-metrics` was removed in Phase 7 — it was defined in Phase 1 but never used in any template. `.summary-metrics` (Phase 2) is the canonical metric grid.

---

## Phase 2 — Operational Summary Cards

### Summary Metrics Strip

- [x] Add a `summary-metrics` row at the top of the workspace dashboard — always visible
- [x] **Active operations** metric card: count of draft/planning/locked operations, sub-text shows archived count
- [x] **Ready** metric card: `N / total` ratio with semantic left-border accent (green when all ready, amber when some not ready)
- [x] **Pending signups** metric card: total unassigned signup count across all operations, amber when non-zero
- [x] Metric cards use conditional `.metric-card--ok`, `--warning`, `--danger`, `--neutral` border accents based on actual values — no hardcoded colours

### Needs Attention Section (replaces pending-action cards)

- [x] Add a "Needs attention" card — **only rendered when there are actionable issues** (absent when all clear)
- [x] Shows a count badge in the card header (total number of attention items)
- [x] Per-operation attention items: any `planning`/`locked` operation with `not_ready` or `forming` readiness renders as a row with status badge, readiness state, unassigned signup count, and a "Planner" link (officer/owner)
- [x] Discord retry attention item: shown when `pending_retry_count > 0` (officer/owner only), links to Scheduler page
- [x] Payout ledger attention item: shown when `draft + approved` ledger entry count > 0 (officer/owner only)
- [x] Scheduler stale attention item: shown when scheduler has not run within the stale threshold (officer/owner only), links to Diagnostics
- [x] Attention rows use `.attention-item--warning` (amber) and `--danger` (red) severity variants

### Active Operations Cards

- [ ] Replace the operations list table with an operations card grid — **deferred to Phase 4** (table retained; card grid is a larger UX change)
- [x] Operations table retains pending-action signal via "Pending" column (unassigned signup count)
- [x] Empty state is clear with `.empty-state` text
- [ ] Sort by upcoming first, then status priority — deferred to Phase 4

### Readiness Summary Cards

- [x] Global readiness summary visible in the metrics strip (ready count / total)
- [x] Per-operation readiness state visible in both the operations table and the attention section
- [ ] Direct planner link from a dedicated readiness card — deferred; attention section provides op-level planner links for not-ready ops only

### Scheduler Health

- [x] Scheduler stale state surfaces in the "Needs attention" section (officer/owner) when threshold exceeded
- [x] Pending retry count surfaces in the attention section (officer/owner) when non-zero
- [ ] Dedicated standalone scheduler health card (always-visible) — deferred to Phase 6 (Diagnostics Summary Widget)

### Payout / Regear Summary

- [x] Draft + approved ledger entry count surfaces in the "Needs attention" section when non-zero (officer/owner)
- [ ] Per-operation payout totals card (approved/paid amounts, link to ledger) — deferred to Phase 6 (Recent Payouts Widget)

### Quick-Action Sidebar

- [x] Quick actions sidebar card with clearly labelled buttons: New Operation (primary), Compositions, Members (conditional), Discord settings (conditional), Scheduler (conditional)
- [x] Officer/owner-only actions gated on `can_mutate` and `can_manage_members`
- [x] All buttons are full-width text buttons via `.action-group` — no icon-only actions

### New CSS components (`app/templates/base.html`)

| Class | Description |
|---|---|
| `.summary-metrics` | Top-of-page `auto-fit, minmax(150px, 1fr)` KPI grid |
| `.metric-card--ok/warning/danger/neutral` | Semantic left-border accent variants for metric-card |
| `.attention-list` | Flex-column container for attention rows inside a card |
| `.attention-item` | Flex row: count + label + action; collapses on narrow screens |
| `.attention-item--warning/danger/info` | Semantic count colour variants |

### New repository function (`app/repositories.py`)

`count_pending_ledger_entries_for_workspace(db, guild_workspace_id)` — counts `draft` and `approved` payout ledger entries workspace-wide. Used by the dashboard attention section.

### Route additions (`app/routes.py` — `get_workspace_dashboard`)

New context variables computed inside the existing DB transaction:

| Variable | Type | Purpose |
|---|---|---|
| `active_op_count` | `int` | Count of draft/planning/locked operations |
| `ready_op_count` | `int` | Count of operations with `readiness_state == 'ready'` |
| `total_unassigned_signups` | `int` | Sum of `unassigned_signup_count` across all readiness snapshots |
| `attention_ops` | `list[dict]` | Planning/locked ops with `not_ready` or `forming` readiness |
| `pending_retry_count` | `int` | Global pending Discord dispatch retries (0 if not officer) |
| `pending_ledger_count` | `int` | Draft + approved ledger entries for workspace (0 if not officer) |
| `scheduler_stale` | `bool` | Whether scheduler last run exceeds stale threshold (False if not officer) |

---

## Phase 3 — Information Hierarchy

### Action Prominence Rules

- [x] Define a rule: every page has at most one primary call-to-action — `+ New Operation` in the sidebar is the sole `.btn-primary` on the dashboard
- [x] Primary CTA uses `.btn-primary` — no secondary element uses the same style
- [x] Document the CTA hierarchy: primary (one, sidebar), secondary (table row `.btn btn-sm`), tertiary (text links, `.section-header__action`)
- [ ] Audit existing templates for multiple competing `.btn-primary` uses and resolve — cross-template audit deferred to Phase 7

### Section Priority Rules

> Section priority order established and formalised in template comments:
> 1. Summary metrics strip (always visible)
> 2. Needs Attention section (conditional, highest-priority)
> 3. All-clear state (conditional, when healthy — only when active ops exist)
> 4. Operations table + sidebar

- [x] Formalize the priority order as a documented rule — enforced via template structure and comments
- [ ] Enforce this order across all workspace-level pages beyond the dashboard — deferred to Phase 7
- [x] Lower-priority sections do not appear above higher-priority ones in the dashboard template

### Dashboard Scan-Path Optimization

- [x] Severity-sorted attention section: `not_ready` ops (danger tier) appear before `forming` ops (warning tier) and before infra/admin items
- [x] `attention_ops_danger` and `attention_ops_warning` split in route, each sorted ascending by `scheduled_start_at` — most imminent op first
- [x] `not_ready` metric card variant changed from `--warning` to `--danger` to communicate higher urgency
- [x] Row-level readiness accents in ops table (`row-not-ready`, `row-forming`) allow severity scanning without reading badges
- [ ] Audit page load first-screen content for operation detail and planner — deferred to Phase 7

### Visual Grouping Strategy

- [x] Established pattern: all content lives in `.card` with `.card-header` — no bare content at layout level
- [x] Cross-section separation uses `margin-bottom: var(--space-5)` on cards — no `<hr>` elements
- [x] Secondary info card (Workspace) uses `.card--compact` + `.sidebar-label` instead of full `.card-header` to visually recede
- [ ] Define `.dashboard-section` include wrapping — deferred to Phase 7

### Empty-State Strategy

- [x] Positive empty state: `.all-clear-state` strip with `badge-success` — appears when active ops exist but no issues — *intentional and reassuring, not blank*
- [x] Neutral empty state: "No operations yet. Create the first one →" — inline CTA link
- [x] Transitional empty state: "All operations are archived. Start a new one →" — when active count is 0 but archived count > 0
- [x] No attention section rendered when there are no issues — it is entirely absent, not an empty card
- [ ] Informational empty states on operation detail and planner — deferred to Phase 7

### Status-Emphasis Rules

- [x] Warning and danger states produce distinct visible colour signals — `--danger-text` red for not-ready, `--warning` amber for forming
- [x] Neutral/archived rows use `.row-muted` — visually receded from active rows
- [x] Attention items use `--danger` and `--warning` tiers consistently; infra items never outrank op readiness issues
- [ ] Cross-template badge audit — deferred to Phase 7

### Shipped CSS primitives (`app/templates/base.html`)

| Class | Description |
|---|---|
| `.op-title-cell` / `.op-title-cell a` | `font-weight: 600` — makes the operation name the primary scan target in the table |
| `.op-type-cell` | Muted, small-caps type label; rendered inline below op name, not in a separate column |
| `.data-table tr.row-not-ready td` | Danger left-border accent on table rows for `not_ready` operations |
| `.data-table tr.row-forming td` | Warning left-border accent on table rows for `forming` operations |
| `.all-clear-state` | Compact success strip — only shown when active ops exist and all are healthy |
| `.card--compact` | Reduced padding variant for secondary/metadata cards |
| `.sidebar-label` | Replaces `.card-header` in low-priority sidebar cards — tiny all-caps, `--text-faint` colour |

### Route additions (`app/routes.py`)

| Variable | Type | Purpose |
|---|---|---|
| `attention_ops_danger` | `list[dict]` | `not_ready` ops sorted by `scheduled_start_at` ascending |
| `attention_ops_warning` | `list[dict]` | `forming` ops sorted by `scheduled_start_at` ascending |

`attention_ops` (the combined list) is still passed for backward-compatible conditionals. `attention_ops_danger` and `attention_ops_warning` are the new primary loop variables used in the template.

---

## Phase 4 — Dashboard UX Improvements

### Reduce Table-First Layouts

- [ ] Audit all pages that currently lead with a `<table>` and assess whether a card or summary view is more appropriate — cross-template audit deferred to Phase 7
- [ ] Replace the operations list table on the workspace dashboard with the card grid — **deferred to Phase 5**; table retained and refined in this phase instead
- [ ] Replace the workspace members table with a more scannable member list layout — deferred to Phase 7
- [x] Retained tables for dense operational data (planner slots, ledger entries, scheduler runs) where tables are genuinely the right tool

### Replace Raw Admin Feel

- [x] Replaced generic "Edit" / "Open" links on every row with context-aware CTAs:
  - `draft` → **"Setup →"** (navigate to operation setup)
  - `planning` + not-ready/forming → **"Planner →"** (navigate directly to planning work surface)
  - `locked` / `planning` ready → **"Open"** (neutral review)
  - `completed` / `archived` → **"View"** (muted, terminal state)
- [x] Operations table now has a non-trivial empty state and a transitional "all archived" state
- [x] Attention item actions updated: "Review" replaced with **"Planner →"** for op readiness items — action label now describes the work, not the destination
- [ ] Form pages with no section description or contextual help text — deferred to Phase 7
- [ ] Ensure every form page has a clear title and labelled submit — deferred to Phase 7

### Improve Workflow Discoverability

- [x] Sidebar quick actions split into three labelled sections using `.action-section-label`:
  - **Plan** — `+ New Operation`, `Compositions` (primary operational entry points, always first)
  - **Manage** — `Members` (conditional on `can_manage_members`)
  - **Settings** — `Discord settings`, `Scheduler` (configuration, visually receded with `.btn-ghost`)
- [x] Officers can identify which sidebar actions are operational vs administrative without reading every label
- [x] Attention items link directly to the work surface:
  - Not-ready / forming ops → `/planner` (not the op detail page)
  - Stale scheduler → `/settings/diagnostics`
  - Pending retries → `/settings/scheduler`
- [x] Ledger attention item provides instructional context ("open the operation below") when no direct workspace-level ledger page exists
- [ ] Remove dead-end pages (pages with no obvious next action) — cross-template audit deferred to Phase 7

### Improve Officer Scanning Speed

- [x] Readiness state visible without clicking into an operation — shown in metrics strip and operations table (Phase 2)
- [x] Pending ledger entries surfaced at dashboard level via "Needs attention" section (Phase 2)
- [x] Discord failure state visible from the dashboard via "Needs attention" section (Phase 2)
- [x] Op continuation hints (`.op-next-step`) below the title cell for states with pending work — removes ambiguity about next action
- [ ] Ensure operation status is always the first visible datum on any operation-related UI — cross-template audit deferred to Phase 7

### Improve CTA / Readiness Visibility

- [x] `+ New Operation` CTA is in the persistent sidebar, always visible (Phase 1)
- [x] `Compositions` link is elevated to the Plan section of the sidebar alongside New Operation
- [ ] Ensure "Post Announcement" and "Post Roster" are visible from the operation header — not only inside tabs — deferred to Phase 7
- [ ] Ensure "Mark paid" and "Approve entry" actions are surfaced in the payout summary, not only the full ledger — deferred to Phase 6 (Recent Payouts Widget)

### Shipped CSS components (`app/templates/base.html`)

| Class | Description |
|---|---|
| `.action-section-label` | Divider label within a sidebar action group — separates Plan / Manage / Settings tiers |
| `.btn-ghost` | Ghost button — transparent at rest, surfaces border and background on hover; used for configuration-tier sidebar actions |
| `.op-next-step` | Block-level continuation hint below the op title in a table row — shown only for states with a clear pending action |

---

## Phase 5 — Responsive Dashboard Behavior

### Breakpoints

Two `@media` breakpoints defined and applied in `base.html`:

- **768 px (tablet / compact laptop)** — tightened padding, compact `.summary-metrics`, flex-wrapped attention items, minimum button touch targets, `min-width` on `.data-table` for horizontal scroll containment.
- **480 px (phone)** — single-column `.summary-metrics`, further reduced page/card padding, scaled-down `h1`, tightened workspace nav and sidebar spacing.

### Tablet Layout Rules

- [x] Define tablet breakpoint as ≤ 768px
- [x] On tablet: `dashboard-grid` collapses to single column (breakpoint at 960 px defined in Phase 1)
- [x] On tablet: `.summary-metrics` switches to tighter `minmax(120px, 1fr)`
- [x] On tablet: card and page padding tightened to reduce wasted whitespace
- [x] On tablet: navigation remains horizontal — no hamburger menu required at this breakpoint

### Mobile Stacking Rules

- [x] Define phone breakpoint as ≤ 480px
- [x] On phone: `.summary-metrics` collapses to `1fr` (single column)
- [x] On phone: page horizontal padding reduces further; `h1` font size scales down
- [x] On phone: workspace nav padding tightened; sidebar panel gap tightened

### Dashboard Overflow Handling

- [x] `.data-table` given `min-width: 540px` so tables scroll horizontally inside `.table-wrap` before cells break
- [x] `.op-title-cell` uses `overflow-wrap: break-word` to prevent long op names from breaking layout on narrow screens
- [x] `.attention-item__body strong` wraps with `overflow-wrap: break-word`
- [ ] Audit planner page layout on tablet — ensure role/slot tables scroll horizontally — deferred
- [ ] Ensure `.op-tabs` wraps naturally on narrow screens without hiding active tab — deferred

### Touch Target Sizing

- [x] `.btn`, `.btn-primary`, `.btn-sm` given increased `min-height` (44px, 42px, 36px) at ≤ 768px for touch friendliness
- [x] `.attention-item` uses `flex-wrap: wrap` so the action button drops to a second line rather than being squeezed on narrow screens
- [ ] Audit planner and composition builder touch targets — deferred to later planner UX work

### Shipped CSS (`app/templates/base.html`)

Two `@media` blocks added at the bottom of the inline `<style>` section:

```
@media (max-width: 768px)  — tablet / compact laptop refinements
@media (max-width: 480px)  — phone/narrow refinements
```

No new CSS class names introduced — all changes are media-query overrides of existing primitives.

---

## Phase 6 — Operational Widgets

### Recent Operational Events Widget ✅ Shipped

- [x] Compact sidebar widget showing the last 5 notable operational events — newest first
- [x] Each entry shows: event label (human-readable), operation title link, relative time ("5m ago", "2h ago")
- [x] Widget only renders when `recent_activity` is non-empty — entirely absent on new workspaces
- [x] Events from archived operations are filtered out by the repository query
- [x] Covered event types: operation created/published/locked/completed/archived, payout approved/paid, Discord announcement posted/updated, roster posted/updated
- [ ] Widget links to the full operation timeline for each event — deferred (links to operation detail for now)
- [ ] Actor display name — deferred; actor data not yet enriched in the activity query

### Recent Discord Failures Widget

- [ ] Define a reusable Discord failures widget: count + last error summary — deferred; Discord retry count already shown in "Needs attention" section
- [ ] Widget links directly to the scheduler page for detail — deferred

### Recent Payouts Widget

- [ ] Define a reusable payout widget: last 5 approved/paid ledger entries — deferred
- [ ] Widget is only visible to officers/owners — deferred

### Readiness Summary Widget

- [ ] Dedicated readiness widget (operation name, readiness %, slot fill count) — deferred; readiness already surfaced in metrics strip and operations table

### Diagnostics Summary Widget

- [ ] Standalone diagnostics widget (DB state, scheduler state) — deferred; scheduler stale already surfaced in "Needs attention" section

### Widget Extensibility Rules

- [x] Widget contract followed: empty state (absent), non-empty state (rendered), permission-gated (per route context)
- [x] All widget data passed from route handler — no in-template data fetching
- [ ] Widgets as standalone Jinja2 includes — deferred to Phase 7 (current implementation is inline in `workspace_dashboard.html`)
- [ ] Document widget interface in this file as new widgets are defined — partially deferred

### New CSS components (`app/templates/base.html`)

| Class | Description |
|---|---|
| `.activity-list` | Flex-column container for recent-event rows inside a `.card--compact` |
| `.activity-item` | One event row: flex-column with `gap: 0.15em` and bottom border divider |
| `.activity-item__event` | Primary text: event label, `font-weight: 600`, `line-height: 1.35` |
| `.activity-item__op` | Secondary text: operation title link, muted colour |
| `.activity-item__meta` | Faint relative timestamp, `font-size: 0.72rem`, `--text-faint` |

### New repository function (`app/repositories.py`)

`get_recent_workspace_activity(db, guild_workspace_id, limit=5)` — queries `operational_events` joined with `guild_operations`, filters to tracked event types and excludes archived operation events, ordered by `occurred_at DESC`.

### Route additions (`app/routes.py` — `get_workspace_dashboard`)

| Addition | Purpose |
|---|---|
| `_relative_time(iso)` helper | Converts ISO timestamp → human-readable "just now / Nm ago / Nh ago / N days ago" |
| `_ACTIVITY_LABELS` dict | Maps `event_type` strings to human-readable labels |
| `recent_activity` context var | Enriched list passed to template; absent when empty |

---

## Phase 7 — Consistency / Technical Discipline

### Dead Code Removal

- [x] Removed `.three-col-metrics` — defined in Phase 1 but never used in any template; superseded by `.summary-metrics`
- [x] Fixed `test_attendance_page_hides_reliability_column_for_member` — pre-existing assertion matched a CSS comment text rather than the HTML table header; tightened to `">Reliability<"`

### CSS Section Comment Normalisation

Phase-numbered section labels replaced with responsibility-based labels in `base.html`:

| Before | After |
|---|---|
| `/* ── Phase 3 — Information Hierarchy */` | `/* ── Dashboard hierarchy — readiness accents, emphasis, empty states */` |
| `/* ── Phase 4 — Workflow Discoverability */` | `/* ── Dashboard discoverability — sidebar sections + table workflow CTAs */` |
| `/* ── Phase 6 — Operational Widgets */` | `/* ── Recent activity widget */` (block comment rewritten) |

A new `/* ── Phase 7 — Utility consolidation */` block was added to document the new utility classes, making it clear that these are stable dashboard primitives, not one-offs.

### Inline Style Elimination

- [x] `style="font-size:0.65em;color:var(--text-muted);font-weight:400"` on metric fraction → `.metric-card__fraction` class
- [x] `style="margin-left:0.4em"` on `.op-type-cell` span → moved to CSS as part of `.op-type-cell` rule
- [x] `style="white-space:nowrap;font-size:0.85em"` on scheduled date column → `.col-meta` class
- [x] `style="white-space:nowrap"` on action column → `.col-action` class
- [x] `style="color:var(--text-muted)"` on "View" button → `.btn-muted` class
- [ ] Remaining inline styles (conditional `style="color:var(--warning)"` on metric values, `style="margin-left:0.3em"` on empty state links) — retained as conditional/one-off; extracting to utility classes would add complexity without clarity benefit

### Reusable Card Primitives

- [x] Card variants documented and in use: `.card` (standard), `.card--compact` (reduced padding), `.sidebar-label` (replaces card-header in low-priority sidebar cards)
- [ ] Audit all templates for card-like structures outside the standard primitive — cross-template audit deferred to future planner/composition UX work
- [ ] Borderless (within-card) card variant — deferred; not yet needed

### Avoid One-Off Layout Hacks

- [x] All high-frequency inline layout styles eliminated from `workspace_dashboard.html`
- [ ] Cross-template inline style audit — deferred; other templates (operation_detail, planner) not touched in this phase

### Activity Widget Refinement

- [x] `.activity-item` gap increased from `0.1em` to `0.15em` for improved scanability
- [x] `.activity-item__event` given `line-height: 1.35` to improve multi-line event label readability
- [x] `.activity-item__meta` margin-top increased from `0.05em` to `0.1em` for cleaner timestamp separation
- [x] Duplicated CSS comment block for the activity widget cleaned up — single responsibility-labelled header

### Test / Regression Hardening

- [x] Added `tests/test_dashboard_widgets.py` with 11 targeted tests covering:
  - Recent activity absent on new workspaces (`class="activity-list"` absent check)
  - Recent activity present after operation lifecycle events
  - Archived operation titles excluded from activity widget
  - Sidebar "Plan" and "Settings" section labels always present for owners
  - "Needs attention" absent when scheduler is fresh and no planning ops exist
  - "Needs attention" present for `not_ready` planning ops
  - Attention ordering: `not_ready` (danger) appears before `forming` (warning) in HTML
  - All-clear state shown when active ops are healthy and scheduler is fresh
  - Context-aware CTAs: draft ops show "Setup →", not-ready planning ops show "Planner →"
- [x] `_stamp_fresh_scheduler_run()` test helper added to suppress scheduler-stale false positives in clean-state tests

### Shipped CSS utility classes (`app/templates/base.html`)

| Class | Description |
|---|---|
| `.col-meta` | Table column: muted, `font-size: 0.85em`, `white-space: nowrap` — for scheduled dates, type columns |
| `.col-action` | Table column: `white-space: nowrap` — for action button columns |
| `.btn-muted` | Button modifier: `color: var(--text-muted)` at rest, `--text` on hover — for terminal-state "View" actions |
| `.metric-card__fraction` | Inline span: `font-size: 0.65em`, muted, normal weight — for "/ total" denominators inside `__value` |

### Deferred

- Cross-template inline style audit (operation_detail, planner, ledger) — future work
- Formalising dashboard sections as standalone Jinja2 includes — future work
- `<section aria-label>` / `<nav aria-label>` semantic HTML audit — future work
- Splitting CSS into separate files — explicitly deferred (see Non-Goals)

---

## Explicit Non-Goals

- **No SPA rewrite.** The dashboard is and remains server-rendered Jinja2. No React, Vue, Alpine, or HTMX required.
- **No frontend framework migration.** JavaScript is used only where strictly necessary (details disclosure, no logic).
- **No visual gimmicks.** No animated counters, no progress bar animations, no skeleton loaders. Operational tools are not marketing pages.
- **No excessive animation.** CSS transitions are limited to color/opacity changes under 150ms. No layout-shifting animations.
- **No dashboard clutter.** Every widget or card on the dashboard must earn its place by answering a real officer question. Decorative or aspirational content is not acceptable.
- **No copying Ironkeep v1.** This is a redesign based on operational clarity principles, not a port of the previous interface.
- **No full-page redesigns in a single slice.** Dashboard composition changes are delivered in small, focused, testable slices — not a single big-bang refactor.
- **No breaking changes to existing route contracts.** Dashboard improvements do not change URL structure, HTTP methods, or query parameter conventions.

---

## Success Criteria

- [x] An officer can open the workspace dashboard and identify the top-priority action within 5 seconds — "Needs attention" section surfaces the most urgent items (danger before warning) with direct "Planner →" links.
- [x] The readiness state of the next upcoming operation is visible on the dashboard without clicking into the operation — shown in the metrics strip, operations table, and row-level border accents.
- [x] Pending actions (unresolved signups, draft ledger entries, pending retries) surface at dashboard level with direct links to the relevant page — delivered via "Needs attention" section.
- [x] The workspace dashboard does not look like a generic admin table list — metrics strip, conditional attention section, severity-sorted issues, context-aware CTAs, and sectioned sidebar create an operational feel.
- [x] All dashboard sections collapse gracefully to a single column on tablet and mobile without horizontal overflow — `auto-fit` grids, responsive `dashboard-grid`, natural flex wrapping, `min-width` scroll containment on tables.
- [x] An officer can identify what workflow action is expected next without reading every column — context-aware row CTAs ("Planner →", "Setup →", "View") and `.op-next-step` hints communicate pending work.
- [x] Operational and configuration sidebar actions are visually separated — Plan/Manage sections use standard buttons; Settings section uses `.btn-ghost`, reducing config-action visual weight.
- [x] Recent operational activity is visible at a glance — "Recent activity" sidebar widget surfaces the last 5 events with human-readable labels and relative timestamps; absent when nothing to show.
- [x] New dashboard widgets can be added by creating a scoped route helper and a template section — no structural changes required. *(primitives and patterns are in place; standalone Jinja2 include pattern deferred)*
- [x] The test suite continues to assert against stable text anchors and section headings — 11 new targeted tests added for widget rendering, attention ordering, all-clear state, and CTA behaviour; pre-existing brittleness fixed.
- [x] A new contributor can understand the full dashboard layout by reading this document and the `base.html` design tokens section.
