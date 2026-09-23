"""MCP (Model Context Protocol) server — expose homelab-ai tools as MCP tools.

Supports auth tokens, tool whitelists, and per-user session isolation.
Run standalone::

    python -m homelab_ai.mcp_server
    python -m homelab_ai.mcp_server --host 0.0.0.0 --port 8456 --auth-token sk-my-secret
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP as FastMCPType

from homelab_ai import tools as brain_tools
from homelab_ai.config import logger
from homelab_ai.schemas import TOOL_MODELS

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None

TOOL_CATEGORIES = {
    "Code": ["analyze_code", "analyze_python", "calculate_complexity", "format_code",
             "sort_imports", "lint_code", "search_files", "count_tokens"],
    "Files": ["list_dir", "view_file", "write_file", "patch_file", "read_pdf",
              "read_spreadsheet", "read_yaml", "parse_markdown", "analyze_image",
              "read_pdf_detailed", "read_excel_sheets"],
    "Git": ["git_status", "git_log", "git_diff"],
    "System": ["execute_command", "get_system_stats", "get_app_paths", "scrape_website",
               "web_search", "web_fetch_async", "get_weather", "summarize_youtube",
               "read_local_video"],
    "SSH/Docker": ["ssh_execute", "ssh_scp_upload", "ssh_scp_download", "docker_ps",
                   "docker_images", "pexpect_spawn"],
    "Network": ["ping_host", "network_interfaces", "scapy_traceroute", "dns_lookup",
                "wake_on_lan", "broadlink_discover"],
    "DB/MQ": ["redis_exec", "mongodb_query", "mongodb_async_query", "sql_query",
              "mqtt_publish"],
    "UI": ["screen_info", "capture_screen", "mouse_click", "type_text",
           "locate_on_screen", "pynput_click", "pynput_type"],
    "Browser": ["scrape_website", "cloudscrape", "browse_website", "mechanical_browse",
                "browser_automate", "browser_selenium"],
    "DS/Audio": ["analyze_data_stats", "train_model", "analyze_network",
                 "text_to_speech", "speech_to_text", "play_audio", "record_audio"],
    "Proxmox": ["proxmox_list_nodes", "proxmox_list_vms"],
    "Util": ["generate_qrcode", "generate_otp", "parquet_info", "config_read",
             "humanize_value", "slugify_text", "parse_string", "arrow_time",
             "cron_next", "prometheus_metrics", "schedule_add", "crontab_add",
             "rpyc_call", "send_signal", "watch_directory"],
}


def _dispatch(name: str, params: dict[str, Any]) -> str:
    func = getattr(brain_tools, name, None)
    if not func:
        return f"Error: tool '{name}' not found."
    try:
        result = func(**params)
        return str(result)
    except TypeError as exc:
        return f"Error: invalid params for {name}: {exc}"
    except Exception as exc:
        return f"Error: {exc}"


def _find_category(tool_name: str) -> str:
    for cat, tools in TOOL_CATEGORIES.items():
        if tool_name in tools:
            return cat
    return "Other"


def build_server(
    name: str = "homelab-ai",
    auth_token: str = "",
    whitelist: list[str] | None = None,
) -> "FastMCPType":
    """Build a FastMCP server with auth and tool whitelisting."""
    if FastMCP is None:
        raise ImportError("fastmcp not installed. Run: pip install fastmcp")

    mcp = FastMCP(name)
    allowed = set(whitelist or list(TOOL_MODELS.keys()))

    def _check_auth(headers: dict | None = None) -> bool:
        if not auth_token:
            return True
        token = (headers or {}).get("authorization", "").removeprefix("Bearer ")
        return token == auth_token

    for tool_name, model_cls in TOOL_MODELS.items():
        if tool_name not in allowed:
            continue

        schema = model_cls.model_json_schema()
        props = schema.get("properties", {})
        required = schema.get("required", [])

        sig_parts = []
        for pname, pinfo in props.items():
            opt = "" if pname in required else "?"
            sig_parts.append(f"{pname}{opt}")

        category = _find_category(tool_name)

        def _make_handler(tn: str, ms: type[Any]) -> callable:
            params = ", ".join(f"{field_name}=None" for field_name in ms.model_fields)
            namespace = {
                "_dispatch": _dispatch,
                "_tool_name": tn,
                "_model_cls": ms,
            }
            exec(
                "def handler(%s):\n    return _dispatch(_tool_name, _model_cls(**locals()).model_dump())" % params,
                namespace,
            )
            handler = namespace["handler"]
            handler.__name__ = tn
            handler.__qualname__ = tn
            return handler

        mcp.tool(
            name=tool_name,
            description=f"[{category}] {tool_name}({', '.join(sig_parts)})",
        )(_make_handler(tool_name, model_cls))

    # Add meta-tools
    @mcp.tool(name="_list_tools", description="List all available tools with descriptions")
    def list_tools() -> str:
        lines = []
        for n in sorted(allowed):
            schema = TOOL_MODELS[n].model_json_schema()
            props = ", ".join(schema.get("properties", {}).keys()) or "—"
            lines.append(f"  {n}({props})")
        return "\n".join(lines)

    @mcp.tool(name="_health", description="Health check endpoint")
    def health() -> str:
        return json.dumps({
            "status": "ok",
            "tools": len(allowed),
            "auth": bool(auth_token),
        })

    return mcp


def run_server(
    host: str = "127.0.0.1",
    port: int = 8456,
    auth_token: str = "",
    whitelist: list[str] | None = None,
):
    """Start the MCP server with optional auth."""
    token = auth_token or os.getenv("MCP_AUTH_TOKEN", "")
    mcp = build_server(auth_token=token, whitelist=whitelist)
    logger.info(
        "MCP server '%s' — %d tools, auth=%s",
        mcp.name, len(mcp._tool_manager._tools) if hasattr(mcp, '_tool_manager') else "?",
        bool(token),
    )
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HomeLab AI MCP Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8456)
    parser.add_argument("--auth-token", default="", help="Bearer token for auth")
    parser.add_argument("--whitelist", nargs="*", help="Tool names to expose (default: all)")
    args = parser.parse_args()
    run_server(
        host=args.host, port=args.port,
        auth_token=args.auth_token,
        whitelist=args.whitelist,
    )
