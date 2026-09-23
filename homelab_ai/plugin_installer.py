"""Install plugins from online sources — GitHub, raw URLs, or plugin registries."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import httpx

from .config import BASE_DIR, logger
from .plugin_manager import PLUGIN_DIR, discover_plugins

PLUGIN_INDEX_URL = os.getenv(
    "HOMELAB_PLUGIN_INDEX",
    "https://raw.githubusercontent.com/netsure/homelab-ai-plugins/main/index.json",
)
PLUGIN_REGISTRY: dict[str, dict] = {}
"""Cache of remote plugin index: {name: {url, desc, author, ...}}"""


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: int = 30) -> str | None:
    """Download text content from a URL."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("Fetch failed: %s — %s", url, e)
        return None


def _safe_filename(name: str) -> str:
    """Sanitize a name for use as a filename."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name).strip("_") or "plugin"


def _validate_plugin_code(code: str) -> tuple[bool, str]:
    """Basic validation: must contain a hook impl marker."""
    if "_impl" not in code and "homelab_ai_" not in code:
        return False, "No @_impl hook marker found — not a valid homelab-ai plugin."
    if "__import__(" in code or "exec(" in code or "eval(" in code:
        return False, "Suspicious code pattern detected."
    return True, ""


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"


def _parse_gh_ref(ref: str) -> dict | None:
    """Parse ``gh:owner/repo[/path/to/file.py]`` or raw GitHub URL."""
    m = re.match(r"^gh:([^/]+)/([^/]+)(?:/(.+))?$", ref)
    if m:
        owner, repo, path = m.group(1), m.group(2), m.group(3) or ""
        return {"owner": owner, "repo": repo, "path": path, "branch": "main"}
    m = re.match(r"github\.com/([^/]+)/([^/]+)(?:/blob/([^/]+)/(.+))?", ref)
    if m:
        owner, repo, branch, path = m.group(1), m.group(2), m.group(3) or "main", m.group(4) or ""
        return {"owner": owner, "repo": repo, "path": path, "branch": branch}
    return None


def _resolve_gh_plugin(info: dict) -> str | None:
    """Resolve a GitHub ref to a raw .py URL."""
    owner, repo, branch = info["owner"], info["repo"], info["branch"]
    path = info["path"]

    # If path given, use it directly
    if path:
        if path.endswith(".py"):
            return f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}"
        # It might be a directory — look for plugin.py inside
        return f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}/plugin.py"

    # No path — try common filenames
    for name in ("plugin.py", "main.py", f"{repo}.py"):
        url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{name}"
        if _fetch(url, timeout=10):
            return url

    # Try listing dir via API
    api_url = f"{GITHUB_API}/repos/{owner}/{repo}/contents?ref={branch}"
    try:
        resp = httpx.get(api_url, timeout=15)
        if resp.status_code == 200:
            for item in resp.json():
                if item["name"].endswith(".py") and not item["name"].startswith("_"):
                    return f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{item['name']}"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Plugin info / registry
# ---------------------------------------------------------------------------

def fetch_registry(url: str | None = None) -> dict[str, dict]:
    """Fetch & cache the remote plugin index."""
    global PLUGIN_REGISTRY
    if PLUGIN_REGISTRY:
        return PLUGIN_REGISTRY

    text = _fetch(url or PLUGIN_INDEX_URL)
    if not text:
        return {}

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            PLUGIN_REGISTRY = data
        elif isinstance(data, list):
            PLUGIN_REGISTRY = {p.get("name", f"plugin_{i}"): p for i, p in enumerate(data)}
    except json.JSONDecodeError:
        pass
    return PLUGIN_REGISTRY


# ---------------------------------------------------------------------------
# Core install functions
# ---------------------------------------------------------------------------

def install_plugin(source: str, *, name: str | None = None,
                   branch: str = "main") -> dict:
    """Install a plugin from a URL or GitHub ref.

    Args:
        source: URL (``https://...``), GitHub ref (``gh:owner/repo``),
                or registry name (e.g. ``web-search``).
        name: Optional custom filename (stem only).
        branch: Git branch (only for ``gh:`` refs).

    Returns:
        ``{"ok": bool, "path": str|None, "error": str|None}``
    """
    # 1. Check registry
    registry = fetch_registry()
    if source in registry:
        entry = registry[source]
        url = entry.get("url") or entry.get("source", "")
        name = name or entry.get("filename") or _safe_filename(source)
        return _install_from_url(url, name)

    # 2. GitHub ref
    gh_info = _parse_gh_ref(source)
    if gh_info:
        gh_info["branch"] = branch
        url = _resolve_gh_plugin(gh_info)
        if url:
            stem = name or _safe_filename(f"{gh_info['owner']}_{gh_info['repo']}")
            result = _install_from_url(url, stem)
            if result["ok"] and not result.get("plugin_name"):
                result["plugin_name"] = gh_info["repo"]
            return result
        return {"ok": False, "path": None,
                "error": f"No .py plugin found at {source}"}

    # 3. Direct URL
    if source.startswith(("http://", "https://")):
        stem = name or _safe_filename(Path(source).stem)
        return _install_from_url(source, stem)

    return {"ok": False, "path": None,
            "error": f"Unknown source format: {source}"}


def _install_from_url(url: str, name: str) -> dict:
    """Download a single .py plugin file and save to PLUGIN_DIR."""
    if not name.endswith(".py"):
        name += ".py"

    code = _fetch(url)
    if code is None:
        return {"ok": False, "path": None, "error": f"Failed to download: {url}"}

    valid, err = _validate_plugin_code(code)
    if not valid:
        return {"ok": False, "path": None, "error": err}

    dest = PLUGIN_DIR / name
    try:
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")
        logger.info("Plugin installed: %s (%s)", dest, url)
        return {"ok": True, "path": str(dest), "error": None}
    except OSError as e:
        return {"ok": False, "path": None, "error": str(e)}


def remove_plugin(name: str) -> dict:
    """Remove an installed plugin file."""
    if not name.endswith(".py"):
        name += ".py"
    dest = PLUGIN_DIR / name
    if not dest.exists():
        return {"ok": False, "error": f"Plugin not found: {name}"}
    try:
        dest.unlink()
        logger.info("Plugin removed: %s", dest)
        return {"ok": True, "error": None}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def list_plugins() -> list[dict]:
    """Return metadata on all installed plugin files."""
    plugins: list[dict] = []
    if not PLUGIN_DIR.exists():
        return plugins
    for fpath in sorted(PLUGIN_DIR.glob("*.py")):
        if fpath.name.startswith("_"):
            continue
        plugins.append({
            "name": fpath.stem,
            "filename": fpath.name,
            "path": str(fpath),
            "size": fpath.stat().st_size,
        })
    return plugins


def load_registry_plugins() -> list[dict]:
    """Return available plugins from the remote registry."""
    registry = fetch_registry()
    return [
        {"name": k, **v}
        for k, v in registry.items()
    ]


def hot_reload() -> int:
    """Re-discover plugins (call after install/remove). Returns count loaded."""
    from .plugin_manager import reload_plugins
    return reload_plugins()
