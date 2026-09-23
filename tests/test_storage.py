"""Tests for storage.py (#7 SQLite session persistence)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_save_and_load_history() -> None:
    from homelab_ai.storage import load_history, save_history
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    save_history("test_session", messages)
    loaded = load_history("test_session")
    assert loaded is not None
    assert len(loaded) == 3
    assert loaded[0]["role"] == "system"
    assert loaded[-1]["content"] == "hi"


def test_save_overwrites_previous() -> None:
    from homelab_ai.storage import load_history, save_history
    save_history("overwrite_test", [{"role": "user", "content": "first"}])
    save_history("overwrite_test", [{"role": "user", "content": "second"}])
    loaded = load_history("overwrite_test")
    assert loaded is not None
    assert len(loaded) == 1
    assert loaded[0]["content"] == "second"


def test_load_nonexistent_session() -> None:
    from homelab_ai.storage import load_history
    assert load_history("nonexistent_session") is None


def test_list_sessions() -> None:
    from homelab_ai.storage import list_sessions, save_history
    save_history("list_test_1", [{"role": "user", "content": "hi"}])
    save_history("list_test_2", [{"role": "user", "content": "hey"}])
    sessions = list_sessions()
    ids = {s["id"] for s in sessions}
    assert "list_test_1" in ids
    assert "list_test_2" in ids


def test_delete_session() -> None:
    from homelab_ai.storage import delete_session, load_history, save_history
    save_history("delete_test", [{"role": "user", "content": "bye"}])
    delete_session("delete_test")
    assert load_history("delete_test") is None


def test_export_markdown() -> None:
    from homelab_ai.storage import export_session_to_markdown
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "**hi**"},
    ]
    path = export_session_to_markdown(messages)
    assert os.path.exists(path)
    content = Path(path).read_text(encoding="utf-8")
    assert "USER" in content
    assert "HomeLab AI" in content


def test_backward_compat_functions() -> None:
    from homelab_ai.storage import load_history_from_json, save_history_to_json
    data = [{"role": "user", "content": "test"}]
    save_history_to_json(data)
    loaded = load_history_from_json()
    assert loaded is not None
    assert loaded[0]["content"] == "test"


def test_autocomplete_db() -> None:
    from homelab_ai.storage import get_all_keywords, init_autocomplete_db, learn_new_words
    init_autocomplete_db()
    keywords = get_all_keywords()
    assert len(keywords) > 10
    learn_new_words("some new words to learn")
    updated = get_all_keywords()
    assert len(updated) > len(keywords)
