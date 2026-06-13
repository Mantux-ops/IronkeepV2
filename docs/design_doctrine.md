# IronkeepV2 — Design Doctrine

> **Status: Authoritative — Phase 8.7 Slice 1**
>
> This document is the permanent visual and interaction constitution for IronkeepV2.
> It governs all future UI work. When this document conflicts with ad-hoc design choices,
> this document wins.
>
> **Companion references (implementation detail, not doctrine):**
> - `docs/ui_architecture_system.md` — CSS file structure, component taxonomy, naming
> - `app/static/css/tokens.css` — canonical token values
> - `app/domain/readiness.py` — readiness state calculation rules
> - `app/tactical.py` — role family classification and tactical summaries
>
> **Cursor prompt guidance:** Read `docs/design_doctrine.md` before any visual or template change.
> Do not implement UI that violates this doctrine without an explicit doctrine amendment.

---

## Document Purpose

IronkeepV2 has completed its foundational UI architecture (Phases 1–8), design system consolidation (Phase 8.6), and operational register reinforcement (Phase 8.6 Slices A–B). What was missing was a single, permanent statement of *why* the system looks and behaves the way it does — and what must never change without deliberate review.

This doctrine exists so that:
- Officers experience one coherent command surface, not a collection of pages
- Future UI work increases operational clarity by default
- Design decisions can be reviewed against rules, not taste
- IronkeepV2 remains distinct from generic SaaS dashboards and dev-tool clones

---

# 1. Product Identity

## What IronkeepV2 Is

IronkeepV2 is an **operational command platform** for Albion Online guild officers.

It is:
- A **tactical planning surface** — compositions, slot assignments, role distribution, readiness
- **Guild operations software** — signup, roster lock, attendance, Discord coordination
- A **server-rendered coordination system** — FastAPI + Jinja2, no SPA, no frontend framework
- A **trust instrument** — officers rely on it immediately before and during live CTAs

Every visual decision must answer: *does this help an officer understand operational state under time pressure?*

## What IronkeepV2 Is Not

IronkeepV2 must never be styled or positioned as:

| Not this | Why |
|---|---|
| Generic SaaS dashboard | Card grids, metric vanity, "all-in-one platform" aesthetics obscure tactical state |
| AI / chat application | Conversational UI patterns (bubbles, prompts, streaming text) are wrong register |
| Social platform | Activity feeds, reactions, profile-centric layouts are out of scope |
| Marketing-first application | Decorative hero sections belong on the landing page only, never in operational surfaces |
| Developer tool clone | Linear/Raycast/Vercel aesthetics are references for discipline, not targets for imitation |
| Game client UI | Ornament, glow, HUD chrome, animated scan lines — landing page only, never planner |

The product identity is **mission control for a guild operation**, not a productivity app with a dark theme.

---

# 2. Design Principles

These principles are ordered by priority. When principles conflict, higher items win.

### 1. Data Before Decoration
Operational data — slot fill, role gaps, readiness state, assignment status — must be visible before any decorative element registers. If a visual element does not carry operational meaning, remove it.

### 2. Operational Clarity Before Aesthetics
Beauty is a side effect of clarity, not a goal. A dense, readable planner beats a spacious, elegant dashboard every time for this product.

### 3. State Before Interaction
Officers scan state first, then act. Visual hierarchy must communicate *what is happening* before *what can be clicked*. Buttons and links are secondary to badges, borders, tallies, and gap signals.

### 4. Density Where Operationally Justified
The planner and composition surfaces are high-density by design. Administrative surfaces (settings, build forms) may breathe more. Public surfaces (landing, login) may be spacious. Density is not universal — it is register-specific.

### 5. Consistency Over Novelty
A new surface that looks "fresh" but uses different status colours, spacing, or component names is a regression. Reuse existing primitives. Novel patterns require doctrine review.

### 6. Server-Rendered Simplicity
No JavaScript framework. No build pipeline. Progressive enhancement only for non-critical affordances. The UI must be fully functional with JavaScript disabled.

### 7. Honest Presentation
No aspirational screenshots. No invented metrics. No enterprise SaaS language. The product is what it is — a guild coordination tool for structured Albion operations.

### 8. Preserve Testability
Meaningful UI states must be assertable via CSS class presence in pytest. Class names are part of the operational contract, not implementation details.

---

# 3. Visual Registers

IronkeepV2 has three visual registers. Each register has its own density, typography, and component expectations. **Never apply one register's rules to another.**

---

## Public Register

**Purpose:** Attract, explain, and authenticate. First contact for officers and alliance members who have not yet entered a workspace.

**Surfaces:**
- Landing page (`landing.html`, `landing.css`)
- Login / auth (`login.html`, `base_public.html`)
- Open signup page (member-facing, read-only roster view)

**Density:** Low to medium. Generous section spacing is acceptable. Content may breathe.

**Typography:** Marketing headings may be larger (`--text-xl`, `--text-2xl`). Body remains `--text-base`. Operational monospace rules do not apply to marketing copy.

**Appropriate components:**
- Hero sections, feature showcases, step flows
- `.btn-discord`, primary CTA buttons
- Real product screenshots from actual planner state (not invented mockups)
- `.ls-*` landing-specific classes

**Inappropriate components:**
- Slot cards, gap pills, role tallies (show in screenshots only, not as interactive UI)
- Dashboard metric cards
- Tactical readiness instruments

**Motion:** Permitted with restraint. Landing transitions must respect `prefers-reduced-motion`. Operational motion rules do not apply here.

**Examples:**
- `app/templates/landing.html`
- `app/static/css/landing.css`

---

## Administrative Register

**Purpose:** Configure, manage, and maintain. Officers set up workspaces, builds, compositions, Discord integration, and members.

**Surfaces:**
- Workspace dashboard (summary view — borderline operational; see note below)
- Build library (list, detail, edit, import)
- Composition builder (list, detail, edit, new)
- Settings (Discord, members, diagnostics, scheduler)
- Operation overview (detail page — pre/post planning)
- Account page

**Density:** Medium. Forms, tables, and cards with standard spacing (`--space-3` to `--space-5`).

**Typography:** Standard scale. Tabular numbers on numeric columns in tables. Monospace for IDs, snowflakes, timestamps in diagnostics.

**Appropriate components:**
- `.card`, `.data-table`, form system (`forms.css`)
- `.badge-*` for lifecycle and entity status
- `.empty-state`, flash messages, action bars
- Build cards (`.bld-card`), composition builder (`.cb-*`)

**Inappropriate components:**
- Planner slot cards at full tactical density (composition preview uses reduced preview mode)
- Readiness fill bar (operation detail shows summary, not full instrument)
- Party panel layouts

**Note on dashboard:** The workspace dashboard is administrative in layout but displays operational signals (readiness badges, attention items). It must use canonical status vocabulary and badge classes, not ad-hoc inline colours.

**Examples:**
- `app/templates/builds_list.html`
- `app/templates/compositions_edit.html`
- `app/templates/workspace_discord_settings.html`

---

## Operational Register

**Purpose:** Live coordination. Officers assign players, read readiness, detect gaps, lock rosters, and post to Discord during active planning windows.

**Surfaces:**
- **Tactical planner** (`operation_planner.html`) — primary surface
- Operation tabs context (planner, signup, attendance, ledger, timeline)
- Discord roster/announcement previews embedded in planner and detail
- Signup page (officer view with assignment context)

**Density:** High. Compact spacing. Minimal vertical waste. Every pixel serves scan speed.

**Typography:** Mixed register — proportional sans for labels and names; tabular numbers and monospace for counts, percentages, timestamps, and slot indices.

**Appropriate components:**
- `.slot-card`, `.party-panel`, `.party-summary`
- `.role-tally`, `.comp-overview`, `.tac-gap-badge`
- `.gap-pill`, `.gap-pills`, `.readiness-fill`, `.readiness-sticky`
- `.fill-count`, `.readiness-bar__*`
- `.planner-columns`, sticky readiness card

**Inappropriate components:**
- Large metric hero cards
- Spacious empty-state boxes with excessive padding
- Decorative illustrations or gradients
- Generic `.text-danger` / `.text-warning` paragraphs (use gap pills)
- Inline `style=""` colour overrides

**Examples:**
- `app/templates/operation_planner.html`
- `app/static/css/tactical.css`

---

# 4. Typography Doctrine

IronkeepV2 uses a **dual-typography model**: proportional sans for human-readable labels, monospace/tabular for live operational data. This follows command-center convention — instruments read differently from instructions.

## Heading Hierarchy

| Level | Use | Size token | Weight |
|---|---|---|---|
| Page title | One per page, in `.page-header` or `.card-header h2` | `--text-xl` or card default | 600–700 |
| Section title | Card headers, party panels | `--text-lg` or default h2/h3 | 600 |
| Subsection | Panel labels, form sections | `--text-base` | 600 |
| Meta label | Uppercase section caps, table headers | `--text-xs` / `--text-sm` | 600, letter-spacing |

**Rules:**
- One `h1` per page (page title)
- Planner party panels use `h3` under planner context — acceptable; do not restructure for AT marginal gain
- Settings pages with `h3` inside cards without preceding `h2` are known violations — fix when touched

## Body Text

- Default: `--text-base` (0.875rem / 14px), `--text` colour
- Secondary: `--text-sm`, `--text-muted`
- Disabled / placeholder: `--text-faint`

## Monospace Usage

Use `font-family: ui-monospace, monospace` for:

| Content | Example |
|---|---|
| Discord snowflakes | Channel IDs, guild IDs |
| Scheduler job names | Diagnostics tables |
| Slot indices | `#1`, `#2` in compact contexts |
| API-style identifiers | When shown to officers for copy/paste |

**Do not** use monospace for:
- Player names
- Build names / weapon names
- Role labels
- Composition names
- General paragraph text

## Tabular Number Usage

Use `font-variant-numeric: tabular-nums` for:

| Content | Example |
|---|---|
| Slot counts | `3 / 5 assigned` |
| Readiness percentages | `60%` |
| Role tally counts | `T:2 H:1 D:3` |
| Dashboard metric values | Operation counts |
| Attendance numbers | Marked / unmarked counts |
| Open slot counts | Per-party fill counts |

Tabular numbers align columns for scan speed. Apply via CSS class, not inline styles.

## Operational Metrics Presentation

Operational metrics are **instrument readings**, not form labels. They must:

1. Use tabular numbers (and monospace where specified below)
2. Appear adjacent to their unit/context (`3 / 5 assigned`, not just `3`)
3. Use state colour only through canonical badge/fill classes — not inline `style="color:..."`
4. Update via server re-render — never animate the numeric value

| Metric type | Presentation rule |
|---|---|
| **Counts** (assigned/total, open slots) | `assigned / total` format; tabular nums; in readiness header and fill-count |
| **Percentages** (readiness fill) | Integer percent; shown as number + fill bar width; `0%` when total is 0 |
| **Timestamps** (snapshot created_at) | ISO truncated to minute; `--text-muted`; `--text-sm` or `readiness-bar__meta` |
| **Readiness metrics** (gaps, signups, attendance) | Gap pills for roles/builds; secondary stats row for signups/attendance/scouts |

---

# 5. Status Vocabulary

IronkeepV2 has **two distinct status domains**. They must never share CSS classes or colour assignments incorrectly.

---

## A. Readiness Status (snapshot readiness_state)

Computed by `app/domain/readiness.py`. Based solely on slot assignment coverage.

| State | Meaning | Threshold |
|---|---|---|
| `ready` | All slots assigned | `open_slots == 0` (and `total_slots > 0`) |
| `forming` | Roster filling, acceptable progress | ≥ 75% fill ratio |
| `not_ready` | Insufficient coverage | < 75% fill, or `total_slots == 0` |

### Colours (readiness)

| State | Badge class | Fill bar class | Semantic tokens |
|---|---|---|---|
| `ready` | `.badge-ready` | `.readiness-fill--ready` | `--success-*` |
| `forming` | `.badge-forming` | `.readiness-fill--forming` | `--warning-*` |
| `not_ready` | `.badge-not_ready` | `.readiness-fill--not_ready` | `--danger-*` |

### Allowed usages
- Readiness badge in planner readiness card, operation detail, dashboard operation rows
- Readiness fill bar colour in planner
- Dashboard attention items referencing readiness state
- Gap pills alongside readiness (role/build gaps are separate signals)

### Prohibited usages
- Using readiness colours for operation lifecycle status
- Using `.text-danger` / `.text-warning` instead of gap pills or badges
- Inline `style="color:var(--danger-text)"` for readiness on dashboard (use badge classes)
- Animating readiness percentage or fill bar width on every poll (initial render transition only, max 200ms)

---

## B. Operation Lifecycle Status (operation.status)

Computed by domain state machine in `app/domain/guild_operations.py`.

| State | Meaning |
|---|---|
| `draft` | Created; not open for signups |
| `planning` | Published; signups and assignments active |
| `locked` | Roster frozen; assignment mutations disabled |
| `completed` | Operation finished |
| `archived` | Closed / historical |

### Colours (operation lifecycle)

| State | Badge class | Tab accent (`data-op-status`) | Semantic tokens |
|---|---|---|---|
| `draft` | `.badge-draft` | `--border-strong` | muted |
| `planning` | `.badge-planning` | `--accent` ⚠ | info |
| `locked` | `.badge-locked` | `--info` | info |
| `completed` | `.badge-completed` | `--success` | success |
| `archived` | `.badge-archived` | `--border` | faint |

⚠ **Known tension:** `planning` tab accent uses `--accent`. Doctrine prefers status colours for state communication and accent for interaction only. See violations section.

### Allowed usages
- Operation list badges, tab strip accent, operation header status
- Conditional rendering (show/hide Lock Roster button)
- Locked planner banner (`.alert-info` — informational, not error)

### Prohibited usages
- Using operation status colours for readiness fill bars
- Treating `locked` as danger — it is informational/frozen, not an error
- Using `badge-planning` colour to mean readiness `forming` (different domains)

---

## C. Gap Severity (tactical, not lifecycle)

| Signal | Class | Token | Meaning |
|---|---|---|---|
| Role gap | `.gap-pill--role` | `--danger-*` | Required role slot empty |
| Build gap | `.gap-pill--build` | `--warning-*` | Build missing on slot |
| All clear | `.gap-pill--ok` | `--success-*` | No role or build gaps |
| Critical party gap | `.tac-gap-badge--critical` | `--danger-*` | Blocking tactical gap in party strip |
| Warn party gap | `.tac-gap-badge--warn` | `--warning-*` | Sub-optimal gap |

Gap pills are the **canonical** gap warning component in the operational register. Do not create alternate warning patterns.

---

# 6. Role Vocabulary

Role colours identify **Albion tactical role families** for scan speed. They are semantic, not decorative.

## Canonical Role Families

From `app/tactical.py::role_family()` — these are the only valid CSS `data-role` values:

| Family | Token | Colour role | Display aliases |
|---|---|---|---|
| `tank` | `--role-tank` | Steel blue | frontline → tank |
| `healer` | `--role-healer` | Forest green | holy, nature → healer |
| `support` | `--role-support` | Muted violet | — |
| `dps` | `--role-dps` | War red | melee → dps |
| `ranged` | `--role-ranged` | Amber gold | — |
| `default` | `--role-default` | Neutral grey | unclassified |

**Never change role token values without updating all three consumers:**
1. `app/static/css/tactical.css` (slot cards, role tally)
2. `app/static/css/builds.css` (build card role labels)
3. `app/static/css/landing.css` (showcase tally labels)

## Where Role Colours Appear

| Surface | Element | Mechanism |
|---|---|---|
| Planner slot cards | Left border, role label | `[data-role="*"]` on `.slot-card` |
| Role tally strip | T/H/D/S/R counts | `.role-tally__item[data-role="*"]` |
| Build library cards | Role label text | `.bld-card[data-role="*"] .bld-card__role` |
| Composition overview | Tally strip | Same as role tally |
| Landing showcase | Demo tally | `.ls-tally__label--*` |

## Where Role Colours Must NOT Appear

- Navigation chrome (nav links, tabs, breadcrumbs)
- Primary buttons (`.btn`, `.btn-primary`)
- Page backgrounds or card backgrounds (role colour is accent on border/label, not fill)
- Status badges (readiness, operation lifecycle — separate vocabulary)
- Discord embed mock (uses Discord's own palette)
- Error/warning alerts unrelated to role identity
- Random colour assignment for visual variety

## Role Tally Format

Canonical format: `T:n H:n D:n S:n R:n` with bold count inside each item.

Zero counts use `.role-tally__item--zero` (dimmed). Do not hide zero counts — they signal gaps.

---

# 7. Surface Hierarchy

IronkeepV2 uses a four-step dark surface ladder. Depth is communicated through **surface luminance**, not drop shadows.

## Token Definitions

| Token | Value | Role |
|---|---|---|
| `--bg` | `#0d1117` | Page canvas only |
| `--surface` | `#161b22` | Cards, panels, primary containers |
| `--surface-2` | `#1c2128` | Card headers, elevated sub-panels, comp-overview background |
| `--surface-3` | `#22272e` | Hover states, input backgrounds, fill bar tracks |

## Rules

### Cards
- All `.card` backgrounds use `--surface`
- Card headers use `--surface-2` (already in `components.css`)
- Cards must not use `--bg` as background
- Cards must not use drop shadows for depth (border `--border` is sufficient)

### Nested Cards
- Inner panels within cards use `--surface-2`
- Third level uses `--surface-3` (rare — avoid deep nesting)
- Never nest more than two card levels in operational register

### Hover Surfaces
- Interactive row hover: `--surface-2` or `--surface-3`
- Slot card hover: border colour shift only (see tactical.css)
- Button hover: defined in `components.css` — do not override per-page

### Popovers / Dropdowns
- Use `--surface-2` or `--surface-3`
- Border: `--border` or `--border-strong`
- No box-shadow elevation stacks

### Prohibited
- Using `--bg` for card bodies
- Hardcoded hex backgrounds outside tokens.css
- `box-shadow` for primary depth (shadow tokens exist for focus rings and rare modals only)
- Glassmorphism, frosted overlays, or gradient fills on data surfaces

---

# 8. Accent Usage

## What Accent Means

`--accent` (`#58a6ff`) means **"you can interact with this"**. It is an affordance colour, not a status colour.

Accent communicates:
- Links (`a { color: var(--accent) }`)
- Focus rings (`--shadow-focus`)
- Active navigation state (workspace nav active tab)
- Open slot border (slot accepting assignment — interactive state)
- Primary action buttons (`.btn-primary`)
- Tactical overview accent stripe (`.comp-overview` left border — "this is the active planning context")

## Where Accent May Appear

| Context | Usage |
|---|---|
| Links | Default link colour |
| Focus visible | Keyboard focus rings on all interactive elements |
| Active nav | Workspace nav active tab underline |
| Primary buttons | `.btn-primary`, publish actions |
| Open slot state | `.slot-card--open` left border (slot is actionable) |
| Comp overview stripe | `.comp-overview { border-left: 3px solid var(--accent) }` |
| Hint links | Secondary navigation within tactical context |

## Where Accent Must Never Appear

| Context | Why |
|---|---|
| Readiness state | Use success/warning/danger |
| Operation lifecycle status badge fill | Use lifecycle badge classes |
| Role identity | Use `--role-*` tokens |
| Error/danger alerts | Use `--danger-*` |
| Decorative headings | Accent is not emphasis |
| Background fills for large areas | Accent-dim (`.accent-dim`) only for small highlights |
| Gap pills | Use gap severity tokens |

**Doctrine rule:** If a colour communicates *state*, it is not accent. If it communicates *interaction*, it may be accent.

---

# 9. Motion Rules

IronkeepV2 is a coordination system used under time pressure. Motion must not delay comprehension.

## Allowed Motion

| Context | Max duration | Purpose |
|---|---|---|
| Modal / dialog entry | 150ms | Confirm destructive actions (lock roster) |
| `<details>` disclosure arrow rotation | 120ms | Expand/collapse secondary panels |
| Focus/hover transitions | 120ms | Button and link feedback |
| Readiness fill bar initial width | 200ms ease-out | One-time render only |
| Landing page (public register) | 120ms | Marketing surface only; respect `prefers-reduced-motion` |

## Forbidden Motion

| Context | Why |
|---|---|
| Slot card content on re-render | Planner must feel instant after POST-redirect |
| Readiness count/percentage value changes | Numbers are instruments — they must not tween |
| Role tally count changes | Same |
| Gap pill appearance | State change must be immediate |
| Page-wide animations | No fade-in on planner load |
| Parallax, scroll-triggered effects | Public register only, never operational |
| Loading spinners on assignment POST | SSR redirect pattern — flash message, not spinner |

## Reduced Motion

All transitions in `landing.css` must be disabled under `@media (prefers-reduced-motion: reduce)`. Operational CSS should avoid introducing new transitions without this guard.

---

# 10. Planner Doctrine

The tactical planner is the **primary operational surface** of IronkeepV2. It is the reference implementation of this doctrine.

## Planner as Command Center

When an officer opens the planner, they must be able to answer within 5 seconds:
1. How full is the roster? (readiness fill bar + percentage)
2. What roles or builds are missing? (gap pills)
3. Which parties have gaps? (party summary strips, weak party borders)
4. Who is assigned where? (slot cards with role colour)
5. Can I still mutate assignments? (operation status, locked banner)

If any of these require scrolling past decorative content, the planner has failed.

## Tactical Density Principles

- **Sticky readiness card** at top of planner column — always visible on wide screens
- **Two-column layout** on ≥960px: left = reserve/bench/signups; right = party panels
- **Party panels** grouped with fill count, role tally, and gap badges in summary strip
- **Slot cards** compact: role + build + player in minimum vertical space
- **Secondary actions** (build edit, manual assign) in `<details>` disclosure — not always visible
- **Gap pills** not paragraphs — scannable tokens, not sentences

## Scan Speed Requirements

| Element | Scan target |
|---|---|
| Readiness state badge | Peripheral vision — colour alone must register |
| Role tally | Single horizontal strip, all parties visible in comp-overview |
| Slot assignment state | Left border colour on slot card |
| Missing role | Red gap pill or critical tac-gap-badge |
| Open slot accepting signup | Accent left border on slot card |

Colour-only state communication is an accepted tradeoff for scan speed. Do not add icons to badges for differentiation unless accessibility audit requires it.

## Operational Hierarchy (planner top → bottom)

1. **Operation header** — title, status, composition link, lock/publish actions
2. **Locked banner** (if `status == locked`) — informational, immediate
3. **Readiness instrument** — fill bar, percentage, state badge, gap pills, secondary stats
4. **Comp overview strip** — full-composition role tally + continuation hint
5. **Party panels** — ordered by party number, scroll-anchored (`#party-N`)
6. **Reserve / bench** (left column) — secondary to party assignment
7. **Discord preview** (collapsible) — tertiary, post-planning

Do not reorder this hierarchy without doctrine amendment.

## Planner-Specific Components (canonical)

| Component | Class | Register |
|---|---|---|
| Readiness instrument | `.readiness-sticky`, `.readiness-fill`, `.readiness-bar__*` | Operational |
| Gap warnings | `.gap-pills`, `.gap-pill--role/build/ok` | Operational |
| Comp overview | `.comp-overview`, `.comp-overview__hint--*` | Operational |
| Party summary | `.party-summary`, `.role-tally`, `.tac-gap-badge` | Operational |
| Slot card | `.slot-card`, `.slot-card--assigned/open/empty` | Operational |
| Fill count | `.fill-count--full/partial/empty` | Operational |

---

# 11. Future UI Review Checklist

Before merging any UI change, answer all questions. If any answer is "no" or "violation", stop and revise.

## Register Identification

- [ ] Which register does this surface belong to? (Public / Administrative / Operational)
- [ ] Am I applying the correct density level for that register?
- [ ] Am I importing components from another register inappropriately?

## Operational Clarity

- [ ] Does this change help an officer understand operational state faster?
- [ ] Does it add decorative complexity without operational meaning?
- [ ] Can the primary question ("what is the state?") still be answered at a glance?

## Status Vocabulary

- [ ] Does it use canonical readiness states (`ready`, `forming`, `not_ready`) correctly?
- [ ] Does it use canonical operation lifecycle states (`draft`, `planning`, `locked`, etc.) correctly?
- [ ] Does it avoid mixing readiness colours with lifecycle colours?
- [ ] Does it use gap pills (not `text-danger`/`text-warning` paragraphs) for gap warnings in operational register?

## Role Vocabulary

- [ ] Does it use `--role-*` tokens via `data-role` attributes?
- [ ] Does it avoid role colours on non-role elements (nav, buttons, backgrounds)?
- [ ] Is ranged using `--role-ranged` (amber), not `--role-dps` (red)?

## Surface & Accent

- [ ] Does it use the surface ladder correctly (no `--bg` cards)?
- [ ] Is `--accent` used only for interaction affordances, not state?
- [ ] Are borders hairline (`--border`), not heavy or decorative?

## Typography

- [ ] Are operational counts using tabular numbers?
- [ ] Is monospace limited to IDs, indices, and diagnostics?
- [ ] Are player/build/role names in proportional sans?

## Motion

- [ ] Does it avoid animating operational data values?
- [ ] Are any new transitions ≤ 200ms with reduced-motion guard?

## Implementation Hygiene

- [ ] Does it use tokens from `tokens.css`, not hardcoded hex?
- [ ] Does it use existing component classes, not new one-off patterns?
- [ ] Does it avoid inline `style=""` attributes (extract to CSS class)?
- [ ] Are meaningful states covered by existing or new pytest assertions?

## Testing

- [ ] Which validation tier applies? (See `docs/testing_strategy.md` **Risk-Scaled Validation Matrix**, Section 3.5)
- [ ] Template class changes (single surface, visual/identity): **Tier 4a** (targeted slice + surface tests)
- [ ] Template class changes (multi-surface / shared inheritance): **Tier 4b**
- [ ] Tactical/planner **behavior** changes: Tier 3 + Tier 4a
- [ ] Visual/identity work (brand, hero, typography utilities, CSS polish): **Tier 4a — Tier 5 not required**

---

# Appendix A — Existing Violations Discovered

Audit date: 2026-06-12. These are known gaps between current implementation and this doctrine. **Do not fix in Slice 1** — ranked for Slice 2 in Appendix B.

| # | Violation | Register | Severity | Location |
|---|---|---|---|---|
| V1 | **Inline `style=""` attributes** — bypass CSS system, prevent token enforcement | All | High | 25+ templates; heaviest in `operation_ledger.html`, `account.html`, `workspace_dashboard.html`, `operation_planner.html` |
| V2 | ~~**Dashboard inline colour styles** for readiness~~ — fixed Slice 2: badge classes on metric subs and attention items | Administrative | — | `workspace_dashboard.html` |
| V3 | **Operation `planning` tab accent uses `--accent`** — conflates interaction colour with lifecycle state | Operational | Medium | `components.css` `main[data-op-status="planning"]` |
| V4 | ~~**`badge-locked` uses warning tokens**~~ — fixed Slice 2: info tokens aligned with locked banner | Operational | — | `components.css` |
| V5 | ~~**Monospace/tabular not enforced** on all operational metrics~~ — fixed Slice 2: `op-metric*` utilities on dashboard, planner, detail | Operational | — | Dashboard rows, planner readiness, operation detail stat grid |
| V6 | **Template duplication** — comp-overview, party-summary, slot card grids duplicated across planner and composition detail without shared macro | Operational | Medium | `operation_planner.html`, `compositions_detail.html` |
| V7 | **Slot card / disclosure transitions** on border and arrow — minor motion on operational data containers | Operational | Low | `tactical.css` `.slot-card`, `.slot-build-edit`, `.slot-manual-assign` |
| V8 | **Heading hierarchy gap** — `h3` without preceding `h2` in Discord settings | Administrative | Low | `workspace_discord_settings.html` |
| V9 | **Nav link colour** — global nav uses `--nav-muted` but active state enforcement not documented in CSS as doctrine rule | All | Low | `layout.css` |
| V10 | **Colour-only badge differentiation** — readiness/attendance badges distinguish state by colour alone (accessibility risk) | All | Low | `components.css` badge system |
| V11 | **Composition builder transitions** on slot cards — administrative register, acceptable but undocumented | Administrative | Low | `composition_builder.css` |
| V12 | **`text-danger` / `text-warning` utilities remain** — could reintroduce non-gap-pill warnings if used in operational templates | Operational | Medium | `utilities.css`; grep before use in planner/detail |
| V13 | **Phase 8 responsive comp editor breakpoints** still unchecked — mobile/tablet planner layouts incomplete | Operational | Medium | `integrated_composition_builder_foundation.md` open items |

**Fixed in Phase 8.6 (no longer violations):**
- Undefined CSS tokens in builds.css / tactical.css
- Ranged role colour mismatch (builds vs planner)
- Gap pills missing on operation detail (Slice A)
- Locked planner banner missing (Slice A)
- Readiness as text-only summary without fill bar (Slice B)
- Missing `.empty-state`, `.btn-secondary`, `.btn-discord` definitions

---

# Appendix B — Recommended Phase 8.7 Slice 2 Candidates

Ranked by **impact × (1 / risk)**. Highest first.

| Rank | Slice | Impact | Risk | Effort | Notes |
|---|---|---|---|---|---|
| **1** | **Operational metrics typography pass** | High | Low | Small | Add tabular-nums/monospace classes to readiness counts, dashboard slot counts, role tallies; CSS-only + class additions |
| **2** | **Dashboard readiness inline colour cleanup** | High | Low | Small | Replace inline `style="color:..."` with badge classes in `workspace_dashboard.html` |
| **3** | **Accent scope correction** | Medium | Medium | Small | Change `planning` op-status tab accent from `--accent` to `--info` or `--border-strong`; preserves interaction/accent separation |
| **4** | **Locked state semantic alignment** | Medium | Low | Small | Align `badge-locked` with informational (info/muted) rather than warning; match locked banner |
| **5** | **Planner inline style elimination** | High | Medium | Medium | Extract 13 inline styles from `operation_planner.html` to tactical.css classes |
| **6** | **Nav dimming enforcement** | Medium | Low | Small | Document and enforce `--nav-muted` default, bright active only; workflow-order nav links |
| **7** | **Comp-overview macro extraction** | Medium | Medium | Medium | Shared Jinja macro for comp-overview strip; reduces drift between planner and composition detail |
| **8** | **Operational motion audit** | Low | Low | Small | Remove or gate slot-card border transitions; add `prefers-reduced-motion` to tactical.css |
| **9** | **Inline style elimination (admin templates)** | Medium | Medium | Large | Ledger, account, builds — high file count, lower operational urgency |
| **10** | **Responsive planner breakpoints** | High | High | Large | Deferred from Phase 8; significant template + CSS work; do after doctrine enforcement slices |

### Recommended Slice 2 scope (single prompt)

**"Phase 8.7 Slice 2 — Doctrine Enforcement: Metrics & Dashboard"**

Implement ranks **1, 2, and 4** together:
- Typography classes for operational metrics
- Dashboard inline colour → badge class migration
- Locked badge semantic alignment

Validation: Tier 4a (slice tests). Tier 5 not required unless behavioral paths also changed.

---

# Appendix C — Relationship to Other Documents

| Document | Relationship |
|---|---|
| `docs/ui_architecture_system.md` | Implementation architecture — file structure, BEM naming, phase log. Doctrine defines *rules*; UI architecture defines *structure*. |
| `docs/integrated_composition_builder_foundation.md` | Feature phases for composition workflow. Doctrine governs how those features look. |
| `docs/landing_page_tactical_operations_platform.md` | Public register messaging and layout spec. Must conform to Public Register rules here. |
| `docs/testing_strategy.md` | Validation tiers and **Risk-Scaled Validation Matrix** (Section 3.5). Checklist in Section 11 references this. |
| `docs/pre_weekend_live_trial_checklist.md` | Operational verification — doctrine ensures trial surfaces are coherent. |
| Command-Center Design Audit (2026-06) | Reference analysis that informed Sections 2, 4, 7, 8, 9. Not duplicated here. |
| Design System Consistency Audit (2026-05) | Tier 1–5 roadmap; Phase 8.6 addressed Tiers 1, 2, 4. Tier 3 (component unification) remains. |
| Operational Register Audit (2026-05) | Phase 8.6 Slices A–B addressed gap pills, locked banner, readiness instrument. |

---

*Document version: Phase 8.7 Slice 1 — testing matrix aligned Phase 9.0 — 2026-06-13*
*No code changes. Doctrine only.*
