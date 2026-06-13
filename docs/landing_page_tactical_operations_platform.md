# IronkeepV2 — Landing Page Design Planning
## Option 2: Tactical Operations Platform

> **Status: Phases 1–5 complete. Phase 6 is conditional — requires real, verifiable trust signals before beginning.**
> This document defines design direction, UX structure, messaging philosophy, and branding strategy for the IronkeepV2 landing page. Open design questions are resolved in Section 13. Implementation log in Section 14.

---

## Checklist Overview

- [x] Vision defined
- [x] Honest positioning defined
- [x] Core messaging direction defined
- [x] Landing page structure defined (all sections)
- [x] Visual design direction defined
- [x] Tactical planner showcase philosophy defined
- [x] Composition-first philosophy defined
- [x] UX principles defined
- [x] Responsiveness philosophy defined
- [x] Technical philosophy defined
- [x] Future implementation phases defined
- [x] Explicit non-goals defined
- [x] Open design questions captured and resolved (Section 13)
- [x] Phase 1 — Visual Foundation implemented (Section 14)
- [x] Phase 2 — Visual Scaffolding implemented (Section 14)
- [x] Phase 3 — Tactical Showcase Composition implemented (Section 14)
- [x] Phase 4 — Content Refinement & Information Hierarchy implemented (Section 14)
- [x] Phase 5 — Polish, Accessibility & Production Readiness implemented (Section 14)
- [x] Auth redirect fix — post-login target updated from `/` to `/workspaces` (Section 14)

---

## 1. Vision

### Intended Feeling

IronkeepV2 should feel like operational software that guild officers trust during real events. Not a marketing page. Not a gaming product page. Not a SaaS trial pitch.

The landing page should evoke the feeling of opening a command center: structured, purposeful, dense with meaning, immediately legible. An officer who lands on the page should feel — within five seconds — that this tool was built for people who coordinate under pressure, not for casual players experimenting with a free tier.

The emotional arc of the landing page:

1. **Recognition** — "This is built for people doing what I do."
2. **Credibility** — "This looks like it actually works."
3. **Clarity** — "I understand what it does without reading a wall of text."
4. **Pull** — "I want to see how it handles my specific problem."

This is not excitement or hype. It is operational confidence — the feeling a well-designed tool should produce before you even log in.

### Command-Center Inspiration

The visual and structural model is the operational dashboard, not the product landing page. Think:

- Flight operations briefing rooms — structured, annotated, everything has a position for a reason
- Military command overlays — information density is a feature, not a problem to be solved
- Tournament bracket management software — functional, precise, legible under time pressure
- Modern devops dashboards — dark surfaces, status signals, real data visible at a glance

Not: hero illustrations, animated particles, floating feature cards on white backgrounds.

### Operational/Tactical Atmosphere

The atmosphere should be produced by:

- **Information density** — the page shows real operational structure, not abstract feature claims
- **Dark palette** — deep backgrounds with precise accent colours signalling role and state
- **Typography discipline** — monospaced or semi-monospaced elements where operational data appears; variable-weight type for headings that earn hierarchy
- **Controlled negative space** — breathing room between sections, but no vast empty hero padding that signals emptiness
- **Purposeful layout** — grid systems that echo the planner's own party grid logic

### How IronkeepV2 Should Feel Different from IronkeepV1

IronkeepV1 was a functional coordination system. It worked. It did not feel like a platform.

IronkeepV2 must feel like a deliberate step toward something more considered — not a cosmetic upgrade, but a structural reorientation. The landing page should communicate that difference without requiring the visitor to dig into features. The visual and information hierarchy itself should signal the shift:

| IronkeepV1 | IronkeepV2 |
|---|---|
| Admin tool aesthetic | Operational platform aesthetic |
| Forms and tables | Composition views and role grids |
| Data entry workflow | Command-center workflow |
| Feature list framing | Operational outcome framing |
| Implicit readiness | Explicit readiness signals |
| Guild management | Tactical orchestration |

---

## 2. Honest Positioning

### What IronkeepV2 Actually Is Today

IronkeepV2 is a guild coordination platform for Albion Online guilds that run structured operations (CTAs). It manages:

- Operation lifecycle: creation → composition planning → slot assignment → signups → readiness → attendance → Discord posting
- Tactical compositions: reusable role-based templates with build assignment
- Tactical planner: party grid with slot cards, role identity, build/weapon representation
- Roster management: player profiles, participation tracking, reliability signals
- Discord integration: announcements, roster posting, check-in via Discord buttons

It is a real, functional system. It is not at scale. It is not in production for thousands of guilds. It is purpose-built, well-engineered, and evolving.

### What It Is Evolving Toward

The direction is clear: a unified tactical operations platform where every phase of guild coordination — from draft composition to post-operation analysis — flows through a single coherent interface. The planner, the roster, the Discord layer, and the attendance record all connect to a common operational state.

IronkeepV2 is early in this trajectory. The foundation is solid. The surface is not yet complete.

### How to Communicate Ambition Honestly

Honest ambition looks like:

- **Showing real capability** — real planner UI, real compositions, real operation state — not rendered from invented data
- **Describing what the system does** — not what it will someday do at massive scale
- **Naming the domain clearly** — guild coordination for structured Albion Online operations
- **Letting the tool speak for itself** — the operational density of the UI is more convincing than superlatives

Dishonest ambition looks like:

- Claiming "trusted by hundreds of guilds" before that is true
- Showing metrics that do not exist
- Using enterprise SaaS language to make a guild tool sound like a B2B platform
- Inflating the scope with "AI-powered" or "industry-leading" language

### Messaging Principles

1. **Describe outcomes, not abstractions.** Not "streamline your workflow" — say "your officer knows which slots are unfilled before the op starts."
2. **Name the audience specifically.** Not "team leaders" or "community managers" — say "guild officers" and "CTA commanders."
3. **Describe the problem it solves before the solution.** Officers switching between Discord, spreadsheets, and DMs to plan a composition is the real pain. Name it.
4. **Do not over-claim the current state.** The platform is operational, not at scale. That is fine to communicate implicitly through restraint.
5. **Let density signal capability.** A page that shows a real 20-man comp grid — filled slots, role distribution, readiness state — communicates more than any feature bullet.

### Tone Principles

- **Precise.** Every word earns its place. No filler adjectives.
- **Operational.** Write from inside the workflow, not above it.
- **Respectful of intelligence.** Guild officers reading this page know MMO coordination. Do not over-explain.
- **Grounded.** No superlatives, no exclamation points, no hype punctuation.
- **Direct.** Short sentences. No passive voice if avoidable.

### Authenticity Rules

- [ ] No invented testimonials
- [ ] No fake guild counts
- [ ] No fake user numbers
- [ ] No fake operation statistics
- [ ] No fake activity metrics
- [ ] No placeholder "lorem ipsum" guild names as social proof
- [ ] No "as featured in" if that has not happened
- [ ] No urgency tactics ("Sign up before slots fill")
- [ ] No inflated competitive positioning ("the only platform that...")
- [ ] Screenshots or UI showcases must come from real system state, not invented mockups

---

## 3. Core Messaging Direction

### The Central Message

IronkeepV2 is not a productivity tool. It is not a Discord bot with a dashboard. It is not a spreadsheet replacement.

It is a **tactical coordination platform for guild officers who run structured Albion Online operations** — from composition draft to operation execution.

The landing page should never need to say "all-in-one." If the system genuinely handles the full coordination lifecycle, showing that is more convincing than claiming it.

### Candidate Message Directions

These are directional possibilities for headlines, taglines, and section framing. None are final.

**Direction A — Tactical Coordination**
> "From composition draft to Discord post — your operation, structured."

Emphasis: the full arc. Planning → readiness → communication. No step is missing from the workflow.

**Direction B — Composition Planning**
> "Your composition is more than a slot list. Build it like one."

Emphasis: role identity, build assignment, party structure. Compositions as tactical assets, not checklists.

**Direction C — Operational Readiness**
> "Know who's ready before the operation starts."

Emphasis: readiness signals, slot fill state, gap detection. Officers don't get surprised.

**Direction D — Structured Guild Execution**
> "Guild coordination built for officers who plan, not improvise."

Emphasis: the distinction from Discord-only, casual coordination. This tool is for serious structured play.

**Direction E — Command-Center Workflow**
> "Every role. Every slot. Every readiness signal. One surface."

Emphasis: information consolidation. The officer does not need to leave the tool to understand what's happening.

### Language to Avoid

| Avoid | Why |
|---|---|
| "Revolutionary" | Meaningless superlative |
| "AI-powered" | Not a feature of IronkeepV2 |
| "All-in-one platform" | Generic SaaS cliché |
| "Streamline your workflow" | Says nothing specific |
| "Next-generation" | Inflated |
| "Game-changing" | Cliché; also inappropriate register |
| "Trusted by thousands" | Only if true |
| "Industry-leading" | Unverifiable and overreaching |
| "Effortless" | Misrepresents coordination complexity |
| "Seamless" | Overused and meaningless |
| "Powerful" | Unearned and vague |

---

## 4. Landing Page Structure

> All sections are planning-level only. No templates, routes, or assets implied.

---

### Section 1 — Hero

**Purpose:** Establish identity, operational atmosphere, and primary message within 5 seconds of arrival.

**Emotional goal:** Recognition and credibility. The visitor — an Albion Online guild officer — should immediately feel that the page understands their operational context.

**UX role:** Anchor the page. Orient the visitor. Set the visual and tonal register for everything below.

**Operational value:** The hero does not list features. It names the context (Albion Online guild operations), communicates the scope (composition-to-execution coordination), and shows — not tells — the system's visual character.

**Design notes:**
- Headline: short, precise, operational. Two lines maximum.
- Subheadline: one sentence describing the operational scope. No more.
- Visual: a dark, dense planner preview — a cropped, real-state composition grid showing role cards and slot fill status. Not illustrated. Not decorative.
- Primary CTA: clear, single, functional. Not "Start your free trial" — something specific to the operational context.
- No animation on first load beyond a minimal fade. No hero video. No particle background.
- No social proof counts in the hero unless real and verified.

---

### Section 2 — Tactical Planner Showcase

**Purpose:** Communicate the core planning surface — the heart of IronkeepV2 — through real operational density.

**Emotional goal:** Competence. The visitor should see something that looks more capable than anything they have used before for this purpose.

**UX role:** The first substantive proof of value. This section converts interest from the hero into belief in the capability.

**Operational value:** Shows officers that slot-level orchestration, role identity, build assignment, and readiness state are all visible in a single surface — without needing a paragraph of explanation.

**Design notes:**
- The planner visual is the primary element. Text supports it, not the other way around.
- Three to five callout annotations pointing at specific planner elements (role badge, build name, readiness state, party grouping, gap badge) with short precise labels.
- No long feature descriptions. The annotations are the description.
- If an interactive preview is ever built, it should reflect real state, not a demo mode with invented data.

---

### Section 3 — Composition Planning Showcase

**Purpose:** Explain the composition library as a tactical asset store — not a list of templates.

**Emotional goal:** Recognition of depth. Officers who have maintained compositions in Discord or spreadsheets should recognise immediately how this differs.

**UX role:** Differentiates IronkeepV2 from simpler coordination tools by surfacing the strategic layer above individual operations.

**Operational value:** Compositions are reusable role-based tactical templates. The officer builds a composition once, refines it over multiple operations, and reuses it. The landing page should communicate this operational continuity.

**Design notes:**
- Show the compositions list view: role tallies, active operation usage, name search — all visible.
- A side-by-side or annotated layout: composition in the library → composition assigned to an operation. Shows the connection.
- Messaging frames compositions as assets with operational history, not form fields.

---

### Section 4 — Operational Workflow Showcase

**Purpose:** Show the full lifecycle: draft → assign → post → check in → record.

**Emotional goal:** Confidence in completeness. The officer should see that the system handles the full arc, not just one phase.

**UX role:** Removes the "but what about X phase of coordination" question before it is asked.

**Operational value:** IronkeepV2 manages operation creation, slot assignment, Discord posting, player check-in, and attendance recording. The landing page should communicate this as a connected sequence, not a feature list.

**Design notes:**
- A horizontal flow diagram (not animated) showing the five to six phases: Draft → Plan → Assign → Post → Confirm → Record.
- Each phase has one sentence of description and one visual signal (an icon or minimal illustration — not decorative, functional).
- No step claims the platform does something it does not yet do.

---

### Section 5 — Discord Integration

**Purpose:** Position Discord as a coordination surface, not the operational brain.

**Emotional goal:** Relief for guilds currently trying to run operations from Discord alone.

**UX role:** Addresses a likely question: "Can this work with our existing Discord setup?" before it is asked.

**Operational value:** Officers post announcements, share roster links, and receive check-in responses via Discord — all driven from the web platform. Discord does not own the state. The platform does.

**Design notes:**
- Show the Discord output — an announcement embed, a roster post, a check-in button — alongside the platform state that produced it.
- One sentence framing: Discord handles communication. IronkeepV2 handles coordination.
- No claims about Discord automation features that do not exist yet.

---

### Section 6 — Readiness Visibility

**Purpose:** Communicate the readiness signal system — what it shows, why it matters before an operation.

**Emotional goal:** Confidence that the officer will not be surprised on the day of an operation.

**UX role:** Surfaces a specific, concrete, operational pain point: not knowing who has confirmed, who is missing, which roles are unfilled, which slots are at risk.

**Operational value:** The system shows slot fill state, player check-in status, and role gap signals before the operation begins. No spreadsheet archaeology. No DM polling.

**Design notes:**
- Show a readiness summary: slots filled/total, roles present, check-in rate.
- Use the real visual language from the planner (state-based border accents, gap badges, status indicators).
- Do not fabricate readiness numbers. Use an illustrative but clearly labelled example.

---

### Section 7 — Tactical Orchestration Explanation

**Purpose:** Explain how IronkeepV2 differs structurally from spreadsheet, Discord-only, and generic MMO tool workflows — without attacking competitors.

**Emotional goal:** Intellectual credibility. The officer should feel the page understands coordination complexity.

**UX role:** Answers the implicit question: "How is this different from what I already do?" without a comparison table or competitor naming.

**Operational value:** Frames the structural advantage: a single operational state that all phases — planning, communication, readiness, attendance — read from and write to. Not a patchwork of tools.

**Design notes:**
- Not a comparison table (too confrontational for a planning document page).
- A brief conceptual diagram or annotated layout showing information flow from composition → slot → player → attendance.
- Writing is descriptive and precise, not marketing.

---

### Section 8 — FAQ

**Purpose:** Proactively answer real questions from guild officers evaluating the tool.

**Emotional goal:** Transparency and honesty. The FAQ should feel like it was written by someone who actually uses the system.

**UX role:** Reduces friction to decision. Officers who have questions that aren't answered leave. Officers whose questions are answered honestly stay.

**Operational value:** Real officers will ask real operational questions. The FAQ should answer them directly.

**Candidate FAQ questions (planning only — answers to be written when real):**
- Does it work with any Albion Online server type (HCE, open world, ZvZ)?
- Does the bot require specific Discord permissions?
- Can multiple officers manage the same operation?
- How does player check-in actually work?
- Is there a mobile app?
- What happens if Discord goes down during an operation?
- Is this open source / self-hosted?
- How is this different from [common alternative]?

**Design notes:**
- Expandable accordion, not a wall of text.
- Answers should be short and honest. "Not yet" is a valid answer. "Planned for a future release" is honest if true.
- No FAQ question should be invented to make the product look better.

---

### Section 9 — Footer

**Purpose:** Navigation, contact, and context anchor.

**Emotional goal:** Professional closure. The footer should feel like it belongs to a real operational tool, not a startup landing page.

**UX role:** Provides secondary navigation, quick links, and context for the project.

**Operational value:** Minimal but complete.

**Design notes:**
- Dark background, consistent with page palette.
- Links: documentation, Discord (if public server exists), GitHub (if public), changelog (if public).
- No fake "Press" or "Investors" sections.
- No inflated footer link density to look like a big company.
- Optional: a short honest description of the project — one or two sentences, factual.

---

## 5. Visual Design Direction

### Dark Tactical Palette

The base palette should derive from the operational character of the platform — not from gaming aesthetics.

**Palette principles:**
- Deep background: near-black with a very slight cool tint (not pure black, not navy)
- Surface elevation: two to three tiers of surface lightness — base, card, elevated card — to create spatial hierarchy without colour noise
- Accent colours: functional, not decorative. Role family colours (tank, DPS, healer, support) from the existing planner system should appear on the landing page in the same registers they appear inside the app
- Status colours: green (ready/filled), amber (at risk/gap), red (missing/critical) — these are operational signals, not marketing colour choices
- Neutral text: two to three weights of grey for body, secondary, and muted text — never flat white on black for body copy

**What to avoid:**
- Neon glow accents as decoration
- Purple/gold esports palette
- Rainbow gradient hero sections
- Dark mode as aesthetic trend (it must be dark because the tool is dark, not for style)

### Typography Philosophy

- **Headings:** strong weight, tight tracking, short lines — hierarchical, not decorative
- **Body copy:** legible at information density, comfortable line height
- **Operational data** (slot names, role labels, build names in showcases): monospaced or tabular numerals to preserve alignment
- **No display fonts** that signal "gaming" — no condensed athletic typefaces, no serif with fantasy connotations
- **Size scale:** functional hierarchy — one H1 per section block, supporting text clearly subordinated

### Spacing Philosophy

- Dense where it serves operational communication (planner showcases, role grids)
- Breathable between sections to signal transitions and rest the eye
- Never "design agency whitespace" — large hero padding that is empty by design
- The planner showcase should look as dense as the planner, because the density is the point

### Operational Density Philosophy

The landing page is allowed — and expected — to be more visually dense than a standard SaaS landing page. The density communicates capability. A sparse landing page for a tactical coordination tool is a false signal.

Officers evaluating guild tools understand grid layouts, role notation, and status signals. Density that would confuse a general consumer audience is appropriate for this audience.

**Density rule:** Every dense element must be legible and annotated. Dense for its own sake is clutter. Dense-and-legible is signal.

### Hierarchy Philosophy

- One primary element per section — planner grid, composition list, workflow diagram
- Supporting text explains; it does not lead
- Status signals (role colours, readiness states) carry hierarchy through colour, not just size
- No section should require reading to understand — the visual should communicate the premise before the copy explains it

### Animation Restraint Philosophy

- No hero animations
- No scroll-triggered animations that transform content
- No particle effects, no floating elements, no parallax
- Acceptable: a single, minimal fade-in on first load (CSS only, no JS required)
- Acceptable: accordion expand/collapse in the FAQ
- Acceptable: a hover state on CTAs that is functional, not theatrical

**Principle:** If removing the animation would improve the page, it should be removed.

### Iconography Direction

- Functional icons that carry meaning — role family identifiers, status indicators, operation phase markers
- No decorative icons that exist to break up text
- Icons used in the planner should be the same icons (or their equivalents) used in the landing page showcases — visual consistency between marketing and tool is a trust signal
- No generic SaaS icon packs (check marks, lightbulbs, rockets)

---

## 6. Tactical Planner Showcase Philosophy

### The Showcase Premise

The planner is the most distinguishing surface of IronkeepV2. The landing page showcase of the planner must do what a paragraph of feature descriptions cannot: show an officer what it feels like to run a composition.

The showcase is not a screenshot. It is a deliberately composed, annotated view of the planner in a real operational state.

### Operational Density

The showcase should show a composition in progress — not empty, not fully complete. Mid-state is the most convincing operational state because it shows the system doing real work: some slots filled, some at risk, some empty, roles distributed across parties, readiness signals active.

An empty planner proves nothing. A full planner is too clean to be believable. Mid-state is honest and operational.

### Role Identity

The role colour system — tank, DPS, healer, support — should be visible in the showcase as it appears in the real planner. Officers scanning the showcase should recognise their own coordination vocabulary without needing a legend.

### Tactical Grouping

Party groupings should be visible. The showcase should show the 5-person party grid structure, not a flat slot list. Party composition as a unit of tactical planning — not just as a container — should be legible from the showcase without annotation.

### Readiness Visibility

At least one gap badge, one at-risk state, and one filled state should be visible in the showcase. This is not pessimism — it is realism. Officers do not need to see a perfect composition. They need to see that the system surfaces imperfection clearly.

### Slot Orchestration

Individual slot cards should be distinguishable — role badge, build name, weapon name, player assignment (if present). The showcase should communicate that each slot has a specific tactical identity, not just a position number.

### Composition Readability

The role tally strip — the count of tanks, healers, DPS, support across the full composition — should appear in the showcase. This is the single most useful at-a-glance signal for a composition lead evaluating a draft comp.

### Scan Speed

The showcase must be readable within 5 seconds. If it takes longer to understand, the annotation layer has failed. Each callout annotation should point at one thing and say one thing.

### What the Showcase Is Not

- Not a cinematic render of a composition
- Not an illustrated game screenshot
- Not a mockup with invented guild names and imaginary builds
- Not a marketing asset that diverges from what the real UI looks like

---

## 7. Composition-First Philosophy

### How IronkeepV2 Differs

**From spreadsheet workflows:**
Spreadsheets require column management, manual role counting, and human reconciliation when assignments change. IronkeepV2 computes role distribution automatically, surfaces gaps visually, and keeps assignment state authoritative without manual bookkeeping.

**From Discord-only coordination:**
Discord-only coordination distributes operational state across message history, threads, and DMs. State becomes unknowable without reading back through channel history. IronkeepV2 maintains a single authoritative operational state that Discord communicates, but does not own.

**From generic MMO tools:**
Generic tools are designed for generic coordination. IronkeepV2 is designed specifically for the Albion Online CTA coordination workflow: fixed party sizes, specific role families, weapon-based builds, structured signups, and explicit check-in confirmation. The domain specificity is a feature.

### Tactical Orchestration

A composition is not a list of player names. It is a tactical structure:

- Defined party slots with assigned roles and builds
- Role distribution calculated across the full composition
- Gap detection that surfaces structural weaknesses before the operation
- Readiness state per slot that reflects who has confirmed

The composition is the tactical blueprint. The operation is the execution of that blueprint. IronkeepV2 keeps both in sync.

### Operational Continuity

Compositions persist between operations. A composition that has run five operations has five data points of real operational history. Officers refine compositions based on what worked. IronkeepV2 surfaces active-operation usage counts on the compositions list precisely because this continuity is the value.

### Readiness Visibility

Readiness is not a single boolean. IronkeepV2 surfaces slot-level readiness (is this slot assigned and confirmed?), role-level readiness (does the comp have the role distribution it planned for?), and player-level readiness (who has checked in?). This three-layer readiness model is not available in spreadsheet or Discord-only workflows.

### Composition Execution

The composition is not finalised and forgotten. Officers continue to make slot assignments, swap builds, and update readiness signals as the operation approaches. The planner is a live operational surface, not a document that is created and then abandoned.

---

## 8. UX Principles

### Operational Clarity

Every section of the landing page should communicate one clear operational thing. No section should require the visitor to synthesise multiple competing ideas. If a section needs two paragraphs to explain its premise, the premise is too complex.

### Tactical Readability

Visual elements on the landing page should be legible at the speed an officer reads the planner. Dense information should be structured — annotated, grouped, colour-coded — not presented as unstructured walls.

### Scan Speed

A visitor should be able to scan the full landing page structure in 30–45 seconds and understand what IronkeepV2 does, who it is for, and what the primary capability is. This means headlines carry weight, visual showcases carry meaning, and body copy supports rather than leads.

### Compositional Hierarchy

Information should be organised the way the planner organises information: primary signals (party grid, readiness state) are visually dominant; secondary signals (build names, slot notes) are accessible but subordinated; tertiary information (history, metadata) is collapsed or absent until requested.

### Low-Friction Workflow

The landing page should not make the visitor work. Navigation is clear. CTAs are singular and purposeful. Sections flow in a logical operational sequence. No decisions are required before the visitor reaches the CTA.

### Command-Center Feeling

The page should feel like entering an operational environment, not browsing a product catalogue. The visual language — dark surfaces, status signals, role colour system — is continuous from the landing page into the application itself. There is no aesthetic discontinuity between "the marketing surface" and "the tool."

### Honesty Over Hype

Where the tool has limitations, the FAQ and positioning should acknowledge them honestly. An honest "not yet available on mobile" is more trust-building than a vague non-answer. Officers evaluating guild tools have been burned by overcommitted tools before. Honesty is a competitive advantage.

---

## 9. Responsiveness Philosophy

### Desktop-First Tactical UX

The primary design surface is desktop — 1280px and above. Guild officers planning operations are at their desktop, not their phone. The planner showcase, composition grid, and workflow diagram are all desktop-native surfaces. The landing page should be designed for this context first.

### Tablet Operational Support

At tablet widths (768–1024px), the page should remain fully functional and operationally legible. Planner showcases may scale down but should not collapse to a description-only view — the visual is too important. Two-column layouts may stack to single-column. Navigation should remain accessible.

### Mobile Review Philosophy

The mobile landing page is a review context, not a primary evaluation context. Officers visiting on mobile are likely checking something they discovered on desktop. The mobile layout should:

- Preserve the headline and primary CTA
- Collapse the planner showcase to a clearly labelled, scrollable view (not hidden)
- Stack all multi-column layouts
- Maintain readability of the FAQ and operational workflow diagram

Mobile should not receive a different page — it should receive a simplified stacking of the same content.

### What Should Remain Dense

- Role colour indicators and status signals should remain visible at all breakpoints — their information density is the point
- The planner showcase should not degrade to a single screenshot thumbnail on mobile — it should remain an annotated view, even if smaller
- The FAQ accordion should remain interactive at all breakpoints

### What Should Simplify

- Multi-column section layouts stack to single-column
- Navigation collapses to a minimal mobile header
- Annotation callouts on the planner showcase may reduce from five to two at mobile sizes

---

## 10. Technical Philosophy

### Performance

The landing page should load fast. No external dependencies that block render. No large JavaScript bundles. No hero video autoplay. No third-party tracking scripts that add latency. A landing page for a tool that emphasises operational speed should itself be operationally fast.

### Server-Rendered Simplicity

Consistent with the rest of IronkeepV2, the landing page should be server-rendered Jinja2 HTML with CSS. No client-side framework. No hydration. No state management. The page is static in operational terms — it does not query live data.

If future phases introduce a live planner preview (read-only), it should be designed as a progressively enhanced addition, not an architectural requirement for the base page.

### Accessibility

- Semantic HTML throughout: headings in correct order, landmarks, ARIA labels on interactive elements
- Colour is not the only signal — role colours are accompanied by text labels or icons
- Keyboard navigation for FAQ accordion and navigation
- Sufficient contrast at all text sizes
- No motion that cannot be disabled via `prefers-reduced-motion`

### Maintainability

The landing page must be maintainable by the same team that maintains the rest of IronkeepV2. No novel CSS architectures that diverge from the existing token system. No new build steps. No tooling dependencies introduced solely for the landing page.

### Progressive Enhancement

The base experience — readable, navigable, informative — must work without JavaScript. The FAQ accordion should have a CSS-only fallback (or open by default on no-JS). No showcase element should require JavaScript to be visible.

### Avoid

- Animation-heavy architecture that requires JS animation libraries
- Frontend framework dependency (React, Vue, Svelte) for a static marketing page
- Fake interactivity: planner previews that look interactive but are not
- Infinite scroll or lazy-load patterns that fragment the page experience

---

## 11. Implementation Phases

### Phase 1 — Visual Foundation ✅ Complete

- [x] Audit existing CSS tokens for reuse vs. extension — no additions required; existing token set is sufficient for all Phase 1 primitives
- [x] Define landing page colour token extension — none needed; `tokens.css` already covers all backgrounds, semantic colours, role colours, spacing, and typography used in the landing surface
- [x] Define typographic scale for landing page headings — existing `--text-*` scale is sufficient; `--text-hero-headline` is a future candidate if a heading larger than `--text-xl` is needed in Phase 4
- [x] Define section layout primitives — 15 structural classes implemented in `app/static/css/landing.css`
- [x] Define spacing scale for between-section rhythm — uses existing `--space-*` tokens throughout
- [x] Define the base HTML structure — `base_public.html` + `landing.html` with 9 labelled empty sections; correct landmark hierarchy (`<nav>`, `<main>`, `<footer>`, `<h1>` + `<h2>` per section)

### Phase 2 — Visual Scaffolding ✅ Complete

- [x] Apply full-width public shell backgrounds and borders to `body > header` and `body > footer`
- [x] Reset `section { margin-bottom }` override for landing sections — rhythm controlled via `padding-block` and `border-top`
- [x] Style `.landing-nav` links and brand for correct colour and weight
- [x] Apply `border-top` separator rhythm to `.landing-section`
- [x] Style `.landing-hero h1` with `--text-2xl` and max-width constraint
- [x] Style `.landing-hero > p` with `--text-muted` and `--text-lg`
- [x] Style `.landing-cta` alignment
- [x] Apply placeholder frame (`min-height`, `background`, `border`, `border-radius`) to `.landing-showcase__visual`
- [x] Style `.landing-feature__text` flex layout
- [x] Apply placeholder frames to `.landing-flow__step` and `.landing-faq__item`
- [x] Style `.landing-footer` and `.landing-footer .brand`
- [x] Add responsive overrides for 1024px, 768px, and 480px
- [x] Phase 2 visual structure applied to `landing.html` showcase sections (3 and 5)

### Phase 3 — Tactical Showcase Composition ✅ Complete

- [x] Hero: 2-column grid layout (`.ls-hero-layout`) — text left, mini status card right
- [x] Hero: tactical headline ("Know who's ready before the operation starts.")
- [x] Hero: restrained subheadline — audience-first framing, specific operational scope
- [x] Hero: primary CTA ("Login") and secondary CTA ("See the planner ↓") anchoring to `#section-showcase`
- [x] Hero: mini operation status card with composition name, slot fill progress bar, role tally, gap badge
- [x] Section 2: full 3-party planner showcase — 13/20 slots assigned (~65% fill)
  - Party 1: 4/5 assigned, 1 open DPS
  - Party 2: tank slot `--open-core` (warning badge visible)
  - Party 3: no tank build (`--critical`), no support build (`--critical`)
  - All four required states present: `--assigned`, `--open`, `--open-core`, `--critical`
- [x] Section 2: composition overview bar — role tally, slot open count, gap summary
- [x] Section 3: composition library mini list — 3 comps with active/archived badges and op counts
- [x] Section 3: supporting copy (1 paragraph)
- [x] Section 4: 4 workflow flow steps — Draft / Plan / Execute / Record — with numbered headings and descriptions
- [x] Section 5: static Discord embed mock using `--discord-embed-*` tokens; 3 fields + footer
- [x] Section 5: supporting copy (2 paragraphs)
- [x] Section 6: 4 readiness state rows — ok / warn / crit / empty — with coloured dot indicators and left-border accents
- [x] Section 6: supporting copy (1 paragraph)
- [x] Section 7: 4 tactical differentiation cards — composition-first, role-aware gap detection, single operational state, Albion-specific domain
- [x] Section 8: 8 FAQ items with real, honest answers covering self-hosting, Discord integration, Albion specificity, active development, multi-officer access, mobile, check-in flow
- [x] All slot content uses operationally plausible Albion Online builds (1H Mace, Hallowfall, Warbow, Locus, Battleaxe, Siege Shield, Nature Staff, Daggers, Curse Staff, Bow, Spear) and MMO-style player names
- [x] Responsive overrides for planner slot grid (5-col → 3-col → 2-col), diff grid, Discord embed fields, hero layout
- [x] Phase 3 regression assertions added to `test_ui_regression.py` — 6 new tests (73 total)
- [x] `test_landing_no_stray_empty_interactive_elements` updated — `<details>`/`<summary>` now permitted with real content; `<li>` check retained

### Phase 4 — Content Refinement & Information Hierarchy ✅ Complete

- [x] Section eyebrow labels added to all 7 content sections (`ls-section-eyebrow`) — improves scanability; full page structure readable in ~2 seconds without reading body copy
- [x] Hero subheadline tightened — from product-first to audience-first framing ("For Albion Online guild officers running structured operations...")
- [x] Hero CTA: "Login →" label simplified to "Login"; secondary CTA given `aria-label`
- [x] Trust strip added below hero CTA (`ls-trust-strip`): "Self-hosted · Albion Online-specific · Actively developed"
- [x] Section 2 heading refined: "Tactical planner — party by party" → "Party by party — role by role" (eyebrow now carries the category label)
- [x] Section 3 heading refined: "Compositions are reusable tactical templates" → "Build once — reuse across every operation"
- [x] Section 3 copy: 2 paragraphs merged → 1 (removed generic "refine what works" filler)
- [x] Section 5 copy: "remains the communication channel" → "is the communication layer" (sharper; shorter)
- [x] Section 6 heading: replaced abstract heading with concrete signal description
- [x] Section 6 copy: removed "Readiness is not a single boolean" abstract opener — leads with concrete operational fact
- [x] Section 7 heading: "Built for structured Albion Online operations" → "Albion-specific, from the ground up"
- [x] Section 7 diff items: text tightened — removed redundant clauses, sharpened each to one precise statement
- [x] FAQ answers: 3 items trimmed for brevity
- [x] `.landing-section h2` visual hierarchy rule — scoped to public shell only
- [x] Hover states added: `.ls-diff-item` and `.ls-faq__summary` (background-color transitions, 0.10–0.12s)
- [x] All 73 UI regression tests passing

### Phase 5 — Polish, Accessibility & Production Readiness ✅ Complete

- [x] **Skip link styled** — `.skip-link` had no CSS; added off-screen `transform` with `:focus-visible` reveal; keyboard users can now bypass navigation (was a silent accessibility failure)
- [x] **`prefers-reduced-motion` implemented** — all transitions (skip link, diff item hover, FAQ summary hover) disabled inside `@media (prefers-reduced-motion: reduce)` block; smooth scroll conditionally enabled inside `no-preference` block. WCAG 2.3.3.
- [x] **Trust strip specificity fixed** — `.ls-hero-text p` (0,1,1) was overriding `.ls-trust-strip` (0,1,0), giving the trust strip large/muted text. Fixed with more-specific `.ls-hero-text > .ls-trust-strip` (0,2,0).
- [x] **Hero visual order fixed** — Phase 3 set `order: -1` on `.ls-hero-visual` at ≤1024px, placing the status card above the headline on mobile/tablet. Phase 5 resets to `order: 0` — text-first as correct for mobile.
- [x] **FAQ touch target** — `<summary>` measured ~38px (insufficient). Added `display: flex; align-items: center; min-height: 44px`. WCAG 2.5.5.
- [x] **FAQ `overflow: hidden`** — `.landing-faq__item` now clips expanded answer content to its border-radius correctly.
- [x] **Inline styles removed** — Sections 3 and 5 had `style="padding: ..."` and `style="display: flex; ..."` attributes. Extracted to `.ls-showcase-padded` and `.ls-showcase-centered` utility classes.
- [x] **`<meta name="description">` added** — via `{% block head_extra %}` in `landing.html`, scoped to the page (not polluting `base_public.html`).
- [x] **CTA "See the planner ↓" aria-label** — Unicode `↓` in link text reads ambiguously; `aria-label="See the tactical planner"` provides clean screen-reader announcement.
- [x] **Footer brand link** — `<span class="brand">IronkeepV2</span>` → `<a class="brand" href="/">IronkeepV2</a>`. Standard UX expectation.
- [x] **Footer sub-label** — "Tactical coordination for Albion Online" — factual, restrained.
- [x] **Smooth scroll** — `scroll-behavior: smooth` added conditionally inside `prefers-reduced-motion: no-preference`.
- [x] **390px breakpoint** — added `@media (max-width: 390px)` tightening section padding (16px → 12px), hero block padding, subheadline font scale.
- [x] All 73 UI regression tests passing after Phase 5 changes

### Phase 6 — Community and Trust Evolution (Conditional)

> This phase should only begin when real, verifiable trust signals exist.

- [ ] Identify real guilds willing to be named as users (with permission)
- [ ] Write honest attribution: guild name, server type, how they use IronkeepV2
- [ ] Define the visual pattern for a real testimonial (not a marketing quote box)
- [ ] Define a real usage metric if one exists and is meaningful (e.g., operations run through the system)
- [ ] Revisit FAQ to incorporate real questions from real users

---

## 12. Explicit Non-Goals

The following are explicit anti-patterns for the landing page. Implementing any of these would undermine the operational and honest positioning of IronkeepV2.

### Fake Social Proof

- [ ] No "trusted by X guilds" unless the number is real and verified
- [ ] No invented testimonials with fake guild officer names
- [ ] No fake "as featured in" press logos
- [ ] No fabricated activity statistics ("1,400 operations planned this month")
- [ ] No placeholder social proof that was supposed to be replaced before launch and wasn't

### Inflated Positioning

- [ ] No competitive framing that names and dismisses other tools
- [ ] No "the only platform that..." claims
- [ ] No enterprise tier language (SLA, 99.9% uptime, enterprise support) unless those exist
- [ ] No "used by top guilds" without verification

### Aesthetic Drift

- [ ] No crypto/Web3 aesthetics — glow effects, gradient text, generative backgrounds
- [ ] No generic esports branding — team jersey imagery, arena photography, bracket overlays unrelated to the tool
- [ ] No TikTok-style animation design — rapid cuts, scroll-triggered chaos, fullscreen takeovers
- [ ] No giant hero illustration with fictional game characters
- [ ] No stock photography of gamers

### Generic SaaS Cloning

- [ ] No feature grid with check marks comparing "Basic / Pro / Enterprise" tiers
- [ ] No "How it works in 3 easy steps" if the real workflow has more than three steps
- [ ] No countdown timers or urgency mechanics
- [ ] No hero with a giant generic dashboard screenshot that could belong to any SaaS tool
- [ ] No "Join the waitlist" if there is no waitlist

### Technical Anti-Goals

- [ ] No frontend framework dependency introduced solely for the landing page
- [ ] No external animation library imported for decorative effects
- [ ] No fake interactive elements (clickable planner that is actually an image map)
- [ ] No third-party analytics that slow the page or compromise privacy before a policy exists

---

## 13. Open Design Questions

All questions resolved before Phase 1 implementation began. Decisions are binding for Phase 2 and forward.

### Audience and Targeting

- [x] **Primary landing page visitor:** The guild officer evaluating the tool. Regular members have no autonomy to set up IronkeepV2 — they do not evaluate it. All information density, vocabulary, and CTA framing targets the officer role.
- [x] **CTA framing:** Individual officer setup. IronkeepV2 is not a guild-collective purchase — an officer installs and configures it. The CTA is "set this up for your operations," not "get your whole guild onboard."

### Showcase Authenticity

- [x] **Tactical density before login:** Show one annotated party panel from a real composition — not a full 4-party grid. Enough to demonstrate slot-level orchestration, role colour system, and readiness state without overwhelming non-officers before they understand the coordinate system.
- [x] **Real vs. curated data:** Curated real data — a real composition created specifically for the showcase using the actual system, seeded with plausible Albion Online builds. Not invented. Not from a live guild's private state.
- [x] **Mid-state for the planner showcase:** ~65% fill. At least one gap badge visible (`--critical` or `--warn`), one `--assigned` slot, one `--open-core` slot. Enough assigned slots to read as operational; enough open slots to show gap detection and readiness signals.

### Differentiation

- [x] **Albion Online naming:** Yes — name the game explicitly. Domain specificity is a feature, not a liability. Guild officers searching for Albion CTA tools should find this page.
- [x] **Discord integration prominence:** Secondary, not primary. Discord belongs in Section 5 of 9. Framing: "Discord handles communication. IronkeepV2 handles coordination." Do not lead with the bot.
- [x] **V1 vs V2 differentiation:** The contrast table in Section 1 (admin tool aesthetic → operational platform aesthetic) is the guiding reference. V1 had no landing page, so V2 has no specific divergence target — avoid the generic form-and-tables aesthetic by default.

### Trust and Honesty Timeline

- [x] **Community/Trust section timing:** Not yet. Phase 6 is conditional on real, verifiable trust signals existing. No trust section until real guild attribution is available with permission.
- [x] **Communicating active development:** Embed in the FAQ as a plain honest answer. If a public changelog exists, link it. Do not use "built in public" framing — it signals startup mode, not operational tool.
- [x] **Self-hosted nature:** Acknowledge in the FAQ as a plain fact framed as a data ownership advantage, not a setup burden.

### Operational Content

- [x] **FAQ length:** Cap at 8 questions. The candidate list in Section 4 has exactly 8 — that is the limit. More than 8 signals a complex product requiring excessive explanation before trust.
- [x] **Planned but not built features:** Do not feature them in showcases or main sections. If raised in the FAQ, use "this is on the roadmap" without a timeline.
- [x] **"What IronkeepV2 is not" section:** No standalone section. Embed differentiation inside Section 7 (Tactical Orchestration Explanation) through positive descriptive framing. A standalone "what we are not" section is defensive.

---

## 14. Implementation Log

### Phase 1 — Visual Foundation (Shipped 2026-05-18)

**What was added:**

| Item | Detail |
|---|---|
| `app/static/css/landing.css` | 15 structural layout primitive classes — no decorative styling |
| `app/templates/base_public.html` | Public rendering shell; loads `landing.css` pipeline; no authenticated elements |
| `app/templates/landing.html` | Extends `base_public.html`; 9 empty labelled sections; correct landmark hierarchy |
| `GET /` route | Public landing route; no authentication required; no dynamic context |
| `GET /workspaces` route | Existing authenticated workspace list moved from `/` to `/workspaces` |
| `tests/test_ui_regression.py` | 9 new `TestLandingPageSmoke` assertions: 200 response, landmark presence, CSS pipeline, absence of authenticated elements |
| `tests/test_auth_dev_login.py` | Two assertions updated from `/` → `/workspaces` to reflect route relocation |

**Architectural decisions:**

| Decision | Rationale |
|---|---|
| `base_public.html` separate from `base.html` | `base.html` carries authenticated context (`workspace_nav`, `global-nav__account`, workspace switcher) that cannot be cleanly stripped via block overrides. A dedicated public shell is the correct separation. |
| `landing.css` as a dedicated file | Landing layout primitives (hero shell, showcase containers, flow diagram, FAQ accordion) have no equivalent in the app surface. Mixing them into `components.css` would pollute the app component namespace. |
| `dashboard.css` and `tactical.css` excluded from public shell | These files carry zero landing page primitives. Omitting them reduces payload and prevents class namespace leakage on the public surface. |
| `GET /` → landing; workspace list → `GET /workspaces` | The landing page is the correct public entry point. The workspace list is an authenticated resource and belongs at a path that implies authentication scope. |

**Token audit result:** No additions to `tokens.css` required. The existing token set — backgrounds, semantic colours, role colours, spacing scale, typography scale — covers all Phase 1 and anticipated Phase 2 needs. `--text-hero-headline` is a candidate addition in Phase 4 if the hero H1 requires a size above `--text-xl`.

**What was NOT changed:**
- No copy or headlines written
- No planner showcase data or visual
- No composition list showcase
- No workflow diagram
- No FAQ content
- No annotation callout styling
- No decorative CSS of any kind

**Validation:**

| Tier | Command | Result |
|---|---|---|
| Tier 1 | `python -m pytest --collect-only -q` | ✅ 1655 tests collected |
| Tier 4 | `python -m pytest tests/test_ui_regression.py -q` | ✅ 9/9 new landing tests passed; 1 pre-existing failure unrelated to Phase 1 |
| Tier 5 | `python -m pytest -q` | ✅ 1654 passed; 1 pre-existing failure (`TestPhase4IntegrityRefinements::test_continuation_link_renders_for_editable_comp_with_warnings` — string not present in any template; pre-dates Phase 1) |

---

### Auth Redirect Fix — Post-Login Destination (Shipped 2026-05-18)

**Problem:** After Phase 1 moved `/` to the public landing page and `/workspaces` to the authenticated surface, the `_safe_next()` fallback in `app/routes.py` still returned `"/"`. Successful logins with no explicit `next` parameter redirected users to the public landing page instead of the authenticated surface.

**Changes:**

| File | Change |
|---|---|
| `app/routes.py` — `_safe_next()` | Fallback return changed from `"/"` to `"/workspaces"` in both fallback positions (missing/empty `path` and unsafe path) |
| `app/routes.py` — `get_auth_discord` error template | `"next_path": "/"` → `"next_path": "/workspaces"` |
| `tests/test_auth_dev_login.py` | Three new regression tests added: successful login redirects to `/workspaces`, authenticated user can still access `/`, logout still lands at `/` |

**Constraint preserved:** Explicit `?next=...` paths continue to work unmodified — only the default fallback was changed. Public landing at `/` is not gated and remains accessible to authenticated users.

**Validation:**

| Tier | Command | Result |
|---|---|---|
| Tier 1 | `python -m pytest --collect-only -q` | ✅ Collected correctly |
| Targeted | `python -m pytest tests/test_auth_dev_login.py -q` | ✅ All auth tests pass |

---

### Phase 2 — Visual Scaffolding (Shipped 2026-05-18)

**What was added:**

| Item | Detail |
|---|---|
| `app/static/css/landing.css` | Visual scaffolding CSS added to existing Phase 1 primitives: public shell backgrounds, section border-top rhythm, hero typography, showcase placeholder frames, CTA alignment, footer styling |
| `app/templates/landing.html` | Showcase sections (3 and 5) given placeholder frame containers; hero text and CTA placeholders in place |
| Responsive overrides | Three breakpoints (1024px, 768px, 480px) added; showcase frames collapse; hero becomes single-column |

**What was NOT changed:**
- No real copy or showcase data
- No planner slot content
- No FAQ content

**Validation:**

| Tier | Command | Result |
|---|---|---|
| Tier 4 | `python -m pytest tests/test_ui_regression.py -q` | ✅ All passing |

---

### Phase 3 — Tactical Showcase Composition (Shipped 2026-05-18)

**What was added:**

| Item | Detail |
|---|---|
| `app/templates/landing.html` | All 9 sections fully populated with operational showcase content (see Phase 3 checklist above) |
| `app/static/css/landing.css` | ~200 lines added: `.ls-hero-layout`, `.ls-hero-text`, `.ls-hero-visual`, `.ls-status-card`, `.ls-planner`, `.ls-party`, `.ls-slot` (4 states), `.ls-gap-badge`, `.ls-role-tally`, `.ls-comp-row`, `.ls-comp-meta`, `.ls-workflow-steps`, `.ls-workflow-step`, `.ls-discord-embed-mock`, `.ls-readiness-panel`, `.ls-readiness-row`, `.ls-diff-grid`, `.ls-diff-item`, `.ls-faq__item`, `.ls-faq__summary`, `.ls-faq__answer` |
| `tests/test_ui_regression.py` | 6 new Phase 3 assertions: FAQ content, planner states (all 4), tactical headline, workflow steps, Discord embed, login CTA. `test_landing_no_stray_empty_interactive_elements` updated to permit real `<details>`/`<summary>` |

**Authenticity decisions:**

| Decision | Rationale |
|---|---|
| ~65% fill (13/20 slots) | Mid-state is the most operationally honest and visually convincing state — empty proves nothing, full is implausibly clean |
| Real Albion Online weapon/build names | Domain specificity is a trust signal; generic "Role A / Build B" labels would undermine credibility immediately |
| No invented guild names | Authenticity rules prohibit placeholder social proof; player names are generic operational handles |
| Discord embed styled with `--discord-embed-*` tokens | Visual continuity between landing page and what the app actually produces; avoids divergence |
| 4 workflow steps (Draft / Plan / Execute / Record) not 6 | Matches real implemented capability; omits phases not yet built |

**Validation:**

| Tier | Command | Result |
|---|---|---|
| Tier 4 | `python -m pytest tests/test_ui_regression.py -q` | ✅ 73 tests passing |

---

### Phase 4 — Content Refinement & Information Hierarchy (Shipped 2026-05-18)

**What was added:**

| Item | Detail |
|---|---|
| `app/templates/landing.html` | Eyebrow labels (`.ls-section-eyebrow`) added to all 7 content sections; hero subheadline tightened; trust strip added; per-section headings and copy refined across all sections; FAQ answers trimmed |
| `app/static/css/landing.css` | `.landing-section h2` heading visual rule; `.ls-section-eyebrow` styling; `.ls-trust-strip` rule; hover transitions on `.ls-diff-item` and `.ls-faq__summary` |

**Copy refinement rationale:**

| Change | Why |
|---|---|
| Hero subheadline from product-first to audience-first | Officers need to see themselves in the first sentence, not the feature list |
| Trust strip below CTA | Restrained, factual — signals active development and self-hosted nature without fabricated social proof |
| Section eyebrow labels | Officers scan headings; eyebrows reduce cognitive load by pre-labelling the category before reading the heading |
| Per-section copy trimmed | Every removed sentence reduces scroll friction; no section lost informational meaning |

**Validation:**

| Tier | Command | Result |
|---|---|---|
| Tier 4 | `python -m pytest tests/test_ui_regression.py -q` | ✅ 73 tests passing |

**Responsive validation (manual):**

| Breakpoint | Notes |
|---|---|
| 1440px | Full two-column hero; planner 5-col; diff grid 2×2; FAQ comfortable |
| 1024px | Hero stacks; planner narrows but remains readable; section padding tighter |
| 768px | Single-column throughout; eyebrow labels legible; trust strip wraps onto 2 lines (acceptable) |
| 480px | Planner slots 3-col; diff grid 2-col; CTA full-width; FAQ answers comfortable |
| 390px | No crushed content; hero subheadline slightly smaller; all section padding tight but sufficient |

---

### Phase 5 — Polish, Accessibility & Production Readiness (Shipped 2026-05-18)

**What was added:**

| Item | Detail |
|---|---|
| `app/static/css/landing.css` | ~120 lines: skip-link off-screen/focus-visible reveal; trust-strip specificity fix; FAQ summary `min-height: 44px` touch target; `overflow: hidden` on FAQ items; `.ls-showcase-padded` and `.ls-showcase-centered` utility classes; `.ls-footer-sub` style; `scroll-behavior: smooth` inside `prefers-reduced-motion: no-preference`; full `prefers-reduced-motion: reduce` block disabling all transitions; hero visual `order: 0` reset at ≤1024px; `max-width: 390px` breakpoint |
| `app/templates/landing.html` | `<meta name="description">` in `{% block head_extra %}`; `aria-label="See the tactical planner"` on secondary CTA; inline `style=` attributes replaced with `.ls-showcase-padded` and `.ls-showcase-centered` |
| `app/templates/base_public.html` | Footer brand `<span>` → `<a href="/">` (standard UX); `<span class="ls-footer-sub">Tactical coordination for Albion Online</span>` added |

**Accessibility improvements:**

| Issue | Fix | Standard |
|---|---|---|
| Skip link was unstyled and invisible to keyboard users | Off-screen CSS + `:focus-visible` reveal | WCAG 2.4.1 |
| `<summary>` touch target ~38px | `min-height: 44px` + flex vertical centering | WCAG 2.5.5 |
| `↓` arrow in CTA link text read ambiguously by screen readers | `aria-label="See the tactical planner"` | WCAG 2.4.6 |
| Transitions not suppressed for motion-sensitive users | `prefers-reduced-motion: reduce` block | WCAG 2.3.3 |
| Hero visual appeared above headline on mobile | `order: 0` reset at ≤1024px | Content-first mobile UX |

**Production readiness fixes:**

| Issue | Fix |
|---|---|
| No `<meta name="description">` | Added via `head_extra` block |
| Footer brand not a link | Changed to `<a href="/">` |
| Inline styles in showcase sections | Extracted to CSS utility classes |

**Validation:**

| Tier | Command | Result |
|---|---|---|
| Tier 4 | `python -m pytest tests/test_ui_regression.py -q` | ✅ 73 tests passing |

**Responsive validation (manual):**

| Breakpoint | Notes |
|---|---|
| 1440px | No regressions; hero text-first, visual right; trust strip single line |
| 1280px | Consistent with 1440px; no layout shifts |
| 1024px | Hero stacks correctly; visual below text (not above after order fix) |
| 768px | Trust strip wraps cleanly; FAQ touch targets comfortable |
| 480px | CTA buttons full-width; footer sub-label readable |
| 390px | Tightest breakpoint; section padding 12px; no clipped content |

---

*Document version: Phase 5 complete — May 2026*
*Phase 6 (Community and Trust Evolution) is conditional — do not begin until real, verifiable guild attribution is available with permission. See Section 11 for Phase 6 checklist.*
