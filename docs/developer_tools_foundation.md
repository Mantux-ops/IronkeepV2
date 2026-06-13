# IronkeepV2 — Developer Tools Foundation

## Status

**In Planning**

This document is the long-term design reference for the IronkeepV2 developer tooling direction. It covers the developer page, runtime introspection, architecture visibility, operational debugging, diagnostics export, and security hardening for development and maintenance workflows.

Read this before adding any new debug endpoints, admin pages, or introspection tooling.

---

## Goal

Provide IronkeepV2 maintainers with a trusted, scoped, and safe set of tools for understanding the system at runtime — without exposing secrets, turning the UI into a junk drawer, or introducing unsafe admin primitives.

The developer page is **owner-only by design**. It is never a feature surface for guild officers. It is never exposed to unauthenticated users. It is a maintainability aid, not an escape hatch.

---

## Core Principles

- **Owner-only by default.** No developer tool is visible to officers or members. Every route and page in this area is gated on workspace owner or superuser role.
- **Read-only by default.** Introspection surfaces must not mutate state. Write operations require explicit, separate, clearly-scoped forms with CSRF and confirmation.
- **No secrets exposed.** Tokens, Discord credentials, OAuth secrets, and environment values are never rendered — not even partially or truncated. Log them never.
- **No junk drawer.** Every tool added to the developer page must answer a concrete debugging or operational question. Ad-hoc "dump everything" panels are not accepted.
- **Operational clarity first.** The developer page must remain scannable. Walls of raw JSON or unstructured output are not acceptable.
- **Additive and isolated.** Developer tooling is never tangled into the main application flow. Route prefixes, permissions, and templates stay cleanly separated.
- **Maintainable over clever.** Plain server-rendered HTML. No live polling. No WebSockets. No client-side framework complexity.

---

## Phase 1 — Developer Page Foundation

### Routing and Access

- [ ] Add `/workspaces/{slug}/dev` as the developer tools landing page
- [ ] Gate the entire `/dev` prefix on workspace `owner` role (not officer)
- [ ] Return 403 to non-owners with a clear message — no information leakage
- [ ] Add a link to the developer page in the workspace nav (visible to owners only)
- [ ] Ensure the route prefix is cleanly separated from settings/scheduler/diagnostics routes

### Landing Page Structure

- [ ] Define the section layout for the developer landing page
- [ ] Include a clear scope notice: "Owner-only. Development and maintenance tools."
- [ ] Add a last-visited / last-generated timestamp to each section where relevant
- [ ] Ensure the page degrades gracefully when individual sections fail to load

### Navigation

- [ ] Add a workspace nav entry for "Developer" (owner-only visibility)
- [ ] Define breadcrumb structure for nested developer sub-pages
- [ ] Ensure the developer nav entry does not appear in any non-owner session

---

## Phase 2 — Build / Runtime / Environment Introspection

### Application Version

- [ ] Surface application version (from `__version__`, git tag, or `VERSION` file)
- [ ] Surface the Python version
- [ ] Surface the Starlette/FastAPI version
- [ ] Surface the SQLite library version (`sqlite3.sqlite_version`)
- [ ] Surface the SQLite driver version (`sqlite3.version`)
- [ ] Document how `VERSION` file or `app/__version__.py` is maintained

### Environment Context

- [ ] Surface the active environment name (`IRONKEEP_ENV`)
- [ ] Surface the database path basename (filename only — no absolute paths)
- [ ] Surface whether WAL mode is active
- [ ] Surface whether Discord integration is configured (boolean — no token values)
- [ ] Surface whether OAuth is configured (boolean — no secret values)
- [ ] Explicitly mask all credential/token environment variables — never render values

### Process Visibility

- [ ] Surface the current process uptime (time since app start)
- [ ] Surface the current UTC time (for clock-skew debugging)
- [ ] Surface whether the scheduler process is detected as alive (last heartbeat check)

---

## Phase 3 — Route / Architecture Visibility

### Route Registry

- [ ] Add a developer sub-page: `GET /workspaces/{slug}/dev/routes`
- [ ] List all registered FastAPI/Starlette routes with: method, path pattern, function name
- [ ] Group routes by prefix (auth, workspace, operation, scheduler, dev, health)
- [ ] Mark owner-only and officer-only routes visually
- [ ] Exclude routes that expose secrets or raw internals from the listing
- [ ] Add a search/filter input (client-side, no backend query needed)

### Dependency Map

- [ ] Document the module dependency graph in this file (static reference, not generated)
- [ ] Identify which modules are allowed to import which others (boundary rules)
- [ ] Flag any detected cross-boundary imports in the developer page if feasible

### Template Registry

- [ ] Add a developer sub-page: `GET /workspaces/{slug}/dev/templates`
- [ ] List all Jinja2 templates in `app/templates/` with filename and last-modified
- [ ] Identify templates that are currently unreachable from any route
- [ ] Do not render template content inline — filenames only

---

## Phase 4 — Operational Debugging Visibility

### Recent Operational Events

- [ ] Add a developer sub-page: `GET /workspaces/{slug}/dev/events`
- [ ] Show the 100 most recent `guild_operation_events` across all operations in the workspace
- [ ] Columns: timestamp, operation ref, event type, actor, payload (collapsed by default)
- [ ] Allow filtering by event type (client-side or simple query parameter)
- [ ] Payload disclosure uses `<details>/<summary>` — never expanded by default
- [ ] Truncate payloads at a safe limit (2 000 chars); show a "truncated" notice if cut

### Scheduler Debug View

- [ ] Add a developer sub-page: `GET /workspaces/{slug}/dev/scheduler`
- [ ] Show the last 50 scheduler runs across all job types (global, not workspace-scoped)
- [ ] Show stuck/stale detection with the same logic used by the diagnostics page
- [ ] Show all pending dispatch failures (not limited to workspace scope)
- [ ] Show reminder delivery state for the last 20 eligible operations
- [ ] No retry buttons — read-only view

### Database Inspection (Safe Subset)

- [ ] Add a developer sub-page: `GET /workspaces/{slug}/dev/db`
- [ ] Show: table names, row counts for each table, last `PRAGMA integrity_check` result
- [ ] Show: WAL file presence, WAL file size, DB file size, last modified
- [ ] Show: schema version or migration state indicator
- [ ] Do NOT show: raw SQL, table column definitions with sensitive data, arbitrary query execution

### Error Log Snapshot

- [ ] Define a standard for structured error logging in `app/` modules
- [ ] Surface the last N logged errors in the developer error panel (in-memory ring buffer or DB table)
- [ ] Each entry: timestamp, module, error type, message (no stack trace in UI — too noisy)
- [ ] Clear/reset mechanism for the in-memory buffer (POST with confirmation)

---

## Phase 5 — Diagnostics / Support Export Tooling

### Diagnostic Report Export

- [ ] Add `GET /workspaces/{slug}/dev/export/diagnostics.json`
- [ ] Include: app version, environment name, DB health, scheduler state, WAL state, row counts
- [ ] Explicitly exclude: credential values, absolute file paths, user PII
- [ ] Add a download button to the developer landing page
- [ ] The export must be deterministic and stable across reruns given the same state

### Support Bundle Concept

- [ ] Define what a "support bundle" contains for this project (document in this file)
- [ ] Support bundle = diagnostics export + recent scheduler run summary + error snapshot
- [ ] Do NOT include: database file, any credential, any user display name
- [ ] Consider adding `GET /workspaces/{slug}/dev/export/support-bundle.json` as a future route
- [ ] Add a `support_bundle` section to the developer landing page once defined

### Schema Snapshot Export

- [ ] Add `GET /workspaces/{slug}/dev/export/schema.sql` (owner-only)
- [ ] Returns the result of `SELECT sql FROM sqlite_master WHERE sql IS NOT NULL`
- [ ] Useful for comparing deployed schema against expected schema
- [ ] Response is `text/plain` with `Content-Disposition: attachment; filename="schema.sql"`

---

## Phase 6 — UI / Frontend Development Helpers

### Design System Reference Page

- [ ] Add `GET /workspaces/{slug}/dev/design-system`
- [ ] Render all badge variants with their class names
- [ ] Render all button variants (primary, secondary, danger, lifecycle)
- [ ] Render all alert variants (error, success, info, warning)
- [ ] Render typography scale (h1–h4, body, muted, faint, code)
- [ ] Render spacing scale (visual swatches for `--space-1` through `--space-6`)
- [ ] Render surface/border hierarchy (card, card header, panel-muted, table row states)
- [ ] This page is a living reference — update it as the design system evolves

### Template Lint Helpers

- [ ] Document naming conventions for template files and CSS classes
- [ ] Add a developer check that verifies no inline `style=""` attributes exist in templates (except documented exceptions)
- [ ] Add a check that all `<form>` POST routes have a corresponding redirect response (no direct template renders on POST)
- [ ] Add a check that all `TemplateResponse` calls use the correct `(request, name, context)` signature

### Flash Message Preview

- [ ] Add a section to the design system page showing all flash message types
- [ ] Show: success, error, info, warning flash variants
- [ ] Document the flash message cookie key and expected format

---

## Phase 7 — Security Hardening

### Secret Safety Checks

- [ ] Add a startup check that warns if `SECRET_KEY` is set to a known-weak default value
- [ ] Add a startup check that `IRONKEEP_ENV=production` is paired with a strong secret
- [ ] Add a developer page section showing which security checks passed/failed at startup
- [ ] Document all environment variables that must never appear in logs or responses

### HTTP Security Headers

- [ ] Add `X-Content-Type-Options: nosniff` to all responses
- [ ] Add `X-Frame-Options: DENY` to all responses
- [ ] Add `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] Add `Content-Security-Policy` header (define allowed sources for scripts/styles)
- [ ] Surface current header state on the developer security panel
- [ ] Do not add headers that break the existing Jinja2/server-rendered architecture

### Session and Cookie Hardening

- [ ] Verify session cookie has `HttpOnly` flag
- [ ] Verify session cookie has `SameSite=Lax` or `Strict`
- [ ] Verify session cookie has `Secure` flag in production environments
- [ ] Add a developer panel entry for session cookie configuration state

### Rate Limiting Visibility

- [ ] Document which routes are candidates for rate limiting (login, OAuth callback, POST routes)
- [ ] Add a developer panel entry listing unprotected high-frequency POST endpoints
- [ ] Add rate limiting to the login/dev-login routes as a minimum baseline
- [ ] Do not add rate limiting middleware that silently swallows errors

---

## Explicit Non-Goals

- **No arbitrary SQL execution.** The developer page will never expose a query runner or REPL.
- **No credential display.** Tokens, secrets, and OAuth values are never shown, truncated, or hinted at.
- **No raw environment variable dump.** `os.environ` is never serialized into a response.
- **No live data mutation from dev tools.** State changes must go through use cases and proper routes.
- **No unauthenticated developer endpoints.** There is no `/debug` or `/admin` route that bypasses the auth layer.
- **No external monitoring stack.** This is not Prometheus, Grafana, Sentry, or Datadog. Keep it in-process and simple.
- **No Docker or Kubernetes tooling.** The project does not assume a container runtime.
- **No client-side framework.** All developer pages are server-rendered Jinja2 — no React, Vue, or Alpine.
- **No "dump everything" panels.** Every panel must answer a specific operational question.
- **No permanent debug modes.** Development helpers must be gated on environment and role, never silently active.

---

## Success Criteria

- A workspace owner can open the developer page and answer: "Is the scheduler running? Is the database healthy? What version is this?"
- A maintainer can export a diagnostics JSON without needing SSH access to the server.
- A new contributor can open the design system reference page and understand all available UI primitives.
- No guild officer or member can access any developer page, even by guessing the URL.
- No credentials, tokens, or secrets appear anywhere in developer page responses — including in HTML comments, JSON keys, or truncated strings.
- The developer page remains fast, readable, and non-intrusive — it does not slow down the rest of the application.
- Adding a new developer tool takes less than one focused slice: route → use case → template → tests.
- The test suite covers permission enforcement for all `/dev/*` routes.
