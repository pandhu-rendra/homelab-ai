"""Runtime OS / environment detection (brain helper, bug-fixed)."""
from __future__ import annotations

import platform
from pathlib import Path


def get_os_context() -> str:
    """Detect OS and distro in real time for Windows and Linux."""
    current_os = platform.system()

    if current_os == "Windows":
        return f"Windows {platform.release()} (Environment: PowerShell/CMD)"

    if current_os == "Linux":
        release_file = Path("/etc/os-release")
        if release_file.exists():
            try:
                for line in release_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        pretty = line.split("=", 1)[1].strip().strip('"')
                        return f"Linux ({pretty})"
            except Exception:
                pass
        return f"Linux ({platform.release()})"

    if current_os == "Darwin":
        return f"macOS {platform.mac_ver()[0]} (Environment: zsh/bash)"

    return current_os
