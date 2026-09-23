"""Command execution layer built on **pexpect** and **plumbum**.

* ``pexpect`` drives a pseudo-terminal so command output can be streamed line
  by line into the TUI in real time (like Claude Code's shell tool).
* ``plumbum`` resolves executables and opens files / URLs with the host's
  native launcher.

Safety vetting (``ALLOWED_COMMANDS`` + the LLM ``check_command_safety``) is
reused from :mod:`homelab_ai.tools` so the brain's policy is unchanged.
"""
from __future__ import annotations

import platform
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

import pexpect
from plumbum import local
from plumbum.commands.processes import CommandNotFound

from .config import logger
from .tools import ALLOWED_COMMANDS, check_command_safety

OutputCallback = Callable[[str], None]


@dataclass
class CommandResult:
    command: str
    exit_code: Optional[int]
    output: str
    blocked: bool = False
    error: Optional[str] = None
    lines: list[str] = field(default_factory=list)

    def as_tool_result(self) -> str:
        """Render in the same shape the brain expects from ``execute_command``."""
        if self.blocked:
            return self.error or "Error: command blocked."
        if self.error:
            return f"Error executing command: {self.error}"
        result = f"Exit Code: {self.exit_code}\nSTDOUT:\n{self.output}\nSTDERR:\n"
        if self.exit_code not in (0, None):
            result += (
                "\n[System Warning]: The command executed with a non-zero exit code. "
                "Inspect the output, audit the offending file with 'view_file' and "
                "repair it with 'write_file'/'patch_file'."
            )
        return result


def _vet(command: str) -> Optional[str]:
    """Return an error string if the command is not allowed, else ``None``."""
    segments = [segment.strip() for segment in command.split("&&") if segment.strip()]
    for segment in segments:
        try:
            args = shlex.split(segment)
        except ValueError as exc:
            return f"Error: could not parse command ({exc})."
        if not args:
            continue

        base = args[0].lower()
        if base in ALLOWED_COMMANDS:
            continue

        if check_command_safety(segment):
            ALLOWED_COMMANDS.add(base)
            logger.info("[Auto-Learned Command]: Integrated '%s' into trusted database.", base)
            continue

        logger.warning("[Security Block]: Blocked dangerous command: '%s'", segment)
        return f"Error: The command '{base}' was flagged as restricted or dangerous."

    return None


def run_command_stream(
    command: str,
    on_output: Optional[OutputCallback] = None,
    timeout: int = 30,
) -> CommandResult:
    """Run *command* in a PTY, streaming each line through *on_output*."""
    blocked = _vet(command)
    if blocked:
        if on_output:
            on_output(blocked)
        return CommandResult(command=command, exit_code=None, output="", blocked=True, error=blocked)

    # Windows 'start' shim, preserved from the original behaviour.
    spawn_target = command
    if platform.system() == "Windows" and command.strip().lower().startswith("start "):
        remaining = command.strip()[6:]
        spawn_target = f'powershell -Command "Start-Process {remaining}"'

    if platform.system() == "Windows":
        spawn_target = re.sub(
            r"(?i)(?<![\w-])(?:mkdir|md)\s+([^&|]+)",
            lambda match: f'(if not exist "{match.group(1).strip().strip(chr(34))}" mkdir "{match.group(1).strip().strip(chr(34))}")',
            spawn_target,
        )

    if platform.system() == "Windows":
        try:
            completed = subprocess.run(
                spawn_target,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = completed.stdout
            if completed.stderr:
                output = f"{output}{completed.stderr}"
            lines = output.rstrip("\r\n").splitlines() if output else []
            for line in lines:
                if on_output:
                    on_output(line)
            return CommandResult(
                command=command,
                exit_code=completed.returncode,
                output=output.rstrip("\r\n"),
                lines=lines,
            )
        except subprocess.TimeoutExpired:
            logger.error("[Command Timeout]: Execution exceeded %ss for: %s", timeout, command)
            msg = "Error: Command execution timeout."
            if on_output:
                on_output(msg)
            return CommandResult(command=command, exit_code=None, output="", error="timeout")
        except Exception as exc:  # noqa: BLE001
            logger.error("[Command Error]: %s", exc)
            if on_output:
                on_output(f"Error: {exc}")
            return CommandResult(command=command, exit_code=None, output="", error=str(exc))

    collected: list[str] = []
    try:
        child = pexpect.spawn(
            "/bin/sh" if platform.system() != "Windows" else "cmd",
            ["-c", spawn_target] if platform.system() != "Windows" else ["/c", spawn_target],
            encoding="utf-8",
            timeout=timeout,
            echo=False,
        )
        while True:
            try:
                line = child.readline()
            except pexpect.TIMEOUT:
                child.close(force=True)
                logger.error("[Command Timeout]: Execution exceeded %ss for: %s", timeout, command)
                msg = "Error: Command execution timeout."
                if on_output:
                    on_output(msg)
                return CommandResult(command=command, exit_code=None, output="\n".join(collected), error="timeout")
            if not line:
                break
            line = line.rstrip("\r\n")
            collected.append(line)
            if on_output:
                on_output(line)
        child.close()
        return CommandResult(
            command=command,
            exit_code=child.exitstatus,
            output="\n".join(collected),
            lines=collected,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[Command Error]: %s", exc)
        if on_output:
            on_output(f"Error: {exc}")
        return CommandResult(command=command, exit_code=None, output="\n".join(collected), error=str(exc))


def which(binary: str) -> Optional[str]:
    """Resolve an executable path using plumbum, or ``None`` if missing."""
    try:
        return str(local[binary].executable)
    except CommandNotFound:
        return None


def open_path(target: str) -> str:
    """Open a file/URL/app with the host's native launcher via plumbum."""
    system = platform.system()
    launcher = {"Windows": "start", "Darwin": "open"}.get(system, "xdg-open")
    if which(launcher) is None and launcher != "start":
        return f"Error: launcher '{launcher}' not found on this system."
    try:
        local[launcher].run([target], retcode=None)
        return f"Opened '{target}' via {launcher}."
    except Exception as exc:  # noqa: BLE001
        return f"Error opening '{target}': {exc}"
