# IronkeepV2 — UI Architecture System

## Current Status

**Phase 8 complete. Phase 9 is the active next target.**

| Phase | Status | Summary |
|---|---|---|
| Phase 1 — UI Inventory / Audit | ✅ Shipped | Full audit complete — findings, counts, and cleanup order documented below |
| Phase 2 — CSS Extraction from base.html | ✅ Shipped | All CSS extracted to 10 static files; `base.html` reduced from 1,485 to 54 lines |
| Phase 3 — Token and Base Layer Formalization | ✅ Shipped | Typography scale added; 60+ hardcoded values normalized; specialty badge tokens centralized |
| Phase 4 — Component Layer Formalization | ✅ Shipped | 4 undefined classes added; metric-card BEM reunited; slot-card--empty formalized; modifier naming documented |
| Phase 5 — Tactical UI Layer Formalization | ✅ Shipped | Tactical summary hierarchy documented; role-default selectors added; dead CSS removed; hint-neutral added |
| Phase 6 — Template Include / Macro Cleanup | ✅ Shipped | `discord_embed` macro added to `_discord_macros.html`; used in `operation_detail.html` and `operation_planner.html`; `flash_messages.html` extended with `warning`/`info` support; tactical card abstraction intentionally avoided |
| Phase 7 — Responsive and Accessibility Hardening | ✅ Shipped | Skip link added; nav aria-labels added; focus-visible rings for links/nav/tabs/summaries; `scope="col"` on all data tables; `sr-only` utility; form-in-p fixed; inline-style debt cleaned; tactical density preserved |
| Phase 8 — Regression Test Hardening | ✅ Shipped | 25 new regression tests in `test_ui_regression.py`; covers slot-card states, data-role attributes, tac-gap-badge, comp-overview, status badges, empty states, skip link, nav aria-labels, table scope, sr-only anchors |
| Phase 9 — Landing Page UI Alignment | 🔲 Not started | — |

Read this document before modifying CSS, templates, or layout patterns in any IronkeepV2 surface. It is the authoritative reference for UI structure, component taxonomy, design tokens, and naming conventions.

---

## Problem Statement

IronkeepV2 has accumulated UI across multiple development phases — dashboard widgets, tactical planner slot cards, composition previews, diagnostics panels, attendance tables, payout ledgers, and a landing page — without a formal architecture governing them. The result is:

- **All CSS lives in `base.html`.** One monolithic inline `<style>` block of ~1,000+ lines serves every page. It is unsearchable, unextractable, and hard to reason about in sections.
- **Component naming is inconsistent.** Slot cards use BEM (`.slot-card__header`), tables use flat descriptors (`.data-table`), dashboard widgets use hybrid patterns (`.metric-card`, `.activity-widget`). There is no enforced taxonomy.
- **Design tokens exist but are incomplete.** Color tokens live in `:root`, spacing tokens do not exist, and typography tokens are absent. Components use a mix of token references and hardcoded pixel values.
- **Tactical UI primitives are partially formalised.** Phase 8 of the Tactical Composition Planning Foundation created `app/tactical.py` and removed Jinja classification logic, but the corresponding CSS primitives (`slot-card`, `role-tally`, `comp-overview`) are documented nowhere as a formal system.
- **Responsive behaviour is ad-hoc.** Media queries appear inline throughout `base.html` with no documented breakpoint strategy or mobile-first vs desktop-first policy.
- **Templates duplicate structural HTML.** The `comp-overview` strip, `party-summary` strip, and slot card grid appear in both `operation_planner.html` and `compositions_detail.html` without shared includes or macros.
- **No shared empty-state or loading-state pattern.** Each page implements its own "nothing here" message with different wording, styling, and placement.

This is acceptable for a solo development pace. It becomes a maintenance liability as the tactical system scales — more planner surfaces, more composition views, a landing page, future operator dashboards — without a shared foundation.

---

## Goal

Define a **formal, lightweight UI architecture** for IronkeepV2 that:

1. Separates CSS into purpose-oriented files rather than one monolithic block.
2. Establishes a canonical component taxonomy with consistent naming conventions.
3. Formalises design tokens for colour, spacing, and typography.
4. Documents tactical UI primitives so they can be reused across every planning surface.
5. Defines a state/status system used identically by all surfaces.
6. Creates a responsive strategy that is explicit, documented, and consistently applied.
7. Establishes a template include / macro strategy to eliminate structural HTML duplication.
8. Preserves all server-rendered simplicity — no build pipeline, no framework, no SPA dependency.
9. Makes future Cursor-assisted development faster and less error-prone by providing a shared reference.

---

## Core UI Principles

### Operational Clarity First
Every layout decision must serve one primary question: *can an officer understand the operational state at a glance?* Visual complexity that does not directly aid comprehension is removed, not decorated.

### Tactical Density
The planner and composition surfaces must display meaningful information at a high density without sacrificing readability. Compact components, tight spacing, and restrained whitespace are preferred over spacious "card-heavy" dashboard aesthetics.

### Server-Rendered Simplicity
All UI is generated by Jinja2 templates and FastAPI route handlers. No JavaScript framework is required for core functionality. Progressive JavaScript enhancement is acceptable for non-critical affordances (e.g. client-side search filtering) but must never be a hard dependency.

### Reusable Primitives Over Page-Specific Hacks
Every recurring visual pattern — slot cards, role tallies, gap badges, metric cards, status badges — must exist as a named, documented component class. Page-specific CSS overrides are a last resort and must be explicitly justified in a comment.

### Restrained Visual Hierarchy
IronkeepV2 uses a dark-native palette. Visual hierarchy is achieved through spacing, weight, and muted colour differentials — not gradients, shadows, borders, or animation. The UI should feel calm and functional, not decorative.

### No Visual Gimmicks
No CSS animations on operational data, no hover-reveal interactions for primary content, no decorative dividers or icons used purely for aesthetics. Interactions are functional or they are absent.

### No Frontend Framework Dependency
No React, Vue, Svelte, or equivalent. No Tailwind CSS. No PostCSS pipeline. CSS files are plain CSS consumed directly by the browser. Jinja2 macros and includes handle structural reuse.

### Preserve Testability
Every meaningful UI state must be assertable in pytest integration tests. Component classes are chosen partly for their test anchoring value — `.slot-card--assigned`, `.status-badge--ready`, `.tac-gap-badge--critical` — so tests can assert on CSS class presence rather than raw text.

### Consistency Across Surfaces
Dashboard widgets, tactical planner slot cards, composition previews, diagnostics panels, and the landing page all share the same token set, component naming conventions, and spacing rules. An officer moving between surfaces should never encounter a visually foreign page.

### Honest Product Presentation
The landing page and any public-facing copy must present IronkeepV2 accurately. No aspirational screenshots of features that do not exist. No generic SaaS copy. The product is a tactical guild management tool for Albion Online officers — this should be legible in every word and visual choice.

---

## UI Layer Architecture

### Planned CSS File Structure

All CSS will be extracted from `base.html` into purpose-oriented files served as static assets. The extraction is additive — files are introduced phase by phase without breaking existing pages.

```
app/static/css/
├── tokens.css          — Design tokens: colour, spacing, typography, elevation
├── base.css            — HTML reset, body, scrollbar, selection, focus ring
├── layout.css          — Page shell, header, nav, sidebar, content area, footer
├── components.css      — Shared UI components: cards, buttons, badges, forms, tables, nav
├── dashboard.css       — Dashboard-specific: metric cards, activity widgets, attention items
├── tactical.css        — Tactical planner: slot cards, party panels, role tallies, gap badges
├── tables.css          — Data table system: col utilities, sortable, sticky header
├── forms.css           — Form system: inputs, selects, labels, hints, validation states
├── responsive.css      — Breakpoint overrides and media query consolidation
└── utilities.css       — One-purpose helper classes: visibility, spacing, text, flex
```

### Load Order

Files must be loaded in dependency order:

```
tokens.css → base.css → layout.css → components.css
→ dashboard.css / tactical.css / tables.css / forms.css
→ utilities.css → responsive.css
```

`responsive.css` loads last so breakpoint overrides can refer to any component class. `utilities.css` loads before responsive so utilities can be overridden at breakpoints if needed.

### During Transition

While CSS lives in `base.html`, the monolithic block will be reorganised with labelled section comments matching the planned file names:

```css
/* ── tokens ───────────────────────────────────────── */
/* ── base ─────────────────────────────────────────── */
/* ── layout ───────────────────────────────────────── */
/* ── components ───────────────────────────────────── */
/* ── dashboard ────────────────────────────────────── */
/* ── tactical ─────────────────────────────────────── */
/* ── tables ───────────────────────────────────────── */
/* ── forms ────────────────────────────────────────── */
/* ── utilities ────────────────────────────────────── */
/* ── responsive ───────────────────────────────────── */
```

This allows the extraction phase to be mechanical — cut a section, paste into a file, update the `<link>` in `base.html`.

### What Stays in `base.html`

After full extraction, `base.html` retains only:
- The `<link>` tags loading all CSS files in order
- The `<nav>` and page shell HTML (which is not templated elsewhere)
- Flash message HTML that is tightly coupled to the base layout

---

## Design Token Strategy

All visual values that appear in more than one place must be CSS custom properties defined in `tokens.css` (or the `/* ── tokens */` section of `base.html` during the transition period). Hardcoded values that appear only once are acceptable but must be commented.

### Colour Tokens

#### Base Palette

```css
:root {
  --clr-bg-page:     #0f1117;   /* Page background — deepest dark */
  --clr-bg-surface:  #1a1e2a;   /* Card / panel background */
  --clr-bg-raised:   #222736;   /* Raised element (dropdown, popover) */
  --clr-bg-sunken:   #12151f;   /* Inset / input background */
  --clr-border:      #2e3347;   /* Default border */
  --clr-border-muted:#1e2235;   /* Subtle dividers */

  --clr-text-primary: #e8eaf0;  /* Primary readable text */
  --clr-text-muted:   #8b91a8;  /* Secondary / metadata text */
  --clr-text-faint:   #4a5068;  /* Placeholder, disabled, empty state */
  --clr-text-inverse: #0f1117;  /* Text on bright backgrounds */
}
```

#### Semantic Colour Tokens

```css
:root {
  --clr-accent:         #5b8dee;  /* Primary interactive accent (blue) */
  --clr-accent-hover:   #4a7be0;
  --clr-success:        #4caf7d;  /* Success, ready, assigned */
  --clr-success-muted:  #2d5e45;
  --clr-warning:        #e8a84c;  /* Warning, forming, missing builds */
  --clr-warning-muted:  #6b4a20;
  --clr-danger:         #e85c5c;  /* Danger, critical gap, not-ready */
  --clr-danger-muted:   #6b2020;
  --clr-info:           #5b8dee;  /* Informational (shares accent) */
  --clr-info-muted:     #1e2e5a;
  --clr-muted:          #4a5068;  /* Muted/neutral/inactive */
}
```

#### Tactical Role Colour Tokens

```css
:root {
  --role-tank:    #5b8dee;  /* Blue — tank / frontline */
  --role-healer:  #4caf7d;  /* Green — healer */
  --role-support: #a78bfa;  /* Purple — support / utility */
  --role-dps:     #e85c5c;  /* Red — DPS / melee / caller */
  --role-ranged:  #e8a84c;  /* Amber — ranged / mage / bow */
  --role-default: #8b91a8;  /* Muted — unclassified */
}
```

### Spacing Tokens

```css
:root {
  --space-1:  0.25rem;   /*  4px */
  --space-2:  0.5rem;    /*  8px */
  --space-3:  0.75rem;   /* 12px */
  --space-4:  1rem;      /* 16px */
  --space-5:  1.25rem;   /* 20px */
  --space-6:  1.5rem;    /* 24px */
  --space-8:  2rem;      /* 32px */
  --space-10: 2.5rem;    /* 40px */
  --space-12: 3rem;      /* 48px */
}
```

### Typography Tokens

```css
:root {
  --font-sans: system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "Cascadia Code", "Fira Code", ui-monospace, monospace;

  --text-xs:   0.7rem;    /* 11.2px — metadata, labels */
  --text-sm:   0.8rem;    /* 12.8px — secondary content */
  --text-base: 0.9rem;    /* 14.4px — body default */
  --text-md:   1rem;      /* 16px   — slightly emphasised */
  --text-lg:   1.15rem;   /* 18.4px — section headers */
  --text-xl:   1.35rem;   /* 21.6px — page titles */
  --text-2xl:  1.7rem;    /* 27.2px — hero headings */

  --weight-normal: 400;
  --weight-medium: 500;
  --weight-semi:   600;
  --weight-bold:   700;

  --leading-tight:  1.2;
  --leading-normal: 1.5;
  --leading-loose:  1.75;
}
```

### Elevation Tokens

```css
:root {
  --radius-sm:  4px;
  --radius-md:  6px;
  --radius-lg:  10px;

  --shadow-sm:  0 1px 3px rgba(0,0,0,0.4);
  --shadow-md:  0 2px 8px rgba(0,0,0,0.5);
  --shadow-lg:  0 4px 20px rgba(0,0,0,0.6);
}
```

### Token Rules

- **No hardcoded colour hex values outside tokens.css.** If a new colour is needed, add a token first.
- **No hardcoded pixel values for spacing inside component definitions.** Use `--space-*` tokens.
- **Font sizes in component definitions must reference `--text-*` tokens**, not raw `rem` or `px` values.
- **Role colours must come from `--role-*` tokens exclusively.** No hardcoded hex for role identity in any component or template.

---

## Component Taxonomy

All components are named using a flat BEM-inspired convention: `.component` for blocks, `.component__element` for sub-parts, `.component--modifier` for state variants. Tactical components use the `tac-` namespace prefix where they are exclusive to planning surfaces.

### Cards

| Class | Purpose |
|---|---|
| `.card` | Base surface container: background, border, border-radius, padding |
| `.card-header` | Top section of a card with title and optional actions |
| `.card-body` | Primary content area of a card |
| `.card-footer` | Bottom section with secondary actions or metadata |
| `.card--flat` | Card with no border or shadow — used for nested sub-panels |
| `.card--raised` | Card with elevated shadow — used for primary page sections |

### Metric Cards

| Class | Purpose |
|---|---|
| `.metric-card` | Compact KPI block: label, value, optional change indicator |
| `.metric-card__label` | Small muted label above the value |
| `.metric-card__value` | Large primary value |
| `.metric-card__change` | Signed delta indicator (positive/negative/neutral) |
| `.metric-card__fraction` | Secondary fraction display: e.g. "12/20" |

### Attention Items

| Class | Purpose |
|---|---|
| `.attention-item` | Flagged operational issue: icon, title, description, timestamp |
| `.attention-item--critical` | Red left accent — blocking issue |
| `.attention-item--warning` | Amber left accent — non-blocking issue |
| `.attention-item--info` | Blue left accent — informational notice |

### Slot Cards *(see Tactical UI Primitives)*

| Class | Purpose |
|---|---|
| `.slot-card` | Atomic tactical slot unit |
| `.slot-card__header` | Role label + slot index |
| `.slot-card__body` | Weapon-first build display + player name |
| `.slot-card__footer` | Assignment actions / inline edit / status |
| `.slot-card--assigned` | Green left accent — player assigned |
| `.slot-card--open-core` | Amber left accent — core priority, unfilled |
| `.slot-card--open` | Blue left accent — has signups, unfilled |
| `.slot-card--empty` | Muted left accent — no signups, unfilled |

### Party Panels *(see Tactical UI Primitives)*

| Class | Purpose |
|---|---|
| `.party-panel` | Party group container: header + summary + slot grid |
| `.party-panel__header` | Party title row with fill count and Quick Fill button |

### Role Tallies *(see Tactical UI Primitives)*

| Class | Purpose |
|---|---|
| `.role-tally` | Horizontal list of role-family count tokens |
| `.role-tally__item` | Single role count: `T:3`, `H:2`, etc. |
| `.role-tally__item--zero` | Dimmed variant for empty role families |

### Gap Badges *(see Tactical UI Primitives)*

| Class | Purpose |
|---|---|
| `.tac-gap-badge` | Inline tactical warning chip |
| `.tac-gap-badge--critical` | Red — missing role (no healer, no tank) |
| `.tac-gap-badge--warn` | Amber — non-critical issue (missing builds) |

### Tables

| Class | Purpose |
|---|---|
| `.data-table` | Base table: full-width, subtle row borders, dark rows |
| `.data-table th` | Header row: small caps, muted colour, sticky on scroll |
| `.data-table td` | Body cell: base text, controlled padding |
| `.col-meta` | Muted narrow column for secondary metadata |
| `.col-action` | Right-aligned column for row action buttons |
| `.table-wrap` | Horizontal scroll wrapper for wide tables |

### Buttons

| Class | Purpose |
|---|---|
| `.btn` | Base button: padding, border-radius, cursor, transition |
| `.btn-primary` | Filled accent colour — primary call to action |
| `.btn-secondary` | Outlined accent colour — secondary action |
| `.btn-danger` | Filled danger colour — destructive action |
| `.btn-muted` | Low-contrast text-only — tertiary / retire / archive |
| `.btn-sm` | Small button variant: reduced padding and font size |
| `.btn-xs` | Extra-small button variant: inline table actions |

### Navigation

| Class | Purpose |
|---|---|
| `.site-nav` | Top navigation bar container |
| `.nav-link` | Standard navigation item |
| `.nav-link--active` | Current page indicator |
| `.nav-group` | Section grouping within a sidebar nav |
| `.workspace-switcher` | Workspace selector within the nav |

### Forms

| Class | Purpose |
|---|---|
| `.form-group` | Vertical label + input + hint block |
| `.form-label` | Field label |
| `.form-control` | Text input, textarea, select |
| `.form-hint` | Muted helper text beneath a field |
| `.form-error` | Validation error message |
| `.inline-form` | Horizontal form layout for single-action forms |
| `.form-row` | Horizontal row of multiple form groups |

### Status Badges

| Class | Purpose |
|---|---|
| `.status-badge` | Base inline badge: background, text, border-radius |
| `.status-badge--success` | Green — ready / assigned / built |
| `.status-badge--warning` | Amber — forming / partial / unbuilt |
| `.status-badge--danger` | Red — not-ready / critical |
| `.status-badge--info` | Blue — informational |
| `.status-badge--muted` | Grey — archived / retired / inactive |
| `.status-badge--neutral` | Outline-only — no strong signal |

### Activity Widgets

| Class | Purpose |
|---|---|
| `.activity-widget` | Chronological activity feed container |
| `.activity-item` | Single activity row: icon, actor, action, timestamp |
| `.activity-item__meta` | Muted timestamp and secondary context |

### Empty States

| Class | Purpose |
|---|---|
| `.empty-state` | Centred full-area empty state container |
| `.empty-state__icon` | Optional large muted icon |
| `.empty-state__title` | Primary "nothing here" label |
| `.empty-state__body` | Supporting copy and suggestion |
| `.empty-state__action` | CTA button to resolve the empty state |

### Landing Page Sections

| Class | Purpose |
|---|---|
| `.landing-hero` | Full-width top hero: headline, sub-headline, CTA |
| `.landing-feature` | Feature row: icon + title + description |
| `.landing-section` | Generic content section with consistent vertical rhythm |
| `.landing-cta` | Standalone call-to-action block |
| `.landing-nav` | Public navigation bar (distinct from app `.site-nav`) |

---

## Layout Primitives

Layout primitives are structural classes that define how content is positioned on a page. They are not visual components — they provide no colour, border, or typography. They only control dimension, position, and flow.

### Page Shell

```
.page-shell              — outermost page wrapper; flex column; min-height: 100vh
.page-header             — top nav bar; fixed or sticky depending on context
.page-content            — main content area below the header
.page-sidebar            — optional left sidebar within .page-content
.page-main               — primary content column; grows to fill remaining space
.page-footer             — optional footer row
```

### Content Layout

```
.content-width           — max-width constraint (e.g. 1200px) centered with horizontal margin
.content-width--narrow   — narrower constraint for focused views (e.g. 800px)
.content-width--wide     — wider constraint for data-heavy views (e.g. 1440px)
```

### Grid Primitives

```
.two-col-grid            — 2-column responsive grid; collapses to 1 column on mobile
.three-col-grid          — 3-column responsive grid; collapses at tablet and mobile
.metric-grid             — Auto-fit metric card grid; min column 160px
.sidebar-layout          — Fixed sidebar + fluid main: sidebar on left, main fills rest
```

### Flex Primitives

```
.flex-row                — flex; flex-direction: row; align-items: center
.flex-col                — flex; flex-direction: column
.flex-between            — flex-row; justify-content: space-between
.flex-end                — flex-row; justify-content: flex-end
.flex-wrap               — flex-row; flex-wrap: wrap; gap: var(--space-2)
.flex-gap-sm             — gap: var(--space-2) on a flex container
.flex-gap-md             — gap: var(--space-4) on a flex container
```

### Stack Primitives

```
.stack                   — flex column with gap — generic vertical stacking primitive
.stack--sm               — gap: var(--space-2)
.stack--md               — gap: var(--space-4)
.stack--lg               — gap: var(--space-8)
```

---

## Tactical UI Primitives

Tactical UI primitives are components exclusive to the planner and composition surfaces. They live in `tactical.css` and use the `tac-` prefix for context-specific utilities. Core block components (`slot-card`, `party-panel`) do not use the prefix — they are named by their domain role.

### Slot Card

The atomic planning unit. Represents a single roster slot in a composition or operation.

```
.slot-card               — block container; left-border accent by state; min-height; border-radius
.slot-card__header       — role label (left) + slot index (right)
.slot-card__role         — role name text; coloured by [data-role] attribute
.slot-card__idx          — slot number + core marker (●)
.slot-card__body         — weapon-first build identity; player name
.slot-card__weapon       — primary build identity: weapon_name; truncated with ellipsis
.slot-card__weapon--empty — muted "No build" indicator
.slot-card__build        — secondary build label (build_name, if different from weapon_name)
.slot-card__player       — assigned player name; truncated
.slot-card__footer       — action row: assign / edit build / status messages
.slot-card--assigned     — state: player assigned (green accent)
.slot-card--open-core    — state: core priority, unfilled (amber accent)
.slot-card--open         — state: has signups, unfilled (blue accent)
.slot-card--empty        — state: no signups, unfilled (muted accent)
```

Data attributes:
- `data-role="tank|healer|support|dps|ranged|default"` — drives `[data-role]` CSS colour rules for role label and header accent border.

Role family is always precomputed by `tactical.role_family()` in the route handler. Templates must never re-derive it.

### Party Panel

Contains the party header, summary strip, and slot card grid for one party.

```
.party-panel             — card-like container for a single party group
.party-panel__header     — party name row; fill count badge; optional Quick Fill button
```

Slot card grids within party panels use `.slot-card-grid` (below).

### Slot Card Grid

```
.slot-card-grid          — CSS Grid container; auto-fill columns; min 140px
```

Collapses to 2 columns at tablet, 1 column at mobile.

### Role Tally

Compact horizontal list of role-family counts. Appears in party summary strips and composition overview.

```
.role-tally              — inline-flex row; gap; small font
.role-tally__item        — single count token: "T:3"; coloured by [data-role]
.role-tally__item--zero  — dimmed variant for zero-count families
```

### Tactical Gap Badge

Inline chip signalling a tactical deficiency in a party or composition.

```
.tac-gap-badge           — base chip: small font, border-radius, padding
.tac-gap-badge--critical — red background; ⚠ prefix; missing role (no healer, no tank)
.tac-gap-badge--warn     — amber background; missing builds
```

### Composition Overview Strip

Full-composition role distribution bar shown above the party panels in the planner and on the composition detail page.

```
.comp-overview           — horizontal strip: role tally (left) + continuation hint (right)
```

### Weapon-First Build Display

Within `.slot-card__body`, weapon name takes visual priority over build name. If `weapon_name` is set, it renders as `.slot-card__weapon`. `build_name` renders as `.slot-card__build` only if it differs and is not empty.

The logic is precomputed in the route handler. Templates must not re-derive whether to display weapon vs. build label.

### Role-Family Colour System

All role identity colour in templates comes from:
1. The `data-role` attribute on `.slot-card` and `.role-tally__item`.
2. The `[data-role]` CSS selector in `tactical.css` targeting `--role-*` tokens.
3. Never from inline `style` attributes or hardcoded class names.

```css
/* Example rule — lives in tactical.css */
[data-role="tank"]   { color: var(--role-tank); }
[data-role="healer"] { color: var(--role-healer); }
/* etc. */
```

### Tactical Continuation Hints

The `comp_summary.hint` string computed by `tactical.derive_tactical_summaries()` is shown in the `.comp-overview` strip. The `hint_state` value ("ok", "warn", "neutral") drives the hint's text colour.

Templates render the precomputed hint string and apply the CSS class based on `hint_state`. They do not evaluate tactical state themselves.

```
.tac-hint                — hint text container
.tac-hint--ok            — success colour; "All slots built and assigned"
.tac-hint--warn          — warning colour; missing builds or unassigned players
.tac-hint--neutral       — muted; no slots defined yet
```

---

## State / Status System

IronkeepV2 surfaces operational state across all pages — operations, slots, assignments, rosters, builds, compositions. The state/status system defines the canonical visual language for each state and applies identically across all surfaces via `.status-badge` and semantic colour tokens.

### Status States

| State | CSS Modifier | Colour Token | Meaning |
|---|---|---|---|
| `success` | `--success` | `--clr-success` | Action completed; slot filled; build confirmed |
| `warning` | `--warning` | `--clr-warning` | Attention needed; forming; partial completion |
| `danger` | `--danger` | `--clr-danger` | Critical issue; operation not ready; blocking gap |
| `info` | `--info` | `--clr-info` | Informational; neutral notice |
| `muted` | `--muted` | `--clr-muted` | Inactive; archived; secondary metadata |
| `neutral` | `--neutral` | `--clr-border` | No strong signal; default |
| `empty` | `--empty` | `--clr-text-faint` | Nothing present; empty state |

### Slot / Assignment States

| State | Left-border | Meaning |
|---|---|---|
| `assigned` | `--clr-success` | Slot has an active player assignment |
| `open-core` | `--clr-warning` | Core priority slot; no assignment yet |
| `open` | `--clr-accent` | Has signups available; not yet assigned |
| `empty` | `--clr-border` | No signups; unfilled |

### Build States

| State | Rendered as | Meaning |
|---|---|---|
| `built` | `.status-badge--success` | `build_name` or `weapon_name` is set |
| `unbuilt` | `.slot-card__weapon--empty` / `.status-badge--warning` | No build defined on the slot |

### Operation States

| State | Rendered as | Meaning |
|---|---|---|
| `ready` | `.status-badge--success` | Operation is confirmed ready |
| `forming` | `.status-badge--warning` | Operation is being assembled |
| `not-ready` | `.status-badge--danger` | Operation has critical unresolved issues |
| `archived` | `.status-badge--muted` | Operation is closed / past |

### Composition States

| State | Rendered as | Meaning |
|---|---|---|
| `active` | `.status-badge--success` or no badge | Composition is in active use |
| `retired` | `.status-badge--muted` | Composition is retired / no longer used |

### Wording Rules

The following canonical terms are used across all surfaces. No synonyms.

| Concept | Canonical term |
|---|---|
| Slot has a player | "Assigned" |
| Slot has no player | "Unassigned" |
| Slot has a build set | "Built" |
| Slot has no build | "No build" |
| Composition is ready for use | "Ready" |
| Composition is being assembled | "Forming" |
| Operation confirmed | "Ready" |
| Operation being assembled | "Forming" |
| Composition no longer in use | "Retired" |
| Operation closed | "Archived" |
| Tactical role gap | "No [role]" (e.g. "No healer") |
| Build missing | "N no builds" / "1 no build" |

Officers must never encounter the same concept described with different words on different pages.

---

## Typography Rules

1. **Page titles** (`<h1>`) use `--text-xl` or `--text-2xl`, `--weight-semi`, `--clr-text-primary`.
2. **Section headings** (`<h2>`) use `--text-lg`, `--weight-semi`.
3. **Panel/card headings** (`<h3>`) use `--text-md`, `--weight-medium`.
4. **Sub-headings** (`<h4>`) use `--text-base`, `--weight-medium`, often `--clr-text-muted`.
5. **Body text** uses `--text-base`, `--weight-normal`, `--leading-normal`.
6. **Metadata / secondary labels** use `--text-sm`, `--clr-text-muted`.
7. **Microlabels / column headers** use `--text-xs`, `--weight-medium`, `letter-spacing: 0.04em`, `text-transform: uppercase`.
8. **Monospace content** (IDs, keys, timestamps) uses `--font-mono`, `--text-sm`.
9. **No `em`-based font sizes in component definitions.** All component font sizes reference `--text-*` tokens.
10. **No decorative typefaces.** The system font stack (`--font-sans`) is the only permitted body typeface.
11. **Link styling:** underline on hover only; colour inherits from context (`--clr-accent` for standalone links).

---

## Spacing / Density Rules

IronkeepV2 is a tactical planning tool used under time pressure. The default density is **medium-compact** — enough whitespace to separate information clearly, but not enough to require scrolling past empty space.

### Density Levels

| Level | Where used | Description |
|---|---|---|
| Compact | Slot cards, role tallies, gap badges, table rows | Minimal padding; content fills the space |
| Default | Cards, forms, metric grids, panels | Standard readable padding |
| Relaxed | Landing page sections, onboarding, empty states | More generous vertical rhythm |

### Padding Rules

- **Card body default:** `var(--space-4)` (16px)
- **Compact card body (e.g. `.party-panel__header`):** `var(--space-2) var(--space-3)` (8px/12px)
- **Button default:** `var(--space-2) var(--space-4)` (8px/16px)
- **Button small:** `var(--space-1) var(--space-3)` (4px/12px)
- **Table cell:** `var(--space-2) var(--space-3)` (8px/12px)
- **Form group gap:** `var(--space-2)` between label and input, `var(--space-4)` between groups

### Gap Rules

- **Between metric cards:** `var(--space-4)`
- **Between slot cards:** `var(--space-2)` to `var(--space-3)`
- **Between party panels:** `var(--space-6)`
- **Between dashboard sections:** `var(--space-8)`
- **Between landing sections:** `var(--space-12)`

### Density Anti-Patterns

- Do not use `padding: 2rem` on slot cards or tactical components.
- Do not add `margin-top: 2rem` between every heading and its content.
- Do not use `line-height: 2` on dense data displays.
- Do not add decorative whitespace between data cells in tables.

---

## Accessibility Rules

IronkeepV2 targets professional desktop users on modern browsers. Full WCAG AA compliance is the goal for interactive elements; best-effort for read-only surfaces.

### Colour Contrast

- All text on dark backgrounds must meet 4.5:1 contrast ratio (WCAG AA).
- Large text (18px+ or 14px+ bold) must meet 3:1 contrast ratio.
- Interactive elements (buttons, links) must meet 3:1 against their background.
- Role colour tokens (`--role-*`) are used for accent/identity only — role labels must always be accompanied by the role name text, not colour alone.

### Focus Rings

- All interactive elements must have a visible `:focus-visible` ring.
- Default ring: `outline: 2px solid var(--clr-accent); outline-offset: 2px`.
- No `outline: none` without an equivalent visible replacement.

### Semantic HTML

- Each party group uses `<section aria-label="Party N">`.
- The slot card grid uses `<ul>` / `<li>` structure for list semantics.
- All interactive slot elements are `<button>` or `<a>` — no `<div>` click handlers.
- Heading hierarchy is strict: `<h1>` page title, `<h2>` section, `<h3>` party/panel, `<h4>` sub-section.
- Status badges include a visually hidden label when colour alone conveys meaning.
- Form inputs have associated `<label>` elements — no placeholder-as-label patterns.

### Keyboard Navigation

- All interactive elements are keyboard reachable in logical tab order.
- Inline `<details>` disclosures (slot build edit, manual assign) are keyboard operable via native browser behaviour.
- No keyboard traps.

### ARIA

- Use ARIA roles only when semantic HTML is insufficient.
- `aria-label` on icon-only buttons.
- `aria-live="polite"` on flash message regions.
- Do not use `aria-hidden` on content that is keyboard-focusable.

---

## Responsive Rules

### Breakpoints

```css
/* Mobile:  < 640px   — review mode; editing is degraded-acceptable */
/* Tablet:  640–1024px — full composition review; editing acceptable with constraints */
/* Desktop: > 1024px   — primary planning environment */

@media (max-width: 1024px) { /* tablet */ }
@media (max-width: 640px)  { /* mobile */ }
```

### Mobile-First vs Desktop-First

IronkeepV2 uses a **desktop-first** approach. Base styles are written for the 1024px+ desktop environment. `max-width` media queries override for tablet and mobile.

Rationale: the planner is a desktop tool. Officers do not plan 20-man compositions on a phone. Mobile is read-only review mode. Designing base styles mobile-first would add unnecessary complexity for the primary use case.

### Responsive Behaviour by Surface

| Surface | Desktop | Tablet | Mobile |
|---|---|---|---|
| Dashboard | 3-col metric grid; sidebar visible | 2-col metric grid; sidebar collapses | 1-col stacked |
| Tactical Planner | Multi-party side-by-side; full slot card grid | Party panels stack vertically | Party panels stack; slot cards narrow |
| Composition List | Full table with all columns | Hide "Role mix" column | Table scrolls horizontally |
| Composition Detail | Party panels in row | Party panels stack | Party panels stack; slot cards 1-col |
| Forms | Side-by-side field rows | Single column | Single column |
| Landing Page | Hero + feature grid | Hero + stacked features | Hero + stacked; text-only |

### Rules

- No horizontal scrolling on the desktop viewport (1280px+).
- Slot card grids collapse to 2 columns at tablet, 1 column at mobile.
- Tables with many columns use `.table-wrap` for horizontal scroll on narrow viewports.
- Navigation collapses to a hamburger or simplified list on mobile.
- Font sizes do not increase on mobile — the compact scale is appropriate across all viewports.
- Media queries live exclusively in `responsive.css` (or the `/* ── responsive */` section of `base.html` during transition). No scattered `@media` blocks inside component definitions.

---

## CSS Organisation Plan

### Current State

All CSS (~1,000+ lines) lives in a `<style>` block inside `base.html`. There are no static CSS files. This is the starting point for the extraction phases.

### Target State

```
app/static/css/
├── tokens.css
├── base.css
├── layout.css
├── components.css
├── dashboard.css
├── tactical.css
├── tables.css
├── forms.css
├── responsive.css
└── utilities.css
```

`base.html` references these files via `<link rel="stylesheet">` in dependency order. No inline `<style>` block remains.

### Section Comment Convention (Pre-Extraction)

During the transition, sections of `base.html`'s `<style>` block are labelled:

```css
/* ═══════════════════════════════════════════════════════════════
   tokens — design tokens (colour, spacing, typography, elevation)
   ═══════════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════
   base — reset, body, scrollbar, selection, focus ring
   ═══════════════════════════════════════════════════ */

/* ══════════════════════════════════════════════════
   layout — page shell, header, nav, content, sidebar
   ══════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════
   components — cards, buttons, badges, forms, nav, empty states
   ═══════════════════════════════════════════════════════════════ */

/* ══════════════════════════════════════════
   dashboard — metric cards, activity widgets
   ══════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════════
   tactical — slot cards, party panels, role tallies, gap badges
   ═══════════════════════════════════════════════════════════════════ */

/* ════════════════════════════════════
   tables — data-table, col utilities
   ════════════════════════════════════ */

/* ════════════════════════
   forms — form system
   ════════════════════════ */

/* ════════════════════════════════
   utilities — spacing, text, flex
   ════════════════════════════════ */

/* ═══════════════════════════════════════════════════
   responsive — breakpoint overrides (all at the end)
   ═══════════════════════════════════════════════════ */
```

### Naming Rules

- **Block classes:** lowercase kebab-case (`.slot-card`, `.metric-card`, `.data-table`)
- **Element classes:** BEM double-underscore (`.slot-card__header`, `.metric-card__value`)
- **Modifier classes:** BEM double-dash (`.slot-card--assigned`, `.btn--primary`)
- **Tactical namespace:** `tac-` prefix for tactical-only utilities not part of a named block (`.tac-gap-badge`, `.tac-hint`)
- **Utility classes:** descriptive single-purpose (`.text-muted`, `.mt-4`, `.flex-between`)
- **No camelCase in CSS class names.**
- **No ID selectors for styling** (IDs are for JavaScript anchors and `aria` references only).

---

## Template / Include Strategy

### Current State

`operation_planner.html` and `compositions_detail.html` duplicate the structural HTML for:
- The composition overview strip (`.comp-overview`)
- The party summary strip (`.party-summary`)
- The slot card grid and individual slot cards

There are no shared Jinja2 includes or macros. Each template manages its own copy.

### Target State

High-duplication structural blocks are extracted into Jinja2 macros or template includes under `app/templates/includes/`.

```
app/templates/includes/
├── _slot_card.html          — slot card macro: renders one slot card
├── _party_panel.html        — party panel macro: renders one party (header + summary + grid)
├── _comp_overview.html      — comp overview strip: role tally + hint
├── _role_tally.html         — role tally strip: reusable across planner and detail
├── _flash_messages.html     — flash success/error message block
├── _empty_state.html        — parameterised empty state block
└── _status_badge.html       — status badge macro: text + modifier
```

### Macro Design Rules

- Macros receive pre-computed data only — they never derive tactical meaning.
- Macros do not call Python or perform any computation.
- Macros are imported at the top of templates that use them: `{% from 'includes/_slot_card.html' import slot_card %}`.
- Macro parameters are documented with a comment block inside the macro file.
- Macros are kept small — if a macro requires more than 5 parameters, the calling route should build a context object and pass it as a single argument.

### Flash Message Strategy

All flash messages use a shared `_flash_messages.html` include. The include reads `?error=` and `?success=` query parameters passed from the route context. Templates do not implement their own flash rendering.

### Page-Specific HTML

Structural HTML that is genuinely unique to a single page (e.g. the operation detail event timeline) remains in the page template and is not extracted. Only patterns that appear on 2+ pages warrant extraction.

---

## Testing Strategy

The UI architecture must remain testable through the existing pytest integration test suite. No visual regression tool (Playwright screenshot comparison, etc.) is required.

### CSS Class Anchoring

Component CSS classes serve as stable test anchors. Tests assert on class presence, not on text content or computed styles.

```python
# Good: anchored to component class
assert 'class="slot-card slot-card--assigned"' in response.text

# Acceptable: anchored to canonical vocabulary
assert "No healer" in response.text

# Fragile: anchored to arbitrary text that might change
assert "This slot has no assigned player yet" in response.text
```

### Required Test Coverage for Each Component

When a new component class is introduced or modified, the corresponding page integration tests must verify:

1. The component renders at all (class present in response).
2. All expected state variants render in the correct conditions.
3. The "empty" state renders when no data is present.
4. Interactive elements (forms, buttons) submit correctly and produce the expected redirect.

### Shared Macro Tests

When a Jinja2 macro is introduced (`_slot_card.html`, `_party_panel.html`), at least one integration test for each page that uses the macro must remain passing. The macro must not silently remove expected content.

### Regression Baselines

Before extracting CSS from `base.html` into separate files (Phase 2), a baseline test run must pass. After each file extraction, the full test suite must pass before the next extraction begins. CSS extraction should never change rendered HTML structure — only the delivery mechanism changes.

### Token Changes

Changes to design token values (colours, spacing, typography) do not require new tests but must be reviewed against WCAG contrast requirements before merging.

---

## Implementation Phases

### Phase 1 — UI Inventory / Audit

**Goal:** Understand the current state before changing anything.

- [x] Audit `base.html` inline CSS: count lines, identify sections, estimate duplicated rules
- [x] Audit component class names in use across all templates: document all `.data-table`, `.card`, `.metric-card`, `.slot-card`, `.btn-*` occurrences
- [x] Identify all hardcoded colour hex values outside `:root` tokens
- [x] Identify all hardcoded pixel values for spacing in component definitions
- [x] Identify all responsive `@media` blocks and their locations
- [x] Identify all structural HTML duplications across templates
- [x] Produce an audit report listing: token gaps, naming inconsistencies, duplication candidates, hardcoded value count
- [x] Run full test suite as a baseline before any changes

---

### Phase 1 Audit Report

> Completed: 2026-05-18. Baseline test result: **1493 passed, 0 failed.**
> No CSS, templates, or classes were modified during this phase.

---

#### A. CSS Scale and Structure

**`base.html` inline `<style>` block: 1,441 lines** (total file: 1,485 lines).
The entire CSS surface of IronkeepV2 lives in a single monolithic inline block.
No `app/static/` directory exists. No external CSS files exist.

**Existing informal section labels** (present but not standardised):

| Lines (approx.) | Current label | Maps to planned file |
|---|---|---|
| 14–98 | Design Tokens | `tokens.css` |
| 100–120 | Reset + Base | `base.css` |
| 122–127 | Headings | `base.css` |
| 128–165 | Layout helpers | `layout.css` |
| 150–303 | Dashboard layout + metric cards + attention list + summary metrics | `dashboard.css` |
| 287–412 | Dashboard hierarchy, page-header, summary-strip | `dashboard.css` |
| 413–466 | Global nav, workspace nav | `layout.css` |
| 468–502 | Cards and panels | `components.css` |
| 505–556 | Tables | `tables.css` |
| 558–603 | Forms | `forms.css` |
| 605–651 | Buttons | `components.css` |
| 653–728 | Alerts + Badges (34 variants) | `components.css` |
| 730–760 | Scheduler status table | `dashboard.css` or `tables.css` |
| 762–801 | Utility classes + account page | `utilities.css` / `components.css` |
| 803–822 | Discord embed mock | `components.css` |
| 824–854 | Operation tabs | `components.css` |
| 848–884 | Timeline | `components.css` |
| 886–915 | Planner UX (readiness bar, gap pills, fill count) | `tactical.css` |
| 916–986 | Tactical Phase 5 (comp-overview, party-summary, role-tally, tac-gap-badge) | `tactical.css` |
| 988–1013 | Signup cards | `components.css` |
| 1015–1062 | Slot build-edit + manual-assign disclosures | `tactical.css` |
| 1063–1204 | Slot card system (Phase 2–3) | `tactical.css` |
| 1205–1235 | Discord preview collapsibles | `components.css` |
| 1237–1257 | Planner layout grid + op status accent | `tactical.css` / `layout.css` |
| 1259–1283 | Phase 7 utility consolidation (col-meta, btn-muted, metric-card__fraction) | `utilities.css` |
| 1284–1329 | Activity list widget | `dashboard.css` |
| 1331–1434 | Responsive media queries | `responsive.css` |
| 1436–1446 | Dev-mode warning banner | `base.css` |

**Largest destination buckets by estimated line count:**
- `tactical.css`: ~280 lines
- `components.css`: ~260 lines (alerts + badges + cards + discord + timeline)
- `dashboard.css`: ~220 lines
- `tables.css`: ~55 lines
- `forms.css`: ~55 lines
- `layout.css`: ~90 lines
- `tokens.css`: ~85 lines
- `base.css`: ~35 lines
- `utilities.css`: ~30 lines
- `responsive.css`: ~110 lines

---

#### B. Design Token Audit

**Existing tokens (complete):**
- Background surface hierarchy: `--bg`, `--surface`, `--surface-2`, `--surface-3` ✓
- Border: `--border`, `--border-strong` ✓
- Text: `--text`, `--text-muted`, `--text-faint` ✓
- Accent: `--accent`, `--accent-hover`, `--accent-dim` ✓
- Semantic: `--success-*`, `--warning-*`, `--danger-*`, `--info-*` (full bg/border/text groups) ✓
- Role families: `--role-tank`, `--role-healer`, `--role-support`, `--role-dps`, `--role-ranged` ✓
- Spacing: `--space-1` through `--space-6` ✓
- Layout widths: `--max-width-narrow`, `--max-width`, `--max-width-wide` ✓
- Elevation: `--radius`, `--radius-lg`, `--shadow`, `--shadow-md` ✓

**Token gaps identified:**

| Gap | Detail | Priority |
|---|---|---|
| `--radius-sm` used but not defined | `tac-gap-badge` uses `var(--radius-sm)` — token is referenced but absent from `:root`; browser falls back to `initial` | **Critical** — fix in Phase 3 |
| `--role-default` missing | `app/tactical.py` returns `"default"` as a family; there is no `--role-default` CSS token; `data-role="default"` has no colour rule | Medium |
| `--space-7` through `--space-12` absent | The architecture plan defines `--space-8` through `--space-12`; the codebase only goes to `--space-6` | Low — add in Phase 3 |
| Typography tokens absent | No `--text-*` or `--weight-*` CSS custom properties; all font sizes are raw `rem` values | Medium — formalise in Phase 3 |
| `--nav-bg`, `--nav-text`, `--nav-muted` exist but aren't in planned token taxonomy | Nav tokens are functional but not documented in the architecture token strategy | Low |
| Legacy `--error-bg`, `--error-border`, `--error-text` aliases | Live in `:root` for template compatibility; not referenced in the architecture doc | Cleanup |

**Hardcoded hex values outside `:root`** (colours that should be tokens):

| Location | Value | Should become |
|---|---|---|
| `.global-nav` border-bottom | `#21262d` | `--border` or new `--nav-border` token |
| `.global-nav .brand` color | `#e6edf3` | `var(--nav-text)` |
| `.global-nav .sep` | `#30363d` | `var(--border)` |
| `.data-table tr.row-assigned` | `#0a1f10` | `var(--success-bg)` |
| `.data-table tr.row-open` | `#0c1a30` | `var(--info-bg)` |
| `.data-table tr.row-unmarked-attendance` | `#1a1400` | `var(--warning-bg)` |
| `.btn-primary` text color | `#0d1117` | `var(--bg)` |
| `.badge-core` | `#201800`, `#d4a017`, `#4a3800` | New `--core-*` tokens |
| `.badge-support` | `#0a2018`, `#34c4a8`, `#1a4838` | New `--teal-*` tokens or alias |
| `.discord-embed` | `#4f545c`, `#2b2d31`, `#dbdee1` | Discord-specific tokens |
| `[data-op-status]` accent values | 5 hardcoded hex values | Token aliases using existing semantic tokens |
| `.dev-banner` | `#5a2000`, `#ffcf88`, `#7a3800` | Dev-specific tokens (low priority) |
| `base.html` nav account link | `color:var(--nav-muted)` in inline style | Move to CSS class |

**Total hardcoded hex count outside `:root` CSS rules: ~25 values.**
These are all in `base.html` CSS — not in templates (templates use `var()` correctly).

---

#### C. Typography Audit

**27 unique font-size values** are in use in `base.html`:

```
0.6rem  0.65em  0.68rem  0.7rem  0.72rem  0.73rem  0.75rem  0.775rem
0.78rem  0.8rem  0.8125rem  0.85rem  0.875rem  0.88rem  0.9rem  0.9375rem
0.95rem  1rem  1.05rem  1.1rem  1.2rem  1.25rem  1.5rem
```

The planned token scale (`--text-xs` through `--text-2xl`) has 7 sizes. The audit reveals **the codebase uses significantly more steps** than the planned scale. The Phase 3 token formalisation must consolidate these into the canonical scale and tolerate minor rounding — or define a wider scale.

**Key clusters:**
- `~0.7rem` range: 5 values (`0.6`, `0.65`, `0.68`, `0.7`, `0.72`, `0.73`) — consolidate to `--text-xs` (`0.7rem`)
- `~0.8rem` range: 5 values (`0.775`, `0.78`, `0.8`, `0.8125`, `0.85`) — consolidate to `--text-sm` (`0.8rem`)
- `~0.875rem` range: 3 values (`0.875`, `0.88`) — consolidate to existing body-sub size
- `~0.9rem` range: 3 values (`0.9`, `0.9375`, `0.95`) — body default range
- `1rem+` range: 4 values (`1.0`, `1.05`, `1.1`, `1.25`) — section heading range

**No `--weight-*` or `--leading-*` tokens exist** — these are all raw values (`font-weight: 600`, `line-height: 1.5`).

---

#### D. Spacing Audit

The existing `--space-1` through `--space-6` scale covers `0.25rem–2rem`. There are approximately **42 hardcoded `rem`/`px` spacing values** outside this scale in component definitions within `base.html`. Common offenders:

- `0.15rem`, `0.1em`, `0.2rem` — sub-grid micro-spacing (no token exists)
- `0.3rem`, `0.35rem` — between `--space-1` and `--space-2` (no token)
- `0.4rem`, `0.45rem` — near `--space-2` (should alias to `--space-2`)
- `0.6rem`, `0.7rem` — between `--space-2` and `--space-3`
- `3.5rem` — used for sticky planner offset (no token)
- `4rem`, `8rem` — specific layout constraints (acceptable as one-offs)

The spacing scale needs `--space-0` (0.125rem for micro-gaps) and the `--space-7` / `--space-8` additions planned in the architecture. Most sub-`--space-1` values are acceptable as one-offs in component definitions.

---

#### E. Responsive Architecture Audit

**Five `@media` blocks identified:**

| Line | Breakpoint | Type | Purpose |
|---|---|---|---|
| 146 | `max-width: 900px` | max-width | `.layout-two-col` collapse |
| 160 | `max-width: 960px` | max-width | `.dashboard-grid` collapse |
| 1238 | `min-width: 960px` | **min-width** | Planner columns layout |
| 1343 | `max-width: 768px` | max-width | Tablet overrides (comprehensive) |
| 1406 | `max-width: 480px` | max-width | Phone overrides |

**Issues found:**

1. **Inconsistent breakpoint values**: Three different breakpoints in the 900–960px range (`900px`, `960px`, `960px` min-width). The architecture defines `1024px` as the tablet breakpoint. The codebase uses `768px`. These are misaligned — the architecture document's breakpoints need updating to match reality, or the media queries need normalisation to `1024px` / `640px`.

2. **Mixed min/max-width strategy**: Line 1238 uses `min-width: 960px` for the planner layout (mobile-first exception). All others use `max-width` (desktop-first). This inconsistency is intentional (planner uses `min-width` so the 2-column layout is opt-in on wide screens) but should be documented as deliberate.

3. **Breakpoints scattered inside component sections**: The `@media (max-width: 900px)` block at line 146 is inside the layout section, and `@media (max-width: 960px)` at line 160 is also inside the layout section — both before the main responsive block at line 1331. Phase 2 must consolidate all `@media` blocks into the `responsive.css` section.

4. **No breakpoint for the slot-card grid at 1024px**: The grid switches from 140px-min to 120px-min at 768px, and to 2-col fixed at 480px. A 1024px intermediate step may be needed for the planner on mid-range tablets.

5. **`dashboard-grid` collapses at 960px** but workspace nav collapses padding at 768px — these are not coordinated breakpoints.

**Conclusion:** The responsive foundation is functional but uses 5 different breakpoints across the file. Phase 2 must normalise these to a maximum of 3 canonical values: `1024px`, `768px`, `480px`.

---

#### F. Component Inventory

**Template count: 25** (including `base.html`, includes like `flash_messages.html`, `workspace_nav.html`, `page_header.html`, `operation_tabs.html`, `_discord_macros.html`).

**Most component-rich templates:**
- `workspace_dashboard.html` — 69 component class references
- `operation_planner.html` — 68 component class references
- `operation_detail.html` — 47 references
- `compositions_detail.html` — 41 references

**Component class inventory:**

| Component | CSS Class(es) | Templates using it |
|---|---|---|
| Card | `.card`, `.card-header`, `.card-body`, `.card--compact` | ~18 templates |
| Button | `.btn`, `.btn-primary`, `.btn-danger`, `.btn-sm`, `.btn-muted`, `.btn-ghost`, `.btn-publish`, `.btn-lock`, `.btn-complete`, `.btn-archive` | ~20 templates |
| Badge | `.badge` + 34 `badge-*` variants | ~15 templates |
| Data table | `.data-table`, `.table-wrap` | ~8 templates |
| Alert | `.alert`, `.alert-error`, `.alert-success`, `.alert-info`, `.alert-warning` | ~10 templates |
| Form | `.form-group`, `.form-hint`, `.form-actions`, `.action-bar`, `.inline-form` | ~15 templates |
| Metric card | `.metric-card`, `.metric-card__value`, `.metric-card__label`, `.metric-card__sub`, `.metric-card__fraction` | `workspace_dashboard.html` |
| Attention item | `.attention-list`, `.attention-item`, `.attention-item__count`, `.attention-item__body` | `workspace_dashboard.html` |
| Activity widget | `.activity-list`, `.activity-item`, `.activity-item__event`, `.activity-item__op`, `.activity-item__meta` | `workspace_dashboard.html` |
| Stat grid | `.stat-grid`, `.stat-item` | `workspace_dashboard.html` |
| Slot card | `.slot-card`, `.slot-card__header`, `.slot-card__body`, `.slot-card__footer` + state/element variants | `operation_planner.html`, `compositions_detail.html` |
| Party panel | `.party-panel`, `.party-panel__header` | `operation_planner.html`, `compositions_detail.html` |
| Role tally | `.role-tally`, `.role-tally__item`, `.role-tally__item--zero` | `operation_planner.html`, `compositions_detail.html`, `compositions_list.html` |
| Comp overview | `.comp-overview` | `operation_planner.html`, `compositions_detail.html` |
| Party summary | `.party-summary` | `operation_planner.html`, `compositions_detail.html` |
| Gap badge | `.tac-gap-badge`, `.tac-gap-badge--critical`, `.tac-gap-badge--warn` | `operation_planner.html`, `compositions_detail.html` |
| Timeline | `.timeline-list`, `.timeline-entry`, `.timeline-time`, `.timeline-body`, `.timeline-label`, `.timeline-meta` | `operation_timeline.html` |
| Signup cards | `.signup-cards`, `.signup-card` | `operation_signup.html`, `operation_planner.html` |
| Readiness bar | `.readiness-bar`, `.gap-pills`, `.gap-pill` | `operation_planner.html` |
| Operation tabs | `.op-tabs` | `operation_tabs.html` |
| Empty state | `.empty-state` (generic utility only — no shared macro) | Many templates (ad-hoc) |
| Scheduler table | `.sched-table` | `workspace_diagnostics.html`, `workspace_scheduler_status.html` |
| Discord embed | `.discord-embed` + sub-elements | `operation_detail.html`, `operation_planner.html` |

**Badge proliferation**: 34 `.badge-*` variants. This is the largest single namespace. Variants span: operation readiness, lifecycle, signup state, attendance, auth provider, specialty role, timeline group, scheduler status — all using the same `.badge` base with different colour rules. This is correct architecturally but means the components.css badge section will be substantial (~80 lines).

---

#### G. Inline Style / One-Off Layout Hack Audit

**Total inline `style=""` instances: ~210 across 19 templates.**
`account.html` and `operation_ledger.html` are the most heavily inline-styled templates.

**High-frequency inline style patterns** (should become utility classes or component modifiers):

| Pattern | Approx. count | Recommended resolution |
|---|---|---|
| `style="margin-top: Xrem"` | ~25 | `.mt-3`, `.mt-4` utility classes |
| `style="font-size: 0.Xrem"` | ~30 | `.text-sm`, `.text-xs` utility classes |
| `style="color: var(--text-muted)"` | ~15 | `.text-muted` (already exists) |
| `style="color: var(--danger-text)"` | ~8 | `.text-danger` (already exists — just not used) |
| `style="display:flex;align-items:center;gap:Xrem"` | ~15 | `.flex-row.flex-gap-sm` / `.cluster` (already exists) |
| `style="max-width:520px"` on `.card` | ~3 in `account.html` | `.card--narrow` modifier |
| `style="margin:0"` on `<h2>` inside `.card-header` | ~8 | CSS rule: `.card-header h2 { margin: 0; }` (already exists — but not always honoured) |
| `style="overflow-x:auto"` on a div | ~4 | `.table-wrap` (already exists — should be used instead) |
| `style="font-variant-numeric:tabular-nums"` | ~4 | `.tabular-nums` utility class |
| `border-left-color: {{ color_hex }}` on `.discord-embed` | 2 | Legitimate exception — runtime colour from API data |

**Exceptional inline styles** (genuinely one-off, acceptable):
- `operation_detail.html` / `operation_planner.html` — Discord embed `border-left-color` from API-provided colour hex. This is a runtime value and cannot be a static class.
- `operation_planner.html` — `style="display:inline"` on some forms; acceptable for inline PRG forms.

**Templates with the most remediable inline styles** (priority order for Phase 4–6):
1. `account.html` — 35+ inline styles; nearly all should be component classes or utility classes
2. `operation_ledger.html` — 30+ inline styles; heavily relies on ad-hoc flex layout
3. `workspace_scheduler_status.html` — 20+ inline styles on structural wrappers
4. `workspace_diagnostics.html` — 15+ inline styles on `h2`, table wrappers, alert widths

---

#### H. Duplicated Structural HTML Audit

**Flash messages** — ✅ Already extracted. `flash_messages.html` exists and is included via `{% include "flash_messages.html" %}` in 19 templates. No duplication.

**Role tally HTML** — ⚠️ **Duplicated** in 3 templates. The 5-item `.role-tally` span block (T/H/D/S/R with zero-dimming) appears identically in:
- `operation_planner.html` — twice (comp-level and per-party)
- `compositions_detail.html` — twice (comp-level and per-party)
- `compositions_list.html` — once (per-row in table)

Each copy is ~10 lines of nearly identical Jinja. Prime candidate for a `_role_tally.html` macro in Phase 6.

**Comp overview strip** — ⚠️ **Duplicated** in 2 templates. The `.comp-overview` div with role tally and hint appears in `operation_planner.html` and `compositions_detail.html`. Candidate for `_comp_overview.html` include in Phase 6.

**Party summary strip** — ⚠️ **Duplicated** in 2 templates. The `.party-summary` div appears identically in `operation_planner.html` and `compositions_detail.html`. Candidate for extraction in Phase 6.

**Slot card grid + individual slot cards** — ⚠️ **Duplicated** in 2 templates. The full `slot-card-grid` / `slot-card` block appears in both `operation_planner.html` (interactive, with footer actions) and `compositions_detail.html` (read-only, without footer actions). These differ enough (interactive vs. preview) that a single macro with conditional rendering is needed — or two separate macros (`_slot_card_live.html` and `_slot_card_preview.html`).

**Card header with flex layout** — ⚠️ **Pattern duplicated via inline styles**. Several templates write `style="display:flex;align-items:center;justify-content:space-between"` on `.card-header` divs (`compositions_list.html`, `operation_ledger.html`, `workspace_members.html`). The `.card-header` CSS already defines this layout — the inline overrides are redundant and can be removed.

**Empty state** — ⚠️ **Not extracted**. Each template implements its own "nothing here" message — different wording, different wrapping element, different styling. No shared empty state pattern exists. Candidates in Phase 6: `_empty_state.html` macro with `title` and optional `body` parameters.

**Action bar** — `.action-bar` class exists and is widely used (~12 templates), but frequently augmented with `style="margin-top:1rem"` or `style="margin-top:var(--space-3)"`. The base `.action-bar` class should include a default top margin or a `--at` modifier.

---

#### I. Accessibility Audit

**ARIA usage:** Sparse. Only 3 templates use `aria-label` or `role="":
- `workspace_nav.html` — `<nav aria-label="Workspace">` ✓
- `compositions_list.html` — `aria-label` on search input ✓
- `workspace_diagnostics.html` / `workspace_scheduler_status.html` — `role="status"`, `role="alert"`, `role="note"` on alert divs ✓

**Risks identified:**

| Risk | Location | Severity |
|---|---|---|
| `outline: none` on `:focus` without visual replacement | `base.html` lines 585–587 (form inputs) | **High** — inputs lose all focus indicator. Only a `box-shadow` replacement is used, which may not be sufficient for high-contrast modes. |
| `:focus-visible` only on buttons, not inputs | Buttons use `:focus-visible`; inputs use `:focus` (both — also catches keyboard and mouse). Inconsistent model. | Medium |
| Icon/symbol-only content with no accessible label | Several places use `&#9888;` (⚠), `&#10003;` (✓), `›` (breadcrumb separator) without `aria-hidden` or `aria-label` | Medium |
| Colour-only state communication | `.badge-ready`, `.badge-forming`, `.badge-not_ready` distinguish operational state by colour alone; no icon or text variant accompanies different states | Medium |
| `<h2>` used inside `.card-header` for section headings regardless of page context | Some pages skip from `<h1>` directly to `<h2>` inside a card; some use `<h2>` where `<h3>` would be more accurate | Low–Medium |
| Form inputs with no `<label>` | `operation_planner.html` — inline build edit inputs use `placeholder` only, no label | Medium |
| `details/summary` disclosures lack `aria-expanded` | `.slot-build-edit` and `.slot-manual-assign` use native `<details>` — browser handles keyboard but no ARIA state is exposed to assistive tech | Low (native behaviour covers most cases) |
| `<nav class="global-nav">` has no `aria-label` | Global nav is unlabelled; could conflict with labelled workspace nav | Low |

**Focus ring status:** `button:focus-visible` uses `box-shadow: 0 0 0 3px rgba(88,166,255,.25)` — visible but low contrast against dark backgrounds. Input `:focus` uses similar `box-shadow`. Passes basic visibility but may not meet WCAG 2.2 focus appearance requirements.

---

#### J. Naming Inconsistencies

| Issue | Detail | Resolution |
|---|---|---|
| `.stat-grid` / `.stat-item` vs. `.metric-card` | Two overlapping KPI display patterns: `stat-grid` (account page) and `metric-card` (dashboard). Both show a big number + label. | Consolidate to `.metric-card` in Phase 4 |
| `.summary-strip` vs. `.comp-overview` vs. `.party-summary` | Three strip-style horizontal info bars with slightly different padding and context. Only partial alignment. | Clarify taxonomy in Phase 5 |
| `.all-clear-state` vs. `.empty-state` | `all-clear-state` is a success variant; `empty-state` is a no-data variant. Names are fine but `empty-state` is only a utility class (one line), not a component. | Formalise `empty-state` as a component in Phase 4 |
| `.form-actions` vs. `.action-bar` | Used interchangeably; `.action-bar` appears more frequently. | Standardise on `.action-bar`; deprecate `.form-actions` |
| `.gap-pill` vs. `.tac-gap-badge` | Two pill-badge patterns for gap reporting: `gap-pill` (Phase 1-era planner overview) and `tac-gap-badge` (Phase 5 party summaries). Both are used in `operation_planner.html` simultaneously. | Document distinction; unify in Phase 5 |
| `.btn-ghost` vs. `.btn-muted` | Two low-contrast button variants with overlapping intent. `.btn-ghost` has no background at rest; `.btn-muted` is text-colour only. | Clarify semantics; `.btn-ghost` for sidebar recessed actions; `.btn-muted` for terminal/retire actions |
| `.panel-muted` | Defined in CSS but not audited as used in templates; may be dead code | Verify in Phase 4 |
| `.card-section` | Used in `workspace_discord_settings.html` with inline style overrides — class has no CSS definition | Dead class; remove inline styles and use correct structural pattern |
| `.form-field` | Used in `operation_ledger.html` with inline flex styles — class has no CSS definition | Dead class; define or replace with existing form patterns |
| `.timeline-payout-detail` | Used in `operation_timeline.html` — has no CSS definition in `base.html` | Dead class; style is entirely inline |

---

#### K. Recommended Cleanup Order

**Before Phase 2 (must fix first):**
1. Define `--radius-sm` token in `:root` — it is referenced but absent, causing a CSS bug.
2. Add `--role-default` token — used by `tactical.py` output but has no CSS colour rule.

**In Phase 3 (token formalisation):**
3. Consolidate 27 font-size values to the canonical `--text-*` scale (7–9 levels).
4. Replace ~25 hardcoded hex values in component CSS with token references.
5. Add `--space-7`, `--space-8` to the spacing scale.
6. Define typography weight and leading tokens.

**In Phase 4 (component formalisation):**
7. Define `.card-section` CSS (or remove the class from `workspace_discord_settings.html`).
8. Define `.form-field` CSS (or replace with `.form-group` in `operation_ledger.html`).
9. Verify `.panel-muted` usage; remove if dead.
10. Standardise `.action-bar` over `.form-actions`.
11. Formalise `.empty-state` as a proper component with `__title` and `__body` sub-elements.
12. Consolidate `.stat-item` into `.metric-card` pattern.

**In Phase 5 (tactical layer):**
13. Clarify the `gap-pill` vs. `tac-gap-badge` distinction; document or unify.
14. Normalise `.summary-strip`, `.comp-overview`, `.party-summary` into a clear strip hierarchy.

**In Phase 6 (template macros):**
15. Extract `_role_tally.html` macro (5 occurrences of duplicate HTML).
16. Extract `_comp_overview.html` include (2 occurrences).
17. Extract `_party_summary.html` include (2 occurrences).
18. Extract `_slot_card_preview.html` macro for read-only slot card in `compositions_detail.html`.

**In Phase 7 (accessibility):**
19. Add `aria-label` to `.global-nav`.
20. Add visible labels to inline build edit inputs in `operation_planner.html`.
21. Audit colour-only badge states and add visually-hidden text.
22. Verify `:focus-visible` coverage on all interactive elements.

---

#### L. What Should NOT Be Touched Yet

- **No CSS extraction yet** — all CSS remains in `base.html` until Phase 2 is active.
- **No template refactoring yet** — no inline styles removed until Phase 4.
- **No class renames** — class names are referenced in tests; renaming without updating tests and all templates simultaneously will break the suite.
- **No macro extraction yet** — Phase 6 work. Attempting it before Phase 4/5 formalises the CSS for those components risks cascading failures.
- **No responsive breakpoint normalisation yet** — Phase 7. Changing breakpoint values risks visual regressions across all responsive surfaces simultaneously.
- **Badge variants** — do not consolidate badge variants or change badge class names; many tests assert on badge class names directly.

---

#### M. What Phase 2 Should Do

1. Add standardised section comment labels to `base.html` inline CSS matching the planned file taxonomy.
2. Create `app/static/css/` directory and configure FastAPI to serve static files from it.
3. Extract sections one at a time, in dependency order, running the full test suite after each extraction.
4. Fix `--radius-sm` and `--role-default` token gaps during the tokens extraction step.
5. Move all `@media` blocks to a single `responsive.css` section (consolidating the 3 breakpoints at 900px, 960px, and 960px-min into a 3-value canonical system).
6. Confirm the `<style>` block in `base.html` is fully empty and removed at the end of Phase 2.

### Phase 2 — CSS Extraction from base.html

**Goal:** Move from one monolithic inline style block to purpose-oriented static files.

- [x] Add section comment labels to `base.html` inline CSS (tokens / base / layout / components / dashboard / tactical / tables / forms / utilities / responsive)
- [x] Create `app/static/css/` directory
- [x] Extract `/* tokens */` section → `tokens.css`; link in `base.html`; run tests
- [x] Extract `/* base */` section → `base.css`; link in `base.html`; run tests
- [x] Extract `/* layout */` section → `layout.css`; link in `base.html`; run tests
- [x] Extract `/* components */` section → `components.css`; link in `base.html`; run tests
- [x] Extract `/* dashboard */` section → `dashboard.css`; link in `base.html`; run tests
- [x] Extract `/* tactical */` section → `tactical.css`; link in `base.html`; run tests
- [x] Extract `/* tables */` section → `tables.css`; link in `base.html`; run tests
- [x] Extract `/* forms */` section → `forms.css`; link in `base.html`; run tests
- [x] Extract `/* utilities */` section → `utilities.css`; link in `base.html`; run tests
- [x] Extract `/* responsive */` section → `responsive.css`; link in `base.html`; run tests
- [x] Confirm `base.html` `<style>` block is now empty and removed
- [x] Run full test suite; confirm all pass

#### Phase 2 — Implementation Log

**Date:** 2026-05-18

**Files created:**

| File | Responsibility | Key contents |
|---|---|---|
| `app/static/css/tokens.css` | Design tokens only | `:root` block; added `--radius-sm: 4px` and `--role-default: #8b949e` |
| `app/static/css/base.css` | Reset + base HTML elements | `*` reset, `body`, `a`, `p/em/code`, `h1–h4`, `.dev-banner` |
| `app/static/css/layout.css` | Page shell + navigation | `.page*`, `.stack`, `.cluster`, `.layout-two-col`, `.page-header`, `.summary-strip`, `.global-nav*`, `.workspace-nav*` |
| `app/static/css/components.css` | Shared UI components | `.card*`, `.panel-muted`, `.party-panel` base, alerts, badges (34 variants), buttons (all variants incl. `.btn-ghost`), auth card, Discord embed, op-tabs, timeline, collapsible Discord preview, op-status accent, account components |
| `app/static/css/dashboard.css` | Dashboard-specific widgets | `.dashboard-grid`, `.sidebar-panel`, `.dashboard-section`, `.section-header*`, `.metric-card*`, `.action-group`, `.attention-*`, `.summary-metrics`, `.all-clear-state`, op title/type cells, row accents, `.card--compact` overrides, `.sidebar-label`, `.action-section-label`, `.op-next-step`, `.stat-grid`, `.stat-item`, `.sched-table*`, `details.result-details`, `.activity-*` |
| `app/static/css/tactical.css` | Tactical planner primitives | `.readiness-bar*`, `.gap-pill*`, `.fill-count*`, `.comp-overview*`, `.party-summary`, `.role-tally*`, `.tac-gap-badge*`, `.unassigned-panel`, `.signup-card*`, `.slot-build-edit*`, `.slot-manual-assign*`, `.slot-card-grid`, `.slot-card*` (full system incl. role identity `[data-role]` selectors) |
| `app/static/css/tables.css` | Table wrappers + row states | `.table-wrap`, `.data-table` (full), all `.data-table tr.row-*` variants, generic `table/th/td` |
| `app/static/css/forms.css` | Form layout + inputs | `form.form`, `label`, all inputs/select/textarea, focus styles, `.form-group`, `.form-hint`, `.form-actions`, `.action-bar`, `.inline-form`, `.slot-table*`, `.wide-form`, `.slot-row` |
| `app/static/css/utilities.css` | Atomic helpers | `.text-muted`, `.text-danger`, `.text-warning`, `.empty-state`, `.col-meta`, `.col-action`, `.btn-muted`, `.metric-card__fraction` |
| `app/static/css/responsive.css` | All `@media` overrides | Consolidated 5 media blocks from across the file: `max-width: 900px` (layout-two-col), `max-width: 960px` (dashboard-grid), `min-width: 960px` (planner columns), `max-width: 768px` (tablet), `max-width: 480px` (phone) |

**Infrastructure changes:**

- `app/main.py`: Added `StaticFiles` mount at `/static` pointing to `app/static/` using `Path(__file__).parent / "static"` for reliable path resolution.
- `app/templates/base.html`: Replaced the 1,441-line inline `<style>` block with 10 `<link rel="stylesheet">` tags. File reduced from 1,485 to 54 lines.

**Extraction order (dependency-safe):**

`tokens.css` → `base.css` → `layout.css` → `components.css` → `dashboard.css` → `tactical.css` → `tables.css` → `forms.css` → `utilities.css` → `responsive.css`

**Token fixes applied:**

- `--radius-sm: 4px` — was referenced by `.tac-gap-badge` but undefined in `:root`. Added to `tokens.css`.
- `--role-default: #8b949e` — was used by `app/tactical.py` output but had no corresponding CSS token. Added to `tokens.css`.

**Responsive consolidation:**

All 5 `@media` blocks previously scattered across the inline CSS were consolidated into `responsive.css` in a single pass:

| Block | Original location in base.html | Breakpoint |
|---|---|---|
| `.layout-two-col` collapse | Layout helpers section (line 146) | `max-width: 900px` |
| `.dashboard-grid` collapse | Dashboard layout section (line 160) | `max-width: 960px` |
| `.planner-columns` grid | Planner layout section (line 1238) | `min-width: 960px` |
| Tablet overrides | Phase 5 responsive section (line 1343) | `max-width: 768px` |
| Phone overrides | Phase 5 responsive section (line 1406) | `max-width: 480px` |

Breakpoint values were preserved exactly — no responsive behaviour was redesigned.

**Issues encountered and fixes applied:**

1. **`fix_base.py` helper script**: The `<style>` block was too large (1,441 lines) for `StrReplace`. A one-shot Python script using `re.sub(r'<style>.*?</style>', ...)` was used to do the replacement, then deleted.
2. **dashboard.css first draft discrepancies**: The initial draft had incorrect CSS for `.metric-card`, `.sidebar-panel`, `.stat-grid`, `.stat-item`, `.sched-table`, and `.activity-*` (some invented, some had wrong property values). All were corrected by reading the exact CSS from `base.html` before finalising the file.
3. **Activity widget sub-elements**: The final `activity-item` uses `__event`, `__op`, `__meta` sub-elements (column layout). The early draft had incorrectly used `__icon`, `__body`, `__text` sub-elements from an older pattern. Corrected on second pass.

**Validation performed:**

| Tier | Command | Result |
|---|---|---|
| Tier 1 (import smoke) | `python -m pytest --collect-only -q` | 1493 tests collected, 0 errors |
| Tier 4 (UI/template) | `pytest test_dashboard_widgets.py test_dashboard_readiness.py test_op_status_coloring.py test_planner_ergonomics.py test_tactical_logic.py -q` | 80 passed, 0 failed |
| Tier 5 (full suite) | `python -m pytest -q` | 1493 passed, 0 failed |

The known Windows `PermissionError: [WinError 5]` on pytest temp-dir cleanup is unrelated to CSS and does not affect test results.

### Phase 3 — Token and Base Layer Formalization

**Goal:** Ensure all design tokens are defined, complete, and consistently used.

- [x] Add all missing spacing tokens (`--space-1` through `--space-12`) to `tokens.css`
- [x] Add all missing typography tokens (`--text-*`, `--weight-*`, `--leading-*`) to `tokens.css`
- [x] Add elevation tokens (`--radius-*`, `--shadow-*`) to `tokens.css`
- [x] Replace all hardcoded colour hex values in `components.css` / `dashboard.css` / `tactical.css` with token references
- [x] Replace all hardcoded pixel spacing values in component definitions with `--space-*` tokens
- [x] Replace all hardcoded font sizes in component definitions with `--text-*` tokens
- [x] Audit `base.css` — ensure it covers HTML reset, scrollbar, body background, selection, focus ring
- [x] Run full test suite; confirm all pass

#### Implementation Log — Phase 3 (2026-05-18)

**Tokens added to `tokens.css`:**

| Token | Value | Purpose |
|---|---|---|
| `--text-xs` | `0.75rem` | 12px — metadata caps, sidebar labels, sched table headers |
| `--text-sm` | `0.8rem` | ~13px — secondary/muted text, table meta, compact cells |
| `--text-base` | `0.875rem` | 14px — default component text (alerts, buttons, forms) |
| `--text-md` | `0.9375rem` | 15px — page body font-size, timeline labels |
| `--text-lg` | `1.05rem` | ~17px — card sub-headings, stat values |
| `--text-xl` | `1.5rem` | 24px — metric values, h1 |
| `--text-2xl` | `2rem` | 32px — reserved for large KPI displays (no current use) |
| `--shadow-focus` | `0 0 0 3px rgba(88,166,255,.25)` | Button focus-visible ring |
| `--shadow-focus-sm` | `0 0 0 3px rgba(88,166,255,.15)` | Input/select/textarea focus ring |
| `--nav-border` | `#21262d` | Nav bottom border — deeper than `--border` for depth |
| `--core-bg/text/border` | `#201800 / #d4a017 / #4a3800` | Gold core-slot badge |
| `--plan-bg/text/border` | `#1a0a30 / #c084fc / #3a1a68` | Purple lifecycle/plan badge |
| `--teal-text` | `#34c4a8` | Shared text for badge-support + badge-signups |
| `--teal-border` | `#1a4838` | Shared border for badge-support + badge-signups |
| `--teal-support-bg` | `#0a2018` | badge-support background |
| `--teal-signups-bg` | `#0a1f1a` | badge-signups background (intentionally different from support-bg) |
| `--attend-bg/text/border` | `#1f1000 / #f0843a / #4a2800` | Orange attendance badge |
| `--discord-badge-bg/text/border` | `#1e2060 / #a5aaff / #3c4095` | Discord identity badge |
| `--discord-embed-bg` | `#2b2d31` | Discord embed mock background |
| `--discord-embed-border` | `#4f545c` | Discord embed left border |
| `--discord-embed-text` | `#dbdee1` | Discord embed primary text |
| `--discord-embed-muted` | `#b5bac1` | Discord embed description text |
| `--discord-embed-footer` | `#80848e` | Discord embed footer text |
| `--discord-embed-sep` | `#3f4147` | Discord embed footer separator |

**Hardcoded values normalized (by file):**

- **`base.css`**: `body font-size` → `var(--text-md)`; `h1 font-size` → `var(--text-xl)`; `h2 font-size` → `var(--text-lg)`; `code border-radius: 4px` → `var(--radius-sm)`
- **`layout.css`**: `border-bottom #21262d` → `var(--nav-border)`; `.brand color #e6edf3` → `var(--nav-text)`; `.sep color #30363d` → `var(--border)`; 4× `font-size: 0.875rem` → `var(--text-base)`; `.brand font-size: 0.9375rem` → `var(--text-md)`
- **`components.css`**: All 5 op-status accent hardcodes → semantic tokens (`--border-strong`, `--accent`, `--warning`, `--success`, `--border`); all `#0d1117` in btn-primary/lock/complete/publish hover → `var(--bg)`; all 6 Discord embed color literals → `var(--discord-embed-*)` tokens; `badge-core/discord/support/plan/signups/attendance` color triplets → specialty tokens; focus ring `rgba(88,166,255,.25)` → `var(--shadow-focus)`; 8× `font-size: 0.875rem` → `var(--text-base)`; `font-size: 0.9375rem` → `var(--text-md)`; 3× `font-size: 0.8rem` → `var(--text-sm)`; `font-size: 0.75rem` → `var(--text-xs)`; `font-size: 1.05rem` → `var(--text-lg)`
- **`dashboard.css`**: 9× typography tokens applied (`--text-base`, `--text-xs`, `--text-sm`, `--text-xl`, `--text-lg`)
- **`tactical.css`**: 7× typography tokens applied (`.readiness-bar__stats`, `.empty-all-placed`, `.signup-card`, `.signup-card__meta`, `.slot-build-edit input`, `.slot-card__weapon`, `.slot-card__player`)
- **`tables.css`**: 3× `font-size: 0.875rem` → `var(--text-base)`; row state backgrounds `#0a1f10 → var(--success-bg)`, `#0c1a30 → var(--info-bg)`, `#1f1800 → var(--warning-bg)` (all exact matches confirmed)
- **`forms.css`**: `label font-size`, `input/select/textarea font-size` → `var(--text-base)`; focus `box-shadow rgba(88,166,255,.15)` → `var(--shadow-focus-sm)`

**Deliberate exceptions preserved (NOT normalized):**

| Value | Location | Reason |
|---|---|---|
| `0.6rem` | Disclosure arrows (`.discord-preview-details`, `.slot-build-edit`) | Structural chevron — not body text, no equivalent token |
| `0.68rem` | `.slot-card__idx` | Micro-density slot index — intentionally below xs scale |
| `0.7rem` | `.badge`, `.tac-gap-badge`, `.slot-card__role`, `.slot-card__build`, `.action-section-label` | Tactical badge density — distinct from any token value |
| `0.72rem` | `.slot-card__status`, `.activity-item__meta` | Fractional density — would change to 0.75 if mapped to `--text-xs` |
| `0.73rem` | `.op-next-step` | Continuation hint density |
| `0.775rem` | `.activity-item__op` | Unique activity widget density |
| `0.78rem` | `.gap-pill`, `.comp-overview__hint`, `.role-tally`, `.timeline-payload`, `.discord-embed__field-name`, `.discord-embed__footer`, `.sched-table .col-err` | Tactical/Discord density — intentionally fractional |
| `0.8125rem` | `.btn-sm`, `.btn-ghost`, `.fill-count`, `.readiness-bar__meta`, `.slot-build-edit`, `.slot-manual-assign`, `.metric-card__sub`, `.discord-preview-target`, `.form-hint`, `.activity-item__event`, `.data-table th`, `.sched-table .col-job` | Compact form/widget size — distinct from `--text-sm` (0.8) and `--text-base` (0.875) |
| `0.85rem / 0.85em` | `.kv-list dt`, `.discord-name__id` | Between-token size; `em` in discord-name is intentionally relative |
| `0.9rem` | `.signup-card__name` | Player name larger than body — operational scan priority |
| `0.95rem` | `h3` | Between `--text-lg` and `--text-md`, preserves heading hierarchy |
| `0.88rem` | `h4` | Between `--text-base` and `--text-md`, preserves heading hierarchy |
| `1.1rem` | `.readiness-bar__fill` | Fill readiness emphasis — between `--text-lg` and `--text-xl` |
| `1rem` | `.attention-item__count` | Alert count emphasis |
| `1.05rem` | `details.discord-preview-details summary h2` | Inline heading in summary (separate from h2 base-level) |
| `#fff` | `.btn-danger:hover`, `.discord-embed__title`, `.discord-embed__field-name` | Pure white on dark bg — intentional maximum contrast |
| `#1c3a68` | `.btn-publish border-color` | One-off accent-dim border shade, only usage |
| `#1a1400` | `.row-unmarked-attendance` | Intentionally darker than `--warning-bg` (#1f1800) — distinct operational signal |
| `#5a2000 / #ffcf88 / #7a3800` | `.dev-banner` | Dev-mode warning colors — intentionally unique, no production use |
| `0.4rem / 0.6rem / 0.9rem` | `.sched-table` padding, `.alert` padding, `.result-details pre` padding | Dense-context compact padding — not on the 4-point `--space-*` scale |

**Remaining technical debt before Phase 4:**

- `0.4rem` and `0.6rem` compact padding values appear in 3–4 places each (sched-table, result-details pre, alert) but no token was added (adding `--space-compact` was deemed unclear naming without Phase 4 component audit)
- `h3` (0.95rem) and `h4` (0.88rem) have no tokens — intentional since they sit between existing scale points; Phase 7 can address heading-specific tokens if needed
- The `--text-2xl` token (2rem) is defined but has no current usage — reserved for future large KPI display components
- `--shadow-md` is defined but not referenced by any component CSS — Phase 4 may introduce elevated modal/overlay surfaces that use it
- `--discord-embed-*` tokens are intentionally NOT mapped to IronkeepV2 semantic tokens — they mirror Discord's own palette, which may change independently

**Validation:**
- Tier 1 (`--collect-only`): ✅ 1493 tests collected
- Tier 4 (UI/template/Discord tests): ✅ 113 passed
- Tier 5 not run — no broad shared-system regressions expected from token-only normalization

### Phase 4 — Component Layer Formalization

**Goal:** Ensure all shared components are named, documented, and complete.

- [x] Audit all `.card` / `.card-*` usages; fill gaps in `components.css`
- [x] Audit all `.btn` / `.btn-*` usages; confirm all variants are documented
- [x] Audit all `.status-badge` / `.status-badge--*` usages; confirm all state variants exist
- [x] Audit all `.empty-state` usages across templates; replace ad-hoc empty state HTML with canonical pattern
- [x] Audit all `.form-group` / `.form-control` / `.form-hint` usages; fill gaps in `forms.css`
- [x] Confirm `.data-table` / `.col-meta` / `.col-action` / `.table-wrap` are all defined and used consistently
- [x] Document all component classes with a short responsibility comment in their CSS file
- [x] Remove all duplicate component class definitions introduced across phases
- [x] Run full test suite; confirm all pass

#### Implementation Log — Phase 4 (2026-05-18)

**Audit findings (25 templates, 4 CSS files):**

A structured audit of all 25 templates against the extracted CSS files identified 4 class names used in templates without a matching CSS definition, one BEM element split across the wrong file, one missing semantic modifier, and one inline-style empty state.

**Components consolidated / gaps filled:**

| Class | File | Action |
|---|---|---|
| `.page-container` | `layout.css` | Added — alias for `.page`, used by `account.html` as its top-level wrapper |
| `.flash` / `.flash-error` / `.flash-success` | `components.css` | Added — secondary alert API used by `account.html` and `login.html`; visually identical to `.alert` / `.alert-*` |
| `.card-section` | `components.css` | Added — inner-card structural separator with border-top; removes inline style from `workspace_discord_settings.html` |
| `.detail-list` | `components.css` | Added — labelled `dl` metadata grid (like `.kv-list` but for settings/config context with uppercase keys) |
| `.metric-card__fraction` | moved from `utilities.css` → `dashboard.css` | BEM element now lives with its parent component family |
| `.metric-card--info` | `dashboard.css` | Added — was the only missing semantic state (ok / info / warning / danger / neutral now complete) |
| `.slot-card--empty` | `tactical.css` | Added explicit rule (was comment-only); documents the intentional no-highlight state |

**Tactical primitives hardened:**

- `.slot-card` modifier block now has an explanatory comment documenting all 4 states (`--assigned`, `--open-core`, `--open`, `--empty`) and the operational-language naming rationale
- `.tac-gap-badge` comment documents why `--warn` (not `--warning`) is the canonical modifier name, and that tests assert on it
- `.gap-pill` comment documents why `--ok` (not `--success`) is the canonical positive modifier

**Template changes (minimal — 2 files):**

- `workspace_scheduler_status.html`: Replaced `<p style="color: var(--text-muted); font-size: 0.875rem">No scheduler runs recorded yet.</p>` with `<p class="empty-state">No scheduler runs recorded yet.</p>`
- `workspace_discord_settings.html`: Removed redundant inline style from `.card-section` (values now in CSS)

**Modifier naming canonical reference (Phase 4 decision):**

| Pattern | Modifier convention | Reason |
|---|---|---|
| `metric-card--*` | `--ok / --info / --warning / --danger / --neutral` | Generic semantic states for KPI tiles |
| `slot-card--*` | `--assigned / --open-core / --open / --empty` | Operational assignment workflow states |
| `tac-gap-badge--*` | `--critical / --warn` | Tactical severity — `--warn` shorthand is locked by tests |
| `gap-pill--*` | `--role / --build / --ok` | Operational gap type — `--ok` is tactical readiness language |
| `badge-*` | semantic noun (`.badge-ready`, `.badge-locked`) | Status as the noun that describes the entity state |

**Abstractions intentionally avoided:**

- No flash message macro created — `account.html` uses CSS-covered `.flash` classes; adding a macro would hide a 2-line template pattern
- No card-header toolbar component created — the inline `style="display:flex;align-items:center;"` on card headers with controls was left alone (card-header already defines flex in CSS; the extra inline is usually one-off justification)
- No generic empty-state macro created — context-specific wording must be inline; only the CSS class is canonical
- No `render_*` helper added — PHP-style template functions are explicitly out of scope

**Remaining duplication/risk areas before Phase 5:**

- `account.html` Albion character section has significant inline styling (flex layouts, font sizes, border-bottom separators) — complex interactive section, not changed in Phase 4
- `.dashboard-section` is defined in `dashboard.css` but never used in templates — possibly dead CSS, safe to remove in Phase 5 audit
- `.section-header` parent rule is defined but templates only use `.section-header__action` — parent block may be orphaned
- `account.html` card h2 headers use `style="font-size:1rem;margin-bottom:1rem;color:var(--text-muted)"` — could become `.card-section-label` in Phase 5
- Discord embed block (`discord-embed` + `discord-preview-target` + inline-form POST buttons) appears identically in `operation_detail.html` and `operation_planner.html` — candidate for a Jinja include in Phase 6

**Validation:**
- Tier 1 (`--collect-only`): ✅ 1493 tests collected
- Tier 4 (UI/template/Discord tests): ✅ 113 passed
- Tier 5 not run — no broad shared-system changes; all modifications are additive CSS definitions and 2 template line fixes

### Phase 5 — Tactical UI Layer Formalization

**Goal:** Ensure all tactical primitives are formally defined in `tactical.css` with no duplication.

- [x] Confirm `.slot-card` and all sub-elements / modifiers are fully documented in `tactical.css`
- [x] Confirm `.slot-card-grid` column behaviour is defined and tested at all breakpoints
- [x] Confirm `.party-panel` / `.party-panel__header` are defined in `tactical.css`
- [x] Confirm `.role-tally` / `.role-tally__item` / `.role-tally__item--zero` are defined
- [x] Confirm `.tac-gap-badge` / `.tac-gap-badge--critical` / `.tac-gap-badge--warn` are defined
- [x] Confirm `.comp-overview` is defined and renders identically in planner and composition detail
- [x] Confirm all `[data-role]` CSS selectors target `--role-*` tokens; no hardcoded colours
- [x] Confirm `.tac-hint` / `.tac-hint--ok` / `.tac-hint--warn` / `.tac-hint--neutral` are defined
- [x] Remove any duplicated tactical CSS that exists in `components.css` or dashboard sections
- [x] Run full test suite; confirm all pass

#### Implementation Log — Phase 5 (2026-05-18)

**Tactical primitives confirmed / hardened:**

All primitives listed in the Phase 5 checklist were confirmed present in `tactical.css` with correct token references:
`.slot-card`, `.slot-card-grid`, `.party-panel__header`, `.readiness-bar`, `.gap-pills`, `.fill-count`, `.comp-overview`, `.party-summary`, `.role-tally`, `.tac-gap-badge`, `.slot-build-edit`, `.slot-manual-assign`, `.signup-card`

**Additions to `tactical.css`:**

| Addition | Reason |
|---|---|
| Block comment: tactical summary hierarchy | Explains the 5-level comp→party→tally→badge→hint reading order |
| Block comment: full state vocabulary | Documents all 4 slot states, 3 fill states, 3 hint states, 5 gap states, 6 role families |
| `[data-role="default"]` selectors for `.slot-card__role` and `.slot-card__header` | `tactical.py::role_family()` can return `"default"` when no role pattern matches; selectors now apply `--role-default` token instead of falling through to base `--text` |
| `.comp-overview__hint--neutral` | `tactical.py` produces `hint_state = "neutral"` for early-planning state; CSS had `--ok` and `--warn` but no `--neutral` rule. Added as explicit alias of base (muted text). |
| Note about planner layout classes | `readiness-sticky`, `planner-columns`, `planner-col--left/right` are correctly in `responsive.css` inside `@media (min-width: 960px)`; documented in file header. |

**Role-family color consistency:**

All `[data-role]` selectors — in both `.slot-card__role` and `.slot-card__header` — use `--role-*` tokens exclusively. Audit confirmed: no hardcoded hex values remain in `tactical.css`.

Role families covered: `tank → --role-tank`, `healer → --role-healer`, `support → --role-support`, `dps → --role-dps`, `ranged → --role-ranged`, `default → --role-default`

**Dead CSS removed from `dashboard.css`:**

| Rule removed | Evidence |
|---|---|
| `.dashboard-section { margin-bottom: var(--space-6); }` | Grepped all 25 templates; `class="dashboard-section"` appears 0 times |
| `.section-header { display:flex; … }` + `.section-header h2, h3 { margin:0; }` | Only `section-header__action` (child) is used in `workspace_dashboard.html`; parent class never applied |

A comment was added above `section-header__action` explaining why the parent rule was removed.

**`.tac-hint` deferred:**

The Phase 5 checklist referenced `.tac-hint` as a standalone class system. Audit found: no template uses `.tac-hint`; the `.comp-overview__hint` family (`--ok`, `--warn`, `--neutral` now complete) covers the entire surface. Adding a separate `.tac-hint` system would be speculative abstraction with no current usage. Deferred to Phase 6 if a new surface needs it.

**No tactical CSS found misplaced in other files:**

- `components.css`: no tactical-only selectors
- `dashboard.css`: only dashboard-specific selectors (after dead CSS removal)
- `responsive.css`: correctly contains planner layout + slot-card-grid breakpoint overrides

**Remaining risks before Phase 6:**

- `account.html` Albion character section — significant inline styling remains; not tactical, but part of ongoing template cleanliness debt
- `compositions_list.html` uses `.role-tally` inside a data-table row — works correctly but the role tally is not inside a `.comp-overview` or `.party-summary` container; slightly inconsistent with the tactical hierarchy. Not a bug, not addressed here.
- Discord embed block duplicated verbatim in `operation_detail.html` and `operation_planner.html` — Phase 6 include candidate

**Validation:**
- Tier 1 (`--collect-only`): ✅ 1493 tests collected
- Tier 4 (UI/template/Discord/tactical tests): ✅ 113 passed
- Tier 5 not run — changes are purely additive (new selectors + removed orphan rules); no shared rendering behavior changed

### Phase 6 — Template Include / Macro Cleanup

**Goal:** Reduce clearly repeated template fragments using lightweight includes, while preserving template readability and server-rendered simplicity.

- [x] Audit flash/alert rendering duplication — `flash_messages.html` already handles `error`/`success`; extended with `warning`/`info` support
- [x] Extract Discord embed rendering into `discord_embed` macro in `_discord_macros.html`
- [x] Update `operation_detail.html` to use `discord_embed` macro
- [x] Update `operation_planner.html` to use `discord_embed` macro
- [x] Audit sidebar metadata/KV blocks for shared extraction candidates — assessed, left inline
- [x] Confirm no tactical card abstraction introduced (slot-card, party-panel, comp-overview — all remain inline)
- [x] Run full test suite; confirm all pass

#### Implementation Log — Phase 6 (2026-05-18)

**`flash_messages.html` — extended:**

The existing include already handled `error` and `success` context variables. Added `warning` and `info` rendering to make the include complete for all four alert types. No templates currently inject these via flash, but the support is now canonical so future routes can use them without adding inline HTML.

**`discord_embed` macro added to `_discord_macros.html`:**

The Discord embed rendering block (`.discord-embed` div with title, description, fields, footer) appeared verbatim in two templates with the following structural differences:

| Attribute | `operation_detail.html` | `operation_planner.html` |
|---|---|---|
| Variable name | `discord_preview` | `discord_roster_preview` |
| Description block | present (conditional) | absent |
| Field inline/block | `field.inline` conditional | all block (always `--block`) |
| Field value style | none | `white-space:pre-line` |

A single macro with one optional parameter (`value_pre_line=False`) handles both cases cleanly. The `description` block is always guarded by `{% if embed.description %}`, which resolves correctly for both callers (roster preview objects have no description). The `field.inline` conditional covers both templates naturally — all roster fields have `inline=False` in the data layer. No per-caller conditional branching is required in the macro.

The macro was added to the existing `_discord_macros.html` file rather than creating a new `includes/` directory — this places it alongside `discord_name`, the only other Discord macro, following the established `_discord_macros.html` pattern.

**Callers updated:**

Both templates now import `discord_name, discord_embed` from `_discord_macros.html` at the point of use (inside the `{% if discord_preview %}` / `{% if discord_roster_preview %}` blocks), consolidating the previously split `{% from %}` import and the inline embed block into two clean lines:

- `operation_detail.html`: `{{ discord_embed(discord_preview) }}`
- `operation_planner.html`: `{{ discord_embed(discord_roster_preview, value_pre_line=True) }}`

The outer wrappers (card vs. `<details>` disclosure), button labels, action URLs, and config-gap alerts remain inline in each template. These are semantically distinct surfaces and were correctly left in place.

**Abstractions intentionally avoided:**

| Pattern | Reason |
|---|---|
| `.slot-card` macro | Operationally critical surface; must remain directly readable |
| `.party-panel` macro | Nested interactive state; extraction would obscure officer-critical layout |
| `.comp-overview` include | Phase 6 spec explicitly prohibits this |
| `.role-tally` include | Role tally rendering is tightly coupled to parent loop context |
| `_empty_state.html` macro | Empty state copy is always context-specific; only the CSS class is canonical |
| `_party_panel.html` macro | Tactical card abstraction explicitly excluded from Phase 6 |
| New `includes/` directory | Unnecessary — `_discord_macros.html` is the natural home; a new directory would add structure with no benefit |

**Sidebar/KV metadata blocks:**

Audited `workspace_discord_settings.html`, `operation_detail.html`, and `workspace_dashboard.html` sidebar metadata areas. Each uses `detail-list` or `kv-list` patterns with context-specific field names and values. No two templates share the same field structure, and none appear in more than one template. Left inline.

**Readability review:**

Templates affected were reviewed after extraction. Both `operation_detail.html` and `operation_planner.html` are more readable after the change:

- The Discord embed block previously required 12–14 lines of structural HTML to understand; now the call-site is one readable line with an explicit variable name.
- The `{% from %}` import is now merged with `discord_name` (already used in the same block), eliminating a redundant import statement.
- The outer conditional, post-button form, and config-gap alerts remain inline and clearly legible.

**Remaining risks before Phase 7:**

- `account.html` Albion character section — significant inline styling remains; not addressed here (not template duplication)
- `compositions_list.html` role-tally usage — inside a table row without the full tactical hierarchy container; not a Phase 6 concern
- No `includes/` directory was created; if future phases add more macros, consider whether a dedicated includes directory improves or reduces navigation clarity

**Validation:**
- Tier 1 (`--collect-only`): ✅ 1493 tests collected
- Tier 4 (Discord announcement + roster template tests): ✅ 33 passed
- Tier 5 not run — changes are confined to two templates and one macro file; no shared rendering behaviour changed beyond the embed block itself

### Phase 7 — Responsive and Accessibility Hardening

**Goal:** Harden responsiveness and accessibility across IronkeepV2 without redesigning tactical workflows, reducing operational density, or introducing frontend-framework complexity.

- [x] Audit `responsive.css` — all `@media` rules follow desktop-first policy; no changes needed
- [x] Verify slot card grid collapses correctly at tablet and phone breakpoints — existing rules confirmed adequate
- [x] Add skip-to-main link (`<a class="skip-link">`) in `base.html`; add `id="main-content"` to `<main>`
- [x] Add `aria-label="Primary navigation"` to the global `<nav>` in `base.html`
- [x] Add `aria-label="Operation"` to operation tabs `<nav>` in `operation_tabs.html`
- [x] Add `a:focus-visible` outline rule in `base.css` (covers all body text links globally)
- [x] Add `.global-nav a:focus-visible` and `.workspace-nav a:focus-visible` rules in `layout.css`
- [x] Add `.op-tabs a:focus-visible` rule in `components.css`
- [x] Fix `.btn-ghost:focus` → `.btn-ghost:focus-visible` in `components.css`
- [x] Add `summary:focus-visible` outline rule in `components.css` (covers all `<details>` disclosures)
- [x] Add `.skip-link` / `.skip-link:focus` styles in `layout.css`
- [x] Add `.sr-only` utility class in `utilities.css`
- [x] Add `scope="col"` to all `<th>` in `workspace_dashboard.html`, `compositions_list.html`, `workspace_scheduler_status.html`, `operation_signup.html`
- [x] Add `<span class="sr-only">Actions</span>` to empty action-column `<th>` in three tables
- [x] Remove inline `style=` from account link in `base.html` (`.global-nav__account a` CSS covers it)
- [x] Add `aria-label="Notes (optional)"` to placeholder-only notes input in `operation_planner.html`
- [x] Replace `<p>` wrapper around inline form with `<div>` in `workspace_discord_settings.html`
- [x] Confirm tactical planner heading hierarchy and density — left intentionally unchanged (see implementation log)
- [x] Run full test suite (Tier 1 + Tier 4); confirm all pass

#### Implementation Log — Phase 7 (2026-05-18)

**Responsive audit:**

`responsive.css` was audited across all five breakpoints (900px, 960px, 768px, 480px). All rules follow desktop-first policy. The slot card grid, dashboard grid, planner two-column layout, summary metrics strip, and workspace nav all have adequate responsive rules. No responsive breakage found. No new breakpoints added; existing rules confirmed to be working.

Table overflow is handled by the existing table-wrap / `min-width: 540px` rules in the 768px block. The data-table rule prevents tables from becoming unusable at tablet width by enforcing a minimum width within a scrollable container.

**Skip-to-main link:**

A `<a class="skip-link" href="#main-content">` was added as the first element in `<body>` in `base.html`. The link is visually hidden via `position: absolute; left: -9999px` until focused, at which point it appears as a fixed overlay link in the top-left corner. `.skip-link` styling lives in `layout.css` alongside other global navigation styles. `id="main-content"` was added to `<main>`.

**Navigation landmarks:**

Both nav regions now have accessible names:
- `<nav class="global-nav" aria-label="Primary navigation">` — `base.html`
- `<nav class="op-tabs" aria-label="Operation">` — `operation_tabs.html`

The workspace nav (`<nav class="workspace-nav">`) is rendered in `workspace_nav.html` which extends `base.html`. If that template has a `<nav>`, it should also get `aria-label="Workspace"` in a future cleanup (noted in remaining risks).

**Focus-visible rings:**

All interactive elements now have explicit `:focus-visible` rules:

| Target | Rule location | Ring style |
|---|---|---|
| All body links (`a`) | `base.css` | `outline: 2px solid var(--accent); offset: 2px` |
| Global nav links | `layout.css` | Same outline |
| Workspace nav links | `layout.css` | `outline-offset: -2px` (contained within tab) |
| Operation tab links | `components.css` | `outline-offset: -2px` (contained within tab) |
| Buttons / `.btn` | `components.css` (existing) | `box-shadow: var(--shadow-focus)` |
| `.btn-ghost` | `components.css` (fixed) | Background change on `:focus-visible` (was `:focus`) |
| `<summary>` | `components.css` (new) | `outline: 2px solid var(--accent); offset: 2px` |
| Form inputs | `forms.css` (existing) | `border-color: var(--accent); box-shadow: var(--shadow-focus-sm)` |

The `.btn-ghost` selector was corrected from `:focus` to `:focus-visible` to avoid showing the background-change state during mouse click (`:focus` fires on mouse press; `:focus-visible` fires only for keyboard/programmatic focus).

**Table semantics:**

`scope="col"` added to all `<th>` elements in every data table. Empty action-column `<th>` cells were given a `<span class="sr-only">Actions</span>` so screen readers announce the column purpose without visible text cluttering the header row.

Tables affected: `workspace_dashboard.html`, `compositions_list.html`, `workspace_scheduler_status.html` (both tables), `operation_signup.html`.

**Form accessibility:**

- `operation_planner.html` reserve notes: `<input name="notes" placeholder="...">` was given `aria-label="Notes (optional)"`. Without an associated `<label>` (the field is inline in a form row beside a select), `aria-label` is the appropriate fallback.
- `workspace_discord_settings.html`: `<form>` was nested inside a `<p>` element. Browsers auto-close `<p>` before `<form>`, producing invalid/unpredictable DOM structure. Changed to `<div class="page-meta">`.

**Inline style cleanup:**

The account link in `base.html` had `style="color:var(--nav-muted);text-decoration:none;font-size:0.9rem"`. All three properties are already covered by `.global-nav__account a` in `layout.css` and the global `.global-nav a` rules. The inline style was removed. The visual difference is imperceptible (`0.9rem` → `--text-base` / `0.875rem`).

**Tactical density decisions intentionally preserved:**

| Decision | Reason |
|---|---|
| Planner heading hierarchy unchanged | Party panel `h3` headings sit under a contextual `h2` ("Reserve / Bench") in DOM order; restructuring would require significant template surgery for marginal AT benefit in a desktop-first operational tool |
| Slot cards not stacked more aggressively at mobile | Officers need scan speed; 2-column mobile grid (already set) is the minimum useful density |
| No badge visually-hidden text added | Badges appear adjacent to their labelled entity (slot name, operation title, player name); the surrounding context provides meaning |
| `summary` h2 in discord-preview-details retained | This is an established pattern in the planner; the trade-off (unusual AT exposure) is documented in Phase 5 |

**Heading hierarchy findings (not fixed, documented):**

- `workspace_discord_settings.html` line 85: `h3` "Current Configuration" appears without a preceding `h2`. The card structure provides visual context but the heading level is technically incorrect. Low risk for this operational tool; flagged for future correction.
- `operation_planner.html`: Party panel `h3` headings appear in DOM after left-column `h2` elements. A future pass could add a region landmark or reorder the DOM. Not changed here to preserve tactical layout readability.

**Remaining accessibility/responsive risks before Phase 8:**

- `workspace_nav.html` (workspace-level nav) — if it contains a `<nav>`, it should also carry `aria-label="Workspace"` for multiple-nav disambiguation
- `compositions_new.html` slot editor table inputs — column headers use `<th>` but row inputs have no associated `<label>` or `aria-labelledby`; meaningful only for AT users editing compositions, which is a rare officer-only workflow
- `workspace_discord_settings.html` h3 heading level — technically skips from h1 to h3 inside the settings card; not fixed due to card template structure constraints
- Planner party panel heading order — AT DOM order does not match visual order; not fixed (surgical template change with UX risk)
- Badge colour-only state communication — badges use text labels (e.g. "READY", "LOCKED"), not colour alone; no additional AT annotation needed

**Validation:**
- Tier 1 (`--collect-only`): ✅ 1493 tests collected
- Tier 4 (dashboard, Discord, roster, reliability template tests): ✅ 72 passed
- Tier 5 not run — no broad shared rendering logic changed; all changes are additive HTML attributes and CSS additions

### Phase 8 — Regression Test Hardening

**Goal:** Harden UI/template regression coverage so the newly formalized UI architecture remains stable as future work continues.

- [x] Audit existing integration tests for CSS class anchor coverage
- [x] Add tests asserting `slot-card--assigned` renders when a slot has an active assignment
- [x] Add tests asserting `slot-card--open-core` renders for unassigned core slots
- [x] Add tests asserting `slot-card--empty` renders for normal-priority slots with no signups
- [x] Add tests asserting `slot-card--assigned` is absent when no assignments exist
- [x] Add tests asserting `data-role="tank"`, `"healer"`, `"dps"` render on slot cards
- [x] Add tests asserting `tac-gap-badge--critical` renders when party has no healer/tank slot
- [x] Add tests asserting `tac-gap-badge--critical` absent when all key roles present
- [x] Add tests asserting `comp-overview` renders on the planner
- [x] Add tests asserting `role-tally` renders on the planner with correct `data-role` attributes
- [x] Add tests asserting `badge-draft`, `badge-planning`, `badge-locked` render in dashboard table
- [x] Add tests asserting `empty-state` renders on compositions list and planner reserve panel
- [x] Add tests asserting skip link present and targets `#main-content` (Phase 7 regression)
- [x] Add tests asserting `id="main-content"` on main element (Phase 7 regression)
- [x] Add tests asserting `aria-label="Primary navigation"` on global nav (Phase 7 regression)
- [x] Add tests asserting `aria-label="Operation"` on operation tabs nav (Phase 7 regression)
- [x] Add tests asserting `scope="col"` on compositions table `<th>` (Phase 7 regression)
- [x] Add tests asserting `sr-only Actions` text in action column header (Phase 7 regression)
- [x] Run new test file; confirm all 25 pass

#### Implementation Log — Phase 8 (2026-05-18)

**Coverage audit findings:**

| Component | Pre-Phase 8 coverage | Gap identified |
|---|---|---|
| `slot-card--assigned` | None | ✅ Added |
| `slot-card--open-core` | None | ✅ Added |
| `slot-card--empty` | None | ✅ Added |
| `data-role` on slot cards | None | ✅ Added |
| `tac-gap-badge--critical` | Domain level only (`test_tactical_logic.py`) | ✅ Added template-level |
| `comp-overview` | None | ✅ Added |
| `role-tally` + `data-role` items | None | ✅ Added |
| `badge-draft/planning/locked` | None | ✅ Added |
| `empty-state` | None | ✅ Added |
| `data-op-status` attribute | `test_op_status_coloring.py` ✅ | Already covered |
| `signup-card` | `test_planner_ergonomics.py` ✅ | Already covered |
| `readiness-sticky` | `test_planner_ergonomics.py` ✅ | Already covered |
| Skip link, main id, nav aria-labels | None (Phase 7 additions) | ✅ Added |
| `scope="col"`, `sr-only` Actions | None (Phase 7 additions) | ✅ Added |

**New test file: `tests/test_ui_regression.py`**

25 tests organized in 7 groups:

| Group | Tests | Anchor protected |
|---|---|---|
| `TestSlotCardClasses` | 5 | `slot-card--assigned`, `--open-core`, `--empty` (presence and absence) |
| `TestDataRoleAttributes` | 3 | `data-role="tank"`, `"healer"`, `"dps"` on slot cards |
| `TestTacticalGapBadges` | 2 | `tac-gap-badge--critical` (present and absent) |
| `TestCompOverviewAndRoleTally` | 3 | `comp-overview`, `role-tally`, `data-role` on tally items |
| `TestStatusBadges` | 4 | `badge-draft`, `badge-planning`, `badge-locked`, `badge-planning` absent for draft |
| `TestEmptyStates` | 2 | `empty-state` on compositions list and planner reserve panel |
| `TestAccessibilityAnchors` | 6 | skip link, `id="main-content"`, nav aria-labels, `scope="col"`, `sr-only` Actions |

**Shared composition fixtures:**

Two slot compositions are defined as module-level constants to keep tests readable:

- `_MIXED_SLOTS` — 3-slot party: core Tank + core Healer + normal DPS. Used by slot card and data-role tests. Produces all three unassigned classes plus one assignable slot.
- `_DPS_ONLY_SLOTS` — 2-slot all-DPS party. No healer or tank slot → two `tac-gap-badge--critical` entries. Used by gap badge tests.

**Testing approach notes:**

- All tests are HTTP/template level using `TestClient`. No domain-only assertions except what the route renders.
- Assertions check for substring presence/absence in response HTML, not exact blocks or indentation.
- Negative assertions (e.g. `slot-card--assigned absent when no assignments`) are included to confirm the modifier is conditional, not always-on.
- The `tac-gap-badge--critical` test is intentionally about composition structure gaps (no healer/tank slot defined), not player assignment gaps. This is how the tactical module works: a party with no healer SLOT defined fires the badge regardless of assignment state.

**Anchors intentionally NOT tested:**

| What | Why |
|---|---|
| `comp-overview` on composition detail page | Already covered structurally; same template pattern as planner |
| `badge-completed`, `badge-archived` | Lifecycle states covered by `test_op_status_coloring.py`; badge suffix is identical to status suffix |
| `slot-card--open` (non-core, has signup) | Requires a non-core slot with a signup and no assignment — uncommon setup; the `--empty` and `--open-core` states cover the critical visual distinctions |
| `role-tally__item--zero` rendering | Domain logic covered by `test_tactical_logic.py`; template rendering is trivially conditional |
| `workspace-nav` aria-label | The workspace nav HTML lives in a partial without a `<nav>` element itself; the outer nav element is in `workspace_nav.html` which may not have one |
| Table `scope="col"` on dashboard, signup, scheduler tables | Three tests would be repetitive; the compositions list test confirms the pattern is live |
| Full embed HTML structure | Discord embed rendering covered by `test_discord_announcement_preview.py` and `test_discord_post_roster.py` |

**Remaining UI regression risks before Phase 9:**

- `compositions_detail.html` has a `comp-overview` and `role-tally` surface — not directly tested here (same source code as planner version; adding a dedicated test could guard against future divergence)
- `attendance.html` status badges not tested at template level
- `workspace_dashboard.html` `<th scope="col">` not explicitly tested (covered by the compositions list test pattern)
- Landing page CSS and template structure not yet tested (Phase 9 scope)

**Validation:**
- Tier 1 (`--collect-only`): ✅ 25 tests collected
- Tier 4 (all 25 new tests): ✅ 25 passed in 13.7s
- Tier 5 not run — no route logic changed; all additions are new test assertions

### Phase 9 — Landing Page UI Alignment

**Goal:** Ensure the landing page uses the same token and component system as the app.

- [ ] Audit landing page CSS against `tokens.css`; confirm all colour/spacing/typography references use tokens
- [ ] Confirm `.landing-hero`, `.landing-feature`, `.landing-section`, `.landing-cta`, `.landing-nav` are defined in `components.css` or a dedicated `landing.css`
- [ ] Ensure landing page presents only real, shipped features — audit all copy and screenshots
- [ ] Ensure landing page typography is consistent with app typographic scale
- [ ] Verify landing page is usable and readable at mobile viewport (600px)
- [ ] Run full test suite; confirm all pass

---

## Explicit Non-Goals

- **No React, Vue, Svelte, or Tailwind migration.** IronkeepV2 is and will remain a server-rendered Jinja2 application. No JavaScript component framework is introduced.
- **No SPA rewrite.** The routing model stays FastAPI + Jinja2. No client-side routing.
- **No build pipeline requirement.** CSS files are plain `.css` served as static assets. No PostCSS, Sass, Webpack, Vite, or equivalent is required to develop or deploy.
- **No visual redesign for its own sake.** Phase goals are consistency, maintainability, and correctness — not visual novelty. The dark-native aesthetic is preserved.
- **No overabstracted design system.** This is not Storybook. There is no design system documentation site, no component playground, no token export for design tools. The CSS files and this document are the design system.
- **No animation-heavy UI.** No entrance animations, loading spinners for synchronous pages, or transition effects on data changes. Transitions on hover states (colour, border) are acceptable if they are instantaneous or < 150ms.
- **No generic SaaS styling.** IronkeepV2 is not a generic SaaS dashboard. The visual language must remain tactically focused and guild-specific — not interchangeable with a project management tool or CRM.
- **No breaking of existing server-rendered workflows.** CSS extraction and template macro refactors must be zero-regression. Pages must look and behave identically before and after each phase. No phase should require a database migration or route change.
- **No forced mobile-first rewrite.** Desktop is the primary environment. Mobile support is best-effort for review use cases.

---

## Success Criteria

- [ ] All CSS lives in purpose-oriented static files; no inline `<style>` block remains in `base.html`.
- [ ] Every colour used in any component references a `--clr-*` or `--role-*` token; no hardcoded hex values exist outside `tokens.css`.
- [ ] Every spacing value in component definitions references a `--space-*` token; no hardcoded `px` values for margin or padding.
- [ ] Every font size in component definitions references a `--text-*` token.
- [ ] The `.slot-card`, `.party-panel`, `.role-tally`, `.tac-gap-badge`, and `.comp-overview` components are defined once, in `tactical.css`, and used identically across the planner and composition surfaces.
- [ ] The slot card grid collapses correctly at 640px and 1024px without horizontal overflow.
- [ ] All interactive elements have a `:focus-visible` ring.
- [ ] No template defines its own flash message HTML; all templates use the shared `_flash_messages.html` include.
- [ ] No template re-derives `role_family` from a raw role string; all templates use the pre-annotated `slot.role_family` field.
- [ ] Every component state variant has at least one asserting integration test.
- [ ] The full pytest suite (1,493+ tests) passes after every phase.
- [ ] A new Cursor prompt implementing a new planner or dashboard feature can reference this document to determine component names, token names, and CSS file targets without reading `base.html`.

---

## Open Design Questions

- **When should `landing.css` be created?** The landing page (`landing_page_tactical_operations_platform.md`) may have sufficiently distinct layout needs to warrant its own CSS file rather than fitting into `components.css`. Should `.landing-*` classes live in `components.css` or a dedicated file extracted only during Phase 9?

- **Should `tactical.css` be split further?** As the tactical surface grows (party layout preview, composition cloning, operation generation), `tactical.css` may become large. Should it split into `slot-cards.css` and `composition.css` from the start, or remain unified until a natural split point is reached?

- **Should Jinja2 macros accept typed context objects or positional parameters?** Macros with many parameters (e.g. a slot card macro with slot, assigned_map, can_mutate, slot_participants, etc.) become hard to call correctly. A better pattern may be to pass a pre-built slot context dict from the route. What is the maximum acceptable parameter count before this refactor is mandatory?

- **How should component documentation be maintained alongside CSS?** This document defines the component taxonomy, but CSS files themselves have no enforced documentation standard. Should each component block in `components.css` have a mandatory comment header? If so, what should it contain?

- **Should utilities be atomic or grouped?** The current utility concept is small (`text-muted`, `mt-4`, `flex-between`). Should these be kept as hand-authored focused utilities, or should a utility generation strategy be introduced for the spacing scale? A utility explosion (`.mt-1` through `.mt-12` × top/right/bottom/left × margin/padding) may be counterproductive for a solo-developer codebase.

- **What is the right Jinja2 macro boundary for the slot card?** The slot card in `operation_planner.html` includes interactive elements (Quick Assign, slot manual assign, inline build edit) that are not present in the read-only composition detail view. Should there be one macro with conditional rendering, or separate `_slot_card_live.html` and `_slot_card_preview.html` macros?

- **How should the responsive breakpoints evolve if a mobile editing mode is added?** The current desktop-first policy explicitly deprioritises mobile editing. If a future phase adds mobile officer tools (e.g. quick sign-off on the go), the breakpoint strategy and density rules may need to be revisited. Should the breakpoint values be encoded as CSS custom properties to make them changeable from one place?
