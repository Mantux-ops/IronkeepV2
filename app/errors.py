"""
Shared domain error hierarchy.

Both domain modules and use cases raise these — never plain RuntimeError or
bare Exception — so callers can handle them uniformly.
"""


class IronkeepError(Exception):
    """Base class for all domain errors."""


class NotFoundError(IronkeepError):
    """Entity not found, or not visible in the current workspace."""


class ConflictError(IronkeepError):
    """Requested operation would violate a domain invariant (duplicate, wrong state)."""


class ValidationError(IronkeepError):
    """Input data failed domain validation."""


class WorkspaceBoundaryViolation(IronkeepError):
    """Attempted to reference an entity from a different GuildWorkspace."""


class AuthenticationRequired(IronkeepError):
    """No authenticated user is available for the request."""


class PermissionDenied(IronkeepError):
    """Authenticated user lacks permission for the requested action."""
