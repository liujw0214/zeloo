"""Structured logging — JSON output + automatic trace_id correlation."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

_RESET = "\x1b[0m"
_COLOURS: dict[str, str] = {
    "DEBUG": "\x1b[38;5;244m",
    "INFO": "\x1b[38;5;39m",
    "WARNING": "\x1b[38;5;214m",
    "ERROR": "\x1b[38;5;196m",
    "CRITICAL": "\x1b[38;5;201m",
}

# contextvars propagate through asyncio + copy_context() workers.
_global_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "Zeloo_global_trace_id", default=None
)


def set_global_trace_id(trace_id: str) -> None:
    """Set the process-wide default ``trace_id`` for subsequent records."""
    _global_trace_id.set(trace_id)


def get_global_trace_id() -> str | None:
    """Return the current global trace id (or ``None``)."""
    return _global_trace_id.get()


def clear_global_trace_id() -> None:
    """Reset the global trace id to ``None`` (test helper)."""
    _global_trace_id.set(None)


def new_trace_id() -> str:
    """Generate a fresh 32-char hex trace id."""
    return uuid.uuid4().hex


class JSONFormatter(logging.Formatter):
    """Render :class:`logging.LogRecord` as single-line JSON."""

    STANDARD_FIELDS: ClassVar[set[str]] = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def __init__(
        self,
        include_trace_id: bool = True,
        static_fields: dict | None = None,
        timestamp_field: str = "timestamp",
    ) -> None:
        super().__init__()
        self._include_trace_id = include_trace_id
        self._static_fields: dict[str, Any] = dict(static_fields or {})
        self._timestamp_field = timestamp_field

    def format(self, record: logging.LogRecord) -> str:
        """Render *record* as a JSON string."""
        payload: dict[str, Any] = {
            self._timestamp_field: datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = getattr(record, "trace_id", None) or get_global_trace_id()
        if self._include_trace_id and trace_id:
            payload["trace_id"] = trace_id
        span_id = getattr(record, "span_id", None)
        if span_id:
            payload["span_id"] = span_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        payload["source"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }
        for key, value in record.__dict__.items():
            if key in self.STANDARD_FIELDS or key.startswith("_"):
                continue
            if key in payload or key in ("trace_id", "span_id"):
                continue
            payload[key] = _safe(value)
        payload.update(self._static_fields)
        return json.dumps(payload, default=_safe, ensure_ascii=False)


class ConsoleColorFormatter(logging.Formatter):
    """Compact colourised formatter for interactive terminals."""

    def __init__(self, use_color: bool | None = None) -> None:
        super().__init__()
        if use_color is None:
            use_color = sys.stderr.isatty()
        self._use_color = bool(use_color)

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        if self._use_color and level in _COLOURS:
            level_str = f"{_COLOURS[level]}{level:<8}{_RESET}"
        else:
            level_str = f"{level:<8}"
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%H:%M:%S"
        )
        trace_id = getattr(record, "trace_id", None) or get_global_trace_id()
        trace_part = f" trace={trace_id[:8]}" if trace_id else ""
        extras: list[str] = []
        for key, value in record.__dict__.items():
            if key in JSONFormatter.STANDARD_FIELDS or key.startswith("_"):
                continue
            if key in ("trace_id", "span_id"):
                continue
            extras.append(f"{key}={value!r}")
        extra_str = " " + " ".join(extras) if extras else ""
        out = f"{ts} {level_str} {record.name}{trace_part}: {record.getMessage()}{extra_str}"
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        return out


class StructuredLogger:
    """Logger with structured fields + automatic trace_id injection."""

    def __init__(
        self,
        name: str,
        level: int = logging.INFO,
        output_file: Path | None = None,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._name = name
        self._level = level
        self._extra_fields: dict[str, Any] = {}
        self._trace_id: str | None = None
        self._lock = threading.Lock()
        if output_file is not None:
            self._attach_file_handler(Path(output_file))

    def set_level(self, level: int) -> None:
        """Change the minimum emit level for this logger."""
        self._level = level
        self._logger.setLevel(level)

    def get_level(self) -> int:
        """Return the current minimum emit level."""
        return self._level

    def set_trace_id(self, trace_id: str) -> None:
        """Pin a per-logger trace_id overriding the global value."""
        self._trace_id = trace_id

    def clear_trace_id(self) -> None:
        """Remove the per-logger trace override."""
        self._trace_id = None

    def with_fields(self, **fields: Any) -> StructuredLogger:
        """Return a new logger that auto-adds *fields* to every record."""
        child = StructuredLogger.__new__(StructuredLogger)
        child._logger = self._logger
        child._name = self._name
        child._level = self._level
        child._extra_fields = {**self._extra_fields, **fields}
        child._trace_id = self._trace_id
        child._lock = self._lock
        return child

    def _log(self, level: int, message: str, fields: dict[str, Any]) -> None:
        extra: dict[str, Any] = dict(self._extra_fields)
        extra.update(fields or {})
        if self._trace_id:
            extra.setdefault("trace_id", self._trace_id)
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **fields: Any) -> None:
        """Emit a DEBUG record with structured fields."""
        self._log(logging.DEBUG, message, fields)

    def info(self, message: str, **fields: Any) -> None:
        """Emit an INFO record with structured fields."""
        self._log(logging.INFO, message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        """Emit a WARNING record with structured fields."""
        self._log(logging.WARNING, message, fields)

    def error(self, message: str, **fields: Any) -> None:
        """Emit an ERROR record with structured fields."""
        self._log(logging.ERROR, message, fields)

    def critical(self, message: str, **fields: Any) -> None:
        """Emit a CRITICAL record with structured fields."""
        self._log(logging.CRITICAL, message, fields)

    def _attach_file_handler(self, path: Path) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            for existing in self._logger.handlers:
                if (
                    isinstance(existing, logging.FileHandler)
                    and Path(existing.baseFilename) == path
                ):
                    return
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(JSONFormatter())
            self._logger.addHandler(handler)

    @property
    def underlying(self) -> logging.Logger:
        """Return the wrapped stdlib logger (escape hatch)."""
        return self._logger


_loggers: dict[str, StructuredLogger] = {}
_loggers_lock = threading.Lock()
_configured = False


def get_structured_logger(name: str) -> StructuredLogger:
    """Return a module-scoped :class:`StructuredLogger` (cached per name)."""
    with _loggers_lock:
        existing = _loggers.get(name)
        if existing is not None:
            return existing
        logger = StructuredLogger(name=name)
        _loggers[name] = logger
        return logger


def configure_structured_logging(
    level: int = logging.INFO,
    json_output: bool = True,
    output_file: Path | None = None,
    static_fields: dict | None = None,
) -> None:
    """One-shot root configuration (console + optional JSON file)."""
    global _configured
    root = logging.getLogger()
    root.setLevel(level)
    formatter: logging.Formatter = (
        JSONFormatter(include_trace_id=True, static_fields=static_fields)
        if json_output else ConsoleColorFormatter()
    )
    with _loggers_lock:
        for handler in list(root.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                root.removeHandler(handler)
        stream_handler = logging.StreamHandler(stream=sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
        if output_file is not None:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(output_file, encoding="utf-8")
            file_handler.setFormatter(
                JSONFormatter(include_trace_id=True, static_fields=static_fields)
            )
            root.addHandler(file_handler)
        _configured = True


def is_configured() -> bool:
    """Return ``True`` if :func:`configure_structured_logging` ran."""
    return _configured


def _safe(value: Any) -> Any:
    """Make *value* JSON-serializable in a defensive way."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(_safe(v) for v in value)
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


__all__ = [
    "ConsoleColorFormatter", "JSONFormatter", "StructuredLogger",
    "clear_global_trace_id", "configure_structured_logging",
    "get_global_trace_id", "get_structured_logger", "is_configured",
    "new_trace_id", "set_global_trace_id",
]
