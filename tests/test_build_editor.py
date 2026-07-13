"""
Phase 12.2 — Visual Build Editor route test suite.

Test groups:
  1.  GET /workspaces/{slug}/builds/editor returns 200 for members
  2.  Unauthenticated users are redirected to login
  3.  Unknown workspace returns 404
  4.  Template renders the equipment grid container
  5.  Template renders the item picker modal structure
  6.  Template links back to builds list
  7.  Route is accessible before the {build_id} catch-all route (no 404)
  8.  CSS asset reference is present in the page
  9.  Filter chips are present for Tier, Enchantment
  10. Two-handed filter group is present in the markup
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app
from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _editor_url(slug: str) -> str:
    return f"/workspaces/{slug}/builds/editor"


# ---------------------------------------------------------------------------
# 1. GET returns 200 for an authenticated workspace member
# ---------------------------------------------------------------------------

class TestBuildEditorAccessible:
    def test_member_gets_200(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner1")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        resp = client.get(_editor_url(ws["slug"]), follow_redirects=False)
        assert resp.status_code == 200

    def test_response_content_type_is_html(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner2")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        resp = client.get(_editor_url(ws["slug"]))
        assert "text/html" in resp.headers.get("content-type", "")

    def test_non_owner_member_can_access_editor(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("EditorOwner3")
        member = make_user("EditorMember3")
        ws     = make_workspace(owner_user_id=owner["id"])

        # Add member to workspace
        import uuid
        from datetime import datetime, timezone
        from app import repositories
        membership = {
            "id":                str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "user_id":           member["id"],
            "role":              "member",
            "created_at":        datetime.now(timezone.utc).isoformat(),
        }
        with database.transaction() as db:
            repositories.insert_workspace_member(db, membership)

        _login(client, member["display_name"])
        resp = client.get(_editor_url(ws["slug"]))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Unauthenticated users are redirected to login
# ---------------------------------------------------------------------------

class TestBuildEditorAuthRequired:
    def test_unauthenticated_redirects_to_login(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner4")
        ws    = make_workspace(owner_user_id=owner["id"])

        resp = client.get(_editor_url(ws["slug"]), follow_redirects=False)
        # Expect redirect to login
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# 3. Unknown workspace returns 404
# ---------------------------------------------------------------------------

class TestBuildEditorNotFound:
    def test_unknown_workspace_returns_404(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner5")
        _login(client, owner["display_name"])

        resp = client.get(_editor_url("no-such-workspace-slug-xyz"))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Template renders the equipment grid container
# ---------------------------------------------------------------------------

class TestBuildEditorGridMarkup:
    def test_equip_grid_container_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner6")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-equip-grid"' in html

    def test_two_handed_notice_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner7")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-two-handed-notice"' in html

    def test_reset_button_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner8")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-reset-btn"' in html


# ---------------------------------------------------------------------------
# 5. Template renders the item picker modal
# ---------------------------------------------------------------------------

class TestBuildEditorModalMarkup:
    def test_modal_backdrop_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner9")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-backdrop"' in html

    def test_modal_close_button_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner10")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-close"' in html

    def test_search_input_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner11")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-search"' in html

    def test_results_container_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner12")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-results"' in html

    def test_modal_has_dialog_role(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner13")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'role="dialog"' in html
        assert 'aria-modal="true"' in html


# ---------------------------------------------------------------------------
# 6. Template links back to builds list
# ---------------------------------------------------------------------------

class TestBuildEditorNavigation:
    def test_builds_back_link_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner14")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert f"/workspaces/{ws['slug']}/builds" in html

    def test_workspace_nav_shows_builds_active(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner15")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        # workspace_nav_active = 'builds' → the Builds link should have class="active"
        assert 'class="active"' in html


# ---------------------------------------------------------------------------
# 7. Route is correctly registered (not caught by {build_id})
# ---------------------------------------------------------------------------

class TestBuildEditorRouteRegistration:
    def test_editor_literal_path_not_caught_by_build_id_param(self):
        """'editor' must not be treated as a build UUID, returning 404."""
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner16")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        resp = client.get(_editor_url(ws["slug"]))
        assert resp.status_code == 200

    def test_editor_path_distinct_from_builds_new(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner17")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        editor_resp = client.get(_editor_url(ws["slug"]))
        new_resp    = client.get(f"/workspaces/{ws['slug']}/builds/new")

        assert editor_resp.status_code == 200
        assert new_resp.status_code == 200
        # The pages serve different content
        assert "vbe-equip-grid" in editor_resp.text
        assert "vbe-equip-grid" not in new_resp.text


# ---------------------------------------------------------------------------
# 8. CSS asset reference present
# ---------------------------------------------------------------------------

class TestBuildEditorAssets:
    def test_build_editor_css_linked(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner18")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert "build_editor.css" in html

    def test_page_title_contains_build_editor(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner19")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert "Build Editor" in html


# ---------------------------------------------------------------------------
# 9. Filter chips for Tier and Enchantment
# ---------------------------------------------------------------------------

class TestBuildEditorFilterChips:
    def test_tier_chips_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner20")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-tier-chips"' in html
        assert 'data-tier="7"' in html
        assert 'data-tier="8"' in html

    def test_enchantment_chips_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner21")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-ench-chips"' in html
        for ench in range(4):
            assert f'data-ench="{ench}"' in html

    def test_all_tier_chips_default_to_active(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner22")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        # Both tier chips should have the --active class
        assert html.count('data-tier=') == 2
        # Both should have vbe-chip--active class
        import re
        tier_chips = re.findall(r'<button[^>]*data-tier="[78]"[^>]*>', html)
        assert len(tier_chips) == 2
        assert all("vbe-chip--active" in chip for chip in tier_chips)


# ---------------------------------------------------------------------------
# 10. Two-handed filter group is present in markup
# ---------------------------------------------------------------------------

class TestBuildEditorTwoHandedFilter:
    def test_two_handed_filter_group_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner23")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'id="vbe-2h-filter-group"' in html

    def test_two_handed_chips_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner24")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        assert 'data-2h="any"' in html
        assert 'data-2h="1h"' in html
        assert 'data-2h="2h"' in html

    def test_two_handed_filter_is_hidden_by_default(self):
        """Off-hand / two-handed filter is hidden until a weapon slot is opened."""
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner25")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(_editor_url(ws["slug"])).text
        # The filter group has `hidden` attribute by default
        assert 'id="vbe-2h-filter-group" hidden' in html


# ---------------------------------------------------------------------------
# 11. Builds list page now includes the Visual Editor link
# ---------------------------------------------------------------------------

class TestBuildsListEditorLink:
    def test_builds_list_has_visual_editor_link(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner = make_user("EditorOwner26")
        ws    = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])

        html = client.get(f"/workspaces/{ws['slug']}/builds").text
        assert f"/workspaces/{ws['slug']}/builds/editor" in html
        assert "Visual Editor" in html
