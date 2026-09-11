"""State-level exception types for zeloo_state subsystem."""

from __future__ import annotations


class ZelooStateError(Exception):
    """Base exception for all zeloo_state errors."""

    pass


class SchemaError(ZelooStateError):
    """Schema version mismatch or migration failure."""

    pass


class MigrationError(SchemaError):
    """Failed to apply a schema migration."""

    pass


class RepairError(ZelooStateError):
    """Database repair operation failed."""

    pass


class SessionNotFoundError(ZelooStateError):
    """Requested session does not exist."""

    pass


class MessageNotFoundError(ZelooStateError):
    """Requested message does not exist."""

    pass


class StateCorruptError(ZelooStateError):
    """Database is corrupt and cannot be read."""

    pass


class StateLockError(ZelooStateError):
    """Database is locked by another process."""

    pass


class MaintenanceError(ZelooStateError):
    """Maintenance task failed."""

    pass


class ValidationError(ZelooStateError):
    """Data validation failed."""

    pass


def format_state_error(exc: Exception) -> str:
    """Format a state exception for safe display (no internal paths or keys)."""
    name = type(exc).__name__.replace("Error", "").replace("State", "").replace(" Zeloo", "State")
    return f"[State/{name}] {exc}"
