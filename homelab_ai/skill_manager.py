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

from .config import BASE_DIR, logger

# Repository-local skills are portable with the application. The user-level
# directory remains a compatibility fallback for previously installed skills.
SKILL_DIR = BASE_DIR / "skills"
LEGACY_SKILL_DIR = Path.home() / ".config" / "homelab-ai" / "skills"
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
    """Return local and legacy skills without mixing them with plugins."""
    results: dict[str, dict] = {}
    for root, origin in ((SKILL_DIR, "project"), (LEGACY_SKILL_DIR, "user")):
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            instruction_files = _instruction_files(path)
            metadata = _read_frontmatter(instruction_files[0]) if instruction_files else {}
            results.setdefault(path.name, {
                "name": str(metadata.get("name") or path.name),
                "path": str(path),
                "origin": origin,
                "has_instructions": bool(instruction_files),
                "description": str(metadata.get("description") or ""),
                "keywords": str(metadata.get("keywords") or metadata.get("triggers") or ""),
            })
    return [results[name] for name in sorted(results)]


def build_skill_context(user_input: str) -> str:
    """Return relevant local skill instructions for any supported model."""
    query = user_input or ""
    selected = []
    for skill in list_skills():
        candidates = _instruction_files(Path(skill["path"]))
        if not candidates or not _skill_matches(skill, query):
            continue
        selected.append((skill, candidates[0]))
    if not selected:
        return ""
    sections: list[str] = [
        "[SKILL EXECUTION RULES]",
        "Treat the selected local skill instructions below as active for this request.",
        "These instructions use a portable Markdown contract compatible with Claude, Gemini, GPT, and OpenAI-compatible models.",
        "If the user names a directory or file, use that exact path; do not substitute a default folder such as plugins.",
        "If the user names multiple skills, use all of the named installed skills before responding.",
        "For a code or UI change, inspect the requested target first, then apply the skill guidance while editing it.",
    ]
    for skill, candidate in selected:
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        sections.append(f"[LOCAL SKILL: {skill['name']}]\n{content[:14000]}")
    return "\n\n".join(sections)


def _instruction_files(path: Path) -> list[Path]:
    """Support common skill filenames used by Claude/Gemini/GPT workflows."""
    preferred = ["SKILL.md", "skill.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "GPT.md"]
    files = []
    for name in preferred:
        files.extend(sorted(path.rglob(name)))
    return files or sorted(path.glob("*.md"))[:1]


def _read_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    metadata: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip('"\'')
    return metadata


def _skill_matches(skill: dict, query: str) -> bool:
    """Match explicit skill names first, then frontmatter and content terms."""
    lowered = query.lower()
    name = str(skill.get("name", "")).lower()
    path_name = Path(str(skill.get("path", ""))).name.lower()
    if re.search(rf"(?:@|\b){re.escape(name)}\b|\b{re.escape(path_name)}\b", lowered):
        return True
    description = str(skill.get("description", "")).lower()
    keywords = str(skill.get("keywords", "")).lower()
    terms = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", f"{name} {description} {keywords}"))
    if terms and any(term in lowered for term in terms):
        return True
    if _UI_QUERY_TERMS.search(query) and ("ui" in name or "ux" in name or "web" in name or "frontend" in name):
        return True
    return bool(_UI_QUERY_TERMS.search(query) and _UI_QUERY_TERMS.search(description))