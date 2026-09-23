"""Validated tool dispatch for the LangGraph ``act`` node."""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from . import tools as brain_tools
from .memory import record_tool_call
from .runners import run_command_stream
from .schemas import validate_tool_params

Emit = Callable[[str, dict], None]
Approver = Callable[[dict], bool]


def _is_file_write_command(command: str) -> bool:
    """Detect shell patterns that write or overwrite local files.

    Directory creation and setup commands like ``mkdir`` or ``New-Item -ItemType Directory``
    are not file edits and must remain allowed.
    """
    lowered = command.lower()

    directory_patterns = (
        "mkdir ", "md ", "new-item -itemtype directory", "create directory",
        "-itemtype directory",
    )
    if any(pattern in lowered for pattern in directory_patterns):
        return False

    return any(pattern in lowered for pattern in (
        "set-content", "out-file", "add-content", " here-string",
        " > ", ">>", " tee ", "echo ", "write-output ",
    )) and any(token in lowered for token in (".html", ".htm", ".css", ".js", ".tsx", ".jsx"))


def _has_literal_escaped_lines(file_path: str, content: str) -> bool:
    """Detect source serialized with literal JSON-style newline escapes."""
    suffix = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
    return suffix in {"html", "htm", "css", "js", "jsx", "ts", "tsx"} and "\\n" in content and "\n" not in content


class ToolExecutor:
    def __init__(self, emit: Emit, approver: Optional[Approver] = None, dry_run: bool = False) -> None:
        self.emit = emit
        self.approver = approver or (lambda _patch: True)
        self.dry_run = dry_run

    def dispatch(self, name: str, raw_params: dict) -> str:
        payload = raw_params or {}
        if isinstance(payload, dict):
            if "parameters" in payload and isinstance(payload["parameters"], dict):
                payload = payload["parameters"]
            elif "arguments" in payload and isinstance(payload["arguments"], dict):
                payload = payload["arguments"]
            elif "args" in payload and isinstance(payload["args"], dict):
                payload = payload["args"]
            if not name and isinstance(raw_params, dict):
                candidate_name = raw_params.get("name") or raw_params.get("tool") or raw_params.get("tool_name")
                if isinstance(candidate_name, str) and candidate_name:
                    name = candidate_name
        model, error = validate_tool_params(name, payload)
        if error:
            from .config import logger
            logger.error("[Tool validation error] name=%s error=%s payload_keys=%s",
                         name, error, sorted(payload.keys()) if isinstance(payload, dict) else [])
            return error
        p = model.model_dump()

        if self.dry_run and name == "write_file":
            return f"DRY RUN: would write {p['file_path']} ({len(p['content'])} characters)."
        if self.dry_run and name == "patch_file":
            preview = brain_tools.compute_patch(p["file_path"], p["search_text"], p["replace_text"])
            if not preview.get("ok"):
                return preview.get("error", "Error: patch preview failed.")
            return f"DRY RUN: would patch {p['file_path']}.\n{preview['diff']}"

        start = time.time()
        result = self._do_dispatch(name, p)
        if name in {"write_file", "patch_file", "execute_command"}:
            from .config import logger
            logger.info("[Tool result] name=%s result=%s", name, result[:1000])
        elapsed = time.time() - start
        if result.startswith("Error"):
            record_tool_call(name, elapsed, error=result)
        else:
            record_tool_call(name, elapsed)
        return result

    def _do_dispatch(self, name: str, p: dict) -> str:
        # Self-healing: retry once if ImportError (#10)
        try:
            return self._try_dispatch(name, p)
        except ImportError as exc:
            from .config import _lazy_install
            pkg = str(exc).split("'")[1] if "'" in str(exc) else str(exc).split()[-1]
            _lazy_install(pkg)
            return self._try_dispatch(name, p)

    def _try_dispatch(self, name: str, p: dict) -> str:
        try:
            # --- Original tools ---
            if name == "scrape_website":
                return brain_tools.scrape_website(p["url"])
            if name == "read_pdf":
                return brain_tools.read_pdf(p["file_path"])
            if name == "list_dir":
                return brain_tools.list_dir(p["directory_path"])
            if name == "view_file":
                return brain_tools.view_file(p["file_path"])
            if name == "write_file":
                content = p["content"]
                if _has_literal_escaped_lines(p["file_path"], content):
                    content = content.replace("\\r\\n", "\r\n").replace("\\n", "\n").replace("\\t", "\t")
                    content = content.replace('\\"', '"')
                return brain_tools.write_file(p["file_path"], content)
            if name == "execute_command":
                if _is_file_write_command(p["command"]):
                    return (
                        "Error: Do not modify files through execute_command. "
                        "Use write_file or patch_file with the exact target path."
                    )
                return self._run_command(p["command"])


            if name == "summarize_youtube":
                return brain_tools.summarize_youtube(p["url"])
            if name == "read_local_video":
                return brain_tools.read_local_video(
                    p["file_path"],
                    on_status=lambda m: self.emit("status", {"text": m}),
                )
            if name == "web_search":
                return brain_tools.web_search(p["query"])
            if name == "get_weather":
                return brain_tools.get_weather(p["location"])
            if name == "get_system_stats":
                return brain_tools.get_system_stats()
            if name == "patch_file":
                return self._patch(p)

            # --- Phase 1 enhanced ---
            if name == "analyze_code":
                return brain_tools.analyze_code(p["file_path"], p.get("language"))
            if name == "search_files":
                return brain_tools.search_files(p["pattern"], p["root_dir"])
            if name == "count_tokens":
                return brain_tools.count_tokens(p["text"], p["model"])
            if name == "resolve_jsonref":
                return brain_tools.resolve_jsonref(p["file_path"])
            if name == "web_fetch_async":
                return asyncio.run(brain_tools.web_fetch_async(p["url"], p["method"], p.get("headers")))
            if name == "get_app_paths":
                return brain_tools.get_app_paths(p["app_name"])

            # --- Phase 2 – Code analysis ---
            if name == "analyze_python":
                return brain_tools.analyze_python(p["file_path"])
            if name == "calculate_complexity":
                return brain_tools.calculate_complexity(p["file_path"])
            if name == "format_code":
                return brain_tools.format_code(p["file_path"])
            if name == "sort_imports":
                return brain_tools.sort_imports(p["file_path"])
            if name == "lint_code":
                return brain_tools.lint_code(p["file_path"])

            # --- Phase 2 – Git ---
            if name == "git_status":
                return brain_tools.git_status(p["repo_path"])
            if name == "git_log":
                return brain_tools.git_log(p["count"], p["repo_path"])
            if name == "git_diff":
                return brain_tools.git_diff(p.get("file_path"), p["repo_path"])

            # --- Phase 2 – Documents ---
            if name == "read_spreadsheet":
                return brain_tools.read_spreadsheet(p["file_path"])
            if name == "read_excel_sheets":
                return brain_tools.read_excel_sheets(p["file_path"])
            if name == "analyze_image":
                return brain_tools.analyze_image(p["file_path"])
            if name == "read_pdf_detailed":
                return brain_tools.read_pdf_detailed(p["file_path"])
            if name == "read_yaml":
                return brain_tools.read_yaml(p["file_path"])
            if name == "parse_markdown":
                return brain_tools.parse_markdown(p["file_path"])

            # --- Phase 2 – SSH ---
            if name == "ssh_execute":
                return brain_tools.ssh_execute(p["host"], p["command"], p["username"],
                                               p["port"], p.get("key_path"))

            # --- Phase 2 – Docker ---
            if name == "docker_ps":
                return brain_tools.docker_ps(p["all_containers"])
            if name == "docker_images":
                return brain_tools.docker_images()

            # --- Phase 2 – ASCII ---
            if name == "generate_ascii_banner":
                return brain_tools.generate_ascii_banner(p["text"], p["font"])
            if name == "display_color_text":
                return brain_tools.display_color_text(p["text"], p["color"])

            # --- Phase 2 – Data serialization ---
            if name == "read_msgpack":
                return brain_tools.read_msgpack(p["file_path"])
            if name == "read_json_fast":
                return brain_tools.read_json_fast(p["file_path"])

            # --- Phase 2 – Security ---
            if name == "encrypt_text":
                return brain_tools.encrypt_text(p["plaintext"])

            # --- Phase 3 – UI Automation ---
            if name == "screen_info":
                return brain_tools.screen_info()
            if name == "capture_screen":
                return brain_tools.capture_screen()
            if name == "mouse_click":
                return brain_tools.mouse_click(p["x"], p["y"], p["button"])
            if name == "type_text":
                return brain_tools.type_text(p["text"])
            if name == "locate_on_screen":
                return brain_tools.locate_on_screen(p["image_path"])
            if name == "pynput_click":
                return brain_tools.pynput_click(p["x"], p["y"], p["button"])
            if name == "pynput_type":
                return brain_tools.pynput_type(p["text"])

            # --- Phase 3 – Web Scraping ---
            if name == "cloudscrape":
                return brain_tools.cloudscrape(p["url"])
            if name == "browse_website":
                return brain_tools.browse_website(p["url"])
            if name == "mechanical_browse":
                return brain_tools.mechanical_browse(p["url"])
            if name == "browser_automate":
                return brain_tools.browser_automate(p["url"], p.get("actions", ""))
            if name == "browser_selenium":
                return brain_tools.browser_selenium(p["url"], p.get("actions", ""))

            # --- Phase 3 – Databases ---
            if name == "redis_exec":
                return brain_tools.redis_exec(p["command"], p["host"], p["port"], p["db"])
            if name == "mongodb_query":
                return brain_tools.mongodb_query(p["connection_string"], p["database"],
                                                  p["collection"], p["query"], p["limit"])
            if name == "sql_query":
                return brain_tools.sql_query(p["connection_string"], p["query"])
            if name == "mqtt_publish":
                return brain_tools.mqtt_publish(p["topic"], p["message"], p["host"], p["port"])
            if name == "mongodb_async_query":
                return asyncio.run(brain_tools.mongodb_async_query(
                    p["connection_string"], p["database"], p["collection"], p["query"], p["limit"]))

            # --- Phase 3 – IoT ---
            if name == "broadlink_discover":
                return brain_tools.broadlink_discover()

            # --- Phase 3 – Data Science ---
            if name == "analyze_data_stats":
                return brain_tools.analyze_data_stats(p["file_path"])
            if name == "train_model":
                return brain_tools.train_model(p["data_path"], p["target_column"], p["test_size"])
            if name == "analyze_network":
                return brain_tools.analyze_network(p["data"])

            # --- Phase 3 – Audio ---
            if name == "text_to_speech":
                return brain_tools.text_to_speech(p["text"], p["lang"], p["filename"])
            if name == "speech_to_text":
                return brain_tools.speech_to_text(p["audio_file"])
            if name == "play_audio":
                return brain_tools.play_audio(p["file_path"])
            if name == "record_audio":
                return brain_tools.record_audio(p["duration"], p["samplerate"], p["filename"])

            # --- Phase 3 – Scheduling ---
            if name == "schedule_add":
                return brain_tools.schedule_add(p["time_str"], p["command_text"])
            if name == "crontab_add":
                return brain_tools.crontab_add(p["schedule_expr"], p["command_text"])
            if name == "rpyc_call":
                return brain_tools.rpyc_call(p["host"], p["port"], p["function"], p["arg"])

            # --- Phase 3 – Utilities ---
            if name == "generate_qrcode":
                return brain_tools.generate_qrcode(p["data"], p["file_path"])
            if name == "generate_otp":
                return brain_tools.generate_otp(p["secret"])
            if name == "parquet_info":
                return brain_tools.parquet_info(p["file_path"])
            if name == "config_read":
                return brain_tools.config_read(p["file_path"], p.get("section"))

            # --- Phase 4 – Additional Libraries ---
            if name == "proxmox_list_nodes":
                return brain_tools.proxmox_list_nodes(p["host"], p["token_id"], p["token_secret"], p.get("verify_ssl", True))
            if name == "proxmox_list_vms":
                return brain_tools.proxmox_list_vms(p["host"], p["token_id"], p["token_secret"], p.get("node", ""), p.get("verify_ssl", True))
            if name == "wake_on_lan":
                return brain_tools.wake_on_lan(p["mac_address"], p.get("broadcast_ip", "255.255.255.255"))
            if name == "ping_host":
                return brain_tools.ping_host(p["host"], p.get("count", 4))
            if name == "ssh_scp_upload":
                return brain_tools.ssh_scp_upload(p["host"], p["username"], p["local_path"], p["remote_path"], p.get("password", ""), p.get("port", 22))
            if name == "ssh_scp_download":
                return brain_tools.ssh_scp_download(p["host"], p["username"], p["remote_path"], p["local_path"], p.get("password", ""), p.get("port", 22))
            if name == "pexpect_spawn":
                return brain_tools.pexpect_spawn(p["command"], p.get("timeout", 30))
            if name == "network_interfaces":
                return brain_tools.network_interfaces()
            if name == "scapy_traceroute":
                return brain_tools.scapy_traceroute(p["target"], p.get("max_hops", 15))
            if name == "dns_lookup":
                return brain_tools.dns_lookup(p["domain"], p.get("record_type", "A"))
            if name == "humanize_value":
                return brain_tools.humanize_value(p["value"], p.get("type_name", "number"))
            if name == "slugify_text":
                return brain_tools.slugify_text(p["text"])
            if name == "parse_string":
                return brain_tools.parse_string(p["pattern"], p["text"])
            if name == "arrow_time":
                return brain_tools.arrow_time(p.get("expression", "now"))
            if name == "cron_next":
                return brain_tools.cron_next(p["cron_expression"])
            if name == "send_signal":
                return brain_tools.send_signal(p["name"], p.get("data", ""))
            if name == "watch_directory":
                return brain_tools.watch_directory(p["path"], p.get("pattern", ""), p.get("timeout", 5))
            if name == "prometheus_metrics":
                return brain_tools.prometheus_metrics()

            # --- Phase 5 – Vector RAG ---
            if name == "ask_codebase":
                return brain_tools.ask_codebase(p["question"], p.get("top_k", 5))

            # --- Plugin management ---
            if name == "plugin_install":
                return brain_tools.plugin_install(p["source"], p.get("name", ""))
            if name == "plugin_remove":
                return brain_tools.plugin_remove(p["name"])

            # --- Phase 6 – Docker Compose ---
            if name == "docker_compose_up":
                return brain_tools.docker_compose_up(p["file_path"], p.get("service", ""), p.get("detach", True))
            if name == "docker_compose_down":
                return brain_tools.docker_compose_down(p["file_path"], p.get("volumes", False))
            if name == "docker_compose_logs":
                return brain_tools.docker_compose_logs(p["file_path"], p.get("service", ""), p.get("tail", 50))
            if name == "docker_compose_ps":
                return brain_tools.docker_compose_ps(p["file_path"])

            # --- Phase 6 – Kubernetes ---
            if name == "kubectl_get":
                return brain_tools.kubectl_get(p["resource"], p.get("namespace", ""), p.get("output", ""))
            if name == "kubectl_logs":
                return brain_tools.kubectl_logs(p["pod"], p.get("container", ""), p.get("namespace", ""), p.get("tail", 100), p.get("follow", False))
            if name == "kubectl_describe":
                return brain_tools.kubectl_describe(p["resource"], p["name"], p.get("namespace", ""))

            # --- Phase 6 – Network Port Scanner ---
            if name == "scan_ports":
                return brain_tools.scan_ports(p["host"], p.get("ports", "1-1024"), p.get("timeout", 1.0))

            # --- Phase 6 – Log Viewer ---
            if name == "tail_log_file":
                return brain_tools.tail_log_file(p["file_path"], p.get("lines", 50), p.get("follow", False))
            if name == "search_log_file":
                return brain_tools.search_log_file(p["file_path"], p["pattern"], p.get("context_lines", 3))

            # --- Phase 6 – Vision Image Understanding ---
            if name == "analyze_image_advanced":
                return brain_tools.analyze_image_advanced(p["file_path"], p.get("prompt", "Describe this image in detail."))

        except Exception as exc:
            return f"Error executing tool logic: {exc}"
        return f"Error: Tool '{name}' not recognized."

    def _run_command(self, command: str) -> str:
        self.emit("command_start", {"command": command})
        result = run_command_stream(
            command,
            on_output=lambda line: self.emit("command_line", {"line": line}),
        )
        self.emit("command_end", {"exit_code": result.exit_code})
        return result.as_tool_result()

    def _patch(self, params: dict) -> str:
        preview = brain_tools.compute_patch(
            params["file_path"], params["search_text"], params["replace_text"]
        )
        if not preview.get("ok"):
            return preview.get("error", "Error: patch failed.")
        self.emit("patch_preview", {"file_path": preview["file_path"], "diff": preview["diff"]})
        approved = self.approver(preview)
        if not approved:
            return f"Rejected: user declined the change to '{preview['file_path']}'."
        return brain_tools.apply_patch(preview["file_path"], preview["new_content"])
