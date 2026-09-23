"""Vector RAG for codebase context — semantic search over workspace files.

Uses ChromaDB + built-in embedding function (all-MiniLM-L6-v2 via ONNX).
Indexes project files in a background thread and provides ``ask_codebase``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from homelab_ai.config import BASE_DIR, logger

_IMPORTS: dict = {}

def _lazy(mod: str):
    if mod not in _IMPORTS:
        try:
            _IMPORTS[mod] = __import__(mod)
        except ImportError:
            return None
    return _IMPORTS[mod]


CHUNK_SIZE = 512          # characters per overlapping chunk
CHUNK_OVERLAP = 64
INDEX_DIR = BASE_DIR / ".rag_index"
INCLUDE_EXTS = {".py", ".ts", ".js", ".tsx", ".jsx", ".md", ".txt", ".yaml", ".yml",
                ".json", ".toml", ".cfg", ".ini", ".conf", ".sh", ".bash", ".zsh",
                ".sql", ".html", ".css", ".scss", ".rs", ".go", ".java", ".kt", ".swift"}
EXCLUDE_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".rag_index",
                ".opencode", "history", ".mypy_cache", ".pytest_cache"}


class RAGEngine:
    """Semantic search over the codebase.

    Usage::

        rag = RAGEngine()
        rag.index_workspace()
        results = rag.query("how does login work?")
    """

    def __init__(self, workspace: str = ""):
        self.workspace = workspace or str(BASE_DIR)
        self._collection = None
        self._client = None
        self._ready = False
        self._indexing = False

    # ---- public API -------------------------------------------------------

    def ensure_indexed(self, force: bool = False) -> str:
        """Index (or re-index) the workspace. Safe to call repeatedly."""
        if self._ready and not force:
            return f"RAG already indexed ({self._count_docs()} docs)."

        chro = _lazy("chromadb")
        if not chro:
            return "Error: chromadb not installed."

        self._indexing = True
        try:
            INDEX_DIR.mkdir(parents=True, exist_ok=True)
            self._client = chro.PersistentClient(path=str(INDEX_DIR))
            collection_name = "codebase"
            try:
                self._client.delete_collection(collection_name)
            except Exception:
                pass
            self._collection = self._client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            count = self._index_files()
            self._ready = True
            return f"Indexed {count} chunks from workspace."
        except Exception as exc:
            logger.error("RAG indexing failed: %s", exc)
            return f"RAG indexing error: {exc}"
        finally:
            self._indexing = False

    def query(self, question: str, top_k: int = 5) -> str:
        """Search indexed codebase for relevant context."""
        if not self._ready:
            return "RAG not indexed yet. Call ensure_indexed() first."
        try:
            results = self._collection.query(
                query_texts=[question],
                n_results=min(top_k, 20),
            )
            if not results["documents"] or not results["documents"][0]:
                return "No relevant results found."
            lines = []
            for i, (doc, meta, dist) in enumerate(
                zip(results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0])
            ):
                path = meta.get("path", "?")
                lines.append(f"[{i+1}] {path} (score={1-dist:.3f})")
                lines.append(f"    {doc[:200].strip()}")
            return "--- RAG Results ---\n" + "\n".join(lines)
        except Exception as exc:
            return f"RAG query error: {exc}"

    def status(self) -> str:
        """Return indexing status."""
        if self._indexing:
            return "RAG: indexing in progress…"
        if not self._ready:
            return "RAG: not indexed."
        return f"RAG: ready ({self._count_docs()} chunks)."

    # ---- internal ---------------------------------------------------------

    def _index_files(self) -> int:
        total = 0
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext not in INCLUDE_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except Exception:
                    continue
                chunks = self._chunk_text(text)
                rel = os.path.relpath(fpath, self.workspace)
                ids = [f"{rel}#{i}" for i in range(len(chunks))]
                metas = [{"path": rel} for _ in chunks]
                self._collection.add(documents=chunks, ids=ids, metadatas=metas)
                total += len(chunks)
        return total

    def _chunk_text(self, text: str) -> list[str]:
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= CHUNK_SIZE:
            return [text] if text else []
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            chunks.append(text[start:end])
            start += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

    def _count_docs(self) -> int:
        try:
            return self._collection.count()
        except Exception:
            return 0


# ---- Singleton ---------------------------------------------------------

_engine: Optional[RAGEngine] = None


def get_rag() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


def background_index():
    """Call from a thread to index without blocking the UI."""
    rag = get_rag()
    rag.ensure_indexed()
