"""Install and load AI skills for HomeLab AI.

Skills are instruction/data bundles, unlike Python plugins. A skill can be
installed from a GitHub repository and its SKILL.md is added to model context
only when the user asks about the skill's domain.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import httpx

from .config import logger

SKILL_DIR = Path.home() / ".config" / "homelab-ai" / "skills"
UI_UX_SOURCE = "gh:nextlevelbuilder/ui-ux-pro-max-skill"
_UI_QUERY_TERMS = re.compile(
    r"\b(ui|ux|frontend|front-end|web|website|landing page|dashboard|component|"
    r"react|vue|tailwind|css|html|design system|interface|visual)\b",
    re.IGNORECASE,
)


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name).strip("_.-") or "skill"


def _github_archive(source: str) -> tuple[str, str] | None:
    match = re.match(r"^(?:gh:|https?://github\.com/)([^/]+)/([^/#]+)", source)
    if not match:
        return None
    owner, repo = match.groups()
    repo = repo.removesuffix(".git")
    return (
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        _safe_name(repo),
    )


def install_skill(source: str, *, name: str | None = None) -> dict:
    """Download a GitHub skill archive into the local skill directory."""
    resolved = _github_archive(source.strip())
    if not resolved:
        return {"ok": False, "path": None, "error": "Use gh:owner/repo or a GitHub URL."}

    url, repo_name = resolved
    target = SKILL_DIR / _safe_name(name or repo_name)
    try:
        response = httpx.get(url, follow_redirects=True, timeout=60)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            target.mkdir(parents=True, exist_ok=True)
            root = archive.namelist()[0].split("/", 1)[0]
            for member in archive.infolist():
                relative = member.filename.split("/", 1)[-1]
                if not relative or relative.startswith("__MACOSX/"):
                    continue
                destination = (target / relative).resolve()
                if target.resolve() not in destination.parents:
                    return {"ok": False, "path": None, "error": "Unsafe archive path."}
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(member))
        logger.info("Skill installed: %s from %s (%s)", target, source, root)
        return {"ok": True, "path": str(target), "error": None}
    except (httpx.HTTPError, OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "path": None, "error": str(exc)}


def remove_skill(name: str) -> dict:
    """Remove an installed skill directory."""
    target = SKILL_DIR / _safe_name(name)
    if not target.is_dir():
        return {"ok": False, "error": f"Skill not found: {name}"}
    try:
        import shutil
        shutil.rmtree(target)
        return {"ok": True, "error": None}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def list_skills() -> list[dict]:
    """Return installed skill directories and their instruction file status."""
    if not SKILL_DIR.exists():
        return []
    return [
        {"name": path.name, "path": str(path), "has_instructions": bool(list(path.rglob("SKILL.md")))}
        for path in sorted(SKILL_DIR.iterdir())
        if path.is_dir()
    ]


def build_skill_context(user_input: str) -> str:
    """Return relevant skill instructions for a query, or an empty string."""
    if not _UI_QUERY_TERMS.search(user_input):
        return ""
    sections: list[str] = [
        "[SKILL EXECUTION RULES]",
        "Treat the installed skill instructions below as active for this request.",
        "If the user names a directory or file, use that exact path; do not substitute a default folder such as plugins.",
        "If the user names multiple skills, use all of the named installed skills before responding.",
        "For a code or UI change, inspect the requested target first, then apply the skill guidance while editing it.",
    ]
    for skill in list_skills():
        candidates = sorted(Path(skill["path"]).rglob("SKILL.md"))
        if not candidates:
            continue
        try:
            content = candidates[0].read_text(encoding="utf-8")
        except OSError:
            continue
        sections.append(f"[INSTALLED SKILL: {skill['name']}]\n{content[:14000]}")
    return "\n\n".join(sections)