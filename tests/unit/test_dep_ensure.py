"""Tests for ``zeloo_cli.dep_ensure`` — Hermes Agent parity bootstrap.

Covers:
* :func:`is_available` / :func:`missing_required` pure checks
* :func:`ensure_dependency` headless detection + auto-install dispatch
* :func:`find_install_script` repo-root probe
* :func:`stamp_install_method` / :func:`read_install_marker` round-trip
* :func:`doctor_report` structured output
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


# ──────────────────────────────────────────────────────────────────────
# Pure availability checks
# ──────────────────────────────────────────────────────────────────────


class TestIsAvailable:
    """``is_available`` returns True iff any of the dep's binaries is on PATH."""

    def test_python_binary_is_implicitly_available(self, monkeypatch) -> None:
        # The test runner itself is running on Python, so shutil.which
        # will find a `python` or `python3` binary on PATH.
        from zeloo_cli.dep_ensure import KNOWN_DEPS
        # We don't directly check Python (it's not in KNOWN_DEPS) —
        # use one of the real deps as a smoke test.
        from zeloo_cli.dep_ensure import is_available

        # Bash is on PATH in any POSIX runner; on Windows we skip.
        if sys.platform != "win32":
            assert is_available("bash") is True

    def test_unknown_dep_returns_false(self) -> None:
        from zeloo_cli.dep_ensure import is_available

        assert is_available("definitely-not-a-real-tool-xyz") is False

    def test_known_deps_keys(self) -> None:
        from zeloo_cli.dep_ensure import KNOWN_DEPS

        for name in ("ripgrep", "ffmpeg", "git", "node", "uv"):
            assert name in KNOWN_DEPS


class TestMissingRequired:
    def test_returns_only_missing(self) -> None:
        from zeloo_cli.dep_ensure import KNOWN_DEPS, is_available, missing_required

        # Build a candidate list mixing available + guaranteed-missing.
        available = [n for n, s in KNOWN_DEPS.items() if not s.optional and is_available(n)]
        # Pick a dep that's definitely missing.
        missing_candidate = next(
            (n for n, s in KNOWN_DEPS.items()
             if not s.optional and not is_available(n)),
            None,
        )
        if missing_candidate is None:
            pytest.skip("All optional deps already present on this runner")

        result = missing_required(missing_candidate)
        assert missing_candidate in result

    def test_empty_input(self) -> None:
        from zeloo_cli.dep_ensure import missing_required

        assert missing_required() == []


# ──────────────────────────────────────────────────────────────────────
# Headless context detection
# ──────────────────────────────────────────────────────────────────────


class TestHeadlessDetection:
    def setup_method(self) -> None:
        from zeloo_cli import dep_ensure

        self._mod = dep_ensure

    def teardown_method(self) -> None:
        # Restore module state in case any test patched it.
        self._mod._stdin_isatty = lambda: True

    def test_gateway_argv_is_headless(self) -> None:
        from zeloo_cli.dep_ensure import _is_headless_context

        # Pretend we are running ``zeloo gateway start``.
        self._mod._stdin_isatty = lambda: True  # force TTY
        assert _is_headless_context(["zeloo", "gateway", "start"]) is True

    def test_cron_argv_is_headless(self) -> None:
        from zeloo_cli.dep_ensure import _is_headless_context

        self._mod._stdin_isatty = lambda: True
        assert _is_headless_context(["zeloo", "cron", "list"]) is True

    def test_doctor_argv_is_headless(self) -> None:
        from zeloo_cli.dep_ensure import _is_headless_context

        self._mod._stdin_isatty = lambda: True
        assert _is_headless_context(["zeloo", "doctor", "--fix"]) is True

    def test_non_tty_is_headless(self) -> None:
        from zeloo_cli.dep_ensure import _is_headless_context

        self._mod._stdin_isatty = lambda: False
        assert _is_headless_context(["zeloo", "chat"]) is True

    def test_interactive_chat_is_not_headless(self) -> None:
        from zeloo_cli.dep_ensure import _is_headless_context

        self._mod._stdin_isatty = lambda: True
        assert _is_headless_context(["zeloo", "chat", "-q", "hello"]) is False

    def test_non_interactive_flag_short_circuits(self) -> None:
        from zeloo_cli.dep_ensure import _is_headless_context

        self._mod._stdin_isatty = lambda: True
        assert _is_headless_context(["zeloo", "chat", "--non-interactive"]) is True
        assert _is_headless_context(["zeloo", "chat", "-y"]) is True


# ──────────────────────────────────────────────────────────────────────
# Install-method stamp
# ──────────────────────────────────────────────────────────────────────


class TestStampInstallMethod:
    def test_round_trip(self, tmp_path: Path) -> None:
        from zeloo_cli.dep_ensure import read_install_marker, stamp_install_method

        stamp_install_method(
            "git",
            home=tmp_path,
            extra={"ref_kind": "branch", "ref_value": "main"},
        )
        marker = tmp_path / ".install_method"
        assert marker.exists()
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["kind"] == "git"
        assert payload["ref_value"] == "main"

        # Round-trip via the reader.
        back = read_install_marker(home=tmp_path)
        assert back["kind"] == "git"
        assert back["ref_value"] == "main"

    def test_pip_kind(self, tmp_path: Path) -> None:
        from zeloo_cli.dep_ensure import stamp_install_method

        stamp_install_method("pip", home=tmp_path, extra={"wheel": "zeloo-0.16.0"})
        payload = json.loads((tmp_path / ".install_method").read_text(encoding="utf-8"))
        assert payload["kind"] == "pip"
        assert payload["wheel"] == "zeloo-0.16.0"

    def test_missing_marker_returns_empty_dict(self, tmp_path: Path) -> None:
        from zeloo_cli.dep_ensure import read_install_marker

        assert read_install_marker(home=tmp_path) == {}

    def test_corrupt_marker_returns_empty_dict(self, tmp_path: Path) -> None:
        from zeloo_cli.dep_ensure import read_install_marker

        (tmp_path / ".install_method").write_text("{not json", encoding="utf-8")
        assert read_install_marker(home=tmp_path) == {}


# ──────────────────────────────────────────────────────────────────────
# Install-script discovery
# ──────────────────────────────────────────────────────────────────────


class TestFindInstallScript:
    def test_git_marker_finds_repo_script(self, tmp_path: Path, monkeypatch) -> None:
        # Synthesize a repo layout: tmp_path/z {cli.py, zeloo_cli/,
        # install.ps1, install.sh} + tmp_path/z/.install_method marker.
        repo = tmp_path / "fake-repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "zeloo_cli").mkdir()
        (repo / "cli.py").touch()
        if sys.platform == "win32":
            (repo / "install.ps1").write_text("# stub", encoding="utf-8")
        else:
            (repo / "install.sh").write_text("# stub", encoding="utf-8")

        from zeloo_cli import dep_ensure

        monkeypatch.setattr(dep_ensure, "_find_repo_root", lambda: repo)

        path, kind = dep_ensure.find_install_script(kind="git")
        assert path is not None
        assert kind == "git"
        assert path.exists()

    def test_pip_marker_returns_none(self) -> None:
        from zeloo_cli.dep_ensure import find_install_script

        path, kind = find_install_script(kind="pip")
        assert path is None
        assert kind == "pip"


# ──────────────────────────────────────────────────────────────────────
# ensure_dependency
# ──────────────────────────────────────────────────────────────────────


class TestEnsureDependency:
    def test_returns_true_when_already_available(self) -> None:
        from zeloo_cli import dep_ensure

        # Pick the first dep we can guarantee is on PATH.
        for name, spec in dep_ensure.KNOWN_DEPS.items():
            if not spec.optional and dep_ensure.is_available(name):
                assert dep_ensure.ensure_dependency(name, interactive=False) is True
                return
        pytest.skip("No guaranteed-available dep on this runner")

    def test_unknown_dep_raises_keyerror(self) -> None:
        from zeloo_cli.dep_ensure import ensure_dependency

        with pytest.raises(KeyError):
            ensure_dependency("not-a-real-dep")

    def test_headless_no_script_returns_false(self, monkeypatch) -> None:
        from zeloo_cli import dep_ensure

        # Force headless + pretend the script is missing.
        monkeypatch.setattr(dep_ensure, "_stdin_isatty", lambda: False)
        monkeypatch.setattr(dep_ensure, "find_install_script", lambda: (None, None))
        # Use a synthetic dep name that is definitely missing.
        monkeypatch.setitem(
            dep_ensure.KNOWN_DEPS,
            "test-fake-dep",
            dep_ensure.DepSpec(
                name="test-fake-dep",
                binary="test-fake-dep-binary",
                purpose="synthetic",
            ),
        )
        assert dep_ensure.ensure_dependency(
            "test-fake-dep", interactive=True,
        ) is False


# ──────────────────────────────────────────────────────────────────────
# Doctor report
# ──────────────────────────────────────────────────────────────────────


class TestDoctorReport:
    def test_includes_all_deps(self) -> None:
        from zeloo_cli.dep_ensure import KNOWN_DEPS, doctor_report

        report = doctor_report(include_optional=True)
        assert set(report.keys()) == set(KNOWN_DEPS.keys())

    def test_excludes_optional_when_requested(self) -> None:
        from zeloo_cli.dep_ensure import KNOWN_DEPS, doctor_report

        report = doctor_report(include_optional=False)
        for name in report:
            assert not KNOWN_DEPS[name].optional

    def test_each_entry_has_expected_keys(self) -> None:
        from zeloo_cli.dep_ensure import doctor_report

        report = doctor_report(include_optional=False)
        for name, info in report.items():
            assert "available" in info
            assert "purpose" in info
            assert "binary" in info
            assert isinstance(info["available"], bool)


# ──────────────────────────────────────────────────────────────────────
# Integration: install --repair stamps the marker
# ──────────────────────────────────────────────────────────────────────


class TestInstallRepairStampsMarker:
    def test_marker_created_after_install(self, tmp_path: Path, monkeypatch) -> None:
        """``zeloo install`` stamps ``.install_method`` next to the home dir.

        ``install.py`` uses :func:`Path.home() / ".Zeloo"` directly so we
        redirect via :func:`monkeypatch.chdir` (which affects
        :func:`Path.home`) instead of trying to swap the env var.
        """
        # Make ``Path.home()`` resolve into the tmp dir so the install
        # command's hard-coded ``Path.home() / ".Zeloo"`` lands there.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("ZELOO_HOME", str(tmp_path / ".Zeloo"))

        # Patch Path.home globally for the duration of the test.
        import pathlib
        original_home = pathlib.Path.home
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))

        from zeloo_cli.subcommands.install import InstallCmd

        # Non-repair path runs the stamp.
        ns = type("A", (), {"repair": False, "minimal": True})()
        cmd = InstallCmd()
        rc = cmd.run(ns)
        assert rc == 0

        marker = tmp_path / ".Zeloo" / ".install_method"
        assert marker.exists(), f"expected marker at {marker}"
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["kind"] == "git"
        assert payload["source"] == "zeloo install"


# ──────────────────────────────────────────────────────────────────────
# install.ps1 / install.sh PowerShell / Bash syntax validation
# ──────────────────────────────────────────────────────────────────────


class TestInstallScriptSyntax:
    @pytest.mark.skipif(sys.platform != "win32" or shutil.which("powershell") is None, reason="Windows + PowerShell only")
    def test_install_ps1_parses_without_errors(self, tmp_path: Path) -> None:
        """install.ps1 must parse without errors in PS 5.1 (Windows PowerShell).

        We use the System.Management.Automation.Language.Parser API to check
        for parse errors without actually running the script.  The key issues
        this guards against:

        * Backtick chars inside double-quoted strings breaking the string
          terminator (the `` `" `` escape sequence).
        * ``$(...)`` sub-expressions inside ``param()`` defaults triggering
          a PS 5.1 parser bug.
        * Function call before definition causing CommandNotFoundError at
          runtime.
        """
        import subprocess

        install_ps1 = (
            Path(__file__).resolve().parent.parent.parent
            / "install.ps1"
        )
        ps1_escaped = str(install_ps1).replace("{", "{{").replace("}", "}}")
        ps_code = (
            "$ErrorActionPreference = 'SilentlyContinue'\n"
            "$t = $null; $e = $null\n"
            "[void][System.Management.Automation.Language.Parser]::ParseFile(\n"
            "    '{path}',\n"
            "    [ref]$t,\n"
            "    [ref]$e\n"
            ")\n"
            "if ($e) {{\n"
            "    foreach ($err in $e) {{\n"
            "        $ext = $err.Extent\n"
            "        Write-Host ('L' + $ext.StartLineNumber + ':' + $ext.StartColumnNumber + ' ' + $err.Message)\n"
            "    }}\n"
            "    exit 1\n"
            "}} else {{\n"
            "    Write-Host 'PARSE_OK'\n"
            "    exit 0\n"
            "}}\n"
        ).format(path=ps1_escaped)

        check_script = tmp_path / "_ps_parse_check.ps1"
        check_script.write_text(ps_code, encoding="utf-8")

        powershell_exe = shutil.which("powershell") or shutil.which("powershell.exe")
        if not powershell_exe:
            pytest.skip("powershell executable not found")
        result = subprocess.run(
            [
                powershell_exe,
                "-ExecutionPolicy", "Bypass",
                "-NoProfile",
                "-File", str(check_script),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            "install.ps1 has parse errors:\nstdout={}\nstderr={}".format(
                result.stdout, result.stderr
            )
        )
        assert "PARSE_OK" in result.stdout, result.stdout

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
    def test_install_sh_passes_bash_n(self) -> None:
        """install.sh must pass ``bash -n`` (parse only, no execution)."""
        import subprocess

        install_sh = (
            Path(__file__).resolve().parent.parent.parent
            / "install.sh"
        )
        result = subprocess.run(
            ["bash", "-n", str(install_sh)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"install.sh has syntax errors:\n{result.stderr}"
        )
