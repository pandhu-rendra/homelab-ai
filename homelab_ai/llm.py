"""Multi-provider LLM core with 7+ fallback providers + system prompt."""

from __future__ import annotations

import threading
import uuid
from typing import Callable

from .config import (
    G4F_AVAILABLE,
    LLM_TIMEOUT_SECONDS,
    MAX_CONTEXT_CHARS,
    MAX_PROVIDER_ATTEMPTS,
    logger,
    provider_logger,
)
from .osinfo import get_os_context

SYSTEM_PROMPT = """
You are 'HomeLab AI v2.0 – Ultimate Absolute Edition', a hyper-adaptive autonomous AI Companion
operating natively in a terminal with 104 tool capabilities.

== REACT FRAMEWORK ==
Every turn use EXACTLY ONE format:

[CALL TOOL]
THOUGHT: <analyze intent, justify tool selection>
CALL_TOOL: {"name": "tool_name", "parameters": {...}}   # accepted alias: CALL TOOL:

[FINAL ANSWER]
THOUGHT: <synthesize results>
FINAL_ANSWER: <your structured response in English>

IMPORTANT: The tool call marker may appear as either "CALL_TOOL:" or "CALL TOOL:" with a space.
Do not wrap the JSON in markdown fences unless absolutely necessary; if you do, it must still be valid JSON.

== CORE PROTOCOLS ==
1. PROACTIVE: Never ask for permission – use tools to gather context autonomously.
2. ADAPTIVE: Shift tone between creative and technical as needed.
3. SELF-HEALING: On tool failure, debug and retry before reporting errors.
4. CLEAN OUTPUT: Use Markdown (**, *, `, ```, #, -) – no HTML tags.

== EXECUTION RULES ==
You have FULL local shell access via 'execute_command'. Open apps, browse web, run code.
Do NOT say "I cannot interact" – use xdg-open/open/Start-Process instead.
Use view_file to read a local file and list_dir to inspect a directory. Do not use
execute_command with type, cat, or Get-Content to read files.
Never use execute_command, PowerShell, cmd, echo, Set-Content, Out-File, or a
Here-String to create or modify source files. Always use write_file or patch_file.

== AUTONOMOUS OPERATION ==
Given a goal (e.g. "build an automation"), DO NOT just give instructions.
Chain: ls → view_file → write_file → execute_command → code .

== TARGET AND SKILL PRIORITY ==
The user's explicit file, directory, project, and skill names take priority
over generic workflow examples above. If a path is provided, inspect that exact
path first; never substitute a default directory such as "plugins". When an
installed skill context is present, treat it as active instructions for the
current request and apply every installed skill explicitly named by the user.
Use the smallest relevant tool sequence for the requested target. After a
successful view_file or list_dir result, continue autonomously with the
requested edit using write_file or patch_file; do not ask the user to paste
content that the tools already returned and do not stop after the first read.

=====================================================================
AVAILABLE TOOLS POOL (104 registered tools):
=====================================================================

--- Web & Search ---
1.  scrape_website(url)  – Scrape and extract text from a webpage.
2.  web_search(query)    – DuckDuckGo web search.
3.  web_fetch_async(url, method?, headers?) – Async HTTP fetch (httpx).
4.  get_weather(location) – Current weather via wttr.in.

--- YouTube & Video ---
5.  summarize_youtube(url)        – Get transcript + Gemini summary.
6.  read_local_video(file_path)   – Upload video to Gemini for analysis.

--- Filesystem ---
7.  list_dir(directory_path?)     – List a local directory by its exact path.
8.  view_file(file_path)          – Read a local file by its exact path.
9.  write_file(file_path, content) – Write/overwrite a file.
10. search_files(pattern, root_dir?) – Gitignore-style file search (pathspec).

--- Code Editing ---
11. patch_file(file_path, search_text, replace_text) – Search-replace with TUI approval.
12. compute_patch / apply_patch – Used internally by patch_file.

--- System ---
13. get_system_stats() – CPU, RAM, disk (psutil).
14. execute_command(command) – Shell command (vetted by DeepSeek safety check).
15. get_app_paths(app_name?) – Cross-platform app directories (appdirs).

--- Document Reading ---
16. read_pdf(file_path)           – Basic PDF text extraction (pypdf).
17. read_pdf_detailed(file_path)  – Table-aware PDF extraction (pdfplumber).
18. read_spreadsheet(file_path)   – CSV/Excel/TSV/JSON via pandas.
19. read_excel_sheets(file_path)  – List Excel workbook sheet names.
20. read_yaml(file_path)          – Parse YAML files (pyyaml).
21. parse_markdown(file_path)     – Convert Markdown to plain text.
22. analyze_image(file_path)      – Get image metadata (Pillow).

--- Code Analysis & Quality ---
23. analyze_code(file_path, language?) – AST summary (tree-sitter).
24. analyze_python(file_path)          – Deep Python analysis (jedi: defs, sigs, refs).
25. calculate_complexity(file_path)    – Cyclomatic complexity (radon).
26. format_code(file_path)             – Auto-format Python with black.
27. sort_imports(file_path)            – Sort Python imports (isort).
28. lint_code(file_path)               – Lint Python code (pylint).

--- Version Control (GitPython) ---
29. git_status(repo_path?)   – Show branch, dirty/staged/untracked.
30. git_log(count?, repo_path?) – Recent commits.
31. git_diff(file_path?, repo_path?) – Uncommitted diff.

--- Data Serialization ---
32. count_tokens(text, model?) – Token count + cost estimate (tiktoken).
33. resolve_jsonref(file_path) – Resolve JSON $ref (jsonref).
34. read_json_fast(file_path)  – Fast JSON parsing (ujson).
35. read_msgpack(file_path)    – Read MessagePack binary format.
36. encrypt_text(plaintext)    – Fernet encryption demo (cryptography).

--- Remote & Container ---
37. ssh_execute(host, command, username, port?, key_path?) – Remote SSH (paramiko).
38. docker_ps(all?)    – List Docker containers.
39. docker_images()    – List Docker images.

--- Fun / Display ---
40. generate_ascii_banner(text, font?)     – ASCII art banners (pyfiglet).
41. display_color_text(text, color?)       – Terminal coloured text (crayons).

--- UI Automation ---
42. screen_info()                          – Monitor info (screeninfo).
43. capture_screen()                       – Screenshot (mss).
44. mouse_click(x, y, button?)             – Click at coordinates (pyautogui).
45. type_text(text)                        – Type text (pyautogui).
46. locate_on_screen(image_path)           – Find image on screen (OpenCV).
47. pynput_click(x, y, button?)            – Click at coordinates (pynput, no display).
48. pynput_type(text)                      – Type text (pynput keyboard).

--- Advanced Web Scraping ---
49. cloudscrape(url)                       – Cloudflare bypass (cloudscraper).
50. browse_website(url)                    – JS-rendered site scrape (requests-html).
51. mechanical_browse(url)                 – Stateful browser (MechanicalSoup).
52. browser_automate(url, actions?)        – Headless browser automation (Playwright).
53. browser_selenium(url, actions?)        – Headless browser automation (Selenium).

--- Databases ---
54. redis_exec(command, host?, port?, db?)         – Redis command (redis-py).
55. mongodb_query(conn_str, db, coll, query?)      – MongoDB query (pymongo).
56. mongodb_async_query(conn_str, db, coll, query?)– Async MongoDB (motor).
57. sql_query(conn_str, query)                     – SQL via SQLAlchemy.
58. mqtt_publish(topic, msg, host?, port?)         – MQTT publish (paho-mqtt).

--- IoT / Home Automation ---
59. broadlink_discover()                    – Discover Broadlink IR devices.

--- Data Science ---
60. analyze_data_stats(file_path)           – Statistical analysis (numpy/scipy).
61. train_model(data_path, target_col, test_size?) – ML training (scikit-learn).
62. analyze_network(data?)                  – Graph analysis (networkx).

--- Audio ---
62. text_to_speech(text, lang?, filename?)  – TTS (gTTS).
63. speech_to_text(audio_file)              – STT (SpeechRecognition).
64. play_audio(file_path)                   – Audio metadata (pydub).
65. record_audio(duration?, rate?, file?)   – Record mic (sounddevice).

--- Scheduling & RPC ---
66. schedule_add(time_str, command_text)    – Task scheduler (schedule).
67. crontab_add(expr, command_text)         – Crontab entry (python-crontab).
68. rpyc_call(host, port?, func?, arg?)     – Remote procedure call (RPyC).

--- Utilities ---
69. generate_qrcode(data, file_path?)       – QR code generator.
70. generate_otp(secret?)                   – TOTP one-time password.
71. parquet_info(file_path)                 – Parquet metadata (pyarrow).
72. config_read(file_path, section?)        – INI config parser.

--- Meta ---
73. retry_with_backoff() – Info about resiliency libraries (tenacity/backoff/loguru/tqdm).

--- Proxmox VE ---
74. proxmox_list_nodes(host, token_id, token_secret, verify_ssl?)      – List Proxmox nodes.
75. proxmox_list_vms(host, token_id, token_secret, node?, verify_ssl?) – List VMs/containers.

--- Networking ---
76. wake_on_lan(mac, broadcast_ip?)        – Wake-on-LAN magic packet (wakeonlan).
77. ping_host(host, count?)                – ICMP ping (ping3).
78. network_interfaces()                   – List network interfaces (netifaces).
79. scapy_traceroute(target, max_hops?)    – Traceroute (scapy).
80. dns_lookup(domain, record_type?)       – DNS lookup (dnspython).

--- SCP File Transfer ---
81. ssh_scp_upload(host, user, local, remote, password?, port?)   – Upload via SCP.
82. ssh_scp_download(host, user, remote, local, password?, port?) – Download via SCP.

--- Process & Terminal ---
83. pexpect_spawn(command, timeout?)       – Interactive process spawn (pexpect).

--- Text & Date Utilities ---
84. humanize_value(value, type?)           – Human-readable numbers/bytes/dates (humanize).
85. slugify_text(text)                     – URL-friendly slug (python-slugify).
86. parse_string(pattern, text)            – String parsing with patterns (parse).
87. arrow_time(expression?)               – Date/time manipulation (arrow).
88. cron_next(cron_expression)             – Compute next cron execution (croniter).

--- Events & Monitoring ---
89. send_signal(name, data?)               – Send blinker signal.
90. watch_directory(path, pattern?, timeout?) – Watch for file changes (watchdog).
91. prometheus_metrics()                   – Generate Prometheus metrics.

--- Vector RAG ---
92. ask_codebase(question, top_k?)         – Ask a question about the codebase (ChromaDB vector search over workspace files).

--- Docker Compose ---
95.  docker_compose_up(file_path?, service?, detach?)       – Start compose services.
96.  docker_compose_down(file_path?, volumes?)              – Stop compose services.
97.  docker_compose_logs(file_path?, service?, tail?)       – View compose logs.
98.  docker_compose_ps(file_path?)                          – List compose containers.

--- Kubernetes ---
99.  kubectl_get(resource, namespace?, output?)             – Get K8s resources (pods, deployments, services, etc.).
100. kubectl_logs(pod, container?, namespace?, tail?, follow?) – Tail pod logs.
101. kubectl_describe(resource, name, namespace?)           – Describe K8s resource.

--- Network ---
102. scan_ports(host, ports?, timeout?)         – Scan open TCP ports on a host.

--- Log Viewer ---
103. tail_log_file(file_path, lines?, follow?)  – Tail recent log file lines.
104. search_log_file(file_path, pattern, context_lines?) – Regex-search a log file.

--- Vision ---
105. analyze_image_advanced(file_path, prompt?) – Analyze image via Gemini Vision (describe, answer questions).

=====================================================================
TOOL USAGE TIPS
=====================================================================
- For code reviews: analyze_code → analyze_python → calculate_complexity → lint_code
- For project exploration: search_files → view_file → analyze_python
- For data analysis: read_spreadsheet → read_yaml → parse_markdown → analyze_data_stats
- For debugging: git_status → git_diff → view_file → format_code → execute_command
- For DevOps: docker_ps → docker_images → ssh_execute → redis_exec → prometheus_metrics
- For home automation: broadlink_discover → mqtt_publish
- For UI testing: screen_info → capture_screen → locate_on_screen → mouse_click → type_text
- For pynput fallback: pynput_click → pynput_type (works without X display)
- For browser automation: browser_automate → browser_selenium (choose by driver availability)
- For data science: read_spreadsheet → analyze_data_stats → train_model → analyze_network
- For async DB: mongodb_async_query (motor, async/await)
- For audio pipeline: record_audio → speech_to_text → text_to_speech
- For networking: network_interfaces → ping_host → dns_lookup → scapy_traceroute
- For file transfer: ssh_scp_upload → ssh_scp_download
- For Proxmox: proxmox_list_nodes → proxmox_list_vms
- For scheduling: cron_next → croniter
"""

# ---------------------------------------------------------------------------
# Pricing & context window for token cost estimation
# ---------------------------------------------------------------------------

MODEL_INFO: dict[str, dict] = {
    # model_key  ->  {input_price_per_1M, output_price_per_1M, context_window}
    "deepseek-chat":          {"input": 0.14,  "output": 0.28,  "ctx": 131072},
    "deepseek-reasoner":      {"input": 0.55,  "output": 2.19,  "ctx": 131072},
    "gemini-2.0-flash":       {"input": 0.10,  "output": 0.40,  "ctx": 1048576},
    "gemini-2.5-flash":       {"input": 0.15,  "output": 0.60,  "ctx": 1048576},
    "gemini-2.0-pro":         {"input": 0.50,  "output": 1.50,  "ctx": 2097152},
    "gpt-4o":                 {"input": 2.50,  "output": 10.00, "ctx": 131072},
    "gpt-4o-mini":            {"input": 0.15,  "output": 0.60,  "ctx": 131072},
    "gpt-3.5-turbo":          {"input": 0.50,  "output": 1.50,  "ctx": 16384},
    "claude-3-haiku-20240307":{"input": 0.25,  "output": 1.25,  "ctx": 200000},
    "claude-3.5-sonnet":      {"input": 3.00,  "output": 15.00, "ctx": 200000},
}

DEFAULT_MODEL_INFO = {"input": 1.00, "output": 2.00, "ctx": 131072}

def _lookup_model(model_key: str) -> dict:
    """Look up pricing/context; fall back to defaults."""
    for key, info in MODEL_INFO.items():
        if key in model_key.lower():
            return info
    return dict(DEFAULT_MODEL_INFO)


def trim_chat_history(messages: list[dict], keep_last: int = 8, *, system_prompt: str | None = None) -> list[dict]:
    """Keep a single system prompt and the most recent N non-system messages.

    This applies a sliding-window context strategy so the request payload never
    keeps growing forever. It preserves the current system instruction while
    dropping stale conversation turns automatically before the provider call.
    """
    if keep_last <= 0:
        keep_last = 1

    system_msg: dict | None = None
    non_system: list[dict] = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        content = msg.get("content", "")
        if role == "system":
            if not system_msg:
                system_msg = {"role": "system", "content": content or (system_prompt or SYSTEM_PROMPT)}
            continue
        if role in {"user", "assistant", "tool"}:
            non_system.append(dict(msg))

    if system_msg is None:
        system_msg = {"role": "system", "content": system_prompt or SYSTEM_PROMPT}

    trimmed = [system_msg]
    trimmed.extend(non_system[-keep_last:])
    return trimmed


def _cap_message_context(messages: list[dict], max_chars: int) -> list[dict]:
    """Keep the system prompt and newest message content within a hard budget."""
    if max_chars <= 0:
        return messages
    result = [dict(message) for message in messages]
    total = sum(len(str(message.get("content", ""))) for message in result)
    for message in result[1:]:
        if total <= max_chars:
            break
        content = str(message.get("content", ""))
        allowed = max(200, max_chars - (total - len(content)))
        if len(content) > allowed:
            message["content"] = content[-allowed:]
            total -= len(content) - allowed
    return result


# ---------------------------------------------------------------------------
# Provider registry — ordered fallback + named selection
# ---------------------------------------------------------------------------

AVAILABLE_PROVIDERS: dict[str, str] = {}  # name -> model string (empty = default)


class _ProviderStop:
    """Combine user cancellation and provider-winner cancellation signals."""

    def __init__(self, *events: object | None) -> None:
        self._events = tuple(event for event in events if event is not None)

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)  # type: ignore[union-attr]


def log_provider_event(event: str, provider: str, status: str, details: dict | None = None, *, request_id: str | None = None) -> None:
    """Write a structured provider event to the dedicated provider log."""
    payload = {"event": event, "provider": provider, "status": status}
    if details:
        payload.update(details)
    request_label = request_id or "-"
    provider_logger.info("request_id=%s event=%s winner=%s status=%s details=%s", request_label, event, provider, status, payload)


def _try_provider(name: str, client_getter, model: str, messages: list[dict],
                  *, is_gemini: bool = False, is_g4f: bool = False,
                  on_chunk: Callable[[str], None] | None = None,
                  request_timeout: float | None = None,
                  cancel_event: object | None = None,
                  ) -> tuple[str, str, dict] | None:
    """Try a single provider. Returns (content, provider_name, usage) or None."""
    try:
        if is_g4f:
            return _try_g4f(model, messages, on_chunk=on_chunk, request_timeout=request_timeout,
                            cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
            return None
        if is_gemini:
            from google.genai import types as t
            contents = [
                t.Content(role="user" if m["role"] == "user" else "model",
                          parts=[t.Part.from_text(text=m.get("content", ""))])
                for m in messages if m["role"] != "system"
            ]
            full = ""
            prompt_tokens = 0
            completion_tokens = 0
            resp = client_getter().models.generate_content_stream(
                model=model, contents=contents,
                config=t.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.2),
                timeout=request_timeout,
            )
            for chunk in resp:
                if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
                    return None
                if chunk.text:
                    full += chunk.text
                    if on_chunk:
                        try:
                            on_chunk(chunk.text)
                        except Exception:
                            pass
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    prompt_tokens = getattr(chunk.usage_metadata, "prompt_token_count", None) or prompt_tokens
                    completion_tokens = getattr(chunk.usage_metadata, "candidates_token_count", None) or completion_tokens
            total = prompt_tokens + completion_tokens
            return full, name, {"prompt": prompt_tokens, "completion": completion_tokens, "total": total}
        full = ""
        prompt_tokens = 0
        completion_tokens = 0
        resp = client_getter().chat.completions.create(
            model=model, messages=messages, temperature=0.2, stream=True,
            timeout=request_timeout,
        )
        for chunk in resp:
            if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
                return None
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full += content
                if on_chunk:
                    try:
                        on_chunk(content)
                    except Exception:
                        pass
            usage_chunk = getattr(chunk, "usage", None)
            if usage_chunk:
                prompt_tokens = usage_chunk.prompt_tokens or prompt_tokens
                completion_tokens = usage_chunk.completion_tokens or completion_tokens
        total = prompt_tokens + completion_tokens or (len(full) // 4)
        usage = {"prompt": prompt_tokens, "completion": completion_tokens, "total": total}
        return full, name, usage
    except Exception as e:
        provider_logger.debug("[FAIL] %s | model=%s | error=%s", name, model, e)
        logger.warning("%s failed: %s", name, e)
        return None


def _try_g4f(model: str, messages: list[dict],
             on_chunk: Callable[[str], None] | None = None,
             request_timeout: float = 20.0,
             cancel_event: object | None = None,
             ) -> tuple[str, str, dict] | None:
    """Try G4F (free) as fallback provider."""
    from g4f.client import Client as G4FClient

    models_to_try = ["gpt-4o", "gpt-4", "command-r7b"]
    if model and model != "default":
        models_to_try.insert(0, model)

    client = G4FClient()
    for g4f_model in models_to_try:
        if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
            return None
        try:
            resp = client.chat.completions.create(
                model=g4f_model, messages=messages, stream=True,
                timeout=request_timeout,
            )
            full = ""
            for chunk in resp:
                if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
                    return None
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        full += delta.content
                        if on_chunk:
                            try:
                                on_chunk(delta.content)
                            except Exception:
                                pass
            if full.strip():
                total = len(full) // 4
                return full, "G4F", {"prompt": 0, "completion": total, "total": total}
        except Exception as e:
            provider_logger.debug("[FAIL] G4F | model=%s | error=%s", g4f_model, e)
            continue
    return None


# Build the provider registry — ALL visible, only keyed ones + G4F tryable
_PROVIDER_LIST: list[tuple[str, str, str, bool]] = []
# (name, client_getter_callable, model, is_gemini)

# G4F special: tuple(format: name, model, is_g4f)
_G4F_ENTRY: tuple[str, str, bool] | None = None


def _init_providers():
    from .config import (
        DEEPSEEK_API_KEY,
        DEEPSEEK_MODEL,
        FLAZ_API_KEY,
        FLAZ_MODEL,
        GEMINI_API_KEY,
        GEMINI_MODEL,
        OPENROUTER_API_KEY,
        OPENROUTER_MODEL,
        get_deepseek_client,
        get_flaz_client,
        get_gemini_client,
        get_openrouter_client,
    )

    # All provider definitions — always shown in AVAILABLE_PROVIDERS
    all_configs: list[tuple[str, str, str, str, bool, bool]] = [
        # (key_val, name, getter, model, is_gemini, is_g4f)
        (DEEPSEEK_API_KEY, "DeepSeek", get_deepseek_client, DEEPSEEK_MODEL, False, False),
        (GEMINI_API_KEY, "Gemini", get_gemini_client, GEMINI_MODEL, True, False),
        (OPENROUTER_API_KEY, "OpenRouter", get_openrouter_client, OPENROUTER_MODEL, False, False),
        (FLAZ_API_KEY, "Flaz", get_flaz_client, FLAZ_MODEL, False, False),
    ]

    global _PROVIDER_LIST, AVAILABLE_PROVIDERS, _G4F_ENTRY
    _PROVIDER_LIST.clear()
    AVAILABLE_PROVIDERS.clear()
    _G4F_ENTRY = None

    for key_val, name, getter, model, is_gemini, is_g4f in all_configs:
        model_short = model.split("/")[-1] if "/" in model else model
        valid = bool(key_val)
        # Gemini keys: "AIzaSy..." (old) or "AQ..." / "AIza..." (new Google AI Studio format)
        if is_gemini and key_val and not (key_val.startswith("AIzaSy") or key_val.startswith("AQ.")):
            valid = False
        if valid:
            AVAILABLE_PROVIDERS[name] = model_short
            _PROVIDER_LIST.append((name, getter, model, is_gemini))
        else:
            suffix = " (no key)" if not key_val else " (invalid key)"
            AVAILABLE_PROVIDERS[name] = f"{model_short}{suffix}"

    # G4F — always visible, always tryable (no key needed)
    if G4F_AVAILABLE:
        from .config import G4F_PROVIDER
        import g4f
        g4f_default = g4f.models.default
        g4f_model_name = g4f_default.name if g4f_default and g4f_default.name else "default"
        g4f_display = G4F_PROVIDER or g4f_model_name
        AVAILABLE_PROVIDERS["G4F (free)"] = g4f_display
        _G4F_ENTRY = ("G4F (free)", G4F_PROVIDER, True)


_init_providers()


def call_llm(messages: list[dict], preferred: str = "",
             on_status: Callable[[str], None] | None = None,
             on_chunk: Callable[[str], None] | None = None,
             cancel_event: threading.Event | None = None,
             ) -> tuple[str, str, dict]:
    """Try providers in order. ``preferred`` picks a specific provider first.
    
    Returns ``(content, provider_name, usage_dict)`` where ``usage_dict``
    has keys ``prompt``, ``completion``, ``total``.
    
    ``on_status`` is called with a short status message before each attempt
    (e.g. "DeepSeek…") so the UI can show live progress.
    ``on_chunk`` is called with each token as it arrives for streaming display.
    """
    os_detected = get_os_context()
    memory_ctx = ""
    try:
        from .memory import build_memory_context
        memory_ctx = build_memory_context()
    except Exception:
        pass
    dynamic_instruction = (
        SYSTEM_PROMPT
        + f"\n\n[ENV]: OS is {os_detected}. Match your solution to this architecture!"
        + (f"\n\n{memory_ctx}" if memory_ctx else "")
    )
    try:
        from .skill_manager import build_skill_context
        latest_user_input = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        skill_context = build_skill_context(latest_user_input)
        if skill_context:
            dynamic_instruction += f"\n\n{skill_context}"
    except Exception:
        pass
    try:
        from .plugin_manager import build_plugin_context
        plugin_context = build_plugin_context(latest_user_input)
        if plugin_context:
            dynamic_instruction += f"\n\n{plugin_context}"
    except Exception:
        pass

    active_messages = trim_chat_history(
        messages,
        keep_last=8,
        system_prompt=dynamic_instruction,
    )
    active_messages = _cap_message_context(active_messages, MAX_CONTEXT_CHARS)

    if cancel_event and cancel_event.is_set():
        return "Cancelled by user.", "Cancelled", {"prompt": 0, "completion": 0, "total": 0}

    request_id = f"req-{uuid.uuid4().hex[:8]}"
    log_provider_event("request_start", "system", "begin", {"provider_count": len(_PROVIDER_LIST)}, request_id=request_id)

    # Build ordered list — preferred first, then rest
    ordered = list(_PROVIDER_LIST)
    if preferred:
        pref_idx = None
        for i, (name, *_) in enumerate(ordered):
            if name.lower() == preferred.lower():
                pref_idx = i
                break
        if pref_idx is not None:
            ordered.insert(0, ordered.pop(pref_idx))

    preferred_g4f = bool(preferred and "g4f" in preferred.lower())

    import concurrent.futures as _futures
    import time as _time

    def _run_provider_candidate(
        candidate: tuple[str, object, str, bool],
        stop_event: object | None = None,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str, dict] | None:
        active_stop = stop_event or cancel_event
        if active_stop and active_stop.is_set():  # type: ignore[union-attr]
            return None
        name, getter, model, is_gemini = candidate
        provider_timeout = LLM_TIMEOUT_SECONDS or None
        log_provider_event("attempt", name, "start", {"model": model, "timeout": provider_timeout}, request_id=request_id)
        if on_status:
            on_status(f"🧠 {name}…")
        result = _try_provider(name, getter, model, active_messages,
                               is_gemini=is_gemini, on_chunk=chunk_callback or on_chunk,
                               request_timeout=provider_timeout, cancel_event=active_stop)
        if result is not None:
            log_provider_event("winner", name, "success", {"model": model, "response_len": len(result[0])}, request_id=request_id)
        else:
            log_provider_event("attempt", name, "failed", {"model": model, "timeout": provider_timeout}, request_id=request_id)
        return result

    def _run_provider_group(candidates: list[tuple[str, object, str, bool]]) -> tuple[str, str, dict] | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return _run_provider_candidate(candidates[0])

        # If Flaz is in the candidate set, give it a much longer window before a
        # fallback is considered. The previous 4.5s threshold was too aggressive and
        # caused G4F to win even when Flaz was healthy but just slower.
        has_flaz = any(name.lower() == "flaz" for name, _, _, _ in candidates)
        wait_timeout = LLM_TIMEOUT_SECONDS or None

        result_holder: dict[str, tuple[str, str, dict] | None] = {"value": None}
        result_event = threading.Event()
        stop_event = _ProviderStop(cancel_event, result_event)
        result_lock = threading.Lock()
        threads: list[object] = []

        def run_one(candidate: tuple[str, object, str, bool]) -> None:
            if stop_event.is_set():
                return
            buffered_chunks: list[str] = []
            value = _run_provider_candidate(candidate, stop_event, buffered_chunks.append)
            if value is None:
                return
            with result_lock:
                if result_event.is_set():
                    return
                result_holder["value"] = value
                result_event.set()
                if on_chunk and buffered_chunks:
                    on_chunk("".join(buffered_chunks))

        for candidate in candidates[:MAX_PROVIDER_ATTEMPTS]:
            thread = threading.Thread(target=run_one, args=(candidate,), daemon=True)
            thread.start()
            threads.append(thread)

        if not result_event.wait(timeout=wait_timeout):
            log_provider_event("fallback", "G4F (free)", "timeout_after_wait", {"model": "provider_race", "timeout": wait_timeout})
            for thread in threads:
                if thread.is_alive():
                    thread.join(timeout=0.05)
            return None

        # Success path: return immediately once a real winner is found. Waiting on
        # slow threads here reintroduces the same race bug we are trying to fix.
        return result_holder["value"]

    if preferred_g4f and _G4F_ENTRY is not None:
        g4f_name, g4f_model, _ = _G4F_ENTRY
        if on_status:
            on_status(f"🧠 {g4f_name}…")
        log_provider_event("fallback", g4f_name, "preferred", {"model": g4f_model, "timeout": 4.0}, request_id=request_id)
        result = _try_provider(g4f_name, None, g4f_model, active_messages,
                               is_g4f=True, on_chunk=on_chunk, request_timeout=4.0)
        if result is not None:
            log_provider_event("winner", g4f_name, "success", {"model": g4f_model, "response_len": len(result[0])}, request_id=request_id)
            log_provider_event("request_end", g4f_name, "final", {"response_len": len(result[0])}, request_id=request_id)
            return result
        return "Error: All providers failed or timed out.", "None", {"prompt": 0, "completion": 0, "total": 0}

    if not ordered and _G4F_ENTRY is not None:
        g4f_name, g4f_model, _ = _G4F_ENTRY
        if on_status:
            on_status(f"🧠 {g4f_name}…")
        log_provider_event("fallback", g4f_name, "no_live_providers", {"model": g4f_model, "timeout": 4.0}, request_id=request_id)
        result = _try_provider(g4f_name, None, g4f_model, active_messages,
                               is_g4f=True, on_chunk=on_chunk, request_timeout=4.0)
        if result is not None:
            log_provider_event("winner", g4f_name, "success", {"model": g4f_model, "response_len": len(result[0])}, request_id=request_id)
            log_provider_event("request_end", g4f_name, "final", {"response_len": len(result[0])}, request_id=request_id)
            return result
        return "Error: All providers failed or timed out.", "None", {"prompt": 0, "completion": 0, "total": 0}

    result = _run_provider_group(list(ordered))
    if result is not None:
        log_provider_event("winner", result[1], "selected", {"provider": result[1], "response_len": len(result[0])}, request_id=request_id)
        log_provider_event("request_end", result[1], "final", {"response_len": len(result[0])}, request_id=request_id)
        return result

    if _G4F_ENTRY is not None and not (cancel_event and cancel_event.is_set()):
        g4f_name, g4f_model, _ = _G4F_ENTRY
        if on_status:
            on_status("🧠 G4F (free)…")
        log_provider_event("fallback", g4f_name, "late_fallback", {"model": g4f_model, "timeout": 4.0}, request_id=request_id)
        result = _try_provider(g4f_name, None, g4f_model, active_messages,
                               is_g4f=True, on_chunk=on_chunk, request_timeout=4.0)
        if result is not None:
            log_provider_event("winner", g4f_name, "success", {"model": g4f_model, "response_len": len(result[0])}, request_id=request_id)
            log_provider_event("request_end", g4f_name, "final", {"response_len": len(result[0])}, request_id=request_id)
            return result

    if _G4F_ENTRY is not None and preferred and "g4f" in preferred.lower():
        _, g4f_model, _ = _G4F_ENTRY
        for alt_model in ("gpt-4", "claude-3-haiku-20240307"):
            if on_status:
                on_status(f"🧠 G4F ({alt_model})…")
            result = _try_provider("G4F (free)", None, alt_model, active_messages,
                                   is_g4f=True, on_chunk=on_chunk, request_timeout=4.0)
            if result is not None:
                log_provider_event("winner", "G4F (free)", "success", {"model": alt_model, "response_len": len(result[0])}, request_id=request_id)
                log_provider_event("request_end", "G4F (free)", "final", {"response_len": len(result[0])}, request_id=request_id)
                return result

    return "Error: All providers failed or timed out.", "None", {"prompt": 0, "completion": 0, "total": 0}


def reinit_providers() -> None:
    """Re-read config and rebuild provider registry (call after .env changes)."""
    _init_providers()


def get_provider_list() -> list[str]:
    """Return list of available provider names."""
    return list(AVAILABLE_PROVIDERS.keys())
