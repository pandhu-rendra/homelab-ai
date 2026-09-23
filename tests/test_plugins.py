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


def test_project_plugin_manifest_context(tmp_path, monkeypatch) -> None:
    import homelab_ai.plugin_manager as manager

    plugin_dir = tmp_path / "weather-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text("# executable hook", encoding="utf-8")
    (plugin_dir / "PLUGIN.md").write_text(
        "---\nname: Weather Plugin\ndescription: Weather reports and forecasts\nkeywords: weather, forecast\n---\n"
        "Use the weather tool and include Celsius units.",
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "PROJECT_PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(manager, "LEGACY_PLUGIN_DIR", tmp_path / "missing")

    context = manager.build_plugin_context("give me a weather forecast")

    assert "Weather Plugin" in context
    assert "Celsius" in context


def test_plugin_manifest_is_listed(tmp_path, monkeypatch) -> None:
    from homelab_ai.plugin_manager import list_plugin_manifests
    import homelab_ai.plugin_manager as manager

    (tmp_path / "demo" ).mkdir()
    (tmp_path / "demo" / "PLUGIN.md").write_text("Demo plugin", encoding="utf-8")
    monkeypatch.setattr(manager, "PROJECT_PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(manager, "LEGACY_PLUGIN_DIR", tmp_path / "missing")

    listed = list_plugin_manifests()

    assert listed[0]["name"] == "demo"
    assert listed[0]["origin"] == "project"
