# IronkeepV2 — Tactical Party Layout Preview Foundation

> **STATUS: COMPLETE** — All phases and follow-up slices implemented. May 2026.

## Current Status

| Phase | Status | Slice |
|---|---|---|
| Phase 1 — Read-Only Party Layout Preview | ✅ Complete | Foundation + visual grouping |
| Phase 2 — Preview Accuracy / Shared Logic | ✅ Complete | Shared synthesis helper + consistency tests |
| Phase 3 — Role Counts vs Build Slot Counts Clarification | ✅ Complete | Integrity helper + non-blocking warnings |
| Phase 4 — Tactical Preview Enhancements | ✅ Complete | Warning hierarchy, actionable hints, collapsible, divergence note |
| Phase 5 — Composition Creation Integration | ✅ Complete | Slot re-fill, structural preview, creation guidance |
| Phase 6 — Strengthen Canonical Slot Template Model | ✅ Complete | Model audit, field propagation harness (23 tests) |
| Follow-up — Clone Composition | ✅ Complete | Clone route, UI affordance, 11 tests |

---

## Implementation Reality Update — Phase 3 Finding

> **This section supersedes all references to `role_counts` and `build_slot_counts_json` throughout this document.**

The original roadmap was written against a planned data model that was **not implemented**. The actual IronkeepV2 implementation uses a simpler, cleaner model:

### What the roadmap assumed (incorrect)

- `albion_compositions` would store `role_counts` (expected role totals) and `build_slot_counts_json` (per-build slot counts) as separate metadata fields.
- Preview logic would compare these fields against actual slot templates and surface mismatches.
- Slot generation would use `build_slot_counts_json` as the authoritative source.
- Phase 6 would migrate away from this split model toward a canonical slot template table.

### What the implementation actually does (correct)

| Concept | Reality |
|---|---|
| `role_counts` | **Does not exist.** Role distribution is derived at read time from slot templates via `role_family()`. |
| `build_slot_counts_json` | **Does not exist.** Build identity is stored directly on each `composition_slot_templates` row. |
| `composition_slot_templates` | **Single canonical source of truth.** Each row stores `party_number`, `slot_index`, `role`, `build_name`, `weapon_name`, `priority`. |
| Slot generation | Copies `composition_slot_templates` 1:1 into `operation_slots`. No transformation, no metadata merge. |

### Implications for all future phases

- There is no split-brain metadata model to resolve.
- There are no phantom metadata fields to compare against slot templates.
- `composition_slot_templates` already IS the canonical party template model.
- Phase 6 is now about **strengthening** the existing canonical model, not migrating toward one.
- Integrity checks in all future phases must operate on actual slot template data, not on non-existent metadata fields.
- The preview is already honest: it shows exactly what `composition_slot_templates` contains.

### Remaining real integrity risks (actual, based on implementation)

1. **Empty templates** — a composition with no slot rows cannot generate operation slots.
2. **Missing critical roles** — parties with no healer or no tank slot produce combat-ineffective formations.
3. **Uneven party sizes** — compositions where parties have significantly different slot counts may be accidentally incomplete.
4. **No integrity visibility during creation** — officers cannot see structural warnings until they navigate to the detail page after saving.
5. **No actionable correction flow** — warnings tell officers *what* is wrong but not *how to fix it*.

---

## Phase 1 Implementation Notes — 2026-05-18

**Scope delivered:** Tactical party visual grouping foundation — CSS hardening + template annotation only. No new data model, no JavaScript, no restructuring of routes or slot synthesis logic.

### What was already in place (inherited from UI Architecture System Phases 3–8)

The composition detail view (`compositions_detail.html`) and the tactical planner (`operation_planner.html`) already had a substantial tactical layout preview system in place:

- Per-party panels using `.card.party-panel` with card-body padding reduction
- `.slot-card-grid` auto-fill grid inside each party panel
- Individual slot cards (`.slot-card`) with: role-family `data-role` attributes, state modifier classes (`--assigned`, `--open-core`, `--open`, `--empty`), header divider colour from role token, weapon-first build label, slot index
- `.party-summary` strip with `.role-tally` (T/H/D/S/R) and `.tac-gap-badge--critical` / `--warn` gap indicators
- `.comp-overview` strip with full-composition role tally and continuation hint (`ok` / `warn` / `neutral`)
- Read-only slot state on composition detail (no player assignments, only build coverage shown)

Phase 1 therefore focused on **strengthening visual grouping and scan clarity** on top of this foundation, not rebuilding it.

### Tactical grouping improvements

- **`party-panel--weak` left-border accent** — New CSS modifier `.party-panel.party-panel--weak { border-left: 3px solid var(--danger); }` applied when any critical gap exists in the party (`psumm.gaps` contains a `'critical'` tuple). Uses Jinja2 `namespace()` pattern to detect within the loop. Applied to both `compositions_detail.html` and `operation_planner.html` for full surface consistency.
  - Parties with structural gaps (no healer slot, no tank slot) now visually emerge during scroll without requiring gap badge scanning.
  - Danger colour (red) is consistent with `tac-gap-badge--critical` severity.
  - Non-weak parties remain unstyled — no noise for healthy compositions.

- **"Tactical Layout" section heading** — Added `<h2>Tactical Layout <span class="text-muted">— preview</span></h2>` before the comp-overview strip in `compositions_detail.html`. Establishes correct heading hierarchy (`h1 → h2 → h3`), makes the section skip-linkable, and clarifies that the section is a read-only preview vs the active operations section above it.

- **Read-only comment block** — Added a Jinja2 block comment above the tactical layout section in `compositions_detail.html` explicitly documenting: no forms, no POST targets, no operation context, no assignment state. Guards against future regression where someone adds an action to this section accidentally.

### Role distribution improvements

- **`.role-color-bar` + `.role-color-bar__segment`** — New compact scan strip (4px height) rendered above each party's slot-card-grid in `compositions_detail.html`. One segment per slot, coloured by `data-role` using `--role-*` tokens. Provides immediate party-level role distribution scan without counting individual cards.
  - Added to the composition detail preview only, NOT the planner. In the planner, the slot card header border colours and the `.role-tally` strip already provide role distribution signal at two levels — a third strip would be redundant clutter.
  - Height (4px) was deliberately chosen to be below the threshold of visual distraction. Officers can ignore it when reading slot cards; it only activates for peripheral composition-level scanning.
  - Uses `--role-*` tokens throughout; default/unclassified role falls back to `--border-strong` (muted grey).

### Weak-party visibility improvements

- **Composition detail:** `party-panel--weak` left-border visually separates problem parties from healthy ones during page scan. Combined with the existing `tac-gap-badge--critical` badges in the party-summary strip, a weak party now signals at two distinct visual levels: structural (left-border) and labelled (badge).
- **Planner:** Same `party-panel--weak` logic added. The planner already had clear gap badge visibility; the left-border adds a peripheral scan signal visible before the officer reads the party header.

### Density preservation decisions

- **Role color bar height:** 4px chosen. Evaluated 6px (visually dominant, felt chart-like) and 2px (too faint to read at a glance). 4px is below the card header height and reads as a compact scan aid.
- **No role color bar on planner:** Adding it there was evaluated and rejected. The planner is a live assignment surface with more visual density than the composition preview. The bar would add a third role signal layer (alongside slot header borders + role-tally), creating noise rather than clarity.
- **No party label changes:** The party panel header `Party N · N/N built` pattern was not altered. It is already compact and clear. Adding a secondary label row was evaluated and rejected — it would increase vertical height per party.
- **No shadow or heavy border on `party-panel--weak`:** Only a left-border accent, not a full box-shadow or background tint. Shadow would bleed visually and feel like an alarm system; a background tint would make the card feel contextually different rather than just flagged.
- **No animation on weak parties:** Static left-border only. Blinking or pulsing was not considered — explicitly out of scope per Phase 1 constraints.

### Visual patterns intentionally avoided

- Charts, progress bars, or fill percentage visualisations
- Rainbow visual systems or multi-colour party panels
- MMO HUD-style layout (large card dimensions, equipment slot grids)
- Modal warnings or dashboard-style alert spam for weak parties
- Animation or blinking states
- Hover tooltips
- JS-driven live preview updates
- Drag-and-drop or interactive slot editing
- Consumer-friendly onboarding overlays

### Planner / composition consistency

- `party-panel--weak` applied identically in both surfaces using the same Jinja2 `namespace()` detection pattern
- Both surfaces continue to use identical: `.slot-card`, `.slot-card-grid`, `.role-tally`, `.tac-gap-badge`, `.comp-overview`, `.party-summary`
- Role family CSS tokens (`--role-*`) used uniformly — no surface-specific colour overrides

### Remaining risks before Phase 2

1. **No composition-level structural warnings** — the preview shows what slot templates contain but does not flag structural issues (no healer, no tank, uneven parties) at the composition level. Phase 3 addresses this via `derive_composition_integrity()`.

2. **No "expected party size" context** — the preview shows actual defined slots only. If an officer intends 20 slots but defines only 18, the shortfall is not visible. Phase 4 can add size-expectation context derived from existing party sizes.

3. **Role color bar placement assumes party size ≤ 10** — for very large parties (e.g. 10+ slots), bar segments become very narrow. Acceptable for Phase 1 since IronkeepV2 primarily targets 5-man sub-parties within 20-man ZvZ comps. Phase 4 can add a max-segment or grouping strategy.

4. **No preview during composition creation** — the preview is additive on the detail view only. Officers cannot see the preview while filling out `compositions_new.html`. Phase 5 addresses this.

5. **Composition detail preview is not a "live" preview** — the server-rendered preview updates only on page load or form submit. Phase 5 / progressive enhancement could add optional JS-driven live feedback.

---

Read this document before modifying `compositions_detail.html`, `composition_slot_templates`, party layout rendering, `app/tactical.py`, or any composition-to-operation slot synthesis logic. It is the authoritative planning reference for tactical party layout preview. See the **Implementation Reality Update** section for the correct data model — do not reference `role_counts` or `build_slot_counts_json` in new code.

---

## Problem Statement

Today, officers building a composition in IronkeepV2 work essentially blind. They define slot templates (party number, role, build name, weapon name, priority) through a form — but they never see what the resulting party layout will look like until they have created an operation, attached the composition, generated slots, and opened the tactical planner.

This is a significant workflow friction point:

- Officers cannot validate a composition's tactical structure without creating an operation.
- The slot-template form is a table of rows, not a spatial party layout — structural problems (no healer, unbalanced parties) are not visually obvious.
- Empty or partially-filled compositions are invisible until slot generation produces fewer rows than expected.
- Parties missing critical roles (healer, tank) are only discovered after slots are generated and the planner is opened.
- Build names and role identities have no visual representation during composition editing or on the detail page until Phase 1 introduced the slot card preview.
- Officers with less experience cannot reason about whether a composition is tactically sound without actually running it through an operation.

The result is repeated "create operation → generate slots → realise the comp is wrong → go back → start over" cycles that erode officer confidence and slow operational preparation.

> **Note:** The original problem statement referenced `role_counts` and `build_slot_counts_json` as sources of confusion. These fields do not exist. The actual friction point is the gap between the flat slot-template form and the spatial party-by-party understanding officers need. See the **Implementation Reality Update** section.

---

## Goal

Make the tactical party layout **visible during composition design** — before any operation is created.

An officer should be able to open a composition, see a projected party-by-party breakdown of every slot (role, build, weapon, fill status), spot gaps or mismatches immediately, and correct them — all without leaving the composition surface.

This is a **read-only preview** in the first phase. No mutation of operations, no assignment state, no canonical party-template model required initially.

The longer-term goal is to evolve the preview into a trusted tactical formation view that closely matches what officers will see in the live planner — reducing the gap between "designing a comp" and "running a comp" to near-zero.

---

## Core Principles

### Tactical Visibility Before Operation Creation
Officers should understand the tactical structure of a composition — party layout, role distribution, slot count, build identity — before creating any operation. The composition is the plan; it must be legible as a plan.

### Composition as Tactical Formation
A composition is not a list of build entries. It is a tactical formation: parties, roles, and build archetypes arranged for a specific scenario. The UI must reflect this. A build list renders as a table; a tactical formation renders as a spatial party layout.

### Party Layout Over Build List
The primary view of a composition should be a party-by-party layout, not a flat list of slot templates. Role distribution, slot density, and party balance should be immediately scannable without counting rows.

### Zero Blind Setup
No officer should need to create an operation to answer the question: "Does this comp have the right structure?" Every composition should be self-documenting through its preview.

### Officer Scan Speed
Preview layouts must be compact and fast to read. No oversized cards, no excessive whitespace, no analytics-style widgets. This is a tactical brief, not a dashboard.

### Read-Only Preview First
The preview is non-interactive in Phase 1. No assignment, no editing, no mutation. Establish trust in the preview's accuracy before adding interactivity.

### No Workflow Disruption
The preview is additive — it appears below or alongside existing composition editing forms. It must not replace, reorder, or block existing composition creation and editing workflows.

### Preserve Reusable Builds
Builds remain reusable entities independent of compositions and operations. The preview renders build references, not inline build definitions. No build data should be duplicated into the composition record.

### Preserve Server-Rendered Simplicity
All preview rendering is server-side Jinja2. No JavaScript-driven live preview, no client-side slot synthesis, no reactive state. Preview updates on form submit or page load only. If JavaScript enhancement is added in later phases, it must be progressive and non-blocking.

### Avoid JavaScript-Heavy Preview Systems
The preview must not depend on JavaScript to function. A future JavaScript enhancement (e.g. live update on slot-count input change) is acceptable as optional progressive enhancement — but the core preview must be fully usable without it.

---

## Architecture Constraints

- **`composition_slot_templates` is the canonical source of truth.** All preview rendering, integrity checking, and tactical summary derivation operates on slot template data. There are no additional metadata fields on `albion_compositions` to compare against.
- **Compositions remain reusable** across multiple operations. The preview must never tie a composition's representation to a specific operation's state.
- **Builds remain reusable entities.** Slot template entries reference a build by name (`build_name`, `weapon_name`). The preview renders those references; it does not embed build definitions.
- **`operation_slots` is a 1:1 copy of `composition_slot_templates` at generation time.** The preview and the planner must therefore produce structurally equivalent party layouts for the same composition. This invariant is tested and guaranteed by `build_parties()` and the `TestBuildParties` consistency tests.
- **No schema migration needed for preview correctness.** The canonical slot template model already exists and is fully functional. Future phases may extend it (e.g. add fields, support versioning) but do not need to replace it.
- **Integrity checks operate on actual slot templates only.** There are no expected-size or expected-role metadata fields to compare against. Structural warnings are derived from what slot templates actually contain.
- **No operation required to preview a comp.** The preview works at the composition level with no operation context.
- **Preview must not mutate assignments or operation state.** The preview is strictly read-only. It must never write to `operation_slots`, `assignments`, or any other operational record.
- **Preserve server-rendered simplicity.** All preview and integrity rendering is server-side Jinja2. JavaScript is optional progressive enhancement, not a requirement.

---

## Implementation Phases

---

### Phase 1 — Read-Only Party Layout Preview

**Goal:** Add a projected party layout preview to the composition detail/editing surface using existing data. Officers can see what the resulting slot layout will look like without creating an operation.

**Scope:** Template and route changes only. No new data model, no new backend storage, no JavaScript required.

#### Composition Detail Template
- [x] Audit `comp_detail.html` (or equivalent composition view) to identify where the preview should appear
- [x] Add a "Tactical Layout Preview" section below the existing composition metadata — added `<h2>Tactical Layout — preview</h2>` before the comp-overview strip
- [x] Render a projected party-by-party slot grid from `composition_slot_templates` — already in place via `slot_templates` passed from the route; confirmed (note: original checklist referenced `build_slot_counts_json` which does not exist — the implementation correctly uses slot templates)
- [x] Group slots into parties using existing `party_number` — already in place via route `parties` dict; confirmed
- [x] Show role name for each slot — rendered in `.slot-card__role`
- [x] Show build name for each slot — rendered in `.slot-card__weapon` / `.slot-card__build` (weapon-first)
- [x] Show weapon name for each slot when available — weapon-first logic already in place
- [x] Apply role-family color coding consistent with the tactical planner — `data-role="{{ slot.role_family }}"` already in place; uses same `role_family()` mapping
- [x] Show slot index within each party — rendered in `.slot-card__idx`

#### Fill Count + Slot Status
- [x] Show filled slot count per party — `party_built/party_total built` in party panel header
- [x] Show total composition slot count — `comp_summary.total` in the page header meta
- [x] Mark empty or flex slots visually — `slot-card--empty` for no-build normal slots, `slot-card--open-core` for no-build core slots
- [ ] Distinguish between "defined slots" and "underfilled to expected size" — deferred to Phase 4 (no expected party size field exists; must be derived from actual party sizes or a future composition-level field)

#### Role Colour Bar
- [x] Add a compact role colour distribution bar above the party grid — added `.role-color-bar` with one `.role-color-bar__segment` per slot
- [x] Each segment represents one slot; colour matches the role family — `data-role` drives `--role-*` token background
- [x] Keep the bar compact — 4px height; 2px gap; flex layout; does not increase card height perceptibly

#### Route Changes
- [x] Audit the composition detail route — `slot_templates` already fetched; `parties` dict with `role_family` annotation already built; `party_summaries` and `comp_summary` already derived
- [x] No new route endpoints required for Phase 1 — confirmed

#### No Mutations
- [x] Confirm preview section contains no forms, no POST targets, no mutation-capable UI — confirmed; slot cards in composition detail carry no action forms
- [x] Add a comment in the template marking the preview as read-only — block comment added at section start

---

### Phase 2 — Preview Accuracy / Shared Logic

**Goal:** Ensure the preview output is consistent with what the tactical planner shows after slot generation. Extract shared slot-synthesis logic to avoid divergence.

#### Shared Helper Extraction
- [x] Compare slot synthesis logic used in the planner route with slot template rendering in the preview — divergence audit completed; both routes had identical inline party-grouping loops
- [x] Identify any divergence in how party grouping, slot ordering, or fill counts are computed — no semantic divergence found; only syntactic duplication (`dict(slot)` vs `{**slot, ...}`)
- [x] Extract a pure helper function — extracted as `build_parties(slot_rows)` in `app/tactical.py`; simpler and more accurate name than `synthesise_preview_slots` since the function groups and annotates without synthesising new data
- [x] Place the helper in `tactical.py` — correct location; pure Python, no DB access, no route coupling; `derive_tactical_summaries` already lived here

#### Consistency Tests
- [x] Tests asserting equivalent party/slot structure for both preview and planner data sources — `test_equivalent_inputs_produce_equivalent_party_structure` and `test_equivalent_tactical_summaries_from_both_sources`
- [x] Edge cases: empty composition, single-slot, 20-slot, 30-slot — covered by `TestBuildParties`
- [x] Slot ordering within parties — `test_slot_ordering_preserved_within_party`

#### Snapshot vs Live Differences
- [x] Intentional differences documented — see semantic boundary section in `app/tactical.py` module docstring
  - Preview = `composition_slot_templates`: template structure, builds planned, no assignment state
  - Planner = `operation_slots` + `assigned_map`: generated operational instance with live assignment state
  - Assignment / readiness remain planner-only concerns passed via `assigned_map` and `track_assignments`
- [ ] Visible UI note clarifying preview vs live — deferred; the Phase 1 "preview" label and read-only comment in the template serve this purpose adequately for now. A more explicit UI note is a Phase 4 candidate.

---

## Phase 2 Implementation Notes — 2026-05-18

### Synthesis divergence findings

The audit found **no semantic divergence** between the composition detail and planner party-grouping paths. Both routes used structurally identical inline code:

```python
parties: dict[int, list] = {}
for slot in <slot_rows>:
    slot_dict = dict(slot)          # or {**slot, ...}
    slot_dict["role_family"] = tactical.role_family(slot.get("role"))
    parties.setdefault(slot["party_number"], []).append(slot_dict)
```

The only differences were:
1. Syntactic: `dict(slot)` vs `{**slot, "role_family": ...}` — functionally identical
2. Input source: `composition_slot_templates` vs `operation_slots` — both `ORDER BY party_number, slot_index`

Both queries guaranteed identical ordering (`ORDER BY party_number, slot_index`), so party insertion order and within-party slot order were already deterministic and consistent. The template `| sort` on `parties.items()` further ensured deterministic party iteration regardless of dict insertion order.

`derive_tactical_summaries()` was already correctly shared and worked identically for both surfaces via the `track_assignments` flag and `assigned_map={}`.

### Shared helper added

`build_parties(slot_rows: iterable) -> dict[int, list[dict]]` extracted into `app/tactical.py`:
- Pure Python; no DB access, no route coupling, no template logic
- Preserves input ordering (relies on repository `ORDER BY party_number, slot_index`)
- Annotates each slot dict with `role_family` via the canonical `role_family()` function
- Works for both `composition_slot_templates` and `operation_slots` without modification
- Added to `__all__` for discoverability
- Comprehensive docstring documents ordering guarantees, semantic boundary, and input contract

Both routes simplified to a single call:
```python
parties = tactical.build_parties(slot_rows)
```

### Intentional semantic boundaries preserved

The following distinctions are deliberately preserved and are **not** unified:

| Concern | Composition Preview | Tactical Planner |
|---|---|---|
| Data source | `composition_slot_templates` | `operation_slots` |
| Assignment state | None (`assigned_map={}`) | Live (`assigned_map` from DB) |
| Hint mode | `track_assignments=False` | `track_assignments=True` (default) |
| Player rows | Not rendered | Rendered in slot card body |
| Quick-assign actions | Not present | Present when `can_mutate` |
| Readiness state | Not shown | Shown via readiness snapshot |

These are intentional differences: the preview is a design-time aid; the planner is a live orchestration surface. `build_parties()` is input-agnostic and does not enforce these boundaries — the routes do, by passing different inputs and parameters.

### Ordering guarantees

| Guarantee | Mechanism |
|---|---|
| Party ordering (across parties) | Repository `ORDER BY party_number`; template `\| sort` |
| Slot ordering (within party) | Repository `ORDER BY slot_index`; `setdefault` preserves input order |
| Deterministic role_family | `role_family()` is a pure function with no external state |

A future refactor that removes the `ORDER BY` clause from repository queries or changes `setdefault` to a different dict construction would break slot ordering. The `TestBuildParties` tests will catch ordering regressions at the unit level.

### Tests added

17 new tests in `TestBuildParties` (appended to `tests/test_tactical_logic.py`):

| Test | Covers |
|---|---|
| `test_empty_input_returns_empty_dict` | Empty composition edge case |
| `test_single_slot_creates_one_party` | Single slot |
| `test_single_slot_role_family_annotated` | role_family annotation |
| `test_single_slot_original_fields_preserved` | Field pass-through |
| `test_multi_slot_single_party_grouping` | Multi-slot single party |
| `test_slot_ordering_preserved_within_party` | Slot index ordering |
| `test_multi_party_grouping_correct` | Multi-party grouping |
| `test_party_keys_in_insertion_order` | Party insertion order |
| `test_role_family_annotated_for_all_families` | All 6 role families |
| `test_standard_5man_party_structure` | Standard 5-man party |
| `test_standard_20slot_4party_composition` | Standard 20-slot ZvZ |
| `test_large_multi_party_composition` | 30-slot multi-party |
| `test_none_role_annotated_as_default` | None role edge case |
| `test_extra_fields_on_slot_are_preserved` | Extra field pass-through |
| `test_equivalent_inputs_produce_equivalent_party_structure` | Preview/planner consistency |
| `test_equivalent_tactical_summaries_from_both_sources` | Phase 2 invariant regression |

Total `test_tactical_logic.py`: 50 tests (33 pre-existing + 17 new).

### Remaining risks before Phase 3

1. **No composition-level structural warnings** — the preview shows what slot templates contain but does not flag structural issues at the composition level (e.g. "2 of 4 parties have no healer"). Phase 3 adds `derive_composition_integrity()`. ✅ Resolved in Phase 3.

2. **No underfill detection** — if a comp defines 18 slots but the officer intends 20, the shortfall is invisible. Phase 4.

3. **No UI note distinguishing preview from live planner** — the "preview" label and read-only comment are the only signals. Phase 4 candidate.

4. **`build_parties` ordering relies on repository ORDER BY** — if `get_composition_slot_templates` or `get_operation_slots` ever lose their `ORDER BY party_number, slot_index` clause, slot ordering becomes non-deterministic. Unit tests catch regressions at the helper level; repository query order is not tested directly. A future integration test could close this gap.

---

### Phase 3 — Role Counts vs Build Slot Counts Clarification

**Goal (as implemented):** Surface composition integrity warnings based on actual slot template data. The original goal — clarifying `role_counts` vs `build_slot_counts_json` — was scoped against a planned data model that was not implemented. See Phase 3 Implementation Notes for the source-of-truth audit result.

#### Visual Explanation
- [n/a] `role_counts` and `build_slot_counts_json` do not exist in the current data model. The `albion_compositions` table has no such columns. See Phase 3 notes.
- [n/a] Form hint copy improvement deferred — the current composition creation form explains slot templates accurately without legacy field references.

#### Mismatch Detection (reframed)
- [x] Added `derive_composition_integrity(parties, comp_summary, party_summaries)` in `app/tactical.py` — surfaces composition-level structural warnings based on actual slot templates
- [x] Surfaced as non-blocking warning block in `compositions_detail.html` (above comp-overview strip)
- [x] Warning codes: `empty_template`, `parties_missing_healer`, `parties_missing_tank`, `uneven_party_sizes`
- [x] Severity levels: `critical` (→ `alert-error`), `warn` (→ `alert-warning`), `info` (→ `alert-info`)
- [x] Critical warnings for all-party gaps (all parties lack healer or tank)
- [x] Warn-severity for partial gaps (some but not all parties)

#### Readiness Integrity
- [x] Preview fill count is unchanged — based on actual built slots (build_name or weapon_name set), not expected party size — confirmed no false readiness
- [x] `comp_summary.hint` already provides "N slots missing builds" / "All slots built" — integrity warnings complement this without duplicating it

#### Improved Helper Copy
- [n/a] `role_counts` / `build_slot_counts_json` form hints not applicable — fields don't exist
- [x] Composition creation hint already correctly describes slot templates as the tactical formation definition

---

## Phase 3 Implementation Notes — 2026-05-18

### Source-of-truth audit result

**`role_counts` and `build_slot_counts_json` do not exist in IronkeepV2.**

The `albion_compositions` table schema has only: `id`, `guild_workspace_id`, `name`, `description`, `deleted_at`, `created_at`, `updated_at`. No count or metadata columns.

The foundation document described these as a possible data model design. The implementation chose a cleaner path:

| Concept | Implementation reality |
|---|---|
| `role_counts` | **Does not exist.** Tactical role distribution is derived from slot templates at read time via `role_family()`. |
| `build_slot_counts_json` | **Does not exist.** Build assignment is stored directly on each slot template row (`build_name`, `weapon_name`). |
| `composition_slot_templates` | **Single source of truth.** Each slot has `party_number`, `slot_index`, `role`, `build_name`, `weapon_name`, `priority`. |
| Slot generation | Copies slot templates 1:1 into `operation_slots` at plan attachment time. No transformation. |

There is therefore no "mismatch between role_counts and build_slot_counts_json" to surface — the split never existed in the current implementation. Phase 3 was reframed to surface meaningful composition integrity signals based solely on slot template data, per the Phase 3 prompt guidance: *"If the audit finds a different truth, document it honestly and follow the code."*

### Integrity helper added

`derive_composition_integrity(parties, comp_summary, party_summaries) -> list[dict]` added to `app/tactical.py`:

- Pure Python — no DB access, no route coupling, no Jinja logic
- Takes the outputs of `build_parties()` and `derive_tactical_summaries()` as inputs
- Returns a list of `{severity, code, message}` dicts (empty list when composition is clean)
- Added to `__all__` for discoverability

### Warning types

| Code | Severity | Trigger |
|---|---|---|
| `empty_template` | critical | `comp_summary["total"] == 0` — no slots at all |
| `parties_missing_healer` | critical | ALL parties lack a healer slot |
| `parties_missing_healer` | warn | SOME (not all) parties lack a healer slot |
| `parties_missing_tank` | critical | ALL parties lack a tank slot |
| `parties_missing_tank` | warn | SOME (not all) parties lack a tank slot |
| `uneven_party_sizes` | info | `n_parties > 1` and `max_size - min_size > 1` |

**Not included (deliberately):** `unbuilt_slots` — already surfaced in `comp_summary.hint` ("N slots missing builds"). Including it in integrity warnings would duplicate the existing signal.

### UI warning placement

Warnings appear in `compositions_detail.html` between the `<h2>Tactical Layout</h2>` heading and the `.comp-overview` strip:
- Container: `<div class="comp-integrity-warnings">`
- Each warning: `<div class="alert alert-{css_class}">message</div>`
- Severity → CSS mapping: `critical → alert-error`, `warn → alert-warning`, `info → alert-info`
- Only rendered when `integrity_warnings` is non-empty; clean comps show nothing

### Tests added

**Unit tests** (appended to `tests/test_tactical_logic.py` — `TestDeriveCompositionIntegrity`, 19 tests):
covers: clean comp no-warning, empty comp critical, all-parties missing healer (critical), some-parties missing healer (warn), single-party missing healer (critical), no-healer warning absent when healer present, all/some parties missing tank, expected tank count exceeds actual, no tank warning when tank present, equal party sizes (no uneven warning), size diff of 1 (no warning), size diff of 2+ (info), single party (no uneven), multiple warnings coexist, stability.

**Template regression tests** (appended to `tests/test_ui_regression.py` — `TestCompositionIntegrityWarnings`, 3 tests):
covers: integrity warning block rendered for DPS-only comp; `alert-error` class rendered for critical; no warning block for clean comp.

### Remaining risks before Phase 4

1. **Integrity warnings are composition-level only** — they summarise per-party gaps but the per-party gap badges (tac-gap-badge in the party-summary strip) provide more granular information. There's currently some visual redundancy between the two layers. Density-conscious officers may find the integrity warnings adding noise for comps they already understand.

2. **No guidance on how to fix the warnings** — warnings tell officers *what* is wrong but not *how to fix it* (e.g. "add a healer slot to party 2"). Phase 4 / Phase 5 could add a link to the composition editing surface or an inline hint.

3. **Uneven party size warning may false-positive** — some intentional comp designs have uneven parties (e.g. a command squad of 3 + a support squad of 5). The warning uses a threshold of `max - min > 1`, which catches most accidental cases but cannot distinguish intentional designs.

4. **`compositions_new.html` still has no preview** — officers cannot see integrity issues during initial composition creation. Phase 5 addresses this.

5. **Integrity warnings not shown on compositions list** — the list view shows `role-mix` and a `badge-ready / badge-forming` indicator, but no integrity signals. Officers must navigate to the detail page to see warnings.

---

### Phase 4 — Tactical Preview Enhancements ✓ Complete

**Goal:** Improve the actionability and scan quality of the composition preview without redesigning the tactical planner or introducing new data model fields. All enhancements operate on `composition_slot_templates` data only.

> **Reframed from original:** The original Phase 4 included "missing-role indicators" based on `role_counts`. Since `role_counts` does not exist, missing-role detection is now handled by `derive_composition_integrity()` (Phase 3). Phase 4 focuses on reducing warning redundancy, adding actionable correction hints, and improving visual scan clarity.

#### Warning Redundancy Reduction
- [x] Audit overlap between composition-level integrity warnings (Phase 3) and per-party `tac-gap-badge` indicators
- [x] Evaluate whether integrity warnings should be suppressed when the same issue is already clear from party badges
- [x] Define a clear hierarchy: integrity block = composition-level summary; party badges = granular per-party detail

**Implementation note:** Both signals are preserved. The design hierarchy is: composition-level warnings answer "what and how many" (e.g. "2 of 4 parties have no healer slot."); per-party badges answer "which party" (the `⚠ No healer` badge on that specific party). Suppressing either level would lose tactical context. The messages were made concise so neither level feels redundant. The new `hint` field directs officers from the warning to the badges ("Party 2, Party 3 are highlighted below."), making the two-level flow explicit.

#### Actionable Warning Copy
- [x] Add "what to fix next" hint copy alongside integrity warnings — each warning now has a `hint` field (second muted line within the alert)
- [x] If the composition is editable and a path exists, add a compact continuation link — "Create a revised composition →" appears below the warning block for `can_mutate` comps with active warnings. (No edit route exists; creation of a revised comp is the correct action path.)
- [x] Warning area remains compact: hint is a single muted line per warning; continuation link is small text below the block

**Implementation note:** The `hint` field was added to all warning dicts in `derive_composition_integrity()`. Hints are short operational sentences: "Party 2 is highlighted below." / "All parties are highlighted below." / "Party 3 (1 slot) — most parties have 5 slots. This may be intentional for a support or command slot structure." The template renders hints as `.comp-integrity-hint` spans inside the alert. The continuation link renders conditionally: `can_mutate and not comp.deleted_at and integrity_warnings`.

#### Underfilled / Overfilled Party Visibility
- [x] Detect parties that have significantly fewer slots than other parties (min size vs modal)
- [x] Surface as `info`-severity hint naming the specific undersized parties and their slot counts — e.g. "Party 3 (1) — most parties have 5 slots."
- [x] Expected party size derived from the modal slot count across all parties — no hardcoded "correct" size

**Implementation note:** `derive_composition_integrity()` now uses `max(set(sizes), key=sizes.count)` to derive the modal party size. Undersized parties are named individually in the hint (e.g. "Party 2 (3), Party 4 (2)"). The message is concise ("Party slot counts are uneven."); the party-specific detail lives in the hint. Advisory language ("may be intentional") avoids implying the structure is invalid.

#### Preview / Planner Divergence Note
- [x] Added a one-sentence muted note below the "Tactical Layout — preview" heading: "Template preview only — no player assignments. The live planner shows current assignment state."
- [x] Styled as `.comp-preview-note` with `var(--text-sm)` — visually subordinate, non-alarming

#### Compact Slot Status Clarity
- [x] Confirmed: `slot-card--empty` renders "No build" label (`.slot-card__weapon--empty`); `slot-card--open-core` renders "No build" + `●` core marker. No clarity regression found vs the planner.
- [x] No new labels or tokens added — existing rendering is sufficient

#### Optional Collapsible Preview
- [x] Per-party panels wrapped in `<details class="comp-preview-details">` (no `open` attribute) for compositions with > 4 parties
- [x] Summary line: "Party layout — N parties · M slots" — slot/party count visible without opening
- [x] Compositions with ≤ 4 parties render panels directly — no wrapper, no change to existing layout

**Implementation note:** The threshold of > 4 parties was chosen because a 4-party 20-man ZvZ composition fits comfortably on screen. Compositions larger than this (e.g. 40-man or unusual structures) benefit from the collapsible. The `.comp-preview-details` CSS uses a `▶` indicator that rotates 90° on open. Accessibility: the `<summary>` is keyboard-focusable via native `<details>` behaviour.

#### Implementation Files Changed
- `app/tactical.py` — `derive_composition_integrity`: added `hint` to all warning dicts; made messages concise; added per-party name resolution for partial gaps and uneven sizing
- `app/templates/compositions_detail.html` — added divergence note, `hint` rendering, continuation link, collapsible
- `app/static/css/components.css` — added `.comp-integrity-hint`, `.comp-integrity-action`, `.comp-integrity-warnings`
- `app/static/css/tactical.css` — added `.comp-preview-note`, `.comp-preview-details` summary styles

#### Tests Added (Phase 4)
- `tests/test_tactical_logic.py` — 10 new unit tests in `TestDeriveCompositionIntegrity` (hint field presence, hint content for all/partial healer gaps, all/partial tank gaps, uneven party naming, message conciseness, message/hint separation)
- `tests/test_ui_regression.py` — 8 new template regression tests in `TestPhase4IntegrityRefinements` (hint rendering, divergence note, continuation link present/absent, collapsible present/absent, uneven advisory, undersized party naming)

#### Remaining Risks Before Phase 5
- No edit composition route exists. The continuation flow points to "Create a revised composition →" which requires officers to re-enter slot data manually. If a bulk-edit or clone route is added in Phase 6, the continuation link should be updated to point there.
- The collapsible `<details>` starts collapsed for > 4 parties. Officers unfamiliar with the collapsible pattern may not notice the tactical layout is hidden. If this becomes a usability issue, the summary line copy can be strengthened (e.g. "▶ Click to expand 6-party layout").
- `comp-integrity-action` (continuation link) is only shown for `can_mutate and not comp.deleted_at`. Read-only officers and retired-composition views will not see the link. This is intentional — those officers cannot create compositions.
- Warning count is currently unbounded. A composition with no tanks, no healers, and uneven parties shows 3 warnings + 3 hints. This is already below the "alert wall" threshold but worth monitoring if future checks are added in Phase 6.

---

### Phase 5 — Composition Creation Integration ✓ Complete

**Goal:** Surface a preview during new composition creation, before the officer saves the form, so they can see the projected party structure as they define it.

#### Feasibility Assessment
- [x] Assess whether server-rendered Jinja can provide meaningful preview during composition creation without a page reload
- [x] Assess whether a lightweight JavaScript progressive enhancement is appropriate (e.g. update a preview section when slot rows are added via the existing `addSlotRow()` JS function)
- [x] Document the chosen approach before implementation

**Feasibility findings:**
- **Live JS preview**: NOT feasible without significant client-side complexity. `addSlotRow()` is minimal DOM manipulation with no state tracking. Duplicating tactical synthesis logic (grouping, tally, integrity) client-side would be fragile and violate the server-side-rendering principle.
- **Server-side preview on initial load**: NOT applicable — no slot data exists before the form is submitted.
- **Server-side preview after failed validation**: FEASIBLE. The POST route already parses the `slots` list before attempting the save. When validation fails, `slots` is available and can be processed with existing tactical helpers and passed back to the template.
- **Decision**: No live JS preview. Implement a quiet placeholder for initial load + a structural preview card on failed-validation re-render using existing `tactical.py` helpers.

#### Additive Integration
- [x] Added a preview section to `compositions_new.html` below the slot table
- [x] On initial load: quiet placeholder "Tactical preview appears after save. Each slot row becomes one card in the composition layout, grouped by Party #."
- [x] On page reload after failed validation: preview card with slot count, role tally, and integrity warnings (messages only — hints suppressed, as they reference party badges that don't exist on the creation page)
- [x] Slot table rows re-filled from `prev_slots` on re-render — officers do not lose their entered data after a validation error
- [x] Form rewrite avoided — all additions are purely additive

**Implementation note:** The re-render now preserves only rows that passed the route's slot filter (`role` AND `build_name` non-empty). Empty/partial rows are not passed back. This is correct behaviour — the preview shows what would actually be saved. The improved "Tactical roles" hint copy explains the slot-to-card mapping and the preview relationship before officers save.

#### Template Presets (Future)
- [ ] Do not implement template presets in Phase 5 — defer to Phase 6 planning
- [ ] Capture the idea: a preset library of common compositions (5-man ZvZ, 20-man ZvZ, HG squad) that pre-fill the slot table
- [ ] Note: `composition_slot_templates` already stores exactly the data presets would need — presets are a UI pattern on top of the existing model, not a model change

#### Implementation Files Changed
- `app/routes.py` — GET `get_new_composition`: added `prev_slots: []`, `prev_party_count: 0`, `prev_comp_summary: None`, `prev_integrity_warnings: []` to context. POST `post_create_composition` error path: added `tactical.build_parties` + `tactical.derive_tactical_summaries` + `tactical.derive_composition_integrity` calls; passes `prev_slots`, `prev_party_count`, `prev_comp_summary`, `prev_integrity_warnings` to template.
- `app/templates/compositions_new.html` — improved "Tactical roles" hint copy (explains preview relationship); slot table re-fills from `prev_slots` when available (Jinja `if/else`); preview placeholder and preview card added below the form.
- `app/static/css/tactical.css` — added `.comp-creation-placeholder` and `.comp-creation-preview h3` styles.

#### Tests Added (Phase 5)
- `tests/test_ui_regression.py` — 8 new tests in `TestPhase5CompositionCreation`: creation page renders, guidance copy present, placeholder renders on fresh load, no preview card on fresh load, slot data preserved after failed validation, structural summary card appears, placeholder absent when slot data present, integrity warnings render on creation page.

#### Remaining Risks Before Phase 6
- Empty/partial rows are not preserved in `prev_slots` — officers who had half-filled rows will see only their complete rows on re-render. This may occasionally be surprising, but it prevents confusing partial data from appearing in the preview.
- The structural preview card shows role tally using `prev_comp_summary.tally` which uses `role_family()` classification. If an officer enters a role string that doesn't classify to a standard family (e.g. "Commander"), it will count as "default" in the tally but not be flagged. This is consistent with existing tally behaviour across the application.
- No live preview is implemented — officers only see the structural summary AFTER a validation error forces a re-render. First-time saves with issues will not get pre-save feedback. This is by design (avoids JS complexity) and is noted as a Phase 6 / future consideration.
- The "Create a revised composition →" continuation link on the detail page points to the new-composition form, which now shows the improved guidance. The loop is: detail page flags issues → officer clicks link → creation page guides correct slot entry → save.

---

### Phase 6 — Strengthen Canonical Slot Template Model ✓ Complete

**Goal:** Confirm `composition_slot_templates` fully satisfies future needs, and decide on any extensions (versioning, cloning, presets, expected-size context) that would make the model more powerful without disrupting existing compositions.

> **Reframed from original:** The original Phase 6 planned a migration from `role_counts` / `build_slot_counts_json` to a canonical slot template table. That migration is unnecessary — `composition_slot_templates` already IS the canonical model. Phase 6 now focuses on strengthening and extending it.

#### Model Adequacy Assessment
- [x] Confirm `composition_slot_templates` satisfies all current preview, planner, and integrity needs
- [x] Identify any fields that are consistently absent or frequently updated
- [x] Document whether `priority` (core / normal) is being used meaningfully in practice or is vestigial
- [x] Map all routes and templates that read `composition_slot_templates` — produce a dependency list

**Adequacy verdict: sufficient for all current needs. No schema change justified.**

`composition_slot_templates` fields and usage:

| Field | Used by | Notes |
|---|---|---|
| `party_number` | preview, planner, integrity, generation | Sufficient. Controls party grouping. |
| `slot_index` | preview, planner, ordering | Sufficient. Controls within-party order. |
| `role` | tactical family, tally, gap detection | Sufficient. Classified by `role_family()`. |
| `build_name` | slot card display, readiness | Sufficient. Required (non-nullable). |
| `weapon_name` | slot card display, planner | Sufficient. Nullable — optional shorthand. |
| `priority` | slot card visual state (core/normal) | Used and propagated. Not vestigial. |
| `created_at` / `updated_at` | audit | Present and managed. |

**`priority` is meaningful**: slots with `priority = 'core'` render as `slot-card--open-core` (orange) when unbuilt vs `slot-card--empty` (plain) for `normal` priority. It signals which unfilled slots are tactically critical.

**Route dependency map** (reads `composition_slot_templates`):
1. `get_composition_detail` → `repositories.get_composition_slot_templates()` → `tactical.build_parties()` → detail preview
2. `post_create_composition` (error path) → parsed `slots` → `tactical.build_parties()` → creation preview
3. `generate_operation_slots` (use_case) → `repositories.get_composition_slot_templates()` → `insert_operation_slots()` → frozen snapshot

**Routes that read `operation_slots`** (frozen copy, not templates):
4. `get_planner` → `repositories.get_operation_slots()` → `tactical.build_parties()` → live planner

**Shared path confirmed**: Both preview (path 1) and planner (path 4) pass slot rows through `tactical.build_parties()`. No divergence possible if `build_parties()` is the only grouping entry point — confirmed by Phase 2 + Phase 6 integration tests.

#### Possible Extensions (evaluated, all deferred)
- [x] **Expected party size field** — `albion_compositions` could gain `expected_party_size`. **Deferred**: dynamic derivation from modal slot count (Phase 4) is sufficient; advisory language already communicates structural variation without locking in an expectation.
- [x] **Composition cloning** — officers could fork an existing composition as a starting point. **Recommended as next slice** (see below). No model change needed — cloning reuses `create_albion_composition` with new IDs from existing template rows.
- [x] **Preset library** — named preset compositions (5-man ZvZ, 20-man ZvZ, HG squad). **Deferred**: this is a filtered compositions list view, not a model change. The current model already stores everything a preset needs.
- [x] **Slot template versioning** — revision history for composition slot templates. **Deferred**: compositions are currently revised by retire + create; no rollback need has been expressed. If needed, a `composition_revisions` child table is the right approach — no destructive change.

#### Integrity and Safety Constraints
- [x] Any new field on `albion_compositions` must have a safe default that preserves all existing compositions
- [x] Any extension to `composition_slot_templates` must be additive (new nullable column or new related table) — no destructive column changes
- [x] Slot generation (composition templates → operation slots) must remain a 1:1 copy unless a specific, tested transformation is explicitly required
- [x] All existing composition + operation slot regression tests must pass throughout any model extension

#### Tests Before Any Model Changes
- [x] Written comprehensive integration tests for current slot synthesis behaviour in `tests/test_slot_template_model.py`
- [x] These tests are the regression harness: they must continue to pass after any model extension

#### Recommended Next Slice — Composition Cloning

The highest-value next workflow addition is **clone composition**:

- **User story**: Officer sees an existing 5-man ZvZ comp and wants a 5-man variation with one role swapped. Currently must recreate from scratch.
- **Implementation**: New GET route `/workspaces/{slug}/compositions/{comp_id}/clone` pre-fills the creation form from `get_composition_slot_templates` rows. POST is the existing `post_create_composition`. Zero model changes.
- **Risk**: Low. Read-only route + reuse of existing creation POST logic. No new DB fields.
- **Deferred from Phase 6**: Not implemented — the workflow is clear and safe, but the phase scope was audit-only.

#### Partial-Row Preservation Assessment (from Phase 5)

Phase 5 noted that incomplete slot rows (role or build_name missing) are not preserved on failed validation. Assessment:

- **Category**: composition creation UX follow-up, not a model issue
- **Fix approach**: pass partial rows through the route filter with a separate `prev_partial_slots` list; render them in the form with a visual warning (e.g. muted row, "incomplete" label)
- **Risk**: Low if implemented carefully; medium if partial rows enter the slot preview logic
- **Decision**: Defer to a future composition editor slice. The current approach (complete rows only) is correct for the preview; the UX gap is that officers lose partial work. Acceptable trade-off for Phase 5.

#### Implementation Files Changed
- `tests/test_slot_template_model.py` — new file: 23 integration tests across 6 test classes covering count invariant, field propagation, nullable weapon_name, priority variants, ordering (party_number + slot_index), source tracking, preview/planner grouping consistency, empty composition safety.

#### Tests Added (Phase 6)
- `tests/test_slot_template_model.py` — 23 tests in `TestSlotCountInvariant`, `TestFieldPropagation`, `TestNullableWeaponName`, `TestPriorityVariants`, `TestSlotOrdering`, `TestSourceTracking`, `TestPreviewPlannerGroupingConsistency`, `TestEmptyCompositionSafety`

#### Remaining Risks After This Foundation
- No composition editing route exists. Officers who need to fix a structural issue must retire and recreate. The "Create a revised composition →" continuation link established in Phase 4 covers the most urgent case.
- The `source_composition_slot_template_id` link on `operation_slots` is nullable and audit-only. If a composition is retired and its template rows are eventually deleted (future soft-delete cascades), lineage history would be broken. Currently no cascade delete is defined — safe for now.
- `weapon_name` is nullable on both `composition_slot_templates` and `operation_slots`. An operation slot without a `weapon_name` shows the `build_name` as the primary label in the planner. This is intentional (weapon is shorthand), but could cause display confusion if officers expect weapon to always appear.
- The `priority` field meaning ("core" = tactically important unfilled slot) is defined in CSS behaviour only, not enforced by the domain. An officer can mark all slots as "core" without semantic consequence. This is a data quality risk if `priority` gains more meaning in future features.

---

## End of Tactical Party Layout Preview Foundation Roadmap (Phases 1–6)

---

## Explicit Non-Goals

- **Do not build drag-and-drop** composition planning. Party layout is a preview, not an interactive editor.
- **Do not replace the tactical planner.** The planner is the live orchestration surface for operations. The preview is a design-time aid for compositions.
- **Do not create an operation just to preview a comp.** The preview works at the composition level with no operation context.
- **Do not mutate operation state.** The preview is strictly read-only. No writes to `operation_slots`, `assignments`, or any operational record.
- **Do not remove reusable builds** or tightly couple build definitions into composition slot entries.
- **Do not introduce SPA complexity.** JavaScript is optional progressive enhancement, not a requirement. The preview must function fully without it.
- **Do not reference non-existent fields.** `role_counts` and `build_slot_counts_json` do not exist. Do not add code that reads, compares, or surfaces these phantom fields.
- **Do not add visual clutter or giant cards.** The preview is a compact tactical brief. Officer scan speed is the primary design constraint.
- **Do not show fake readiness.** The preview fill count must be based on actual slot template data only — no expected-size denominators unless clearly and separately labelled.
- **Do not block composition editing.** The preview section is additive and must never prevent an officer from submitting or editing a composition.

---

## Follow-up Slice — Clone Composition ✓ Complete

**Why clone before edit:**
Officers who find structural issues in a composition (via Phase 3/4 integrity warnings) currently have no way to fix them without retiring the original and recreating from scratch. A full "edit composition" feature would require new routes, mutation of existing templates, and careful handling of composed vs operational state. A clone workflow achieves the same officer goal (revise the formation) with zero risk to existing compositions or operations: the original is never mutated.

**What was implemented:**

- `GET /workspaces/{slug}/compositions/{comp_id}/clone` — read-only route that fetches the source composition's slot templates and renders `compositions_new.html` pre-filled with:
  - Name: `"Copy of {original name}"`
  - Description: original description
  - All slot rows: `party_number`, `slot_index`, `role`, `build_name`, `weapon_name`, `priority` (repository metadata stripped — new IDs assigned on save)
  - Structural preview card (via existing Phase 5 preview logic)
- `"Create revised copy →"` link added to the `compositions_detail.html` page header for `can_mutate` users. Available for both active and retired compositions (cloning a retired comp is valid — it gives its slot structure a new life).
- POST reuses the unchanged `post_create_composition` route. No new write paths.

**Safety guarantees:**
- The GET clone route reads only — nothing is created, mutated, or locked.
- The original composition's slot templates are never modified.
- Any `operation_slots` generated from the original remain frozen snapshots.
- Active operations using the original composition are unaffected.
- The cloned composition receives entirely new UUIDs (from `create_albion_composition`).

**Implementation files changed:**
- `app/routes.py` — added `get_clone_composition` route between `get_composition_detail` and `post_create_composition`
- `app/templates/compositions_detail.html` — updated page header to show "Create revised copy →" link for `can_mutate` users

**Tests added (Tier 4):**
11 new tests in `TestCloneComposition` (`tests/test_ui_regression.py`):
- Route returns 200 for officer; redirect for unauthenticated
- Name pre-filled with "Copy of …" prefix
- Slot roles and build names pre-filled
- Weapon name pre-filled where present
- Structural preview card appears
- UI affordance ("Create revised copy →") appears on detail page
- POST creates a new composition (redirect 303)
- Original slot templates unchanged after clone is saved
- Priority (core/normal) preserved in form
- Party number ordering preserved

**Remaining future work:**
- No edit-in-place route exists. Officers who want to change a single slot in an existing comp still need to clone + delete the unneeded rows. A lightweight "edit composition" route would complement cloning by enabling minor in-place corrections without full recreation.
- Partial-row deletion from the clone form (i.e. removing slots before saving) is handled by the existing "✕" row-remove buttons — officers can prune the clone form before saving. No additional work needed.
- Clone of a retired composition is currently allowed. If this causes confusion (officers accidentally using a retired comp as a template for an unintended purpose), a warning on the clone form (e.g. "You are cloning a retired composition") could be added.

---

## Success Criteria

- [x] Officers can see a projected party layout while viewing a composition — without creating an operation. *(Phase 1)*
- [x] Officers no longer need to create and open a tactical planner to understand a composition's party structure. *(Phase 1)*
- [x] `composition_slot_templates` are visually understandable: role, build, weapon, priority, and fill status are reflected in the slot card preview grid. *(Phase 1)*
- [x] The preview layout structurally matches what officers see in the tactical planner after slot generation. *(Phase 2 — `build_parties()` shared helper; consistency tests pass)*
- [x] Structural integrity warnings (missing healer, missing tank, empty template, uneven party sizes) are surfaced as non-blocking alerts before any operation is created. *(Phase 3)*
- [ ] Underfilled parties (fewer slots than the composition's modal party size) are visibly flagged as incomplete. *(Phase 4)*
- [ ] Officers receive actionable "what to fix next" guidance when integrity warnings are present. *(Phase 4)*
- [ ] Officers can see a preview during initial composition creation — before saving. *(Phase 5)*
- [ ] Implementation remains additive throughout: no existing composition creation, editing, or operation workflows are disrupted.
- [ ] Implementation remains testable: all shared synthesis logic has unit coverage; preview/planner consistency is verified by regression tests.
- [ ] No JavaScript required for Phase 1–4 core functionality.

---

## Open Design Questions

1. **Should healer/tank expectations be configurable per composition type?**
   The current `derive_composition_integrity()` warns when any party lacks a healer or tank slot. Some compositions are deliberately non-standard (e.g. a pure DPS squad, a scouting formation). Should officers be able to tag a composition as "non-standard" to suppress these warnings? If so, where is that flag stored — as a description convention, a future `albion_compositions` field, or a per-slot priority setting?

2. **Should uneven party size warnings be severity-tuned?**
   The current threshold (`max - min > 1`) is heuristic. A comp with 5+5+4 slots may be intentional; a comp with 5+2 is probably an accident. Should the threshold be configurable? Should the severity escalate from `info` to `warn` for larger discrepancies?

3. **Should intentional non-standard compositions suppress warnings?**
   Related to question 1. If an officer explicitly acknowledges a warning (e.g. "I know this has no healer — it's a gank squad"), should the system remember that acknowledgement and stop surfacing the warning on subsequent page loads? This requires some form of per-composition preference state, which does not currently exist.

4. **Should composition creation show integrity warnings before save?**
   Currently, officers only see integrity warnings after saving and navigating to the composition detail page. Phase 5 plans to add a preview during creation. Should that preview also include an integrity warning summary — even if it's server-rendered on validation failure?

5. **Should slot template versioning or cloning become part of Phase 6?**
   The `composition_slot_templates` model is already canonical. The question for Phase 6 is whether it needs extension for features like: (a) forking a comp to create a variant, (b) tracking edit history, (c) saving named presets. Which of these is most valuable to officers and what is the simplest implementation path?

6. **Should an `expected_party_size` field be added to `albion_compositions`?**
   Underfill detection (Phase 4) currently derives expected size from the modal party size across all parties. An optional `expected_party_size` field on the composition record would let officers specify the intended formation size explicitly (e.g. "20-man ZvZ"). This would enable cleaner underfill/overfill signalling. Is this worth the schema extension, or is the modal-size heuristic sufficient?

7. **When should Phase 6 begin?**
   The trigger for starting Phase 6 should be defined clearly: is it when a specific feature (cloning, presets, versioning) becomes a planning priority? Is it when integrity warnings prompt officers to ask "can I fix this without recreating the comp"? Defining the trigger prevents indefinite deferral.
