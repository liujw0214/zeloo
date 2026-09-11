"""Plugins package — third-party extensions for Zeloo.

Place your plugin modules or packages here. Each plugin must define a
``register(registry, skills_manager)`` callable (optional) and may use
the ``@tool`` decorator from :mod:`tools.base` to register tools.
"""

from plugins.manager import PluginInfo, PluginManager

__all__ = ["PluginManager", "PluginInfo"]
