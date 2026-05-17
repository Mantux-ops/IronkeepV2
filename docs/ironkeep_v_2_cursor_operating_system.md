# IronkeepV2 — Cursor Operating System

## Purpose

This document defines how Cursor should be used while building IronkeepV2.

Goal:
- Preserve operational depth
- Prevent AI-driven architecture drift
- Keep Ironkeep Albion-first
- Avoid generic SaaS abstractions
- Maintain product focus around CTA operations
- Refactor/build intentionally instead of randomly generating code

---

# Core Product Doctrine

Ironkeep is NOT:
- a generic guild management tool
- a community platform
- a Discord replacement
- a generic event system
- an analytics dashboard

Ironkeep IS:
- an operational coordination system for organized multiplayer groups
- focused primarily on Albion Online guilds and ZvZ teams
- centered around CTA readiness and operational awareness

The mass planner is the operational heart of the system.

Discord is communication.
Ironkeep is the source of truth.

---

# Non-Negotiable Product Rules

## 1. Albion-first

Albion UX should remain rich and specialized.

Do NOT:
- flatten builds into generic MMO gear systems
- genericize CTA workflows
- remove Albion-specific terminology
- simplify operational complexity for abstraction purity

Future games should be supported via adapters/capabilities.

NOT through a generic UI rewrite.

---

## 2. Operational focus

Every major feature must improve one of:
- CTA readiness
- coordination
- assignment quality
- attendance reliability
- role visibility
- officer decision-making
- operational awareness

If a feature does not improve operational effectiveness:
- question it
- deprioritize it
- or hide it

---

## 3. Analytics philosophy

Analytics are NOT vanity dashboards.

Every metric must answer:
- What action should an officer take?
- What operational problem exists?
- What readiness issue exists?

Good analytics:
- missing roles
- unreliable attendance
- no-show patterns
- comp instability
- readiness gaps
- scout/support contribution
- CTA health

Bad analytics:
- total users
- random activity charts
- meaningless trends
- decorative graphs

---

## 4. Discord philosophy

Discord is:
- communication
- reminders
- notifications
- lightweight interaction

Discord is NOT:
- the operational source of truth
- the state owner
- the assignment system

The bot should be a thin operational interface over shared services.

---

## 5. Refactor philosophy

Never rewrite large systems blindly.

Prefer:
- extracting services
- isolating domains
- preserving workflows
- phased replacement

Current Ironkeep is:
- operational reference implementation
- edge-case reference
- workflow reference

NOT the final architecture.

---

# Cursor Usage Rules

## Use Claude Sonnet for:
- architecture
- domain modeling
- service extraction
- operational workflows
- refactor planning
- large-file understanding

Avoid Auto mode for architecture.

---

## Preferred workflow

1. Analyze
2. Plan
3. Propose file-by-file changes
4. Ask for approval
5. Implement one slice
6. Run tests
7. Manual smoke test
8. Commit

Never allow:
- massive autonomous rewrites
- uncontrolled multi-file cleanup
- architecture generation without review

---

# Required Cursor Behavior

Before modifying code:
- explain what is changing
- explain why
- explain risks
- list affected modules
- list tests to run

After modifying code:
- summarize changes
- list behavioral risks
- provide manual smoke checklist

---

# Operational Core Domains

These systems are FIRST-CLASS systems.

## Core domains

### CTA lifecycle
- CTA creation
- signup lifecycle
- readiness
- assignments
- operational state

### Mass planner
- P1/P2/P3 priorities
- fill logic
- comp resolution
- party structure
- readiness gaps
- assignment validation

### Caller board
- live assignments
- role visibility
- quick assignment
- operational awareness

### Attendance
- attendance truth
- scout attendance
- support participation
- reliability history

### Discord integration
- operational notifications
- signup intake
- reminders
- embeds

### Operational analytics
- readiness scoring
- role gaps
- CTA health
- reliability
- no-shows
- comp stability
- officer insights

### Financial systems
- payouts
- regear
- settlement tracking
- ledger integrity

---

# Preferred Architecture Shape

## HTTP Layer
Thin routers only.

Responsibilities:
- auth
- request parsing
- response rendering
- permission checks

No major business logic.

---

## Services Layer

Contains:
- CTA rules
- signup rules
- assignment rules
- attendance rules
- readiness logic
- payout logic
- analytics logic

Pure operational logic.

Reusable by:
- web
- Discord bot
- schedulers
- future APIs

---

## Persistence Layer

Repository-style modules.

Avoid:
- giant db.py dumping ground
- inline SQL duplication
- route-specific query logic

---

## Discord Layer

Thin wrappers over services.

Commands should:
- validate
- call services
- render embeds

No duplicated operational logic.

---

# Anti-Patterns To Avoid

## DO NOT:
- create generic SaaS dashboards
- add social/community feeds
- build unnecessary AI assistants
- overabstract for future games
- rebuild working systems for purity
- merge unrelated domains
- flatten operational workflows
- turn Ironkeep into an Albion toolbox

---

# Product Navigation Philosophy

Primary navigation should focus on:
- current operations
- CTAs
- mass planner
- caller board
- builds/comps
- attendance
- payouts/regear

Utilities should be secondary/collapsed.

Ironkeep should feel like:
"This is where we run operations."

NOT:
"This is a collection of tools."

---

# Testing Philosophy

Every operational change must include:

## Automated tests
- permissions
- tenant isolation
- signup rules
- assignment rules
- attendance rules
- payout correctness
- analytics calculations

## Manual smoke tests
At minimum:
- create CTA
- signup
- fill signup
- assign role
- attendance mark
- Discord reminder
- payout/regear flow

---

# Long-Term Strategic Direction

IronkeepV2 should evolve toward:

"Operational infrastructure for organized multiplayer groups"

NOT:
"A feature-heavy guild utility app"

The long-term moat is:
- operational readiness
- shared operational state
- officer decision support
- workflow reliability

NOT:
- utility count
- random integrations
- visual complexity

---

# Final Engineering Rule

When making decisions:

Always ask:

1. Does this improve operational readiness?
2. Does this reduce CTA chaos?
3. Does this help officers make decisions faster?
4. Does this preserve Albion operational depth?
5. Does this keep the mass planner central?

If not:
reconsider the implementation.

