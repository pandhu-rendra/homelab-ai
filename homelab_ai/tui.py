"""HomeLab AI — Textual TUI.

A Claude-Code / Blackbox-style terminal UI: a streaming conversation pane, a
live context + file-activity sidebar, slash commands and an approval modal for
file edits. The agent runs in a worker thread (LangGraph) and streams events
back into the UI via ``call_from_thread``.
"""
from __future__ import annotations

import getpass
import os
import re
import subprocess
import threading
import time
from typing import Optional

from rich.box import HEAVY, ROUNDED
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Footer, Input, RichLog, Static, TabbedContent, TabPane


from . import __version__
from .config import (
    CONFIG_META,
    ENV_PATH,
    HISTORY_JSON_FILE,
    MAX_ATTEMPTS,
    PROVIDER_LOG_FILE,
    keys_present,
    provider_logger,
    save_env as save_env_config,
)
from .graph import build_agent
from .llm import SYSTEM_PROMPT, get_provider_list, reinit_providers, trim_chat_history
from .agent_profiles import (
    create_agent,
    delete_agent,
    edit_agent,
    list_agents,
    set_agent_enabled,
)
from .memory import (
    get_tool_stats,
    learn_from_conversation,
    record_tool_call,
    build_memory_context,
    save_preference,
)
from .plugin_installer import (
    install_plugin,
    list_plugins,
    load_registry_plugins,
    remove_plugin,
    hot_reload,
)
from .osinfo import get_os_context
from .plugin_manager import apply_after_query, discover_plugins
from .skill_manager import install_skill, list_skills, remove_skill, UI_UX_SOURCE
from .schemas import tool_manifest
from .storage import (
    export_session_to_markdown,
    get_all_keywords,
    init_autocomplete_db,
    learn_new_words,
    load_history_from_json,
    save_history_to_json,
)

ACCENT = "#7c6cf0"
ACCENT2 = "#36d399"

# Slash commands list for autocomplete
SLASH_COMMANDS = [
    "help", "clear", "save", "tools", "history",
    "agent", "model", "config", "plugin", "skill",
    "rename", "plan", "code", "dry-run", "branch", "search", "notify",
]


class KeywordSuggester(Suggester):
    """Suggestions from keyword DB, plus /commands, @files, and context-aware."""

    async def get_suggestion(self, value: str) -> str | None:
        if not value or len(value) < 2:
            return None
        if value.startswith("/"):
            cmd = value[1:].lower()
            for c in SLASH_COMMANDS:
                if c.startswith(cmd) and c != cmd:
                    return f"/{c} [dim]{_cmd_desc(c)}[/dim]"
            return None
        if value.startswith("@"):
            prefix = value[1:].lower()
            try:
                for entry in os.scandir("."):
                    if entry.name.startswith("."):
                        continue
                    if entry.name.lower().startswith(prefix) and entry.name.lower() != prefix:
                        return f"@{entry.name}"
            except Exception:
                pass
            return None
        lowered = value.lower()
        # Check for common question patterns and suggest actions
        if any(w in lowered for w in ["system", "stats", "cpu", "ram"]):
            return "system stats [dim]→ get_system_stats[/dim]"
        if any(w in lowered for w in ["docker", "container"]):
            return "docker ps [dim]→ list containers[/dim]"
        if any(w in lowered for w in ["file", "list", "dir"]):
            return "list files [dim]→ list_dir[/dim]"
        if any(w in lowered for w in ["search", "find"]):
            return "search: <query> [dim]→ web search[/dim]"
        if any(w in lowered for w in ["deploy", "compose", "up"]):
            return "/plan docker compose up [dim]→ planner[/dim]"
        if any(w in lowered for w in ["kube", "k8s", "pod", "deployment"]):
            return "/plan kubernetes deploy [dim]→ planner[/dim]"
        try:
            keywords = get_all_keywords()
        except Exception:
            return None
        matches = [kw for kw in keywords if kw.startswith(lowered)]
        return matches[0] if matches else None


def _cmd_desc(cmd: str) -> str:
    """Return a short description for a slash command."""
    descs = {
        "help": "show help", "clear": "clear chat", "save": "export session",
        "tools": "list tools", "history": "session stats", "agent": "switch provider",
        "config": "settings", "plugin": "plugin manager",
        "rename": "rename tab", "plan": "multi-step planner",
        "code": "coding mode with verification", "dry-run": "preview edits without writing",
        "branch": "fork conversation", "search": "search transcript",
        "notify": "test notification",
    }
    return descs.get(cmd, "")


class PatchApproveScreen(ModalScreen[bool]):
    """Modal showing a unified diff and asking the user to apply or reject."""

    BINDINGS = [
        Binding("y", "approve", "Apply"),
        Binding("n", "reject", "Reject"),
        Binding("escape", "reject", "Reject"),
    ]

    def __init__(self, file_path: str, diff: str) -> None:
        super().__init__()
        self._file_path = file_path
        self._diff = diff

    def compose(self) -> ComposeResult:
        diff_render = Syntax(self._diff or "(no changes)", "diff", theme="ansi_dark", word_wrap=True)
        body = Group(
            Text.from_markup(f"[bold]Proposed edit to[/bold] [cyan]{self._file_path}[/cyan]"),
            Rule(style="grey42"),
            diff_render,
            Rule(style="grey42"),
            Text.from_markup("[bold green]y[/bold green] apply    [bold red]n[/bold red] reject"),
        )
        yield Static(Panel(body, title="Code Proposal", border_style=ACCENT, box=ROUNDED), id="patch-card")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)


class AgentSelectScreen(ModalScreen[str]):
    """Modal to pick the active LLM provider/agent."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        providers = get_provider_list()
        rows = Table.grid(padding=(0, 2))
        rows.add_column(style=f"bold {ACCENT2}")
        rows.add_column(style="grey74")
        for p in providers:
            rows.add_row(p, "")
        body = Group(
            Text.from_markup(f"[bold {ACCENT}]Select Agent[/bold {ACCENT}]"),
            Rule(style="grey42"),
            Text("\n".join(f"  {i+1}. {p}" for i, p in enumerate(providers)) or "  (no providers registered)"),
            Rule(style="grey42"),
            Text.from_markup("[dim]Type a number or agent name, or Escape to cancel.[/dim]"),
        )
        yield Static(Panel(body, border_style=ACCENT, box=ROUNDED), id="agent-card")
        yield Input(placeholder="Agent name…", id="agent-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if not val:
            return
        providers = get_provider_list()
        # Try number first
        try:
            idx = int(val) - 1
            if 0 <= idx < len(providers):
                self.dismiss(providers[idx])
                return
        except ValueError:
            pass
        # Try name match
        for p in providers:
            if p.lower().startswith(val.lower()):
                self.dismiss(p)
                return
        self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")


class SearchInChatScreen(ModalScreen[str]):
    """Modal for searching text in the current transcript."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "search_next", "Next"),
    ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search transcript…", id="search-input")
        yield Static("", id="search-status")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_search_next()

    def action_cancel(self) -> None:
        self.dismiss("")

    def action_search_next(self) -> None:
        query = self.query_one("#search-input", Input).value.strip()
        if not query:
            return
        try:
            app = self.app
            tid = app.active_tab_id or "tab_1"  # type: ignore[attr-defined]
            log_id = f"transcript_{tid}"
            app.query_one(f"#{log_id}", RichLog)  # type: ignore[attr-defined]
            # Trigger search by sending signal back to app
            app._search_in_transcript(query)  # type: ignore[attr-defined]
            self.query_one("#search-status", Static).update(f"Searching for: {query}")
        except Exception:
            pass


class PlanApproveScreen(ModalScreen[list[str]]):
    """Modal showing a multi-step plan and asking user to approve/reject."""

    BINDINGS = [
        Binding("y", "approve", "Execute All"),
        Binding("n", "reject", "Cancel"),
        Binding("escape", "reject", "Cancel"),
        Binding("space", "toggle_step", "Toggle Step"),
    ]

    def __init__(self, steps: list[str]) -> None:
        super().__init__()
        self.steps = steps
        self.selected = set(range(len(steps)))
        self._focus_idx = 0

    def compose(self) -> ComposeResult:
        body = Group(
            Text.from_markup("[bold]Proposed Execution Plan[/bold]"),
            Rule(style="grey42"),
        )
        for i, step in enumerate(self.steps):
            icon = "✓" if i in self.selected else "○"
            body.renderables.append(
                Text.from_markup(f"  [{icon}] Step {i+1}: {step}")
            )
        body.renderables.extend([
            Rule(style="grey42"),
            Text.from_markup("[bold green]y[/bold green] execute    [bold red]n[/bold red] cancel    [dim]Space to toggle[/dim]"),
        ])
        yield Static(Panel(body, title="Execution Plan", border_style="#7c6cf0", box=ROUNDED), id="plan-card")

    def action_approve(self) -> None:
        steps = [self.steps[i] for i in sorted(self.selected)]
        self.dismiss(steps)

    def action_reject(self) -> None:
        self.dismiss([])

    def action_toggle_step(self) -> None:
        if self.steps:
            i = self._focus_idx % len(self.steps)
            if i in self.selected:
                self.selected.discard(i)
            else:
                self.selected.add(i)
            self._focus_idx = (i + 1) % len(self.steps)


# ── command palette providers ──────────────────────────────────────────────

class HomeLabCommands(Provider):
    COMMANDS: dict[str, str] = {
        "clear chat": "clear_chat",
        "save session": "save_session",
        "new tab": "new_tab",
        "close tab": "close_tab",
        "copy response": "copy",

        "open url": "open_link",
        "rename tab": "rename_tab",
        "search chat": "search_chat",
        "next tab": "next_tab",
        "show help": "show_help",
        "switch agent": "select_agent",
    }

    async def search(self, query: str) -> Hits:
        for desc, action in self.COMMANDS.items():
            if query.lower() in desc.lower():
                def cb(action=action) -> None:
                    self.app.action_forward(action)
                yield Hit(1, desc, cb, help=f"Run /{action}")


class HomeLabApp(App):
    TITLE = "HomeLab AI"
    SUB_TITLE = f"v{__version__}"
    COMMANDS: set[type[Provider]] = App.COMMANDS | {HomeLabCommands}
    COMMAND_PALETTE_DISPLAY = "Commands"

    CSS = """
    Screen { background: #0b0d12; }

    #body { height: 1fr; }

    #tabs {
        width: 3fr;
        border: round #2a2f3a;
    }
    #tabs > TabPane { background: #0e1118; }
    #tabs > TabPane > RichLog {
        padding: 0 1;
        scrollbar-color: #7c6cf0;
    }
    #tabs > TabPane > RichLog > .text-line:ansi {
        background: #36d399;
        color: #0b0d12;
    }

    #thought_bar {
        height: auto;
        margin: 0 1;
        background: #11141d;
        color: #888;
    }
    #thought_bar:empty { height: 0; }

    #sidebar {
        width: 34;
        background: #0e1118;
        border: round #2a2f3a;
        padding: 0 1;
    }
    #sidebar Static { margin-bottom: 1; }

    #statusbar {
        height: 1;
        background: #11141d;
        color: #cdd3e0;
        padding: 0 1;
    }

    #prompt {
        border: round #7c6cf0;
        background: #11141d;
    }
    #prompt:focus { border: round #36d399; }

    PatchApproveScreen { align: center middle; }
    #patch-card { width: 90%; max-width: 110; height: auto; max-height: 80%; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True, show=True),
        Binding("ctrl+c", "copy", "Copy", priority=True, show=False),
        Binding("ctrl+shift+v", "paste", "Paste", show=False),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
        Binding("ctrl+s", "save_session", "Save", show=False),
        Binding("ctrl+t", "new_tab", "New Tab", show=False),
        Binding("ctrl+w", "close_tab", "Close Tab", show=False),
        Binding("ctrl+tab", "next_tab", "Next Tab", show=False),
        Binding("ctrl+a", "select_agent", "Agent", show=False),
        Binding("ctrl+f", "search_chat", "Search", show=False),
        Binding("ctrl+o", "open_link", "Open URL", show=False),
        Binding("f1", "show_help", "Help", show=True),
        Binding("f2", "rename_tab", "Rename", show=False),
        Binding("escape", "cancel_run", "Cancel", priority=True, show=True),
    ]


    provider: reactive[str] = reactive("—", init=False)
    attempt: reactive[str] = reactive("—", init=False)
    latency: reactive[str] = reactive("—", init=False)
    busy: reactive[bool] = reactive(False, init=False)

    def __init__(self, force_demo: bool = False) -> None:
        super().__init__()
        self.username = getpass.getuser()
        self.os_context = get_os_context()
        self.force_demo = force_demo
        self.demo_mode = force_demo or not keys_present()
        self._preferred_provider: str = ""
        self._active_agent_profile: str = ""
        provider_logger.debug(
            "STARTUP | force_demo=%s | keys_present=%s | demo_mode=%s",
            force_demo, keys_present(), self.demo_mode,
        )
        self._tabs: dict[str, list[dict]] = {}          # tab_id -> conversation
        self._tab_order: list[str] = ["tab_1"]           # ordered tab IDs for navigation
        self._tab_counter = 0
        self._active_tab_for_run: str = "tab_1"
        self._approval_event: Optional[threading.Event] = None
        self._cancel_event = threading.Event()
        self._approval_result = False
        self._file_events: list[str] = []
        self._watcher = None
        self._msg_counter = 0
        self._msg_map: dict[int, str] = {}
        self._select_start: Optional[int] = None
        self._select_tid: Optional[str] = None
        self._stream_buf: str = ""
        self._stream_panel = None
        init_autocomplete_db()

    def _new_conversation(self) -> list[dict]:
        from .llm import SYSTEM_PROMPT
        return [{"role": "system", "content": SYSTEM_PROMPT}]

    @property
    def active_tab_id(self) -> str:
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            return tabs.active or "tab_1"
        except Exception:
            return "tab_1"

    @property
    def conversation(self) -> list[dict]:
        tid = self.active_tab_id
        if tid not in self._tabs:
            self._tabs[tid] = self._new_conversation()
        return self._tabs[tid]

    @conversation.setter
    def conversation(self, val: list[dict]) -> None:
        self._tabs[self.active_tab_id] = val

    # ----------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Static(self._status_line(), id="statusbar")
        with Horizontal(id="body"):
            with TabbedContent(initial="tab_1", id="tabs"):
                with TabPane("Session 1", id="tab_1"):
                    yield RichLog(
                        id="transcript_tab_1",
                        wrap=True,
                        markup=True,
                        highlight=True,
                    )
            with Vertical(id="sidebar"):
                yield Static(id="context")
                yield Static(id="analytics")
                yield Static(id="files")
        yield Static(id="thought_bar")
        yield Input(
            placeholder="Ask anything…  (/help for commands)",
            id="prompt",
            suggester=KeywordSuggester(),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self._last_usage = {"prompt": 0, "completion": 0, "total": 0}
        self._active_tab_for_run = "tab_1"
        self._tabs["tab_1"] = self._new_conversation()
        # Restore cross-session preferences
        try:
            from .memory import load_preference
            saved_provider = load_preference("provider")
            if saved_provider and saved_provider in get_provider_list():
                self._preferred_provider = saved_provider
        except Exception:
            pass
        self.provider = self._preferred_provider or "auto"
        self._refresh_status()
        # Discover plugins early
        discover_plugins()
        self._render_context()
        self._render_analytics()
        self._render_files()
        self._print_welcome()
        self._start_watcher()
        saved = load_history_from_json()
        if saved:
            stale_markers = (
                "mode offline (demo)",
                "semua penyedia ai",
                "all providers failed",
                "providers unavailable",
            )
            cleaned = [
                message for message in saved
                if message.get("role") != "assistant"
                or not any(marker in message.get("content", "").lower()
                           for marker in stale_markers)
            ]
            self._tabs["tab_1"] = cleaned
            self._log(Text.from_markup(f"[dim]Loaded {len(saved)} messages from previous session.[/dim]"))

    # ----------------------------------------------------------------- helpers
    def _status_line(self) -> Text:
        dot = "[#36d399]●[/#36d399]" if not getattr(self, "demo_mode", False) else "[#f5a623]●[/#f5a623]"
        mode = "DEMO" if getattr(self, "demo_mode", False) else "LIVE"
        return Text.from_markup(
            f"{dot} [bold]HomeLab AI[/bold] [dim]{mode}[/dim]"
            f"  │ 👤 {getattr(self, 'username', '')}  "
            f"│ 🖥  {getattr(self, 'os_context', '')}  "
            f"│ ⚙ {self.provider}  │ ⏱ {self.latency}"
        )

    def _refresh_status(self) -> None:
        try:
            self.query_one("#statusbar", Static).update(self._status_line())
        except Exception:  # noqa: BLE001 - status bar not mounted yet
            pass

    def watch_provider(self) -> None:
        self._refresh_status()
        try:
            self._render_context()
        except Exception:  # noqa: BLE001
            pass

    def watch_latency(self) -> None:
        self._refresh_status()
        try:
            self._render_context()
        except Exception:
            pass

    def on_unmount(self) -> None:
        if self._watcher:
            self._watcher._stop.set()
        from .memory import close_connection
        close_connection()

    def _log(self, renderable) -> None:
        """Write to the active tab's transcript."""
        tid = self.active_tab_id
        log_id = f"transcript_{tid}"
        try:
            self.query_one(f"#{log_id}", RichLog).write(renderable)
        except Exception:
            try:
                self.query_one("#transcript_tab_1", RichLog).write(renderable)
            except Exception:
                pass

    def _render_context(self) -> None:
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left", style="dim")
        table.add_column(justify="left")
        table.add_row("OS", self.os_context)
        table.add_row("Engine", str(self.provider))
        attempt_limit = "unlimited" if MAX_ATTEMPTS == 0 else str(MAX_ATTEMPTS)
        table.add_row("Attempt", f"{self.attempt}/{attempt_limit}")
        table.add_row("Latency", str(self.latency))
        table.add_row("Mode", "Demo" if self.demo_mode else "Live")
        u = self._last_usage
        if u.get("total", 0):
            try:
                from .llm import _lookup_model
                info = _lookup_model(str(self.provider))
                ctx = info.get("ctx", 131072)
                inp = info.get("input", 1.0)
                out = info.get("output", 2.0)
                pct = min(u["total"] / ctx * 100, 100.0)
                cost = (u.get("prompt", 0) * inp + u.get("completion", 0) * out) / 1_000_000
                table.add_row("Tokens", f"{u['total']:,} / {ctx:,} ({pct:.1f}%)")
                table.add_row("Spent", f"${cost:.6f}")
            except Exception:
                table.add_row("Tokens", f"{u['total']:,}")
        panel = Panel(table, title="🧭 Context", border_style=ACCENT, box=ROUNDED)
        self.query_one("#context", Static).update(panel)

    def _set_thought(self, msg: str) -> None:
        try:
            self.query_one("#thought_bar", Static).update(Text.from_markup(f"[dim]{msg}[/dim]"))
        except Exception:
            pass

    def _render_analytics(self) -> None:
        try:
            stats = get_tool_stats()
            if not stats:
                body = Text("No tool data yet.", style="dim")
            else:
                table = Table.grid(padding=(0, 1))
                table.add_column(style=f"bold {ACCENT2}")
                table.add_column(style="grey74")
                table.add_column(style="grey42")
                total_calls = sum(s["call_count"] for s in stats)
                total_errs = sum(s["error_count"] for s in stats)
                top = sorted(stats, key=lambda x: x["call_count"], reverse=True)[:5]
                for s in top:
                    err_mark = f" [red]✗{s['error_count']}[/red]" if s["error_count"] else ""
                    table.add_row(s["tool_name"], str(s["call_count"]) + err_mark, "")
                body = Group(
                    Text.from_markup(f"[dim]Tool calls: {total_calls}  Errors: {total_errs}[/dim]"),
                    table,
                )
            panel = Panel(body, title="⚡ Tool Health", border_style="grey42", box=ROUNDED)
            self.query_one("#analytics", Static).update(panel)
        except Exception:
            pass

    def _render_files(self) -> None:
        if self._file_events:
            body = Text("\n".join(self._file_events[-12:]))
        else:
            body = Text("No file activity yet.", style="dim")
        panel = Panel(body, title="📁 File Activity", border_style="grey42", box=ROUNDED)
        self.query_one("#files", Static).update(panel)

    def _print_welcome(self) -> None:
        mode_str = f"[bold #36d399]LIVE[/bold #36d399]" if not self.demo_mode else "[#f5a623]DEMO[/#f5a623]"
        prov_str = self._preferred_provider or "auto"
        logo = (
            f"[bold {ACCENT}]┓┏┏┓┳┳┓┏┓┓ ┏┓┳┓[/bold {ACCENT}]  [bold white]HomeLab AI[/bold white] [dim]v{__version__}[/dim]\n"
            f"[bold {ACCENT}]┣┫┃┃┃┃┃┣ ┃ ┣┫┣┫[/bold {ACCENT}]  [grey58]Terminal AI companion[/grey58]\n"
            f"[bold {ACCENT}]┛┗┗┛┛ ┗┗┛┗┛┛┗┻┛[/bold {ACCENT}]  [grey58]{mode_str} · Agent: [bold]{prov_str}[/bold][/grey58]"
        )
        sep = f"[dim]─[/dim]" * 56
        binds = Table.grid(padding=(0, 2))
        binds.add_column(style=f"bold {ACCENT2}")
        binds.add_column(style="grey54")
        binds.add_row("Ctrl+P", "command palette")
        binds.add_row("/help · F1", "help")
        binds.add_row("/clear · Ctrl+L", "clear conversation")
        binds.add_row("/save · Ctrl+S", "save session")
        binds.add_row("/agent · Ctrl+A", "switch agent")
        binds.add_row("Ctrl+C", "copy selected text or last response")
        binds.add_row("Ctrl+Shift+V", "paste")
        binds.add_row("Ctrl+O", "open URL")
        binds.add_row("/tools", "tool list")
        binds.add_row("/code <request>", "coding mode: inspect -> edit -> verify -> test")
        binds.add_row("/dry-run <request>", "preview edits without writing files")
        binds.add_row("/config", "set API key / model")
        binds.add_row("@file", "attach file")
        binds.add_row("search: <q>", "force web search")
        body = Group(
            logo,
            Text.from_markup(f"\n{sep}"),
            binds,
        )
        self._log(Panel(body, border_style=ACCENT, box=HEAVY))

    # ----------------------------------------------------------------- watcher
    def _start_watcher(self) -> None:
        from .watcher import FileWatcher

        def on_change(change_type: str, path: str) -> None:
            rel = os.path.relpath(path, os.getcwd())
            icon = {"added": "＋", "modified": "✎", "deleted": "✗"}.get(change_type, "•")
            self.call_from_thread(self._note_file_change, f"{icon} {rel}")

        self._watcher = FileWatcher(os.getcwd(), on_change)
        self._watcher.start()

    def _note_file_change(self, line: str) -> None:
        self._file_events.append(line)
        self._render_files()

    # ----------------------------------------------------------------- input
    @on(Input.Submitted, "#prompt")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if self.busy:
            self.notify("Agent is busy — please wait.", severity="warning")
            return
        if text.startswith("/") or text.lower() in ("exit", "quit", "bye", "clear"):
            self._handle_command(text)
            return
        self._submit_query(text)

    def on_click(self, event: events.Click) -> None:
        style = event.style
        if style and style.link:
            link = str(style.link)
            if link.startswith("copy:"):
                try:
                    mid = int(link.split(":", 1)[1])
                    text = self._msg_map.get(mid)
                    if text:
                        self.copy_to_clipboard(self._extract_copyable_text(text))
                        self.notify("Copied message to clipboard")
                    else:
                        self.notify("Message not found", severity="warning")
                except (ValueError, IndexError):
                    self.notify("Invalid copy link", severity="warning")
            elif link.startswith("copy-code:"):
                try:
                    mid = int(link.split(":", 1)[1])
                    text = self._msg_map.get(mid)
                    if text:
                        code = self._extract_copyable_code(text)
                        if code:
                            self.copy_to_clipboard(code)
                            self.notify("Copied code block to clipboard")
                        else:
                            self.notify("No code block found in this message", severity="warning")
                    else:
                        self.notify("Message not found", severity="warning")
                except (ValueError, IndexError):
                    self.notify("Invalid copy link", severity="warning")
            else:
                self.open_url(link)
            event.stop()
            return

        # Let RichLog handle ordinary clicks and drag selection. Ctrl+C then
        # reads the selected range through action_copy; only explicit copy
        # links above should copy an entire assistant message.

    def _handle_command(self, text: str) -> None:
        cmd = text.lstrip("/").lower().strip()
        if cmd in ("exit", "quit", "bye"):
            self.action_quit()
        elif cmd == "clear":
            self.action_clear_chat()
        elif cmd == "help":
            self.action_show_help()
        elif cmd == "save":
            self.action_save_session()
        elif cmd == "tools":
            self._show_tools()
        elif cmd == "history":
            self._show_history_summary()
        elif cmd in ("agent", "model"):
            self._handle_agent_command(cmd)
        elif cmd.startswith("config"):
            self._handle_config(cmd)
        elif cmd.startswith("plugin"):
            self._handle_plugin(cmd)
        elif cmd.startswith("skill"):
            self._handle_skill(cmd)
        elif cmd.startswith("rename"):
            parts = cmd.split(maxsplit=1)
            new_name = parts[1].strip() if len(parts) > 1 else ""
            self.action_rename_tab(new_name)
        elif cmd.startswith("plan"):
            parts = cmd.split(maxsplit=1)
            goal = parts[1].strip() if len(parts) > 1 else ""
            self._start_plan_mode(goal)
        elif cmd.startswith("dry-run"):
            prompt = cmd[len("dry-run"):].strip()
            self._submit_query(prompt, dry_run=True)
        elif cmd.startswith("code"):
            prompt = cmd[len("code"):].strip()
            self._submit_query(prompt, coding_mode=True)
        elif cmd.startswith("branch"):
            self.action_branch_conversation()
        elif cmd.startswith("search"):
            self.action_search_chat()

        else:
            self.notify(f"Unknown command: /{cmd}", severity="warning")

    def _handle_agent_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else "provider"
        name = parts[2].strip() if len(parts) > 2 else ""
        if sub in {"provider", "model"}:
            self.action_select_agent()
        elif sub == "list":
            agents = list_agents()
            if not agents:
                self._log(Text.from_markup("[dim]No user agents yet. Use /agent create <name>.[/dim]"))
                return
            table = Table.grid(padding=(0, 2))
            table.add_column(style=f"bold {ACCENT2}")
            table.add_column(style="grey74")
            table.add_column(style="grey42")
            for profile in agents:
                marker = "active" if profile["name"] == self._active_agent_profile else "idle"
                state = "enabled" if profile["enabled"] else "disabled"
                table.add_row(profile["name"], f"{state} · {marker}", profile["description"][:60])
            self._log(Panel(table, title="User Agents", border_style=ACCENT, box=ROUNDED))
        elif sub == "create":
            if not name:
                self.notify("Usage: /agent create <name>", severity="warning")
                return
            result = create_agent(name)
            if result["ok"]:
                self._log(Text.from_markup(
                    f"[green]Agent created:[/green] {result['path']}\n"
                    f"Edit it with [bold]/agent edit {name}[/bold], then use [bold]/agent use {name}[/bold]."
                ))
            else:
                self.notify(result["error"], severity="warning")
        elif sub == "use":
            if not name or not any(p["name"].lower() == name.lower() and p["enabled"] for p in list_agents()):
                self.notify(f"Enabled agent not found: {name}", severity="warning")
                return
            self._active_agent_profile = name
            self._set_thought(f"Agent profile: {name}")
            self._render_context()
        elif sub in {"enable", "disable"}:
            if not name:
                self.notify(f"Usage: /agent {sub} <name>", severity="warning")
                return
            message = set_agent_enabled(name, sub == "enable")
            self._log(Text.from_markup(f"[dim]{message}[/dim]"))
        elif sub == "delete":
            if not name:
                self.notify("Usage: /agent delete <name>", severity="warning")
                return
            message = delete_agent(name)
            if self._active_agent_profile.lower() == name.lower():
                self._active_agent_profile = ""
            self._log(Text.from_markup(f"[dim]{message}[/dim]"))
        elif sub == "edit":
            if not name:
                self.notify("Usage: /agent edit <name>", severity="warning")
                return
            self._log(Text.from_markup(f"[dim]{edit_agent(name)}[/dim]"))
        else:
            self.notify("Use /agent list|create|use|enable|disable|edit|delete", severity="warning")

    def _handle_plugin(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=2)
        sub = parts[1] if len(parts) > 1 else "help"
        if sub == "help":
            self._log(Panel(
                Text.from_markup(
                    "[bold]Plugin Manager[/bold]\n\n"
                    "  [bold]/plugin list[/bold]              – installed plugins\n"
                    "  [bold]/plugin install <url|gh:...>[/bold]  – install from URL/GitHub\n"
                    "  [bold]/plugin remove <name>[/bold]      – remove a plugin\n"
                    "  [bold]/plugin registry[/bold]           – list remote registry\n"
                    "  [bold]/plugin reload[/bold]             – hot-reload all plugins\n\n"
                    "Examples:\n"
                    "  /plugin install gh:owner/repo\n"
                    "  /plugin install https://example.com/my_plugin.py"
                ),
                title="Plugin Commands", border_style=ACCENT, box=ROUNDED,
            ))
        elif sub == "list":
            plugins = list_plugins()
            if not plugins:
                self._log(Text.from_markup("[dim]No plugins installed.[/dim]"))
                return
            table = Table.grid(padding=(0, 2))
            table.add_column(style=f"bold {ACCENT2}")
            table.add_column(style="grey74")
            table.add_column(style="grey42")
            for p in plugins:
                table.add_row(
                    p["name"],
                    p["filename"],
                    f"{p['size']} B" + (" · portable" if p.get("portable_manifest") else ""),
                )
            self._log(Panel(table, title="Installed Plugins", border_style=ACCENT, box=ROUNDED))
        elif sub == "registry":
            registry = load_registry_plugins()
            if not registry:
                self._log(Text.from_markup("[dim]Failed to load registry (check connection).[/dim]"))
                return
            table = Table.grid(padding=(0, 2))
            table.add_column(style=f"bold {ACCENT2}")
            table.add_column(style="grey74")
            for p in registry:
                desc = p.get("description", p.get("desc", ""))[:60]
                table.add_row(p["name"], desc)
            self._log(Panel(
                table, title="Remote Plugin Registry",
                border_style=ACCENT, box=ROUNDED,
            ))
        elif sub == "install":
            if len(parts) < 3:
                self._log(Text.from_markup("[red]Use: /plugin install <url|gh:owner/repo>[/red]"))
                return
            source = parts[2]
            self._log(Text.from_markup(f"[dim]⏬ Installing plugin from {source}…[/dim]"))
            result = install_plugin(source)
            if result["ok"]:
                hot_reload()
                self._log(Text.from_markup(
                    f"[bold #36d399]✓ Plugin installed: {result['path']}[/bold #36d399]"
                ))
                self.notify(f"Plugin installed → {result['path']}")
            else:
                self._log(Text.from_markup(f"[red]✗ Failed: {result.get('error', 'unknown error')}[/red]"))
                self.notify(f"Install failed: {result.get('error')}", severity="error")
        elif sub == "remove":
            if len(parts) < 3:
                self._log(Text.from_markup("[red]Use: /plugin remove <name>[/red]"))
                return
            name = parts[2]
            result = remove_plugin(name)
            if result["ok"]:
                hot_reload()
                self._log(Text.from_markup(f"[bold #36d399]✓ Plugin removed: {name}[/bold #36d399]"))
            else:
                self._log(Text.from_markup(f"[red]✗ {result.get('error', 'unknown error')}[/red]"))
        elif sub == "reload":
            count = hot_reload()
            self._log(Text.from_markup(f"[dim]Plugin reloaded: {count} detected.[/dim]"))
            self.notify(f"Reloaded {count} plugins.")
        else:
            self._log(Text.from_markup(f"[red]Unknown subcommand: /plugin {sub}[/red]"))
            self._log(Text.from_markup("[dim]Use /plugin help for assistance.[/dim]"))

    def _handle_skill(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=2)
        sub = parts[1] if len(parts) > 1 else "list"
        if sub == "help":
            self._log(Text.from_markup(
                "[bold]Skill Manager[/bold]\n\n"
                "  [bold]/skill install <gh:owner/repo>[/bold]  – install an AI skill\n"
                "  [bold]/skill list[/bold]                         – installed skills\n"
                "  [bold]/skill remove <name>[/bold]               – remove a skill\n\n"
                f"Example: /skill install {UI_UX_SOURCE}"
            ))
        elif sub == "list":
            skills = list_skills()
            if not skills:
                self._log(Text.from_markup("[dim]No skills installed.[/dim]"))
                return
            table = Table.grid(padding=(0, 2))
            table.add_column(style=f"bold {ACCENT2}")
            table.add_column(style="grey74")
            for skill in skills:
                table.add_row(skill["name"], "ready" if skill["has_instructions"] else "missing SKILL.md")
            self._log(Panel(table, title="Installed Skills", border_style=ACCENT, box=ROUNDED))
        elif sub == "install":
            if len(parts) < 3:
                self._log(Text.from_markup(f"[red]Use: /skill install {UI_UX_SOURCE}[/red]"))
                return
            source = parts[2]
            self._log(Text.from_markup(f"[dim]Installing skill from {source}…[/dim]"))
            result = install_skill(source)
            if result["ok"]:
                self._log(Text.from_markup(f"[bold #36d399]✓ Skill installed: {result['path']}[/bold #36d399]"))
                self.notify("Skill installed and ready for matching requests.")
            else:
                self._log(Text.from_markup(f"[red]✗ Failed: {result.get('error', 'unknown error')}[/red]"))
        elif sub == "remove":
            if len(parts) < 3:
                self._log(Text.from_markup("[red]Use: /skill remove <name>[/red]"))
                return
            result = remove_skill(parts[2])
            self._log(Text.from_markup(
                f"[bold #36d399]✓ Skill removed: {parts[2]}[/bold #36d399]"
                if result["ok"] else f"[red]✗ {result.get('error', 'unknown error')}[/red]"
            ))
        else:
            self._log(Text.from_markup("[red]Unknown subcommand. Use /skill help.[/red]"))

    def _handle_config(self, cmd: str) -> None:
        parts = cmd.split()
        if len(parts) == 1:
            # Show current config
            self._show_config()
            return
        sub = parts[1]
        if sub == "set" and len(parts) >= 3:
            kv = parts[2]
            if "=" not in kv:
                self._log(Text.from_markup("[red]Use format: /config set KEY=VALUE[/red]"))
                return
            key, val = kv.split("=", 1)
            key = key.upper().strip()
            val = val.strip()
            if key not in CONFIG_META:
                self._log(Text.from_markup(f"[red]Key '{key}' not recognized. Use /config to see the list.[/red]"))
                return
            CONFIG_META[key] = val
            self._log(Text.from_markup(f"[dim]→ [bold]{key}[/bold] = {val}[/dim]"))
            self.notify(f"{key} updated in memory. /config save to persist.")
        elif sub == "save":
            save_env_config(CONFIG_META)
            reinit_providers()
            self._log(Text.from_markup("[bold #36d399]Config saved to .env and providers re-initialized.[/bold #36d399]"))
            self.notify("Config saved & providers re-initialized.")
        else:
            self._log(Text.from_markup(f"[red]Unknown subcommand: /config {sub}\n[/red]"
                                       "[dim]Use: /config, /config set KEY=VALUE, /config save[/dim]"))

    def _show_config(self) -> None:
        from rich.table import Table
        table = Table.grid(padding=(0, 2))
        table.add_column(style=f"bold {ACCENT2}")
        table.add_column(style="grey74")
        table.add_column(style="grey42")
        for key in sorted(CONFIG_META):
            val = CONFIG_META[key]
            display = val[:40] + "…" if len(val) > 40 else val
            if "KEY" in key and val:
                display = val[:8] + "****" if len(val) > 8 else "****"
            table.add_row(key, display, "")
        body = Panel(
            table,
            title="⚙ Configuration",
            border_style=ACCENT,
            box=ROUNDED,
        )
        self._log(body)
        self._log(Text.from_markup(
            "[dim]set: [bold]/config set KEY=VALUE[/bold]  |  save: [bold]/config save[/bold][/dim]"
        ))

    def _submit_query(self, text: str, dry_run: bool = False, coding_mode: bool = False) -> None:
        if not text:
            self.notify("Usage: /code <request> or /dry-run <request>", severity="warning")
            return
        learn_new_words(text)

        forced_search = False
        mode_prefix = "[CODING MODE] Follow inspect -> edit -> verify -> test -> report. " if coding_mode else ""
        mode_prefix += "[DRY RUN] Do not modify files; preview requested edits only. " if dry_run else ""
        msg: dict = {"role": "user", "content": mode_prefix + text}
        self._log(self._user_bubble(text))

        if text.lower().startswith(("search:", "net:")):
            forced_search = True
            query = text.split(":", 1)[1].strip()
            self.conversation.append({**msg, "content": text})
            self.conversation.append(
                {
                    "role": "user",
                    "content": (
                        "[USER INSTRUCTION]: You are REQUIRED to use the 'web_search' tool "
                        f"immediately to find the latest references for: '{query}'"
                    ),
                }
            )
        else:
            self.conversation.append(msg)

        self._set_thought("🧠 Thinking…")
        self._maybe_compress_history()
        self.busy = True
        self.attempt = "1"
        # Capture tab id so the worker thread writes to the right transcript
        self._active_tab_for_run = self.active_tab_id
        self.run_agent(forced_search, dry_run=dry_run, coding_mode=coding_mode)

    def _user_bubble(self, text: str) -> Panel:
        return Panel(
            Text(text, style="bold white"),
            border_style=ACCENT2,
            box=ROUNDED,
            title=f"➜ {self.username}",
            title_align="left",
        )

    def _maybe_compress_history(self) -> None:
        """Keep the newest turns only, while preserving the system prompt."""
        self.conversation = trim_chat_history(self.conversation, keep_last=8, system_prompt=SYSTEM_PROMPT)

    # ----------------------------------------------------------------- agent
    @work(thread=True, exclusive=True)
    def run_agent(self, forced_search: bool, dry_run: bool = False, coding_mode: bool = False) -> None:
        self._cancel_event.clear()
        llm_fn = None
        if self.force_demo:
            from .demo import demo_llm
            llm_fn = lambda msgs, **kw: demo_llm(msgs)
        else:
            from .llm import call_llm as real_call_llm

            def _llm_status(msg: str) -> None:
                self.call_from_thread(lambda: self._set_thought(msg))

            def safe_llm(messages, **kwargs):
                if self.force_demo:
                    from .demo import demo_llm
                    return demo_llm(messages)
                _llm_status("🧠 Contacting provider…")
                text, prov, usage = real_call_llm(
                    messages, preferred=self._preferred_provider,
                    on_status=_llm_status,
                    on_chunk=kwargs.get("on_chunk"),
                    cancel_event=self._cancel_event,
                    agent_profile=self._active_agent_profile or None,
                )
                if prov == "None":
                    _llm_status("✗ Selected provider failed — demo mode disabled")
                    provider_logger.warning(
                        "LIVE_REQUEST_FAILED | preferred=%s | demo fallback disabled",
                        self._preferred_provider or "auto",
                    )
                    return text, self._preferred_provider or "Provider unavailable", usage
                return text, prov, usage
            llm_fn = safe_llm

        start = time.time()
        conv = self._tabs.get(self._active_tab_for_run,
                              list(self._tabs.values())[0] if self._tabs else [])
        agent = build_agent(
            emit=self._emit,
            llm_fn=llm_fn,
            approver=self._approver,
            cancel_event=self._cancel_event,
            dry_run=dry_run,
        )
        result = None
        try:
            result = agent.run(list(conv))
        except Exception as exc:
            self.call_from_thread(self._log, Text.from_markup(f"[red]Agent error: {exc}[/red]"))
        finally:
            elapsed = time.time() - start
            self.call_from_thread(self._finish_turn, elapsed, result)

    def _finish_turn(self, elapsed: float, result: Optional[dict] = None) -> None:
        try:
            self.latency = f"{elapsed:.2f}s"
            if result and result.get("done"):
                self._set_thought(f"Ready · {elapsed:.1f}s")
            conv = self._tabs.get(self._active_tab_for_run,
                                  list(self._tabs.values())[0] if self._tabs else [])
            save_history_to_json(conv)
            # Learn from conversation for persistent memory
            try:
                learn_from_conversation(conv)
            except Exception:
                pass
            self.query_one("#prompt", Input).focus()
            # Desktop notification on completion
            try:
                import platform as _pf
                if _pf.system() == "Linux":
                    subprocess.run(["notify-send", "HomeLab AI", f"Response ready ({elapsed:.1f}s)"],
                                   timeout=2, capture_output=True)
                elif _pf.system() == "Darwin":
                    subprocess.run(["osascript", "-e",
                                    f'display notification "Response ready ({elapsed:.1f}s)" with title "HomeLab AI"'],
                                   timeout=2, capture_output=True)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self.busy = False

    def action_cancel_run(self) -> None:
        if not self.busy:
            return
        self._cancel_event.set()
        self._set_thought("⏹ Cancelling current request…")
        self._log(Text.from_markup("[yellow]Cancellation requested.[/yellow]"))

    # event emitter (runs on worker thread) -> marshalled onto UI thread
    def _emit(self, event_type: str, payload: dict) -> None:
        self.call_from_thread(self._handle_event, event_type, payload)

    def _should_keep_scroll_locked(self, tr: RichLog) -> bool:
        """Only auto-scroll when the user is already near the bottom."""
        try:
            scroll_y = max(0, int(getattr(tr, "scroll_y", 0) or 0))
            viewport_h = max(1, int(getattr(tr.size, "height", 0) or 0))
            content_h = max(1, int(getattr(tr.virtual_size, "height", 0) or 0))
            if content_h <= viewport_h:
                return True
            distance_to_bottom = content_h - (scroll_y + viewport_h)
            return distance_to_bottom <= max(12, viewport_h // 2)
        except Exception:
            return True

    def _handle_event(self, event_type: str, payload: dict) -> None:
        tid = getattr(self, "_active_tab_for_run", None) or self.active_tab_id or "tab_1"
        log_id = f"transcript_{tid}"
        try:
            tr = self.query_one(f"#{log_id}", RichLog)
        except Exception:
            return

        try:
            tb = self.query_one("#thought_bar", Static)
        except Exception:
            tb = None

        # Streaming buffer for chunked output
        _stream_buf = self._stream_buf
        _stream_panel = self._stream_panel

        if event_type == "status":
            text = payload.get("text", "")
            if "attempt" in text.lower():
                import re
                m = re.search(r"(\d+)/", text)
                if m:
                    self.attempt = m.group(1)
            if tb:
                tb.update(Text.from_markup(f"[dim]… {text}[/dim]"))
        elif event_type == "chunk":
            # Streaming token received — update streaming panel
            _stream_buf += payload.get("text", "")
            self._stream_buf = _stream_buf
            if tb:
                snippet = _stream_buf[-120:].replace("\n", " ").strip()
                tb.update(Text.from_markup(f"[dim]⋯ {snippet}[/dim]"))
        elif event_type == "thought":
            prov = payload.get("provider")
            if prov:
                self.provider = prov
            if tb:
                tb.update(Text(payload.get("text", ""), style="italic grey58"))
        elif event_type == "tool_call":
            if tb:
                name = payload.get("name", "")
                tb.update(Text.from_markup(f"[dim]⚙ {name}…[/dim]"))
        elif event_type == "tool_result":
            if tb:
                name = payload.get("name", "")
                result = payload.get("result", "")
                snippet = result[:80].replace("\n", " ").strip()
                tb.update(Text.from_markup(f"[dim]✔ {name}: {snippet}[/dim]"))
        elif event_type == "command_start":
            if tb:
                tb.update(Text.from_markup(f"[dim]$ {payload.get('command','')}[/dim]"))
        elif event_type == "command_line":
            if tb:
                tb.update(Text(payload.get("line", ""), style="grey42"))
        elif event_type == "command_end":
            code = payload.get("exit_code")
            style = "green" if code in (0, None) else "red"
            if tb:
                tb.update(Text.from_markup(f"[{style}]↳ exit code: {code}[/{style}]"))
        elif event_type == "patch_preview":
            pass
        elif event_type == "final":
            prov = payload.get("provider")
            if prov:
                self.provider = prov
            usage = payload.get("usage", {})
            if usage:
                self._last_usage = usage
            self._render_context()
            if tb:
                tb.update("")
            self._stream_buf = ""
            last_user = ""
            conv = self._tabs.get(tid, [])
            for msg in reversed(conv):
                if msg["role"] == "user":
                    last_user = msg["content"]
                    break
            modified = apply_after_query(last_user, payload.get("text", ""))
            conv.append({"role": "assistant", "content": modified})
            self._msg_counter += 1
            self._msg_map[self._msg_counter] = modified
            tr.write(self._assistant_panel(modified, prov, self._msg_counter))
        elif event_type == "error":
            if tb:
                tb.update("")
            tr.write(Text.from_markup(f"[red]✗ {payload.get('text','')}[/red]"))

        if self._should_keep_scroll_locked(tr):
            tr.scroll_end(animate=False)

    def _tool_call_panel(self, payload: dict) -> Panel:
        import json

        params = json.dumps(payload.get("parameters", {}), ensure_ascii=False, indent=2)
        body = Group(
            Text.from_markup(f"[bold]{payload.get('name','')}[/bold]  [dim]via {payload.get('provider','?')}[/dim]"),
            Syntax(params, "json", theme="ansi_dark", word_wrap=True),
        )
        return Panel(body, title="⚙ tool call", border_style=ACCENT2, box=ROUNDED)

    def _tool_result_panel(self, payload: dict) -> Panel:
        result = payload.get("result", "")
        if len(result) > 4000:
            result = result[:4000] + "\n… (truncated)"
        return Panel(
            Text(result, style="grey74"),
            title=f"↩ result · {payload.get('name','')}",
            border_style="grey42",
            box=ROUNDED,
        )

    def _assistant_panel(self, text: str, provider: Optional[str], msg_id: int = 0) -> Panel:
        if msg_id:
            label = (
                f"[link=copy:{msg_id}]↪ HomeLab AI · {provider or '?'}[/link] "
                f"[link=copy:{msg_id}] [Copy answer][/link] "
                f"[link=copy-code:{msg_id}] [Copy code][/link]"
            )
        else:
            label = f"↪ HomeLab AI · {provider or '?'}"
        title = Text.from_markup(label)
        return Panel(Markdown(text or "(empty)", code_theme="monokai"), title=title,
                     border_style=ACCENT, box=ROUNDED, title_align="left")

    # patch approval bridge (called on worker thread)
    def _approver(self, preview: dict) -> bool:
        event = threading.Event()
        self._approval_event = event
        self._approval_result = False

        def ask() -> None:
            def cb(result: Optional[bool]) -> None:
                self._approval_result = bool(result)
                event.set()

            self.push_screen(PatchApproveScreen(preview["file_path"], preview["diff"]), cb)

        self.call_from_thread(ask)
        event.wait()
        verdict = "applied" if self._approval_result else "rejected"
        self.call_from_thread(
            self._log, Text.from_markup(f"[dim]Patch {verdict} for {preview['file_path']}[/dim]")
        )
        return self._approval_result

    # ----------------------------------------------------------------- actions
    def action_new_tab(self) -> None:
        self._tab_counter += 1
        tid = f"tab_{self._tab_counter + 1}"
        label = f"Session {self._tab_counter + 1}"
        self._tabs[tid] = self._new_conversation()
        self._tab_order.append(tid)
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.add_pane(TabPane(
            label,
            RichLog(
                id=f"transcript_{tid}",
                wrap=True,
                markup=True,
                highlight=True,
            ),
            id=tid,
        ))
        tabs.active = tid
        self._print_welcome()
        self.query_one("#prompt", Input).focus()

    def action_close_tab(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        active = tabs.active
        if not active or active == "tab_1":
            self.notify("Cannot close the last tab.", severity="warning")
            return
        tabs.remove_pane(active)
        self._tabs.pop(active, None)
        if active in self._tab_order:
            self._tab_order.remove(active)

    def action_next_tab(self) -> None:
        if len(self._tab_order) < 2:
            return
        active = self.active_tab_id or self._tab_order[0]
        try:
            idx = self._tab_order.index(active)
        except ValueError:
            idx = -1
        next_idx = (idx + 1) % len(self._tab_order)
        next_tid = self._tab_order[next_idx]
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = next_tid

    def action_clear_chat(self) -> None:
        """Clear the active tab's transcript."""
        tid = self.active_tab_id or "tab_1"
        log_id = f"transcript_{tid}"
        try:
            self.query_one(f"#{log_id}", RichLog).clear()
        except Exception:
            pass
        self._tabs[tid] = self._new_conversation()
        self._print_welcome()

    def action_save_session(self) -> None:
        tid = self._active_tab_for_run or self.active_tab_id or "tab_1"
        conv = self._tabs.get(tid, [])
        path = export_session_to_markdown(conv)
        if path.startswith("Error"):
            self.notify(path, severity="error")
        else:
            self.notify(f"Saved session → {path}")

    def action_rename_tab(self, new_name: str = "") -> None:
        """Rename the active tab."""
        if not new_name:
            self.notify("Usage: /rename <new name>", severity="warning")
            return
        tid = self.active_tab_id or "tab_1"
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            for pane in tabs._tab_panes:
                if pane.id == tid:
                    pane.label = new_name
                    break
            self.notify(f"Tab renamed to '{new_name}'")
        except Exception as e:
            self.notify(f"Rename failed: {e}", severity="error")

    def action_search_chat(self) -> None:
        """Open the in-chat search modal."""
        self.push_screen(SearchInChatScreen())

    def _search_in_transcript(self, query: str) -> None:
        """Search the active transcript for a query string."""
        tid = self.active_tab_id or "tab_1"
        try:
            conv = self._tabs.get(tid, [])
            results = []
            for i, msg in enumerate(conv):
                if query.lower() in msg.get("content", "").lower():
                    role = msg.get("role", "?")
                    preview = msg.get("content", "")[:100].replace("\n", " ")
                    results.append(f"  #{i} [{role}] {preview}…")
            if results:
                self._log(Panel(
                    Text.from_markup("\n".join(results[:20])),
                    title=f"Search: '{query}' ({len(results)} matches)",
                    border_style="#36d399", box=ROUNDED,
                ))
            else:
                self._log(Text.from_markup(f"[dim]No matches for '{query}'.[/dim]"))
        except Exception as e:
            self.notify(f"Search error: {e}", severity="error")

    def action_branch_conversation(self) -> None:
        """Fork the current conversation into a new tab."""
        tid = self.active_tab_id or "tab_1"
        conv = self._tabs.get(tid, [])
        if len(conv) < 2:
            self.notify("Need at least a user + assistant message to branch.", severity="warning")
            return
        self._tab_counter += 1
        new_tid = f"tab_{self._tab_counter + 1}"
        # Copy all messages except the last (to branch from before the last response)
        branch_from = conv[:-1] if conv[-1]["role"] == "assistant" else conv
        self._tabs[new_tid] = list(branch_from)
        self._tab_order.append(new_tid)
        label = f"Branch {self._tab_counter + 1}"
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.add_pane(TabPane(
            label,
            RichLog(
                id=f"transcript_{new_tid}",
                wrap=True,
                markup=True,
                highlight=True,
            ),
            id=new_tid,
        ))
        tabs.active = new_tid
        self.query_one("#prompt", Input).focus()
        self._log(Text.from_markup(f"[dim]Branch created from '{tid}' as '{new_tid}'.[/dim]"))

    def _start_plan_mode(self, goal: str) -> None:
        """Multi-step planner: generate plan, show for approval, then execute."""
        if not goal:
            self.notify("Usage: /plan <goal description>", severity="warning")
            return
        # Generate steps by asking the LLM for a plan
        self._log(Text.from_markup(f"[dim]Generating plan for: {goal}[/dim]"))
        try:
            from .llm import call_llm
            plan_prompt = f"""Generate a numbered execution plan for this goal. Return ONLY a numbered list, each step on a new line starting with "Step N: ".

Goal: {goal}"""
            resp, _ = call_llm([{"role": "user", "content": plan_prompt}])
            steps = [l.strip() for l in resp.split("\n") if l.strip().startswith("Step")][:10]
            if not steps:
                self.notify("Could not parse plan steps.", severity="error")
                return
            def on_plan(steps_or_empty: list[str]) -> None:
                if not steps_or_empty:
                    self._log(Text.from_markup("[dim]Plan cancelled.[/dim]"))
                    return
                self._log(Panel(
                    Text.from_markup("\n".join(f"  ✓ {s}" for s in steps_or_empty)),
                    title="Executing Plan", border_style="#36d399", box=ROUNDED,
                ))
                # Execute each step as a separate query
                for step in steps_or_empty:
                    # Strip "Step N: " prefix
                    step_text = step.split(":", 1)[1].strip() if ":" in step else step
                    self._submit_query(f"[PLAN STEP] {step_text}")
            self.push_screen(PlanApproveScreen(steps), on_plan)
        except Exception as e:
            self.notify(f"Plan failed: {e}", severity="error")

    def action_show_help(self) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style=f"bold {ACCENT2}")
        table.add_column(style="grey74")
        rows = [
            ("/help · F1", "show this help"),
            ("/clear · Ctrl+L", "clear the conversation"),
            ("/save · Ctrl+S", "export session to markdown"),
            ("/agent · Ctrl+A", "select agent/provider"),
            ("⭐ Primary —", "visible in footer bar"),
            ("Ctrl+P", "command palette (search actions)"),
            ("Ctrl+Q", "quit app"),
            ("F1", "show help"),
            ("F3", "toggle select mode (click+drag)"),
            ("⭐ All bindings —", ""),
            ("Ctrl+C", "copy selected text or last AI response"),
            ("Ctrl+Shift+V", "paste from clipboard into input"),
            ("Ctrl+O", "open URL in last response"),
            ("Ctrl+T", "new tab"),
            ("Ctrl+W", "close tab"),
            ("Ctrl+Tab", "next tab"),
            ("Ctrl+F", "search within transcript"),
            ("F2", "rename current tab"),
            ("/config", "configure API keys & models from within TUI"),
            ("/plugin", "install/list/remove plugins from online"),
            ("/rename <name>", "rename current tab"),
            ("/plan <goal>", "multi-step planner (generate → approve → execute)"),
            ("/code <request>", "coding mode with edit verification"),
            ("/dry-run <request>", "preview file edits without modifying disk"),
            ("/branch", "fork conversation into new tab"),
            ("/tools", "list tools"),
            ("/history", "history summary"),
            ("/quit · Ctrl+Q", "leave the app"),
            ("@file", "attach file to prompt"),
            ("search: <q>", "force a web search"),
            ("net: <q>", "force a web search"),
        ]
        for k, v in rows:
            table.add_row(k, v)
        self._log(Panel(table, title="Help", border_style=ACCENT, box=ROUNDED))

    def action_select_agent(self) -> None:
        """Open the agent/provider selection modal."""
        def cb(result: Optional[str]) -> None:
            if result:
                self._preferred_provider = result
                self.provider = result
                save_preference("provider", result)
                self._log(Text.from_markup(f"[dim]Agent changed to [bold]{result}[/bold].[/dim]"))
        self.push_screen(AgentSelectScreen(), cb)

    def _show_tools(self) -> None:
        table = Table(box=ROUNDED, border_style="grey42", title="Available Tools (pydantic-ai schema)")
        table.add_column("tool", style=f"bold {ACCENT2}")
        table.add_column("parameters", style="grey74")
        for entry in tool_manifest():
            props = entry["schema"].get("properties", {})
            params = ", ".join(props.keys()) or "—"
            table.add_row(entry["name"], params)
        self._log(table)

    def _show_history_summary(self) -> None:
        conv = self._tabs.get(self.active_tab_id, [])
        n = len(conv)
        users = sum(1 for m in conv if m["role"] == "user")
        assistants = sum(1 for m in conv if m["role"] == "assistant")
        self._log(
            Panel(
                Text.from_markup(
                    f"Messages: [bold]{n}[/bold]\nUser turns: {users}\nAssistant turns: {assistants}\n"
                    f"Persisted at: [cyan]{HISTORY_JSON_FILE}[/cyan]"
                ),
                title="History",
                border_style="grey42",
                box=ROUNDED,
            )
        )

    def _extract_copyable_text(self, content: str) -> str:
        """Return the meaningful response body for copying.

        Prefer fenced code blocks when present, otherwise strip common AI
        wrappers and return the actual assistant text only.
        """
        text = (content or "").strip()
        if not text:
            return ""

        blocks = re.findall(r"```(?:[A-Za-z0-9_-]+)?\n(.*?)```", text, flags=re.DOTALL)
        if blocks:
            code = "\n\n".join(block.strip() for block in blocks if block.strip())
            if code:
                return code

        text = re.sub(r"^(?:THOUGHT:|FINAL_ANSWER:|\[FINAL ANSWER\])\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*\*+\s*", "", text)
        return text.strip()

    def _extract_copyable_code(self, content: str) -> str:
        """Extract the first fenced code block from AI output, if any."""
        text = content or ""
        blocks = re.findall(r"```(?:[A-Za-z0-9_-]+)?\n(.*?)```", text, flags=re.DOTALL)
        if not blocks:
            return ""
        code = "\n\n".join(block.strip() for block in blocks if block.strip())
        return code.strip()

    def action_open_link(self) -> None:
        tid = self.active_tab_id or "tab_1"
        conv = self._tabs.get(tid, [])
        for msg in reversed(conv):
            if msg["role"] == "assistant":
                import re
                urls = re.findall(r'https?://[^\s\)\]]+', msg.get("content", ""))
                if urls:
                    self.open_url(urls[0])
                    self.notify(f"Opened: {urls[0][:60]}…")
                    return
        self.notify("No URL found in last response", severity="warning")

    def action_copy(self) -> None:
        """Copy selected text from transcript, or fall back to last assistant message."""
        tid = self.active_tab_id or "tab_1"
        try:
            selected_text = self.screen.get_selected_text()
            if selected_text and selected_text.strip():
                self.copy_to_clipboard(selected_text)
                self.notify("Copied selected text")
                return
        except Exception:
            pass
        
        # Fall back to copying last assistant message
        conv = self._tabs.get(tid, [])
        for msg in reversed(conv):
            if msg["role"] == "assistant":
                text = self._extract_copyable_text(msg.get("content", ""))
                if text:
                    self.copy_to_clipboard(text)
                    self.notify("Copied last response to clipboard")
                return
        self.notify("No text selected and no assistant response to copy", severity="warning")

    def action_paste(self) -> None:
        text = ""
        try:
            import pyperclip
            text = pyperclip.paste()
        except Exception:
            try:
                import subprocess
                for cmd in (["xclip", "-o", "-selection", "clipboard"],
                            ["xclip", "-o"],
                            ["wl-paste"]):
                    try:
                        text = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
                        if text:
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        if not text:
            self.notify("Clipboard empty or unavailable.", severity="warning")
            return
        inp = self.query_one("#prompt", Input)
        pos = inp.cursor_position
        val = inp.value
        inp.value = val[:pos] + text + val[pos:]
        inp.cursor_position = pos + len(text)
        inp.focus()

    def action_quit(self) -> None:  # type: ignore[override]
        if self._watcher:
            import threading
            if self._watcher._thread and self._watcher._thread.is_alive():
                self._watcher._stop.set()
                # Don't wait — let the daemon thread die naturally
        if self._tabs:
            main = self._tabs.get("tab_1", list(self._tabs.values())[0])
            export_session_to_markdown(main)
            save_history_to_json(main)
        self.exit()


def run(force_demo: bool = False) -> None:
    try:
        HomeLabApp(force_demo=force_demo).run()
    except KeyboardInterrupt:
        pass
