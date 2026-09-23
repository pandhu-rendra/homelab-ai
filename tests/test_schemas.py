"""Tests for schemas.py — parameter validation and tool manifest."""

from __future__ import annotations


def test_tool_manifest_has_all_93_plus_tools() -> None:
    from homelab_ai.schemas import TOOL_MODELS, tool_manifest
    assert len(TOOL_MODELS) >= 93
    manifest = tool_manifest()
    assert len(manifest) == len(TOOL_MODELS)


def test_validate_valid_params() -> None:
    from homelab_ai.schemas import validate_tool_params
    model, error = validate_tool_params("web_search", {"query": "hello"})
    assert error is None
    assert model is not None
    assert model.query == "hello"


def test_validate_missing_required() -> None:
    from homelab_ai.schemas import validate_tool_params
    model, error = validate_tool_params("web_search", {})
    assert error is not None
    assert "query" in error


def test_validate_unknown_tool() -> None:
    from homelab_ai.schemas import validate_tool_params
    model, error = validate_tool_params("nonexistent_tool", {})
    assert error is not None
    assert "not recognized" in error


def test_ask_codebase_params() -> None:
    from homelab_ai.schemas import AskCodebaseParams
    params = AskCodebaseParams(question="how does this work?")
    assert params.question == "how does this work?"
    assert params.top_k == 5  # default


def test_plugin_install_params() -> None:
    from homelab_ai.schemas import PluginInstallParams
    params = PluginInstallParams(source="gh:owner/repo")
    assert params.source == "gh:owner/repo"
    assert params.name == ""
