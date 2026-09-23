"""Smoke tests for tools.py — verify all tool functions exist and accept params."""

from __future__ import annotations

import os
import tempfile
import asyncio
from types import SimpleNamespace

import pytest


def test_list_dir() -> None:
    from homelab_ai.tools import list_dir
    result = list_dir(".")
    assert isinstance(result, str)
    assert len(result) > 0


def test_view_file() -> None:
    from homelab_ai.tools import view_file
    fname = "test_view_file_tmp.txt"
    with open(fname, "w") as f:
        f.write("hello world")
    result = view_file(fname)
    assert "hello world" in result
    os.unlink(fname)


def test_write_file() -> None:
    from homelab_ai.tools import write_file
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        pass
    result = write_file(f.name, "test content")
    assert "wrote" in result.lower() or "ok" in result.lower()
    with open(f.name) as fh:
        assert fh.read() == "test content"
    assert os.path.isfile(f.name + ".bak")
    with open(f.name + ".bak") as backup:
        assert backup.read() == ""
    os.unlink(f.name)


def test_write_file_creates_backup_for_existing_file(tmp_path) -> None:
    from homelab_ai.tools import write_file

    target = tmp_path / "existing.txt"
    target.write_text("before", encoding="utf-8")

    result = write_file(str(target), "after")

    assert "Backup" in result
    assert target.read_text(encoding="utf-8") == "after"
    assert (tmp_path / "existing.txt.bak").read_text(encoding="utf-8") == "before"


def test_get_system_stats() -> None:
    from homelab_ai.tools import get_system_stats
    result = get_system_stats()
    assert isinstance(result, str)
    assert "CPU" in result or "cpu" in result or "boot" in result


def test_count_tokens() -> None:
    from homelab_ai.tools import count_tokens
    result = count_tokens("hello world")
    assert isinstance(result, str)
    assert "tokens" in result.lower()


def test_humanize_value() -> None:
    from homelab_ai.tools import humanize_value
    result = humanize_value("1500000", type_name="number")
    assert isinstance(result, str)


def test_slugify_text() -> None:
    from homelab_ai.tools import slugify_text
    result = slugify_text("Hello World!")
    assert isinstance(result, str)
    assert "hello-world" in result.lower()


def test_config_read() -> None:
    from homelab_ai.tools import config_read
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
        f.write("[test]\nkey = value\n")
        f.flush()
        result = config_read(f.name)
    os.unlink(f.name)
    assert isinstance(result, str)


def test_build_server_registers_tools() -> None:
    from homelab_ai.mcp_server import build_server

    server = build_server(name="homelab-ai-test")

    assert server is not None
    assert asyncio.run(server.get_tool("execute_command")) is not None


def test_docker_tools_use_and_close_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from homelab_ai import tools

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False
            self.containers = SimpleNamespace(list=lambda all: [])
            self.images = SimpleNamespace(list=lambda: [])

        def close(self) -> None:
            self.closed = True

    client = FakeClient()
    monkeypatch.setitem(tools._IMPORTS, "docker", SimpleNamespace(from_env=lambda: client))

    assert tools.docker_ps() == "No containers."
    assert client.closed is True


def test_mqtt_publish_uses_client_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    from homelab_ai import tools

    calls: list[tuple] = []

    class FakeClient:
        def connect(self, host: str, port: int, keepalive: int) -> None:
            calls.append(("connect", host, port, keepalive))

        def publish(self, topic: str, message: str) -> None:
            calls.append(("publish", topic, message))

        def disconnect(self) -> None:
            calls.append(("disconnect",))

    mqtt = SimpleNamespace(Client=lambda: FakeClient())
    monkeypatch.setitem(tools._IMPORTS, "paho.mqtt.client", mqtt)
    assert "Published" in tools.mqtt_publish("home/test", "on", "broker", 1884)
    assert calls == [("connect", "broker", 1884, 60), ("publish", "home/test", "on"), ("disconnect",)]


def test_audio_validation_rejects_unsafe_empty_inputs() -> None:
    from homelab_ai import tools

    assert "must not be empty" in tools.text_to_speech(" ")
    assert "must be positive" in tools.record_audio(duration=0)


def test_executor_dry_run_does_not_write(tmp_path) -> None:
    from homelab_ai.executor import ToolExecutor

    target = tmp_path / "preview.txt"
    executor = ToolExecutor(emit=lambda *_args: None, dry_run=True)

    result = executor.dispatch("write_file", {
        "file_path": str(target),
        "content": "preview only",
    })

    assert result.startswith("DRY RUN")
    assert not target.exists()
