"""Plugin system using pluggy — auto-discover hook implementations.

Plugins can register new tools, modify behaviour, or respond to events.
Place ``.py`` files in ``~/.config/homelab-ai/plugins/`` or install them
via pip with the ``homelab_ai_plugin`` entry point.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import os
import sys
from pathlib import Path
from typing import Any, Callable

import pluggy

from homelab_ai.config import BASE_DIR, logger

# ---------------------------------------------------------------------------
# Hook specification
# ---------------------------------------------------------------------------

_hook = pluggy.HookspecMarker("homelab_ai")
_impl = pluggy.HookimplMarker("homelab_ai")


class HomelabAIHooks:
    """Hook definitions for homelab-ai plugins."""

    @_hook
    def homelab_ai_tool_registered(self, name: str, func: Callable, params_model: Any):
        """Called when a tool is registered.
        Return a (name, func, params_model) tuple to override or add a tool.
        """

    @_hook
    def homelab_ai_startup(self):
        """Called once during app startup.
        Use this for one-time initialisation.
        """

    @_hook
    def homelab_ai_before_query(self, user_input: str) -> str:
        """Called before every user query. Return modified input."""

    @_hook
    def homelab_ai_after_query(self, user_input: str, agent_response: str) -> str:
        """Called after every agent response. Return modified response."""


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------

PLUGIN_DIR = Path.home() / ".config" / "homelab-ai" / "plugins"
PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

_manager = pluggy.PluginManager("homelab_ai")
_manager.add_hookspecs(HomelabAIHooks)
_loaded = False  # can be reset to True to force re-discovery via reload_plugins()


def discover_plugins():
    """Scan plugin directories and entry points, register implementations."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    # 1. Folder-based plugins
    if PLUGIN_DIR.exists():
        for fpath in sorted(PLUGIN_DIR.glob("*.py")):
            if fpath.name.startswith("_"):
                continue
            mod_name = f"homelab_ai_plugin_{fpath.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, fpath)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = mod
                    spec.loader.exec_module(mod)
                    _register_impls(mod, str(fpath))
            except Exception as exc:
                logger.warning("Plugin load failed: %s — %s", fpath.name, exc)

    # 2. Entry-point plugins (pip-installed)
    try:
        for ep in importlib.metadata.entry_points(group="homelab_ai_plugin"):
            try:
                mod = ep.load()
                _register_impls(mod, ep.name)
            except Exception as exc:
                logger.warning("Plugin entry-point failed: %s — %s", ep.name, exc)
            else:
                logger.info("Plugin loaded: %s", ep.name)
    except Exception:
        pass

    # 3. Fire startup hook
    try:
        _manager.hook.homelab_ai_startup()
    except Exception as exc:
        logger.warning("Startup hook error: %s", exc)


def _register_impls(mod, source: str):
    """Scan a module for hook implementations and register them."""
    for name, obj in inspect.getmembers(mod):
        if inspect.isfunction(obj) and hasattr(obj, "_homelab_ai_hookimpl"):
            try:
                _manager.register(obj)
                logger.info("  hook registered: %s.%s (%s)", mod.__name__, name, source)
            except Exception as exc:
                logger.warning("  hook register failed: %s — %s", name, exc)
        elif inspect.isclass(obj):
            try:
                _manager.register(obj())
                logger.info("  class plugin registered: %s.%s (%s)", mod.__name__, name, source)
            except Exception as exc:
                logger.warning("  class plugin register failed: %s — %s", name, exc)


def reload_plugins() -> int:
    """Force re-discovery (call after installing/removing plugins)."""
    global _loaded
    # Clear plugin modules from sys.modules so they get re-imported
    for mod_name in list(sys.modules):
        if mod_name.startswith("homelab_ai_plugin_"):
            del sys.modules[mod_name]
    # Reset + re-discover
    _loaded = False
    discover_plugins()
    # Count how many were loaded
    count = 0
    if PLUGIN_DIR.exists():
        count = sum(1 for f in PLUGIN_DIR.glob("*.py") if not f.name.startswith("_"))
    return count


def get_plugin_manager() -> pluggy.PluginManager:
    return _manager


def apply_before_query(text: str) -> str:
    """Run all before_query hooks."""
    try:
        results = _manager.hook.homelab_ai_before_query(user_input=text)
        for r in results:
            if r and isinstance(r, str):
                text = r
    except Exception:
        pass
    return text


def apply_after_query(user_input: str, response: str) -> str:
    """Run all after_query hooks."""
    try:
        results = _manager.hook.homelab_ai_after_query(user_input=user_input, agent_response=response)
        for r in results:
            if r and isinstance(r, str):
                response = r
    except Exception:
        pass
    return response
