"""``python -m homelab_ai`` entrypoint."""
from __future__ import annotations

import argparse

from .tui import run


def main() -> None:
    parser = argparse.ArgumentParser(description="HomeLab AI — terminal AI companion (TUI).")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Force offline demo mode (no API calls).",
    )
    sub = parser.add_subparsers(dest="command")

    mcp_parser = sub.add_parser("mcp-server", help="Start the MCP server.")
    mcp_parser.add_argument("--host", default="127.0.0.1", help="Bind address.")
    mcp_parser.add_argument("--port", type=int, default=8000, help="Port.")
    mcp_parser.add_argument("--auth-token", default="", help="Bearer token for auth.")
    mcp_parser.add_argument("--whitelist", nargs="*", help="Tool names to expose.")

    args = parser.parse_args()

    if args.command == "mcp-server":
        from .mcp_server import run_server
        run_server(
            host=args.host, port=args.port,
            auth_token=args.auth_token,
            whitelist=args.whitelist,
        )
        return

    run(force_demo=args.demo)


if __name__ == "__main__":
    main()
