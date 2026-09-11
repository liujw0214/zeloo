"""CLI / TUI skin engine — borrowed design from Hermes Agent.

A *skin* is a tiny key/value table that customises the visual
presentation of the CLI (ANSI colour, banner glyph, prompt symbol,
TUI accent colour) without changing the underlying behaviour. Skins
are loaded from a single ``skin.yaml`` file in the Zeloo home dir and
cached in-process so repeated ``zeloo`` invocations don't re-read the
file.

Why this is useful
------------------

* Operators brand multi-tenant deployments (different banner glyph
  per workspace, different accent colour per env)
* Power users can disable colours for ``script`` / ``CI`` contexts
  with one line: ``zeloo skin set colors.enabled false``
* The TUI and the CLI share the same skin name so they look
  consistent — a ``starlight`` skin produces a deep-blue prompt in
  the CLI and a deep-blue accent in the TUI

Built-in skins
--------------

* ``default`` — green prompt, ⚡ banner, neutral palette
* ``starlight`` — purple prompt, ⭐ banner (suitable for dark bg)
* ``plain`` — no colours, no banner glyphs (for ``script``/CI)

Custom skins live in ``~/.Zeloo/skins/<name>.yaml`` and are merged
on top of the default skin so the user only has to override the
keys they care about.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent.zeloo_constants import get_zeloo_home

logger = logging.getLogger(__name__)


# ── dataclasses ────────────────────────────────────────────────────


@dataclass
class Colors:
    """ANSI colour slots. Each is an ANSI 16-colour name or hex code."""

    enabled: bool = True
    prompt: str = "green"
    banner: str = "cyan"
    error: str = "red"
    warning: str = "yellow"
    success: str = "green"
    info: str = "blue"
    tool: str = "magenta"
    assistant: str = "cyan"


@dataclass
class Banner:
    """Top-of-screen identification."""

    glyph: str = "⚡"
    title: str = "Zeloo Agent"
    subtitle: str = "self-hosted AI runtime"


@dataclass
class Prompt:
    """REPL prompt rendering."""

    symbol: str = "❯"
    user: str = "green"
    assistant: str = "cyan"
    show_working: bool = True  # show a spinner glyph while the agent is running


@dataclass
class TuiAccent:
    """TUI accent colours — mirrored into :class:`zeloo_tui.app` at boot."""

    primary: str = "#4f46e5"
    secondary: str = "#22d3ee"
    user_bg: str = "#eef2ff"
    assistant_bg: str = "#f4f4f6"
    tool_call_bg: str = "#fef3c7"
    tool_result_bg: str = "#d1fae5"


@dataclass
class Skin:
    """A complete skin definition."""

    name: str = "default"
    colors: Colors = field(default_factory=Colors)
    banner: Banner = field(default_factory=Banner)
    prompt: Prompt = field(default_factory=Prompt)
    tui: TuiAccent = field(default_factory=TuiAccent)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "colors": asdict(self.colors),
            "banner": asdict(self.banner),
            "prompt": asdict(self.prompt),
            "tui": asdict(self.tui),
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skin:
        # Be lenient: extra keys are ignored, missing keys fall back
        # to the dataclass default. The ``colors`` / ``prompt`` / etc
        # blocks are optional, so we merge dicts with dataclass
        # defaults rather than replacing them outright.
        colors = Colors(**(data.get("colors") or {}))
        banner = Banner(**(data.get("banner") or {}))
        prompt = Prompt(**(data.get("prompt") or {}))
        tui = TuiAccent(**(data.get("tui") or {}))
        return cls(
            name=data.get("name", "default"),
            colors=colors,
            banner=banner,
            prompt=prompt,
            tui=tui,
            extra=data.get("extra") or {},
        )


# ── built-in skins ────────────────────────────────────────────────


BUILTIN_SKINS: dict[str, Skin] = {
    "default": Skin(name="default"),
    "plain": Skin(
        name="plain",
        colors=Colors(enabled=False),
        banner=Banner(glyph=">>", title="Zeloo", subtitle=""),
        prompt=Prompt(symbol=">"),
    ),
    "starlight": Skin(
        name="starlight",
        colors=Colors(
            enabled=True,
            prompt="magenta",
            banner="bright_magenta",
            error="bright_red",
            success="bright_green",
        ),
        banner=Banner(glyph="⭐", title="Zeloo", subtitle="(starlight skin)"),
        prompt=Prompt(symbol="✦"),
        tui=TuiAccent(primary="#a855f7", secondary="#06b6d4"),
    ),
    "solarized": Skin(
        name="solarized",
        colors=Colors(
            enabled=True,
            prompt="yellow",
            banner="bright_yellow",
            error="red",
            success="green",
            info="cyan",
        ),
        banner=Banner(glyph="☀", title="Zeloo", subtitle="(solarized skin)"),
        prompt=Prompt(symbol="$"),
        tui=TuiAccent(
            primary="#b58900",
            secondary="#268bd2",
            user_bg="#fdf6e3",
            assistant_bg="#eee8d5",
        ),
    ),
}


# ── loader + cache ───────────────────────────────────────────────


_skin_cache: Skin | None = None


def _user_skins_dir() -> Path:
    return get_zeloo_home() / "skins"


def _resolve_skin_path(name: str) -> Path:
    """Return the path to a skin definition; built-in if not user-overridden."""
    user_path = _user_skins_dir() / f"{name}.yaml"
    if user_path.is_file():
        return user_path
    # Built-in skins are inlined in this module — no file lookup needed.
    if name in BUILTIN_SKINS:
        return Path("<builtin>")
    return user_path  # may not exist; the caller handles the error


def _load_skin_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:  # noqa: BLE001
        logger.warning("Failed to load skin %s: %s", path, e)
        return {}


def load_skin(name: str | None = None) -> Skin:
    """Load a skin by name, falling back to ``zeloo_SKIN`` env / ``default``.

    Built-in skins win unless the user has a custom
    ``~/.Zeloo/skins/<name>.yaml`` overriding them. The result is
    cached for the lifetime of the process — call
    :func:`reset_skin_cache` from tests when you need a fresh read.
    """
    global _skin_cache
    if _skin_cache is not None and (_skin_cache.name == (name or "")):
        return _skin_cache
    target = name or os.environ.get("zeloo_SKIN") or "default"
    if target in BUILTIN_SKINS:
        skin = BUILTIN_SKINS[target]
        # If a user file exists, overlay it on top of the built-in.
        user_path = _user_skins_dir() / f"{target}.yaml"
        if user_path.is_file():
            data = _load_skin_file(user_path)
            skin = Skin.from_dict({**skin.to_dict(), **data, "name": target})
    else:
        # Unknown built-in name — try the user file.
        user_path = _user_skins_dir() / f"{target}.yaml"
        if not user_path.is_file():
            logger.warning("Unknown skin '%s'; using 'default'", target)
            skin = BUILTIN_SKINS["default"]
        else:
            data = _load_skin_file(user_path)
            skin = Skin.from_dict({**data, "name": target})
    _skin_cache = skin
    return skin


def reset_skin_cache() -> None:
    """Force the next :func:`load_skin` to re-read from disk."""
    global _skin_cache
    _skin_cache = None


# ── ANSI helpers ──────────────────────────────────────────────────


_ANSI_NAMES: dict[str, str] = {
    "black": "\x1b[30m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[37m",
    "bright_black": "\x1b[90m",
    "bright_red": "\x1b[91m",
    "bright_green": "\x1b[92m",
    "bright_yellow": "\x1b[93m",
    "bright_blue": "\x1b[94m",
    "bright_magenta": "\x1b[95m",
    "bright_cyan": "\x1b[96m",
    "bright_white": "\x1b[97m",
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "italic": "\x1b[3m",
    "underline": "\x1b[4m",
}


def _colorize(text: str, name: str, *, enabled: bool) -> str:
    """Wrap ``text`` in ANSI codes if ``enabled`` and ``name`` is known.

    The function is deliberately tolerant: unknown colour names pass
    through unmodified (no crash) so user-supplied skins don't break
    the boot sequence.
    """
    if not enabled:
        return text
    prefix = _ANSI_NAMES.get(name.lower(), "")
    if not prefix:
        return text
    return f"{prefix}{text}{_ANSI_NAMES['reset']}"


def render_banner(skin: Skin | None = None) -> str:
    """Return the ASCII banner line for the given (or current) skin."""
    s = skin or load_skin()
    parts = [s.banner.glyph, s.banner.title]
    if s.banner.subtitle:
        parts.append("— " + s.banner.subtitle)
    line = " ".join(parts)
    return _colorize(line, s.colors.banner, enabled=s.colors.enabled)


def render_prompt(skin: Skin | None = None) -> str:
    """Return the REPL prompt symbol, optionally coloured."""
    s = skin or load_skin()
    return _colorize(s.prompt.symbol + " ", s.colors.prompt, enabled=s.colors.enabled)


def render_status(level: str, message: str, skin: Skin | None = None) -> str:
    """Render a single status line with the level-appropriate colour.

    ``level`` is one of ``info`` / ``success`` / ``warning`` / ``error`` /
    ``tool`` / ``assistant``. Unknown levels are passed through
    uncoloured.
    """
    s = skin or load_skin()
    color = getattr(s.colors, level, "")
    return _colorize(message, color, enabled=s.colors.enabled)


# ── CLI surface ──────────────────────────────────────────────────


def _print_current_skin(skin: Skin) -> None:
    """Pretty-print the active skin in YAML form."""
    import json

    print(f"Active skin: {skin.name}")
    print(json.dumps(skin.to_dict(), indent=2))


def list_skins() -> list[dict[str, str]]:
    """List available skins — built-in + user-defined."""
    out: list[dict[str, str]] = []
    for name, s in BUILTIN_SKINS.items():
        out.append({"name": name, "source": "builtin", "title": s.banner.title})
    user_dir = _user_skins_dir()
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*.yaml")):
            out.append({"name": p.stem, "source": "user", "title": ""})
    return out


def set_skin_value(name: str, value: Any, *, skin_name: str = "default") -> Path:
    """Set a single skin value (CLI helper).

    The path is ``colors.prompt``, ``banner.glyph``, etc. — the same
    shape the YAML file uses. Returns the path that was written.
    """
    user_dir = _user_skins_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / f"{skin_name}.yaml"
    data: dict[str, Any] = {}
    if target.is_file():
        try:
            with open(target, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}
    # Walk the dot path: "colors.prompt" → data["colors"]["prompt"] = value
    parts = name.split(".")
    cur: dict[str, Any] = data
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value
    with open(target, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    reset_skin_cache()
    return target


__all__ = [
    "BUILTIN_SKINS",
    "Banner",
    "Colors",
    "Prompt",
    "Skin",
    "TuiAccent",
    "list_skins",
    "load_skin",
    "render_banner",
    "render_prompt",
    "render_status",
    "reset_skin_cache",
    "set_skin_value",
]
__all__ += ["_user_skins_dir", "_resolve_skin_path", "_colorize"]