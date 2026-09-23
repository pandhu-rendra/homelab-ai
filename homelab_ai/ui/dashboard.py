"""Humanized broadcast logs and dashboard helpers using the `humanize` library.

Converts raw bytes, timestamps, and durations into natural-language strings
suitable for console output or TUI widgets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Union

from homelab_ai.config import logger

# ---------------------------------------------------------------------------
# Lazy import
# ---------------------------------------------------------------------------
_IMPORTS: dict = {}

def _lazy(mod: str):
    if mod not in _IMPORTS:
        try:
            _IMPORTS[mod] = __import__(mod)
        except ImportError:
            return None
    return _IMPORTS[mod]


# ---- Bytes -----------------------------------------------------------------

def humanize_bytes(value: Union[int, float], gnu: bool = False) -> str:
    """Convert a byte count to a human-readable string.

    >>> humanize_bytes(1073741824)
    '1.0 GB'
    >>> humanize_bytes(1234567)
    '1.2 MB'
    """
    h = _lazy("humanize")
    if not h:
        return _fallback_bytes(value)
    try:
        return h.naturalsize(value, gnu=gnu)
    except Exception:
        return _fallback_bytes(value)


def _fallback_bytes(value: Union[int, float]) -> str:
    """Fallback when humanize is not installed."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


# ---- Datetime / timestamps -------------------------------------------------

def humanize_datetime(dt: Optional[datetime] = None) -> str:
    """Return a natural-language description of a datetime.

    >>> humanize_datetime(datetime.now())
    'just now'
    """
    h = _lazy("humanize")
    if not h:
        return _fallback_datetime(dt)
    try:
        target = dt or datetime.now()
        return h.naturaltime(target)
    except Exception:
        return _fallback_datetime(dt)


def _fallback_datetime(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now()
    delta = datetime.now() - dt
    secs = delta.total_seconds()
    if secs < 5:
        return "just now"
    if secs < 60:
        return f"{int(secs)} seconds ago"
    if secs < 3600:
        return f"{int(secs // 60)} minutes ago"
    if secs < 86400:
        return f"{int(secs // 3600)} hours ago"
    return f"{int(secs // 86400)} days ago"


# ---- Duration / uptime -----------------------------------------------------

def humanize_duration(seconds: Union[int, float]) -> str:
    """Convert a duration in seconds to natural language.

    >>> humanize_duration(3661)
    '1 hour, 1 minute, 1 second'
    """
    h = _lazy("humanize")
    if not h:
        return _fallback_duration(seconds)
    try:
        return h.naturaldelta(int(seconds))
    except Exception:
        return _fallback_duration(seconds)


def _fallback_duration(seconds: Union[int, float]) -> str:
    parts = []
    for unit, div in (("day", 86400), ("hour", 3600), ("minute", 60)):
        val = int(seconds // div)
        if val:
            parts.append(f"{val} {unit}{'s' if val > 1 else ''}")
        seconds %= div
    secs = int(seconds)
    if secs or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return ", ".join(parts)


# ---- Disk report -----------------------------------------------------------

def format_disk_report() -> str:
    """Return a human-readable disk usage report for all mounted partitions.

    Uses psutil to gather data, then humanize for formatting.
    """
    psu = _lazy("psutil")
    if not psu:
        return "psutil not available"

    h = _lazy("humanize")
    lines = ["--- Disk Usage ---"]
    try:
        for part in psu.disk_partitions():
            if part.fstype and "proc" not in part.fstype:
                try:
                    usage = psu.disk_usage(part.mountpoint)
                    total = humanize_bytes(usage.total)
                    used = humanize_bytes(usage.used)
                    free = humanize_bytes(usage.free)
                    lines.append(
                        f"  {part.mountpoint:20s} {used} / {total} "
                        f"({usage.percent:.1f}%) — {free} free"
                    )
                except PermissionError:
                    pass
        return "\n".join(lines)
    except Exception as exc:
        return f"Error reading disk info: {exc}"


# ---- System status (all-in-one) --------------------------------------------

def format_system_status() -> str:
    """Return a humanized snapshot of CPU, RAM, disk, and boot time."""
    psu = _lazy("psutil")
    if not psu:
        return "psutil not available"

    import time as _time
    lines = ["=== System Status ==="]
    try:
        cpu = psu.cpu_percent(interval=0.5)
        lines.append(f"CPU: {cpu:.1f}%")

        mem = psu.virtual_memory()
        lines.append(
            f"RAM: {humanize_bytes(mem.used)} / {humanize_bytes(mem.total)} "
            f"({mem.percent:.1f}%)"
        )

        disk = psu.disk_usage("/")
        lines.append(
            f"Disk: {humanize_bytes(disk.used)} / {humanize_bytes(disk.total)} "
            f"({disk.percent:.1f}%) — {humanize_bytes(disk.free)} free"
        )

        boot = datetime.fromtimestamp(psu.boot_time())
        uptime_secs = _time.time() - psu.boot_time()
        lines.append(f"Boot: {boot.isoformat()} ({humanize_datetime(boot)})")
        lines.append(f"Uptime: {humanize_duration(uptime_secs)}")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"
