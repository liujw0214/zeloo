"""Zeloo state management subsystem.

Subpackages:
    schema       — Schema version management and migration
    repair       — Database self-diagnosis and repair
    maintenance  — Scheduled maintenance tasks
    errors       — State-level exception types
    sessions     — Session lifecycle (archive / merge / stats)
"""

import importlib.util
import sys
from pathlib import Path

from zeloo_state.errors import (
    MaintenanceError,
    MessageNotFoundError,
    MigrationError,
    RepairError,
    SchemaError,
    SessionNotFoundError,
    StateCorruptError,
    StateLockError,
    ValidationError,
    ZelooStateError,
)
from zeloo_state.maintenance import MaintenanceScheduler, MaintenanceStats
from zeloo_state.repair import RepairIssue, RepairResult, Severity, StateRepair
from zeloo_state.schema import (
    INDEXES,
    SCHEMA_VERSION,
    TABLES,
    ensure_schema,
    get_schema_version,
    migrate,
    validate_schema,
)
from zeloo_state.sessions import ArchiveEntry, SessionManager, SessionStats

_init_file = Path(__file__).resolve()
_root_mod_path = _init_file.parents[1] / "zeloo_state.py"

if _root_mod_path.exists():
    _spec = importlib.util.spec_from_file_location("zeloo_state._root", str(_root_mod_path))
    assert _spec is not None, f"Could not load spec for {_root_mod_path}"
    _root_mod = importlib.util.module_from_spec(_spec)
    sys.modules["zeloo_state._root"] = _root_mod
    _spec.loader.exec_module(_root_mod)  # type: ignore[union-attr]
    SessionDB: type = _root_mod.SessionDB
    set_state_home_override = _root_mod.set_state_home_override
else:
    class SessionDB:  # type: ignore[no-redef]
        """SQLite backend unavailable."""
        pass

__all__ = [
    "SCHEMA_VERSION",
    "TABLES",
    "INDEXES",
    "ensure_schema",
    "get_schema_version",
    "migrate",
    "validate_schema",
    "StateRepair",
    "RepairIssue",
    "RepairResult",
    "Severity",
    "MaintenanceScheduler",
    "MaintenanceStats",
    "ZelooStateError",
    "SessionDB",
    "set_state_home_override",
    "SchemaError",
    "MigrationError",
    "RepairError",
    "SessionNotFoundError",
    "MessageNotFoundError",
    "StateCorruptError",
    "StateLockError",
    "ValidationError",
    "MaintenanceError",
    "SessionManager",
    "SessionStats",
    "ArchiveEntry",
]
