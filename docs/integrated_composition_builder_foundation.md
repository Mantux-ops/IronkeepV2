# Integrated Composition Builder Foundation

## Status

| Phase | Title | Status |
|---|---|---|
| 1 | Composition Workflow Foundation | ✅ Shipped — 2026-05-18 |
| 2 | Slot Card System | ✅ Shipped — 2026-05-18 |
| 3 | Inline Build Management | ✅ Shipped — 2026-05-18 |
| 4 | Equipment UX Improvements | ✅ Shipped — 2026-05-18 |
| 5 | Tactical Planning UX | ✅ Shipped |
| 5.5 | Tactical Doctrine Identity | ✅ Shipped |
| 6 S1 | Fast Tactical Mutation | ✅ Shipped — 2026-05-20 |
| 6 S2 | Assignment Workflow Foundation | ✅ Shipped — 2026-05-20 |
| 6 S3 | Build-name suggestions (datalist) | ✅ Shipped — 2026-05-22 |
| 6 S4 | New operation from composition shortcut | ✅ Shipped — 2026-05-22 |
| 6 S5 | Zero-slot compositions (named shell authoring) | ✅ Shipped — 2026-05-22 |
| 6 S6 | Zero-slot / empty-operation tactical warnings | ✅ Shipped — 2026-05-23 |
| 6 S7 | Per-slot promote operation build to composition template | ✅ Shipped — 2026-05-23 |
| 6 Stab | Stabilization (testing docs + planner macro extraction) | ✅ Shipped — 2026-05-23 |
| 6 S8 | Composition variant cloning UX polish | ✅ Shipped — 2026-05-23 |
| **6** | **Operational Workflow Acceleration** | **✅ Complete — 2026-05-23** |
| 7 S1 | Build Usage Discovery | ✅ Shipped — 2026-05-24 |
| 7 S2 | Build Fork | ✅ Shipped — 2026-05-24 |
| 7 S3 | Promote Composition Slot to Library Build | ✅ Shipped — 2026-05-24 |
| **7** | **Build Library Evolution** | **✅ Complete — 2026-05-24** |
| 8 S1 | Scroll Anchoring + Auto-Readiness on Assignment | ✅ Shipped — 2026-05-24 |
| 8 S2 | Compact Mode for Composition Detail | ✅ Shipped — 2026-05-25 |
| 8 S3 | Complete Planner Anchor Coverage | ✅ Shipped — 2026-05-25 |
| 8 | Responsiveness / Interaction | 🔄 In progress |
| Build Import | Build Library CSV/Paste Import | ✅ Shipped — 2026-05-26 |
| Trial M1 | Open signup to authenticated non-members | ✅ Shipped — 2026-05-26 |
| Trial M2 | Lock Roster confirmation dialog | ✅ Shipped — 2026-05-26 |
| 9 | Technical Discipline | Not started |

**Audit note (2026-05-22):** Composition slot template editing (`GET /compositions/{id}/edit`, `POST /compositions/{id}/slots`, `update_composition_slots` use case) confirmed fully implemented and covered by 45 tests across 7 groups. Tier 5: 1945/1945 passed.

---

## Goal

Evolve IronkeepV2 from a build-centric data-entry workflow into a **composition-centric tactical planning surface** — while preserving the reusable build architecture that underpins it.

Today, officers must navigate between the build library, the composition editor, and the slot assignment table across multiple disconnected surfaces. The result is workflow fragmentation: planning a raid comp requires too many context switches and too much upfront ceremony before a usable composition exists.

The target state is a single, coherent planning surface where officers:

1. Open a composition (or create one inline)
2. Define roles and party groupings directly
3. Assign or create builds as part of the same workflow
4. Arrive at a tactically readable, actionable plan

Build entities remain first-class reusable assets underneath — but the officer never needs to leave the composition surface to work with them.

---

## Core Principles

**Composition-first workflow**
The composition editor is the primary tactical planning surface. Everything else — builds, slots, equipment — should feel accessible from within it, not as prior gates.

**Reusable build assets**
Builds are not embedded blob-data inside compositions. They remain independent, reusable entities. Inline creation and editing are a UX layer on top of the same clean data model.

**Tactical planning clarity**
The composition builder should look and feel like operational planning software. Role distribution, party structure, slot status, and readiness gaps should be visible at a glance — not buried in table rows.

**Fast officer workflow**
Experienced officers should be able to build a working composition in minutes, not through a multi-page form wizard. The happy path must be short and low-friction.

**Operational scan speed**
An officer glancing at a composition should immediately understand: which roles are filled, which are open, where the role gaps are, and whether the comp is ready to use.

**Low-friction editing**
Updating a build, swapping a slot assignment, or adjusting party grouping should not require navigating away from the planning surface.

**Preserve clean architecture boundaries**
Composition, Slot, and Build remain separate domain entities with separate tables, repositories, and routes. The integration is a UX concern — not a data model concern.

**Preserve maintainability**
All changes are additive. No rewrites of existing working systems. No giant feature branches. Each phase ships independently and is immediately useful.

**Responsive tactical layouts**
The composition builder layout must remain usable on tablets and common officer screen sizes without sacrificing information density.

**Minimal workflow fragmentation**
Reduce the number of page navigations required to complete a full composition planning cycle. Every context switch is a friction cost.

---

## Phase 1 — Composition Workflow Foundation

Define the composition-centric workflow architecture and establish the structural model that subsequent phases build upon.

### Workflow Architecture

- [x] Audit current composition creation flow and document friction points — *Phase 1 Audit, 2026-05-18*
- [x] Define composition-centric workflow: composition → slots → build assignment — *documented in audit section 1*
- [x] Identify all current cross-surface navigation requirements — *documented in audit section 3 (routes, templates, use cases, repositories)*
- [ ] Define target workflow: what should an officer be able to do without leaving the comp editor
- [x] Document slot-based planning model: what a "slot" represents and how it relates to party/role/build — *documented in audit section 1 (architectural boundary)*

### Build Selection Strategy

- [ ] Define inline build selection model: search, filter, select existing build within comp editor
- [ ] Define how existing builds are surfaced during slot assignment (search, recent, by role)
- [ ] Specify what build metadata is shown during inline selection (role, equipment summary, tags)

### Inline Build Creation Strategy

- [ ] Define the inline build creation trigger: when and how an officer creates a new build from within the comp editor
- [ ] Define minimum required fields for inline quick-create (name, role — defer full equipment to Phase 3)
- [ ] Specify that inline-created builds are saved as full reusable entities, not embedded data

### Party Grouping UX

- [ ] Define party grouping model: how slots are grouped into parties within a composition
- [ ] Specify party size constraints and default grouping behaviour
- [ ] Define how party groups are labelled and reordered
- [ ] Define how ungrouped slots are handled

### Foundation Deliverables

- [x] Audit complete — friction points, workflow map, route/template/use case/repository inventory, architectural boundary documented
- [x] Edit-in-place slot template editing shipped — `GET /edit` + `POST /slots` routes, use case, repository helpers, template, affordances on detail and list pages
- [x] Data model confirmed: `composition_slot_templates` is canonical, no build entity, no schema migration required
- [x] Frozen snapshot invariant confirmed and regression-tested: editing templates does not touch `operation_slots`
- [ ] Target workflow defined: what officers can do without leaving the comp editor (pending Phase 2 scoping)
- [ ] Route and template changes to support inline build selection (pending Phase 2)

---

## Phase 1 Audit — 2026-05-18

> **Audit scope:** Pre-implementation analysis only. No code changed. Validates assumptions in this document against the actual codebase before any Phase 1 work begins.

---

### 1. Current Composition / Build / Slot Workflow Map

#### Critical finding: no `albion_builds` table exists

The integrated_composition_builder_foundation document was written against a mental model in which a "build library" of independent, reusable build entities backs composition slot assignment. **That model does not exist in the current codebase.**

In the current implementation:

| Concept | Reality |
|---|---|
| `albion_builds` table | **Does not exist.** No such table in `schema.sql`. |
| Build library routes | **Do not exist.** No `/builds` routes in `app/routes.py`. |
| Build entity | **Does not exist.** A "build" is currently two plain-text fields (`build_name`, `weapon_name`) stored directly on each `composition_slot_templates` row. |
| Build reuse | **Implicit only.** If two compositions share the string "Hallowfall" as `build_name`, they are logically reusing a build — but there is no FK, no shared entity, and no way to find or update all references. |

This is the most significant audit finding. Every Phase 1 checklist item that references "inline build selection," "surfacing existing builds," or "builds as reusable entities" describes capability that requires a build data layer that does not yet exist. The Phase 1 architecture must account for this gap.

#### Actual current composition workflow

```
Officer                          System
------                           ------
                                 GET /workspaces/{slug}/compositions/new
                                   → get_new_composition route
                                   → compositions_new.html (blank form)

Types slot rows manually:
  party_number, slot_index,
  role, build_name (required),
  weapon_name (optional),
  priority (core/normal)

Submits form
                                 POST /workspaces/{slug}/compositions
                                   → post_create_composition route
                                   → use_cases.create_albion_composition()
                                   → INSERT albion_compositions
                                   → INSERT composition_slot_templates (one row per slot)
                                   → redirect to compositions list

Officer navigates to detail page
                                 GET /workspaces/{slug}/compositions/{comp_id}
                                   → get_composition_detail route
                                   → repositories.get_composition_slot_templates()
                                   → tactical.build_parties()
                                   → tactical.derive_tactical_summaries()
                                   → tactical.derive_composition_integrity()
                                   → compositions_detail.html
                                     (read-only tactical preview, party layout,
                                      integrity warnings, active operations list)
```

#### Attaching a composition to an operation (current)

```
Create operation (GET+POST /operations/new)
→ Operation exists in status 'draft'

Attach plan: POST /operations/{op_id}/plan
→ use_cases.attach_operation_plan()
→ INSERT operation_plans (FK: albion_composition_id)

Generate slots: POST /operations/{op_id}/slots/generate
→ use_cases.generate_operation_slots()
→ repositories.get_composition_slot_templates()
→ repositories.insert_operation_slots()  ← 1:1 frozen snapshot

Open planner: GET /operations/{op_id}/planner
→ reads ONLY operation_slots (never reads composition_slot_templates again)
→ build_name / weapon_name can be updated per-slot via:
     POST /operations/{op_id}/slots/{slot_id}/build
     → repositories.update_operation_slot_build()
     (updates operation_slots row ONLY — composition_slot_templates unchanged)
```

#### Key architectural boundary (preserved and correct)

`composition_slot_templates` → design-time template (mutable, no player state)
`operation_slots` → frozen operational snapshot (immutable structure, mutable build text only)

The planner never reads `composition_slot_templates`. Changes to templates after slot generation have no effect on any live operation. This boundary is sound and must not be blurred by Phase 1 work.

---

### 2. Friction Points in Current Officer Workflow

#### Friction 1 — No edit-in-place for composition slot templates ✅ Resolved

~~There is no `GET /compositions/{comp_id}/edit` route.~~ **Shipped 2026-05-18.** Officers can now click "Edit Slots" on the composition detail page, edit slot rows directly, and save — landing back on the detail page with the updated tactical preview.

The previous 5-step workflow (detail → clone → edit → submit → retire) is replaced by a 3-step workflow (detail → edit → save). Existing operations are not affected. The frozen snapshot invariant is maintained and regression-tested.

#### Friction 2 — No build name autocomplete or reuse surface

Build names are freeform text. Officers type from memory. There is no suggestion of what builds already exist in the workspace, no detection of name variants ("hallowfall" vs "Hallowfall"), and no way to know which compositions share a build name. Build consistency is entirely manual discipline.

#### Friction 3 — In-planner build updates do not propagate to templates

When an officer updates `build_name` on an `operation_slot` during planning (e.g. switching a role from "Hallowfall" to "Graveguard" mid-preparation), the `composition_slot_template` is NOT updated. The template drifts silently from the operational reality. Next time the composition is used for a new operation, the old build name appears again.

There is currently no mechanism — and no UI signal — to propagate a planner-level build update back to the template. Officers must remember to update the composition separately, or clone and fix before the next op.

#### Friction 4 — Composition creation requires upfront completeness

The composition creation form requires all slots to be defined at creation time. There is no "save draft and add more later" path. If an officer wants a 20-slot composition but defines 18 and saves, they must clone to add the remaining 2.

#### Friction 5 — Operation-first workflow rather than composition-first

The current navigation pattern requires an operation to exist before a composition can be activated. An officer who wants to "build a comp and then decide which op to use it for" must still create the operation first to see the comp in live planner form. The composition detail page has a read-only tactical preview but no way to do a trial assignment run.

#### Friction 6 — No quick "New operation using this comp" action

The composition detail page shows active operations that reference this comp, but there is no "Start new operation with this comp" shortcut. The officer must navigate to the operations list, create the operation, then return to attach the composition.

---

### 3. Existing Routes / Templates / Use Cases / Repositories Involved

#### Routes

| Route | Handler | Template | Notes |
|---|---|---|---|
| `GET /workspaces/{slug}/compositions` | `get_compositions_list` | `compositions_list.html` | List with role tally, active op count, search |
| `GET /workspaces/{slug}/compositions/new` | `get_new_composition` | `compositions_new.html` | Blank creation form |
| `GET /workspaces/{slug}/compositions/{comp_id}` | `get_composition_detail` | `compositions_detail.html` | Read-only tactical preview |
| `GET /workspaces/{slug}/compositions/{comp_id}/clone` | `get_clone_composition` | `compositions_new.html` | Pre-fills creation form from existing slot templates |
| `GET /workspaces/{slug}/compositions/{comp_id}/edit` | `get_edit_composition` | `compositions_edit.html` | **[NEW]** Edit form pre-filled with current slot templates; officer/owner only; blocked for retired comps |
| `POST /workspaces/{slug}/compositions` | `post_create_composition` | — | Creates composition + slot templates |
| `POST /workspaces/{slug}/compositions/{comp_id}/retire` | `post_retire_composition` | — | Soft-delete |
| `POST /workspaces/{slug}/compositions/{comp_id}/slots` | `post_update_composition_slots` | — | **[NEW]** Atomically replaces slot templates; redirects to detail on success |
| `GET /workspaces/{slug}/operations/{op_id}/planner` | `get_planner` | `operation_planner.html` | Live planner; reads `operation_slots` only |
| `POST /workspaces/{slug}/operations/{op_id}/slots/{slot_id}/build` | `post_update_slot_build` | — | Updates `build_name` / `weapon_name` on `operation_slots` row only |

#### Templates

| Template | Role in composition workflow |
|---|---|
| `compositions_list.html` | Entry point; role-mix tally, active-ops count per comp; **Edit** link in actions column |
| `compositions_new.html` | Creation form; also used for clone pre-fill; structural preview on re-render |
| `compositions_detail.html` | Tactical preview with party layout, integrity warnings, active ops list; **Edit Slots** primary action; integrity warning continuation link now points to edit route |
| `compositions_edit.html` | **[NEW]** Edit form pre-filled from slot templates; active-operations boundary notice; posts to `POST /slots` |
| `operation_planner.html` | Live assignment surface; slot cards; build update form per slot |

#### Use cases

| Function | What it does |
|---|---|
| `use_cases.create_albion_composition()` | Creates `albion_compositions` + batch inserts `composition_slot_templates` |
| `use_cases.retire_composition()` | Soft-deletes composition (`deleted_at`); leaves slot templates intact |
| `use_cases.update_composition_slots()` | **[NEW]** Atomically replaces all slot templates for an existing composition; validates actor, composition state, and slot structure; does NOT touch `operation_slots` |
| `use_cases.generate_operation_slots()` | Copies `composition_slot_templates` 1:1 into `operation_slots` |
| `use_cases.attach_operation_plan()` | Links operation to composition via `operation_plans` |

#### Repositories

| Function | What it queries |
|---|---|
| `get_albion_compositions()` | `albion_compositions` list, optionally including deleted |
| `get_albion_composition()` | Single composition by id + workspace |
| `get_composition_slot_templates()` | All slot templates for a composition, `ORDER BY party_number, slot_index` |
| `insert_composition_slot_templates()` | Batch insert new slot templates |
| `delete_composition_slot_templates()` | **[NEW]** Deletes all slot templates for a composition; does not touch `operation_slots`; returns row count |
| `touch_albion_composition()` | **[NEW]** Bumps `updated_at` on a composition row after a slot edit |
| `soft_delete_albion_composition()` | Sets `deleted_at` on composition |
| `get_operations_using_composition()` | Reverse lookup: which operations reference this comp via `operation_plans` |
| `get_all_composition_slot_roles_for_workspace()` | Batch fetch of `(albion_composition_id, role)` for all workspace comps — used for list page tally |
| `count_active_operations_per_composition()` | Count non-archived operations per comp — used for list page |
| `get_operation_slots()` | Frozen snapshot slots for a specific operation |
| `update_operation_slot_build()` | Updates `build_name` / `weapon_name` on a single `operation_slots` row |

#### Tactical module (`app/tactical.py`)

| Function | Used in composition workflow |
|---|---|
| `build_parties(slot_rows)` | Groups slot rows by `party_number`, annotates `role_family`; used in detail view, planner, clone route, and creation error path |
| `derive_tactical_summaries(parties, assigned_map)` | Produces `party_summaries` + `comp_summary` (tallies, gap badges, continuation hint) |
| `derive_composition_integrity(parties, comp_summary, party_summaries)` | Structural warnings: empty template, missing healer/tank, uneven party sizes |
| `role_family(role)` | Maps free-text role → canonical family (tank/healer/dps/support/ranged/default) |

---

### 4. Safe Integration Points for Inline Build Selection

The following integration points allow future build selection to be added without architectural disruption:

#### Integration point A — `build_name` input in `compositions_new.html` (lowest risk)

The `build_name` field is already a plain `<input type="text" name="build_name">`. Adding an HTML `<datalist>` backed by a lightweight `GET /workspaces/{slug}/builds/names` endpoint — returning a flat list of distinct `build_name` values from existing slot templates — would provide build name autocomplete with zero data model change and zero breaking impact on any existing test.

This is the lowest-risk path to build name reuse. The "build library" becomes a derived view over existing slot template data, not a new entity.

#### Integration point B — `POST /operations/{op_id}/slots/{slot_id}/build` (low risk)

The in-planner build update route already accepts `build_name` + `weapon_name`. Replacing its text inputs with a build-select dropdown backed by the same build names endpoint would make build selection consistent between creation and the planner without any route-level change.

#### Integration point C — Slot card editor ✅ Shipped (Phase 1 + Phase 2)

`GET /compositions/{comp_id}/edit` renders a tactical slot card surface. Each `.cb-slot-card` contains a `.cb-slot-build-input` for `build_name`. This is the natural attachment point for Phase 3 inline build selection: the input can gain a `<datalist>` backed by a workspace build-names endpoint, or be replaced with an inline build search widget. The card structure (role → build → weapon hierarchy) is already established, so build selection drops in as a UX layer on the existing card without structural change.

#### Integration point D — Dedicated `albion_builds` table (deferred — Phase 3 minimum)

Introducing a first-class build entity with its own table, routes, and lifecycle should be deferred until the basic composition editor (edit-in-place slot templates) is functional and in use. The pressure to do this will emerge naturally from officer feedback once the composition editor exists. Doing it pre-emptively risks building infrastructure before the usage pattern is understood.

---

### 5. Risks of Architectural Explosion

#### Risk 1 — Build entity creep

Introducing `albion_builds` creates immediate pressure for: tags, visibility states, equipment slots, import/export, versioning. Each of these is useful in isolation. Taken together before the composition editor is functional, they would consume Phase 1–3 entirely on infrastructure with no officer-facing value. The guard is: do not introduce the build entity until the composition editor is functional and officer demand for reuse tracking is evident.

#### Risk 2 — Dual-write policy complexity

If builds become entities with FKs, every slot template requires a FK to `albion_builds`. Policy questions immediately arise: what happens when a build is renamed? Do slot templates update? When a build is deleted, are compositions orphaned? These policy decisions must be made before the FK is introduced, and each answer has test and migration implications. Deferring the build entity defers these decisions.

#### Risk 3 — Template and snapshot confusion ✅ Mitigated

Composition slot templates are now editable via the edit-in-place route. The `compositions_edit.html` template shows a non-blocking `alert-info` notice whenever active operations reference the composition: *"Editing slots here does not affect those operations — their slot data was frozen when slots were generated and will not change."* The frozen snapshot invariant is regression-tested in `tests/test_composition_edit.py` (Group 5, three tests).

#### Risk 4 — Editor scope expansion ✅ Mitigated

The basic edit-in-place surface (Phase 1) now ships and is stable. Inline build selection, inline build creation, equipment management, and swap management remain deferred to Phase 2–3. The prerequisite is met.

#### Risk 5 — Premature route proliferation

Adding edit, build-search, inline-create, equipment-management, and swap management routes simultaneously would produce a large surface area change (routes + use cases + repositories + templates + tests) that is difficult to validate atomically. Each slice must add exactly one new capability and ship independently.

#### Risk 6 — Operation slot / template conflation

`operation_slots` and `composition_slot_templates` must remain separate concerns. Any route that writes to `operation_slots` must not also write to `composition_slot_templates` (and vice versa) without explicit officer intent. Blurring the boundary — even accidentally, through shared form targets — would break the frozen snapshot invariant and silently corrupt ongoing operations.

---

### 6. First Implementation Slice ✅ Shipped — 2026-05-18

**Composition slot template editing** — edit-in-place for an existing composition's slot structure.

**What shipped:**
- `GET /workspaces/{slug}/compositions/{comp_id}/edit` — slot table form pre-filled with current slot templates; non-blocking `alert-info` notice when active operations reference the composition; blocked with 403 for retired compositions; officer/owner only
- `POST /workspaces/{slug}/compositions/{comp_id}/slots` — atomically replaces all slot templates (delete + insert in one transaction); rejects retired compositions, empty slot submissions, and non-officer actors; redirects to detail page on success, back to edit on error
- `update_composition_slots(guild_workspace_id, composition_id, actor_user_id, slots)` use case — validates via existing `albion_compositions.validate_slot_templates()`; does NOT touch `operation_slots`; emits `albion_composition.slots.updated` audit event
- `delete_composition_slot_templates(db, comp_id, ws_id)` and `touch_albion_composition(db, comp_id, ws_id, updated_at)` repository helpers
- `compositions_edit.html` — new template; posts to the correct `/slots` endpoint; reuses the same slot table form pattern as `compositions_new.html`
- "Edit Slots" primary button added to `compositions_detail.html` action group (hidden for retired comps); integrity warning continuation link updated to point to edit route
- "Edit" link added to `compositions_list.html` actions column (hidden for retired comps)

**What this slice does NOT do:**
- Does not introduce a build entity or build library
- Does not change `operation_slots` or any live planner data
- Does not add inline build selection (Phase 2 target)
- Does not add equipment management, swap management, or drag-and-drop
- Does not change the tactical preview (detail page picks up updated templates automatically on next load)

**Policy decisions implemented:**
- Editing a retired composition: disallowed (403)
- Submitting an empty slot list: rejected by `validate_slot_templates()` — redirects to edit with error
- Warning for comps with active operations: non-blocking `alert-info`; edit proceeds regardless

---

### 7. Files Changed

| File | Change |
|---|---|
| `app/routes.py` | Added `get_edit_composition` (GET) and `post_update_composition_slots` (POST) routes |
| `app/repositories.py` | Added `delete_composition_slot_templates()` and `touch_albion_composition()` |
| `app/domain/operational_events.py` | Added `ALBION_COMPOSITION_SLOTS_UPDATED` constant |
| `app/application/use_cases.py` | Added `update_composition_slots()` use case |
| `app/templates/compositions_edit.html` | New template — edit form |
| `app/templates/compositions_detail.html` | Added "Edit Slots" primary action; updated integrity warning continuation link |
| `app/templates/compositions_list.html` | Added "Edit" link to actions column |
| `tests/test_composition_edit.py` | New — 31 tests across 6 groups |
| `tests/test_ui_regression.py` | Updated `test_continuation_link_renders_for_editable_comp_with_warnings` to match new link text |

**Files that did NOT change:**
- `app/schema.sql` — no migration required
- `app/tactical.py` — no logic changes
- `app/templates/operation_planner.html` — operation slots untouched

---

### 8. Regression Tests Shipped

**`tests/test_composition_edit.py` — 31 tests**

| Group | Tests | What it covers |
|---|---|---|
| 1 — Repository | 4 | `delete_composition_slot_templates`: deletes all, returns 0 on empty, does not touch other comps, does not touch operation_slots |
| 2 — Use case | 7 | Slot replacement, old slots gone, wrong workspace rejected, retired comp rejected, empty list rejected, non-officer rejected, duplicate (party, index) rejected |
| 3 — GET route | 8 | 200 for officer, build names pre-filled, roles pre-filled, correct form action, 403 for anon, 403 for retired, active-ops notice shown/absent |
| 4 — POST route | 5 | Redirect on success, DB updated, old templates gone, validation error redirect, anon redirect |
| 5 — Frozen snapshot | 3 | Single op unchanged, use-case level edit doesn't touch op slots, multiple ops both frozen |
| 6 — Affordances | 4 | Edit link on detail (officer), edit link absent (retired), edit link on list (officer), edit link absent on list (retired) |

**Validation results:**
```
Tier 1 — collection: 1667 tests collected in 0.66s   ✓
Tier 4 — new tests:  31 passed in 15.30s              ✓
Tier 5 — full suite: 1655 passed in 852.83s           ✓  (0 failed)
```

One pre-existing test updated: `test_continuation_link_renders_for_editable_comp_with_warnings` — the continuation link text changed from "Create a revised composition →" (pointing to `/compositions/new`) to "Edit slots to fix →" (pointing to `/compositions/{comp_id}/edit`). The updated test now also asserts the edit URL is present.

---

### Audit Summary

| Area | Finding |
|---|---|
| Build entity | Does not exist. `build_name` and `weapon_name` are freeform strings on slot template rows. |
| Build library | Does not exist. No `/builds` routes, no `albion_builds` table. |
| Composition edit | ✅ **Shipped.** `GET /edit` + `POST /slots` routes live. Clone-to-fix workflow eliminated. |
| Slot card system | ✅ **Shipped.** Table replaced with `.cb-slot-card` party-grouped editing surface. Role tally headers, state badges, responsive layout. |
| Tactical preview | Fully implemented (Phases 1–6 of `tactical_party_layout_preview_foundation`). |
| Slot snapshot invariant | Sound and regression-tested. `operation_slots` are frozen at generation; editing templates never affects them. |
| Highest friction point | ✅ **Resolved.** Edit-in-place eliminates the 5-step clone → recreate → retire workflow. |
| Prerequisite for Phase 3 | ✅ **Met.** Slot card surface exists. Phase 3 inline build selection can target `cb-slot-build-input` inputs within each card. |
| Build library prerequisite | Edit-in-place and card surface functional. Introduce `albion_builds` when officer demand for reuse tracking is evident. |

---

## Phase 2 — Slot Card System ✅ Shipped — 2026-05-18

Replace the current table-row slot layout with a card-based planning surface that supports faster tactical scanning. This phase is a **presentation-layer change only** — no schema changes, no repository changes, no data model redesign.

### Core Card Component

- [x] Define `.cb-slot-card` component: role input, build name, weapon name, state badges, metadata, remove button
- [x] Implement slot card for composition edit surface (pre-filled from slot templates)
- [x] Implement blank slot cards for composition creation (5 default cards in Party 1)
- [x] Ensure slot cards are accessible and keyboard-navigable (aria-label on all inputs, visible focus states)

### Role-Focused Visual Hierarchy

- [x] Role input is the primary visual element — bold text, role-coloured bottom underline, base font size
- [x] Build name is secondary — compact input box below the role input
- [x] Weapon name is tertiary — borderless underline style, muted colour
- [x] Slot status signalled with left-border accent (role colour) and restrained state badges

### Slot-Level Status Indicators

- [x] Define composition editor card states: `--open` (no build), `--assigned` (has build), `--core` (priority=core), `--critical` (no role)
- [x] Map each state to visual accent via `--role-*` and semantic tokens from `tokens.css` — no hardcoded hex
- [x] CORE badge (gold) and OPEN badge (muted) implemented inside card header
- [x] Open slots visually distinct: dashed left border, reduced opacity, OPEN badge
- [ ] Slot-level quick actions (reassign, clear, flag) — deferred to Phase 3

### Party Group Layout

- [x] Implement `.cb-party-group` sections: groups slot cards by `party_number`
- [x] Party group header: party title, role tally strip (`1T · 1H · 3D`), slot count
- [x] Role tally uses `cb-tally-item[data-role]` — matches scanning shorthand on detail page
- [x] `cb-parties-grid`: multi-column grid on desktop, stacked on tablet, single-column on mobile
- [x] Party group overflow handled by grid `auto-fill minmax(300px, 1fr)` — wraps naturally

### Responsive Slot Layout

- [x] Desktop (> 900px): party groups side by side in multi-column grid
- [x] Tablet (≤ 900px): parties stacked (1 column), slot cards 2-column
- [x] Mobile (≤ 480px): slot cards single-column, full readability

### Form Behaviour Preserved

- [x] All form inputs carry the same `name` attributes as the previous table form — POST handler unchanged
- [x] Form submits correctly without JavaScript (existing slots editable without JS)
- [x] JavaScript adds progressive enhancement: `+ Add slot`, `+ New party`, live role-colour update, badge sync
- [x] `+ New party` creates a new `.cb-party-group` with correct `data-party` and card container

---

### Phase 2 Implementation Log

#### What shipped

**CSS:**
- `app/static/css/composition_builder.css` (new) — 250-line `.cb-*` namespace, isolated from `tactical.css` and `base.css`
- `app/templates/base.html` — new `<link>` for `composition_builder.css`

**Templates:**
- `app/templates/compositions_edit.html` — full rewrite: table replaced with party-grouped `.cb-slot-card` system; same POST action and form input names preserved; progressive-enhancement JS added
- `app/templates/compositions_new.html` — full rewrite: same card system; blank Party 1 with 5 default cards on initial load; `prev_parties` used on error re-render

**Routes:**
- `app/routes.py` — `get_edit_composition` now calls `build_parties()` + `derive_tactical_summaries()` and passes `parties` + `party_summaries` to the template for server-rendered party headers and role tallies
- `app/routes.py` — `get_new_composition` passes `prev_parties: {}` + `prev_party_summaries: {}`
- `app/routes.py` — `get_clone_composition` passes `prev_parties` + `prev_party_summaries` so cloned compositions render with the card system pre-filled
- `app/routes.py` — `post_create_composition` error path now populates `_prev_psumm` in the `else` branch and passes `prev_parties` + `prev_party_summaries` to the template

#### What this phase does NOT include

- No schema changes (`schema.sql` untouched)
- No repository changes
- No operation_slots changes — frozen snapshot invariant preserved
- No drag-and-drop
- No slot-level quick actions (reassign/clear/flag — Phase 3)
- No inline build selection (Phase 3)
- No collapsible party groups (Phase 7)

#### CSS architecture rationale

| Decision | Rationale |
|---|---|
| `.cb-*` namespace | Isolated from `.slot-card` (planner read-only), `.party-panel`, and `.form-*` — no cross-surface bleed |
| Role-coloured left border via `[data-role]` | Matches the existing tactical planner convention; role scanning is the same reflex on both surfaces |
| Left-border `dashed` for `--open` | Communicates "incomplete, not broken" — restrained vs danger-red |
| `cb-badge--core` gold + `cb-badge--open` muted | Core is operationally significant (gold); open is a reminder (faint) — severity hierarchy preserved |
| Party tally format `1T · 1H · 3D` | Mirrors the read-only detail page tally — consistent scanning language |
| `auto-fill minmax()` party grid | 1 party fills the width; 2+ parties sit side by side; no fixed column count needed |
| JS is enhancement-only | Forms work without JS; adding/removing slots requires JS — acceptable (table form had the same JS dependency) |

#### Tactical readability improvements

An officer glancing at the edit surface can now:
- **Identify party structure** — each party is a clearly bordered group with a header
- **Scan role distribution per party** — `1T · 1H · 3D` tally in the party header, without reading individual cards
- **Spot open slots** — dashed left border + OPEN badge; visually lighter than assigned cards
- **Spot core slots** — gold CORE badge in the card header
- **Understand role identity** — left-border colour maps role family before the role text is read
- **Work without page context switching** — the full edit surface is one form, one submit

---

### Phase 2 Files Changed

| File | Change |
|---|---|
| `app/static/css/composition_builder.css` | **New** — `.cb-*` card system, party group grid, responsive breakpoints, state modifiers |
| `app/templates/base.html` | Added `<link>` for `composition_builder.css` |
| `app/templates/compositions_edit.html` | Full rewrite — table replaced with party-grouped slot cards; same form semantics |
| `app/templates/compositions_new.html` | Full rewrite — card system; blank defaults on initial load; `prev_parties` on error re-render |
| `app/routes.py` | Edit route passes `parties` + `party_summaries`; new/clone/error paths pass `prev_parties` + `prev_party_summaries` |
| `tests/test_composition_edit.py` | Added Group 7 — 14 Phase 2 card system tests |
| `tests/test_ui_regression.py` | Updated Group 5 `slot-table` assertion; added Group 9 — 19 card regression tests |

**Files that did NOT change:**
- `app/schema.sql` — no migration
- `app/tactical.py` — no logic changes
- `app/repositories.py` — no changes
- `app/application/use_cases.py` — no changes
- `app/templates/compositions_detail.html` — read-only tactical preview unchanged
- `app/templates/operation_planner.html` — planner slot cards unchanged

---

### Phase 2 Regression Tests

| File | Group | Tests | What it covers |
|---|---|---|---|
| `test_composition_edit.py` | Group 7 | 14 | Party groups present, slot cards present, role labels, build names, CORE badge, OPEN badge, party header tally, form inputs with name+aria-label, POST still works, editor class, add-party button, frozen snapshot invariant with card POST |
| `test_ui_regression.py` | Group 9A | 9 | Edit surface: cb-composition-editor, cb-party-group, data-party attrs, cb-slot-card, role labels, build names, party header tally, CORE badge, form inputs |
| `test_ui_regression.py` | Group 9B | 4 | New composition surface: editor present, default party group, blank cards, form inputs submittable |
| `test_ui_regression.py` | Group 9C | 2 | Multi-party: 2 cb-party-group sections, correct data-party attrs |
| `test_ui_regression.py` | Group 9D | 4 | Non-regression: detail tactical summaries, slot cards, slot-table absent in edit/new surfaces |

**Validation results:**
```
Tier 4 — new tests:  137 passed in 68s   ✓
Tier 5 — full suite: 1706 passed in 875s  ✓  (0 failed)
```

---

### Redirect Hardening — _safe_next() ✅ Shipped — 2026-05-18

A pre-existing test suite failure in `test_discord_oauth.py` (3 failing tests) was resolved as a prerequisite for Phase 3 planning.

**Root cause:** The `_safe_next()` function had been updated to return `"/workspaces"` as its fallback for invalid/empty inputs (the correct authenticated default), but the tests still asserted `"/"` from the original implementation.

**Fix:** Updated 3 test assertions to `"/workspaces"`, renamed `test_safe_next_returns_slash_for_empty` → `test_safe_next_returns_workspaces_for_empty`, added an explicit whitespace-only check to `_safe_next()`, updated the test module docstring, and added 7 new security coverage tests (whitespace, `javascript:`, `ftp://`, `data:`, query strings, bare `/`, parametric sweep).

Fallback policy confirmed: `_safe_next(invalid)` → `"/workspaces"` (authenticated default), not `"/"` (public landing page). Logout explicitly returns `"/"` by design.

**Validation:** `pytest tests/test_discord_oauth.py` → 31 passed. Full suite → 1706 passed, 0 failed.

---

## Phase 3 — Inline Build Management ✅ Shipped

Allow officers to create, edit, and manage builds directly inside the composition editor without navigating to the build library.

### Inline Build Creation

- [ ] Define the inline build creation panel/modal: opens within the comp editor context
- [ ] Minimum viable inline create: name, role, optional notes — saves as a full reusable build
- [ ] Inline create immediately assigns the new build to the triggering slot
- [ ] Confirm that inline-created builds appear in the main build library

### Inline Build Quick-Edit

- [ ] Allow editing build name and notes from within the slot card (without full build detail page)
- [ ] Changes propagate to the shared build entity — all compositions referencing the build see the update
- [ ] Warn officer if the build is referenced by multiple compositions or operations

### Inline Equipment Management

- [ ] Surface equipment slot editor inline within the comp editor (collapsed by default)
- [ ] Allow adding/editing weapons, armour, and accessories without navigating to the build detail page
- [ ] Equipment changes save to the shared build entity in real time (on form submit)

### Inline Swap Management

- [ ] Define swap slot model: alternative build/equipment for a given slot
- [ ] Allow adding swaps inline within the slot card
- [ ] Display active vs alternative configuration clearly

### Save / Update Behaviour

- [ ] Define clear save semantics: inline edits submit to the same build endpoints as the full editor
- [ ] No separate "inline draft" state — inline edits are real saves
- [ ] Provide inline save confirmation (flash or inline status update)
- [ ] Define what happens on unsaved changes when navigating away (browser warn or auto-save)

### Architecture Guardrails

- [ ] All inline build operations go through existing build routes/repositories — no parallel data path
- [ ] No build data is stored as embedded JSON inside composition or slot tables
- [ ] Inline creation reuses the existing build validation logic

---

## Phase 4 — Equipment UX Improvements ✅ Shipped

Improve the equipment selection experience across both the inline comp editor and the standalone build editor.

### Slot-Aware Equipment Selectors

- [ ] Equipment item selector is aware of the slot type (main hand, off hand, head, chest, etc.)
- [ ] Selector filters available items to valid types for the given slot by default
- [ ] Override available: officer can clear the filter and select any item
- [ ] Item name search within the selector

### Item Filtering

- [ ] Filter by equipment category (weapon, armour, accessory, mount, food, potion)
- [ ] Filter by tier (if applicable)
- [ ] Filter by role affinity or weapon type
- [ ] Clear all filters with one action

### Visual Equipment Slot Grouping

- [ ] Group equipment slots visually: weapons together, armour together, accessories together
- [ ] Equipment slot layout follows a recognisable pattern (head → chest → feet → accessories)
- [ ] Missing/unset equipment slots are visually distinct (empty state indicator, not blank)

### Build Validation Visibility

- [ ] Surface incomplete build warnings: empty required equipment slots
- [ ] Surface build readiness state: complete vs incomplete
- [ ] Role vs equipment affinity warning (e.g. tank role but caster weapon selected)
- [ ] Warnings are informational — officers can proceed regardless

### Quick Duplicate / Copy Workflow

- [ ] Duplicate an existing build from the build library or inline context
- [ ] Duplicate creates a new independent build (no shared reference)
- [ ] Duplicate pre-fills name as "Copy of [original name]" — officer renames

### Future Compatibility

- [ ] Equipment data model supports import/export (no proprietary blob format)
- [ ] Item IDs are string-typed to support future Albion Online API item codes
- [ ] Build export format defined (deferred to a future slice, but data model must allow it)

---

## Phase 5 — Tactical Planning UX ✅ Shipped

Transforms composition planning from card-editing into operational tactical orchestration.
Officers can now assess composition health instantly without opening individual cards.

### Tactical Summary Layer

- [x] `tactical.py`: `derive_tactical_summaries` now returns `open_slots` and `open_core` per party, and `open_slots` + `open_core_slots` at composition level
- [x] `tactical.py`: `derive_composition_integrity` emits `core_slots_unfilled` warning when core-priority slots have no build assigned
- [x] Hint wording updated from "missing builds" → "open slots" (cleaner operational language)
- [x] Per-party gap badges updated: "N open" replaces "N no builds"

### Composition Detail Improvements

- [x] Page header now shows `open` badge when composition has unfilled slots
- [x] Page header shows `core unfilled` signal when core-priority slots lack doctrine
- [x] Each party panel header shows per-party open slot count when any slots are unfilled

### Composition Edit Surface (highest-impact addition)

- [x] Tactical planning summary banner added above the slot editor:
  - `N slots · N parties · N open · N core unfilled`
  - Compact role distribution tally: `2T · 1H · 3D · 1S`
  - Inline critical integrity issues (No healer, No tank, core slots unfilled)
  - ARIA `role="status"` and `aria-label` for screen reader accessibility
- [x] Party health state classes: `cb-party-group--critical` (missing healer/tank), `cb-party-group--warn` (open slots)
- [x] Per-party open slot counter in party header: `N open` in amber when present
- [x] "Highlight open" toggle button: dims assigned cards, elevates open ones — with `aria-pressed` state
- [x] Party collapse/expand toggle: `▾/▸` button per party with `aria-expanded` and `aria-label`

### CSS Additions (`composition_builder.css`)

- [x] `.cb-party-group--critical` / `--warn`: left-border accent health states
- [x] `.cb-comp-summary` / `.cb-comp-summary__row` / `.cb-comp-summary__open` / `--core-open` / `--issue`: summary banner primitives
- [x] `.cb-comp-tally` / `.cb-comp-tally__item[data-role]`: role-colored distribution strip
- [x] `.cb-party-header__open`: amber open-slot counter in party header
- [x] `.cb-party-collapse-btn`: collapse toggle with accessible focus states
- [x] `.cb-editor--highlight-open`: JS toggle mode — dims non-open cards
- [x] `.comp-open-badge` / `.comp-party-open` / `.comp-core-unfilled`: detail page open indicators

### Accessibility

- [x] Tactical summary banner: `role="status"`, `aria-label="Composition planning state"`
- [x] Role tally strip: `aria-label="Role distribution"`
- [x] Party open indicator: `aria-label="N open slot(s)"`
- [x] Collapse button: `aria-expanded`, `aria-label="Collapse/Expand Party N"`
- [x] Integrity issue rows: `role="alert"` — readable without color

### Tests (`tests/test_tactical_planning_ux.py`)

- [x] 45 tests across 14 groups: tactical logic (pure Python), route/template rendering, accessibility, snapshot invariant
- [x] `tests/test_tactical_logic.py`: updated 7 hint/gap wording assertions to match new "open" language
- [x] Tier 1: 1855 collected · Tier 2: 45/45 · Tier 4: 153/153 · Tier 5: **1854/1854**

### Architectural decisions

- **No schema changes**: purely UX/rendering — all data derived from existing `composition_slot_templates` at route time
- **Snapshot invariant preserved**: `operation_slots` not touched; Phase 5 does not introduce any operational mutation
- **No frontend framework**: highlight-open and party collapse are ~20 lines of vanilla JS
- **Additive only**: all Phase 5 elements are new CSS classes and new template sections; zero existing output changed

---

## Phase 5.5 — Tactical Doctrine Identity ✅ Shipped

Introduced a lightweight operational field — `doctrine_role` — to express battlefield responsibility without replacing or augmenting the structural role system.

### Problem

`build_name` was overloaded with four concerns: weapon identity, battlefield responsibility, doctrine variant, and tactical intent. Examples like "Hallowfall - Orb", "Bedrock - Def rune", "Great Arcane - Def rune" forced officers to encode orchestration logic into a single freeform text field that tactical summaries could never interpret correctly.

### What shipped

**New field — `doctrine_role TEXT NULL`**

Added to:
- `albion_builds` — build-level default (e.g. a Tombhammer build defaults to "Engage")
- `composition_slot_templates` — snapshot captured at build-attach time; overridable at slot level
- `operation_slots` — frozen at slot-generation time; immutable thereafter

**UI hierarchy change**

Slot cards now render three tiers:

```
DOCTRINE ROLE   ← battlefield responsibility (e.g. Main Caller, Engage, Beam Spike)
ROLE FAMILY     ← structural tactical category (Tank, Healer, DPS, Support)
BUILD / WEAPON  ← execution package (e.g. Hallowfall, 1H Mace)
```

**Doctrine role examples**

- Main Caller
- Stopper
- Engage
- Debuff
- Peel / Stopper
- Peel / Soaker
- Backline Heal
- Support Heal
- Beam Spike
- Utility
- Soak

**Forms**

- `doctrine_role` input added to build create and edit forms (keyboard accessible, no JS dependency)
- `doctrine_role` input added to each slot card in the composition editor (inline, progressive enhancement)
- Build library autofill propagates `doctrine_role` from a selected build when the slot input is empty; slot-level value wins if already set

**Doctrine role is observational, not structural**

- `role_family` remains the sole authority for tactical summaries, integrity warnings, and role-balance calculations
- `doctrine_role` does not drive any tally, gap badge, health-state, or integrity check
- No doctrine taxonomy, no role-system rewrite, no enum, no doctrine relational model was introduced

### Architecture decisions

**Layer separation**

```
role_family     — structural system layer (Tank / Healer / DPS / Support / Ranged)
doctrine_role   — battlefield responsibility layer (freeform, operational, descriptive)
build/equipment — execution package layer (weapon, offhand, armour, consumables)
```

**Snapshot invariant preserved**

`_resolve_build_for_slot` propagates `doctrine_role` from the build record at attach time only. Slot-level override is preserved (non-empty slot value wins). `generate_operation_slots` snapshots `doctrine_role` at generation time. Build edits after generation do not mutate existing `composition_slot_templates` or `operation_slots`. The invariant is identical in structure to the equipment field invariant introduced in Phase 4.

**Migration**

Three idempotent `ALTER TABLE ADD COLUMN` entries added to `_COLUMN_MIGRATIONS` in `app/database.py`. Existing databases upgrade on next startup without data loss.

### Tests (`tests/test_doctrine_role.py`)

36 tests across 10 groups: domain validation, repository round-trips, use-case propagation, `_resolve_build_for_slot` override semantics, snapshot invariants (composition templates + operation slots), composition create/update propagation, tactical summaries still role_family-based, route GET/POST, composition rendering (detail + edit), nullable/blank semantics.

**Validation:** Tier 1: 1890 collected · Tier 2: 36/36 · Tier 4: 285/285 · Tier 5: **1890/1890**

---

## Phase 6 — Operational Workflow Acceleration

Make IronkeepV2 faster than spreadsheet workflows for the highest-frequency officer actions.

### Operational finding

Real testing revealed that the build library is no longer the primary bottleneck. The bottleneck is **authoring speed, player assignment, and tactical mutation** after signup reality is known. Officers currently reach for spreadsheets because:

- Creating a 20–40 slot composition manually in Ironkeep takes significantly longer than copying a spreadsheet structure
- Assigning 20+ signed-up players to slots has no streamlined workflow path
- Switching a weapon or build mid-preparation requires re-navigating multiple forms
- Creating a Brawl/Kite variant of an existing comp requires rebuilding it from scratch

Phase 6 addresses these friction points directly. Build Library Evolution (formerly Phase 6) is sound architecture, but its value compounds faster once officers are authoring and mutating comps at speed. It has been deferred to Phase 7.

### Spreadsheet-Compatible Rapid Entry

- [ ] Add paste/import mode for tabular comp data
- [ ] Support TSV/CSV-style paste from existing guild sheets
- [ ] Map columns to `doctrine_role`, role_family, build, weapon, equipment, party, slot
- [ ] Validate parsed rows before applying; reject partial/malformed input cleanly
- [ ] Show preview before confirming import
- [ ] Preserve server-rendered form fallback for non-paste workflows

### Fast Tactical Mutation ✅ Shipped (Slice 1 — 2026-05-20)

- [x] Quick-replace weapon/build in a selected slot without re-opening the full edit surface
- [x] Duplicate slot and modify variant fields only
- [x] Replace one build across selected slots or an entire party in one action
- [x] Clone composition variant (pre-filled name "Copy of …") and change only affected slots
- [x] Preserve frozen operation snapshot invariant throughout all mutation paths

**Validation:** 30 targeted tests (`test_fast_mutation.py`). Tier 5: 1920/1920.

### Assignment Workflow Foundation ✅ Shipped (Slice 2 — 2026-05-20)

- [x] Improve assigning signed-up players to operation slots — promoted manual assign (no `<details>` gate)
- [x] Doctrine role visible in planner slot headers (Phase 5.5 field surfaced in planner view)
- [x] `reassign_slot` use case — atomic swap in one DB transaction (no intermediate unassigned state)
- [x] Swap action on assigned slots with unassigned participant dropdown
- [x] Assign-from-left-panel: each unassigned signup card gets a slot selector for the human→slot direction
- [x] `open_slots` context passed to planner template for dropdown population
- [x] Preserve `operation_slots` as frozen assignment state

**Validation:** 25 targeted tests (`test_assignment_workflow.py`). Tier 5: 1945/1945.

### Build-Name Suggestions (Datalist) ✅ Shipped (Slice 3 — 2026-05-22)

**Problem:** Officers typing `build_name` and `weapon_name` in any composition slot card (new, edit, planner build edit) receive no suggestions. Recurring build names are retyped from memory each time, introducing spelling inconsistencies and slowing authoring.

**Constraint:** No albion_builds table, no item metadata, no tiers/enchantments, no JS-heavy autocomplete widget.

**Data source (safe):** `composition_slot_templates.build_name` / `weapon_name` — distinct non-empty values scoped to `guild_workspace_id`. This is workspace-owned data officers themselves entered. No new table, no migration, no schema change needed.

The query is safe for empty workspaces (returns empty list, inputs work normally). The `guild_workspace_id` column on `composition_slot_templates` already has an index via `idx_composition_slot_templates_composition` — the DISTINCT query is not a table-scan risk.

**Integration approach:** native HTML `<datalist>` elements, injected server-side into each form render. No JS required. Degrades gracefully in any browser. No additional HTTP round-trip.

```html
<!-- rendered once per page in the form, then referenced by all build inputs -->
<datalist id="build-name-list">
  {% for n in build_name_suggestions %}<option value="{{ n }}">{% endfor %}
</datalist>
<datalist id="weapon-name-list">
  {% for n in weapon_name_suggestions %}<option value="{{ n }}">{% endfor %}
</datalist>

<!-- on every slot card text input -->
<input type="text" name="build_name" list="build-name-list" ...>
<input type="text" name="weapon_name" list="weapon-name-list" ...>
```

JS-generated slot cards (`_createSlotCard`) also need `list=` on their `build_name` and `weapon_name` inputs. The datalist is already in the DOM, so existing `WORKSPACE_BUILDS` data-autofill is unaffected.

**Files shipped:**

| File | Change |
|------|--------|
| `app/repositories.py` | `get_distinct_slot_build_suggestions(db, ws_id)` → `{build_names: [...], weapon_names: [...]}` |
| `app/routes.py` | `build_name_suggestions` / `weapon_name_suggestions` passed to `get_new_composition`, `get_edit_composition`, `get_planner` |
| `app/templates/compositions_new.html` | Datalist elements added; `list=` on server-rendered + JS `_createSlotCard` inputs |
| `app/templates/compositions_edit.html` | Same |
| `app/templates/operation_planner.html` | Datalist elements added; `list=` on slot build edit inputs |
| `tests/test_build_suggestions.py` | 31 tests across 5 groups: repository (9), new composition (7), edit composition (6), planner (7), JS card (2) |

**Validation:** Tier 2: 31/31. Tier 4: 352/352 (no regressions).

**Explicit non-scope:** spell database, item tiers, enchantments, passives, full-text JS search widget, albion_builds table dependency, drag-and-drop.

### New Operation from Composition Shortcut ✅ Shipped (Slice 4 — 2026-05-22)

Officers can click **"New Operation →"** from a composition detail page and arrive
at the new operation form with that composition pre-selected. After the operation is
created, the composition is automatically attached in the same POST flow — collapsing
the two-step "create → attach" sequence into a single action.

**Data flow:** `compositions_detail.html` → `GET /operations/new?composition_id=…` →
`operation_new.html` (hidden field) → `POST /operations` → `attach_operation_plan()`
→ redirect to operation detail with success message.

**Guard rules:**
- Retired compositions silently ignored in GET (no `preset_comp`); guard in POST
  validates `deleted_at` before calling `attach_operation_plan` (which does not
  check retirement itself).
- Cross-workspace composition IDs silently ignored (repository enforces workspace scope).
- If attachment fails after operation creation, the officer is redirected to the detail
  page with an error note; the standard attach form is still available. The operation
  is never rolled back.
- The `{% if can_mutate and not comp.deleted_at %}` guard on the button is unchanged.

**Files shipped:**

| File | Change |
|------|--------|
| `app/templates/compositions_detail.html` | Added `?composition_id={{ comp.id }}` to "New Operation →" link href |
| `app/routes.py` — `get_new_operation` | Reads `composition_id` query param; fetches and validates comp; passes `preset_comp` |
| `app/templates/operation_new.html` | Renders `preset_comp` display + hidden field above title when set |
| `app/routes.py` — `post_create_operation` | After creation: verifies comp is active, calls `attach_operation_plan`, redirects with message |
| `tests/test_new_op_from_comp.py` | 20 tests across 4 groups: GET param (7), POST with preset (7), template affordances (3), snapshot invariant (3) |

**Validation:** Tier 4: 20/20. Tier 5: 1996/1996 (no regressions).

### Zero-Slot Compositions (Named Shell Authoring) ✅ Shipped (Slice 5 — 2026-05-22)

Officers can save a new composition with only a valid name (and optional description), without providing any slot templates at creation time. Slots are added later via Edit Slots. This removes the "must have at least one slot" authoring gate that previously blocked saving partial work.

**What a zero-slot composition is:**
- Active (`deleted_at IS NULL`) — not a draft, not a special state
- Editable — officers add slots via the existing Edit Slots page
- Attachable — can be attached to an operation and generate operation slots (producing 0 slots, a valid empty snapshot)
- Visible in the compositions list with "0 (no slots yet)" linked to the Edit Slots page

**What it is NOT:**
- Not a draft state — no `status` column, no `draft → active` lifecycle
- Not abusing `deleted_at` — retired semantics are unchanged

**Key semantic boundaries:**
- `create_albion_composition(slots=[])` → allowed (named shell)
- `update_composition_slots(slots=[])` → still rejected ("Clearing all slots via Edit is not allowed. Use Retire to decommission a composition.") — accidental blanking through the edit form is blocked
- `generate_operation_slots` from a zero-slot composition → returns `[]` without error

**Files shipped:**

| File | Change |
|------|--------|
| `app/domain/albion_compositions.py` | Removed `if not slots: raise ValidationError(...)` guard from `validate_slot_templates`; updated docstring |
| `app/application/use_cases.py` | `update_composition_slots`: explicit guard before domain call; `generate_operation_slots`: removed `validate_plan_has_templates` call |
| `app/templates/compositions_new.html` | Added muted hint: "Slots can be added after saving. A card is only saved when both role and build name are filled in." |
| `app/templates/compositions_list.html` | Zero-slot active compositions show `0 (no slots yet)` linked to Edit Slots |
| `app/templates/compositions_detail.html` | Empty-state block now centred with `btn btn-primary` "Edit Slots →" CTA |
| `tests/test_slot_template_model.py` | `test_generate_slots_requires_at_least_one_template` → renamed/inverted to `test_create_zero_slot_composition_is_allowed` |
| `tests/test_zero_slot_compositions.py` | 22 tests across 6 groups: domain validator, create use case, edit guard, routes, template rendering, integration invariants |

**Validation:** Tier 2: 6/6. Tier 4: 22/22. Tier 5: 2018/2018 (no regressions, +22 tests).

**Explicit non-scope:** no schema change, no migration, no draft status, no publication lifecycle, no status column.

### Zero-Slot / Empty-Operation Tactical Warnings ✅ Shipped (Slice 6 — 2026-05-23)

Officers see clear, informational, non-blocking warnings at every decision point where a zero-slot composition or an operation with no generated slots would otherwise silently produce unexpected results.

**What changed:**

- **Operation detail — Tactical Composition card:** When an active zero-slot composition is attached, a muted note reads "The attached composition currently has no slot templates yet. Edit Slots →"
- **Operation detail — Roster Slots card:** The "Generate Slots" button is hidden when `composition_slot_count == 0`. An informational note with "Edit Slots →" link replaces it.
- **post_generate_slots flash message:** When 0 slots are generated (zero-slot composition), the flash reads "0 slots generated — the attached composition currently has no slot templates. Add slots to the composition, then generate again." instead of the generic "0 slots generated."
- **Operation planner — party grid empty state:** Split into two messages: if a plan is attached, "No roster slots — the attached composition may not have slot templates yet. Return to Overview →"; otherwise the existing generic "No roster slots generated yet…" message.

**What did NOT change:**

- No blocking — officers can still attach, navigate, and generate freely
- No new lifecycle state — zero-slot compositions remain active (`deleted_at IS NULL`)
- No schema change — `composition_slot_count` is computed at render time from `get_composition_slot_templates`
- All guards are informational only

**Files shipped:**

| File | Change |
|------|--------|
| `app/routes.py` — `get_operation_detail` | Computes `composition_slot_count` from `get_composition_slot_templates`; passes to template context |
| `app/routes.py` — `post_generate_slots` | Descriptive flash message when 0 slots are generated |
| `app/templates/operation_detail.html` | Tactical Composition card: zero-slot note + Edit Slots link; Roster Slots card: hides Generate button when `composition_slot_count == 0` |
| `app/templates/operation_planner.html` | Party grid empty state split by `plan` presence |
| `tests/test_zero_slot_warnings.py` | 11 tests across 4 groups: Tactical Composition card, Roster Slots card, flash message, planner empty state |

**Validation:** Tier 4: 11/11. Tier 5: 2029/2029 (no regressions, +11 tests).

**Explicit non-scope:** no blocking validation, no schema change, no new lifecycle state.

### Per-Slot Promote Operation Build to Composition Template ✅ Shipped (Slice 7 — 2026-05-23)

Officers can intentionally apply one operation-slot build edit back to its source composition slot template — per-slot, on-demand, officer-initiated. Not auto-sync.

**What changed:**

- **`repositories.py`:** Added `get_composition_slot_template_by_id(db, template_id, guild_workspace_id)` — workspace-scoped single-row fetch.
- **`repositories.py`:** Fixed pre-existing bug in `update_operation_slot_build` — removed `updated_at` from UPDATE (column does not exist on `operation_slots`).
- **`routes.py`:** Added `POST /workspaces/{slug}/operations/{op_id}/slots/{slot_id}/apply-to-template`. Guards: officer permission, slot scoped to operation and workspace, slot must have a source template ID, source template must still exist, source composition must not be retired. Calls `quick_update_composition_slot`. Redirects to planner with success/error flash.
- **`app/templates/_planner_macros.html`:** `planner_slot_build_editor` macro extended with a second form ("Apply to composition template →") rendered only when `slot.source_composition_slot_template_id` exists.

**What did NOT change:**

- Operation slots are untouched (snapshot invariant preserved)
- Other operations sharing the same source composition are unaffected
- No auto-sync — explicit officer action only
- No schema change, no new use case beyond reusing `quick_update_composition_slot`

**Files shipped:**

| File | Change |
|------|--------|
| `app/repositories.py` | `get_composition_slot_template_by_id`; fixed `update_operation_slot_build` |
| `app/routes.py` | `post_apply_slot_to_template` route |
| `app/templates/_planner_macros.html` | Second form in `planner_slot_build_editor` macro |
| `tests/test_promote_to_template.py` | 19 tests across 5 groups |

**Validation:** Tier 4: 19/19. Tier 5: 2048/2048 (no regressions, +19 tests).

**Explicit non-scope:** no auto-sync, no bulk sync, no schema change, no new use case.

---

### Stabilization Slice ✅ Shipped (2026-05-23)

Targeted structural improvements before further feature expansion: documentation and template macro extraction.

**What changed:**

- **`docs/testing_strategy.md`:** Updated Tier 3 and Tier 4 command lists to include all Phase 6/7 test files. Total test count updated to 2048.
- **`app/templates/_planner_macros.html`:** Created with `planner_slot_build_editor` macro.
- **`app/templates/operation_planner.html`:** Extracted inline `<details class="slot-build-edit">` block into the macro call. Template line count dropped from 631 to 606.

**What did NOT change:** No behavior change. No route change. No schema change.

**Validation:** Tier 1: 2048 collected. Tier 4: 163/163.

**Explicit non-scope:** no file splits, no route refactor, no frontend framework.

---

### Composition Variant Cloning UX Polish ✅ Shipped (Slice 8 — 2026-05-23)

Improved discoverability and usability of the existing clone workflow. Officers can now initiate variant clones directly from the list or detail page and receive contextual guidance in the clone form.

**What changed:**

- **`routes.py` — `get_clone_composition`:** Reads optional `?variant=` query param. Name pre-fills as `"{source} — {variant}"` when present, otherwise `"Copy of {source}"`. Passes `cloned_from_name` and build/weapon datalist suggestions to the template.
- **`routes.py` — `get_new_composition`:** Passes `cloned_from_name: None` so the template condition is always defined.
- **`routes.py` — `post_create_composition` (validation re-render):** Passes `cloned_from_name: None` and build/weapon suggestions on validation failure.
- **`app/templates/compositions_list.html`:** Added `Clone →` button (`btn btn-sm btn-ghost`) in the active composition actions column, guarded by `can_mutate and not comp.deleted_at`.
- **`app/templates/compositions_detail.html`:** Added `Brawl · Kite · Anti-Clap` variant shortcut links below the "Clone as Variant →" button, guarded by `not comp.deleted_at`. Each links to `/clone?variant=<name>`.
- **`app/templates/compositions_new.html`:** When `cloned_from_name` is set, renders a muted `"Starting from <source> — edit the name, adjust the slots, then save…"` strip at the top of the form.

**What did NOT change:**

- Clone remains GET prefill → normal POST create
- No schema change, no new use case, no new domain model
- No variant taxonomy, no enums, no doctrine types

**Files shipped:**

| File | Change |
|------|--------|
| `app/routes.py` | `get_clone_composition`, `get_new_composition`, `post_create_composition` re-render |
| `app/templates/compositions_list.html` | Clone link in active composition actions |
| `app/templates/compositions_detail.html` | Brawl/Kite/Anti-Clap variant quick-links |
| `app/templates/compositions_new.html` | Clone banner when `cloned_from_name` is set |
| `tests/test_clone_variant_ux.py` | 10 tests across 4 groups |

**Validation:** Tier 4: 10/10. Tier 5: 2058/2058 (no regressions, +10 tests).

**Explicit non-scope:** no schema change, no new use case, no variant taxonomy, no build/item system.

### Doctrine Variants

- [ ] Support creating composition variants: Brawl, Kite, Anti-Clap, Defensive Peel
- [ ] Allow variant cloning from an existing composition
- [ ] Track variant purpose in composition metadata or notes field
- [ ] Avoid full version-history complexity in this phase

### Ability / Preset Readiness

- [ ] Add lightweight ability preset fields or notes for Q/W/passive expectations per slot
- [ ] Keep ability presets as text/numeric fields — snapshot-friendly, no spell database
- [ ] Do not build a full Albion Online spell database in this phase
- [ ] Ensure assignment delivery can eventually include preset expectations in operation slot payloads

### Keyboard-First Editing

- [ ] Tab order through slot cards follows visual reading order (party → slots within party)
- [ ] All slot card fields directly focusable without mouse interaction
- [ ] Slot quick actions (clear, duplicate, flag) accessible via keyboard
- [ ] No hover-only interactions in the critical editing path

### Success Criteria

- [ ] Officer can create a 20-slot composition from spreadsheet data in under 2 minutes
- [ ] Officer can change one weapon/build in under 10 seconds
- [ ] Officer can assign 20+ signups faster in Ironkeep than in the current spreadsheet workflow
- [ ] Officer can create a Brawl/Kite variant without rebuilding the comp from scratch
- [ ] Spreadsheet remains useful as source data; Ironkeep becomes faster for operation execution

---

## Deferred from Phase 6

The following items were listed in the Phase 6 spec but were not shipped. They are recorded here so they are not silently lost when Phase 7 begins.

### Spreadsheet / Paste Import

**What it is:** A paste or import mode that lets officers enter a large composition from an existing guild spreadsheet (TSV/CSV or free-paste) without manually filling every slot card.

**Why it was deferred:**

- It is architecturally distinct from every slice shipped in Phase 6. All Phase 6 slices stayed within SSR form POST semantics. Paste import requires a new interaction model: a textarea or file input, server-side row parsing, column detection or explicit mapping, a preview/confirm step before applying, and robust validation messaging for malformed or incomplete rows.
- Rushing it as a Phase 6 closing slice would either underscope the interaction (fragile parsing, no preview) or stall the phase indefinitely.
- It needs a dedicated audit and planning pass before implementation — the same process used for every Phase 6 slice.

**Where it belongs:** Its own named slice (Phase 6.9 or Phase 7 opener), with a full audit prompt before implementation. The audit should evaluate: paste surface UX, column mapping strategy, server-side parsing safety, batch insert transaction model, and preview/confirm flow.

**Current workaround:** Clone an existing composition and adjust slots, or use zero-slot authoring progressively. Neither matches paste-import speed for large initial comps, but both are viable for officers who have already migrated their core comp library into Ironkeep.

---

### Doctrine Variant Notes Field

**What it is:** A structured notes or purpose field on a composition to record its variant intent (e.g., "anti-dive kite variant", "defensive brawl"). Separate from the comp name.

**Why it was deferred:** Non-blocking. Variant identity is already carried in the composition name via the S8 `"{source} — {variant}"` naming convention. Officers can read "ZvZ 5-Man — Brawl" without a separate field. The notes field is polish, not a workflow blocker.

**Where it belongs:** Earliest natural home is Phase 8 (Responsiveness and Interaction Efficiency), as an opt-in metadata field on the composition form. No schema migration required if the existing `description` field is reused; one `ALTER TABLE ADD COLUMN` migration if a dedicated field is preferred.

---

### Ability Presets / Slot-Level Notes

**What it is:** Lightweight Q/W/passive expectation notes per slot (e.g., "run Purge", "slot 3: Holy Water focus"). Text fields, not a spell database.

**Why it was deferred:** Listed in the Phase 6 spec as an aspiration, never concretely scoped. The domain problem (surfacing expected ability usage in the planner) is real but lower priority than assignment and variant workflows.

**Where it belongs:** Phase 8 — interaction efficiency. Slot-level notes would add one text field to the slot card editor and one column to `composition_slot_templates` / `operation_slots`. Snapshot semantics are identical to `doctrine_role`.

---

### Keyboard-First Editing

**What it is:** Ensuring tab order, direct field focus, and quick-action keyboard access throughout the slot card editor.

**Why it was deferred:** An interaction efficiency concern that belongs structurally in Phase 8 (Responsiveness and Interaction Efficiency), which already lists keyboard efficiency in its spec.

**Where it belongs:** Phase 8.

---

### Roadmap Note

Phase 7 (Build Library Evolution) may now begin.

If **authoring speed for large compositions** reasserts itself as the dominant operational pain before Phase 7 work begins, the recommended next action is:

> **Audit spreadsheet/paste import first.** Do not implement. Deliver: interaction model options, parsing strategy, preview/confirm UX, server-side batch insert design, test plan, and implementation prompt. Then decide whether it opens Phase 7 or ships as a standalone Phase 6.9 slice.

If the active friction point shifts to **build library management** (searching, reusing, forking builds across multiple comps), proceed directly to Phase 7 as specified.

---

## Phase 7 — Build Library Evolution

Reposition the build library from the primary workflow entry point to a shared asset management surface.

### Build Usage Discovery ✅ Shipped (Slice 1 — 2026-05-24)

Officers can now see where each build is used across the composition library. The existing `albion_build_id` FK in `composition_slot_templates`, which has been written since Phase 3 but never surfaced, is now visible on every build surface.

**What changed:**

- **`repositories.py`:** `get_build_usage_compositions(db, build_id, ws_id)` — returns distinct active compositions referencing a build via FK (retired compositions excluded). `get_builds_with_usage_counts(db, ws_id)` — builds list augmented with `usage_count` via LEFT JOIN.
- **`routes.py` — `get_builds_list`:** Uses `get_builds_with_usage_counts`; reads optional `?role=` filter param; collects `available_roles` for the filter pill row.
- **`routes.py` — `get_build_detail`:** Fetches and passes `used_in` composition list.
- **`routes.py` — `get_edit_build`:** Fetches and passes `usage_count`.
- **`builds_list.html`:** Role filter pill row (rendered when 2+ distinct roles exist). `bld-card__usage` badge showing "used in N comp(s)" — only when `usage_count > 0`.
- **`builds_detail.html`:** "Referenced by N active composition(s)" card with linked composition names. Section omitted entirely when unreferenced.
- **`builds_edit.html`:** Muted informational note — "This build is referenced in N active composition(s). Editing it will not change existing slot templates — the snapshot invariant is preserved." Rendered only when `usage_count > 0`.

**What did NOT change:**

- No schema change — reads the existing `albion_build_id` FK
- No new use case, no new domain entity
- No write paths touched — entirely read-only discovery
- String-based slots (FK = NULL) and FK-linked slots continue to coexist permanently
- No blocking or gating — all signals are informational

**Files shipped:**

| File | Change |
|------|--------|
| `app/repositories.py` | `get_build_usage_compositions`; `get_builds_with_usage_counts` |
| `app/routes.py` | `get_builds_list`, `get_build_detail`, `get_edit_build` |
| `app/templates/builds_list.html` | Role filter pills; usage count badge |
| `app/templates/builds_detail.html` | "Used in compositions" section |
| `app/templates/builds_edit.html` | Informational snapshot invariant note |
| `tests/test_build_usage.py` | 25 tests across 6 groups |

**Validation:** Tier 2+4: 25/25. Tier 5: 2083/2083 (no regressions, +25 tests).

**Explicit non-scope:** no schema change, no visibility/ownership states, no fork-before-edit, no version history.

---

### Build Fork ✅ Shipped (Slice 2 — 2026-05-24)

Officers can now create an independent copy of any active library build, pre-filled with all source fields. The fork renders the standard create-build form (`builds_new.html`) via a `GET /workspaces/{slug}/builds/{build_id}/fork` route, and the officer POSTs to the existing `/builds` create route — no new write path.

**What changed:**

- **`routes.py` — `get_fork_build`:** New `GET /workspaces/{slug}/builds/{build_id}/fork` route. Requires officer/owner mutation permission. Returns 403 for viewers, 404 for missing or retired source builds. Prefills `prev` dict with all source fields; sets `name` to `"Copy of {source.name}"`. Passes `forked_from_name` and `forked_from_id` to the template.
- **`routes.py` — `get_new_build`:** Now explicitly passes `forked_from_name: None` and `forked_from_id: None` so the fresh new-build form never renders the fork banner.
- **`routes.py` — `post_create_build` (validation re-render):** Also passes `forked_from_name: None` and `forked_from_id: None` to the re-render path so validation errors on a fresh form don't accidentally show a banner.
- **`builds_new.html`:** Conditional fork banner ("Forked from **{source}** — update the details and save…") rendered only when `forked_from_name` is set. Armour `<details>` and Consumables `<details>` auto-open when the corresponding `prev` fields are non-empty.
- **`builds_detail.html`:** "Fork →" button added beside Edit in the `action-group`, conditional on `can_mutate and not build.retired_at`.
- **`builds_list.html`:** "Fork →" link added beside Edit in `bld-card__actions`, same guard condition.

**What did NOT change:**

- No schema change — forked build is a plain independent row with no FK back to source
- No new use case — reuses `create_albion_build` via the existing POST route
- No `composition_slot_templates` writes, no `operation_slots` writes
- No snapshot invariant impact
- No versioning, lineage tracking, or visibility states
- String-based and FK-linked slots continue to coexist permanently

**Files shipped:**

| File | Change |
|------|--------|
| `app/routes.py` | `get_fork_build` (new); `get_new_build` and `post_create_build` re-render pass `forked_from_name: None` |
| `app/templates/builds_new.html` | Fork banner; auto-open `<details>` sections |
| `app/templates/builds_detail.html` | "Fork →" button beside Edit |
| `app/templates/builds_list.html` | "Fork →" link beside Edit |
| `tests/test_build_fork.py` | 26 tests across 6 groups |

**Validation:** Tier 4: 26/26. Tier 5: 2109/2109 (no regressions, +26 tests).

**Explicit non-scope:** no schema change, no fork lineage, no item metadata, no versioning.

---

### Promote Composition Slot to Library Build ✅ Shipped (Slice 3 — 2026-05-24)

Officers can now create a new library build from any free-typed composition slot (one where `albion_build_id IS NULL`) and immediately link that slot to the new build — in a single atomic transaction.

**What changed:**

- **`app/application/use_cases.py`:** New `promote_composition_slot_to_build(guild_workspace_id, composition_id, slot_id, actor_user_id) -> dict`. Runs in one transaction: validates actor, composition (not retired), slot (must belong to composition + workspace, `albion_build_id` must be NULL, `build_name` must be non-empty, `weapon_name` must be non-empty). Creates `albion_build` from slot fields (name, role, weapon, doctrine_role, all equipment fields). Backfills `albion_build_id` on the targeted slot only. Touches composition `updated_at`. Returns new build dict.
- **`app/routes.py`:** New `POST /workspaces/{slug}/compositions/{comp_id}/slots/{slot_id}/promote-to-build`. Requires officer/owner. On success: redirects to composition detail with `?success=`. On `IronkeepError`: redirects with `?error=` flash. On `NotFoundError`: 404. On `PermissionDenied`: 403.
- **`app/templates/compositions_detail.html`:** Third `<form>` added inside each slot's quick-edit `<details>` panel, after the Save form. Rendered only when `can_mutate`, composition is not retired, `slot.build_name` is set, `slot.weapon_name` is set, and `slot.albion_build_id` is empty.

**What did NOT change:**

- No schema change
- No automatic migration — promotion is always officer-initiated per-slot
- No bulk promotion — only the single targeted slot is updated
- No `operation_slots` writes — snapshot invariant fully preserved
- No item metadata, no versioning, no visibility states
- Duplicate build names are allowed — no uniqueness check
- All other `composition_slot_templates` rows remain untouched
- `build_name` and `weapon_name` text snapshots on the promoted slot are unchanged after promotion (they match the new build's fields since the build was created from them)

**Files shipped:**

| File | Change |
|---|---|
| `app/application/use_cases.py` | `promote_composition_slot_to_build` (new use case, atomic) |
| `app/routes.py` | `POST .../slots/{slot_id}/promote-to-build` |
| `app/templates/compositions_detail.html` | "Promote to library →" form in quick-edit panel |
| `tests/test_promote_to_build.py` | 33 tests across 5 groups |

**Validation:** Tier 2: 21/21. Tier 4: 33/33. Tier 5: 2142/2142 (no regressions, +33 tests).

**Explicit non-scope:** no schema change, no bulk promotion, no versioning, no item metadata, no auto-migration of existing free-typed slots.

---

### Repositioning

- [ ] Build library is reached from "Manage builds" in quick actions — not the default planning entry point
- [ ] Build library is presented as an advanced/shared resource management surface
- [ ] Primary comp planning workflow never forces officers to navigate to the build library first

### Build Visibility and Ownership

- [ ] Define build visibility states: workspace-shared (default), restricted (officer-only), private (creator-only)
- [ ] Restricted builds do not appear in inline selection for non-officers
- [ ] Private builds are only visible to the creating officer
- [ ] Visibility state is shown in the build library list

### Search and Filtering

- [ ] Build list search by name, role, and tag
- [ ] Filter by role, visibility state, and last-modified date
- [ ] Sort by: most recently edited, most frequently used, name
- [x] "In use" indicator: shows which compositions currently reference a given build

### Build Reuse Workflows

- [x] "Used in" list on build detail: which compositions reference this build
- [x] Allow officer to promote a free-typed composition slot to a library build
- [ ] Warn before editing a build that is referenced by multiple active operations
- [x] Allow officer to fork a build before editing if wide impact is detected

### Template and Versioning (Future)

- [ ] Define build template concept: a locked reference build that comps copy from rather than share
- [ ] Version history model: track build edits with timestamps (full implementation deferred)
- [ ] Export build as standalone JSON for sharing or backup (data model must support this)

---

### Phase 7 Closure (2026-05-24)

**Phase 7 is closed.** Three slices were shipped, addressing the highest-friction build library gaps.

**Achieved:**
- Build usage visibility: usage counts on build list, "used in" section on build detail, snapshot invariant note on edit page, role filter pills (S1).
- Build fork: independent copy of any active build via GET prefill → POST create, with fork banner and affordances on list/detail (S2).
- Promote slot to library: free-typed composition slot → new library build + FK backfill on that slot, atomic, per-slot, officer-initiated (S3).

**Checklist items not completed and rationale:**

| Item | Decision |
|---|---|
| Repositioning (3 items) | Checklist debt — the build library is already a secondary surface. No officer workflow forces navigation there first. |
| Build Visibility/Ownership (4 items) | Explicitly deferred — requires schema change, new domain model, significant testing. Not a current pain point. |
| Build list search by name/role/tag | Speculative — only painful at >50 builds. Role filter pills (S1) already handle the common case. |
| Build list sort options | Speculative — alphabetical ordering is adequate at current scale. |
| Warn before editing a wide-impact build (active operations) | Partially addressed by S1 edit-page composition count note. Remaining "active operations" dimension is a clean future slice if officers report it as pain. |

**Deferred items (available as standalone slices if needed):**
- `get_build_active_operation_count` + `usage_in_operations` context on edit page — estimated 1-day slice, no schema change.
- Build list name filter (client-side JS) — estimated half-day slice.
- Visibility/Ownership states — requires Phase-level planning; not Phase 7 material.

**Phase 8 (Responsiveness / Interaction Efficiency) may now begin.**

---

## Phase 8 — Responsiveness and Interaction Efficiency

Ensure the composition builder remains usable and tactically readable across all common officer screen sizes.

### Slice 1 — Scroll Anchoring + Auto-Readiness on Assignment ✅ Shipped (2026-05-24)

**Goal:** Make assignment mutations in the planner feel faster without adding JavaScript.

**Part A — Scroll anchoring:**
- Added `id="party-{{ party_num }}"` to every `<section class="card party-panel">` in `operation_planner.html`.
- All six assignment mutation routes now resolve the affected slot's `party_number` and append `#party-{N}` to the redirect URL: `post_assign`, `post_assign_participant`, `post_reassign_slot`, `post_remove_assignment`, `post_quick_assign`, `post_quick_fill_party`.
- The browser scrolls directly to the modified party after every POST-redirect cycle.

**Part B — Auto-readiness on every assign:**
- Fixed `assign_slot_to_participant` use case, which previously only recalculated readiness when a reserve was cleaned up. It now unconditionally calls `_recalculate_readiness` — consistent with `quick_assign_slot`, `quick_fill_party`, `remove_assignment`, and `reassign_slot` which already did so.
- No route-level recalculation calls needed; all mutation paths recalculate within their own transaction.

**Label rename:** "Recalculate Readiness" → "Refresh Readiness" on the manual button in `operation_planner.html`. Button and route preserved.

**Files changed:** `app/templates/operation_planner.html`, `app/routes.py`, `app/application/use_cases.py`.

**Tests:** `tests/test_planner_scroll_and_readiness.py` — 17 tests across 5 groups: party anchor rendering, redirect anchors (all 6 routes including multi-party correctness), auto-readiness coverage (regression for conditional-recalc bug), manual Refresh Readiness button, label rename assertions.

**Validation:** Tier 4: 17/17. Tier 5: 2159/2159 (no regressions, +17 tests).

### Slice 2 — Compact Mode for Composition Detail ✅ Shipped (2026-05-25)

**Goal:** Reduce vertical noise on the composition detail page for officers scanning large compositions — hide equipment doctrine summaries and secondary build names behind a `?compact=1` query parameter, with no JS required.

**Route change:** `get_composition_detail` in `routes.py` reads `compact_mode = request.query_params.get("compact", "") == "1"` and passes the boolean to the template. Only the string `"1"` is truthy; `?compact=0` and absent both yield `False`.

**Template changes:** `compositions_detail.html`:
- **Toggle link** inline next to the `<h2>Tactical Layout — preview</h2>` heading: "Compact view" → `?compact=1` in full mode; "Full view" → bare detail URL in compact mode. Uses `hint-link` class to stay visually muted.
- **Equipment doctrine summary** (`doctrine_summary` macro, `bld-doctrine` class): `{% if _has_eq and not compact_mode %}` — multi-line armour + consumables block hidden in compact mode.
- **Secondary build name** (`slot-card__build`): `{% if secondary and not compact_mode %}` — hidden when `weapon_name ≠ build_name` and compact mode is active.

Preserved in both modes: role labels, primary weapon/build name, state border colours, party summary strip (role tally + gap badges), role colour bar, composition integrity warnings, quick-edit panel, and all action buttons.

**Files changed:** `app/routes.py`, `app/templates/compositions_detail.html`.

**Tests:** `tests/test_compact_composition_detail.py` — 14 tests across 3 groups: full mode (equipment/secondary rendered, toggle links to `?compact=1`), compact mode (both hidden, toggle links back, role/weapon/party-summary/color-bar/quick-edit all preserved), edge cases (`?compact=0` as full mode, no-equipment slot, weapon == build_name).

**Validation:** Tier 4: 14/14. Tier 5: 2173/2173 (no regressions, +14 tests).

### Slice 3 — Complete Planner Anchor Coverage ✅ Shipped (2026-05-25)

**Goal:** Extend the S1 `#party-N` scroll anchor to the two remaining planner mutation routes that still redirected to the top of the page after every POST.

**Route changes:** `app/routes.py`

- `post_update_slot_build` — operation slot was already fetched inside the auth transaction for the operation-id guard check. `party_anchor` extracted from the already-fetched slot at zero extra DB cost; appended to success and IronkeepError redirects. The early `build_name` guard fires before slot fetch and intentionally has no anchor.
- `post_apply_slot_to_template` — same pattern. `party_anchor` extracted immediately after the slot guard and used on all five redirect paths: success, no-source-template error, missing-template error, retired-composition error, and IronkeepError/PermissionDenied.

**URL-ordering bug fix (S1 retroactive correction):** The S1 implementation concatenated the fragment before calling the redirect helpers: `_ok_redirect(planner_url + "#party-N", "msg")` produced `/planner#party-N?success=msg` — an invalid URL where the query string sits inside the fragment and is never parsed by the server. Flash messages were silently discarded on every anchored redirect. This was masked in S1 tests (which check the `location` header only, not rendered flash text). Fixed by introducing `_planner_redirect` and `_planner_err_redirect` helpers that build the URL in the correct order: `/planner?success=msg#party-N`. All 21 affected call sites updated; the original `_ok_redirect`/`_err_redirect` helpers preserved unchanged for non-anchor routes. Four pre-existing broken flash messages in `test_promote_to_template.py` were unmasked and corrected as a side effect.

**New helpers added:**
```python
def _planner_redirect(planner_url, party_anchor, msg="")      # url?success=msg#anchor
def _planner_err_redirect(planner_url, party_anchor, error)   # url?error=msg#anchor
```

**Files changed:** `app/routes.py` only.

**Tests:** `tests/test_planner_build_edit_anchors.py` — 8 tests across 2 groups: build edit (success anchor, multi-party correctness, `/planner` base preserved, early guard without anchor), apply-to-template (success anchor, multi-party correctness, `/planner` base preserved, error redirect also carries anchor).

**Validation:** Tier 4: 8/8. Tier 5: 2181/2181 (no regressions, +8 tests). Corrected 4 pre-existing broken flash-message tests in `test_promote_to_template.py` as a side effect.

---

## Build Library CSV/Paste Import ✅ Shipped (2026-05-26)

**Goal:** Let officers bulk-create `albion_builds` rows from spreadsheet-style paste, with a preview-then-confirm two-step flow. No schema changes; SSR-only.

### Flow

1. `GET /workspaces/{slug}/builds/import` — blank import form (textarea + format hints). Officer-only; viewers get 403.
2. `POST /workspaces/{slug}/builds/import/preview` — parse the paste, validate each row using the existing `albion_builds_domain.validate_build`, render preview table. **No DB writes.** If any row is invalid, the error table is shown with row-level messages and no confirm button. If all valid, a confirm button is shown.
3. `POST /workspaces/{slug}/builds/import/confirm` — re-parses the hidden `raw_text` field, re-validates atomically in the use case, bulk-inserts all builds in one transaction. Redirects to `/builds` with a "Imported N builds." success flash.

### Input format

- Auto-detected delimiter: tab (preferred from spreadsheet copy-paste) or comma.
- First row: header detection — if any cell matches a known column name/alias, row is consumed as header; otherwise positional (`name`, `role`, `weapon_name` in columns 0–2).
- **Required columns:** `name`, `role`, `weapon_name`.
- **Optional columns:** `offhand_name`, `head_name`, `armor_name`, `shoes_name`, `cape_name`, `food_name`, `potion_name`, `doctrine_role`, `notes`.
- **Aliases:** `weapon` → `weapon_name`, `offhand` → `offhand_name`, `armor`/`armour` → `armor_name`, `head` → `head_name`, `shoes`/`shoe` → `shoes_name`, `cape` → `cape_name`, `food` → `food_name`, `potion` → `potion_name`, `doctrine` → `doctrine_role`.
- Blank rows skipped. Unknown columns ignored.
- Duplicate build names allowed (consistent with existing single-create rules).

### Atomicity guarantee

`bulk_import_albion_builds` runs in a single transaction: permission check → validate all rows → insert all rows. A validation error on row 3 of 5 aborts before any DB write. Nothing is partially committed.

### Files changed

- `app/application/use_cases.py` — `bulk_import_albion_builds` use case.
- `app/routes.py` — `_IMPORT_COL_ALIASES`, `_parse_build_import_csv` helper, `get_import_builds`, `post_import_builds_preview`, `post_import_builds_confirm` routes. Routes registered before `GET /builds/{build_id}` to avoid wildcard capture.
- `app/templates/builds_import.html` — new template with textarea form + conditional preview table (column-sparse: only columns present in at least one row are rendered) + confirm form.
- `app/templates/builds_list.html` — "Import CSV" button in the action bar, officer-only (inside existing `{% if can_mutate %}` block).

### Tests

`tests/test_build_import.py` — 55 tests across 13 groups: parser (delimiter, headers, aliases, positional, blank rows), use case (success, validation failures, permission guard), routes (GET import, preview valid, preview invalid, confirm success, confirm guards), template (Import CSV button visibility).

**Validation:** Tier 2: 28/28 (parser + use-case groups). Tier 4: 55/55. Tier 5: 2236/2236 (no regressions, +55 tests).

### Known limitations

- **No composition import.** The import target is `albion_builds` only. Importing composition structures (parties, slot templates) is explicitly out of scope.
- **No item metadata.** Build field values are free-text strings (e.g. `"T8.3 Hallowfall"`). No tier, enchantment, spell, or passive data is parsed or stored.
- **No async / progress feedback.** Large pastes (100+ rows) block the server until all rows are inserted. In practice this is fast (~50ms for 100 rows on SQLite), but there is no progress indicator.
- **No partial-save on confirm.** If the browser's hidden `raw_text` field is modified between preview and confirm (e.g. by a browser extension), the re-validation on confirm will catch diverged data and redirect back with an error rather than saving a subset.
- **No undo / rollback UI.** Builds created by import are identical to builds created one at a time; the import source is not tracked. Bulk-undo requires manual deletion via the build detail pages.
- **Delimiter auto-detection is first-row only.** If the first data row uses tabs but later rows use commas (a malformed paste), parsing will be inconsistent. Officers should paste from a consistent source (one spreadsheet copy-paste operation).

---

## Trial Readiness — M1: Open Signup to Authenticated Non-Members ✅ Shipped (2026-05-26)

**Problem solved:** The signup page and POST route previously required workspace membership. Alliance players who signed in via Discord OAuth but were not pre-added to the workspace received a 404. This made real-world alliance trial usage infeasible without officers manually adding every participant before the operation.

**Solution:** Added `resolve_workspace_for_signup` to `app/routes_auth.py`. Any authenticated user can now reach and submit the signup page. Workspace membership is fetched if it exists and its capabilities (officer mutations, ledger tab, withdraw-others) are applied normally. Users without membership receive `visitor_context` — `can_submit_signup: True`, `can_mutate: False` — which is exactly the right access level for alliance players.

**No schema change.** No membership rows are created for signing-up non-members. The `participants` table row is created by the use case's existing `find_or_create_participant` call, unchanged.

**Unchanged behaviour:**
- Withdrawal route still requires workspace membership (non-members can only withdraw their own signup via the display-name `is_own` check)
- All officer/owner flows (planner, ledger, mutations) remain membership-gated via `resolve_workspace_view` / `authorize_workspace_action`
- Unauthenticated users still redirect to login

**Files changed:** `app/routes_auth.py` (new `visitor_context` + `resolve_workspace_for_signup`), `app/routes.py` (two signup route call-sites updated).

**Tests:** `tests/test_open_signup.py` — 23 tests across 5 groups: GET non-member access, POST non-member submission, existing officer/member flows unchanged, auth guards (unauthenticated, bad workspace/op), access context (officer affordances hidden for non-members).

**Validation:** Tier 4: 23/23. Tier 5: 2259/2259 (no regressions, +23 tests).

---

## Trial Readiness — M2: Lock Roster Confirmation Dialog ✅ Shipped (2026-05-26)

**Problem solved:** The "Lock Roster" button in both the operation overview and the tactical planner was a bare `<form>` POST with no confirmation. A single mis-click during active assignment would lock the roster permanently with no UI recovery path.

**Change:** Added `onclick="return confirm('Lock the roster? Assignment mutations will be disabled and cannot be undone from the UI.')"` to the Lock Roster `<button>` in:
- `app/templates/operation_detail.html`
- `app/templates/operation_planner.html`

No routes, use cases, schema, or JS files changed.

**Tests:** `tests/test_lock_confirmation.py` — 10 tests across 2 groups: operation detail (confirm present, message content, absent on locked/draft ops), planner (confirm present, message content, absent on locked op).

**Validation:** Tier 4: 10/10. Tier 5 not required (template-only change).

### Responsive Comp Builder Layouts

- [ ] Define layout breakpoints for the comp editor: full (≥1200px), compact (≥900px), mobile (< 900px)
- [ ] Full layout: multi-party horizontal grid
- [ ] Compact layout: stacked party groups, 2-column slot cards
- [ ] Mobile layout: single-column slot cards, party groups collapsible

### Touch-Friendly Editing

- [ ] Slot card tap targets meet minimum touch target size (44×44px)
- [ ] Inline editors do not rely on hover-only interactions
- [ ] Dropdowns and selectors usable on touch without zooming

### Compact Mode

- [ ] Define compact mode toggle for the comp editor: hides secondary metadata (notes, equipment summary)
- [ ] Compact mode retains: role, build name, status indicator, primary quick actions
- [ ] Compact mode preference persisted per session

### Overflow Handling

- [ ] Compositions with many slots (30+) scroll gracefully within their party group containers
- [ ] Horizontal party grid scrolls horizontally on narrow screens without breaking layout
- [ ] No content overflow causes page-level horizontal scroll

### Keyboard Efficiency

- [ ] Tab order through slot cards follows visual reading order (party → slots)
- [ ] Inline edit fields are directly focusable without mouse
- [ ] Slot quick actions accessible via keyboard

---

## Phase 9 — Technical Discipline

Maintain clean architecture, additive migrations, and server-rendered simplicity as the composition builder grows in complexity.

### Domain Separation

- [ ] Composition entity: metadata, party grouping, slot definitions — no build content inline
- [ ] Slot entity: party membership, role definition, build reference (FK) — no duplicated build data
- [ ] Build entity: reusable, independent, versioned — no composition-specific state
- [ ] Maintain separate repositories, routes, and templates for each domain

### Data Model Integrity

- [ ] No giant JSON column for composition content — all structure in relational tables
- [ ] No build data denormalised into slot or composition rows
- [ ] Equipment data in a separate equipment table linked to build by FK
- [ ] All relationships expressed as explicit FK constraints, not string ID lookups

### Migration Discipline

- [ ] All schema changes are additive: new columns with defaults, new tables — no destructive changes
- [ ] Each phase ships its own migration file
- [ ] Migrations are reversible where possible, documented where not
- [ ] Migrations tested against the existing integration test suite before merge

### Testability

- [ ] Route integration tests cover: composition create, slot assign, inline build create, party group edit
- [ ] Repository unit tests cover all new query functions
- [ ] Template assertions cover key elements: slot card presence, role labels, status badges, party headers
- [ ] No test relies on inline CSS or computed styles — only semantic HTML classes

### Server-Rendered Simplicity

- [ ] All composition builder views are server-rendered Jinja2 templates — no client-side rendering
- [ ] Inline editors use standard HTML forms — no JavaScript-only interactions required
- [ ] JavaScript (if introduced) is progressive enhancement only — forms must work without it
- [ ] Avoid frontend framework adoption: no React, Vue, or equivalent

---

## Explicit Non-Goals

- **Do not remove reusable builds.** Builds remain independent reusable entities across all phases. Inline creation is a UX convenience, not a data model change.
- **Do not tightly couple builds into compositions.** Build data must not be copied or embedded into composition or slot rows. The FK relationship must remain clean.
- **Do not create SPA complexity.** IronkeepV2 is a server-rendered application. This roadmap does not introduce client-side routing, state management libraries, or API-only composition flows.
- **Do not introduce drag-and-drop initially.** Party and slot reordering via drag-and-drop may be considered in Phase 8 or later only after the core planning UX is proven. It is not a Phase 1–3 requirement.
- **Do not sacrifice maintainability for flashy UI.** Every improvement must remain understandable, testable, and extensible by a single developer without significant cognitive overhead.
- **Do not redesign unrelated operational systems.** Operations, readiness snapshots, payout ledger, and scheduler infrastructure are out of scope for this roadmap except where they surface data inside the planner.
- **Do not introduce versioned composition branching prematurely.** Version history is deferred to Phase 7 at the earliest and only after the core inline editing workflow is stable.
- **Do not break existing composition and build tests.** Every phase must ship with a green test suite. No regressions.

---

## Success Criteria

### Shipped

- [x] Officers can build a tactically readable composition without visiting the standalone build library (Phase 1–3)
- [x] Inline build creation integrates naturally into the composition workflow (Phase 3)
- [x] Role gaps and readiness problems are visible in the planner without reading detailed tables (Phase 5)
- [x] Operational scan speed of the editor is measurably faster than the original table-row layout (Phase 2)
- [x] Doctrine role, role family, build, equipment, and assignment are separated cleanly (Phase 5.5)
- [x] Battlefield responsibility (doctrine role) is visible at a glance on every slot card (Phase 5.5)

### Phase 6 targets

- [ ] Officers can import or paste existing spreadsheet comp data without manually retyping every slot — **deferred; see Deferred from Phase 6**
- [x] Officers can assign 20+ signed-up players quickly during CTA preparation
- [x] Officers can mutate one slot/build in under 10 seconds when signup reality changes
- [x] Composition variants such as Brawl/Kite can be created without rebuilding from scratch

### Durable

- [ ] Composition planning remains the primary workflow surface — the build library is accessed for management, not for basic planning
- [ ] Build reuse remains powerful: officers can share, search, filter, and reference builds across multiple compositions and operations
- [ ] The UI reads as tactical planning software — not as a database CRUD form with an Albion theme
- [ ] All composition builder pages pass integration tests with semantic HTML assertions
- [ ] No schema migration introduces a destructive change
- [ ] The composition builder remains fully functional with JavaScript disabled (forms-only fallback)
