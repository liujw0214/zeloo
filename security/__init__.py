"""Security toolkit — unified scanning, SBOM, and policy orchestration.

Public sub-modules:

* :mod:`security.scanner` — orchestrator that combines secret, threat
  and output scanners behind a single ``SecurityScanner`` facade.
* :mod:`security.sbom` — CycloneDX / SPDX SBOM generator with optional
  vulnerability lookup.

For backwards compatibility, the legacy ``security.py`` module's
public symbols (``RateLimiter``, ``sanitize_input``, ``validate_output``,
``SecurityContext``, ``PolicyEngine``, …) are re-exported here so that
``from security import RateLimiter`` continues to work after the package
split.
"""

from __future__ import annotations

# Backwards-compatibility shim: legacy top-level ``security.py`` module.
# We import the *module* attribute (not submodule) and grab symbols from it.
import importlib.util as _importlib_util
import os as _os
import pathlib as _pathlib

_legacy_path = _pathlib.Path(__file__).resolve().parent.parent / "security_legacy.py"
if _legacy_path.exists():
    _spec = _importlib_util.spec_from_file_location(
        "security_legacy_compat", _legacy_path
    )
    if _spec is not None and _spec.loader is not None:
        import sys as _sys
        _legacy_mod = _importlib_util.module_from_spec(_spec)
        _sys.modules["security_legacy_compat"] = _legacy_mod  # register so dataclasses work
        _spec.loader.exec_module(_legacy_mod)
        for _name in dir(_legacy_mod):
            if not _name.startswith("_"):
                globals()[_name] = getattr(_legacy_mod, _name)

# New first-party scanner + SBOM exports
from security.scanner import (
    ScanFinding,
    ScanReport,
    ScanSeverity,
    SecurityScanner,
    scan_text,
)
from security.sbom import Dependency, SBOMGenerator

__all__ = [
    "Dependency",
    "SBOMGenerator",
    "ScanFinding",
    "ScanReport",
    "ScanSeverity",
    "SecurityScanner",
    "scan_text",
    # Re-exported from legacy security.py for backwards compatibility:
    "RateLimiter",
    "sanitize_input",
    "validate_output",
    "SecurityContext",
    "PolicyEngine",
    "ThreatPattern",
]
