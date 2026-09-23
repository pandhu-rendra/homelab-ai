"""Persistence: SQLite sessions, markdown export, autocomplete DB.

Replaces the old JSON-based chat history with proper SQLite storage.
Auto-migrates existing JSON data on first run.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
from typing import Optional

from .config import DB_FILE, HISTORY_DIR, SESSION_DB, logger

_local = threading.local()

DEFAULT_WORDS = [
    "ask", "exit", "quit", "clear", "sudo", "help",
    "fastfetch", "get_weather",
    "scrape_website", "read_pdf", "list_dir", "view_file",
    "write_file", "execute_command", "summarize_youtube",
    "web_search", "patch_file", "analyze_code", "search_files",
    "count_tokens", "web_fetch_async", "analyze_python",
    "calculate_complexity", "format_code", "sort_imports",
    "lint_code", "git_status", "git_log", "git_diff",
    "read_spreadsheet", "analyze_image", "read_yaml",
    "parse_markdown", "ssh_execute", "docker_ps", "docker_images",
    "generate_ascii_banner", "encrypt_text",
    "screen_info", "capture_screen", "mouse_click", "type_text",
    "locate_on_screen", "cloudscrape", "browse_website",
    "browser_automate", "redis_exec", "sql_query", "mqtt_publish",
    "broadlink_discover", "analyze_data_stats", "train_model",
    "text_to_speech", "speech_to_text", "play_audio",
    "schedule_add", "crontab_add", "rpyc_call",
    "generate_qrcode", "parquet_info", "config_read",
    "proxmox_list_nodes", "proxmox_list_vms", "wake_on_lan",
    "ping_host", "ssh_scp_upload", "ssh_scp_download",
    "pexpect_spawn", "network_interfaces", "scapy_traceroute",
    "dns_lookup", "humanize_value", "slugify_text",
    "parse_string", "arrow_time", "cron_next", "prometheus_metrics",
    "watch_directory",
]

# --------------------------------------------------------------------------- #
# SQLite connection helpers (thread-safe)
# --------------------------------------------------------------------------- #


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def _close_conn() -> None:
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


# --------------------------------------------------------------------------- #
# Autocomplete keyword database
# --------------------------------------------------------------------------- #


def init_autocomplete_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS keywords (word TEXT PRIMARY KEY)")
    for word in DEFAULT_WORDS:
        cursor.execute("INSERT OR IGNORE INTO keywords (word) VALUES (?)", (word,))
    conn.commit()
    conn.close()


def get_all_keywords() -> list[str]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT word FROM keywords")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def learn_new_words(sentence: str) -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for word in sentence.lower().split():
        clean_word = "".join(c for c in word if c.isalnum() or c in ["_", "-"])
        if clean_word:
            cursor.execute("INSERT OR IGNORE INTO keywords (word) VALUES (?)", (clean_word,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# SQLite session persistence (#7)
# --------------------------------------------------------------------------- #

_INIT_SESSIONS = False


def _ensure_session_db() -> None:
    global _INIT_SESSIONS
    if _INIT_SESSIONS:
        return
    conn = sqlite3.connect(SESSION_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            label TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
    """)
    conn.commit()
    conn.close()
    # Auto-migrate from old JSON if present
    _migrate_from_json()
    _INIT_SESSIONS = True


def _migrate_from_json() -> None:
    """One-time migration from the old JSON file to SQLite."""
    json_path = os.path.join(os.path.dirname(SESSION_DB), "chat_history_persistent.json")
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        if not data or not isinstance(data, list):
            return
        conn = _session_conn()
        # Check if we already have data
        existing = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        if existing > 0:
            return
        conn.execute("INSERT INTO sessions (id, label) VALUES (?, ?)",
                     ("tab_1", "Migrated from JSON"))
        for msg in data:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls) VALUES (?, ?, ?, ?)",
                ("tab_1", msg.get("role", "user"), msg.get("content", ""),
                 json.dumps(msg.get("tool_calls", []))),
            )
        conn.commit()
        conn.close()
        # Rename old file
        os.rename(json_path, json_path + ".bak")
        logger.info("Migrated %d messages from JSON to SQLite", len(data))
    except Exception as exc:
        logger.warning("Migration from JSON failed: %s", exc)


def _session_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SESSION_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def save_history(session_id: str, messages: list[dict]) -> None:
    """Save a full conversation for a session (replace mode)."""
    _ensure_session_db()
    conn = _session_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,))
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for msg in messages:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls) VALUES (?, ?, ?, ?)",
                (session_id, msg.get("role", "user"), msg.get("content", ""),
                 json.dumps(msg.get("tool_calls", []))),
            )
        conn.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (session_id,))
        conn.commit()
    except Exception as exc:
        logger.error("Save session failed: %s", exc)
    finally:
        conn.close()


def load_history(session_id: str) -> Optional[list[dict]]:
    """Load a conversation from SQLite."""
    _ensure_session_db()
    conn = _session_conn()
    try:
        rows = conn.execute(
            "SELECT role, content, tool_calls FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        if not rows:
            return None
        messages: list[dict] = []
        for row in rows:
            msg = {"role": row["role"], "content": row["content"]}
            tc = row["tool_calls"]
            if tc and tc != "[]":
                try:
                    msg["tool_calls"] = json.loads(tc)
                except json.JSONDecodeError:
                    pass
            messages.append(msg)
        return messages
    except Exception as exc:
        logger.error("Load session failed: %s", exc)
        return None
    finally:
        conn.close()


def list_sessions() -> list[dict]:
    """Return all saved sessions with metadata."""
    _ensure_session_db()
    conn = _session_conn()
    try:
        rows = conn.execute("""
            SELECT s.id, s.created_at, s.updated_at, s.label,
                   COUNT(m.id) as msg_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    """Delete a session and all its messages."""
    _ensure_session_db()
    conn = _session_conn()
    try:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Backward-compatible aliases (old JSON API)
# --------------------------------------------------------------------------- #


def save_history_to_json(history_data: list[dict]) -> None:
    save_history("tab_1", history_data)


def load_history_from_json() -> Optional[list[dict]]:
    return load_history("tab_1")


# --------------------------------------------------------------------------- #
# Markdown session export
# --------------------------------------------------------------------------- #


def export_session_to_markdown(conversation_history: list[dict]) -> str:
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(HISTORY_DIR, f"session_{timestamp}.md")

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts = [
            "# HomeLab AI - Session Log\n",
            f"**Time/Date:** {now}\n",
            "=========================================\n\n",
        ]

        for msg in conversation_history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                continue
            if role == "user":
                if content.startswith("Tool Result:"):
                    clean_text = content.replace("Tool Result: ", "")
                    parts.append(f"### SYSTEM (Tool Result):\n```text\n{clean_text}\n```\n\n")
                else:
                    parts.append(f"## USER:\n{content}\n\n")
            elif role == "assistant":
                if "CALL_TOOL:" in content:
                    parts.append(f"### ASSISTANT (Thinking/Tool Call):\n{content}\n\n")
                else:
                    parts.append(f"## HomeLab AI:\n{content}\n\n")
            parts.append("---\n\n")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("".join(parts))
        return file_path
    except Exception as exc:
        return f"Error: {exc}"
