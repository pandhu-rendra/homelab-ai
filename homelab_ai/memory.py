"""Agent memory / knowledge base (#8).

Stores user preferences, past tool interactions, and learned facts
in a local SQLite DB so the AI can recall context across sessions.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Optional

from . import config
from .config import logger

_local = threading.local()


def _conn() -> sqlite3.Connection:
    configured_path = config.MEMORY_DB
    existing_path = getattr(_local, "mem_conn_path", None)
    if getattr(_local, "mem_conn", None) is not None and existing_path != configured_path:
        close_connection()
    if not hasattr(_local, "mem_conn") or _local.mem_conn is None:
        _local.mem_conn = sqlite3.connect(configured_path)
        _local.mem_conn.row_factory = sqlite3.Row
        _local.mem_conn.execute("PRAGMA journal_mode=WAL")
        _init_db(_local.mem_conn)
        _local.mem_conn_path = configured_path
    return _local.mem_conn


def close_connection() -> None:
    """Close the memory database connection owned by the current thread."""
    connection = getattr(_local, "mem_conn", None)
    if connection is not None:
        connection.close()
        _local.mem_conn = None
        _local.mem_conn_path = None


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'general',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tool_stats (
            tool_name TEXT PRIMARY KEY,
            call_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_duration REAL DEFAULT 0.0,
            last_error TEXT DEFAULT '',
            avg_duration REAL DEFAULT 0.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            source TEXT DEFAULT '',
            confidence REAL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


# --------------------------------------------------------------------------- #
# User preferences / key-value memory
# --------------------------------------------------------------------------- #


def remember(key: str, value: str, category: str = "general") -> None:
    """Store a fact or preference."""
    conn = _conn()
    conn.execute(
        """INSERT INTO memories (key, value, category, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(key) DO UPDATE SET
             value=excluded.value, category=excluded.category, updated_at=CURRENT_TIMESTAMP""",
        (key, value, category),
    )
    conn.commit()


def recall(key: str) -> Optional[str]:
    """Retrieve a stored memory by key."""
    row = _conn().execute("SELECT value FROM memories WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def recall_by_category(category: str) -> list[dict]:
    """Return all memories in a category."""
    rows = _conn().execute(
        "SELECT key, value, updated_at FROM memories WHERE category = ? ORDER BY updated_at DESC",
        (category,),
    ).fetchall()
    return [dict(r) for r in rows]


def forget(key: str) -> None:
    """Delete a memory."""
    _conn().execute("DELETE FROM memories WHERE key = ?", (key,))
    _conn().commit()


def get_all_memories() -> list[dict]:
    rows = _conn().execute(
        "SELECT key, value, category, updated_at FROM memories ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Tool usage statistics
# --------------------------------------------------------------------------- #


def record_tool_call(tool_name: str, duration: float, error: str = "") -> None:
    """Record a tool invocation for analytics."""
    conn = _conn()
    if error:
        conn.execute(
            """INSERT INTO tool_stats (tool_name, call_count, error_count, last_duration, last_error, updated_at)
               VALUES (?, 1, 1, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(tool_name) DO UPDATE SET
                 call_count=call_count+1, error_count=error_count+1,
                 last_duration=excluded.last_duration, last_error=excluded.last_error,
                 updated_at=CURRENT_TIMESTAMP""",
            (tool_name, duration, error),
        )
    else:
        conn.execute(
            """INSERT INTO tool_stats (tool_name, call_count, last_duration, updated_at)
               VALUES (?, 1, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(tool_name) DO UPDATE SET
                 call_count=call_count+1, last_duration=excluded.last_duration,
                 avg_duration=(avg_duration * (call_count-1) + excluded.last_duration) / call_count,
                 updated_at=CURRENT_TIMESTAMP""",
            (tool_name, duration),
        )
    conn.commit()


def get_tool_stats() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM tool_stats ORDER BY call_count DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Facts (long-term knowledge)
# --------------------------------------------------------------------------- #


def learn_fact(fact: str, source: str = "", confidence: float = 1.0) -> None:
    """Store a factual statement the AI learned."""
    _conn().execute(
        "INSERT INTO facts (fact, source, confidence) VALUES (?, ?, ?)",
        (fact, source, min(confidence, 1.0)),
    )
    _conn().commit()


def get_facts(limit: int = 50) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM facts ORDER BY confidence DESC, created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def search_facts(query: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM facts WHERE fact LIKE ? ORDER BY confidence DESC LIMIT 20",
        (f"%{query}%",),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Memory context builder (for LLM prompt injection)
# --------------------------------------------------------------------------- #


def save_preference(key: str, value: str) -> None:
    """Save a cross-session user preference."""
    remember(f"pref_{key}", value, category="preference")


def load_preference(key: str, default: str = "") -> str:
    """Load a cross-session user preference."""
    val = recall(f"pref_{key}")
    return val if val else default


def learn_from_conversation(messages: list[dict]) -> None:
    """Extract and store useful facts from a conversation turn."""
    import re
    for msg in messages[-3:]:
        if msg["role"] != "assistant":
            continue
        content = msg.get("content", "")
        # Store user preferences mentioned in responses
        pref_patterns = [
            (r"(?:prefer|use|like|want|need)\s+(\w+)", "preference"),
        ]
        for pattern, category in pref_patterns:
            for m in re.finditer(pattern, content, re.IGNORECASE):
                key = f"learned_{m.group(1).lower()}"
                existing = recall(key)
                if not existing:
                    remember(key, content[:200], category=category)


def build_memory_context() -> str:
    """Build a compact memory summary for the LLM system prompt."""
    parts: list[str] = []

    prefs = recall_by_category("preference")
    if prefs:
        items = [f"  - {p['key']}: {p['value'][:80]}" for p in prefs[:8]]
        parts.append("[MEMORY] User preferences:\n" + "\n".join(items))

    facts = get_facts(limit=5)
    if facts:
        items = [f"  - {f['fact'][:120]}" for f in facts]
        parts.append("[MEMORY] Learned facts:\n" + "\n".join(items))

    stats = get_tool_stats()
    if stats:
        top = sorted(stats, key=lambda x: x["error_count"], reverse=True)[:3]
        problematic = [s for s in top if s["error_count"] > 2]
        if problematic:
            items = [f"  - {s['tool_name']}: {s['error_count']} errors (last: {s['last_error'][:50]})"
                     for s in problematic]
            parts.append("[MEMORY] Tools with frequent errors:\n" + "\n".join(items))
        # Show most used tools
        most_used = sorted(stats, key=lambda x: x["call_count"], reverse=True)[:3]
        if most_used:
            items = [f"  - {s['tool_name']}: {s['call_count']} calls" for s in most_used]
            parts.append("[MEMORY] Most used tools:\n" + "\n".join(items))

    return "\n\n".join(parts)
