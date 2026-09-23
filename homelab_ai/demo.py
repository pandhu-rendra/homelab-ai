"""Offline demo brain.

When no API keys are configured, this scripted responder lets the full TUI +
LangGraph + tool pipeline be exercised end-to-end (so the UI is testable
without network access). It speaks the same ReAct contract as ``call_llm``.
"""
from __future__ import annotations


def _detect_lang(text: str) -> str:
    """Simple language guess: id/en."""
    id_words = {"halo", "hai", "apa", "bagaimana", "siapa", "kenapa",
                "kapan", "dimana", "yang", "dengan", "tidak", "akan",
                "saya", "kamu", "aku", "bisa", "tolong", "coba",
                "gimana", "dong", "sih", "deh", "kok", "nih",
                "padahal", "udah", "gue", "lu", "nganu", "anjing",
                "anjir", "wow", "astaga", "waduh", "aduh", "yah",
                "iya", "ya", "ok", "oke", "ga", "nggak", "engga",
                "pakai", "pake", "pakek", "aja", "doang", "mah"}
    words = set(text.lower().split())
    match = len(words & id_words)
    return "id" if match >= 1 else "en"


_GREETINGS_ID = [
    "Halo! Ada yang bisa saya bantu?",
    "Hai! Silakan tanya apa saja.",
    "Ya, ada yang bisa saya bantu?",
]
_GREETINGS_EN = [
    "Hello! How can I help you?",
    "Hi! Feel free to ask me anything.",
    "Yes, how can I assist you?",
]


def _echo_response(text: str) -> str:
    lang = _detect_lang(text)
    if lang == "id":
        return (
            f"Maaf, saya sedang dalam mode offline (demo) sehingga tidak bisa "
            f"memproses pertanyaan secara langsung. Silakan coba gunakan perintah "
            f"seperti `system stats` atau `list files` untuk melihat fitur tool, "
            f"atau atur API key di .env agar terhubung ke LLM sungguhan.\n\n"
            f"Pertanyaan Anda: _{text}_"
        )
    return (
        f"I'm currently in offline demo mode, so I can't process your question "
        f"directly. Try commands like `system stats` or `list files` to see the "
        f"tool system in action, or set up an API key in .env to connect to a "
        f"real LLM.\n\n"
        f"Your query: _{text}_"
    )


def demo_llm(messages: list[dict]) -> tuple[str, str, dict]:
    last = messages[-1] if messages else {"role": "user", "content": ""}
    content = last.get("content", "")

    if last.get("role") == "user" and content.startswith("Tool Result:"):
        result = content.replace("Tool Result:", "", 1).strip()
        return (
            "THOUGHT: The tool returned data; I will summarise it for the user.\n"
            "FINAL_ANSWER: Here is the result from the tool:\n\n"
            f"```\n{result[:1200]}\n```\n\n"
            "_(Demo mode — set DEEPSEEK_API_KEY or GEMINI_API_KEY for real answers.)_",
            "Demo",
            {"prompt": 0, "completion": len(content) // 4, "total": len(content) // 4},
        )

    lowered = content.lower()
    if any(k in lowered for k in ("stat", "cpu", "ram", "system", "spec")):
        return (
            "THOUGHT: The user asked about the machine, so I will read live system stats.\n"
            'CALL_TOOL: {"name": "get_system_stats", "parameters": {}}',
            "Demo",
            {"prompt": len(content) // 4, "completion": 0, "total": len(content) // 4},
        )
    if "ls" in lowered.split() or "file" in lowered or "list" in lowered:
        return (
            "THOUGHT: The user wants to inspect the directory contents.\n"
            'CALL_TOOL: {"name": "list_dir", "parameters": {"directory_path": "."}}',
            "Demo",
            {"prompt": len(content) // 4, "completion": 0, "total": len(content) // 4},
        )

    reply = _echo_response(content)
    return (
        "THOUGHT: No tool is required; respond directly.\n"
        f"FINAL_ANSWER: {reply}",
        "Demo",
        {"prompt": len(content) // 4, "completion": 25, "total": len(content) // 4 + 25},
    )
