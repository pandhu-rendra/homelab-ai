"""Shared fixtures for homelab-ai tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _clean_env() -> Generator[None, None, None]:
    """Use a temp directory for all DB/files to avoid polluting real data."""
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        # Point config paths to temp dir
        import homelab_ai.config as cfg
        import homelab_ai.storage as stg
        orig_base = cfg.BASE_DIR
        cfg.BASE_DIR = Path(td)
        cfg.DB_FILE = str(Path(td) / "autocompleter.db")
        cfg.SESSION_DB = str(Path(td) / "sessions.db")
        cfg.MEMORY_DB = str(Path(td) / "memory.db")
        cfg.HISTORY_JSON_FILE = str(Path(td) / "chat_history_persistent.json")
        cfg.HISTORY_DIR = str(Path(td) / "history")
        cfg.ENV_PATH = Path(td) / ".env"
        os.makedirs(cfg.HISTORY_DIR, exist_ok=True)
        # Sync storage module's imported references and reset init flags
        stg.SESSION_DB = cfg.SESSION_DB
        stg.DB_FILE = cfg.DB_FILE
        stg.HISTORY_DIR = cfg.HISTORY_DIR
        stg.HISTORY_JSON_FILE = cfg.HISTORY_JSON_FILE
        stg._INIT_SESSIONS = False
        yield
        import homelab_ai.memory as mem
        mem.close_connection()
        cfg.BASE_DIR = orig_base
        os.chdir(old_cwd)


@pytest.fixture
def sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
    ]


@pytest.fixture
def sample_json_history(tmp_path: Path) -> Path:
    """Create a sample JSON history file for migration testing."""
    data = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    dest = tmp_path / "chat_history_persistent.json"
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest
