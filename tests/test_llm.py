"""Tests for llm.py provider registry."""

from __future__ import annotations

import logging


def test_get_provider_list() -> None:
    from homelab_ai.llm import get_provider_list
    providers = get_provider_list()
    assert len(providers) >= 4  # DeepSeek, Gemini, OpenRouter, Flaz
    assert "DeepSeek" in providers
    assert "Gemini" in providers


def test_available_providers_has_all() -> None:
    from homelab_ai.llm import AVAILABLE_PROVIDERS
    assert "DeepSeek" in AVAILABLE_PROVIDERS
    assert "Gemini" in AVAILABLE_PROVIDERS
    assert "OpenRouter" in AVAILABLE_PROVIDERS
    assert "Flaz" in AVAILABLE_PROVIDERS


def test_reinit_providers() -> None:
    from homelab_ai.llm import get_provider_list, reinit_providers
    before = get_provider_list()
    reinit_providers()
    after = get_provider_list()
    assert before == after


def test_trim_chat_history_keeps_system_and_latest_messages() -> None:
    from homelab_ai.llm import trim_chat_history

    history = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "m2"},
        {"role": "assistant", "content": "r2"},
        {"role": "user", "content": "m3"},
        {"role": "assistant", "content": "r3"},
        {"role": "user", "content": "m4"},
        {"role": "assistant", "content": "r4"},
        {"role": "user", "content": "m5"},
        {"role": "assistant", "content": "r5"},
        {"role": "user", "content": "m6"},
        {"role": "assistant", "content": "r6"},
        {"role": "user", "content": "m7"},
        {"role": "assistant", "content": "r7"},
        {"role": "user", "content": "m8"},
        {"role": "assistant", "content": "r8"},
        {"role": "user", "content": "m9"},
        {"role": "assistant", "content": "r9"},
    ]

    trimmed = trim_chat_history(history, keep_last=8)
    assert len(trimmed) == 9
    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["content"] == "r9"
    assert trimmed[-2]["content"] == "m9"
    assert [msg["content"] for msg in trimmed[1:]] == [
        "m6", "r6", "m7", "r7", "m8", "r8", "m9", "r9"
    ]
    assert "m1" not in [msg["content"] for msg in trimmed if msg["role"] != "system"]


def test_context_budget_keeps_system_and_trims_oldest_content() -> None:
    from homelab_ai.llm import _cap_message_context

    result = _cap_message_context([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "a" * 500},
        {"role": "assistant", "content": "b" * 500},
    ], 650)

    assert result[0]["content"] == "system"
    assert sum(len(str(message["content"])) for message in result) <= 650


def test_call_llm_returns_provider_string() -> None:
    from homelab_ai.llm import call_llm
    text, provider, usage = call_llm([{"role": "user", "content": "say hi"}], preferred="None")
    assert isinstance(text, str)
    assert isinstance(provider, str)
    assert isinstance(usage, dict)
    assert "total" in usage


def test_call_llm_uses_fast_provider_without_waiting_for_slow_fallback(monkeypatch, time_machine=None) -> None:
    import threading
    import time

    import homelab_ai.llm as llm

    class FakeCompletions:
        def __init__(self, payload: str, delay: float):
            self.payload = payload
            self.delay = delay

        def create(self, *args, **kwargs):
            time.sleep(self.delay)

            class Delta:
                def __init__(self, content: str):
                    self.content = content

            class Choice:
                def __init__(self, content: str):
                    self.delta = Delta(content)

            class Chunk:
                def __init__(self, content: str):
                    self.choices = [Choice(content)]
                    self.usage = None

            return [Chunk(self.payload)]

    class FakeClient:
        def __init__(self, payload: str, delay: float):
            self.chat = type(
                "Chat",
                (),
                {
                    "completions": type(
                        "Completions",
                        (),
                        {"create": lambda self, *a, **k: FakeCompletions(payload, delay).create()},
                    )()
                },
            )()

    def slow_getter():
        return FakeClient("slow", 0.5)

    def fast_getter():
        return FakeClient("fast", 0.05)

    monkeypatch.setattr(llm, "_PROVIDER_LIST", [("Slow", slow_getter, "slow-model", False), ("Fast", fast_getter, "fast-model", False)])
    monkeypatch.setattr(llm, "_G4F_ENTRY", None)

    start = time.time()
    text, provider, usage = llm.call_llm([{"role": "user", "content": "say hi"}], preferred="")
    elapsed = time.time() - start

    assert text == "fast"
    assert provider == "Fast"
    assert elapsed < 0.9
    assert usage["total"] >= 0


def test_extract_tool_json_handles_code_fence_and_trailing_text() -> None:
    from homelab_ai.graph import _extract_tool_json

    payload = '''
THOUGHT: I will search for a free billiard game on Steam.
CALL_TOOL: ```json
{"name": "web_search", "parameters": {"query": "free billiard games steam"}}
```

FINAL_ANSWER: I found a few options.
'''

    assert _extract_tool_json(payload) == {
        "name": "web_search",
        "parameters": {"query": "free billiard games steam"},
    }


def test_edit_manifest_detects_missing_sibling_files(tmp_path) -> None:
    from homelab_ai.graph import _missing_requested_files

    target = tmp_path / "index.html"
    target.write_text("<html></html>", encoding="utf-8")
    messages = [{
        "role": "user",
        "content": f"Create {target}, style.css, and script.js",
    }]

    missing = _missing_requested_files(messages, str(target))

    assert str(tmp_path / "script.js") in missing


def test_edit_evidence_reports_missing_html_asset(tmp_path) -> None:
    from homelab_ai.graph import _edit_evidence

    target = tmp_path / "index.html"
    target.write_text('<html><link rel="stylesheet" href="style.css"></html>', encoding="utf-8")
    evidence = _edit_evidence([{"role": "user", "content": f"fix {target}"}], str(target))

    assert "exists" in evidence
    assert "asset missing: style.css" in evidence


def test_source_validator_reports_python_syntax_error(tmp_path) -> None:
    from homelab_ai.graph import _validate_source

    target = tmp_path / "broken.py"
    target.write_text("def broken(:\n", encoding="utf-8")

    checks = _validate_source(str(target))

    assert checks[0].startswith("python syntax error")


def test_call_llm_prefers_flaz_over_g4f_when_flaz_responds_before_timeout(monkeypatch) -> None:
    import time

    import homelab_ai.llm as llm

    class FakeCompletions:
        def __init__(self, payload: str, delay: float):
            self.payload = payload
            self.delay = delay

        def create(self, *args, **kwargs):
            time.sleep(self.delay)

            class Delta:
                def __init__(self, content: str):
                    self.content = content

            class Choice:
                def __init__(self, content: str):
                    self.delta = Delta(content)

            class Chunk:
                def __init__(self, content: str):
                    self.choices = [Choice(content)]
                    self.usage = None

            return [Chunk(self.payload)]

    class FakeClient:
        def __init__(self, payload: str, delay: float):
            self.chat = type(
                "Chat",
                (),
                {
                    "completions": type(
                        "Completions",
                        (), {"create": lambda self, *a, **k: FakeCompletions(payload, delay).create()},
                    )()
                },
            )()

    def openrouter_getter():
        return FakeClient("openrouter", 2.0)

    def flaz_getter():
        return FakeClient("flaz", 1.3)

    monkeypatch.setattr(llm, "_PROVIDER_LIST", [("OpenRouter", openrouter_getter, "or-model", False), ("Flaz", flaz_getter, "flaz-model", False)])
    monkeypatch.setattr(llm, "_G4F_ENTRY", ("G4F (free)", "gpt-4o-mini", True))

    text, provider, usage = llm.call_llm([{"role": "user", "content": "say hi"}], preferred="")

    assert text == "flaz"
    assert provider == "Flaz"
    assert usage["total"] >= 0


def test_validate_tool_params_accepts_wrapped_payload() -> None:
    from homelab_ai.schemas import validate_tool_params

    model, error = validate_tool_params("get_system_stats", {"name": "get_system_stats", "parameters": {}})
    assert error is None
    assert model is not None
    assert model.model_dump() == {}


def test_extract_tool_json_handles_space_variant_and_trailing_note() -> None:
    from homelab_ai.graph import _extract_tool_json

    payload = '''
[CALL TOOL]
THOUGHT: I need to inspect the machine.
CALL TOOL: {"name": "get_system_stats", "parameters": {}}
Note: That was a tool call.
'''

    assert _extract_tool_json(payload) == {
        "name": "get_system_stats",
        "parameters": {},
    }


def test_extract_tool_json_handles_windows_command_with_trailing_text() -> None:
    from homelab_ai.graph import _extract_tool_json

    payload = (
        '[CALL TOOL] THOUGHT: create the public folder. '
        'CALL_TOOL: {"name": "execute_command", '
        '"parameters": {"command": "mkdir D:\\web-tabungan\\public"}} '
        "I will continue after the tool result."
    )

    assert _extract_tool_json(payload) == {
        "name": "execute_command",
        "parameters": {"command": "mkdir D:\\web-tabungan\\public"},
    }


def test_has_tool_call_does_not_allow_invalid_call_to_become_final() -> None:
    from homelab_ai.graph import _has_tool_call

    assert _has_tool_call("I will call a tool. CALL TOOL: not-json")


def test_final_answer_wins_over_echoed_tool_protocol() -> None:
    from homelab_ai.graph import _extract_tool_json, _has_tool_call

    response = (
        'CALL_TOOL: {"name": "tool_name", "parameters": {...}} '
        "FINAL_ANSWER: hei"
    )

    assert _has_tool_call(response)
    assert _extract_tool_json(response) is None


def test_extract_tool_json_handles_bracket_call_tool_format() -> None:
    from homelab_ai.graph import _extract_tool_json

    payload = (
        '[CALL TOOL] {"name": "execute_command", "parameters": '
        '{"command": "cd /d D:\\web-tabungan && mkdir public"}}'
    )

    assert _extract_tool_json(payload) == {
        "name": "execute_command",
        "parameters": {"command": "cd /d D:\\web-tabungan && mkdir public"},
    }


def test_extract_tool_json_normalizes_qwen_tool_arguments_wrapper() -> None:
    from homelab_ai.graph import _extract_tool_json

    payload = (
        "[CALL TOOL] THOUGHT: prepare the project. "
        '{"tool": "execute_command", "arguments": '
        '{"command": "cd /d D:\\web-tabungan && mkdir public"}}'
    )

    assert _extract_tool_json(payload) == {
        "name": "execute_command",
        "parameters": {"command": "cd /d D:\\web-tabungan && mkdir public"},
    }


def test_extract_tool_json_accepts_python_style_tool_dict() -> None:
    from homelab_ai.graph import _extract_tool_json

    payload = (
        "CALL_TOOL: {'name': 'execute_command', 'parameters': "
        "{'command': 'cd /d D:\\\\web-tabungan && mkdir public'}}"
    )

    assert _extract_tool_json(payload) == {
        "name": "execute_command",
        "parameters": {"command": "cd /d D:\\web-tabungan && mkdir public"},
    }


def test_windows_mkdir_command_is_idempotent() -> None:
    from homelab_ai.runners import run_command_stream

    result = run_command_stream("cd /d D:\\web-tabungan && mkdir public && echo after_mkdir")

    assert not result.blocked
    assert result.exit_code == 0
    assert "after_mkdir" in result.output


def test_execute_command_allows_directory_creation_but_blocks_file_redirection() -> None:
    from homelab_ai.executor import _is_file_write_command

    assert not _is_file_write_command("mkdir D:\\web-tabungan\\public")
    assert not _is_file_write_command("New-Item -ItemType Directory -Path D:\\web-tabungan\\public")
    assert _is_file_write_command("echo hello > D:\\web-tabungan\\index.html")
    assert _is_file_write_command("Set-Content -Path D:\\web-tabungan\\style.css -Value 'body{}'")


def test_coding_setup_result_requires_file_write_next() -> None:
    from homelab_ai.graph import _extract_target_path, _is_edit_request

    messages = [{
        "role": "user",
        "content": "buatkan website di D:\\web-tabungan dengan npm",
    }]

    messages.extend([
        {"role": "assistant", "content": "CALL_TOOL: setup"},
        {"role": "user", "content": "Tool Result: Exit Code: 0"},
        {"role": "user", "content": "The setup command succeeded. Use write_file now."},
    ])

    assert _is_edit_request(messages)
    assert _extract_target_path(messages) is None


def test_provider_selection_logs_winner_and_uses_logs_folder(caplog) -> None:
    import homelab_ai.config as config
    import homelab_ai.llm as llm

    assert str(config.LOG_FILE).replace("\\", "/").endswith("/logs/agent_log.txt")
    assert str(config.PROVIDER_LOG_FILE).replace("\\", "/").endswith("/logs/provider_failures.log")

    caplog.set_level(logging.DEBUG, logger="homelab_ai.providers")
    llm.log_provider_event("winner", "Flaz", "HTTP 200 OK", {"model": "claude-sonnet-4-20250514"}, request_id="req-test-001")
    llm.log_provider_event("request_end", "Flaz", "final", {"response_len": 123}, request_id="req-test-001")

    assert "winner=Flaz" in caplog.text
    assert "HTTP 200 OK" in caplog.text
    assert "request_id=req-test-001" in caplog.text
    assert "request_end" in caplog.text
