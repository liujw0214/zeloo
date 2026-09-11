"""i18n — lightweight internationalization for Zeloo.

This module
provides a simple YAML-based translation loader with lazy string
lookup and fallback to English.

Usage::

    from agent.i18n import gettext, set_language

    set_language("zh-CN")
    print(gettext("hello_world"))  # "你好，世界"

Language files are YAML in ``locales/``::

    locales/
    ├── en.yaml
    ├── zh-CN.yaml
    └── ...
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LANGUAGE = "en"
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

# Thread-local current language
_thread_local = threading.local()


def _get_language() -> str:
    """Get the current language for this thread."""
    return getattr(_thread_local, "language", _DEFAULT_LANGUAGE)


def set_language(lang: str) -> None:
    """Set the current language for this thread.

    Falls back to English if the language is not available.
    """
    if not _is_language_available(lang):
        logger.warning("Language '%s' not available, falling back to 'en'", lang)
        lang = _DEFAULT_LANGUAGE
    _thread_local.language = lang


def _is_language_available(lang: str) -> bool:
    """Check if a language file exists."""
    return (_LOCALES_DIR / f"{lang}.yaml").exists()


@lru_cache(maxsize=32)
def _load_language(lang: str) -> dict[str, Any]:
    """Load a language file. Returns empty dict if not found."""
    path = _LOCALES_DIR / f"{lang}.yaml"
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Failed to load language file %s", path)
        return {}


def gettext(key: str, **kwargs: Any) -> str:
    """Translate a key to the current language.

    Supports simple key substitution with ``{var}`` placeholders.
    Falls back to the English translation, then to the key itself.
    """
    lang = _get_language()
    translations = _load_language(lang)

    if key not in translations:
        # Fall back to English
        en_translations = _load_language(_DEFAULT_LANGUAGE)
        if key in en_translations:
            translations = en_translations
        else:
            return key

    value = translations[key]
    if not isinstance(value, str):
        return str(value)

    # Substitute placeholders
    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return value


def get_available_languages() -> list[str]:
    """Return a sorted list of available language codes."""
    if not _LOCALES_DIR.exists():
        return [_DEFAULT_LANGUAGE]
    langs = [
        p.stem
        for p in _LOCALES_DIR.glob("*.yaml")
        if p.stem != _DEFAULT_LANGUAGE
    ]
    return sorted([_DEFAULT_LANGUAGE] + langs)


# Alias for convenience
_ = gettext
