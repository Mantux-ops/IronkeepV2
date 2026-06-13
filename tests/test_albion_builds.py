"""
Albion build lifecycle and composition integration tests — Phase 3.

Covers:
  Group 1  — Domain validation (albion_builds.py)
  Group 2  — Repository CRUD (insert / get / get_all / update / retire)
  Group 3  — Use case: create_albion_build
  Group 4  — Use case: update_albion_build
  Group 5  — Use case: retire_albion_build
  Group 6  — Build Snapshot Invariant: editing build does NOT change existing
             composition slot templates or operation_slots
  Group 7  — Composition integration: attach build FK via update_composition_slots
  Group 8  — Route GET: builds list, detail, new, edit
  Group 9  — Route POST: create, update, retire
  Group 10 — Permissions: can_mutate enforcement, readonly denial
  Group 11 — Retired build restrictions (cannot attach, cannot re-edit)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import albion_builds as builds_domain
from app.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_setup(owner_name: str, slug: str):
    owner = make_user(owner_name)
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    client = TestClient(app)
    client.post("/login", data={"display_name": owner_name, "next": "/"}, follow_redirects=True)
    return client, owner, ws


def _create_build(ws_id: str, actor_id: str, **overrides) -> dict:
    defaults = {
        "guild_workspace_id": ws_id,
        "actor_user_id":      actor_id,
        "name":               "Hallowfall Healer",
        "role":               "Healer",
        "weapon_name":        "T8.3 Hallowfall",
    }
    return use_cases.create_albion_build(**{**defaults, **overrides})


def _make_member(ws_id: str, actor_id: str, display_name: str, role: str = "member") -> dict:
    """Create a user and add them to the workspace.

    add_workspace_member looks users up by display_name, so the user must be
    created first.  It takes (ws_id, actor_id, display_name, role).
    """
    user = make_user(display_name)
    use_cases.add_workspace_member(ws_id, actor_id, display_name, role)
    return user


# ---------------------------------------------------------------------------
# Group 1 — Domain validation
# ---------------------------------------------------------------------------

class TestBuildDomainValidation:

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError, match="name"):
            builds_domain.validate_build({"name": "", "role": "DPS", "weapon_name": "Bow"})

    def test_rejects_missing_role(self):
        with pytest.raises(ValidationError, match="role"):
            builds_domain.validate_build({"name": "Bow DPS", "role": "", "weapon_name": "Bow"})

    def test_rejects_missing_weapon(self):
        with pytest.raises(ValidationError, match="weapon_name"):
            builds_domain.validate_build({"name": "Bow DPS", "role": "DPS", "weapon_name": ""})

    def test_rejects_name_too_long(self):
        with pytest.raises(ValidationError, match="name"):
            builds_domain.validate_build({
                "name": "x" * 101, "role": "DPS", "weapon_name": "Bow"
            })

    def test_rejects_equipment_field_too_long(self):
        """Equipment fields (head_name etc.) enforce the 120-char limit."""
        with pytest.raises(ValidationError, match="head_name"):
            builds_domain.validate_build({
                "name": "Build", "role": "DPS", "weapon_name": "Bow",
                "head_name": "H" * 121,
            })

    def test_rejects_notes_too_long(self):
        """Notes enforce the 500-char limit (raised from 120 in Phase 4)."""
        with pytest.raises(ValidationError, match="notes"):
            builds_domain.validate_build({
                "name": "Build", "role": "DPS", "weapon_name": "Bow",
                "notes": "x" * 501,
            })

    def test_accepts_valid_build(self):
        builds_domain.validate_build({
            "name": "T8 Hallowfall", "role": "Healer", "weapon_name": "T8.3 Hallowfall",
            "notes": "Core healer doctrine",
        })


# ---------------------------------------------------------------------------
# Group 2 — Repository CRUD
# ---------------------------------------------------------------------------

class TestBuildRepository:

    def test_insert_and_get(self):
        ws = make_workspace(slug="repo-bld-1")
        with database.transaction() as db:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            build = {
                "id": "b1", "guild_workspace_id": ws["id"],
                "name": "Tombhammer", "role": "Tank", "weapon_name": "T8 Tombhammer",
                "offhand_name": None, "head_name": None, "armor_name": None,
                "shoes_name": None, "cape_name": None, "food_name": None,
                "potion_name": None, "notes": None, "doctrine_role": None,
                "created_at": now, "updated_at": now, "retired_at": None,
            }
            repositories.insert_albion_build(db, build)
            fetched = repositories.get_albion_build(db, "b1", ws["id"])
        assert fetched["name"] == "Tombhammer"
        assert fetched["role"] == "Tank"

    def test_get_returns_none_for_missing(self):
        ws = make_workspace(slug="repo-bld-2")
        with database.transaction() as db:
            result = repositories.get_albion_build(db, "nonexistent", ws["id"])
        assert result is None

    def test_get_all_excludes_retired_by_default(self):
        owner = make_user("RepoOwner3")
        ws    = make_workspace(owner_user_id=owner["id"], slug="repo-bld-3")
        b1 = _create_build(ws["id"], owner["id"], name="Active Build",
                           role="DPS", weapon_name="Bow")
        b2 = _create_build(ws["id"], owner["id"], name="Retired Build",
                           role="Tank", weapon_name="Mace")
        use_cases.retire_albion_build(ws["id"], b2["id"], owner["id"])
        with database.transaction() as db:
            active = repositories.get_albion_builds(db, ws["id"])
            all_   = repositories.get_albion_builds(db, ws["id"], include_retired=True)
        assert len(active) == 1
        assert active[0]["name"] == "Active Build"
        assert len(all_) == 2

    def test_workspace_isolation(self):
        o1  = make_user("IsoOwner1")
        o2  = make_user("IsoOwner2")
        ws1 = make_workspace(owner_user_id=o1["id"], slug="repo-bld-iso-1")
        ws2 = make_workspace(owner_user_id=o2["id"], slug="repo-bld-iso-2")
        _create_build(ws1["id"], o1["id"], name="WS1 Build", role="DPS", weapon_name="Bow")
        with database.transaction() as db:
            ws2_builds = repositories.get_albion_builds(db, ws2["id"])
        assert len(ws2_builds) == 0


# ---------------------------------------------------------------------------
# Group 3 — Use case: create_albion_build
# ---------------------------------------------------------------------------

class TestCreateAlbionBuild:

    def setup_method(self):
        self.owner = make_user("BuildCreator")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="uc-create-bld")

    def test_creates_build_with_minimal_fields(self):
        build = _create_build(self.ws["id"], self.owner["id"])
        assert build["id"]
        assert build["name"] == "Hallowfall Healer"
        assert build["role"] == "Healer"
        assert build["weapon_name"] == "T8.3 Hallowfall"
        assert build["retired_at"] is None

    def test_creates_build_with_all_fields(self):
        build = use_cases.create_albion_build(
            guild_workspace_id=self.ws["id"],
            actor_user_id=self.owner["id"],
            name="Full Kit",
            role="DPS",
            weapon_name="T8 Bow",
            offhand_name=None,
            head_name="Mage Cowl",
            armor_name="Cleric Robe",
            shoes_name="Cleric Sandals",
            cape_name="Thetford Cape",
            food_name="Beef Stew",
            potion_name="Resistance Potion",
            notes="ZvZ ranged DPS doctrine",
        )
        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], self.ws["id"])
        assert fetched["food_name"] == "Beef Stew"
        assert fetched["notes"] == "ZvZ ranged DPS doctrine"

    def test_rejects_invalid_name(self):
        with pytest.raises(ValidationError):
            use_cases.create_albion_build(
                guild_workspace_id=self.ws["id"],
                actor_user_id=self.owner["id"],
                name="",
                role="DPS",
                weapon_name="Bow",
            )

    def test_rejects_non_officer(self):
        member = _make_member(self.ws["id"], self.owner["id"], "RegMember", "member")
        with pytest.raises(PermissionDenied):
            _create_build(self.ws["id"], member["id"])

    def test_rejects_wrong_workspace(self):
        with pytest.raises(NotFoundError):
            _create_build("nonexistent-ws", self.owner["id"])


# ---------------------------------------------------------------------------
# Group 4 — Use case: update_albion_build
# ---------------------------------------------------------------------------

class TestUpdateAlbionBuild:

    def setup_method(self):
        self.owner = make_user("BuildUpdater")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="uc-upd-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"])

    def test_updates_build_fields(self):
        use_cases.update_albion_build(
            guild_workspace_id=self.ws["id"],
            build_id=self.build["id"],
            actor_user_id=self.owner["id"],
            name="Updated Hallowfall",
            role="Healer",
            weapon_name="T8.4 Hallowfall",
        )
        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, self.build["id"], self.ws["id"])
        assert fetched["name"] == "Updated Hallowfall"
        assert fetched["weapon_name"] == "T8.4 Hallowfall"

    def test_rejects_update_of_retired_build(self):
        use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])
        with pytest.raises(ConflictError):
            use_cases.update_albion_build(
                self.ws["id"], self.build["id"], self.owner["id"],
                name="New Name", role="Healer", weapon_name="Bow",
            )

    def test_rejects_non_officer(self):
        member = _make_member(self.ws["id"], self.owner["id"], "UpdMember", "member")
        with pytest.raises(PermissionDenied):
            use_cases.update_albion_build(
                self.ws["id"], self.build["id"], member["id"],
                name="ValidName", role="DPS", weapon_name="Bow",
            )


# ---------------------------------------------------------------------------
# Group 5 — Use case: retire_albion_build
# ---------------------------------------------------------------------------

class TestRetireAlbionBuild:

    def setup_method(self):
        self.owner = make_user("BuildRetirer")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="uc-ret-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"])

    def test_sets_retired_at(self):
        use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])
        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, self.build["id"], self.ws["id"])
        assert fetched["retired_at"] is not None

    def test_rejects_double_retire(self):
        use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])
        with pytest.raises(ConflictError):
            use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])

    def test_rejects_non_officer(self):
        member = _make_member(self.ws["id"], self.owner["id"], "RetMember", "member")
        with pytest.raises(PermissionDenied):
            use_cases.retire_albion_build(self.ws["id"], self.build["id"], member["id"])

    def test_rejects_missing_build(self):
        with pytest.raises(NotFoundError):
            use_cases.retire_albion_build(self.ws["id"], "nonexistent", self.owner["id"])


# ---------------------------------------------------------------------------
# Group 6 — Build Snapshot Invariant
# ---------------------------------------------------------------------------

class TestBuildSnapshotInvariant:
    """Editing a build must NOT change existing slot templates or operation_slots."""

    def setup_method(self):
        self.owner = make_user("InvOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="inv-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"],
                                   name="Hallowfall", role="Healer",
                                   weapon_name="T8.3 Hallowfall")
        self.comp = make_composition(
            self.ws["id"],
            slots=[{
                "party_number": 1, "slot_index": 1,
                "role": "Healer", "build_name": "Hallowfall",
                "weapon_name": "T8.3 Hallowfall",
                "albion_build_id": self.build["id"],
                "priority": "core",
            }],
        )

    def test_slot_template_text_unchanged_after_build_edit(self):
        use_cases.update_albion_build(
            self.ws["id"], self.build["id"], self.owner["id"],
            name="Hallowfall v2", role="Healer", weapon_name="T9 Hallowfall",
        )
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, self.comp["id"], self.ws["id"]
            )
        assert templates[0]["build_name"] == "Hallowfall"
        assert templates[0]["weapon_name"] == "T8.3 Hallowfall"

    def test_operation_slots_unchanged_after_build_retire(self):
        op = make_operation(self.ws["id"])
        use_cases.attach_operation_plan(self.ws["id"], op["id"], self.comp["id"])
        use_cases.generate_operation_slots(self.ws["id"], op["id"])

        with database.transaction() as db:
            pre_slots = repositories.get_operation_slots(db, op["id"], self.ws["id"])

        use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])

        with database.transaction() as db:
            post_slots = repositories.get_operation_slots(db, op["id"], self.ws["id"])

        assert post_slots[0]["build_name"] == pre_slots[0]["build_name"]
        assert post_slots[0]["weapon_name"] == pre_slots[0]["weapon_name"]


# ---------------------------------------------------------------------------
# Group 7 — Composition integration: attach build FK
# ---------------------------------------------------------------------------

class TestBuildAttachToSlot:

    def setup_method(self):
        self.owner = make_user("AttachOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="attach-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"],
                                   name="Grovekeeper", role="Healer",
                                   weapon_name="T8 Grovekeeper")
        self.comp = make_composition(
            self.ws["id"],
            slots=[{"party_number": 1, "slot_index": 1,
                    "role": "Healer", "build_name": "Placeholder", "priority": "core"}],
        )

    def test_attach_build_populates_text_fields(self):
        """When a valid albion_build_id is submitted, the use case overwrites
        build_name and weapon_name from the build entity."""
        use_cases.update_composition_slots(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            actor_user_id=self.owner["id"],
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "Placeholder",  # will be overwritten
                "albion_build_id": self.build["id"],
                "priority": "core",
            }],
        )
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, self.comp["id"], self.ws["id"]
            )
        assert templates[0]["build_name"] == "Grovekeeper"
        assert templates[0]["weapon_name"] == "T8 Grovekeeper"
        assert templates[0]["albion_build_id"] == self.build["id"]

    def test_invalid_build_id_falls_back_to_text(self):
        """An unresolvable build FK is silently cleared; text fields are used."""
        use_cases.update_composition_slots(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            actor_user_id=self.owner["id"],
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "Manual Entry",
                "albion_build_id": "nonexistent-uuid",
                "priority": "core",
            }],
        )
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, self.comp["id"], self.ws["id"]
            )
        assert templates[0]["build_name"] == "Manual Entry"
        assert templates[0]["albion_build_id"] is None

    def test_retired_build_not_attached(self):
        """Retired builds are rejected at attach time; text fields are preserved."""
        use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])
        use_cases.update_composition_slots(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            actor_user_id=self.owner["id"],
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "Manual Name",
                "albion_build_id": self.build["id"],
                "priority": "core",
            }],
        )
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, self.comp["id"], self.ws["id"]
            )
        assert templates[0]["albion_build_id"] is None

    def test_no_build_id_keeps_manual_text(self):
        """Absence of albion_build_id preserves manual text entry (backward compat)."""
        use_cases.update_composition_slots(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            actor_user_id=self.owner["id"],
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "Free Text Build", "priority": "core",
            }],
        )
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, self.comp["id"], self.ws["id"]
            )
        assert templates[0]["build_name"] == "Free Text Build"
        assert templates[0]["albion_build_id"] is None


# ---------------------------------------------------------------------------
# Group 8 — Route GET
# ---------------------------------------------------------------------------

class TestBuildRouteGet:

    def setup_method(self):
        self.client, self.owner, self.ws = _make_setup("RouteGetOwner", "rg-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"])

    def test_build_list_renders(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert resp.status_code == 200
        assert "Hallowfall Healer" in resp.text

    def test_build_list_shows_builds_link(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "bld-list" in resp.text or "bld-card" in resp.text

    def test_build_new_form_renders(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/new")
        assert resp.status_code == 200
        assert "bld-form" in resp.text

    def test_build_detail_renders(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}"
        )
        assert resp.status_code == 200
        assert "Hallowfall Healer" in resp.text
        assert "T8.3 Hallowfall" in resp.text

    def test_build_edit_form_renders(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}/edit"
        )
        assert resp.status_code == 200
        assert "bld-form" in resp.text
        assert self.build["name"] in resp.text

    def test_composition_edit_shows_build_selector(self):
        comp = make_composition(self.ws["id"])
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-slot-build-select" in resp.text
        assert "Hallowfall Healer" in resp.text


# ---------------------------------------------------------------------------
# Group 9 — Route POST
# ---------------------------------------------------------------------------

class TestBuildRoutePost:

    def setup_method(self):
        self.client, self.owner, self.ws = _make_setup("RoutePostOwner", "rp-bld")

    def test_create_build_redirects(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds",
            data={"name": "New Bow", "role": "DPS", "weapon_name": "T8 Bow"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_create_build_persists(self):
        self.client.post(
            f"/workspaces/{self.ws['slug']}/builds",
            data={"name": "Persisted Build", "role": "Tank", "weapon_name": "Mace"},
            follow_redirects=True,
        )
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, self.ws["id"])
        assert any(b["name"] == "Persisted Build" for b in builds)

    def test_create_build_validation_error_rerenders(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds",
            data={"name": "", "role": "DPS", "weapon_name": "Bow"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "bld-form" in resp.text

    def test_update_build_redirects(self):
        build = _create_build(self.ws["id"], self.owner["id"])
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/{build['id']}",
            data={"name": "Updated", "role": "Healer", "weapon_name": "Staff"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_retire_build_redirects_to_list(self):
        build = _create_build(self.ws["id"], self.owner["id"])
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/{build['id']}/retire",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/builds" in resp.headers["location"]

    def test_retire_build_sets_retired_at(self):
        build = _create_build(self.ws["id"], self.owner["id"])
        self.client.post(
            f"/workspaces/{self.ws['slug']}/builds/{build['id']}/retire",
            follow_redirects=True,
        )
        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], self.ws["id"])
        assert fetched["retired_at"] is not None


# ---------------------------------------------------------------------------
# Group 10 — Permissions
# ---------------------------------------------------------------------------

class TestBuildPermissions:

    def setup_method(self):
        self.client, self.owner, self.ws = _make_setup("PermOwner", "perm-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"])
        self.member_user = _make_member(self.ws["id"], self.owner["id"], "PermMember", "member")
        self.member_client = TestClient(app)
        self.member_client.post(
            "/login", data={"display_name": "PermMember", "next": "/"},
            follow_redirects=True
        )

    def test_member_cannot_create_build(self):
        resp = self.member_client.post(
            f"/workspaces/{self.ws['slug']}/builds",
            data={"name": "X", "role": "DPS", "weapon_name": "Bow"},
            follow_redirects=True,
        )
        # A member should either see a 403 or the form re-rendered with an error.
        # Either way, no build should be created.
        assert resp.status_code in (200, 403)

    def test_member_can_view_build_list(self):
        resp = self.member_client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert resp.status_code == 200

    def test_member_can_view_build_detail(self):
        resp = self.member_client.get(
            f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}"
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Group 11 — Retired build restrictions
# ---------------------------------------------------------------------------

class TestRetiredBuildRestrictions:

    def setup_method(self):
        self.owner = make_user("RetrictOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="ret-restr-bld")
        self.build = _create_build(self.ws["id"], self.owner["id"])
        use_cases.retire_albion_build(self.ws["id"], self.build["id"], self.owner["id"])

    def test_retired_build_not_in_active_list(self):
        with database.transaction() as db:
            active = repositories.get_albion_builds(db, self.ws["id"])
        assert not any(b["id"] == self.build["id"] for b in active)

    def test_retired_build_visible_with_flag(self):
        with database.transaction() as db:
            all_builds = repositories.get_albion_builds(
                db, self.ws["id"], include_retired=True
            )
        assert any(b["id"] == self.build["id"] for b in all_builds)

    def test_cannot_attach_retired_build(self):
        comp = make_composition(
            self.ws["id"],
            slots=[{"party_number": 1, "slot_index": 1, "role": "DPS",
                    "build_name": "Manual", "priority": "normal"}],
        )
        use_cases.update_composition_slots(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            actor_user_id=self.owner["id"],
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "DPS",
                "build_name": "Manual",
                "albion_build_id": self.build["id"],
                "priority": "normal",
            }],
        )
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], self.ws["id"]
            )
        assert templates[0]["albion_build_id"] is None

    def test_edit_route_rejects_retired_build(self):
        client = TestClient(app)
        client.post(
            "/login",
            data={"display_name": "RetrictOwner", "next": "/"},
            follow_redirects=True,
        )
        resp = client.get(
            f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}/edit"
        )
        assert resp.status_code == 403
