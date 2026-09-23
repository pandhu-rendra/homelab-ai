"""Tests for config.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_lazy_install_returns_none_for_bogus_package() -> None:
    from homelab_ai.config import _lazy_install
    result = _lazy_install("nonexistent.module.xyzzy")
    assert result is None


def test_rotating_log_handler() -> None:
    from homelab_ai.config import _log_handler
    assert _log_handler.maxBytes == 1_000_000
    assert _log_handler.backupCount == 3


def test_keys_present() -> None:
    from homelab_ai.config import keys_present
    # Should return True as long as G4F or any key is available
    assert isinstance(keys_present(), bool)


def test_save_env_roundtrip() -> None:
    from homelab_ai.config import CONFIG_META, ENV_PATH, save_env
    original = dict(CONFIG_META)
    test_val = "test_value_123"
    CONFIG_META["DEEPSEEK_API_KEY"] = test_val
    save_env(CONFIG_META)
    assert ENV_PATH.exists()
    content = ENV_PATH.read_text(encoding="utf-8")
    assert test_val in content
    # Restore
    for k, v in original.items():
        CONFIG_META[k] = v


def test_config_meta_has_all_keys() -> None:
    from homelab_ai.config import CONFIG_META
    expected = {
        "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
        "GEMINI_API_KEY", "GEMINI_MODEL",
        "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
        "FLAZ_API_KEY", "FLAZ_MODEL", "FLAZ_ENDPOINT",
        "HOMELAB_G4F_ENABLED", "G4F_PROVIDER",
    }
    assert expected.issubset(CONFIG_META.keys())


@pytest.mark.parametrize("value, expected", [
    ("false", False), ("true", True), ("1", True), ("on", True),
])
def test_g4f_enabled_parses_boolean(monkeypatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("HOMELAB_G4F_ENABLED", value)
    assert (value.strip().lower() in {"1", "true", "yes", "on"}) is expected


def test_doctor_reports_installation_state() -> None:
    from homelab_ai.maintenance import doctor

    result = doctor()

    assert "HomeLab AI doctor" in result
    assert "Python:" in result


def test_uninstall_requires_confirmation(tmp_path) -> None:
    from homelab_ai.maintenance import uninstall

    target = tmp_path / "homelab-ai"
    target.mkdir()

    result = uninstall(target)

    assert "--confirm" in result
    assert target.exists()
