# IronkeepV2 — Testing Strategy

> **Status: Risk-scaled validation matrix shipped (Phase 9.0 Slice 1). Tier 4 split into 4a/4b. Practical commands, philosophy, and escalation guardrails complete. No test reorganisation, no CI/CD, no test rewrites.**
> This document defines testing philosophy, validation tiers, workflow guidance, and future direction for the IronkeepV2 test suite. It is a reference for how and when to validate — not a directive to restructure what currently exists.

> **Cursor prompt guidance:** Follow `docs/testing_strategy.md`. Classify the change using the **Risk-Scaled Validation Matrix** (Section 3.5). Apply the **lowest tier that honestly covers the change category**. Do not run Tier 5 for visual-only or identity slices. See Section 3 (Practical Commands) for copy-paste commands.

---

## Checklist Overview

- [x] Vision defined
- [x] Current state documented
- [x] Practical commands defined and shipped (Section 3)
- [x] Pytest markers registered in `pyproject.toml`
- [x] Cursor prompt guidance note added to document header
- [x] Validation escalation rule defined (Section 5)
- [x] Standard prompt validation footer defined (Section 5)
- [x] Windows pytest PermissionError note added (Section 5)
- [x] Testing philosophy defined
- [x] Validation tiers defined (Tier 1–5)
- [x] Tactical testing strategy defined
- [x] UI/template testing strategy defined
- [x] Database/repository testing strategy defined
- [x] Performance considerations defined
- [x] Future CI/CD direction defined (planning only)
- [x] Explicit non-goals defined
- [x] Operational workflow examples defined
- [x] Open questions captured
- [x] Risk-scaled validation matrix defined (Section 3.5)
- [x] Tier 4 split into 4a (targeted) and 4b (full UI group) (Section 3)
- [x] Visual/identity change guidance defined (Section 3.6)
- [x] Session-level validation guidance defined (Section 3.7)
- [x] Phase 8.7/8.8 validation examples added (Section 12)
- [ ] Pytest markers applied to individual test functions (future phase)
- [ ] `pytest -m tactical` shortcut functional end-to-end (future phase)
- [ ] Nightly regression schedule set up (future phase — CI/CD section)

---

## 1. Vision

### Why Testing Discipline Matters for Tactical Software

IronkeepV2 is not a general-purpose productivity tool. It is a coordination system that guild officers rely on immediately before and during live operations. A regression in slot assignment logic, a broken readiness calculation, or a silently broken Discord post flow does not produce a "minor UX inconvenience." It produces coordination failure during events where timing matters.

Testing discipline exists here to protect the operational contract: the system's behaviour must be predictable, consistent, and trustworthy for officers who are working under time pressure and are not in a position to debug edge cases mid-operation.

### Why Operational Trust Matters

Officers who use IronkeepV2 build operational habits around it. Readiness is checked through the planner. Compositions are drafted and stored in the library. Discord announcements are posted from the platform. The moment any of these behaviours produces an incorrect result — a slot shown as filled when it is not, a check-in not registering, a role tally miscounting — the officer stops trusting the system and reverts to manual coordination.

Testing exists to protect that trust. Not to chase coverage numbers, not to satisfy a process checklist, but because the cost of a silent regression is an officer who loses confidence and falls back to Discord spreadsheets.

### Why Fast Feedback Is Important for Solo Development

IronkeepV2 is maintained by a single developer. The feedback loop between a change and its validation must be short enough that iteration remains fluent. A workflow where every documentation update, CSS token rename, or template wording adjustment triggers a 30–60 second full-suite run creates friction that accumulates across a working session into a significant tax on velocity.

Fast feedback means: the right tests run immediately, and the full suite runs when it is actually needed — not by default.

### Why Full-Suite Validation Still Matters

The full suite exists to catch cross-domain regressions that targeted tests cannot. When a repository change affects multiple downstream use cases, when a template change produces unexpected side effects in a different surface, or when a domain logic change silently breaks an unrelated workflow — the full suite catches it. Running it at meaningful checkpoints (end-of-session commits, pre-release gates, after high-blast-radius changes) is not optional. Running it after every documentation word change or visual polish slice is waste.

The discipline is knowing when each level of validation is appropriate.

---

## 2. Current State

### Suite Size

| Metric | Value |
|---|---|
| Total tests collected | 2,413 |
| Test files | 93 |
| Tier 5 runtime (Windows, single-threaded) | ~22 minutes |
| Tier 4b runtime (documented UI group) | ~3–8 minutes (~374 tests) |
| Tier 4a runtime (targeted slice + surface) | ~5–30 seconds |
| Approximate test categories | domain logic, workflow, repository, Discord, UI/template, backup/restore, tactical |

### Current Test File Groupings (Approximate)

| Category | Representative files |
|---|---|
| Tactical domain | `test_tactical_logic.py`, `test_role_gap_readiness.py`, `test_planner_sorting.py`, `test_planner_ergonomics.py` |
| Composition workflow | `test_composition_soft_delete.py`, `test_lock_from_planner.py`, `test_frozen_operation_slots.py` |
| Assignment lifecycle | `test_assignment_lifecycle.py`, `test_quick_assign.py`, `test_signup_status_rules.py` |
| Operation workflow | `test_operation_lifecycle.py`, `test_operation_mutation_status_rules.py`, `test_vertical_slice.py` |
| Readiness | `test_readiness_v2.py`, `test_dashboard_readiness.py`, `test_operational_health.py` |
| Discord layer | `test_discord_adapter.py`, `test_discord_dispatcher.py`, `test_discord_formatters.py`, `test_discord_post_roster.py`, `test_discord_announcement_preview.py`, `test_discord_component_checkin.py` |
| Attendance/payout | `test_attendance.py`, `test_payout_ledger.py`, `test_payout_ledger_finalization.py`, `test_payout_ledger_export.py`, `test_payout_ledger_audit.py` |
| Repository/data | `test_guild_scoping.py`, `test_workspace_membership.py`, `test_add_workspace_member.py` |
| Backup/restore | `test_backup_restore.py`, `test_backup_script.py` |
| UI/dashboard | `test_dashboard_widgets.py`, `test_dashboard_archived_filter.py`, `test_op_status_coloring.py`, `test_timeline_display.py` |
| Infrastructure | `test_production_hardening.py`, `test_scheduler_jobs.py`, `test_scheduler_status.py` |
| Player/roster | `test_player_reliability.py`, `test_albion_identity.py`, `test_account_linking.py` |

### Current Runtime Pain

The primary friction is not test slowness per test — collection and execution are fast for an individual file. The friction is **default escalation**: every Cursor prompt that touches any file tends to request a full `pytest` run, regardless of the scope of the change.

A documentation-only edit to a planning markdown file, a CSS property tweak, or a brand-mark addition are not changes that require 2,413 tests to run. Running them anyway:

- Adds latency to each iteration cycle
- Creates habit-forming over-caution (if everything requires full validation, nothing feels safe to touch quickly)
- Produces "validation fatigue" — developers who run the full suite so often that they stop reading the output carefully

### Current Workflow Inefficiencies

- Phase deliverables still sometimes request Tier 5 for visual-only slices despite the matrix (agent habit, not strategy gap)
- Tier 4b file list requires manual maintenance as new UI test files are added (markers not yet applied)
- No nightly Tier 5 schedule yet (recommended now that full suite is ~22 minutes)

### Risks of Always Running the Full Suite

- Developer velocity loss across sessions
- Validation fatigue (output stops being read carefully)
- False sense of thoroughness when the bottleneck is decision-making, not test coverage
- Cursor prompt overhead grows as suite grows

### Risks of Not Validating Enough

- Silent regression in tactical domain logic (role tally, gap detection, assignment state)
- Template breakage that is not caught before a session ends
- Repository logic drift that produces incorrect query results
- Discord flow regression that breaks officer workflows silently

The strategy must thread this needle: fast by default, thorough when necessary.

---

## 3. Practical Commands

> **These are the copy-paste commands for local validation. Pick the tier appropriate for the change. Do not default to Tier 5.**

---

### Tier 0 — Docs Only (No pytest required)

Use when: only `.md` files, docstrings, or comments changed.

```
# No test run required. State this explicitly in the prompt response.
```

---

### Tier 1 — Import / Collection Smoke

Use when: any Python file was created or modified. Catches syntax errors and broken imports in under 2 seconds.

```powershell
python -m pytest --collect-only -q
```

Expected output: `2413 tests collected` (or current count — no errors).

---

### Tier 2 — Focused File Validation

Use when: a specific module was changed. Replace `<file>` with the relevant test file(s).

```powershell
# Single file
python -m pytest tests/test_<relevant>.py -q

# Two related files
python -m pytest tests/test_tactical_logic.py tests/test_role_gap_readiness.py -q
```

**Quick-reference: change → test file mapping**

| Changed file | Run this |
|---|---|
| `app/tactical.py` | `tests/test_tactical_logic.py` |
| `app/domain/` readiness logic | `tests/test_readiness_v2.py tests/test_role_gap_readiness.py` |
| `app/application/use_cases.py` (assignment) | `tests/test_assignment_lifecycle.py tests/test_quick_assign.py` |
| `app/repositories.py` | `tests/test_guild_scoping.py tests/test_vertical_slice.py` |
| `app/discord/formatters.py` | `tests/test_discord_formatters.py tests/test_discord_announcement_preview.py` |
| `app/routes.py` (single route) | Tier 4a (new route tests) or Tier 4b if multi-surface |
| Payout / ledger | `tests/test_payout_ledger.py tests/test_payout_ledger_finalization.py` |
| Backup / restore | `tests/test_backup_restore.py tests/test_backup_script.py` |
| `app/domain/guild_operations.py` | `tests/test_operation_lifecycle.py tests/test_operation_mutation_status_rules.py` |

---

### Tier 3 — Tactical Workflow Validation

Use when: `app/tactical.py`, any domain module affecting tactical semantics, planner templates with logic changes, or composition/assignment rules changed.

```powershell
python -m pytest `
  tests/test_tactical_logic.py `
  tests/test_role_gap_readiness.py `
  tests/test_planner_sorting.py `
  tests/test_planner_ergonomics.py `
  tests/test_assignment_lifecycle.py `
  tests/test_quick_assign.py `
  tests/test_composition_soft_delete.py `
  tests/test_lock_from_planner.py `
  tests/test_frozen_operation_slots.py `
  tests/test_readiness_v2.py `
  tests/test_dashboard_readiness.py `
  tests/test_operational_health.py `
  tests/test_zero_slot_compositions.py `
  tests/test_promote_to_template.py `
  -q
```

**Single-line version (cmd / shell paste):**
```
python -m pytest tests/test_tactical_logic.py tests/test_role_gap_readiness.py tests/test_planner_sorting.py tests/test_planner_ergonomics.py tests/test_assignment_lifecycle.py tests/test_quick_assign.py tests/test_composition_soft_delete.py tests/test_lock_from_planner.py tests/test_frozen_operation_slots.py tests/test_readiness_v2.py tests/test_dashboard_readiness.py tests/test_operational_health.py tests/test_zero_slot_compositions.py tests/test_promote_to_template.py -q
```

---

### Tier 4a — Targeted UI Validation

**Default for visual, identity, and single-surface template work.**

Use when: brand/identity slices, hero strips, typography utility application, dashboard polish on one page, new slice test files, template+CSS on a single surface, navigation/shell changes with dedicated slice tests.

```powershell
# Replace with the slice test file(s) and directly affected surface tests
python -m pytest tests/test_<slice>.py tests/test_<affected_surface>.py -q

# Examples:
python -m pytest tests/test_brand_continuity_slice1.py tests/test_auth_dev_login.py -q
python -m pytest tests/test_doctrine_enforcement_slice2.py -q
python -m pytest tests/test_dashboard_widgets.py tests/test_brand_continuity_slice1.py -q
```

**Shell/auth migrations** (e.g. login extends `base_public.html`): always include `tests/test_auth_dev_login.py` in addition to slice tests.

**Expected runtime:** 5–30 seconds (typical slice: 10–25 tests).

**Escalate to Tier 4b when:**
- Template inheritance changed across multiple pages (`base.html`, `base_public.html`, planner)
- Route response shape changed on multiple surfaces
- CSS class renames affect test anchors across many files
- A Tier 4a run surfaces failures outside the changed surface

---

### Tier 4b — Full UI / Template Validation

Use when: multi-surface HTML restructuring, broad template inheritance changes, or Tier 4a escalation.

```powershell
python -m pytest `
  tests/test_dashboard_widgets.py `
  tests/test_dashboard_archived_filter.py `
  tests/test_op_status_coloring.py `
  tests/test_timeline_display.py `
  tests/test_discord_announcement_preview.py `
  tests/test_discord_post_roster.py `
  tests/test_build_suggestions.py `
  tests/test_new_op_from_comp.py `
  tests/test_zero_slot_warnings.py `
  tests/test_promote_to_template.py `
  tests/test_build_usage.py `
  tests/test_build_fork.py `
  tests/test_promote_to_build.py `
  tests/test_planner_scroll_and_readiness.py `
  tests/test_compact_composition_detail.py `
  tests/test_planner_build_edit_anchors.py `
  tests/test_build_import.py `
  tests/test_open_signup.py `
  tests/test_lock_confirmation.py `
  tests/test_ui_regression.py `
  tests/test_doctrine_enforcement_slice2.py `
  tests/test_brand_continuity_slice1.py `
  -q
```

**Single-line version:**
```
python -m pytest tests/test_dashboard_widgets.py tests/test_dashboard_archived_filter.py tests/test_op_status_coloring.py tests/test_timeline_display.py tests/test_discord_announcement_preview.py tests/test_discord_post_roster.py tests/test_build_suggestions.py tests/test_new_op_from_comp.py tests/test_zero_slot_warnings.py tests/test_promote_to_template.py tests/test_build_usage.py tests/test_build_fork.py tests/test_promote_to_build.py tests/test_planner_scroll_and_readiness.py tests/test_compact_composition_detail.py tests/test_planner_build_edit_anchors.py tests/test_build_import.py tests/test_open_signup.py tests/test_lock_confirmation.py tests/test_ui_regression.py tests/test_doctrine_enforcement_slice2.py tests/test_brand_continuity_slice1.py -q
```

**Future:** when `@pytest.mark.ui` is applied to test functions, prefer `python -m pytest -m ui -q` over manual file lists.

**Expected runtime:** ~3–8 minutes (~400 tests in the documented group; count grows as UI tests are added).

**Does not imply Tier 5.** Passing Tier 4b is sufficient for UI-only multi-surface changes unless the matrix requires Tier 5 for behavioral reasons.

---

### Tier 5 — Full Regression Suite

Use when: the **Risk-Scaled Validation Matrix** (Section 3.5) requires Tier 5, at an **end-of-session checkpoint**, or at a **pre-release gate**. Not for visual-only slices.

```powershell
python -m pytest -q
```

**Expected runtime:** ~22 minutes for 2,413 tests (June 2026, Windows, single-threaded SQLite-based suite).

**Tier 5 is required when:**
- `use_cases.py`, `repositories.py`, schema, auth/permissions, or tactical **behavior** changed
- New/changed routes with handler logic (before commit)
- Multi-subsystem refactor
- End-of-session checkpoint after mixed changes
- Pre-release / pre-live trial gate

**Tier 5 is NOT required when:**
- Change category is Tier 0 or Tier 4a-only (visual, identity, CSS-only)
- A phase slice is presentation-only and targeted tests pass
- A lower tier passed and no behavioral paths were touched

---

### Pytest Config Notes

Markers are registered in `pyproject.toml`. They are not yet applied to individual test functions — registration prevents `PytestUnknownMarkWarning` when markers are added to tests in future phases. Running `pytest -m tactical` will collect 0 tests until test functions are decorated in a future phase.

```toml
# pyproject.toml — registered markers (Phase 1)
markers = [
    "tactical", "ui", "discord",
    "repository", "workflow", "smoke", "slow"
]
```

---

## 3.5 Risk-Scaled Validation Matrix

> **Authoritative reference.** Classify every change before choosing a tier. The matrix defines the *lowest honest tier* — not the highest tier that could be justified.

### Matrix

| Change category | Min tier | Required tests | Optional tests | Tier 5? |
|---|---|---|---|---|
| Documentation only | **0** | None | — | No |
| CSS only (properties, no class/name change) | **0** | None | Manual visual spot-check | No |
| CSS only (class rename breaking test anchors) | **4a** | Files asserting those classes | — | No |
| Typography utilities (`op-metric*`, tabular nums) | **4a** | Slice tests for affected surfaces | — | No |
| Brand / identity (marks, naming, hero strips) | **4a** | Slice + affected surface tests | `test_auth_dev_login.py` if login shell touched | **No** |
| Template presentation only (wording, same structure) | **0** | Update assertions if old text anchored | — | No |
| Template + CSS (single admin/public page) | **4a** | Affected page tests + slice tests | — | No |
| Landing page polish (copy, sections, marketing) | **4a** | `test_ui_regression.py` (landing subset) | — | No |
| Dashboard visual polish (cards, badges, layout) | **4a** | `test_dashboard_widgets.py` + slice tests | — | No |
| Ambient backgrounds, gradients, card radius | **0** | None unless test asserts removed class | Manual visual | No |
| Navigation / shell (`base`, `base_public`, login extends) | **4a + auth** | Slice tests + `test_auth_dev_login.py` | **4b** if many templates inherit | Session commit only |
| Workflow UI (planner forms, assignment panels) | **3 + 4a** | Tactical group + planner UX tests | **4b** | Before commit |
| Route changes (new/changed handlers) | **1 + 4a/4b** | Route render tests + handler Tier 2 | — | **Yes, before commit** |
| Use case changes (`use_cases.py`) | **2** | Relevant feature tests | — | **Yes, before commit** |
| Repository changes | **2** | Scoping + feature tests | — | **Yes, before commit** |
| Schema / migration changes | **2** | Repo + vertical slice | — | **Always** |
| Permission / auth middleware changes | **2** | Auth + scoping tests | — | **Always** |
| Operational workflow (tactical, readiness, assignment rules) | **2 + 3** | Tactical group | — | **Yes, before commit** |
| Multi-subsystem refactor | **5** | Full suite | — | **Always** |
| Pre-release / pre-live trial | **5** | Full suite | — | **Always** |

### Tier 5 trigger rule (canonical)

Run Tier 5 when **any** of:

1. Behavioral layer changed: use cases, repositories, schema, auth/permissions, tactical semantics
2. New/changed routes with handler logic (before commit)
3. End-of-session checkpoint after mixed changes across subsystems
4. Pre-release gate (`docs/pre_live_final_checklist.md`, deploy, merge to main)

Do **not** run Tier 5 when:

- Category is Tier 0 or Tier 4a-only
- Only visual/identity/CSS presentation changed and targeted tests pass
- A phase deliverable requests "validation counts" without behavioral scope

---

## 3.6 Visual and Identity Changes

These change types are common in Phase 8+ UI work. **None automatically require Tier 5.**

| Change | Min tier | Notes |
|---|---|---|
| Brand marks (SVG, `.brand-mark`, nav chrome) | **4a** | Targeted slice tests; add auth tests if login shell changes |
| Hero strips (`.ws-hero`, workspace framing) | **4a** | Dashboard/surface tests only |
| Landing page polish (sections, copy, layout CSS) | **4a** | `test_ui_regression.py`; body copy may still say legacy product name until a later slice |
| Typography utilities (`op-metric`, badge classes) | **4a** | Slice tests asserting class presence; CSS-only token work is Tier 0 |
| Ambient backgrounds / gradients | **0** | Pure CSS; optional manual visual check |
| Card radius, spacing, shadow polish | **0** | Pure CSS properties |

**Anti-pattern:** Running Tier 4b or Tier 5 after a Phase 8 visual slice "for safety." The matrix tier is the deliverable validation unless behavioral paths were also changed in the same slice.

---

## 3.7 Session-Level Validation

Validation effort scales with **session scope**, not **slice count**.

### Per-slice validation

Run the **minimum tier from the matrix** for each slice before marking it complete.

| Slice type | Typical validation |
|---|---|
| Docs-only slice | Tier 0 |
| CSS-only slice | Tier 0 |
| Visual/identity slice | Tier 4a (slice tests) |
| Doctrine enforcement (classes, badges) | Tier 4a (slice tests) |
| Tactical behavior slice | Tier 2 + Tier 3 |
| Use case / repo slice | Tier 2; Tier 5 before commit |

Do not accumulate Tier 5 runs across slices. One passing Tier 4a run per visual slice is sufficient.

### End-of-session validation

Run **Tier 5 once** at the end of a working session when:

- Multiple slices landed across different subsystems in one session
- Any slice touched use cases, routes, repositories, or tactical behavior
- You are about to commit/push and have not run Tier 5 since the session started

Do **not** run Tier 5 at end-of-session when the session contained **only** Tier 0 and Tier 4a work (e.g. a full afternoon of CSS polish and brand continuity slices).

### Pre-release validation

Run **Tier 5 always** before:

- Pre-live trial (`docs/pre_weekend_live_trial_checklist.md`)
- Production deploy
- Merge to main / release tag

Pre-release Tier 5 is non-negotiable regardless of per-slice tiers used during development.

---

## 4. Testing Philosophy

### Fast Local Feedback

The default validation workflow must be fast. A focused change should produce focused validation in under five seconds. A broader change should escalate to broader validation in under thirty seconds. Tier 5 full-suite runs are reserved for **session checkpoints and pre-release gates** — not per-slice visual work.

### Deterministic Validation

Tests must be deterministic. Flaky tests — tests that sometimes pass and sometimes fail for reasons unrelated to the code under test — are more dangerous than no tests. They erode trust in the suite and train the developer to ignore failures. Any test that is non-deterministic must be fixed or removed.

### Tactical Trust

The tactical domain — `app/tactical.py`, role family classification, gap detection, readiness interpretation, composition health — is the highest-trust zone of the system. Regressions here are invisible to users until they produce coordination failures. Tactical tests must always run when tactical domain files change, regardless of how small the change appears.

### Layered Validation

Different changes require different validation depths. Layers exist not to reduce rigour, but to apply rigour precisely. A CSS change does not need domain logic validation. A domain logic change does not need backup/restore validation. Layers make rigour efficient.

### No Testing Theater

Tests that exist to make a coverage metric look good but do not test meaningful behaviour are waste. A test that asserts `response.status_code == 200` for a route with no realistic failure modes is not rigour — it is documentation that occupies test infrastructure. Every test must protect something that would otherwise fail silently.

### Meaningful Regressions Over Vanity Coverage

The question is not "what percentage of lines are covered?" The question is "what operational behaviours would break silently if I removed this test?" Coverage as a proxy for safety is only valid when the tests are testing the right things. A 100% covered system with vacuous assertions is less safe than an 80% covered system with meaningful assertions on critical paths.

### Preserve Iteration Speed

The testing strategy must be compatible with a solo-developer iteration pace. Friction compounds. A strategy that adds 30 seconds per iteration cycle costs minutes per working hour and hours per week. The right default is the fastest default that is still honest.

### Server-Rendered Simplicity

IronkeepV2 uses server-rendered Jinja2 templates with FastAPI. The test strategy must be compatible with this architecture. No browser automation by default. No headless Chrome. No JavaScript test runners. Template testing validates rendered HTML through Python — fast, deterministic, and maintainable without additional tooling.

---

## 4. Validation Tiers

These tiers define formal levels of validation with increasing scope and runtime. Each tier has a specific purpose, expected runtime, and triggering criteria.

---

### Tier 1 — Syntax / Import / Smoke Validation

**Purpose:** Verify that Python files are importable, syntax is valid, and no obvious import errors have been introduced. The minimum viable check after any Python file change.

**Expected runtime:** Under 2 seconds (collection only, or a single fast import check).

**When it should run:**
- Any Python file has been created or modified
- A new module has been added
- A dependency has been adjusted

**What kinds of changes require it:**
- Adding a new function to an existing module
- Renaming a class or constant
- Adding a new import
- Restructuring a module's internal organisation
- Any refactor that does not change observable behaviour

**What kinds of changes do NOT require it:**
- Documentation-only changes (`.md` files)
- CSS-only changes in `base.html` or extracted stylesheets
- Template wording changes that do not touch logic
- Changes to non-Python assets (icons, scripts, config files without Python imports)

**Command (planning — not a formal alias yet):**
```
python -m pytest --collect-only -q
```
Collection without execution. Catches import errors and syntax failures without running any test logic.

---

### Tier 2 — Focused Feature / Domain Validation

**Purpose:** Validate a specific domain area or feature in isolation, without running the full suite. The primary validation tier for most development work.

**Expected runtime:** 2–15 seconds depending on the target file(s).

**When it should run:**
- A specific domain module has been changed
- A single use case has been modified
- A repository query has been adjusted
- A single workflow has been added or changed

**What kinds of changes require it:**
- Changes to `app/tactical.py` → run `test_tactical_logic.py`
- Changes to readiness logic → run `test_readiness_v2.py`, `test_role_gap_readiness.py`
- Changes to assignment use cases → run `test_assignment_lifecycle.py`, `test_quick_assign.py`
- Changes to composition logic → run `test_composition_soft_delete.py`, `test_lock_from_planner.py`
- Changes to Discord formatters → run `test_discord_formatters.py`, `test_discord_announcement_preview.py`
- Changes to payout logic → run `test_payout_ledger.py`, `test_payout_ledger_finalization.py`

**What kinds of changes do NOT require it:**
- Documentation-only changes
- CSS-only changes (unless CSS class names are tested in template tests)
- Template wording changes with no logic impact

**Command pattern (planning):**
```
python -m pytest tests/test_<relevant_module>.py -q
```

---

### Tier 3 — Tactical Workflow Validation

**Purpose:** Validate the full tactical coordination surface — tactical domain, planner workflows, composition system, readiness signals, assignment lifecycle — as an integrated domain. The required validation tier for any change to the tactical planning surface.

**Expected runtime:** 30–90 seconds.

**When it should run:**
- Changes to `app/tactical.py` (always — in addition to Tier 2)
- Changes to `app/domain/` that affect tactical semantics
- Changes to the planner templates that involve logic, not just wording
- Changes to the composition workflow
- Changes to slot assignment rules or readiness calculation
- Changes to role family definitions or gap detection logic

**Tactical workflow test grouping (planning — not a formal marker yet):**
```
tests/test_tactical_logic.py
tests/test_role_gap_readiness.py
tests/test_planner_sorting.py
tests/test_planner_ergonomics.py
tests/test_assignment_lifecycle.py
tests/test_quick_assign.py
tests/test_composition_soft_delete.py
tests/test_lock_from_planner.py
tests/test_frozen_operation_slots.py
tests/test_readiness_v2.py
tests/test_dashboard_readiness.py
tests/test_operational_health.py
```

**Command pattern (planning):**
```
python -m pytest tests/test_tactical_logic.py tests/test_role_gap_readiness.py tests/test_assignment_lifecycle.py tests/test_readiness_v2.py tests/test_planner_sorting.py tests/test_planner_ergonomics.py tests/test_composition_soft_delete.py tests/test_lock_from_planner.py tests/test_frozen_operation_slots.py -q
```

**What kinds of changes do NOT require it:**
- Discord-only changes with no tactical domain impact
- Payout/attendance changes with no readiness impact
- Documentation-only changes
- CSS-only changes

---

### Tier 4a — Targeted UI Validation

**Purpose:** Validate a single surface or slice — brand continuity, dashboard polish, doctrine class enforcement — without running the full UI group.

**Expected runtime:** 5–30 seconds.

**When it should run:**
- Brand marks, hero strips, typography utilities applied in templates
- Single-page template+CSS changes with new slice tests
- Navigation/shell changes with dedicated slice + auth tests
- CSS class renames affecting test anchors on one surface

**When it should NOT run:**
- Pure CSS property changes with no template or class anchor impact (Tier 0)

---

### Tier 4b — Full UI / Template Validation

**Purpose:** Validate that server-rendered templates produce correct HTML across the UI test group — structure, anchors, route links, and state signals — without running the full domain suite.

**Expected runtime:** ~3–8 minutes.

**When it should run:**
- Template HTML structure changed on multiple pages
- Shared template inheritance restructured (`base`, `base_public`, planner)
- A new route added or an existing route's response shape changed broadly
- Tier 4a escalation (failures outside changed surface)

**UI/template test grouping:** see Tier 4b command in Section 3.

**What kinds of changes do NOT require Tier 4b:**
- Pure domain logic changes with no template impact
- Documentation-only changes
- CSS token value changes (unless class names are test anchors)
- Visual/identity slices covered by Tier 4a slice tests

**What kinds of template changes are safe to skip all UI tiers:**
- Wording changes to heading text (unless a test asserts the old text)
- Comment additions or removals in templates
- Whitespace-only changes in HTML

---

### Tier 5 — Full Regression Suite

**Purpose:** Validate the complete system — all domains, all workflows, all templates, all infrastructure — to catch cross-domain regressions and emergent failures that targeted tests cannot anticipate.

**Expected runtime:** ~22 minutes for 2,413 tests (June 2026, Windows, single-threaded). Re-time periodically as the suite grows.

**When it should run:**
- Matrix row requires Tier 5 (see Section 3.5)
- End-of-session checkpoint after mixed subsystem changes (Section 3.7)
- Pre-release / pre-live trial gate
- After any change to `app/application/use_cases.py` (central use case layer)
- After any change to `app/repositories.py` or schema/migrations
- After permission/auth middleware changes
- After operational workflow behavior changes (before commit)
- Multi-subsystem refactor

**When it should NOT run:**
- Per-slice visual/identity/CSS-only work (Tier 0 or 4a sufficient)
- Documentation-only changes
- Template wording with no structure change
- "Just to be safe" after a passing Tier 4a run

**Command:**
```
python -m pytest -q
```

---

## 5. Prompt Guidance for Cursor

This section defines recommended validation behaviour for future Cursor prompts. These are not automated rules — they are explicit decision guidance to prevent unnecessary full-suite escalation and to ensure meaningful validation is not skipped.

### Safe Defaults by Change Type

> **Superseded by the Risk-Scaled Validation Matrix (Section 3.5).** This table is retained as a quick reference; the matrix is authoritative when they differ.

| Change type | Minimum validation | Escalate to Tier 5? |
|---|---|---|
| Documentation only (`.md`) | Tier 0 | No |
| CSS-only (no class name changes) | Tier 0 | No |
| CSS class rename (test anchor) | Tier 4a | No |
| Typography utilities / brand / hero / visual polish | Tier 4a | **No** |
| Template wording only (text, no HTML) | Tier 0 | No |
| Template HTML structure (single surface) | Tier 4a | No |
| Template HTML structure (multi-surface / shared inheritance) | Tier 4b | Session commit only |
| Navigation/shell change | Tier 4a + `test_auth_dev_login.py` | Session commit only |
| New Jinja template variable (behavioral) | Tier 4a | No |
| Workflow UI (planner, assignment) | Tier 3 + Tier 4a | Yes, before commit |
| Tactical domain logic (`app/tactical.py`) | Tier 2 + Tier 3 | Yes, before commit |
| Use case change (`use_cases.py`) | Tier 2 + Tier 5 | Yes |
| Repository query change | Tier 2 + Tier 5 | Yes, before commit |
| Schema / migration | Tier 2 + Tier 5 | Always |
| Permission / auth middleware | Tier 2 + Tier 5 | Always |
| New route (with handler logic) | Tier 1 + Tier 4a/4b + Tier 5 | Yes, before commit |
| Domain model change | Tier 5 | Always |
| Discord layer change | Tier 2 (Discord tests) | Before commit |
| Backup/restore logic | Tier 2 (backup tests) | Before commit |
| Dependency addition | Tier 1 + Tier 5 | Yes |
| Multi-subsystem refactor | Tier 5 | Always |

### When Smoke Tests Are Enough

Tier 1 (collection/import check) is sufficient when:
- A new Python file has been created with no outward-facing logic yet
- A constant or configuration value has been renamed with no logic change
- A module has been reorganised without changing its public API
- A new function has been stubbed but not yet connected to any use case

### When to Escalate to Full Suite

Escalate to Tier 5 when:
- The **Risk-Scaled Validation Matrix** (Section 3.5) requires it
- The change touches a shared behavioral abstraction (use cases, repositories, domain models, middleware, tactical semantics)
- The change's downstream effects are unclear and a focused run surfaced unexpected failures
- **End-of-session checkpoint** after mixed changes (Section 3.7)
- **Pre-release gate** (deploy, pre-live trial, merge to main)

Do **not** escalate to Tier 5 merely because:
- A shared *visual* template (`base.html`) changed — use Tier 4a + auth tests instead
- A phase deliverable lists "Tier 4 and Tier 5" without behavioral scope
- A lower tier passed and no matrix row requires Tier 5

### Documentation-Only Prompts

Prompts that only modify `.md` files, planning documents, or docstrings should explicitly note in the prompt output that no test run is required. Running tests after a documentation-only change is waste and should be called out as such.

### CSS-Only Prompts

Prompts that only modify CSS — token values, gradients, border-radius, spacing, ambient backgrounds — require **Tier 0** (no pytest). Escalate to Tier 4a only if class names used as test anchors were renamed or removed.

### Tactical Domain Prompts

Any prompt that modifies `app/tactical.py`, role family definitions, gap detection logic, readiness calculation, or slot assignment rules **must** run Tier 2 + Tier 3 before the prompt is considered complete. This is non-negotiable because tactical domain regressions are silent until they produce coordination failures.

### Template/Route Prompts

- **New routes with handler logic:** Tier 1 + Tier 4a/4b + Tier 5 before commit.
- **Shared template inheritance restructured** across multiple pages: Tier 4b; Tier 5 only at session commit if behavioral paths also changed.
- **Shell/navigation changes** (`base.html`, `base_public.html`, login extends): Tier 4a + `test_auth_dev_login.py`; Tier 5 **not** required for presentation-only shell work.
- **Visual/identity slices:** Tier 4a only; see Section 3.6.

### Validation Escalation Rule

Passing a lower tier does **not** imply permission to run the next tier. Tiers are independent. Each tier must be explicitly justified by the change type before it runs.

| Rule | Statement |
|---|---|
| Tier 1 pass → Tier 2 | Not implied. Tier 2 requires a Python domain change, not just a successful collection. |
| Tier 2 pass → Tier 3 | Not implied. Tier 3 requires a tactical domain change, not just any domain file. |
| Tier 4a pass → Tier 4b | Not implied. Escalate only for multi-surface HTML or 4a failures outside changed surface. |
| Tier 4a/4b pass → Tier 5 | Not implied. Tier 5 requires matrix row, session commit, or pre-release gate. |
| Auto-escalation | Never acceptable. Each tier escalation must be justified in the prompt reasoning. |

**Tier 5 is expensive (~22 minutes) and requires explicit justification.** It should not be run by default after a lower tier passes. Tier 5 is reserved for:
- The change explicitly requires Tier 5 per the **Risk-Scaled Validation Matrix** (Section 3.5)
- End-of-session checkpoint or pre-release gate (Section 3.7)
- The prompt itself requests a full-suite run for behavioral scope
- A broad **behavioral** shared-system change (use cases, domain models, repositories, middleware, tactical semantics) has occurred

**Phase definitions must align with the matrix.** If a foundation doc mandates Tier 5 for a visual-only slice, treat that as stale guidance — use Tier 4a unless behavioral paths changed.

**Minimise iteration cost while preserving confidence.** The correct validation response is always the *lowest tier that honestly covers the change* — not the highest tier that could theoretically be justified.

**Automatic "safety escalation" is explicitly discouraged.** Running Tier 5 "just to be safe" after a documentation edit, a CSS token rename, or an isolated template change is not caution — it is friction that compounds across a session and trains the developer to ignore validation output.

Specific escalation rules by change type:

- **Docs-only changes** (`.md`, docstrings, comments): Tier 0, ever.
- **CSS-only changes** (properties, gradients, radius — no class anchor impact): Tier 0.
- **CSS class rename** (affects HTML selectors in tests): Tier 4a only. Not Tier 5.
- **Visual/identity changes** (brand, hero, typography utilities, landing polish): Tier 4a only. Not Tier 5.
- **Tactical domain changes** (`app/tactical.py`, role families, gap logic): Tier 2 + Tier 3. Tier 5 before commit, not after every iteration.
- **Template wording only** (text content, no HTML structure change): Tier 0.
- **Isolated feature change** (one use case, one domain module): Tier 2 for that module only; Tier 5 before commit.

### Standard Prompt Validation Footer

The following text is the canonical validation footer for Cursor prompts that involve IronkeepV2 changes. Copy it into prompts where validation guidance is needed.

---

```
Follow docs/testing_strategy.md. Use the Risk-Scaled Validation Matrix (Section 3.5).

Default: lowest tier that honestly covers the change category.
Tier 4a for visual/identity slices — not Tier 4b or Tier 5 unless the matrix requires it.

Tier 5 only when the matrix requires it, at an end-of-session checkpoint, or at pre-release.

Report: tier used, tests run, pass count, runtime — not "full suite unless asked."

Do not automatically escalate validation tiers after a passing lower-tier run.
```

---

### Windows pytest PermissionError on Temp Cleanup

On Windows, pytest occasionally emits a `PermissionError` when cleaning up temporary directories after a test run. This is a known, harmless Windows filesystem timing issue — pytest attempts to delete a temp directory while the OS still holds a handle open.

**It is not a test failure.** It does not indicate a broken test, a broken suite, or a failed validation run.

**How to identify it:** The error appears in the output *after* the final test result line (`X passed in Y.Zs`) and references a Windows temp path such as `C:\Users\...\AppData\Local\Temp\pytest-...`. The exit code reported by pytest remains `0` when all tests passed.

**Correct response:**
- If collection succeeded and all tests passed: the run is clean. Do not re-run. Do not escalate to a higher tier.
- Do not treat it as a reason to retry the run at a higher tier.
- Do not treat it as evidence of a test infrastructure problem requiring investigation.

**Incorrect response:**
- Escalating to Tier 5 because a PermissionError appeared after a Tier 2 run that passed.
- Flagging the run as uncertain and re-running "to confirm."
- Treating it as a test failure in the implementation log.

---

## 6. Tactical Testing Strategy

### Scope

Tactical testing covers the domain logic that derives operational meaning from raw data: role classification, composition health, readiness interpretation, gap detection, and assignment state. This logic lives primarily in `app/tactical.py` and the domain modules it depends on.

Tactical tests are the highest-trust tests in the suite. They must be:
- Deterministic (same input always produces same output)
- Fast (no database, no HTTP, no I/O — pure function testing)
- Exhaustive for edge cases (empty compositions, None roles, partial fills, malformed slots)

### Role-Family Derivation

Role classification maps free-text role names (e.g., "Tank", "Frontline", "Healer", "Holy") to canonical role families (tank, healer, dps, support, unknown). Tests must cover:
- [ ] All known role keywords for each family
- [ ] Case-insensitive matching (Albion role names vary in capitalisation across guilds)
- [ ] Unknown/unrecognised role names → `"unknown"` family (no crash, no silent misclassification)
- [ ] None/empty role values → graceful handling
- [ ] Boundary cases: role names that partially match multiple keywords

### Tactical Summaries

`derive_tactical_summaries()` is the central function producing party-level and composition-level tallies, gap detection, and continuation hints. Tests must cover:
- [ ] Role tally correctness for each party (exact count per family)
- [ ] Composition-level role tally (sum across all parties)
- [ ] Gap badge generation: which roles are missing, at what threshold
- [ ] Continuation hint logic: which composition phase to suggest next
- [ ] Edge cases: empty party (no slots), single-slot party, full 5-slot party
- [ ] Operation mode (`track_assignments=True`): assignment state affects readiness signals
- [ ] Template/preview mode (`track_assignments=False`): assignment state is irrelevant to tally

### Readiness Interpretation

Readiness is multi-layered: slot fill state, player assignment, check-in status. Tests must cover:
- [ ] Slot filled (build assigned) vs. slot empty → different readiness signal
- [ ] Player assigned to slot → check-in status tracked separately from assignment
- [ ] Role gap (needed role not present in composition) → surfaces as gap badge, not just low fill
- [ ] Mixed state: some slots filled, some empty, some at-risk → correct aggregate signal

### Gap Detection

Gap detection identifies role families that are structurally missing from a composition. Tests must cover:
- [ ] A composition with no tank → tank gap detected
- [ ] A composition with no healer → healer gap detected
- [ ] A composition that meets minimum role requirements → no gap
- [ ] Threshold logic: how many of a role are needed before the gap is cleared

### Assignment State

Assignment state reflects whether a slot has a player committed to it. Tests must cover:
- [ ] Slot with build but no player assignment → not the same as readiness
- [ ] Slot with player but no build → valid but tactically incomplete
- [ ] Slot with player + build → fully assigned
- [ ] Unassigned slot → gap in operational readiness, not composition health

### Composition Health

Composition health signals derive from the combined role distribution and assignment state. Tests must cover:
- [ ] A structurally sound composition (all roles present, all slots filled) → healthy signal
- [ ] A composition with role gaps → unhealthy signal, gap badges present
- [ ] A composition with empty slots but sound role distribution → partial readiness
- [ ] A composition with no slots defined → edge case, no crash

### Planner Workflows

Planner workflow tests validate the end-to-end officer actions in the planning surface. These are higher-level than pure domain tests and may involve database state:
- [ ] Adding a slot to a composition → slot appears with correct role identity
- [ ] Assigning a build to a slot → slot updates without full planner reload
- [ ] Swapping a build on an existing slot → old build is replaced, tally recalculates
- [ ] Locking a composition to an operation → slot modifications are restricted
- [ ] Unlocking a frozen composition → modification rights restored

### Determinism and Reusability

Tactical tests should use shared helper factories (like the existing `_slot()` helper in `test_tactical_logic.py`) to build test fixtures. These factories must be kept in sync with the actual slot interface. If the slot data shape changes, the factory changes, and all tests that use it immediately surface as needing review.

---

## 7. UI / Template Testing Strategy

### What Should Be Tested

Template tests validate that server-rendered HTML produces the correct operational output for a given application state. The test asks: "given this state in the database, does the rendered template show the right information?"

What to test:
- [ ] Presence of key headings and navigation anchors that officers rely on
- [ ] Route links that appear in the template (correct `href` values)
- [ ] Conditional rendering: elements that appear only when a condition is true (e.g., a "Lock Composition" button only appears when the operation is in draft state)
- [ ] State-based class names that drive visual signals (e.g., `role-tally--gap` appears when a role is missing)
- [ ] Form action URLs and hidden field values that are critical to correct submission
- [ ] Empty-state rendering: when a list is empty, the correct message appears
- [ ] Role tally strip rendering: correct counts appear in the correct positions

### What Should NOT Be Snapshot-Tested Excessively

Snapshot testing — asserting the exact HTML output of a template and failing on any change — is dangerous for a system that is actively evolving its UI architecture. CSS class renames, wording adjustments, and structural improvements should not require snapshot updates across dozens of tests.

Avoid:
- Exact HTML string matching for large template sections
- Asserting specific whitespace or indentation in rendered HTML
- Testing visual style properties (colour, spacing) through HTML output
- Testing CSS class presence for classes that carry no semantic meaning (layout utility classes)

Prefer:
- Asserting the presence/absence of specific meaningful elements (`assert "Lock Composition" in response.text`)
- Asserting route correctness (`assert f"/operations/{op_id}/lock" in response.text`)
- Asserting state-based class names only when those classes drive operational signals

### Server-Rendered Template Validation Philosophy

IronkeepV2 renders all templates server-side. This means template tests run without a browser, without JavaScript, and without a frontend build pipeline. A test client (FastAPI `TestClient`) renders the full HTTP response and the test inspects the HTML string.

This is fast, deterministic, and requires no additional infrastructure. Preserve it.

The risk zone is tests that assert too much of the raw HTML and become brittle during UI evolution (Phase 2–8 of the UI Architecture System). Tests should be written against semantic anchors — text content, route URLs, meaningful class names — not against the surrounding structural HTML.

### Accessibility Considerations

At this stage, automated accessibility validation in tests is not a priority. However:
- [ ] Heading hierarchy should be visually verified during UI architecture phases
- [ ] `aria-label` attributes on interactive elements (check-in buttons, accordions) should be testable via the test client once introduced
- [ ] Colour contrast is a CSS concern, not a Python test concern — addressed during UI Architecture Phase 7

Future consideration: if a Tier 4b UI validation run is defined, an automated `axe-core` or `pa11y` pass could be added as an optional step during Phase 7 of UI Architecture.

### Responsive Validation Philosophy

Responsive layout cannot be tested meaningfully through the server-rendered HTML test client. The rendered HTML is the same regardless of viewport. Responsive testing, if introduced, would require a browser automation layer.

At this stage:
- Responsive validation is a manual concern during development of UI Architecture Phases
- Mobile layout correctness is verified by visual inspection, not automated tests
- Breakpoint behaviour is documented in the UI Architecture system, not enforced by automated tests

### Regression Risk Areas

These template areas carry the highest regression risk and should have the most robust **Tier 4b** coverage (not required for every visual polish slice):

| Area | Risk |
|---|---|
| Planner slot cards | Role identity class, readiness state class, build display |
| Composition overview strip | Role tally counts, gap badge presence |
| Operation status display | Status label, available actions based on status |
| Discord post preview | Formatted text correct for the posting surface |
| Readiness summary | Slot fill count, check-in count |
| Navigation links | Workspace-scoped URLs correct for the current workspace |

---

## 8. Database / Repository Testing Strategy

### Migration Validation Philosophy

IronkeepV2 uses SQLite with a migration system. Migrations are applied at startup via `app/startup.py`. Repository tests that create in-memory databases and apply migrations validate that:
- [ ] The schema produced by migrations matches what the domain layer expects
- [ ] Adding a column does not break existing repository methods
- [ ] Removing a column surfaces as a test failure before it surfaces as a runtime error
- [ ] Ordering of migration steps is correct (later migrations do not reference columns that have not been created yet)

Migration test philosophy: a migration that passes collection and runs without error is not enough. A migration test should verify that the resulting schema supports the repository operations that depend on it.

### Repository Safety Expectations

Repository tests validate that:
- [ ] A query that should return one record does not silently return zero (silent empty set)
- [ ] A query that should return zero records does not silently return stale data
- [ ] Guild scoping is correct — a query for workspace A cannot return records belonging to workspace B
- [ ] Soft-delete patterns (compositions) correctly exclude deleted records from active queries
- [ ] Write operations (insert, update) produce the expected state in the database

Guild scoping is a security and correctness concern, not just a data hygiene concern. The `test_guild_scoping.py` tests protect against cross-workspace data leakage. These must run whenever repository methods are changed.

### Query Correctness Expectations

Repository methods are not inherently self-validating — a method that builds the wrong SQL query will return wrong data silently. Tests must verify:
- [ ] Correct records are returned for the given parameters
- [ ] No records are returned when none should be (empty result is correct)
- [ ] Ordering is correct when ordering is promised by the repository contract
- [ ] Aggregation queries (counts, sums) return correct values for known datasets

### Domain Integrity Expectations

The database is the single source of truth. Domain integrity tests validate that:
- [ ] Domain rules that are enforced at the use-case layer cannot be bypassed by direct repository access
- [ ] Status transitions (operation draft → locked → completed) are only reachable through valid sequences
- [ ] Constraints that exist in the domain (a slot cannot have two players assigned) are testable at the use-case level even if the database does not enforce them as foreign key constraints

---

## 9. Performance Considerations

### Why Full-Suite Runs Are Expensive

At **2,413 tests / ~22 minutes**, a full Tier 5 run is a **session-level checkpoint**, not a per-slice default. The cost is not just wall-clock time. The cost is:
- Context switching: a 22-minute wait interrupts focus mid-session
- Friction accumulation: running Tier 5 after every visual slice wastes hours per week
- Output desensitisation: if every run produces 2,413 passed results, the developer stops reading the output carefully and may miss meaningful failures

### How to Avoid Unnecessary Runs

The primary mechanism is the **Risk-Scaled Validation Matrix** (Section 3.5) and session-level guidance (Section 3.7). The secondary mechanism is explicit change categorisation in Cursor prompts:

- State the change category at the start of validation reasoning
- Apply the appropriate tier based on the category
- Only escalate to a higher tier when the change category justifies it

A future enhancement (not yet implemented) would be pytest markers that allow `pytest -m tactical` or `pytest -m ui` to run specific tiers. Until markers are introduced, explicit file lists are the mechanism.

### How to Preserve Developer Velocity

- Fast changes deserve fast validation. A CSS gradient fix should not wait 22 minutes for Tier 5.
- Save Tier 5 for end-of-session checkpoints and pre-release gates — not for each iteration within a visual slice.
- When a Tier 4a run passes, record that as the validation for that slice. Do not re-run Tier 5 "just to be sure."
- If Tier 4b exceeds ~10 minutes, investigate slow test files or consider marker-based partitioning.

### How to Prevent Validation Fatigue

Validation fatigue occurs when tests are run so frequently and produce so little new information that the developer stops paying attention to results. Symptoms:

- Full-suite runs after documentation-only changes (produces no failures, teaches nothing)
- Identical runs back-to-back within seconds of each other (produces same output, wastes time)
- Running the full suite without looking at the output (the run becomes ceremonial, not informational)

The antidote is the tier system: targeted validation that produces meaningful signal for the specific change at hand.

---

## 10. Future CI/CD Direction

> Planning only. No implementation implied.

### Nightly Full Regression Run

A scheduled nightly run of the full suite (`pytest -q`) against the current working state. **Recommended now** that Tier 5 is ~22 minutes — catches regressions from accumulated Tier 0/4a slices without requiring Tier 5 after every visual change.

Implementation consideration: a simple scheduled script or task runner — no complex pipeline. Could be a PowerShell scheduled task, a cron job on a development machine, or a GitHub Actions scheduled workflow.

### Targeted PR Validation

If the project ever adopts a pull-request workflow (branching for features), a targeted validation pipeline could detect which files changed in a PR and automatically select the appropriate tier to run:
- Only Python files changed → Tier 1 + Tier 2 for the affected modules
- Tactical domain files changed → Tier 3 always
- Templates changed (visual/identity) → Tier 4a (slice + surface tests)
- Templates changed (multi-surface structure) → Tier 4b
- Use cases or domain models changed → Tier 5 always

This requires the tier system to be formalised with pytest markers or a grouping file.

### Tactical-Domain Validation Pipeline

A dedicated pipeline step (or named `pytest` command) that runs only the tactical domain tests and produces a clear pass/fail signal. This would be the first step in any validation workflow that touches tactical logic, regardless of what other tests run.

Benefit: tactical regressions are surfaced immediately, before any broader suite output can obscure them.

### UI Validation Pipeline

Dedicated pipeline steps for **Tier 4a** (targeted slice tests) and **Tier 4b** (full UI group) that run independently of domain logic tests. Useful during Phase 8+ UI work when template changes are frequent.

### Performance Smoke Checks

A periodic check that the full suite completes within a defined time budget (**~25 minutes** at 2,413 tests). If a suite run exceeds the budget, the slowest tests are identified and reviewed via `pytest --durations=20`.

### What to Avoid

- Pipeline complexity that requires maintenance effort proportional to the pipeline itself
- External service dependencies (Docker containers, cloud test environments) for unit-level tests
- Multiple competing CI systems that produce conflicting signals
- "Enterprise DevOps" processes (mandatory approval gates, compliance sign-offs) for a solo-maintained tool

---

## 11. Explicit Non-Goals

### No Coverage Obsession

- [ ] No target percentage (90%, 95%, 100% coverage) is a project goal
- [ ] Coverage is a signal, not a metric. It indicates untested paths, not test quality.
- [ ] Increasing coverage by writing tests that assert trivially true statements is explicitly rejected

### No Snapshot-Testing Explosion

- [ ] No tool that serialises full HTML output and diffs it on every run
- [ ] No visual regression testing (screenshot comparison) at this stage
- [ ] No tests that fail because a CSS class was added to a div that is not part of the semantic test assertion

### No Browser Automation as Default

- [ ] No Selenium, no Playwright, no Puppeteer as part of the default test suite
- [ ] Browser automation is not ruled out for specific future accessibility or end-to-end scenarios, but it is not a default validation layer
- [ ] The FastAPI `TestClient` renders server-rendered HTML deterministically without a browser — this is sufficient for all current validation needs

### No Frontend-Framework Testing Stack

- [ ] No Jest, no Vitest, no React Testing Library
- [ ] IronkeepV2 has no frontend framework — its test suite has no frontend framework testing stack
- [ ] If future enhancement introduces JavaScript behaviour, isolated JS unit tests are acceptable only if they cover genuinely non-trivial logic

### No "Test Because Enterprise"

- [ ] No test categories that exist to satisfy a process checklist rather than protect real behaviour
- [ ] No mandatory test file for every new module regardless of whether the module has testable logic
- [ ] No integration test layer added because it "looks professional" rather than because it catches real regressions

### No Slow Validation by Default

- [ ] The default validation command is always the fastest tier appropriate for the change
- [ ] Full-suite runs are not the default — they are the escalation
- [ ] Any validation step that routinely takes more than 60 seconds without being justified by the change scope is a candidate for removal or restructuring

---

## 12. Operational Workflow Examples

These examples define the expected validation response to specific change types. They are concrete decision guides, not hypotheticals.

---

### Example A — Documentation-only update

**Change:** A planning markdown document in `docs/` has been updated. New sections added, existing sections revised. No Python files touched.

**Validation required:** None.

**Rationale:** No Python, no templates, no routes, no domain logic. Documentation changes cannot introduce runtime regressions.

**Cursor prompt guidance:** The prompt should explicitly state "no test run required" and explain why.

---

### Example B — Tactical summary logic changed

**Change:** `app/tactical.py` — `derive_tactical_summaries()` adjusted to change the threshold for gap badge generation.

**Validation required:** Tier 2 (`test_tactical_logic.py`) immediately. Then Tier 3 (full tactical workflow group). Then Tier 5 before commit.

**Rationale:** Tactical domain logic affects every planner surface, every composition detail view, and every readiness signal. A threshold change can silently change gap badge presence across all operations in the system.

**Cursor prompt guidance:** "Run `test_tactical_logic.py` immediately. Run full tactical group before completing the prompt. Full suite before commit."

---

### Example C — CSS token extraction from base.html

**Change:** CSS custom properties (tokens) extracted from the inline `<style>` block in `base.html` into a separate file. No class names changed. No HTML structure changed.

**Validation required:** **Tier 0** (no pytest). Optional manual visual spot-check.

**Rationale:** Token value relocation does not change Python logic, route behaviour, or class names used as test anchors. If a token reference was accidentally broken, visual inspection catches it faster than running 400 UI tests.

**Cursor prompt guidance:** "No test run required. State Tier 0 explicitly. Optional: spot-check one admin and one public page in browser."

---

### Example D — Repository migration added

**Change:** A new migration step added to `app/startup.py` adding a column to an existing table.

**Validation required:** Tier 2 (repository tests for the affected table). Then Tier 5 (full suite) before commit, because schema changes can affect any repository method that queries the affected table.

**Rationale:** Schema changes are high-blast-radius. A column addition can affect `SELECT *` queries, ORM-style result mapping, and any test that creates a minimal table fixture without the new column.

**Cursor prompt guidance:** "Run repository tests for affected domain entity. Then run full suite. Do not commit without Tier 5 passing."

---

### Example E — Discord formatter adjusted

**Change:** `app/discord/formatters.py` — announcement format string adjusted for better readability.

**Validation required:** Tier 2 (`test_discord_formatters.py`, `test_discord_announcement_preview.py`).

**Rationale:** Discord formatters produce text strings. Tests verify the expected text is present in the output. Formatting changes are isolated — they do not affect domain logic, repositories, or other Discord features.

**Cursor prompt guidance:** "Run Discord formatter and announcement preview tests. If clean, no further escalation required for this change."

---

### Example F — New operation route added

**Change:** A new route added to `app/routes.py`. A new template created. No changes to existing routes or domain logic.

**Validation required:** Tier 1 (import check — new route file must be importable). Tier 4a or 4b (verify the new route renders the correct template). **Tier 5 before commit** (new routes can affect navigation state, guild scoping, and authentication middleware).

**Rationale:** New routes introduce new surface area. Even if the route itself is straightforward, it must integrate correctly with the workspace-scoped URL structure, the authentication layer, and the shared navigation template.

**Cursor prompt guidance:** "Run import check, then UI tests for the new route. Full suite before commit."

---

### Example G — Template wording only

**Change:** A heading in `operation_planner.html` changed from "Composition" to "Tactical Composition." No HTML structure changed. No routes changed. No logic changed.

**Validation required:** None, unless a test asserts the exact previous heading text.

**Rationale:** Template wording changes that do not affect HTML structure, route links, or state-dependent rendering cannot introduce regressions. If a test is currently asserting the old heading text as a meaningful semantic anchor, that test should be reviewed — heading text is not a meaningful test anchor unless it is the only visible label for a functional element.

**Cursor prompt guidance:** "Check if any test asserts the old heading text. If yes, update those assertions. If no, no test run required."

---

### Example H — Multi-subsystem refactor

**Change:** `app/application/use_cases.py` — a shared use case function refactored to change its parameter interface. Multiple features affected.

**Validation required:** Tier 5 (full suite). No exceptions.

**Rationale:** Use cases are the central coordination layer. A parameter interface change can silently break callers in routes, Discord adapters, and other use cases. Only the full suite can reliably surface all affected paths.

**Cursor prompt guidance:** "This change requires full suite validation before commit. Do not consider the prompt complete until `pytest -q` passes."

---

### Example I — Doctrine enforcement slice (Phase 8.7 pattern)

**Change:** Phase 8.7 Slice 2 — operational metrics typography (`op-metric*` utilities), dashboard inline colour removal (badge classes), locked badge semantic alignment (`badge-locked` → info tokens). Templates: `workspace_dashboard.html`, `operation_planner.html`, `operation_detail.html`. CSS: `utilities.css`, `components.css`, `tactical.css`. New tests: `test_doctrine_enforcement_slice2.py`.

**Validation required:** **Tier 4a** — `python -m pytest tests/test_doctrine_enforcement_slice2.py -q` (~9 tests, ~10 seconds).

**Tier 5:** **Not required** for this slice. No use case, repository, route handler, or tactical behavior changed.

**Rationale:** Class additions and badge token changes are presentation-layer enforcement. Slice tests assert the correct classes and absence of inline styles. Running 2,413 tests adds ~22 minutes without proportional risk reduction.

**Cursor prompt guidance:** "Run slice tests only. Report Tier 4a count and runtime. Do not run Tier 5 unless the same session also changed behavioral paths."

---

### Example J — Product identity slice (Phase 8.8 pattern)

**Change:** Phase 8.8 Slice 1 — brand mark (`_brand_mark.html`), "Ironkeep" naming in shells, login extends `base_public.html`, dashboard `.ws-hero` strip. Templates: `base.html`, `base_public.html`, `login.html`, `workspace_dashboard.html`. CSS: `layout.css`, `landing.css`, `dashboard.css`, `components.css`. New tests: `test_brand_continuity_slice1.py`.

**Validation required:** **Tier 4a** — `python -m pytest tests/test_brand_continuity_slice1.py tests/test_auth_dev_login.py -q` (~14–18 tests, ~15 seconds).

**Tier 5:** **Not required** for this slice. Login shell migration is covered by brand tests + auth dev-login tests; no auth logic changed.

**Rationale:** Identity and framing changes are high-visibility but low behavioral blast-radius. Auth flow preservation is validated by targeted tests, not by running payout, Discord dispatcher, and backup tests.

**Cursor prompt guidance:** "Run brand slice tests + auth dev-login tests. Report Tier 4a. Tier 5 deferred to end-of-session if mixed with behavioral work."

---

## 13. Open Questions

### Suite Organisation

- [ ] **Should pytest markers be introduced to formalise validation tiers?** Markers (`@pytest.mark.tactical`, `@pytest.mark.ui`, `@pytest.mark.repository`) would allow `pytest -m tactical` instead of manually listing files. The cost is marker maintenance as the suite grows. Worth defining the marker taxonomy before implementing.
- [ ] **Should the tactical test group be formalised as a named pytest command in a `pyproject.toml` or `pytest.ini` section?** A named subset (e.g., `pytest --co -m tactical -q`) would make Cursor prompt guidance more concrete and less fragile than explicit file lists.
- [ ] **How should test file naming evolve as the suite grows past 70–80 files?** Flat namespace is currently manageable. At 100+ files, subdirectory grouping (`tests/tactical/`, `tests/ui/`, `tests/domain/`) may improve navigation — but requires path updates in any hardcoded test commands.

### Tactical Testing Gaps

- [ ] **Should planner rendering tests be expanded to cover the full slot card HTML structure?** Currently, tactical logic is tested at the pure-function level (`test_tactical_logic.py`). The rendered slot card HTML is tested more loosely. A gap exists between "derive_tactical_summaries returns the right data" and "the planner template renders that data into the correct HTML."
- [ ] **Should `test_tactical_logic.py` cover integration with the template rendering layer?** This would test the full path from raw slot data → tactical summaries → rendered HTML. Currently this integration is only implicitly covered by planner route tests.
- [ ] **Are there tactical edge cases not yet covered?** Compositions with duplicate roles, compositions that exceed party size limits, compositions with all slots in unknown family — these should be audited against the current test coverage.

### UI and Accessibility

- [ ] **Should UI smoke tests be introduced?** A minimal Tier 4b command that visits every registered route and verifies a 200 response (no crashes) would catch routing regressions faster than the current approach. This is a five-minute addition with high value.
- [ ] **Should accessibility validation become automated?** During UI Architecture Phase 7, an automated accessibility pass (e.g., `axe-core` via a headless browser, or an HTML structure linter) would catch heading hierarchy violations, missing ARIA labels, and colour contrast issues systematically. The question is whether the tooling cost is justified at current scale.
- [ ] **How should the responsive validation gap be addressed?** Currently responsive behaviour is validated by manual inspection. As the UI Architecture system evolves, this gap will grow. Defining a lightweight manual review protocol (specific viewports, specific routes, specific components) is more realistic than full browser automation at this stage.

### Tactical Workflow Integration

- [ ] **Should tactical workflows get integration-level validation that crosses the HTTP boundary?** Currently, tactical workflow tests operate at the use-case level or the domain level. A test that makes HTTP requests to the planner route, reads the response, and validates the rendered composition state would catch more. The cost is test complexity and fixture overhead.
- [ ] **How should planner screenshot-based evidence (for landing page and documentation) relate to testing?** If real planner state is used for the landing page showcases, is there a testing concern about that state remaining consistent and representative?

### Performance and Scale

- [x] **At what suite size does the full-suite run become unacceptably slow for per-slice use?** **Resolved (Phase 9.0):** 2,413 tests / ~22 minutes — Tier 5 is a session/pre-release gate, not a per-slice default.
- [ ] **Should a maximum per-test runtime be enforced?** Tests that take more than 1 second individually are candidates for review. A `pytest --durations=20` audit would surface slow tests.
- [ ] **When does the nightly full-regression run become worth setting up?** **Elevated priority:** recommended now that Tier 5 is ~22 minutes and Phase 8 work generates many Tier 0/4a slices per session.
- [ ] **Should `@pytest.mark.ui` be applied to all Tier 4b tests?** Would replace the manual file list in Section 3 and reduce maintenance as new UI test files are added.

---

---

## 14. Implementation Log

### Phase 1 — Practical Commands (Shipped 2026-05-18)

**What was added:**

| Item | Detail |
|---|---|
| Section 3 — Practical Commands | Copy-paste commands for all five tiers |
| Tier 0 (docs-only) | Explicit "no test run required" with rationale |
| Tier 1 (smoke) | `python -m pytest --collect-only -q` |
| Tier 2 (focused) | File-level commands + change→test mapping table |
| Tier 3 (tactical) | Multi-file tactical workflow group, PowerShell + single-line variants |
| Tier 4 (UI/template) | Multi-file UI group, PowerShell + single-line variants |
| Tier 5 (full suite) | `python -m pytest -q` with expected runtime note |
| Cursor prompt note | Added to document header — directs to Section 3 |
| `pyproject.toml` markers | 7 markers registered: `tactical`, `ui`, `discord`, `repository`, `workflow`, `smoke`, `slow` |

**What was NOT changed:**
- No test files modified
- No test behaviour changed
- No test files moved
- No CI/CD introduced
- No markers applied to individual test functions yet

**Validation performed:**
```
python -m pytest --collect-only -q
→ 1493 tests collected in 0.66s  ✓
```

### Phase 2 — Escalation Rules and Prompt Guardrails (Shipped 2026-05-18)

**Why this was added:**

The practical commands from Phase 1 defined *what* to run at each tier, but did not define *when to stop*. In practice, Cursor prompts were automatically escalating from a passing lower-tier run to a higher tier "for safety" — running Tier 5 after CSS changes, after documentation edits, or after isolated template wording adjustments. This pattern produced unnecessary full-suite runs, added latency to every iteration cycle, and created validation fatigue.

The specific workflow issue: prompts involving documentation-only or CSS-only changes were triggering `python -m pytest -q` (Tier 5) despite no Python logic being modified. The tier system was being used as a suggestion rather than a constraint.

**What was added:**

| Item | Detail |
|---|---|
| `### Validation Escalation Rule` | Explicit table: passing Tier N does not imply Tier N+1. Auto-escalation is prohibited. |
| `### Standard Prompt Validation Footer` | Canonical copy-paste text for future Cursor prompts, defining when Tier 5 is permitted. |
| `### Windows pytest PermissionError on Temp Cleanup` | Documents the known harmless Windows temp cleanup error; defines correct vs. incorrect response so it does not trigger escalation. |
| Checklist entries | Three new checked items added for the above additions. |

**What was NOT changed:**
- No test files modified
- No Python code modified
- No pytest configuration modified
- No `pyproject.toml` changes
- No test behaviour changed

**Validation performed:**

This is a documentation-only change. Per Section 3.7 and Tier 0: no pytest run is required or appropriate.

---

### Phase 9.0 Slice 1 — Risk-Scaled Validation Matrix (Shipped 2026-06-13)

**Why this was added:**

At 2,413 tests / ~22 minutes, Tier 5 per visual slice (Phase 8.7, 8.8) produced validation fatigue and contradicted the strategy's own "lowest honest tier" philosophy. Phase 9.0 audit findings were implemented as authoritative matrix guidance.

**What was added:**

| Item | Detail |
|---|---|
| Section 3.5 | Risk-Scaled Validation Matrix (authoritative) |
| Section 3.6 | Visual and identity change guidance |
| Section 3.7 | Session-level validation (per-slice, end-of-session, pre-release) |
| Tier 4a / 4b split | Section 3 + Section 4 tier definitions |
| Examples I, J | Phase 8.7 doctrine enforcement, Phase 8.8 brand continuity |
| Contradiction fixes | Removed "Tier 5 before any commit"; shared shell → 4a not 5; runtime/counts updated |
| Standard footer | Updated to reference matrix and Tier 4a default |

**What was NOT changed:**
- No test files modified
- No Python code modified
- No pytest markers applied (future phase)

**Validation performed:** Tier 0 — documentation only. No pytest run.

---

*Document version: Phase 9.0 Slice 1 — risk-scaled validation matrix — June 2026*
*No test reorganisation, CI/CD changes, or suite rewrites implied. Apply `@pytest.mark.ui` in a future phase to replace Tier 4b file lists.*
