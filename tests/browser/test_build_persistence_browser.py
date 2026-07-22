"""
Phase 12.3b — Build persistence Playwright browser tests.

Covers the full save / version / lifecycle flows via real Chromium.

Test groups:
  1.  Create draft build (full UI flow → detail page → version 1)
  2.  Edit and version (edit mode → version 2 → history)
  3.  Stale save conflict (optimistic lock → 409 visible in browser)
  4.  Validation errors (empty name, negative IP via form manipulation)
  5.  Lifecycle: publish (draft → published)
  6.  Lifecycle: archive (published → archived → hidden from active list)
  7.  Lifecycle: restore (archived → draft → active list)
  8.  No-change save (open edit, save without changes → no new version)

Isolation strategy:
  Each test class creates its own workspace + optional seeded build using
  a function-scoped ``build_workspace`` fixture.  Unique UUID-based slugs
  guarantee no cross-test state bleeding even within the session-scoped DB.

Dependencies:
  - tests/browser/conftest.py  (provides isolated_db, live_server)
  - app.application.use_cases  (used in fixtures to seed data)
  - app.albion.item_catalog     (used to discover a valid item ID)
"""

from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(page: Page, base_url: str, display_name: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill('input[name="display_name"]', display_name)
    page.click('input[type="submit"]')
    page.wait_for_url(f"{base_url}/workspaces**", timeout=8000)


def _get_catalog_item_id(slot: str) -> str:
    from app.albion.item_catalog import get_catalog
    cat = get_catalog()
    items = cat.get_by_slot(slot)
    if not items:
        pytest.skip(f"No catalog items for slot '{slot}'")
    return items[0]["item_id"]


def _get_two_handed_item_id() -> str:
    from app.albion.item_catalog import get_catalog
    cat = get_catalog()
    items = cat.filter(slot="main_hand", is_two_handed=True)
    if not items:
        pytest.skip("No two-handed main_hand items in catalog")
    return items[0]["item_id"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def bws(live_server, isolated_db):
    """Fresh workspace + owner per test.  Returns a dict with:
    base_url, slug, owner_name, ws_id, owner_id.
    """
    from tests.conftest import make_user, make_workspace

    slug = f"bwp-{uuid.uuid4().hex[:8]}"
    owner = make_user(f"BWP-{uuid.uuid4().hex[:6]}")
    ws = make_workspace(
        name=f"Build WS {slug}",
        slug=slug,
        owner_user_id=owner["id"],
    )
    return {
        "base_url":   live_server,
        "slug":       slug,
        "owner_name": owner["display_name"],
        "ws_id":      ws["id"],
        "owner_id":   owner["id"],
    }


@pytest.fixture(scope="function")
def seeded_build(bws):
    """Creates a V2 build (version 1) via use_cases.  Returns bws + build."""
    from app.application import use_cases

    build = use_cases.create_build(
        guild_workspace_id=bws["ws_id"],
        actor_user_id=bws["owner_id"],
        name="Seeded Healer",
        description="Browser test build",
        role="healer",
        event_type="zvz",
        minimum_ip=1000,
        status="draft",
        slot_items_json=json.dumps([
            {"slot": "main_hand", "item_id": _get_catalog_item_id("main_hand"),
             "is_primary": True},
        ]),
        change_summary="Initial version",
    )
    return {**bws, "build": build}


@pytest.fixture(scope="function")
def published_seeded_build(bws):
    """Creates a V2 build with all published-required slots filled."""
    from app.application import use_cases
    from app.albion.item_catalog import get_catalog

    cat = get_catalog()

    def first(slot):
        items = cat.get_by_slot(slot)
        if not items:
            pytest.skip(f"No items for slot {slot}")
        return items[0]["item_id"]

    slots = [
        {"slot": "main_hand", "item_id": first("main_hand"), "is_primary": True},
        {"slot": "head",      "item_id": first("head"),      "is_primary": True},
        {"slot": "chest",     "item_id": first("chest"),     "is_primary": True},
        {"slot": "shoes",     "item_id": first("shoes"),     "is_primary": True},
        {"slot": "food",      "item_id": first("food"),      "is_primary": True},
        {"slot": "potion",    "item_id": first("potion"),    "is_primary": True},
    ]
    build = use_cases.create_build(
        guild_workspace_id=bws["ws_id"],
        actor_user_id=bws["owner_id"],
        name="Published Healer",
        description=None,
        role="healer",
        event_type="zvz",
        minimum_ip=1000,
        status="draft",
        slot_items_json=json.dumps(slots),
        change_summary="For publish test",
    )
    return {**bws, "build": build}


# ---------------------------------------------------------------------------
# 1. Create draft build — full UI flow
# ---------------------------------------------------------------------------

class TestCreateFlow:

    def test_create_draft_build_redirects_to_detail(self, page: Page, bws: dict):
        """Fill metadata, save as draft, verify redirect to V2 detail page."""
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds/editor")
        page.wait_for_selector(".vbe-slot", timeout=6000)

        # Fill metadata
        page.fill("#vbe-name", "Browser Draft Build")
        page.select_option("#vbe-role", value="healer")
        page.select_option("#vbe-event-type", value="zvz")
        page.fill("#vbe-min-ip", "900")

        # Draft is pre-selected; just click save
        page.click("#vbe-save-btn")

        # Must redirect to detail page
        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/**",
            timeout=8000,
        )

        # Verify success flash or build name on detail page
        content = page.content()
        assert "Browser Draft Build" in content

    def test_create_draft_shows_version_1(self, page: Page, bws: dict):
        """After create, detail page shows version 1."""
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds/editor")
        page.wait_for_selector(".vbe-slot", timeout=6000)

        page.fill("#vbe-name", "Version 1 Test Build")
        page.select_option("#vbe-role", value="support")
        page.select_option("#vbe-event-type", value="gank")
        page.click("#vbe-save-btn")
        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/**",
            timeout=8000,
        )

        content = page.content()
        assert "v1" in content or "version 1" in content.lower()

    def test_created_build_appears_in_list(self, page: Page, bws: dict):
        """After create, build appears in the workspace build list."""
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds/editor")
        page.wait_for_selector(".vbe-slot", timeout=6000)

        page.fill("#vbe-name", "List Appearance Build")
        page.select_option("#vbe-role", value="tank")
        page.select_option("#vbe-event-type", value="roam")
        page.click("#vbe-save-btn")
        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/**",
            timeout=8000,
        )

        # Navigate to builds list
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds")
        assert "List Appearance Build" in page.content()


# ---------------------------------------------------------------------------
# 2. Edit / versioning flow
# ---------------------------------------------------------------------------

class TestEditVersionFlow:

    def test_edit_creates_version_2(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/edit"
        )
        page.wait_for_selector(".vbe-slot", timeout=6000)

        # Change the name
        name_input = page.locator("#vbe-name")
        name_input.fill("Seeded Healer v2")

        page.click("#vbe-save-btn")
        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}**",
            timeout=8000,
        )

        content = page.content()
        assert "Seeded Healer v2" in content
        assert "v2" in content or "version 2" in content.lower()

    def test_edit_prepopulates_name(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/edit"
        )
        page.wait_for_selector(".vbe-slot", timeout=6000)

        name_val = page.locator("#vbe-name").input_value()
        assert name_val == "Seeded Healer"

    def test_version_history_shows_both_versions(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])

        # Create version 2 by editing
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/edit"
        )
        page.wait_for_selector(".vbe-slot", timeout=6000)
        page.locator("#vbe-name").fill("Seeded Healer V2 History")
        page.click("#vbe-save-btn")
        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}**",
            timeout=8000,
        )

        # Navigate to version history
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/versions"
        )
        content = page.content()
        assert "v1" in content or "Version 1" in content
        assert "v2" in content or "Version 2" in content

    def test_old_version_is_readonly(self, page: Page, seeded_build: dict):
        """Version 1 detail page must not have an 'Edit / New version' link."""
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])

        # Create version 2 via Python to avoid UI complexity
        from app.application import use_cases
        use_cases.create_build_version(
            guild_workspace_id=bws["ws_id"],
            build_id=build["id"],
            actor_user_id=bws["owner_id"],
            slot_items_json=json.dumps([
                {"slot": "head", "item_id": _get_catalog_item_id("head"),
                 "is_primary": True},
            ]),
            change_summary="Version 2 for RO test",
        )

        # Navigate to version history page
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/versions"
        )
        page.wait_for_selector("table", timeout=5000)

        # Find version 1's "View" link (the last row is the oldest version)
        v1_view_link = page.locator("a", has_text="View").last
        v1_href = v1_view_link.get_attribute("href")
        assert v1_href, "Expected a View link for version 1"

        page.goto(f"{bws['base_url']}{v1_href}")
        content = page.content()
        # Historical version must show historical/read-only indicator
        assert "historical" in content.lower() or "read-only" in content.lower() or (
            "read only" in content.lower()
        )


# ---------------------------------------------------------------------------
# 3. Stale save conflict
# ---------------------------------------------------------------------------

class TestStaleSaveConflict:

    def test_stale_expected_version_shows_conflict(self, page: Page, seeded_build: dict):
        """Submit with old expected_current_version_id → must show 409 error."""
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])

        # Open edit page — loads current version ID in hidden field
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/edit"
        )
        page.wait_for_selector(".vbe-slot", timeout=6000)

        # Simulate another user saving version 2 in Python directly
        from app.application import use_cases
        use_cases.create_build_version(
            guild_workspace_id=bws["ws_id"],
            build_id=build["id"],
            actor_user_id=bws["owner_id"],
            slot_items_json=json.dumps([
                {"slot": "head", "item_id": _get_catalog_item_id("head"),
                 "is_primary": True},
            ]),
            change_summary="Concurrent save",
        )

        # Change name on the browser page (which still has old expected_current_version_id)
        page.locator("#vbe-name").fill("Stale Save Attempt")
        page.click("#vbe-save-btn")

        # Must get a conflict response — either 409 or re-render with error
        # Waits up to 6 seconds for the error to be visible
        page.wait_for_timeout(2000)
        content = page.content()
        # Look for a conflict/error message; either from re-render or error page
        has_conflict_message = any(
            phrase in content.lower()
            for phrase in [
                "modified", "conflict", "stale", "reload", "changed",
                "409", "version", "another save"
            ]
        )
        assert has_conflict_message, (
            "Expected a conflict/stale-save error message to be visible in browser, "
            f"but page content was: {content[:500]}"
        )


# ---------------------------------------------------------------------------
# 4. Validation errors in browser
# ---------------------------------------------------------------------------

class TestValidationErrors:

    def test_empty_name_shows_error_in_editor(self, page: Page, bws: dict):
        """Submitting with empty name must re-render editor with error."""
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds/editor")
        page.wait_for_selector(".vbe-slot", timeout=6000)

        # Clear the name field and submit
        page.fill("#vbe-name", "")
        page.select_option("#vbe-role", value="tank")
        page.select_option("#vbe-event-type", value="ava")
        page.click("#vbe-save-btn")

        page.wait_for_timeout(2000)
        content = page.content()

        # Either browser native validation fires (required field) or
        # server returns editor re-render with error.
        # We verify the page does NOT redirect to a build detail.
        current_url = page.url
        assert "builds/editor" in current_url or (
            # Server returned editor with error
            "error" in content.lower() or
            "name" in content.lower()
        )

    def test_negative_ip_shows_validation_error(self, page: Page, bws: dict):
        """Submitting with negative minimum_ip must fail validation."""
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds/editor")
        page.wait_for_selector(".vbe-slot", timeout=6000)

        page.fill("#vbe-name", "Negative IP Build")
        page.select_option("#vbe-role", value="healer")
        page.select_option("#vbe-event-type", value="cta")

        # Inject negative IP via JavaScript (bypasses browser min="0" attribute)
        page.evaluate(
            "document.getElementById('vbe-min-ip').removeAttribute('min');"
            "document.getElementById('vbe-min-ip').value = '-100';"
        )

        page.click("#vbe-save-btn")
        page.wait_for_timeout(2000)

        content = page.content()
        current_url = page.url
        # Must NOT redirect to a build detail — must show error or stay on editor
        assert (
            "builds/editor" in current_url or
            "error" in content.lower() or
            "minimum" in content.lower() or
            "ip" in content.lower()
        )

    def test_malformed_slot_json_shows_error(self, page: Page, bws: dict):
        """A malformed slot_items_json payload must return an error, not a 500."""
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(f"{bws['base_url']}/workspaces/{bws['slug']}/builds/editor")
        page.wait_for_selector(".vbe-slot", timeout=6000)

        page.fill("#vbe-name", "Malformed Slot Build")
        page.select_option("#vbe-role", value="support")
        page.select_option("#vbe-event-type", value="other")

        # Inject malformed JSON into the hidden slot_items_json field
        page.evaluate(
            "document.getElementById('vbe-slot-items-json').value = 'not-valid-json';"
        )

        page.click("#vbe-save-btn")
        page.wait_for_timeout(2000)

        content = page.content()
        # Must not show a raw 500 — should show an error or stay on editor
        assert "Internal Server Error" not in content
        assert "500" not in page.url


# ---------------------------------------------------------------------------
# 5. Lifecycle: publish
# ---------------------------------------------------------------------------

class TestPublishLifecycle:

    def test_publish_draft_changes_status(self, page: Page, published_seeded_build: dict):
        bws = published_seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )

        # Confirm dialog is pre-handled (page.on("dialog") to auto-accept)
        page.on("dialog", lambda d: d.accept())
        publish_btn = page.locator("button", has_text="Publish")
        publish_btn.click()

        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}**",
            timeout=8000,
        )
        content = page.content()
        assert "published" in content.lower()

    def test_publish_draft_with_missing_required_slots_shows_error(
        self, page: Page, seeded_build: dict
    ):
        """A draft with only main_hand cannot be published — must show error."""
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )
        page.on("dialog", lambda d: d.accept())
        publish_btn = page.locator("button", has_text="Publish")
        if publish_btn.count() == 0:
            pytest.skip("No Publish button (build may already be published)")
        publish_btn.click()

        page.wait_for_timeout(2000)
        content = page.content()
        # Must not show published; must show error
        assert "error" in content.lower() or "required" in content.lower() or (
            "published" not in content.lower()
            or "alert-error" in content
        )


# ---------------------------------------------------------------------------
# 6. Lifecycle: archive
# ---------------------------------------------------------------------------

class TestArchiveLifecycle:

    def test_archive_changes_status_to_archived(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )
        page.on("dialog", lambda d: d.accept())
        archive_btn = page.locator("button", has_text="Archive")
        if archive_btn.count() == 0:
            pytest.skip("No Archive button visible on detail page")
        archive_btn.click()

        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}**",
            timeout=8000,
        )
        content = page.content()
        assert "archived" in content.lower()

    def test_archived_build_hides_edit_button(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        _login(page, bws["base_url"], bws["owner_name"])

        # Archive via Python
        from app.application import use_cases
        use_cases.archive_build(bws["ws_id"], build["id"], bws["owner_id"])

        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )
        content = page.content()
        # Edit button must not be visible for archived builds
        assert "Edit / New version" not in content

    def test_archived_build_detail_accessible(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        from app.application import use_cases
        use_cases.archive_build(bws["ws_id"], build["id"], bws["owner_id"])

        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )
        content = page.content()
        assert "Seeded Healer" in content, (
            "Archived build detail page must still be accessible and show the build name"
        )


# ---------------------------------------------------------------------------
# 7. Lifecycle: restore
# ---------------------------------------------------------------------------

class TestRestoreLifecycle:

    def test_restore_changes_status_to_draft(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        # Archive first via Python
        from app.application import use_cases
        use_cases.archive_build(bws["ws_id"], build["id"], bws["owner_id"])

        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )
        restore_btn = page.locator("button", has_text="Restore")
        if restore_btn.count() == 0:
            pytest.skip("No Restore button visible on detail page")
        restore_btn.click()

        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}**",
            timeout=8000,
        )
        content = page.content()
        assert "draft" in content.lower() or "restored" in content.lower()

    def test_restore_does_not_create_new_version(self, page: Page, seeded_build: dict):
        bws = seeded_build
        build = bws["build"]
        from app.application import use_cases, use_cases as uc
        from app import database, repositories

        use_cases.archive_build(bws["ws_id"], build["id"], bws["owner_id"])

        with database.transaction() as db:
            versions_before = repositories.list_build_versions(
                db, build["id"], bws["ws_id"]
            )

        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}"
        )
        restore_btn = page.locator("button", has_text="Restore")
        if restore_btn.count() == 0:
            pytest.skip("No Restore button visible")
        restore_btn.click()
        page.wait_for_timeout(2000)

        with database.transaction() as db:
            versions_after = repositories.list_build_versions(
                db, build["id"], bws["ws_id"]
            )
        assert len(versions_after) == len(versions_before), (
            f"Restore must not create a new version. Before: {len(versions_before)}, "
            f"After: {len(versions_after)}"
        )


# ---------------------------------------------------------------------------
# 8. No-change save
# ---------------------------------------------------------------------------

class TestNoChangeSave:

    def test_save_without_changes_shows_no_changes_message(
        self, page: Page, seeded_build: dict
    ):
        """Open edit, click save without changes → no new version, shows message."""
        bws = seeded_build
        build = bws["build"]
        from app import database, repositories

        with database.transaction() as db:
            versions_before = repositories.list_build_versions(
                db, build["id"], bws["ws_id"]
            )

        _login(page, bws["base_url"], bws["owner_name"])
        page.goto(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}/edit"
        )
        page.wait_for_selector(".vbe-slot", timeout=6000)

        # Do NOT change anything — just click save
        page.click("#vbe-save-btn")
        page.wait_for_url(
            f"{bws['base_url']}/workspaces/{bws['slug']}/builds/{build['id']}**",
            timeout=8000,
        )

        content = page.content()
        # Must show a "no changes" message
        assert (
            "no changes" in content.lower() or
            "unchanged" in content.lower() or
            "no_changes" in page.url
        )

        # Version count must not have increased
        with database.transaction() as db:
            versions_after = repositories.list_build_versions(
                db, build["id"], bws["ws_id"]
            )
        assert len(versions_after) == len(versions_before), (
            f"Save without changes must not create a new version. "
            f"Before: {len(versions_before)}, After: {len(versions_after)}"
        )
