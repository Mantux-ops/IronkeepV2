"""Workspace membership roles and capability checks."""

from __future__ import annotations

from app.errors import ValidationError

VALID_ROLES = frozenset({"owner", "officer", "member"})
MUTATOR_ROLES = frozenset({"owner", "officer"})
MEMBER_MANAGER_ROLES = frozenset({"owner", "officer"})


def validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValidationError(
            f"Invalid workspace role '{role}'. Must be one of: {sorted(VALID_ROLES)}"
        )


def can_mutate_workspace_operations(role: str) -> bool:
    return role in MUTATOR_ROLES


def can_submit_signup(role: str) -> bool:
    return role in VALID_ROLES


def can_manage_workspace_members(role: str) -> bool:
    return role in MEMBER_MANAGER_ROLES
