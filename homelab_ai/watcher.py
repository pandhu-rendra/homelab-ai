"""Live filesystem watching via **watchfiles**.

Runs in a background thread and reports created/modified/deleted files in the
working directory, so the TUI can surface edits the agent (or the user) makes —
the way Claude Code shows a running list of touched files.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from watchfiles import Change, watch

ChangeCallback = Callable[[str, str], None]  # (change_type, path)

_CHANGE_NAMES = {Change.added: "added", Change.modified: "modified", Change.deleted: "deleted"}

_IGNORE_PARTS = {".git", "__pycache__", ".venv", "node_modules", "history", "shots"}
_IGNORE_FILES = {"chat_history_persistent.json", "autocompleter.db", "agent_log.txt"}
_IGNORE_SUFFIXES = (".db-journal", ".db-wal", ".db-shm", ".pyc", ".swp", ".tmp")


def _ignored(path: str) -> bool:
    p = Path(path)
    if p.name in _IGNORE_FILES:
        return True
    if path.endswith(_IGNORE_SUFFIXES):
        return True
    return any(part in _IGNORE_PARTS for part in p.parts)


class FileWatcher:
    def __init__(self, root: str, on_change: ChangeCallback) -> None:
        self.root = root
        self.on_change = on_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="homelab-watcher", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for changes in watch(self.root, stop_event=self._stop, debounce=400):
                for change, path in changes:
                    if _ignored(path):
                        continue
                    self.on_change(_CHANGE_NAMES.get(change, "changed"), path)
        except Exception:  # noqa: BLE001 - watcher must never crash the app
            return

    def stop(self) -> None:
        self._stop.set()
