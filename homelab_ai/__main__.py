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

    sub.add_parser("doctor", help="Check installation health.")
    sub.add_parser("update", help="Update a Git checkout and dependencies.")
    sub.add_parser("rollback", help="Rollback a clean Git checkout by one commit.")
    uninstall_parser = sub.add_parser("uninstall", help="Show a safe uninstall plan.")
    uninstall_parser.add_argument("--remove-data", action="store_true", help="Also remove .env, skills, and plugins.")
    uninstall_parser.add_argument("--confirm", action="store_true", help="Actually remove the installation.")

    args = parser.parse_args()

    if args.command == "mcp-server":
        from .mcp_server import run_server
        run_server(
            host=args.host, port=args.port,
            auth_token=args.auth_token,
            whitelist=args.whitelist,
        )
        return

    if args.command in {"doctor", "update", "rollback", "uninstall"}:
        from . import maintenance
        if args.command == "doctor":
            print(maintenance.doctor())
        elif args.command == "update":
            print(maintenance.update())
        elif args.command == "rollback":
            print(maintenance.rollback())
        else:
            print(maintenance.uninstall(remove_data=args.remove_data, confirm=args.confirm))
        return

    run(force_demo=args.demo)


if __name__ == "__main__":
    main()
