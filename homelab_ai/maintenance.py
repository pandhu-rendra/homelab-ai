"""Installation diagnostics and lifecycle helpers."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import BASE_DIR, ENV_PATH, LOG_DIR, logger


def _venv_python() -> Path:
    if os.name == "nt":
        return BASE_DIR / ".venv" / "Scripts" / "python.exe"
    return BASE_DIR / ".venv" / "bin" / "python"


def doctor() -> str:
    checks: list[str] = []
    checks.append(f"Python: {sys.version.split()[0]}")
    checks.append(f"Install directory: {BASE_DIR}")
    checks.append(f"Environment: {'present' if ENV_PATH.exists() else 'missing'}")
    checks.append(f"Virtual environment: {'present' if _venv_python().exists() else 'missing'}")
    checks.append(f"Logs: {'present' if LOG_DIR.exists() else 'missing'}")
    try:
        import importlib.metadata
        checks.append(f"Installed distributions: {len(list(importlib.metadata.distributions()))}")
    except Exception as exc:
        checks.append(f"Package check: error ({exc})")
    return "HomeLab AI doctor\n" + "\n".join(f"- {item}" for item in checks)


def update() -> str:
    """Update an installed checkout from its configured Git remote."""
    if not (BASE_DIR / ".git").exists():
        return "Update unavailable: this installation is not a Git checkout."
    try:
        subprocess.run(["git", "pull", "--ff-only"], cwd=BASE_DIR, check=True, capture_output=True, text=True)
        python = _venv_python()
        if python.exists():
            subprocess.run([str(python), "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")],
                           cwd=BASE_DIR, check=True, capture_output=True, text=True)
        return "Update completed."
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("Update failed: %s", exc)
        return f"Update failed: {exc}"


def rollback() -> str:
    """Rollback a Git checkout by one commit after a clean update state."""
    if not (BASE_DIR / ".git").exists():
        return "Rollback unavailable: this installation is not a Git checkout."
    try:
        status = subprocess.run(["git", "status", "--porcelain"], cwd=BASE_DIR, check=True,
                                capture_output=True, text=True).stdout.strip()
        if status:
            return "Rollback refused: working tree has local changes."
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=BASE_DIR, check=True,
                       capture_output=True, text=True)
        return "Rollback completed to the previous commit."
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"Rollback failed: {exc}"


def uninstall(install_dir: Path | None = None, *, remove_data: bool = False, confirm: bool = False) -> str:
    """Remove an installation directory only after explicit confirmation."""
    target = (install_dir or BASE_DIR).resolve()
    if target == Path.cwd().resolve() or target == Path.home().resolve():
        return "Uninstall refused for an unsafe target directory."
    if not target.exists():
        return f"Nothing to uninstall: {target}"
    preserved = []
    if not remove_data:
        for name in (".env", "skills", "plugins"):
            source = target / name
            if source.exists():
                preserved.append(name)
    if not confirm:
        return f"Uninstall plan ready for {target}. Re-run with --confirm. Preserved: {', '.join(preserved) or 'none'}."
    if not remove_data:
        for name in (".env", "skills", "plugins"):
            source = target / name
            if source.exists():
                destination = target.parent / f"{target.name}-{name}-backup"
                if destination.exists():
                    shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
                shutil.move(str(source), str(destination))
    shutil.rmtree(target)
    return f"Uninstalled {target}."


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
