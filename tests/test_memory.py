"""Tests for memory.py (#8)."""

from __future__ import annotations


def test_remember_and_recall() -> None:
    from homelab_ai.memory import forget, recall, remember
    remember("test_key", "test_value", category="test")
    assert recall("test_key") == "test_value"
    forget("test_key")
    assert recall("test_key") is None


def test_recall_by_category() -> None:
    from homelab_ai.memory import forget, recall_by_category, remember
    remember("pref1", "val1", category="preference")
    remember("pref2", "val2", category="preference")
    remember("other", "val3", category="other")
    prefs = recall_by_category("preference")
    assert len(prefs) == 2
    keys = {p["key"] for p in prefs}
    assert keys == {"pref1", "pref2"}
    forget("pref1")
    forget("pref2")
    forget("other")


def test_record_tool_call() -> None:
    from homelab_ai.memory import get_tool_stats, record_tool_call
    record_tool_call("test_tool", 0.5)
    record_tool_call("test_tool", 0.3)
    record_tool_call("test_tool_error", 1.0, error="timeout")
    stats = get_tool_stats()
    stats_by_name = {s["tool_name"]: s for s in stats}
    assert stats_by_name["test_tool"]["call_count"] == 2
    assert stats_by_name["test_tool"]["avg_duration"] > 0
    assert stats_by_name["test_tool_error"]["error_count"] == 1


def test_learn_and_search_facts() -> None:
    from homelab_ai.memory import get_facts, learn_fact, search_facts
    learn_fact("Python is a programming language", source="test", confidence=0.9)
    learn_fact("The sky is blue", source="test", confidence=0.5)
    results = search_facts("Python")
    assert len(results) >= 1
    assert "Python" in results[0]["fact"]
    all_facts = get_facts(limit=10)
    assert len(all_facts) >= 2


def test_build_memory_context() -> None:
    from homelab_ai.memory import build_memory_context, forget, recall_by_category, remember
    # Clean up first
    for p in recall_by_category("preference"):
        forget(p["key"])
    remember("language", "Indonesian", category="preference")
    ctx = build_memory_context()
    assert "language" in ctx
    assert "Indonesian" in ctx
    forget("language")
