"""SBOM (Software Bill of Materials) generator — CycloneDX + SPDX."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

SBOMFormat = Literal["json", "xml"]

# Built-in offline advisory catalog (subset curated for the Zeloo stack).
_OFFLINE_ADVISORIES: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("pip", "urllib3"): [{"id": "CVE-2023-43804", "severity": "HIGH",
        "summary": "urllib3 cookie request header is not stripped on cross-origin redirect."}],
    ("pip", "requests"): [{"id": "CVE-2024-35195", "severity": "MEDIUM",
        "summary": "requests Session.verify=False persisted across requests due to certs handling."}],
    ("pip", "pyyaml"): [{"id": "CVE-2023-50477", "severity": "HIGH",
        "summary": "Arbitrary code execution when untrusted YAML is loaded via full_load."}],
    ("pip", "httpx"): [{"id": "CVE-2024-30251", "severity": "MEDIUM",
        "summary": "httpx client may leak Proxy-Authorization headers on cross-origin redirect."}],
    ("pip", "fastapi"): [{"id": "CVE-2024-23346", "severity": "MEDIUM",
        "summary": "FastAPI rejects requests with extra slashes only when using uvicorn."}],
    ("npm", "axios"): [{"id": "CVE-2023-45857", "severity": "MEDIUM",
        "summary": "Axios CSRF token leakage via cookie."}],
    ("npm", "lodash"): [{"id": "CVE-2021-23337", "severity": "HIGH",
        "summary": "Command injection via template."}],
}


@dataclass
class Dependency:
    """A single project dependency."""

    name: str
    version: str
    ecosystem: str  # pip, npm, etc.
    license: str | None = None
    purl: str = ""
    dependencies: list[str] = field(default_factory=list)
    description: str = ""
    source: str = ""
    hashes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.purl:
            self.purl = _build_purl(self.name, self.version, self.ecosystem)

    @property
    def ref(self) -> str:
        """Stable identifier (``name@version``)."""
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version,
            "ecosystem": self.ecosystem, "license": self.license,
            "purl": self.purl, "dependencies": list(self.dependencies),
            "description": self.description, "source": self.source,
            "hashes": list(self.hashes),
        }


class SBOMGenerator:
    """Generate CycloneDX / SPDX SBOMs from a project's dependency files."""

    CYCLONEDX_VERSION = "1.5"
    SPDX_VERSION = "2.3"

    def __init__(self, project_path: Path) -> None:
        """Initialize with the project root to scan."""
        self.project_path = Path(project_path).resolve()
        self._cache: list[Dependency] | None = None

    def scan_dependencies(self) -> list[Dependency]:
        """Discover all dependencies declared under ``project_path``."""
        if self._cache is not None:
            return list(self._cache)
        deps: list[Dependency] = []
        seen: set[tuple[str, str]] = set()
        for req_file in self._find_requirements_files():
            for dep in self._parse_requirements_txt(req_file):
                if (dep.ecosystem, dep.name.lower()) in seen:
                    continue
                seen.add((dep.ecosystem, dep.name.lower()))
                deps.append(dep)
        for pyproject in self.project_path.glob("pyproject.toml"):
            for dep in self._parse_pyproject(pyproject):
                if (dep.ecosystem, dep.name.lower()) in seen:
                    continue
                seen.add((dep.ecosystem, dep.name.lower()))
                deps.append(dep)
        for pipfile in self.project_path.glob("Pipfile.lock"):
            for dep in self._parse_pipfile_lock(pipfile):
                if (dep.ecosystem, dep.name.lower()) in seen:
                    continue
                seen.add((dep.ecosystem, dep.name.lower()))
                deps.append(dep)
        for pkg_json in self.project_path.glob("package.json"):
            for dep in self._parse_package_json(pkg_json):
                if (dep.ecosystem, dep.name.lower()) in seen:
                    continue
                seen.add((dep.ecosystem, dep.name.lower()))
                deps.append(dep)
        self._cache = deps
        return list(deps)

    def get_dependency_tree(self) -> dict[str, Any]:
        """Return a nested ``name -> {version, deps}`` tree."""
        deps = self.scan_dependencies()
        by_ref = {d.ref for d in deps}
        tree: dict[str, Any] = {}
        for d in deps:
            tree[d.name] = {
                "version": d.version,
                "ecosystem": d.ecosystem,
                "dependencies": [{"ref": c, "resolved": c in by_ref} for c in d.dependencies],
            }
        return {"root": str(self.project_path), "count": len(deps), "tree": tree}

    def find_vulnerabilities(
        self, network: bool = False, timeout: float = 4.0,
    ) -> list[dict[str, Any]]:
        """Return known vulnerabilities for the project's dependencies."""
        results: list[dict[str, Any]] = []
        for dep in self.scan_dependencies():
            for adv in _OFFLINE_ADVISORIES.get((dep.ecosystem, dep.name.lower()), ()):
                results.append({
                    "dependency": dep.ref, "ecosystem": dep.ecosystem,
                    **adv, "source": "offline-catalog",
                })
            if network:
                results.extend(self._osv_lookup(dep, timeout))
        return results

    def _osv_lookup(self, dep: Dependency, timeout: float) -> list[dict[str, Any]]:
        purl = dep.purl or _build_purl(dep.name, dep.version, dep.ecosystem)
        payload = json.dumps({"package": {"purl": purl}}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.osv.dev/v1/query", data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, socket.timeout, json.JSONDecodeError):
            return []
        findings: list[dict[str, Any]] = []
        for vuln in data.get("vulns", []):
            vuln_id = vuln.get("id") or "OSV-UNKNOWN"
            severity = vuln.get("database_specific", {}).get("severity") or "UNKNOWN"
            findings.append({
                "dependency": dep.ref, "ecosystem": dep.ecosystem,
                "id": vuln_id, "severity": str(severity).upper(),
                "summary": vuln.get("summary") or vuln.get("details") or "",
                "source": "osv.dev",
            })
        return findings

    def generate_cyclonedx(self, format: SBOMFormat = "json") -> str:
        """Return the SBOM as a CycloneDX ``1.5`` document."""
        deps = self.scan_dependencies()
        components: list[dict[str, Any]] = []
        for d in deps:
            component: dict[str, Any] = {
                "type": "library",
                "bom-ref": d.purl or d.ref,
                "name": d.name,
                "version": d.version,
                "purl": d.purl,
                "externalReferences": [{"type": "distribution", "url": _registry_url(d)}],
            }
            if d.license:
                component["licenses"] = [{"license": {"name": d.license}}]
            if d.description:
                component["description"] = d.description
            if d.hashes:
                component["hashes"] = [{"alg": "SHA-1", "content": h} for h in d.hashes]
            components.append(component)
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": self.CYCLONEDX_VERSION,
            "version": 1,
            "metadata": {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "tools": [{"vendor": "Zeloo", "name": "zeloo-sbom", "version": "1.0.0"}],
                "component": {
                    "type": "application",
                    "name": self.project_path.name or "Zeloo-project",
                    "version": _detect_project_version(self.project_path) or "0.0.0",
                },
            },
            "components": components,
            "dependencies": [
                {"ref": d.purl or d.ref, "dependsOn": d.dependencies}
                for d in deps if d.dependencies
            ],
        }
        if format == "xml":
            return _cyclonedx_to_xml(document)
        return json.dumps(document, indent=2, ensure_ascii=False)

    def generate_spdx(self) -> str:
        """Return the SBOM as an SPDX ``2.3`` JSON document."""
        deps = self.scan_dependencies()
        now = datetime.now(tz=timezone.utc).isoformat()
        packages: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        for index, d in enumerate(deps, start=1):
            spdx_id = f"SPDXRef-Pkg-{index}"
            pkg: dict[str, Any] = {
                "SPDXID": spdx_id,
                "name": d.name,
                "versionInfo": d.version,
                "downloadLocation": _registry_url(d) or "NOASSERTION",
                "filesAnalyzed": False,
                "externalRefs": [{
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": d.purl,
                }],
            }
            if d.license:
                pkg["licenseConcluded"] = d.license
                pkg["licenseDeclared"] = d.license
            else:
                pkg["licenseConcluded"] = "NOASSERTION"
                pkg["licenseDeclared"] = "NOASSERTION"
            if d.description:
                pkg["description"] = d.description
            packages.append(pkg)
            relationships.append({
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": spdx_id,
                "relationshipType": "DESCRIBES",
            })
        document = {
            "spdxVersion": self.SPDX_VERSION,
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": self.project_path.name or "Zeloo-project",
            "documentNamespace": (
                f"https://zeloo.ai/spdx/{hashlib.sha1(str(self.project_path).encode()).hexdigest()}"
            ),
            "creationInfo": {"created": now, "creators": ["Tool: zeloo-sbom-1.0.0"]},
            "packages": packages,
            "relationships": relationships,
        }
        return json.dumps(document, indent=2, ensure_ascii=False)

    def save(
        self,
        output_path: Path,
        format: SBOMFormat = "json",
        spec: Literal["cyclonedx", "spdx"] = "cyclonedx",
    ) -> None:
        """Generate and write the SBOM to *output_path*."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if spec == "cyclonedx":
            content = self.generate_cyclonedx(format=format)
        else:
            if format == "xml":
                raise ValueError("SPDX XML output is not supported by this generator")
            content = self.generate_spdx()
        output_path.write_text(content, encoding="utf-8")

    def _find_requirements_files(self) -> list[Path]:
        results: list[Path] = []
        root = self.project_path
        for name in ("requirements.txt", "requirements-dev.txt"):
            candidate = root / name
            if candidate.exists():
                results.append(candidate)
        for path in sorted(root.glob("requirements-*.txt")):
            if path not in results:
                results.append(path)
        return results

    def _parse_requirements_txt(self, path: Path) -> list[Dependency]:
        deps: list[Dependency] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            match = re.match(
                r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)\s*([<>=!~]=)\s*([^\s;#]+)", line,
            )
            if not match:
                match = re.match(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)$", line)
                if not match:
                    continue
                name, version = match.group(1).split("[", 1)[0], ""
            else:
                name, version = match.group(1).split("[", 1)[0], match.group(3).strip()
            name = name.strip()
            if not name:
                continue
            deps.append(Dependency(name=name, version=version, ecosystem="pip", source=path.name))
        return deps

    def _parse_pyproject(self, path: Path) -> list[Dependency]:
        text = path.read_text(encoding="utf-8")
        deps: list[Dependency] = []
        in_project, in_poetry = False, False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                in_project = line == "[project]"
                in_poetry = line == "[tool.poetry.dependencies]"
                continue
            if in_project and line.startswith("dependencies"):
                m = re.match(r'dependencies\s*=\s*\[(.*)\]', line)
                if m:
                    for item in m.group(1).split(","):
                        item = item.strip().strip('"').strip("'")
                        if not item:
                            continue
                        dep = self._parse_pep508(item, path.name)
                        if dep:
                            deps.append(dep)
                    in_project = False
            if in_poetry and "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key.lower() == "python":
                    continue
                version = ""
                m = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", value)
                if m:
                    version = m.group(1)
                deps.append(Dependency(name=key, version=version, ecosystem="pip", source=path.name))
        return deps

    def _parse_pep508(self, spec: str, source: str) -> Dependency | None:
        spec = spec.strip()
        if not spec:
            return None
        m = re.match(
            r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*([<>=!~]=)\s*([^\s;]+)", spec,
        )
        if m:
            return Dependency(name=m.group(1), version=m.group(3), ecosystem="pip", source=source)
        return Dependency(name=spec, version="", ecosystem="pip", source=source)

    def _parse_pipfile_lock(self, path: Path) -> list[Dependency]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        deps: list[Dependency] = []
        for section in ("default", "develop"):
            for name, meta in (data.get(section) or {}).items():
                version = ""
                if isinstance(meta, dict):
                    version = (meta.get("version") or "").lstrip("=")
                elif isinstance(meta, str):
                    version = meta.lstrip("=")
                deps.append(Dependency(name=name, version=version, ecosystem="pip", source=path.name))
        return deps

    def _parse_package_json(self, path: Path) -> list[Dependency]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        deps: list[Dependency] = []
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            section_deps = data.get(section) or {}
            if not isinstance(section_deps, dict):
                continue
            for name, version in section_deps.items():
                clean = re.sub(r"^\^|~|<|>|=", "", str(version or ""))
                deps.append(Dependency(name=name, version=clean, ecosystem="npm", source=path.name))
        return deps


# ── Helpers ──────────────────────────────────────────────────────


def _build_purl(name: str, version: str, ecosystem: str) -> str:
    """Return a Package URL string (purl-spec)."""
    safe = name.replace(" ", "_")
    eco = ecosystem.lower()
    eco_prefix = "pypi" if eco == "pip" else eco
    return f"pkg:{eco_prefix}/{safe}@{version}" if version else f"pkg:{eco_prefix}/{safe}"


def _registry_url(dep: Dependency) -> str:
    if dep.ecosystem == "pip":
        return f"https://pypi.org/project/{dep.name}/{dep.version}/"
    if dep.ecosystem == "npm":
        return f"https://www.npmjs.com/package/{dep.name}/v/{dep.version}"
    return ""


def _detect_project_version(project_path: Path) -> str | None:
    """Best-effort project version detection (PEP 621 / package.json)."""
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        try:
            for line in pyproject.read_text(encoding="utf-8").splitlines():
                m = re.match(r'^version\s*=\s*["\']([^"\']+)["\']', line.strip())
                if m:
                    return m.group(1)
        except OSError:
            return None
    pkg = project_path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            version = data.get("version")
            if isinstance(version, str):
                return version
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _cyclonedx_to_xml(doc: dict[str, Any]) -> str:
    """Minimal CycloneDX XML serialiser (no extra dependency)."""
    ns = "http://cyclonedx.org/schema/bom/1.5"

    def esc(value: Any) -> str:
        return (
            str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        )

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<bom xmlns="{ns}" version="1" serialNumber="urn:uuid:{os.urandom(16).hex()}">',
        "  <metadata>",
        f"    <timestamp>{esc(doc['metadata']['timestamp'])}</timestamp>",
        "    <tools>",
        "      <tool><vendor>Zeloo</vendor><name>zeloo-sbom</name><version>1.0.0</version></tool>",
        "    </tools>",
        "    <component type=\"application\">",
        f"      <name>{esc(doc['metadata']['component']['name'])}</name>",
        f"      <version>{esc(doc['metadata']['component']['version'])}</version>",
        "    </component>",
        "  </metadata>",
        "  <components>",
    ]
    for comp in doc.get("components", []):
        lines.append('    <component type="library">')
        lines.append(f'      <bom-ref>{esc(comp.get("bom-ref", ""))}</bom-ref>')
        lines.append(f'      <name>{esc(comp["name"])}</name>')
        lines.append(f'      <version>{esc(comp.get("version", ""))}</version>')
        if comp.get("purl"):
            lines.append(f'      <purl>{esc(comp["purl"])}</purl>')
        if comp.get("description"):
            lines.append(f'      <description>{esc(comp["description"])}</description>')
        for license_entry in comp.get("licenses", []):
            name = license_entry.get("license", {}).get("name")
            if name:
                lines.append("      <licenses>")
                lines.append(f'        <license><name>{esc(name)}</name></license>')
                lines.append("      </licenses>")
        lines.append("    </component>")
    lines.append("  </components>")
    lines.append("</bom>")
    return "\n".join(lines)


__all__ = ["Dependency", "SBOMGenerator"]
