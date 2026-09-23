"""Self-healing watchdog: ping internal servers, monitor RAM/CPU, restart services or WOL down hosts."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from homelab_ai.config import BASE_DIR, logger

# ---------------------------------------------------------------------------
# Lazy imports (safe when libs missing)
# ---------------------------------------------------------------------------
_IMPORTS: dict = {}

def _lazy(mod: str):
    if mod not in _IMPORTS:
        try:
            _IMPORTS[mod] = __import__(mod)
        except ImportError:
            return None
    return _IMPORTS[mod]


@dataclass
class HostTarget:
    """A host to monitor."""
    hostname: str
    ip: str
    mac: str = ""                          # for WOL fallback
    label: str = ""
    services: list[str] = field(default_factory=list)
    healthy: bool = True
    last_seen: Optional[datetime] = None


class WatchdogDaemon:
    """Background thread that pings homelab hosts and reacts to failures.

    Usage::

        wd = WatchdogDaemon(
            hosts=[HostTarget("nas", "192.168.1.10", mac="00:11:22:33:44:55")],
            on_fail=lambda h: print(f"{h.label} is down!"),
        )
        wd.start(interval=30)
        # ... later ...
        wd.stop()
    """

    def __init__(
        self,
        hosts: Optional[list[HostTarget]] = None,
        on_fail: Optional[Callable[[HostTarget], None]] = None,
        on_recover: Optional[Callable[[HostTarget], None]] = None,
        config_path: str = "",
    ):
        self.hosts = hosts or []
        self.on_fail = on_fail
        self.on_recover = on_recover
        self.config_path = config_path or str(BASE_DIR / "watchdog_targets.json")
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ---- public API -------------------------------------------------------

    def start(self, interval: int = 30):
        """Start the watchdog loop in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Watchdog already running.")
            return
        self._load_config()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(interval,), daemon=True, name="watchdog"
        )
        self._thread.start()
        logger.info("Watchdog started (interval=%ss, %d hosts).", interval, len(self.hosts))

    def stop(self):
        """Signal the watchdog loop to stop and wait for it."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=interval + 5)
        logger.info("Watchdog stopped.")

    def add_host(self, host: HostTarget):
        self.hosts.append(host)
        self._save_config()

    def remove_host(self, hostname: str):
        self.hosts = [h for h in self.hosts if h.hostname != hostname]
        self._save_config()

    def status_report(self) -> str:
        """Return a human-readable status string for all hosts + local resources."""
        lines = [f"Watchdog — {len(self.hosts)} hosts monitored"]
        for h in self.hosts:
            status = "UP" if h.healthy else "DOWN"
            seen = h.last_seen.isoformat() if h.last_seen else "never"
            lines.append(f"  {h.label or h.hostname:20s} {status:4s} last={seen}")
        lines.append("")
        lines.append(self._local_resources_text())
        return "\n".join(lines)

    # ---- internal -----------------------------------------------------------

    def _load_config(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path) as f:
                data = json.load(f)
            for item in data.get("hosts", []):
                if not any(h.hostname == item["hostname"] for h in self.hosts):
                    self.hosts.append(HostTarget(**item))
        except Exception as exc:
            logger.warning("Could not load watchdog config: %s", exc)

    def _save_config(self):
        try:
            data = {
                "hosts": [
                    {"hostname": h.hostname, "ip": h.ip, "mac": h.mac,
                     "label": h.label, "services": h.services}
                    for h in self.hosts
                ]
            }
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Could not save watchdog config: %s", exc)

    def _loop(self, interval: int):
        while not self._stop_event.is_set():
            self._check_local_resources()
            for host in self.hosts:
                was_healthy = host.healthy
                host.healthy = self._ping_host(host.ip)
                if host.healthy:
                    host.last_seen = datetime.now()
                if not was_healthy and host.healthy:
                    logger.info("Host recovered: %s (%s)", host.label, host.ip)
                    if self.on_recover:
                        self.on_recover(host)
                elif was_healthy and not host.healthy:
                    logger.warning("Host down: %s (%s)", host.label, host.ip)
                    self._react(host)
                    if self.on_fail:
                        self.on_fail(host)
            self._stop_event.wait(interval)

    # ---- ping ---------------------------------------------------------------

    def _ping_host(self, ip: str) -> bool:
        p3 = _lazy("ping3")
        if not p3:
            return True  # can't check — assume healthy
        try:
            rtt = p3.ping(ip, timeout=3)
            return rtt is not None
        except Exception:
            return False

    # ---- reaction handlers --------------------------------------------------

    def _react(self, host: HostTarget):
        """Try to recover a dead host — restart services or send WOL."""
        if host.services:
            for svc in host.services:
                self._restart_service(svc, host)
        if host.mac:
            self._wake_host(host.mac)

    def _restart_service(self, service: str, host: Optional[HostTarget] = None):
        pl = _lazy("plumbum")
        if not pl:
            logger.warning("plumbum not installed — cannot restart %s", service)
            return
        try:
            from plumbum.local import sudo
            sudo["systemctl", "restart", service]()
            logger.info("Restarted service '%s' on %s.", service,
                        host.label if host else "local")
        except Exception as exc:
            logger.error("Failed to restart '%s': %s", service, exc)

    def _wake_host(self, mac: str, broadcast: str = "255.255.255.255"):
        wol = _lazy("wakeonlan")
        if not wol:
            logger.warning("wakeonlan not installed — cannot WOL %s", mac)
            return
        try:
            wol.send_magic_packet(mac, ip_address=broadcast)
            logger.info("WOL sent to %s via %s.", mac, broadcast)
        except Exception as exc:
            logger.error("WOL failed for %s: %s", mac, exc)

    # ---- local resource monitoring ------------------------------------------

    def _check_local_resources(self):
        """Log a warning if RAM or CPU is critically high."""
        psu = _lazy("psutil")
        if not psu:
            return
        try:
            cpu = psu.cpu_percent(interval=1)
            mem = psu.virtual_memory()
            if cpu > 90:
                logger.warning("High CPU: %.1f%%", cpu)
            if mem.percent > 90:
                logger.warning("Low memory: %.1f%% used", mem.percent)
        except Exception as exc:
            logger.warning("Resource check error: %s", exc)

    def _local_resources_text(self) -> str:
        psu = _lazy("psutil")
        if not psu:
            return "psutil not available"
        try:
            cpu = psu.cpu_percent(interval=None)
            mem = psu.virtual_memory()
            disk = psu.disk_usage("/")
            return (f"CPU: {cpu:.1f}% | RAM: {mem.percent:.1f}% "
                    f"({mem.used//1024**3}GB/{mem.total//1024**3}GB) | "
                    f"Disk: {disk.percent:.1f}% "
                    f"({disk.used//1024**3}GB/{disk.total//1024**3}GB)")
        except Exception:
            return "Could not read local resources"
