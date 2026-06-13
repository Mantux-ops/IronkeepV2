"""Canonical tactical interpretation logic for IronkeepV2.

This module is the single authoritative source for:
- Role-family classification (slot role string → tactical family)
- Party grouping from flat slot rows (build_parties)
- Tactical tally derivation (per-party and composition-level)
- Tactical gap detection (missing roles, missing builds)
- Continuation hints (build coverage and player assignment state)

Used by:
- The Tactical Planner  (operation_planner.html via get_planner)
- The Composition Detail page (compositions_detail.html via get_composition_detail)
- The Compositions List page  (compositions_list.html via get_compositions_list)

Semantic boundary
-----------------
There are two distinct slot data sources in IronkeepV2.  Both pass through
the same grouping and classification logic here, but they represent different
things:

  composition_slot_templates  — the tactical formation as designed.
                                Represents *what roles and builds are planned*.
                                No assignment state; no player names.
                                Used by: get_composition_detail route.

  operation_slots             — the generated operational instance of the comp.
                                Represents *what slots exist for a live operation*.
                                Carries assignment state (via assigned_map).
                                Used by: get_planner route.

Both sources share the same fields: party_number, slot_index, role,
build_name, weapon_name.  build_parties() and derive_tactical_summaries()
work on both without modification.  Assignment / readiness state is
planner-only and handled by passing a populated assigned_map.

All functions are pure Python with no database or Jinja dependencies.
Tests live in tests/test_tactical_logic.py.
"""
from __future__ import annotations

__all__ = [
    "ROLE_FAMILIES",
    "role_family",
    "build_parties",
    "derive_tactical_summaries",
    "derive_composition_integrity",
]

# Ordered tuple of role family keys.
# Used as the canonical tally structure across all tactical surfaces.
ROLE_FAMILIES: tuple[str, ...] = (
    "tank", "healer", "dps", "support", "ranged", "default"
)


def role_family(role: str | None) -> str:
    """Classify a slot role string into a tactical role family.

    Returns one of the strings in ROLE_FAMILIES.

    Matching is substring-based on a lowercased input, applied in priority
    order: tank > healer > support > dps > ranged > default.

    This is the single authoritative mapping used by:
    - Slot card CSS (data-role attribute)
    - Party tally derivation
    - Compositions list role-mix column
    - All server-side gap detection

    The same classification must never be re-implemented in Jinja templates.
    Templates receive pre-annotated slot.role_family from their route handler.
    """
    r = (role or "").lower()
    if any(x in r for x in ("tank", "front", "brawl")):
        return "tank"
    if "heal" in r:
        return "healer"
    if any(x in r for x in ("support", "util")):
        return "support"
    if any(x in r for x in ("dps", "melee", "call", "engage")):
        return "dps"
    if any(x in r for x in ("ranged", "bow", "mage", "frost")):
        return "ranged"
    return "default"


def build_parties(slot_rows) -> dict[int, list]:
    """Group a flat sequence of slot rows into a party dict with role_family annotation.

    This is the single canonical path for party grouping used by both the
    composition detail preview and the live tactical planner.  Both routes
    call this function so grouping logic cannot diverge between surfaces.

    Parameters
    ----------
    slot_rows : iterable of slot dicts (or sqlite3.Row / dict-like objects).
        Must contain at least: ``party_number`` (int), ``slot_index`` (int),
        ``role`` (str | None), ``build_name`` (str | None),
        ``weapon_name`` (str | None).

        Expected ordering: ``ORDER BY party_number, slot_index`` — as
        guaranteed by both ``get_composition_slot_templates`` and
        ``get_operation_slots``.  Within-party slot order is preserved from
        the input sequence.

    Returns
    -------
    dict[int, list]
        ``{party_number: [slot_dict, ...]}``.  Each slot dict is a plain
        ``dict`` copy of the input row, extended with a ``role_family`` key
        set by :func:`role_family`.

    Ordering guarantees
    -------------------
    - Party keys are inserted in ascending ``party_number`` order (because
      the repository queries use ``ORDER BY party_number, slot_index``).
    - Within each party, slots are in ascending ``slot_index`` order
      (same reason).
    - Templates iterate parties with ``| sort`` so party ordering is also
      deterministic even if input order ever changes.

    Semantic boundary
    -----------------
    This function is input-agnostic: it does not know whether the rows come
    from ``composition_slot_templates`` or ``operation_slots``.  The caller
    determines the source; this function only groups and annotates.
    Assignment state (assigned_map) is handled downstream by
    :func:`derive_tactical_summaries`.
    """
    parties: dict[int, list] = {}
    for slot in slot_rows:
        slot_dict = dict(slot)
        slot_dict["role_family"] = role_family(slot_dict.get("role"))
        parties.setdefault(slot_dict["party_number"], []).append(slot_dict)
    return parties


def derive_tactical_summaries(
    parties: dict[int, list],
    assigned_map: dict,
    *,
    track_assignments: bool = True,
) -> tuple[dict, dict]:
    """Derive per-party and composition-level tactical summaries from slot data.

    Works for both live operation slots and read-only composition slot templates.

    Parameters
    ----------
    parties : dict[int, list]
        {party_number: [slot_dicts]}.  Each slot dict must contain at least:
          "id"          — slot identifier (str)
          "role"        — role label (str | None)
          "build_name"  — build name (str | None)
          "weapon_name" — weapon name (str | None)

    assigned_map : dict
        {slot_id: assignment_info} from the active operation.
        Pass ``{}`` when summarising a composition template (no assignments).

    track_assignments : bool, default True
        When True (operation planner), player-assignment counts are tracked
        and the continuation hint mentions unassigned players.
        When False (composition detail / template preview), assignment counts
        are suppressed from hints — the hint only reflects build coverage.

    Returns
    -------
    party_summaries : dict[int, dict]
        Keyed by party_number. Each entry:
          tally      — {role_family: count}
          built      — slots with build_name or weapon_name set
          total      — total slot count
          assigned   — slots with an active assignment (always 0 when
                       assigned_map is empty)
          gaps       — list[tuple[str, str]]: (severity, text) pairs
                       severity is "critical" (red) or "warn" (orange)
          open_slots — total - built (slots without any doctrine)
          open_core  — core-priority slots with no build (subset of open_slots)

    comp_summary : dict
        Full-composition totals with the same tally/built/total/assigned fields,
        plus:
          open_slots      — composition-wide open slot count
          open_core_slots — core-priority open slots across all parties
          hint            — continuation-hint string (None when no slots)
          hint_state      — "warn" | "ok" | "neutral"
    """
    party_summaries: dict[int, dict] = {}
    comp_tally    = {r: 0 for r in ROLE_FAMILIES}
    comp_built    = 0
    comp_assigned = 0
    comp_total    = 0

    for party_num, party_slots in parties.items():
        tally    = {r: 0 for r in ROLE_FAMILIES}
        built    = 0
        assigned = 0

        for slot in party_slots:
            fam = role_family(slot.get("role"))
            tally[fam]      += 1
            comp_tally[fam] += 1
            if slot.get("build_name") or slot.get("weapon_name"):
                built        += 1
                comp_built   += 1
            if slot.get("id") in assigned_map:
                assigned      += 1
                comp_assigned += 1

        total       = len(party_slots)
        comp_total += total

        # Open-core: core-priority slots that have no build assigned yet.
        open_core = sum(
            1 for slot in party_slots
            if not (slot.get("build_name") or slot.get("weapon_name"))
            and slot.get("priority") == "core"
        )

        gaps: list[tuple[str, str]] = []
        if total > 0 and tally["healer"] == 0:
            gaps.append(("critical", "No healer"))
        if total > 0 and tally["tank"] == 0:
            gaps.append(("critical", "No tank"))
        unbuilt = total - built
        if unbuilt == 1:
            gaps.append(("warn", "1 open"))
        elif unbuilt > 1:
            gaps.append(("warn", f"{unbuilt} open"))

        party_summaries[party_num] = {
            "tally":      tally,
            "built":      built,
            "total":      total,
            "assigned":   assigned,
            "gaps":       gaps,
            "open_slots": unbuilt,   # slots without any build/weapon
            "open_core":  open_core, # core-priority slots without a build
        }

    # Composition-level open-slot aggregates
    comp_open_slots = comp_total - comp_built
    comp_open_core  = sum(ps["open_core"] for ps in party_summaries.values())

    # Composition-level continuation hint
    unbuilt    = comp_open_slots
    unassigned = comp_total - comp_assigned

    if comp_total == 0:
        hint       = None
        hint_state = "neutral"
    elif not track_assignments:
        # Template / preview mode: only report build coverage, not player state.
        if unbuilt > 0:
            s          = "s" if unbuilt != 1 else ""
            hint       = f"{unbuilt} open slot{s}"
            hint_state = "warn"
        else:
            hint       = "All slots built"
            hint_state = "ok"
    elif unbuilt > 0 and unassigned > 0:
        hint = (
            f"{unbuilt} open slot{'s' if unbuilt != 1 else ''}"
            f" · {unassigned} unassigned"
        )
        hint_state = "warn"
    elif unbuilt > 0:
        hint       = f"{unbuilt} open slot{'s' if unbuilt != 1 else ''}"
        hint_state = "warn"
    elif unassigned > 0:
        hint       = f"All slots built · {unassigned} player{'s' if unassigned != 1 else ''} still unassigned"
        hint_state = "warn"
    else:
        hint       = "All slots built and assigned"
        hint_state = "ok"

    comp_summary = {
        "tally":           comp_tally,
        "built":           comp_built,
        "total":           comp_total,
        "assigned":        comp_assigned,
        "open_slots":      comp_open_slots,  # slots with no build/weapon
        "open_core_slots": comp_open_core,   # core-priority slots with no build
        "hint":            hint,
        "hint_state":      hint_state,
    }
    return party_summaries, comp_summary


def derive_composition_integrity(
    parties: dict[int, list],
    comp_summary: dict,
    party_summaries: dict[int, dict],
) -> list[dict]:
    """Derive composition-level integrity warnings from slot template data.

    This is a composition-level synthesis that complements the per-party
    tactical gap badges already rendered in the party-summary strip.
    It surfaces structural issues that require scanning all party panels
    to detect, making them immediately visible without counting.

    Signal hierarchy
    ----------------
    Integrity warnings (this function) describe the composition-level
    summary: "how many parties have this gap".  Per-party tac-gap-badges
    (derive_tactical_summaries) identify exactly which party is affected.
    The two signals are complementary, not redundant: warnings answer
    "what is the overall problem", badges answer "where is it".

    Data model note
    ---------------
    IronkeepV2 does not have ``role_counts`` or ``build_slot_counts_json``
    composition fields — these were described in planning documents but not
    implemented.  The ``composition_slot_templates`` table is the single
    source of truth for composition structure.  This function therefore
    analyses only actual slot template data.

    Parameters
    ----------
    parties : dict[int, list]
        Output of build_parties().  {party_number: [slot_dict, ...]} with
        role_family annotation.
    comp_summary : dict
        Output of derive_tactical_summaries() — full-composition totals.
    party_summaries : dict[int, dict]
        Output of derive_tactical_summaries() — per-party tactical summaries.

    Returns
    -------
    list[dict]
        Ordered list of integrity warnings.  Each entry:
          severity — "critical" | "warn" | "info"
          code     — machine-readable identifier (stable; used in tests/CSS)
          message  — concise human-readable summary (composition-level)
          hint     — optional actionable follow-up sentence; may be None

        Returns an empty list when the composition has no integrity issues.
        Returns early (one warning only) when the composition is empty.

    Warning codes
    -------------
    empty_template           — no slots defined at all
    parties_missing_healer   — N of M parties have no healer slot
    parties_missing_tank     — N of M parties have no tank slot
    uneven_party_sizes       — parties have significantly different slot counts
    """
    warnings: list[dict] = []

    # ── Empty composition ─────────────────────────────────────────────
    if comp_summary["total"] == 0:
        warnings.append({
            "severity": "critical",
            "code":     "empty_template",
            "message":  "No slot templates defined.",
            "hint":     "Add slots to this composition before using it in an operation.",
        })
        return warnings  # no further checks are meaningful

    n_parties = len(parties)

    # ── Core slots unfilled ───────────────────────────────────────────
    open_core = comp_summary.get("open_core_slots", 0)
    if open_core > 0:
        s = "s" if open_core != 1 else ""
        warnings.append({
            "severity": "warn",
            "code":     "core_slots_unfilled",
            "message":  f"{open_core} core slot{s} with no build assigned.",
            "hint":     "Core slots mark priority positions — assign doctrine before using this composition.",
        })

    # ── Parties missing healer ────────────────────────────────────────
    missing_healer_pnums = sorted(
        pn for pn, psumm in party_summaries.items()
        if psumm["total"] > 0 and psumm["tally"]["healer"] == 0
    )
    missing_healer = len(missing_healer_pnums)
    if missing_healer == n_parties:
        warnings.append({
            "severity": "critical",
            "code":     "parties_missing_healer",
            "message":  "No healer slot in any party.",
            "hint":     "All parties are highlighted below.",
        })
    elif missing_healer > 0:
        has = "have" if missing_healer != 1 else "has"
        party_word = "parties" if missing_healer != 1 else "party"
        labels = ", ".join(f"Party {pn}" for pn in missing_healer_pnums)
        are = "are" if missing_healer != 1 else "is"
        warnings.append({
            "severity": "warn",
            "code":     "parties_missing_healer",
            "message":  f"{missing_healer} of {n_parties} {party_word} {has} no healer slot.",
            "hint":     f"{labels} {are} highlighted below.",
        })

    # ── Parties missing tank ──────────────────────────────────────────
    missing_tank_pnums = sorted(
        pn for pn, psumm in party_summaries.items()
        if psumm["total"] > 0 and psumm["tally"]["tank"] == 0
    )
    missing_tank = len(missing_tank_pnums)
    if missing_tank == n_parties:
        warnings.append({
            "severity": "critical",
            "code":     "parties_missing_tank",
            "message":  "No tank slot in any party.",
            "hint":     "All parties are highlighted below.",
        })
    elif missing_tank > 0:
        has = "have" if missing_tank != 1 else "has"
        party_word = "parties" if missing_tank != 1 else "party"
        labels = ", ".join(f"Party {pn}" for pn in missing_tank_pnums)
        are = "are" if missing_tank != 1 else "is"
        warnings.append({
            "severity": "warn",
            "code":     "parties_missing_tank",
            "message":  f"{missing_tank} of {n_parties} {party_word} {has} no tank slot.",
            "hint":     f"{labels} {are} highlighted below.",
        })

    # ── Uneven party sizes ────────────────────────────────────────────
    if n_parties > 1:
        party_items = sorted(parties.items())
        sizes = [len(slots) for _, slots in party_items]
        min_sz, max_sz = min(sizes), max(sizes)
        if max_sz - min_sz > 1:
            modal = max(set(sizes), key=sizes.count)
            undersized = [(pn, len(slots)) for pn, slots in party_items if len(slots) < modal]
            oversized  = [(pn, len(slots)) for pn, slots in party_items if len(slots) > modal]
            if undersized:
                labels = ", ".join(f"Party {pn} ({sz})" for pn, sz in undersized)
                hint = (
                    f"{labels} — most parties have {modal} slots. "
                    "This may be intentional for a support or command slot structure."
                )
            elif oversized:
                labels = ", ".join(f"Party {pn} ({sz})" for pn, sz in oversized)
                hint = f"{labels} — other parties have {modal} slots."
            else:
                hint = f"Parties range from {min_sz} to {max_sz} slots."
            warnings.append({
                "severity": "info",
                "code":     "uneven_party_sizes",
                "message":  "Party slot counts are uneven.",
                "hint":     hint,
            })

    return warnings
