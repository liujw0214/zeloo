"""File operation tools.

On the local backend, all operations use Python's pathlib (cross-platform,
works on Windows / macOS / Linux). On docker/ssh backends, operations are
executed as shell commands so they run inside the remote environment.

Path safety
-----------

Every operation that accepts a filesystem path is checked against the
project-wide :class:`~tools.path_safety.PathSafetyPolicy`. The default
policy allows the user's home directory and the current working
directory, plus a built-in deny list (Windows/System32, /etc/shadow,
/proc/...).

Override the default policy via :func:`set_path_safety_policy`, or set
``zeloo_DISABLE_PATH_SAFETY=1`` in the environment to bypass all checks
(useful for tests / single-shot scripts / trusted operators).
"""

from __future__ import annotations

import logging
import os
import shlex
import threading
from pathlib import Path

from tools.base import tool
from tools.path_safety import PathSafetyPolicy, resolve_and_validate

logger = logging.getLogger(__name__)

_HEREDOC_MARKER = "zeloo_FILE_EOF"

# ── Path safety policy (module-level, configurable) ──────────────

_policy_lock = threading.RLock()
_default_policy: PathSafetyPolicy | None = None
_policy_disabled = False


def _build_default_policy() -> PathSafetyPolicy:
    """Build a sensible default policy: $HOME + CWD, built-in deny list."""
    extra: list[Path] = []
    try:
        cwd = Path.cwd()
        if cwd.is_dir():
            extra.append(cwd)
    except Exception:  # noqa: BLE001
        pass
    return PathSafetyPolicy.from_home(extra_roots=extra)


def get_path_safety_policy() -> PathSafetyPolicy:
    """Return the currently-active :class:`PathSafetyPolicy`.

    Lazily builds the default on first access. Thread-safe.
    """
    global _default_policy
    with _policy_lock:
        if _default_policy is None:
            _default_policy = _build_default_policy()
        return _default_policy


def set_path_safety_policy(policy: PathSafetyPolicy | None) -> None:
    """Replace the active policy (or reset to default with ``None``)."""
    global _default_policy, _policy_disabled
    with _policy_lock:
        if policy is None:
            _default_policy = None
            _policy_disabled = False
        else:
            _default_policy = policy
            _policy_disabled = False


def disable_path_safety() -> None:
    """Globally bypass path checks (tests / trusted operators)."""
    global _policy_disabled
    with _policy_lock:
        _policy_disabled = True


def enable_path_safety() -> None:
    """Re-enable path checks (used in tests after :func:`disable_path_safety`)."""
    global _policy_disabled
    with _policy_lock:
        _policy_disabled = False


# ── Output scanning (post-read secret redaction) ────────────────

# Backwards-compat aliases: file_tools originally exposed these names.
# They now delegate to tools.output_scan which is shared across tools.
from tools import output_scan as _output_scan  # noqa: E402, F401


def is_output_scan_enabled() -> bool:
    """Backwards-compat alias for :func:`tools.output_scan.output_scan_enabled`."""
    return _output_scan.output_scan_enabled()


def set_output_scan_enabled(enabled: bool) -> None:
    """Backwards-compat alias — delegates to the shared scanner."""
    _output_scan.set_output_scan_enabled(enabled)


def _scan_file_output(content: str, *, source: str) -> str:
    """Backwards-compat wrapper around :func:`scan_tool_output`."""
    return _output_scan.scan_tool_output(content, tool_name="file_read", source=source)


def _is_safety_enabled() -> bool:
    """Whether path safety is active (env var + module flag both honored)."""
    with _policy_lock:
        if _policy_disabled:
            return False
    if os.environ.get("zeloo_DISABLE_PATH_SAFETY", "").strip() in {"1", "true", "yes"}:
        return False
    return True


def _safe_check(path: str, require_existing_file: bool = False) -> tuple[bool, str]:
    """Validate *path* against the active policy.

    Args:
        path: User-supplied path string.
        require_existing_file: When True, the resolved path must exist
            and be a regular file. Used by ``file_read`` / ``file_edit``.

    Returns:
        ``(ok, message)`` — ``ok`` is True on success; ``message`` is
        either empty (success) or a human-readable error for the tool
        caller.
    """
    if not _is_safety_enabled():
        return True, ""

    policy = get_path_safety_policy()

    # We always require a real path for read/edit; for write we accept
    # non-existent (file_write creates new files).
    effective = policy
    if require_existing_file and not policy.require_real_path:
        from dataclasses import replace

        effective = replace(policy, require_real_path=True)

    result = resolve_and_validate(path, effective)
    if not result.is_safe:
        return False, f"Error: path blocked by safety policy ({result.reason}): {path}"
    if require_existing_file and not result.resolved.is_file():
        return False, f"Error: not a regular file: {path}"
    return True, ""


def _audit_file_event(
    kind: str,
    path: str,
    *,
    outcome: str = "ok",
    detail: dict[str, object] | None = None,
) -> None:
    """Best-effort write of a file operation to the audit log.

    Wrapped in try/except so a logging failure never breaks the tool.
    """
    try:
        from agent.audit_log import audit_event

        audit_event(
            kind,
            actor="tool:file",
            resource=path,
            outcome=outcome,
            detail=dict(detail or {}),
        )
    except Exception:  # noqa: BLE001
        # Audit must never break the runtime path.
        pass


def _get_backend():
    """Return the active terminal backend (falls back to local)."""
    try:
        from run_agent import _current_agent

        agent = _current_agent.get()
        if agent is not None:
            return agent.terminal_backend
    except Exception:
        pass
    from terminal.local import LocalBackend

    return LocalBackend()


def _is_local_backend() -> bool:
    """Return True if the active backend runs on the local machine."""
    from terminal.local import LocalBackend

    return isinstance(_get_backend(), LocalBackend)


def _run(cmd: str, timeout: int = 30) -> str:
    """Run a command through the backend and return combined output."""
    result = _get_backend().execute(cmd, timeout=timeout)
    output = result.stdout
    if result.stderr:
        output += ("\n" if output else "") + result.stderr
    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"
    return output


@tool(name="file_read", description="Read a file's contents", toolset="file")
def file_read(path: str, max_length: int = 10000) -> str:
    """Read a file and return its contents.

    Args:
        path: Path to the file to read.
        max_length: Maximum characters to return.
    """
    ok, err = _safe_check(path, require_existing_file=True)
    if not ok:
        _audit_file_event("file_read", path, outcome="blocked", detail={"reason": err})
        return err
    try:
        if _is_local_backend():
            file_path = Path(path).expanduser()
            if not file_path.is_file():
                return f"Error: File not found: {path}"
            content = file_path.read_text(encoding="utf-8", errors="replace")
        else:
            output = _run(f"cat {shlex.quote(path)} 2>/dev/null || echo 'FILE_NOT_FOUND'")
            if "FILE_NOT_FOUND" in output:
                return f"Error: File not found: {path}"
            content = output.rstrip("\n")
        if len(content) > max_length:
            content = content[:max_length] + "\n...[truncated]"
        content = _scan_file_output(content, source=path)
        _audit_file_event("file_read", path, outcome="ok", detail={"bytes": len(content)})
        return content
    except Exception as e:
        _audit_file_event("file_read", path, outcome="error", detail={"error": str(e)})
        return f"Error reading {path}: {e}"


@tool(name="file_write", description="Write content to a file", dangerous=True, toolset="file")
def file_write(path: str, content: str) -> str:
    """Write content to a file, overwriting if it exists.

    Args:
        path: Path to the file to write.
        content: Content to write.
    """
    ok, err = _safe_check(path, require_existing_file=False)
    if not ok:
        _audit_file_event("file_write", path, outcome="blocked", detail={"reason": err})
        return err
    try:
        if _is_local_backend():
            file_path = Path(path).expanduser()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            _audit_file_event(
                "file_write",
                path,
                outcome="ok",
                detail={"bytes": len(content)},
            )
            return f"File written: {path} ({len(content)} chars)"

        # Remote backend — quoted heredoc (Unix shell)
        parent = os.path.dirname(path) or "."
        cmd = (
            f"mkdir -p {shlex.quote(parent)} && "
            f"cat > {shlex.quote(path)} << '{_HEREDOC_MARKER}'\n"
            f"{content}\n"
            f"{_HEREDOC_MARKER}"
        )
        output = _run(cmd)
        if "exit code" in output:
            _audit_file_event("file_write", path, outcome="error", detail={"output": output[:200]})
            return f"Error writing {path}: {output.strip()}"
        _audit_file_event("file_write", path, outcome="ok", detail={"bytes": len(content)})
        return f"File written: {path} ({len(content)} chars)"
    except Exception as e:
        _audit_file_event("file_write", path, outcome="error", detail={"error": str(e)})
        return f"Error writing {path}: {e}"


@tool(
    name="file_edit",
    description="Replace a string in a file (find-and-replace edit)",
    dangerous=True,
    toolset="file",
)
def file_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Edit a file by replacing occurrences of old_string with new_string.

    Args:
        path: Path to the file to edit.
        old_string: The exact text to find.
        new_string: The text to replace it with.
        replace_all: If True, replace all occurrences; otherwise only the first.

    Returns a success message or an error. If old_string is not found,
    returns an error (no changes are made).
    """
    ok, err = _safe_check(path, require_existing_file=True)
    if not ok:
        _audit_file_event("file_edit", path, outcome="blocked", detail={"reason": err})
        return err
    try:
        if _is_local_backend():
            file_path = Path(path).expanduser()
            if not file_path.is_file():
                _audit_file_event(
                    "file_edit", path, outcome="error", detail={"reason": "not found"}
                )
                return f"Error: File not found: {path}"
            content = file_path.read_text(encoding="utf-8", errors="replace")

            if old_string not in content:
                _audit_file_event(
                    "file_edit", path, outcome="error", detail={"reason": "old_string not found"}
                )
                return f"Error: old_string not found in {path}"

            if replace_all:
                count = content.count(old_string)
                new_content = content.replace(old_string, new_string)
            else:
                count = 1
                new_content = content.replace(old_string, new_string, 1)

            file_path.write_text(new_content, encoding="utf-8")
            _audit_file_event(
                "file_edit", path, outcome="ok", detail={"replaced": count}
            )
            return f"Edited {path}: replaced {count} occurrence(s)"

        # Remote backend — use a Python one-liner for safe string replacement
        import json

        py_script = (
            "import sys,json;"
            "d=json.load(sys.stdin);"
            "p=d['p'];o=d['o'];n=d['n'];ra=d['ra'];"
            "c=open(p,encoding='utf-8',errors='replace').read();"
            "sys.exit('NOT_FOUND') if o not in c else None;"
            "cnt=c.count(o) if ra else 1;"
            "c=c.replace(o,n) if ra else c.replace(o,n,1);"
            "open(p,'w',encoding='utf-8').write(c);"
            "print(cnt)"
        )
        payload = json.dumps({"p": path, "o": old_string, "n": new_string, "ra": replace_all})
        cmd = f"echo {shlex.quote(payload)} | python3 -c {shlex.quote(py_script)}"
        output = _run(cmd)
        if "NOT_FOUND" in output:
            return f"Error: old_string not found in {path}"
        if "exit code" in output:
            return f"Error editing {path}: {output.strip()}"
        count = output.strip().splitlines()[-1] if output.strip() else "1"
        return f"Edited {path}: replaced {count} occurrence(s)"
    except Exception as e:
        return f"Error editing {path}: {e}"


@tool(name="file_list", description="List files in a directory", toolset="file")
def file_list(path: str = ".", show_hidden: bool = False) -> str:
    """List files and directories in a path.

    Args:
        path: Directory path to list.
        show_hidden: Include hidden files.
    """
    try:
        if _is_local_backend():
            dir_path = Path(path).expanduser()
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
            lines = []
            for entry in entries:
                if entry.name.startswith(".") and not show_hidden:
                    continue
                prefix = "/" if entry.is_dir() else " "
                lines.append(f"{prefix} {entry.name}")
            return "\n".join(lines) if lines else "(empty)"

        flag = "-A" if show_hidden else ""
        output = _run(f"ls -1 {flag} {shlex.quote(path)} 2>/dev/null || echo 'NOT_A_DIR'")
        if "NOT_A_DIR" in output:
            return f"Error: Not a directory: {path}"
        entries = [line for line in output.splitlines() if line.strip()]
        return "\n".join(sorted(entries)) if entries else "(empty)"
    except Exception as e:
        return f"Error listing {path}: {e}"


@tool(name="file_find", description="Find files by name pattern", toolset="file")
def file_find(path: str = ".", pattern: str = "*", max_results: int = 50) -> str:
    """Find files matching a glob pattern.

    Args:
        path: Directory to search in.
        pattern: Glob pattern (e.g. '*.py').
        max_results: Maximum number of results.
    """
    try:
        if _is_local_backend():
            import fnmatch

            base = Path(path).expanduser()
            matches = []
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if fnmatch.fnmatch(f, pattern):
                        matches.append(str(Path(root) / f))
                        if len(matches) > max_results:
                            break
                if len(matches) > max_results:
                    break
            if len(matches) > max_results:
                matches = matches[:max_results]
                matches.append("...[more results]")
            return "\n".join(matches) if matches else "(no matches)"

        output = _run(
            f"find {shlex.quote(path)} -name {shlex.quote(pattern)} "
            f"-type f 2>/dev/null | head -n {max_results + 1}"
        )
        entries = [line for line in output.splitlines() if line.strip()]
        if len(entries) > max_results:
            entries = entries[:max_results]
            entries.append("...[more results]")
        return "\n".join(entries) if entries else "(no matches)"
    except Exception as e:
        return f"Error finding files: {e}"


@tool(name="file_delete", description="Delete a file or directory", dangerous=True, toolset="file")
def file_delete(path: str) -> str:
    """Delete a file or directory.

    Args:
        path: Path to delete.
    """
    try:
        if _is_local_backend():
            import shutil

            target = Path(path).expanduser()
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return f"Deleted: {path}"

        output = _run(f"rm -rf {shlex.quote(path)} 2>&1")
        if "exit code" in output:
            return f"Error deleting {path}: {output.strip()}"
        return f"Deleted: {path}"
    except Exception as e:
        return f"Error deleting {path}: {e}"


@tool(name="file_move", description="Move/rename a file or directory", toolset="file")
def file_move(source: str, destination: str) -> str:
    """Move or rename a file/directory.

    Args:
        source: Source path.
        destination: Destination path.
    """
    try:
        if _is_local_backend():
            src = Path(source).expanduser()
            dst = Path(destination).expanduser()
            src.rename(dst)
            return f"Moved: {source} -> {destination}"

        output = _run(f"mv {shlex.quote(source)} {shlex.quote(destination)} 2>&1")
        if "exit code" in output:
            return f"Error moving {source}: {output.strip()}"
        return f"Moved: {source} -> {destination}"
    except Exception as e:
        return f"Error moving {source}: {e}"


@tool(name="file_copy", description="Copy a file or directory", toolset="file")
def file_copy(source: str, destination: str) -> str:
    """Copy a file or directory.

    Args:
        source: Source path.
        destination: Destination path.
    """
    try:
        if _is_local_backend():
            import shutil

            src = Path(source).expanduser()
            dst = Path(destination).expanduser()
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            return f"Copied: {source} -> {destination}"

        output = _run(f"cp -r {shlex.quote(source)} {shlex.quote(destination)} 2>&1")
        if "exit code" in output:
            return f"Error copying {source}: {output.strip()}"
        return f"Copied: {source} -> {destination}"
    except Exception as e:
        return f"Error copying {source}: {e}"
