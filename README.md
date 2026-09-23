# HomeLab AI

A terminal AI companion with a modern TUI — multi-session tabs, streaming
output, code-aware tools, and a free fallback LLM provider so you can use it
right out of the box.

```bash
curl -fsSL https://altivon.my.id/install.sh | sh
homelab
```

On Windows PowerShell, use the native installer:

```powershell
irm https://altivon.my.id/install.ps1 | iex
homelab
```

The Bash installer remains available for Linux, macOS, Git Bash, WSL, and
MSYS2. Release builds publish both `install.sh` and `install.ps1`.

Installation maintenance commands:

```bash
homelab doctor
homelab update
homelab rollback
homelab uninstall                 # preview only
homelab uninstall --confirm       # remove installation, preserve user data
```

Release archives can be verified with SHA-256 checksums. Generate a reproducible
dependency lockfile with `scripts/lock-dependencies.sh` or
`scripts/lock-dependencies.ps1` when `uv` is installed.

---

## Features

### Conversational AI with multi-provider fallback

Type anything and the AI responds in the terminal. It automatically tries
multiple LLM providers in order:

1. **DeepSeek** — primary (requires `DEEPSEEK_API_KEY`)
2. **Gemini** — fallback (requires `GEMINI_API_KEY`)
3. **G4F** — optional free fallback, disabled by default

Switch providers on the fly via **Ctrl+A** or `/agent` command.

### Tools (100+)

The AI can use over 100 tools autonomously:

| Category | Tools |
|---|---|
| **Code** | read, write, edit, patch, diff, search, grep, glob, find, refactor, lint, format |
| **Shell** | run commands, execute scripts, watch processes |
| **Git** | init, clone, add, commit, push, pull, log, diff, status, blame, branch, merge, stash |
| **Files** | list, move, copy, delete, archive, compress, permissions, disk usage |
| **Network** | scan ports, fetch URLs, ping, DNS lookup, traceroute, whois |
| **Docker** | compose up/down/logs/ps, exec, images, ps, logs, inspect |
| **Kubernetes** | get, logs, describe |
| **Databases** | SQLite, MySQL, PostgreSQL query |
| **Screens & Vision** | screenshot, analyze image (Gemini Vision) |
| **Automation** | mouse, keyboard, desktop notification |
| **Search** | web search, news, codebase RAG, file grep |
| **System** | OS info, disk usage, memory, processes, uptime, weather |
| **Package managers** | apt, pip, npm, brew |
| **Utility** | base64, hash, QR code, TTS, translation, URL shortener, calculator |

### Multi-session tabs

Work on multiple tasks at the same time. Each tab has its own conversation
history, and you can rename them with **F2** or `/rename`.

- **Ctrl+T** — new tab
- **Ctrl+W** — close current tab
- **Ctrl+Tab** / **Ctrl+Shift+Tab** — switch tabs
- **F2** — rename current tab

### Multi-step planner

Turn a complex goal into an action plan:

    /plan Deploy a Flask app with Docker

The AI generates numbered steps. You approve/reject each one, and the AI
executes them step by step.

### Conversation branching

Need to explore a different direction without losing context?

    /branch

Copies the current conversation into a new tab, excluding the last assistant
message — so you can rephrase your last request.

### In-chat search

**Ctrl+F** or `/search` opens a search modal. Type a keyword and it highlights
matching lines in the current conversation transcript.

### Plugin system

Extend the AI with custom Python plugins:

    /plugin install https://example.com/my-plugin.py
    /plugin list
    /plugin remove my-plugin

Plugins hook into the conversation lifecycle — before and after the AI responds.

### AI skills

Skills are instruction/data bundles for the local HomeLab AI agent. Install the
public UI UX Pro Max skill without Claude:

    /skill install gh:nextlevelbuilder/ui-ux-pro-max-skill
    /skill list
    /skill remove ui-ux-pro-max-skill

Installed skill instructions are loaded automatically for matching UI/frontend
requests and are stored under `~/.config/homelab-ai/skills/`.

### MCP server

Run HomeLab AI as a Model Context Protocol server:

```bash
homelab mcp-server --port 8000 --auth-token mytoken
```

Tools are exposed via the MCP protocol so any MCP-compatible client can use
them.

### Persistent memory

The AI remembers your preferences, past facts, and conversation history across
sessions:

- **User preferences**: `/config set LANGUAGE=id` — remembered next launch
- **Learned facts**: the AI stores useful information from conversations
- **Tool usage history**: a dashboard shows which tools are used most, error rates, and performance

### Tool health dashboard

The sidebar shows live context: token usage, estimated cost, and a tool health
dashboard with total calls, error counts, and most-used tools.

### Desktop notifications

Get notified when the AI finishes responding — even if you switch to another
window. Works on Linux (notify-send) and macOS (osascript).

---

## Installation

### Quick install

```bash
curl -fsSL https://altivon.my.id/install.sh | sh
```

This installs to `~/.homelab-ai/`, sets up a virtual environment, and creates
the `homelab` command.

### Manual install

```bash
git clone https://github.com/pandhu-rendra/homelab-ai
cd homelab-ai

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# edit .env to add API keys (optional)
```

---

## Configuration

All settings live in `~/.homelab-ai/.env`:

```ini
# =============================================================================
# HomeLab AI — Environment Configuration
# =============================================================================
# Copy this file to .env and fill in the keys you want to use.
# The TUI will try providers in order: DeepSeek → Gemini → OpenRouter → Flaz → G4F (if enabled)
# Leave empty any providers you don't want to use.
#
# G4F is opt-in because it can be unreliable. Set HOMELAB_G4F_ENABLED=true to enable it.
# =============================================================================

# --- DeepSeek ---
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat

# --- Google Gemini ---
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# --- OpenRouter (akses ke Claude, GPT, llama, dsb via satu API) ---
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4o-mini

# --- Flaz.id (OpenAI-compatible, berbagai model termasuk Claude) ---
FLAZ_API_KEY=
FLAZ_MODEL=claude-sonnet-4-20250514
FLAZ_ENDPOINT=https://api.flaz.id/v1

# Runtime safety limits. These values are bounded by the application.
HOMELAB_LLM_TIMEOUT=30
HOMELAB_MAX_ATTEMPTS=20
HOMELAB_MAX_PROVIDER_ATTEMPTS=2
HOMELAB_MAX_CONTEXT_CHARS=24000
HOMELAB_MAX_TOTAL_TOKENS=12000

# --- G4F (free, with out api key) ---
HOMELAB_G4F_ENABLED=false
G4F_PROVIDER=
# Model used G4F. Leave blank for auto (gpt-4o-mini).
```

Edit `.env` directly, or use the in-app command:

    /config set DEEPSEEK_API_KEY sk-xxx
    /config save

### Demo mode

Run without any API keys:

```bash
homelab --demo
```

A local demo LLM handles all requests. The UI, tools, and plugins work normally.

---

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| `/help` | F1 | Command reference |
| `/clear` | Ctrl+L | Clear conversation |
| `/save` | Ctrl+S | Export to Markdown |
| `/tools` | — | List tools with parameters |
| `/history` | — | Past session summary |
| `/search <q>` | Ctrl+F | Search in current transcript |
| `/plan <goal>` | — | Multi-step planner |
| `/branch` | — | Branch conversation to new tab |
| `/rename <name>` | F2 | Rename current tab |
| `/agent` | Ctrl+A | Switch LLM provider |
| `/config` | — | View / edit configuration |
| `/plugin` | — | Manage plugins |
| `/quit` | Ctrl+Q | Exit |

---

## Keybindings

| Key | Action |
|---|---|
| **Ctrl+Q** | Quit |
| **Ctrl+C** | Copy last assistant response |
| **Ctrl+V** | Paste from clipboard |
| **Ctrl+O** | Open first URL from last response |
| **Ctrl+P** | Command palette |
| **Ctrl+F** | Search in transcript |
| **Ctrl+L** | Clear conversation |
| **Ctrl+S** | Save session |
| **Ctrl+T** | New tab |
| **Ctrl+W** | Close tab |
| **Ctrl+A** | Switch provider |
| **Ctrl+Tab** | Next tab |
| **Ctrl+Shift+Tab** | Previous tab |
| **F1** | Help |
| **F2** | Rename tab |
| **F3** | Toggle select mode |

---

## Architecture

```
~/.homelab-ai/
├── .venv/                 Python virtual environment
├── homelab_ai/            Application package
│   ├── tui.py             Textual TUI (tabs, streaming, sidebar)
│   ├── llm.py             LLM providers + system prompt
│   ├── graph.py           ReAct loop (think → act → think → ...)
│   ├── executor.py        Tool dispatch
│   ├── tools.py           All tool implementations
│   ├── schemas.py         Typed tool parameter models
│   ├── memory.py          Persistent memory (preferences, facts, stats)
│   ├── storage.py         SQLite session persistence
│   ├── config.py          Environment, logging, lazy install
│   ├── plugin_manager.py  Plugin hook system
│   ├── plugin_installer.py Plugin installer (URL, GitHub, registry)
│   ├── mcp_server.py      MCP protocol server
│   ├── runners.py         Shell command streaming
│   ├── watcher.py         File watcher
│   ├── rag.py             Codebase RAG engine
│   ├── demo.py            Offline demo mode
│   ├── os/
│   │   ├── __init__.py       OS integration package
│   │   ├── system_io.py      System-level I/O operations
│   │   └── vision_agent.py   Screen and image analysis
│   └── ui/
│       ├── __init__.py       UI package
│       └── dashboard.py      Humanized dashboard helpers
├── plugins/               User-installed plugins
├── install.sh             Cross-platform installer
└── .env                   API keys
```

---

## FAQ

**Q: Do I need an API key?**  
A: No. G4F is an optional free fallback provider. Set
`HOMELAB_G4F_ENABLED=true` to enable it. Without any keys, the app still works
— though response quality may vary.

**Q: Where is chat history stored?**  
A: `~/.homelab-ai/sessions.db` (SQLite). Export to Markdown with `/save`.

**Q: Can I use my own OpenAI/Anthropic key?**  
A: Yes. Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env`.

**Q: How do I update?**  
A: Re-run the installer: `curl -fsSL https://altivon.my.id/install.sh | sh`

**Q: Does it work on Windows?**  
A: Yes — Git Bash, WSL, or MSYS2. A `homelab.cmd` launcher is created for
CMD and PowerShell.

---

## License

MIT
