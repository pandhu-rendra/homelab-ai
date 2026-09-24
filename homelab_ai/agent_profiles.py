"""User-defined agent profiles stored as local YAML files."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .config import BASE_DIR, logger

AGENT_DIR = BASE_DIR / "agents"
LEGACY_AGENT_DIR = Path.home() / ".config" / "homelab-ai" / "agents"
AGENT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TOOLS = ["view_file", "list_dir", "search_files"]


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name.strip()).strip("_.-") or "agent"


def _path(name: str) -> Path:
    return AGENT_DIR / f"{_safe_name(name)}.yaml"


def _normalize(data: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    return {
        "name": str(data.get("name") or fallback_name),
        "description": str(data.get("description") or "User-defined HomeLab AI agent"),
        "enabled": bool(data.get("enabled", True)),
        "model": str(data.get("model") or "current"),
        "max_attempts": int(data.get("max_attempts", 6)),
        "tools": [str(tool) for tool in (data.get("tools") or DEFAULT_TOOLS)],
        "system_prompt": str(data.get("system_prompt") or "You are a helpful specialist. Follow the user's request carefully."),
    }


def create_agent(name: str, description: str = "", system_prompt: str = "") -> dict[str, Any]:
    target = _path(name)
    if target.exists():
        return {"ok": False, "error": f"Agent already exists: {target.name}"}
    profile = _normalize({
        "name": name,
        "description": description or f"User-defined {name} agent",
        "system_prompt": system_prompt or f"You are the {name} specialist. Follow the user's request carefully.",
    }, _safe_name(name))
    target.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"ok": True, "path": str(target), "profile": profile}


def list_agents() -> list[dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for root, origin in ((AGENT_DIR, "project"), (LEGACY_AGENT_DIR, "user")):
        if not root.exists():
            continue
        for path in sorted(root.glob("*.y*ml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                profile = _normalize(data, path.stem)
                profile.update({"path": str(path), "origin": origin})
                profiles[profile["name"]] = profile
            except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
                logger.warning("Agent profile load failed: %s: %s", path, exc)
    return [profiles[name] for name in sorted(profiles)]


def get_agent(name: str) -> dict[str, Any] | None:
    wanted = name.lower()
    return next((profile for profile in list_agents() if profile["name"].lower() == wanted), None)


def set_agent_enabled(name: str, enabled: bool) -> str:
    profile = get_agent(name)
    if not profile:
        return f"Agent not found: {name}"
    data = dict(profile)
    data.pop("path", None)
    data.pop("origin", None)
    data["enabled"] = enabled
    Path(profile["path"]).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return f"Agent {'enabled' if enabled else 'disabled'}: {profile['name']}"


def delete_agent(name: str) -> str:
    profile = get_agent(name)
    if not profile:
        return f"Agent not found: {name}"
    Path(profile["path"]).unlink(missing_ok=True)
    return f"Agent deleted: {profile['name']}"


def edit_agent(name: str) -> str:
    profile = get_agent(name)
    if not profile:
        return f"Agent not found: {name}"
    path = str(Path(profile["path"]).resolve())
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen([os.environ.get("EDITOR", "vi"), path])
    return f"Opened agent profile: {path}"


def build_agent_context(name: str | None, user_input: str) -> str:
    if not name:
        return ""
    profile = get_agent(name)
    if not profile or not profile["enabled"]:
        return ""
    tools = ", ".join(profile["tools"])
    return (
        f"[ACTIVE USER AGENT: {profile['name']}]\n"
        f"Role: {profile['description']}\n"
        f"Allowed tools profile: {tools}\n"
        f"Agent instructions:\n{profile['system_prompt']}\n"
        "Treat this as the selected specialist profile. Do not claim to have tools outside the active system tool policy."
    )
