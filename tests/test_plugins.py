"""Tests for plugin_installer.py."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_validate_plugin_code_valid() -> None:
    from homelab_ai.plugin_installer import _validate_plugin_code
    code = 'from homelab_ai.plugin_manager import _impl\n@_impl\ndef homelab_ai_startup(): pass\n'
    ok, msg = _validate_plugin_code(code)
    assert ok is True
    assert msg == ""


def test_validate_plugin_code_no_hook() -> None:
    from homelab_ai.plugin_installer import _validate_plugin_code
    ok, msg = _validate_plugin_code('print("hello")')
    assert ok is False
    assert "hook marker" in msg


def test_validate_plugin_code_dangerous() -> None:
    from homelab_ai.plugin_installer import _validate_plugin_code
    code = 'from homelab_ai.plugin_manager import _impl\n@_impl\ndef f():\n    eval("1+1")\n'
    ok, msg = _validate_plugin_code(code)
    assert ok is False
    assert "Suspicious" in msg


def test_safe_filename() -> None:
    from homelab_ai.plugin_installer import _safe_filename
    assert _safe_filename("My Cool Plugin!") == "My_Cool_Plugin"
    assert _safe_filename("simple") == "simple"
    assert _safe_filename("") == "plugin"


def test_install_and_remove_plugin(tmp_path: Path) -> None:
    from homelab_ai.plugin_installer import list_plugins, remove_plugin
    from homelab_ai.plugin_manager import PLUGIN_DIR

    # Create a test plugin file directly
    test_code = '"""test"""\nfrom homelab_ai.plugin_manager import _impl\n@_impl\ndef homelab_ai_startup(): pass\n'
    dest = PLUGIN_DIR / "test_plugin.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(test_code, encoding="utf-8")

    plugins = list_plugins()
    names = [p["name"] for p in plugins]
    assert "test_plugin" in names

    result = remove_plugin("test_plugin")
    assert result["ok"] is True
    assert not dest.exists()


def test_parse_gh_ref() -> None:
    from homelab_ai.plugin_installer import _parse_gh_ref
    result = _parse_gh_ref("gh:owner/repo")
    assert result is not None
    assert result["owner"] == "owner"
    assert result["repo"] == "repo"

    result2 = _parse_gh_ref("gh:owner/repo/path/to/plugin.py")
    assert result2 is not None
    assert result2["path"] == "path/to/plugin.py"


def test_hot_reload() -> None:
    from homelab_ai.plugin_installer import hot_reload, list_plugins
    # Just ensure it doesn't crash
    count = hot_reload()
    assert isinstance(count, int)
