"""Configuration, logging and lazy LLM client construction.

This module is part of the *brain*: it sets up the same DeepSeek / Gemini /
G4F clients the original script used. Client construction is lazy so the TUI
can boot (and be tested) even when no API keys are present.
"""
from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys
import threading
import warnings
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    _dotenv_available = True
except ImportError:
    load_dotenv = None
    _dotenv_available = False

warnings.filterwarnings("ignore", category=RuntimeWarning)
os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "logfire-plugin")

# ---------------------------------------------------------------------------
# Paths — keep state next to the package so it works from any CWD.
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
if _dotenv_available:
    load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
else:
    import logging
    logging.getLogger("homelab_ai").warning("python-dotenv not installed; .env file ignored")
DB_FILE = str(BASE_DIR / "autocompleter.db")
SESSION_DB = str(BASE_DIR / "sessions.db")
MEMORY_DB = str(BASE_DIR / "memory.db")
HISTORY_JSON_FILE = str(BASE_DIR / "chat_history_persistent.json")
HISTORY_DIR = str(BASE_DIR / "history")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = str(LOG_DIR / "agent_log.txt")
PROVIDER_LOG_FILE = str(LOG_DIR / "provider_failures.log")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
FLAZ_API_KEY = os.getenv("FLAZ_API_KEY")
FLAZ_MODEL = os.getenv("FLAZ_MODEL", "claude-sonnet-4-20250514")
FLAZ_ENDPOINT = os.getenv("FLAZ_ENDPOINT", "https://api.flaz.id/v1")

# LLM request timeout in seconds. 0 means wait indefinitely.
try:
    LLM_TIMEOUT_SECONDS = max(1.0, float(os.getenv("HOMELAB_LLM_TIMEOUT", "30")))
except ValueError:
    LLM_TIMEOUT_SECONDS = 30.0

try:
    MAX_TOTAL_TOKENS = min(max(1000, int(os.getenv("HOMELAB_MAX_TOTAL_TOKENS", "12000"))), 100000)
except ValueError:
    MAX_TOTAL_TOKENS = 12000

# Agent reasoning attempts. A zero value is normalized to the safe hard cap below.
try:
    MAX_ATTEMPTS = max(0, int(os.getenv("HOMELAB_MAX_ATTEMPTS", "10")))
except ValueError:
    MAX_ATTEMPTS = 10

try:
    MAX_PROVIDER_ATTEMPTS = min(max(1, int(os.getenv("HOMELAB_MAX_PROVIDER_ATTEMPTS", "2"))), 4)
except ValueError:
    MAX_PROVIDER_ATTEMPTS = 2

try:
    MAX_CONTEXT_CHARS = min(max(4000, int(os.getenv("HOMELAB_MAX_CONTEXT_CHARS", "24000"))), 100000)
except ValueError:
    MAX_CONTEXT_CHARS = 24000

# G4F (free fallback) — opt-in because it can be unreliable and slow
G4F_ENABLED = os.getenv("HOMELAB_G4F_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on",
}
G4F_AVAILABLE: bool = False
G4F_PROVIDER = os.getenv("G4F_PROVIDER", "")  # empty = auto
if G4F_ENABLED:
    try:
        import g4f  # noqa: F401
        G4F_AVAILABLE = True
    except ImportError:
        pass

class _LockedRotatingFileHandler(RotatingFileHandler):
    """Serialize writes and rollover across provider worker threads on Windows."""

    _rollover_lock = threading.RLock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._rollover_lock:
            try:
                super().emit(record)
            except PermissionError:
                self.handleError(record)


_log_handler = _LockedRotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s - [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])

logger = logging.getLogger("homelab_ai")

_provider_log_handler = _LockedRotatingFileHandler(PROVIDER_LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_provider_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
_provider_log_handler.setLevel(logging.DEBUG)
provider_logger = logging.getLogger("homelab_ai.providers")
provider_logger.propagate = False
provider_logger.addHandler(_provider_log_handler)
provider_logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Self-healing: auto-install missing packages (#10)
# ---------------------------------------------------------------------------
_INSTALLING: set[str] = set()


def _lazy_install(module_name: str, pkg_name: str | None = None) -> Any | None:
    """Import a module; if missing, pip install it and retry once."""
    if module_name in _INSTALLING:
        return None
    try:
        return importlib.import_module(module_name)
    except ImportError:
        pkg = pkg_name or module_name.split(".")[0]
        _INSTALLING.add(module_name)
        logger.info("Auto-installing missing package: %s", pkg)
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                capture_output=True, timeout=60,
            )
            return importlib.import_module(module_name)
        except Exception as exc:
            logger.warning("Auto-install failed for %s: %s", pkg, exc)
            return None
        finally:
            _INSTALLING.discard(module_name)


@lru_cache(maxsize=1)
def get_deepseek_client():
    """Build the DeepSeek (OpenAI-compatible) client lazily."""
    from openai import OpenAI

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")


@lru_cache(maxsize=1)
def get_gemini_client():
    """Build the Google GenAI client lazily."""
    from google import genai

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=GEMINI_API_KEY)


@lru_cache(maxsize=1)
def get_openrouter_client():
    """Build OpenRouter (OpenAI-compatible) client lazily."""
    from openai import OpenAI

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")


@lru_cache(maxsize=1)
def get_flaz_client():
    """Build Flaz.id (OpenAI-compatible) client lazily."""
    from openai import OpenAI

    if not FLAZ_API_KEY:
        raise RuntimeError("FLAZ_API_KEY is not set")
    return OpenAI(api_key=FLAZ_API_KEY, base_url=FLAZ_ENDPOINT)


def keys_present() -> bool:
    return bool(DEEPSEEK_API_KEY or GEMINI_API_KEY or OPENROUTER_API_KEY or FLAZ_API_KEY or G4F_AVAILABLE)

# All configurable env vars (key name -> current value) for TUI editing
CONFIG_META: dict[str, str] = {
    "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY or "",
    "DEEPSEEK_MODEL": DEEPSEEK_MODEL,
    "GEMINI_API_KEY": GEMINI_API_KEY or "",
    "GEMINI_MODEL": GEMINI_MODEL,
    "OPENROUTER_API_KEY": OPENROUTER_API_KEY or "",
    "OPENROUTER_MODEL": OPENROUTER_MODEL,
    "FLAZ_API_KEY": FLAZ_API_KEY or "",
    "FLAZ_MODEL": FLAZ_MODEL,
    "FLAZ_ENDPOINT": FLAZ_ENDPOINT,
    "HOMELAB_G4F_ENABLED": "true" if G4F_ENABLED else "false",
    "HOMELAB_LLM_TIMEOUT": str(int(LLM_TIMEOUT_SECONDS)) if LLM_TIMEOUT_SECONDS.is_integer() else str(LLM_TIMEOUT_SECONDS),
    "HOMELAB_MAX_ATTEMPTS": str(MAX_ATTEMPTS),
    "HOMELAB_MAX_PROVIDER_ATTEMPTS": str(MAX_PROVIDER_ATTEMPTS),
    "HOMELAB_MAX_CONTEXT_CHARS": str(MAX_CONTEXT_CHARS),
    "HOMELAB_MAX_TOTAL_TOKENS": str(MAX_TOTAL_TOKENS),
    "G4F_PROVIDER": G4F_PROVIDER,
}

ENV_PATH = BASE_DIR / ".env"
ANALYTICS_FILE = str(BASE_DIR / "analytics.db")


def save_env(overrides: dict[str, str]) -> None:
    """Write/update .env with given overrides (only changes specified keys)."""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    # Keep existing lines, override matching keys
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in overrides:
            new_lines.append(f"{key}={overrides[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, val in overrides.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    # Reload env vars — update os.environ and config module globals
    for k, v in overrides.items():
        os.environ[k] = v
    if _dotenv_available:
        load_dotenv(override=True)
    globals().update({
        k: os.getenv(k, "")
        for k in overrides
    })
