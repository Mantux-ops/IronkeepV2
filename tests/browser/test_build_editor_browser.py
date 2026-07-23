"""
Phase 12.2c — Visual Build Editor browser tests (Playwright/Chromium).

Uses real Chromium via pytest-playwright. The `browser_workspace` fixture
(defined in tests/browser/conftest.py) provides a running uvicorn server
and a pre-created workspace that persist for the entire session.

Run:
    pytest tests/browser/ -v             # headless
    pytest tests/browser/ -v --headed    # shows the browser

Test groups:
  1.  Editor page loads and renders slot grid
  2.  Clicking a slot opens the picker modal
  3.  Picker loads items from catalog API
  4.  Live search filters results
  5.  Tier and enchantment chip filtering
  6.  Selecting an item updates the slot tile
  7.  Two-handed weapon locks off_hand
  8.  One-handed weapon unlocks off_hand
  9.  Individual slot clear button
 10.  Reset-all button
 11.  Modal close behaviours (button, Escape, backdrop)
 12.  Focus is trapped inside the modal
 13.  Render-limit notice for large result sets
 15.  Body scroll locked while modal is open
 16.  Network error state (automated_browser_test — Phase 12.2c)
 17.  Retry success flow  (automated_browser_test — Phase 12.2c)
 18.  Invalid JSON response (automated_browser_test — Phase 12.2c)
 19.  Non-2xx HTTP response (automated_browser_test — Phase 12.2c)
 20.  Icon image fallback  (automated_browser_test — Phase 12.2c)
 21.  Prefers-reduced-motion (automated_browser_test — Phase 12.2c)
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Login helper
# ---------------------------------------------------------------------------

def _login(page: Page, base_url: str, display_name: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill('input[name="display_name"]', display_name)
    page.click('input[type="submit"]')
    page.wait_for_url(f"{base_url}/workspaces**", timeout=6000)


def _open_editor(page: Page, bw: dict) -> None:
    """Login and navigate to the build editor. Waits for slot grid."""
    _login(page, bw["base_url"], bw["owner_name"])
    page.goto(f"{bw['base_url']}/workspaces/{bw['slug']}/builds/editor")
    page.wait_for_selector('.vbe-slot', timeout=5000)


# ---------------------------------------------------------------------------
# 1. Editor page loads and renders the slot grid
# ---------------------------------------------------------------------------

class TestEditorPageLoad:
    def test_grid_has_eight_slot_buttons(self, page: Page, browser_workspace):
        # bag and mount were removed from builds — 8 equipment slots remain.
        _open_editor(page, browser_workspace)
        assert page.locator('.vbe-slot').count() == 8

    def test_all_slots_start_empty(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        assert page.locator('.vbe-slot--filled').count() == 0

    def test_two_handed_notice_hidden_on_load(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        assert page.locator('#vbe-two-handed-notice').is_hidden()


# ---------------------------------------------------------------------------
# 2. Clicking a slot opens the picker modal
# ---------------------------------------------------------------------------

class TestPickerOpens:
    def test_click_head_opens_modal(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        expect(page.locator('.vbe-modal')).to_be_visible()

    def test_modal_title_reflects_slot(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-chest')
        expect(page.locator('#vbe-modal-title')).to_have_text('Select — Chest')

    def test_2h_filter_hidden_for_head_slot(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        assert page.locator('#vbe-2h-filter-group').is_hidden()

    def test_2h_filter_visible_for_main_hand(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-main_hand')
        expect(page.locator('#vbe-2h-filter-group')).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Picker loads items from catalog API
# ---------------------------------------------------------------------------

class TestPickerLoadsItems:
    def test_item_cards_appear_after_load(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-cape')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        assert page.locator('.vbe-item-card').count() > 0

    def test_search_input_focused_after_load(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-food')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        expect(page.locator('#vbe-search')).to_be_focused()


# ---------------------------------------------------------------------------
# 4. Live search filters results
# ---------------------------------------------------------------------------

class TestLiveSearch:
    def test_search_claymore_returns_results(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)

        page.fill('#vbe-search', 'Claymore')
        page.wait_for_timeout(300)

        cards = page.locator('.vbe-item-card')
        assert cards.count() > 0
        for i in range(min(cards.count(), 3)):
            assert 'claymore' in cards.nth(i).inner_text().lower()

    def test_search_with_extra_whitespace_works(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.fill('#vbe-search', '  claymore  ')
        page.wait_for_timeout(300)
        assert page.locator('.vbe-item-card').count() > 0

    def test_no_match_shows_empty_state(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.fill('#vbe-search', 'xyznonexistentitemabcdef999')
        page.wait_for_timeout(300)
        assert page.locator('.vbe-item-card').count() == 0
        expect(page.locator('.vbe-empty')).to_be_visible()

    def test_empty_state_shows_reset_filters_button(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.fill('#vbe-search', 'xyznonexistentitemabcdef999')
        page.wait_for_timeout(300)
        expect(page.locator('text=Reset filters')).to_be_visible()

    def test_reset_filters_restores_results(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.fill('#vbe-search', 'xyznonexistentitemabcdef999')
        page.wait_for_timeout(300)

        page.click('text=Reset filters')
        page.wait_for_timeout(300)
        assert page.locator('.vbe-item-card').count() > 0


# ---------------------------------------------------------------------------
# 5. Tier and enchantment chip filtering
# ---------------------------------------------------------------------------

class TestFilterChips:
    def test_deactivating_t7_reduces_results(self, page: Page, browser_workspace):
        # Use potion (48 items total, well below the 100-card render limit)
        # so we can count exact results without hitting the cap.
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-potion')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        all_count = page.locator('.vbe-item-card').count()  # T7 + T8

        page.click('[data-tier="7"]')  # deactivate T7
        page.wait_for_timeout(200)
        t8_count = page.locator('.vbe-item-card').count()  # T8 only

        assert t8_count < all_count, f"Expected fewer results after deactivating T7, got {t8_count} vs {all_count}"


# ---------------------------------------------------------------------------
# 6. Selecting an item updates the slot tile
# ---------------------------------------------------------------------------

class TestItemSelection:
    def test_select_item_fills_slot(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-shoes')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('#vbe-slot-shoes.vbe-slot--filled').count() == 1

    def test_select_item_shows_tier_badge(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-food')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        badge = page.locator('#vbe-slot-food .vbe-tier-badge')
        expect(badge).to_be_visible()
        assert badge.inner_text().startswith('T')

    def test_select_claymore_t8_3_acceptance_criteria(self, page: Page, browser_workspace):
        """Acceptance criteria: officer selects T8.3 Claymore for main hand."""
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)

        page.fill('#vbe-search', 'Claymore')
        page.wait_for_timeout(300)
        page.click('[data-tier="7"]')    # deactivate T7
        page.wait_for_timeout(100)
        for ench in ['0', '1', '2']:
            page.click(f'[data-ench="{ench}"]')
            page.wait_for_timeout(80)

        page.wait_for_selector('.vbe-item-card', timeout=4000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

        slot = page.locator('#vbe-slot-main_hand')
        assert 'vbe-slot--filled' in slot.get_attribute('class')
        assert 'T8' in slot.locator('.vbe-tier-badge').inner_text()


# ---------------------------------------------------------------------------
# 7. Two-handed weapon locks off_hand
# ---------------------------------------------------------------------------

class TestTwoHandedLock:

    def _pick_2h_weapon(self, page: Page) -> None:
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.click('[data-2h="2h"]')
        page.wait_for_timeout(200)
        page.wait_for_selector('.vbe-item-card', timeout=4000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

    def test_off_hand_gets_aria_disabled(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        self._pick_2h_weapon(page)
        assert page.locator('#vbe-slot-off_hand').get_attribute('aria-disabled') == 'true'

    def test_off_hand_gets_disabled_class(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        self._pick_2h_weapon(page)
        assert 'vbe-slot--disabled' in page.locator('#vbe-slot-off_hand').get_attribute('class')

    def test_two_handed_notice_visible(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        self._pick_2h_weapon(page)
        expect(page.locator('#vbe-two-handed-notice')).to_be_visible()

    def test_clicking_disabled_off_hand_does_not_open_picker(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        self._pick_2h_weapon(page)
        page.click('#vbe-slot-off_hand', force=True)
        page.wait_for_timeout(300)
        assert page.locator('.vbe-modal').is_hidden()


# ---------------------------------------------------------------------------
# 8. One-handed weapon unlocks off_hand
# ---------------------------------------------------------------------------

class TestOneHandedUnlock:
    def test_1h_weapon_enables_off_hand(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)

        # Pick 2H weapon first
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.click('[data-2h="2h"]')
        page.wait_for_timeout(200)
        page.wait_for_selector('.vbe-item-card', timeout=4000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('#vbe-slot-off_hand').get_attribute('aria-disabled') == 'true'

        # Pick 1H weapon
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.click('[data-2h="1h"]')
        page.wait_for_timeout(200)
        page.wait_for_selector('.vbe-item-card', timeout=4000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

        off_btn = page.locator('#vbe-slot-off_hand')
        assert off_btn.get_attribute('aria-disabled') is None
        assert 'vbe-slot--disabled' not in (off_btn.get_attribute('class') or '')
        assert page.locator('#vbe-two-handed-notice').is_hidden()


# ---------------------------------------------------------------------------
# 9. Individual slot clear button
# ---------------------------------------------------------------------------

class TestSlotClear:
    def test_clear_button_visible_when_filled(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-potion')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        expect(page.locator('#vbe-slot-potion .vbe-slot__clear')).to_be_visible()

    def test_clear_button_empties_slot(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-cape')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('#vbe-slot-cape.vbe-slot--filled').count() == 1

        page.locator('#vbe-slot-cape .vbe-slot__clear').click()
        page.wait_for_timeout(200)
        assert page.locator('#vbe-slot-cape.vbe-slot--filled').count() == 0

    def test_clear_does_not_open_picker(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-food')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

        page.locator('#vbe-slot-food .vbe-slot__clear').click()
        page.wait_for_timeout(300)
        assert page.locator('.vbe-modal').is_hidden()

    def test_clearing_main_hand_unlocks_off_hand(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)

        # Select 2H weapon
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.click('[data-2h="2h"]')
        page.wait_for_timeout(200)
        page.wait_for_selector('.vbe-item-card', timeout=4000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('#vbe-slot-off_hand').get_attribute('aria-disabled') == 'true'

        # Clear main hand
        page.locator('#vbe-slot-main_hand .vbe-slot__clear').click()
        page.wait_for_timeout(200)

        assert page.locator('#vbe-slot-off_hand').get_attribute('aria-disabled') is None
        assert page.locator('#vbe-two-handed-notice').is_hidden()


# ---------------------------------------------------------------------------
# 10. Reset-all button
# ---------------------------------------------------------------------------

class TestResetAll:
    def test_reset_clears_all_filled_slots(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('.vbe-slot--filled').count() >= 1

        page.click('#vbe-reset-btn')
        page.wait_for_timeout(200)
        assert page.locator('.vbe-slot--filled').count() == 0

    def test_reset_unlocks_off_hand(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)

        # Select 2H weapon
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.click('[data-2h="2h"]')
        page.wait_for_timeout(200)
        page.wait_for_selector('.vbe-item-card', timeout=4000)
        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

        page.click('#vbe-reset-btn')
        page.wait_for_timeout(200)

        assert page.locator('#vbe-slot-off_hand').get_attribute('aria-disabled') is None
        assert page.locator('#vbe-two-handed-notice').is_hidden()


# ---------------------------------------------------------------------------
# 11. Modal close behaviours
# ---------------------------------------------------------------------------

class TestModalClose:
    def test_close_button(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        expect(page.locator('.vbe-modal')).to_be_visible()
        page.click('#vbe-close')
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

    def test_escape_key(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-chest')
        expect(page.locator('.vbe-modal')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

    def test_backdrop_click(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-shoes')
        expect(page.locator('.vbe-modal')).to_be_visible()
        page.mouse.click(5, 5)
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)

    def test_focus_returns_to_slot_after_escape(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-cape')
        expect(page.locator('.vbe-modal')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        page.wait_for_timeout(100)
        # Use document.activeElement instead of Playwright's is_focused(),
        # which can report "inactive" in headless mode even when focus is correct.
        active_id = page.evaluate("document.activeElement?.id")
        assert active_id == 'vbe-slot-cape', \
            f"Expected focus on #vbe-slot-cape after Escape, got: #{active_id}"


# ---------------------------------------------------------------------------
# 12. Focus trap inside the modal
# ---------------------------------------------------------------------------

class TestFocusTrap:
    def test_tab_stays_inside_modal(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        page.wait_for_selector('#vbe-search', timeout=4000)
        expect(page.locator('#vbe-search')).to_be_focused()

        for _ in range(15):
            page.keyboard.press('Tab')
            inside_modal = page.evaluate(
                "document.activeElement?.closest('.vbe-modal') !== null"
            )
            assert inside_modal, "Focus escaped the modal after Tab"


# ---------------------------------------------------------------------------
# 13. Render-limit notice for large result sets
# ---------------------------------------------------------------------------

class TestRenderLimit:
    def test_main_hand_shows_limit_notice(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        expect(page.locator('.vbe-results-limit')).to_be_visible()

    def test_limit_notice_gone_with_narrow_search(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-main_hand')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.fill('#vbe-search', 'Claymore')
        page.wait_for_timeout(300)
        assert page.locator('.vbe-results-limit').is_hidden()


# ---------------------------------------------------------------------------
# 14. Body scroll locked while modal is open
# ---------------------------------------------------------------------------

class TestBodyScroll:
    def test_body_overflow_hidden_when_open(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        expect(page.locator('.vbe-modal')).to_be_visible()
        assert page.evaluate("document.body.style.overflow") == 'hidden'

    def test_body_overflow_restored_after_close(self, page: Page, browser_workspace):
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        page.click('#vbe-close')
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.evaluate("document.body.style.overflow") == ''


# ---------------------------------------------------------------------------
# 16. Network error state  (Phase 12.2c)
# ---------------------------------------------------------------------------

class TestNetworkErrorState:
    """
    Intercept /api/catalog/items* to simulate failure scenarios.

    Evidence level: automated_browser_test
    """

    def test_network_failure_shows_error_state(self, page: Page, browser_workspace):
        """Abort the catalog request — error state must appear, not empty state."""
        page.route("**/api/catalog/items**", lambda r: r.abort())
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')

        page.wait_for_selector('.vbe-error', timeout=8000)

        # Error paragraph visible
        expect(page.locator('.vbe-error')).to_be_visible()

        # Retry button visible
        retry_btn = page.locator('.vbe-state-wrap button')
        expect(retry_btn).to_be_visible()
        assert 'Retry' in retry_btn.inner_text()

        # Not confused with empty state
        assert page.locator('.vbe-empty').count() == 0
        assert page.locator('.vbe-item-card').count() == 0

        # Loading indicator gone
        assert page.locator('.vbe-loading').count() == 0

        # Modal remains open (picker still usable for retry)
        expect(page.locator('.vbe-modal')).to_be_visible()

    def test_network_failure_error_differs_from_empty_state(self, page: Page, browser_workspace):
        """Verify .vbe-error and .vbe-empty are mutually exclusive for a failed request."""
        page.route("**/api/catalog/items**", lambda r: r.abort())
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-chest')

        page.wait_for_selector('.vbe-error', timeout=8000)

        # Error element present, empty element absent
        assert page.locator('.vbe-error').count() >= 1
        assert page.locator('.vbe-empty').count() == 0


# ---------------------------------------------------------------------------
# 17. Retry success flow  (Phase 12.2c)
# ---------------------------------------------------------------------------

class TestRetrySuccess:
    """
    First request aborted → user clicks Retry → second request succeeds.

    Evidence level: automated_browser_test
    """

    def test_retry_clears_error_and_loads_items(self, page: Page, browser_workspace):
        call_count: list[int] = [0]

        def handle(route):
            call_count[0] += 1
            if call_count[0] == 1:
                route.abort()
            else:
                route.continue_()

        page.route("**/api/catalog/items**", handle)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-cape')

        # First load fails
        page.wait_for_selector('.vbe-error', timeout=8000)
        expect(page.locator('.vbe-error')).to_be_visible()

        # Click retry
        page.locator('.vbe-state-wrap button').click()

        # Items appear
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        assert page.locator('.vbe-item-card').count() > 0

        # Error gone
        assert page.locator('.vbe-error').count() == 0

        # Picker still open
        expect(page.locator('.vbe-modal')).to_be_visible()

    def test_retry_item_is_selectable(self, page: Page, browser_workspace):
        """After retry success, an item can be selected normally."""
        call_count: list[int] = [0]

        def handle(route):
            call_count[0] += 1
            if call_count[0] == 1:
                route.abort()
            else:
                route.continue_()

        page.route("**/api/catalog/items**", handle)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-food')

        page.wait_for_selector('.vbe-error', timeout=8000)
        page.locator('.vbe-state-wrap button').click()
        page.wait_for_selector('.vbe-item-card', timeout=8000)

        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('#vbe-slot-food.vbe-slot--filled').count() == 1


# ---------------------------------------------------------------------------
# 18. Invalid JSON response  (Phase 12.2c)
# ---------------------------------------------------------------------------

class TestInvalidJsonResponse:
    """
    Endpoint returns HTTP 200 with a body that is not valid JSON.

    Evidence level: automated_browser_test
    """

    def test_invalid_json_shows_error_state(self, page: Page, browser_workspace):
        def bad_json(route):
            route.fulfill(status=200, body="not valid json {{{", content_type="application/json")

        page.route("**/api/catalog/items**", bad_json)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')

        page.wait_for_selector('.vbe-error', timeout=8000)
        expect(page.locator('.vbe-error')).to_be_visible()

    def test_invalid_json_retry_available(self, page: Page, browser_workspace):
        def bad_json(route):
            route.fulfill(status=200, body="not valid json {{{", content_type="application/json")

        page.route("**/api/catalog/items**", bad_json)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-food')

        page.wait_for_selector('.vbe-error', timeout=8000)
        expect(page.locator('.vbe-state-wrap button')).to_be_visible()
        assert 'Retry' in page.locator('.vbe-state-wrap button').inner_text()

    def test_invalid_json_no_item_cards(self, page: Page, browser_workspace):
        def bad_json(route):
            route.fulfill(status=200, body="not valid json {{{", content_type="application/json")

        page.route("**/api/catalog/items**", bad_json)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-shoes')

        page.wait_for_selector('.vbe-error', timeout=8000)
        assert page.locator('.vbe-item-card').count() == 0
        assert page.locator('.vbe-empty').count() == 0


# ---------------------------------------------------------------------------
# 19. Non-2xx HTTP response  (Phase 12.2c)
# ---------------------------------------------------------------------------

class TestNon2xxResponse:
    """
    Endpoint returns HTTP 500 — same error flow as network failure.

    Evidence level: automated_browser_test
    """

    def test_http_500_shows_error_state(self, page: Page, browser_workspace):
        def server_error(route):
            route.fulfill(status=500, body="Internal Server Error")

        page.route("**/api/catalog/items**", server_error)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-potion')

        page.wait_for_selector('.vbe-error', timeout=8000)
        expect(page.locator('.vbe-error')).to_be_visible()

    def test_http_500_retry_available(self, page: Page, browser_workspace):
        def server_error(route):
            route.fulfill(status=500, body="Internal Server Error")

        page.route("**/api/catalog/items**", server_error)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-food')

        page.wait_for_selector('.vbe-error', timeout=8000)
        retry_btn = page.locator('.vbe-state-wrap button')
        expect(retry_btn).to_be_visible()
        assert 'Retry' in retry_btn.inner_text()

    def test_http_500_no_empty_state(self, page: Page, browser_workspace):
        def server_error(route):
            route.fulfill(status=500, body="Internal Server Error")

        page.route("**/api/catalog/items**", server_error)
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-cape')

        page.wait_for_selector('.vbe-error', timeout=8000)
        assert page.locator('.vbe-empty').count() == 0
        assert page.locator('.vbe-item-card').count() == 0


# ---------------------------------------------------------------------------
# 20. Icon image fallback  (Phase 12.2c)
# ---------------------------------------------------------------------------

class TestIconFallback:
    """
    Intercept the Albion render CDN and verify the JS fallback mechanism.

    Limitation: images use loading="lazy"; in headless Chromium the browser
    may not issue the image request until the image is in the viewport.
    This test additionally triggers the error event via evaluate() to ensure
    deterministic fallback regardless of lazy-load timing.

    Evidence level: automated_browser_test
    """

    def test_broken_image_replaced_by_fallback(self, page: Page, browser_workspace):
        # Intercept all Albion render CDN requests and return 404
        page.route("**render.albiononline.com**", lambda r: r.fulfill(status=404, body=""))

        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-potion')  # 48 items — all visible without scrolling
        page.wait_for_selector('.vbe-item-card', timeout=8000)

        # Force the error event on the first card image (covers lazy-load delay in headless)
        page.evaluate("""
            const img = document.querySelector('.vbe-item-card__icon');
            if (img) img.dispatchEvent(new Event('error'));
        """)
        page.wait_for_timeout(200)

        first_card = page.locator('.vbe-item-card').first

        # Fallback div present
        fallback = first_card.locator('.vbe-item-card__icon-fallback')
        expect(fallback).to_be_visible()

        # Item name still visible
        expect(first_card.locator('.vbe-item-card__name')).to_be_visible()

        # Original <img> removed by _onCardIconError — no broken image icon remains
        assert first_card.locator('img').count() == 0

    def test_broken_image_card_is_selectable(self, page: Page, browser_workspace):
        """Card with a broken image fallback can still be selected."""
        page.route("**render.albiononline.com**", lambda r: r.fulfill(status=404, body=""))

        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-potion')
        page.wait_for_selector('.vbe-item-card', timeout=8000)

        # Trigger fallback on first card
        page.evaluate("""
            const img = document.querySelector('.vbe-item-card__icon');
            if (img) img.dispatchEvent(new Event('error'));
        """)
        page.wait_for_timeout(200)

        page.locator('.vbe-item-card').first.click()
        expect(page.locator('.vbe-modal')).to_be_hidden(timeout=3000)
        assert page.locator('#vbe-slot-potion.vbe-slot--filled').count() == 1


# ---------------------------------------------------------------------------
# 21. Prefers-reduced-motion  (Phase 12.2c)
# ---------------------------------------------------------------------------

class TestReducedMotion:
    """
    Use page.emulate_media(reduced_motion="reduce") to verify that the
    CSS @media (prefers-reduced-motion: reduce) rule disables transitions
    on the modal backdrop and key interactive elements.

    Evidence level: automated_browser_test
    """

    def test_reduced_motion_disables_modal_backdrop_transition(
        self, page: Page, browser_workspace
    ):
        page.emulate_media(reduced_motion="reduce")
        _open_editor(page, browser_workspace)
        page.click('#vbe-slot-head')
        expect(page.locator('.vbe-modal')).to_be_visible()

        # getComputedStyle returns resolved values; transition-duration is '0s'
        # when `transition: none` applies.
        transition = page.evaluate(
            "getComputedStyle(document.querySelector('.vbe-modal-backdrop')).transitionDuration"
        )
        assert transition == '0s', (
            f"Expected backdrop transitionDuration='0s' under reduced-motion, got '{transition}'"
        )

    def test_reduced_motion_disables_slot_transition(
        self, page: Page, browser_workspace
    ):
        page.emulate_media(reduced_motion="reduce")
        _open_editor(page, browser_workspace)

        transition = page.evaluate(
            "getComputedStyle(document.querySelector('.vbe-slot')).transitionDuration"
        )
        assert transition == '0s', (
            f"Expected slot transitionDuration='0s' under reduced-motion, got '{transition}'"
        )
