"""ReAct orchestration as a **LangGraph** state machine.

The original ``for i in range(10)`` think/act loop is rebuilt as an explicit
graph:  ``think`` -> (``act`` -> ``think``)* -> ``END``. The brain itself
(``call_llm`` and the tool functions) is untouched — LangGraph only drives the
control flow and emits structured UI events through a callback so the Textual
layer can render thoughts, tool calls, streamed output and final answers.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import MAX_ATTEMPTS, MAX_TOTAL_TOKENS, logger
from .executor import ToolExecutor
from .plugin_manager import apply_after_query, apply_before_query, discover_plugins

# Discover plugins at import time so hooks are available before any query runs.
try:
    discover_plugins()
except Exception:
    pass

Emit = Callable[[str, dict], None]
# A zero/unset attempt limit must remain bounded. Provider failures and malformed
# tool calls can otherwise consume the account budget indefinitely.
MAX_ITERATIONS = min(MAX_ATTEMPTS if MAX_ATTEMPTS > 0 else 20, 20)
MAX_REPEATED_TOOL_CALLS = 3


class AgentState(TypedDict, total=False):
    messages: list[dict]
    iterations: int
    final_answer: Optional[str]
    provider: Optional[str]
    pending_tool: Optional[dict]
    retry: bool
    tool_counts: dict[str, int]
    tool_fingerprints: dict[str, int]
    done: bool
    cancelled: bool
    usage_total: int
    file_baselines: dict[str, str]


def _has_tool_call(text: str) -> bool:
    """Accept both ``CALL_TOOL:`` and ``CALL TOOL:`` output styles."""
    normalized = re.sub(r"[\u200b\ufeff\r\n]+", " ", text or "")
    return bool(re.search(
        r"(?:\[\s*)?CALL[\s_-]*TOOL(?:\s*\]|\s*:)",
        normalized,
        re.IGNORECASE,
    ))


def _extract_tool_json(text: str) -> Optional[dict]:
    """Pull the first JSON object after a tool-call marker, tolerant of fences and spacing."""
    normalized = re.sub(r"[\u200b\ufeff\r\n]+", " ", text or "")
    match = re.search(
        r"(?:\[\s*)?CALL[\s_-]*TOOL(?:\s*\]|\s*:)\s*",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None

    raw = normalized[match.end():].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)

    # Providers sometimes add a thought between the marker and JSON, or use a
    # wrapper such as {"tool": ..., "arguments": ...}. Try every object
    # boundary so either form can reach the normalizer below.
    decoder = json.JSONDecoder()
    for start in range(len(raw)):
        if raw[start] != "{":
            continue
        candidate = raw[start:]
        # Some Windows-focused models emit C:\path inside JSON without escaping
        # the backslashes. Repair only backslashes that are not valid escapes.
        candidate = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", candidate)
        try:
            obj, _ = decoder.raw_decode(candidate)
            if isinstance(obj, dict) and _looks_like_tool_call(obj):
                return _normalize_tool_call_shape(obj)
        except json.JSONDecodeError:
            continue

    # Some instruct models emit Python-style dicts with single quotes instead
    # of JSON. literal_eval parses data without executing arbitrary code.
    for start in range(len(raw)):
        if raw[start] != "{":
            continue
        try:
            obj = ast.literal_eval(raw[start:])
        except (SyntaxError, ValueError):
            continue
        if isinstance(obj, dict) and _looks_like_tool_call(obj):
            return _normalize_tool_call_shape(obj)

    # Last-resort recovery for malformed JSON emitted by some providers. The
    # tool contract is simple enough to recover a quoted Windows path safely.
    name_match = re.search(r'["\']name["\']\s*:\s*["\']([^"\']+)["\']', raw)
    path_match = re.search(r'["\']file_path["\']\s*:\s*["\']([^"\']+)["\']', raw)
    if name_match and path_match and name_match.group(1) == "view_file":
        return {
            "name": "view_file",
            "parameters": {"file_path": path_match.group(1).replace("\\\\", "\\")},
        }

    return None


def _looks_like_tool_call(payload: dict) -> bool:
    return bool(
        payload.get("name")
        or payload.get("tool")
        or payload.get("tool_name")
        or payload.get("function")
    )


def _normalize_tool_call_shape(payload: dict) -> dict:
    """Normalize common OpenAI/Qwen tool wrappers to the internal contract."""
    name = payload.get("name") or payload.get("tool") or payload.get("tool_name")
    function = payload.get("function")
    if isinstance(function, dict):
        name = name or function.get("name")
        payload = {**function, **payload}
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        for key in ("arguments", "args", "input"):
            if isinstance(payload.get(key), dict):
                parameters = payload[key]
                break
    return {"name": name, "parameters": parameters or {}}


@dataclass
class CompiledAgent:
    graph: Any
    executor: ToolExecutor
    cancel_event: threading.Event

    def run(self, messages: list[dict]) -> AgentState:
        state: AgentState = {
            "messages": messages,
            "iterations": 0,
            "final_answer": None,
            "provider": None,
            "pending_tool": None,
            "retry": False,
            "tool_counts": {},
            "tool_fingerprints": {},
            "done": False,
            "cancelled": False,
            "usage_total": 0,
            "file_baselines": _file_manifest(messages),
        }
        return self.graph.invoke(state, {"recursion_limit": MAX_ITERATIONS * 4})


def build_agent(emit: Emit, llm_fn: Optional[Callable] = None,
                approver: Optional[Callable[[dict], bool]] = None,
                cancel_event: Optional[threading.Event] = None,
                dry_run: bool = False) -> CompiledAgent:
    """Build a compiled LangGraph agent.

    * ``emit`` streams UI events (event_type, payload).
    * ``llm_fn`` defaults to the real :func:`homelab_ai.llm.call_llm`.
    * ``approver`` is asked to confirm ``patch_file`` edits (defaults to allow).
    """
    if llm_fn is None:
        from .llm import call_llm as llm_fn  # noqa: PLC0415

    executor = ToolExecutor(emit=emit, approver=approver, dry_run=dry_run)
    cancel_event = cancel_event or threading.Event()

    def think(state: AgentState) -> AgentState:
        if cancel_event.is_set():
            return _cancelled_state(state, emit)
        attempt_label = str(MAX_ITERATIONS)
        emit("status", {"text": f"Thinking… (attempt {state['iterations'] + 1}/{attempt_label})"})
        messages = list(state["messages"])
        if messages and messages[-1]["role"] == "user":
            msg = messages[-1]
            messages[-1] = {"role": "user", "content": apply_before_query(msg.get("content", ""))}
        # Streaming support: collect chunks and emit to UI
        _chunks: list[str] = []
        def _on_chunk(text: str) -> None:
            _chunks.append(text)
            emit("chunk", {"text": text})
        usage: dict = {"prompt": 0, "completion": 0, "total": 0}
        provider = "None"
        try:
            parameters = inspect.signature(llm_fn).parameters
            supports_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            call_kwargs = {}
            if "on_chunk" in parameters or supports_kwargs:
                call_kwargs["on_chunk"] = _on_chunk
            if "cancel_event" in parameters or supports_kwargs:
                call_kwargs["cancel_event"] = cancel_event
            ai_response, provider, usage = llm_fn(messages, **call_kwargs)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001
            logger.error("[LLM Error]: %s", exc)
            error_text = f"Error contacting model: {exc}"
            emit("error", {"text": error_text})
            emit("final", {"text": error_text, "provider": provider, "usage": usage})
            return {**state, "done": True, "final_answer": error_text}

        if not isinstance(ai_response, str) or not ai_response.strip():
            if state.get("iterations", 0) >= MAX_ITERATIONS:
                final = f"{provider} returned empty responses twice; no file change was applied."
                emit("final", {"text": final, "provider": provider, "usage": usage})
                return {**state, "final_answer": final, "done": True, "retry": False}
            retry_message = (
                "The previous model response was empty. Continue the user's request now. "
                "Use the requested tool or provide a concrete result; do not return an empty response."
            )
            emit("error", {"text": f"{provider} returned an empty response; retrying."})
            return {
                **state,
                "messages": state["messages"] + [{"role": "user", "content": retry_message}],
                "provider": provider,
                "iterations": state["iterations"] + 1,
                "retry": True,
            }

        usage_total = state.get("usage_total", 0) + int(usage.get("total", 0) or 0)
        if usage_total >= MAX_TOTAL_TOKENS:
            final = f"Stopped: task token budget reached ({usage_total}/{MAX_TOTAL_TOKENS})."
            emit("error", {"text": final})
            emit("final", {"text": final, "provider": provider, "usage": usage})
            return {**state, "messages": state["messages"], "provider": provider,
                    "usage_total": usage_total, "final_answer": final,
                    "done": True, "retry": False}

        messages = state["messages"] + [{"role": "assistant", "content": ai_response}]
        # Internal thought is not displayed in the UI
        thought = _split_thought(ai_response)
        logger.info("[Agent raw response] provider=%s text=%r", provider, ai_response[:4000])

        tool_call = _extract_tool_json(ai_response) or _extract_view_file_call(ai_response)
        if tool_call:
                tool_call = _normalize_tool_call(tool_call)
                tool_name = str(tool_call.get("name", ""))
                tool_counts = dict(state.get("tool_counts", {}))
                tool_fingerprints = dict(state.get("tool_fingerprints", {}))
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                fingerprint = _tool_fingerprint(tool_call)
                tool_fingerprints[fingerprint] = tool_fingerprints.get(fingerprint, 0) + 1
                if tool_fingerprints[fingerprint] > 1:
                    final = f"Stopped: duplicate tool call '{tool_name}' was already attempted."
                    emit("error", {"text": final})
                    emit("final", {"text": final, "provider": provider, "usage": usage})
                    return {**state, "messages": messages, "provider": provider,
                            "tool_counts": tool_counts, "tool_fingerprints": tool_fingerprints,
                            "final_answer": final, "done": True, "retry": False}
                if tool_counts[tool_name] > MAX_REPEATED_TOOL_CALLS:
                    final = f"Stopped: tool '{tool_name}' was called repeatedly without completing the task."
                    emit("error", {"text": final})
                    emit("final", {"text": final, "provider": provider, "usage": usage})
                    return {
                        **state,
                        "messages": messages,
                        "provider": provider,
                        "tool_counts": tool_counts,
                        "final_answer": final,
                        "done": True,
                        "retry": False,
                    }
                if _is_edit_request(state["messages"]) and tool_name == "view_file" and tool_counts[tool_name] > 1:
                    return _tool_loop_state(
                        state, messages, provider, tool_counts,
                        "The target file was already read. Stop calling view_file and use patch_file or write_file now.",
                    )
                if tool_name == "execute_command" and _is_file_write_tool_call(tool_call):
                    return _tool_loop_state(
                        state, messages, provider, tool_counts,
                        "This command is forbidden for file edits. Use write_file or patch_file now.",
                    )
                return {**state, "messages": messages, "provider": provider,
                    "pending_tool": tool_call, "tool_counts": tool_counts,
                    "tool_fingerprints": tool_fingerprints, "usage_total": usage_total,
                    "retry": False}

        # Providers sometimes echo the protocol examples from the system prompt
        # and still return a normal final answer. Do not retry that answer as an
        # invalid tool call unless it contains no explicit final-answer marker.
        has_final_answer = bool(re.search(r"FINAL\s*_?\s*ANSWER\s*:", ai_response, re.IGNORECASE))
        if _has_tool_call(ai_response) and not has_final_answer:
            tool_counts = dict(state.get("tool_counts", {}))
            tool_counts["__invalid__"] = tool_counts.get("__invalid__", 0) + 1
            if tool_counts["__invalid__"] >= 2:
                final = "The model returned an invalid tool call twice; no tool was executed."
                emit("error", {"text": final})
                emit("final", {"text": final, "provider": provider, "usage": usage})
                return {**state, "messages": messages, "provider": provider,
                        "tool_counts": tool_counts, "final_answer": final,
                        "done": True, "retry": False}
            return {
                **state,
                "messages": messages + [{
                    "role": "user",
                    "content": (
                        "Your tool call was not valid JSON. Retry it now using exactly "
                        'CALL_TOOL: {"name": "tool_name", "parameters": {...}} '
                        "with no markdown or extra text."
                    ),
                }],
                "provider": provider,
                "tool_counts": tool_counts,
                "usage_total": usage_total,
                "iterations": state.get("iterations", 0) + 1,
                "retry": True,
            }

        if re.search(r"FINAL\s*_?\s*ANSWER\s*:", ai_response, re.IGNORECASE):
            final = re.split(r"FINAL\s*_?\s*ANSWER\s*:", ai_response, maxsplit=1, flags=re.IGNORECASE)[1]
        elif "THOUGHT:" in ai_response:
            final = ai_response.split("THOUGHT:", 1)[1]
        else:
            final = ai_response
        if _is_edit_request(state["messages"]) and state.get("iterations", 0) < MAX_ITERATIONS:
            target_path = _extract_target_path(state["messages"])
            source_content = _extract_source_content(final)
            if target_path and source_content:
                return {
                    **state,
                    "messages": messages,
                    "provider": provider,
                    "pending_tool": {
                        "name": "write_file",
                        "parameters": {"file_path": target_path, "content": source_content},
                    },
                    "usage_total": usage_total,
                    "retry": False,
                }
            edit_message = (
                "Do not return source code as the final answer yet. The user requested an edit. "
                "Use patch_file or write_file on the exact target file now, then report the result."
            )
            return {
                **state,
                "messages": messages + [{"role": "user", "content": edit_message}],
                "provider": provider,
                "usage_total": usage_total,
                "iterations": state.get("iterations", 0) + 1,
                "retry": True,
            }
        # Strip ReAct artifacts from the start of the final text
        final = re.sub(r'^(?:\[FINAL ANSWER\]|THOUGHT:)\s*', '', final.strip())
        final = final.lstrip('. \t\n\r')
        final = _format_code_response(final)
        emit("final", {"text": final, "provider": provider, "usage": usage})
        return {**state, "messages": messages, "provider": provider,
            "usage_total": usage_total, "final_answer": final, "done": True, "retry": False}

    def act(state: AgentState) -> AgentState:
        if cancel_event.is_set():
            return _cancelled_state(state, emit)
        pending = state.get("pending_tool") or {}
        name = pending.get("name", "")
        params = pending.get("parameters", {})
        emit("tool_call", {"name": name, "parameters": params, "provider": state.get("provider")})
        result = executor.dispatch(name, params)
        emit("tool_result", {"name": name, "result": result})
        messages = state["messages"] + [{"role": "user", "content": f"Tool Result: {result}"}]
        if name in {"write_file", "patch_file", "apply_patch"} and not result.startswith("Error"):
            if dry_run:
                final = f"Dry run complete. No files changed.\n{result}"
                emit("final", {"text": final, "provider": state.get("provider"), "usage": {}})
                return {**state, "messages": messages, "pending_tool": None,
                        "final_answer": final, "done": True}
            incomplete_files = _incomplete_requested_files(
                state["messages"], state.get("file_baselines", {}), params.get("file_path", "")
            )
            if incomplete_files and state.get("iterations", 0) + 1 < MAX_ITERATIONS:
                missing_list = ", ".join(incomplete_files)
                return {
                    **state,
                    "messages": messages + [{
                        "role": "user",
                        "content": (
                            f"The previous file was written successfully. Continue the same task now. "
                            f"Write every remaining requested file using write_file: {missing_list}. "
                            "Do not answer yet and do not repeat files that already succeeded."
                        ),
                    }],
                    "pending_tool": None,
                    "iterations": state.get("iterations", 0) + 1,
                    "retry": True,
                }
            evidence = _edit_evidence(
                state["messages"], params.get("file_path", ""), state.get("file_baselines", {})
            )
            final = f"✓ Task completed. File updated successfully with {name}: {result}\nVerification:\n{evidence}"
            emit("final", {"text": final, "provider": state.get("provider"), "usage": {}})
            return {
                **state,
                "messages": messages,
                "pending_tool": None,
                "final_answer": final,
                "done": True,
            }
        if result.startswith("Error:") and name == "execute_command" and _is_edit_request(state["messages"]):
            return _tool_loop_state(
                state, messages, state.get("provider"), state.get("tool_counts", {}),
                "The shell edit was rejected. Use write_file or patch_file; do not retry execute_command.",
            )
        if name == "execute_command" and _is_edit_request(state["messages"]):
            command = str(params.get("command", "")).lower()
            if any(token in command for token in ("npm", "npx", "mkdir", "create-react-app")):
                return {
                    **state,
                    "messages": messages + [{
                        "role": "user",
                        "content": (
                            "The setup command succeeded. Continue the coding task now: do not run another "
                            "setup command and do not answer with prose. Use write_file immediately to create "
                            "the requested website files in the user's exact folder, at minimum index.html, "
                            "style.css, and script.js. Put complete working source in each file, then use "
                            "execute_command only for a final verification."
                        ),
                    }],
                    "pending_tool": None,
                    "iterations": state["iterations"] + 1,
                    "retry": True,
                }
        return {
            **state,
            "messages": messages,
            "pending_tool": None,
            "iterations": state["iterations"] + 1,
        }

    def route_after_think(state: AgentState) -> str:
        if state.get("done"):
            return END
        if state.get("pending_tool"):
            return "act"
        if state.get("retry") and state.get("iterations", 0) < MAX_ITERATIONS:
            return "think"
        return END

    def route_after_act(state: AgentState) -> str:
        if state["iterations"] >= MAX_ITERATIONS:
            emit("error", {"text": "Reached maximum reasoning attempts."})
            return END
        return "think"

    builder = StateGraph(AgentState)
    builder.add_node("think", think)
    builder.add_node("act", act)
    builder.add_edge(START, "think")
    builder.add_conditional_edges("think", route_after_think, {"act": "act", "think": "think", END: END})
    builder.add_conditional_edges("act", route_after_act, {"think": "think", END: END})

    return CompiledAgent(graph=builder.compile(), executor=executor, cancel_event=cancel_event)


def _split_thought(ai_response: str) -> Optional[str]:
    if "THOUGHT:" not in ai_response:
        return None
    after = ai_response.split("THOUGHT:", 1)[1]
    for marker in ("CALL_TOOL:", "FINAL_ANSWER:"):
        if marker in after:
            after = after.split(marker, 1)[0]
    return after.strip() or None


def _is_edit_request(messages: list[dict]) -> bool:
    """Detect whether the original user request requires a file mutation."""
    original = _original_user_request(messages)
    return bool(re.search(
        r"\b(create|build|design|edit|modify|change|update|improve|fix|rewrite|implement|ubah|perbaiki|buatkan|buat)\b",
        original,
        re.IGNORECASE,
    )) and bool(re.search(r"[A-Za-z]:\\|/|\.html\b|\.css\b|\.js\b|\.tsx?\b", original, re.IGNORECASE))


def _extract_target_path(messages: list[dict]) -> Optional[str]:
    original = _original_user_request(messages)
    match = re.search(r"([A-Za-z]:\\[^\s`\"']+\.(?:html?|css|jsx?|tsx?))", original, re.IGNORECASE)
    return match.group(1).rstrip(".,)") if match else None


def _original_user_request(messages: list[dict]) -> str:
    """Return the user's request, excluding synthetic tool-loop messages."""
    for message in messages:
        if message.get("role") != "user":
            continue
        content = str(message.get("content", ""))
        if content.startswith("Tool Result:") or content.startswith("[USER INSTRUCTION]"):
            continue
        return content
    return ""


def _extract_source_content(text: str) -> Optional[str]:
    fenced = re.search(r"```(?:html?|css|javascript|js|jsx|typescript|ts)?\s*\n?(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()
        return content if len(content) > 80 else None
    if re.search(r"<!doctype html|<html\b", text, re.IGNORECASE):
        start = re.search(r"<!doctype html|<html\b", text, re.IGNORECASE)
        content = text[start.start():].strip() if start else ""
        return content if len(content) > 80 else None
    return None


def _is_file_write_tool_call(tool_call: dict) -> bool:
    params = tool_call.get("parameters", {})
    command = params.get("command", "") if isinstance(params, dict) else ""
    lowered = command.lower() if isinstance(command, str) else ""
    return any(token in lowered for token in ("set-content", "out-file", "add-content", "here-string", ">>", " > "))


def _tool_fingerprint(tool_call: dict) -> str:
    payload = json.dumps(tool_call, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cancelled_state(state: AgentState, emit: Emit) -> AgentState:
    final = "Cancelled by user. No further provider or tool calls will be started."
    emit("error", {"text": final})
    emit("final", {"text": final, "provider": state.get("provider"), "usage": {}})
    return {**state, "final_answer": final, "done": True, "retry": False, "cancelled": True}


def _missing_requested_files(messages: list[dict], current_path: str) -> list[str]:
    """Find explicitly named sibling source files that the request still lacks."""
    if not current_path or not _is_edit_request(messages):
        return []
    original = _original_user_request(messages)
    names = re.findall(
        r"(?<![\w.-])([\w.-]+\.(?:html?|css|jsx?|tsx?))(?![\w.-])",
        original,
        re.IGNORECASE,
    )
    requested: list[str] = []
    directory = os.path.dirname(current_path)
    for name in names:
        candidate = name if os.path.isabs(name) else os.path.join(directory, name)
        if candidate not in requested and not os.path.isfile(candidate):
            requested.append(candidate)
    current_absolute = os.path.abspath(current_path)
    return [path for path in requested if os.path.abspath(path) != current_absolute]


def _edit_evidence(messages: list[dict], current_path: str, baselines: dict[str, str] | None = None) -> str:
    paths = _requested_source_files(messages)
    if current_path and current_path not in paths:
        paths.append(current_path)
    lines = []
    for path in paths:
        try:
            stat = os.stat(path)
            checks = []
            if path.lower().endswith(('.html', '.htm')):
                with open(path, encoding="utf-8") as source_file:
                    content = source_file.read().lower()
                checks.append("html" if "<html" in content else "missing <html>")
                for asset in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', content):
                    if not re.match(r"(?:https?:|data:|#|/)", asset):
                        asset_path = os.path.join(os.path.dirname(path), asset)
                        checks.append(f"asset ok: {asset}" if os.path.isfile(asset_path) else f"asset missing: {asset}")
            elif path.lower().endswith(('.css', '.js', '.jsx', '.ts', '.tsx')):
                checks.append("non-empty" if stat.st_size else "empty")
            checks.extend(_validate_source(path))
            suffix = f"; {', '.join(checks)}" if checks else ""
            before_hash = baselines.get(path, "MISSING") if baselines else "MISSING"
            after_hash = _file_hash(path)
            changed = "new" if before_hash in (None, "MISSING") else (
                "changed" if after_hash != before_hash else "unchanged"
            )
            lines.append(f"- {path}: exists, {changed}, {stat.st_size} bytes, before={before_hash[:12]}, after={after_hash[:12]}{suffix}")
        except OSError:
            lines.append(f"- {path}: MISSING")
    return "\n".join(lines) or "- target file exists"


def _requested_source_files(messages: list[dict]) -> list[str]:
    original = _original_user_request(messages)
    names = re.findall(
        r"(?<![\w.-])([A-Za-z]:[\\/][^\s`\"']+\.(?:html?|css|jsx?|tsx?)|[\w.-]+\.(?:html?|css|jsx?|tsx?))(?![\w.-])",
        original,
        re.IGNORECASE,
    )
    paths = []
    base = os.path.dirname(_extract_target_path(messages) or "")
    for name in names:
        path = name if os.path.isabs(name) else os.path.join(base, name)
        if path not in paths:
            paths.append(path)
    return paths


def _file_hash(path: str) -> str:
    try:
        with open(path, "rb") as source_file:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source_file.read(65536), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError:
        return "MISSING"


def _file_manifest(messages: list[dict]) -> dict[str, str]:
    return {path: _file_hash(path) for path in _requested_source_files(messages)}


def _validate_source(path: str) -> list[str]:
    """Run lightweight local syntax/structure checks without external telemetry."""
    suffix = os.path.splitext(path)[1].lower()
    try:
        with open(path, encoding="utf-8") as source_file:
            content = source_file.read()
    except OSError as exc:
        return [f"validation error: {exc}"]
    if suffix == ".py":
        try:
            compile(content, path, "exec")
            return ["python syntax ok"]
        except SyntaxError as exc:
            return [f"python syntax error: line {exc.lineno}: {exc.msg}"]
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        node = shutil.which("node")
        if not node:
            return ["javascript syntax skipped: node unavailable"]
        result = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=10)
        return ["javascript syntax ok"] if result.returncode == 0 else [
            f"javascript syntax error: {(result.stderr or result.stdout).strip()[:240]}"
        ]
    if suffix == ".css":
        return ["css braces ok"] if content.count("{") == content.count("}") else ["css brace mismatch"]
    return []


def _incomplete_requested_files(messages: list[dict], baselines: dict[str, str], current_path: str) -> list[str]:
    current_absolute = os.path.abspath(current_path) if current_path else ""
    incomplete = []
    for path in _requested_source_files(messages):
        current_hash = _file_hash(path)
        if current_hash == "MISSING" or current_hash == baselines.get(path):
            if os.path.abspath(path) == current_absolute and current_hash != baselines.get(path):
                continue
            incomplete.append(path)
    if current_path and current_absolute not in {os.path.abspath(path) for path in _requested_source_files(messages)}:
        if _file_hash(current_path) == baselines.get(current_path):
            incomplete.append(current_path)
    return incomplete


def _tool_loop_state(state: AgentState, messages: list[dict], provider: Optional[str],
                     tool_counts: dict[str, int], instruction: str) -> AgentState:
    """Feed one corrective instruction back to the model, then stop repeated loops."""
    invalid_count = tool_counts.get("__invalid__", 0) + 1
    tool_counts["__invalid__"] = invalid_count
    if invalid_count >= 2:
        final = "Stopped after repeated invalid tool calls. The file was not changed by the rejected commands."
        return {**state, "messages": messages, "provider": provider,
                "tool_counts": tool_counts, "final_answer": final, "done": True, "retry": False}
    return {**state, "messages": messages + [{"role": "user", "content": instruction}],
            "provider": provider, "tool_counts": tool_counts,
            "iterations": state.get("iterations", 0) + 1, "retry": True}


def _format_code_response(text: str) -> str:
    """Make provider-produced source readable when it reaches the final panel."""
    if "```" in text or len(text) < 120:
        return text
    stripped = text.lstrip()
    language = ""
    if re.search(r"<!doctype html|<html\b|<body\b", stripped, re.IGNORECASE):
        language = "html"
    elif re.search(r"(^|\n)\s*(body|:root|\.[\w-]+|#[\w-]+)\s*\{", stripped):
        language = "css"
    elif re.search(r"(^|\n)\s*(const|let|var|function|import)\b", stripped):
        language = "javascript"
    if not language:
        return text
    return f"```{language}\n{stripped}\n```"


def _normalize_tool_call(tool_call: dict) -> dict:
    """Correct common model mistakes before dispatching a tool call."""
    if tool_call.get("name") != "execute_command":
        return tool_call
    params = tool_call.get("parameters")
    if not isinstance(params, dict):
        return tool_call
    command = params.get("command", "")
    if not isinstance(command, str):
        return tool_call
    match = re.match(r'^\s*(?:type|cat|Get-Content)\s+["\'](.+)["\']\s*$', command, re.IGNORECASE)
    if not match:
        return tool_call
    return {"name": "view_file", "parameters": {"file_path": match.group(1)}}


def _extract_view_file_call(text: str) -> Optional[dict]:
    """Recover Flaz's common textual view_file format as a final fallback."""
    if not _has_tool_call(text):
        return None
    path_match = re.search(
        r'["\']file_path["\']\s*:\s*["\']((?:[A-Za-z]:)?[^"\']+)["\']',
        text,
        re.IGNORECASE,
    )
    if not path_match:
        return None
    return {
        "name": "view_file",
        "parameters": {"file_path": path_match.group(1).replace("\\\\", "\\")},
    }
