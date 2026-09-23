"""AI tools powered by 100+ libraries for autonomous code & system engineering."""

from __future__ import annotations

import asyncio
import csv
import difflib
import io
import json
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

import appdirs
import httpx
import jsonref
import pathspec
import psutil
import requests
import tiktoken
import yaml
from bs4 import BeautifulSoup
from ddgs import DDGS
from pypdf import PdfReader
from youtube_transcript_api import YouTubeTranscriptApi

try:
    _tree_sitter = __import__("tree_sitter_languages", fromlist=["get_language", "get_parser"])
    get_language = _tree_sitter.get_language
    get_parser = _tree_sitter.get_parser
    TREE_SITTER_AVAILABLE = True
except (ImportError, AttributeError):
    TREE_SITTER_AVAILABLE = False
    get_language = get_parser = None

# -- Lazy-loaded optional imports --
_IMPORTS: dict[str, Any] = {}

def _lazy(mod: str, name: str = ""):
    if mod not in _IMPORTS:
        try:
            _IMPORTS[mod] = __import__(mod, fromlist=[name] if name else [])
        except ImportError:
            return None
    return _IMPORTS[mod] if not name else getattr(_IMPORTS[mod], name)

from .config import get_deepseek_client, get_gemini_client, logger

StatusCallback = Callable[[str], None]


# --------------------------------------------------------------------------- #
# Web / document tools
# --------------------------------------------------------------------------- #

def scrape_website(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return f"Error fetching website: status {resp.status_code}"
        soup = BeautifulSoup(resp.content, "html.parser")
        for el in soup(["script", "style"]):
            el.extract()
        return " ".join(soup.get_text().split())[:4000]
    except Exception as e:
        return f"Error scraping website: {e}"


def read_pdf(file_path: str) -> str:
    try:
        text = "".join((p.extract_text() or "") + "\n" for p in PdfReader(file_path).pages)
        return text[:4000]
    except Exception as e:
        return f"Error reading PDF: {e}"


def web_search(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No results found."
            buf = ""
            for i, r in enumerate(results):
                buf += f"Result {i+1}:\nTitle: {r.get('title')}\nLink: {r.get('href')}\nDescription: {r.get('body')}\n\n"
            return f"--- Web Search for '{query}' ---\n{buf}--------------------"
    except Exception as e:
        return f"Error performing web search: {e}"


def get_weather(location: str) -> str:
    try:
        resp = requests.get(f"https://wttr.in/{location}?format=3", timeout=5)
        return resp.text.strip() if resp.status_code == 200 else f"Error: {resp.status_code}"
    except Exception as e:
        return f"Error fetching weather: {e}"


def summarize_youtube(url: str) -> str:
    try:
        vid = url.split("v=")[1].split("&")[0] if "v=" in url else url.split("youtu.be/")[1].split("?")[0]
        try:
            transcript = YouTubeTranscriptApi.get_transcript(vid, languages=["id", "en"])
        except Exception:
            return "Error: Transcript unavailable."
        text = " ".join(t["text"] for t in transcript)[:6000]
        prompt = f"Summarise this YouTube transcript:\n\n{text}"
        resp = get_gemini_client().models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return f"--- YouTube Summary ({url}) ---\n{resp.text}\n--------------------"
    except Exception as e:
        return f"Error summarizing YouTube: {e}"


def read_local_video(file_path: str, on_status: Optional[StatusCallback] = None) -> str:
    def status(msg: str) -> None:
        if on_status:
            on_status(msg)
    try:
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' not found."
        client = get_gemini_client()
        status("Uploading video…")
        vf = client.files.upload(file=file_path)
        status("Processing…")
        while vf.state.name == "PROCESSING":
            time.sleep(3)
            vf = client.files.get(name=vf.name)
        if vf.state.name == "FAILED":
            return "Error: Gemini failed to process video."
        status("Analysing…")
        prompt = "Provide a detailed forensic analysis of this video."
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=[vf, prompt])
        try:
            client.files.delete(name=vf.name)
        except Exception:
            pass
        return f"--- VIDEO ANALYSIS ---\n{resp.text}"
    except Exception as e:
        return f"Error processing video: {e}"


# --------------------------------------------------------------------------- #
# Enhanced tools using new libraries (tree-sitter, pathspec, tiktoken, etc.)
# --------------------------------------------------------------------------- #

def analyze_code(file_path: str, language: Optional[str] = None) -> str:
    if not TREE_SITTER_AVAILABLE:
        return "Error: tree-sitter-languages not available."
    try:
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' does not exist."
        if language is None:
            ext = Path(file_path).suffix.lower()
            lang_map = {".py":"python", ".js":"javascript", ".ts":"typescript", ".rs":"rust",
                        ".go":"go", ".java":"java", ".cpp":"cpp", ".c":"c"}
            language = lang_map.get(ext)
        if not language:
            return f"Error: Could not detect language."
        parser = get_parser(language)
        with open(file_path) as f:
            source = f.read()
        tree = parser.parse(bytes(source, "utf8"))
        results = []
        def walk(node, d=0):
            if node.type in ("function_definition","function_declaration","method_definition",
                             "class_definition","class_declaration","import_statement","import_declaration"):
                line = source[node.start_byte:node.end_byte].split("\n")[0][:120]
                results.append(f"{'  '*d}{node.type}: {line}")
            for c in node.children:
                walk(c, d+1)
        walk(tree.root_node)
        header = f"--- Code Analysis: {file_path} ({language}) ---\n"
        return header + "\n".join(results[:100]) if results else "No structures found."
    except Exception as e:
        return f"Error analyzing code: {e}"


_IGNORE_DIRS = {".venv", "venv", ".git", "__pycache__", "node_modules", ".mypy_cache",
                ".pytest_cache", "dist", "build", ".eggs", ".ruff_cache"}

def _is_ignored(path: Path) -> bool:
    return any(p in _IGNORE_DIRS for p in path.parts)


def search_files(pattern: str, root_dir: str = ".") -> str:
    try:
        root = Path(root_dir).resolve()
        if not root.exists():
            return f"Error: Directory '{root_dir}' does not exist."
        spec = pathspec.PathSpec.from_lines("gitwildmatch", [pattern])
        matches = []
        for fp in root.rglob("*"):
            if fp.is_file() and not _is_ignored(fp.relative_to(root)):
                rel = str(fp.relative_to(root))
                if spec.match_file(rel):
                    matches.append(rel)
        if not matches:
            return f"No files matched '{pattern}'."
        return f"--- Files matching '{pattern}' ---\n" + "\n".join(matches[:200])
    except Exception as e:
        return f"Error searching files: {e}"


def count_tokens(text: str, model: str = "cl100k_base") -> str:
    try:
        enc = tiktoken.get_encoding(model)
        tokens = enc.encode(text)
        return (f"--- Token Count ({model}) ---\nCharacters: {len(text)}\n"
                f"Tokens: {len(tokens)}\nCost (GPT-4o): ${len(tokens)/1_000_000*2.50:.6f}")
    except Exception as e:
        return f"Error counting tokens: {e}"


def resolve_jsonref(file_path: str) -> str:
    try:
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' does not exist."
        with open(file_path) as f:
            data = json.load(f)
        resolved = jsonref.replace_refs(data)
        def conv(obj):
            if isinstance(obj, dict):
                return {k: conv(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [conv(v) for v in obj]
            if isinstance(obj, jsonref.JsonRef):
                return str(obj)
            return obj
        return f"--- Resolved JSON ---\n{json.dumps(conv(resolved), indent=2, ensure_ascii=False)[:8000]}"
    except Exception as e:
        return f"Error resolving JSON refs: {e}"


async def web_fetch_async(url: str, method: str = "GET", headers: Optional[dict] = None) -> str:
    try:
        hdrs = {"User-Agent": "Mozilla/5.0"}
        if headers:
            hdrs.update(headers)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            resp = await c.request(method, url, headers=hdrs)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                data = resp.json()
                return f"--- JSON from {url} ---\n{json.dumps(data, indent=2, ensure_ascii=False)[:8000]}"
            return f"--- Response from {url} ---\n{resp.text[:8000]}"
    except Exception as e:
        return f"Error fetching {url}: {e}"


def get_app_paths(app_name: str = "homelab-ai") -> str:
    try:
        return (f"--- App Directories ---\nUser Data: {appdirs.user_data_dir(app_name)}\n"
                f"User Config: {appdirs.user_config_dir(app_name)}\n"
                f"User Cache: {appdirs.user_cache_dir(app_name)}")
    except Exception as e:
        return f"Error: {e}"


# --------------------------------------------------------------------------- #
# NEW: Deep Python code analysis with jedi / rope / radon / black / isort / pylint
# --------------------------------------------------------------------------- #

def analyze_python(file_path: str) -> str:
    """Deep Python analysis using jedi: definitions, signatures, imports, usages."""
    try:
        jedi = _lazy("jedi")
        if not jedi:
            return "Error: jedi not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        with open(file_path) as f:
            source = f.read()
        script = jedi.Script(source, path=file_path)
        names = script.get_names(all_scopes=True, definitions=True)
        lines = []
        for n in names:
            desc = f"{n.type}: {n.name}"
            if hasattr(n, "full_name") and n.full_name:
                desc += f" ({n.full_name})"
            if n.line:
                desc += f" line {n.line}"
            lines.append(desc)
            if n.type in ("function", "class"):
                sigs = script.get_signatures(line=n.line, column=n.column or 0)
                for s in sigs:
                    lines.append(f"  signature: {s.description}")
        if not lines:
            lines.append("(no definitions found)")
        return f"--- Python Analysis: {file_path} ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error analyzing Python: {e}"


def calculate_complexity(file_path: str) -> str:
    """Calculate cyclomatic complexity using radon."""
    try:
        radon = _lazy("radon.complexity")
        if not radon:
            return "Error: radon not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        with open(file_path) as f:
            source = f.read()
        blocks = radon.cc_visit(source)
        if not blocks:
            return "No functions/classes found."
        lines = [
            f"  {b.name}: complexity={b.complexity}, rank={b.rank}, "
            f"line={b.lineno}, end={b.endline}"
            for b in sorted(blocks, key=lambda b: b.complexity, reverse=True)
        ]
        avg = sum(b.complexity for b in blocks) / len(blocks)
        return (f"--- Complexity: {file_path} ---\nAverage complexity: {avg:.1f}\n" +
                "\n".join(lines))
    except Exception as e:
        return f"Error calculating complexity: {e}"


def format_code(file_path: str) -> str:
    """Auto-format Python code with black."""
    try:
        black = _lazy("black")
        if not black:
            return "Error: black not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        mode = black.Mode()
        with open(file_path) as f:
            source = f.read()
        formatted = black.format_str(source, mode=mode)
        if formatted == source:
            return f"'{file_path}' is already well-formatted."
        with open(file_path, "w") as f:
            f.write(formatted)
        return f"Successfully formatted '{file_path}' with black."
    except Exception as e:
        return f"Error formatting code: {e}"


def sort_imports(file_path: str) -> str:
    """Sort imports using isort."""
    try:
        isort_lib = _lazy("isort")
        if not isort_lib:
            return "Error: isort not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        isort_lib.file(file_path)
        return f"Successfully sorted imports in '{file_path}'."
    except Exception as e:
        return f"Error sorting imports: {e}"


def lint_code(file_path: str) -> str:
    """Lint Python code with pylint (concise output)."""
    try:
        from pylint import lint as pylint_lint
        from pylint.reporters.text import TextReporter
    except ImportError:
        return "Error: pylint not installed."
    if not os.path.exists(file_path):
        return f"Error: '{file_path}' not found."
    try:
        out = io.StringIO()
        reporter = TextReporter(out)
        pylint_lint.Run([file_path, "--disable=all", "--enable=E,F,W,C,R",
                         "--output-format=text"], reporter=reporter, do_exit=False)
        result = out.getvalue()
        return f"--- Lint: {file_path} ---\n{result[:4000]}"
    except SystemExit:
        pass
    except Exception as e:
        return f"Error linting: {e}"
    return "Lint completed."


# --------------------------------------------------------------------------- #
# NEW: Git / VCS tools (GitPython, diff-match-patch, jsondiff, dictdiffer)
# --------------------------------------------------------------------------- #

def git_status(repo_path: str = ".") -> str:
    """Git status using GitPython."""
    try:
        git = _lazy("git")
        if not git:
            return "Error: GitPython not installed."
        repo = git.Repo(repo_path, search_parent_directories=True)
        if repo.bare:
            return "Error: bare repository."
        lines = [f"Branch: {repo.active_branch.name}"]
        if repo.is_dirty():
            lines.append("Status: DIRTY (uncommitted changes)")
        else:
            lines.append("Status: clean")
        for item in repo.index.diff(None):
            lines.append(f"  modified: {item.a_path}")
        for item in repo.index.diff("HEAD"):
            lines.append(f"  staged: {item.a_path}")
        for item in repo.untracked_files:
            lines.append(f"  untracked: {item}")
        return "--- Git Status ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def git_log(count: int = 10, repo_path: str = ".") -> str:
    """Recent commits using GitPython."""
    try:
        git = _lazy("git")
        if not git:
            return "Error: GitPython not installed."
        repo = git.Repo(repo_path, search_parent_directories=True)
        commits = list(repo.iter_commits(max_count=min(count, 50)))
        lines = []
        for c in commits:
            msg = c.message.split("\n")[0][:80]
            lines.append(f"{c.hexsha[:8]} | {c.author.name} | {msg}")
        return f"--- Git Log (last {len(commits)}) ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def git_diff(file_path: Optional[str] = None, repo_path: str = ".") -> str:
    """Show diff using GitPython."""
    try:
        git = _lazy("git")
        if not git:
            return "Error: GitPython not installed."
        repo = git.Repo(repo_path, search_parent_directories=True)
        if file_path:
            diffs = repo.index.diff(None, paths=file_path)
            if not diffs:
                diffs = repo.index.diff("HEAD", paths=file_path)
        else:
            diffs = repo.index.diff(None)
        lines = []
        for d in diffs:
            lines.append(f"--- a/{d.a_path}  +++ b/{d.b_path}")
            if d.diff:
                text = d.diff.decode("utf-8", errors="replace")
                lines.append(text[:2000])
        return "--- Git Diff ---\n" + "\n".join(lines) if lines else "No changes."
    except Exception as e:
        return f"Error: {e}"


# --------------------------------------------------------------------------- #
# NEW: Document / Spreadsheet tools (pandas, openpyxl, pillow, tabulate, pdfplumber)
# --------------------------------------------------------------------------- #

def read_spreadsheet(file_path: str) -> str:
    """Read CSV / Excel with pandas and tabulate."""
    try:
        pd = _lazy("pandas")
        if not pd:
            return "Error: pandas not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        ext = Path(file_path).suffix.lower()
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, engine="openpyxl")
        elif ext == ".csv":
            df = pd.read_csv(file_path)
        elif ext == ".tsv":
            df = pd.read_csv(file_path, sep="\t")
        elif ext == ".json":
            df = pd.read_json(file_path)
        else:
            return f"Unsupported format: {ext}"
        tabulate_lib = _lazy("tabulate")
        if tabulate_lib:
            table = tabulate_lib.tabulate(df.head(50), headers="keys", tablefmt="rounded_grid")
        else:
            table = df.head(50).to_string()
        return f"--- {file_path} ({len(df)} rows, {len(df.columns)} cols) ---\n{table}"
    except Exception as e:
        return f"Error reading spreadsheet: {e}"


def read_excel_sheets(file_path: str) -> str:
    """List sheet names from an Excel workbook."""
    try:
        openpyxl_lib = _lazy("openpyxl")
        if not openpyxl_lib:
            return "Error: openpyxl not installed."
        wb = openpyxl_lib.load_workbook(file_path, read_only=True)
        sheets = wb.sheetnames
        info = [f"Sheet: {s}" for s in sheets]
        return f"--- Excel Sheets: {file_path} ---\n" + "\n".join(info)
    except Exception as e:
        return f"Error reading Excel sheets: {e}"


def analyze_image(file_path: str) -> str:
    """Get image metadata using Pillow."""
    try:
        PIL = _lazy("PIL")
        Image = _lazy("PIL", "Image") or _lazy("PIL.Image")
        if not Image:
            return "Error: Pillow not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        img = Image.open(file_path)
        fmt = img.format or "unknown"
        mode = img.mode
        w, h = img.size
        return (f"--- Image: {file_path} ---\nFormat: {fmt}\nSize: {w}x{h}\n"
                f"Mode: {mode}\nFile: {os.path.getsize(file_path)} bytes")
    except Exception as e:
        return f"Error analyzing image: {e}"


def read_pdf_detailed(file_path: str) -> str:
    """Extract PDF text with pdfplumber (better tables)."""
    try:
        pdfplumber_lib = _lazy("pdfplumber")
        if not pdfplumber_lib:
            return "Error: pdfplumber not installed."
        text_parts = []
        with pdfplumber_lib.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                text_parts.append(f"--- Page {i+1} ---\n{text[:2000]}")
        return "\n".join(text_parts[:10]) + "\n… (truncated)" if len(text_parts) > 10 else "\n".join(text_parts)
    except Exception as e:
        return f"Error reading PDF: {e}"


# --------------------------------------------------------------------------- #
# NEW: YAML / TOML / config tools (pyyaml)
# --------------------------------------------------------------------------- #

def read_yaml(file_path: str) -> str:
    """Read and parse a YAML file."""
    try:
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        with open(file_path) as f:
            data = yaml.safe_load(f)
        return f"--- YAML: {file_path} ---\n{json.dumps(data, indent=2, ensure_ascii=False)[:8000]}"
    except Exception as e:
        return f"Error reading YAML: {e}"


def parse_markdown(file_path: str) -> str:
    """Convert Markdown to plain text."""
    try:
        markdown_lib = _lazy("markdown")
        if not markdown_lib:
            return "Error: markdown not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        with open(file_path) as f:
            html = markdown_lib.markdown(f.read())
            from bs4 import BeautifulSoup as BS
            return BS(html, "html.parser").get_text()[:4000]
    except Exception as e:
        return f"Error parsing markdown: {e}"


# --------------------------------------------------------------------------- #
# NEW: SSH / Remote execution (paramiko, scp)
# --------------------------------------------------------------------------- #

def ssh_execute(host: str, command: str, username: str, port: int = 22,
                key_path: Optional[str] = None) -> str:
    """Execute a command on a remote host via SSH (paramiko)."""
    try:
        paramiko_lib = _lazy("paramiko")
        if not paramiko_lib:
            return "Error: paramiko not installed."
        ssh = paramiko_lib.SSHClient()
        ssh.set_missing_host_key_policy(paramiko_lib.AutoAddPolicy())
        try:
            if key_path:
                key = paramiko_lib.RSAKey.from_private_key_file(key_path)
                ssh.connect(host, port=port, username=username, pkey=key)
            else:
                ssh.connect(host, port=port, username=username)
            _, stdout, stderr = ssh.exec_command(command, timeout=30)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return f"--- SSH: {host} ---\nSTDOUT:\n{out[:4000]}\nSTDERR:\n{err[:2000]}"
        finally:
            ssh.close()
    except Exception as e:
        return f"Error executing SSH: {e}"


# --------------------------------------------------------------------------- #
# NEW: Docker tools
# --------------------------------------------------------------------------- #

def docker_ps(all_containers: bool = False) -> str:
    """List Docker containers."""
    try:
        docker_lib = _lazy("docker")
        if not docker_lib:
            return "Error: docker not installed."
        client = docker_lib.from_env()
        try:
            containers = client.containers.list(all=all_containers)
        finally:
            close = getattr(client, "close", None)
            if close:
                close()
        if not containers:
            return "No containers."
        lines = []
        for c in containers:
            lines.append(f"{c.short_id} | {c.name} | {c.status} | image={c.image.tags}")
        return f"--- Docker Containers ({len(containers)}) ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing containers: {e}"


def docker_images() -> str:
    """List Docker images."""
    try:
        docker_lib = _lazy("docker")
        if not docker_lib:
            return "Error: docker not installed."
        client = docker_lib.from_env()
        try:
            images = client.images.list()
        finally:
            close = getattr(client, "close", None)
            if close:
                close()
        if not images:
            return "No images."
        lines = []
        for img in images:
            lines.append(f"{img.short_id} | tags={img.tags}")
        return f"--- Docker Images ({len(images)}) ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing images: {e}"


# --------------------------------------------------------------------------- #
# NEW: Async / Resiliency helpers (tenacity, backoff, loguru, tqdm)
# --------------------------------------------------------------------------- #

def retry_with_backoff(task_description: str = "") -> str:
    """Show info about retry/resiliency libraries available."""
    info = []
    if _lazy("tenacity"):
        info.append("tenacity: retry decorator with configurable backoff")
    if _lazy("backoff"):
        info.append("backoff: exponential backoff decorator")
    if _lazy("loguru"):
        info.append("loguru: structured logging")
    if _lazy("tqdm"):
        info.append("tqdm: progress bars")
    return "--- Resiliency Libraries ---\n" + "\n".join(info) if info else "No resiliency libs installed."


# --------------------------------------------------------------------------- #
# NEW: ASCII art / TUI output (art, pyfiglet)
# --------------------------------------------------------------------------- #

def generate_ascii_banner(text: str, font: str = "standard") -> str:
    """Generate ASCII art banner using pyfiglet."""
    try:
        pyfiglet_lib = _lazy("pyfiglet")
        if not pyfiglet_lib:
            # fallback to art
            art_lib = _lazy("art")
            if art_lib:
                return f"--- Banner ---\n{art_lib.text2art(text)}"
            return "Error: pyfiglet or art not installed."
        result = pyfiglet_lib.figlet_format(text, font=font)
        return f"--- Banner ---\n{result}"
    except Exception as e:
        return f"Error generating banner: {e}"


def display_color_text(text: str, color: str = "green") -> str:
    """Return coloured terminal text using crayons."""
    try:
        crayons_lib = _lazy("crayons")
        if not crayons_lib:
            return text
        color_fn = getattr(crayons_lib, color, crayons_lib.green)
        return str(color_fn(text))
    except Exception:
        return text


# --------------------------------------------------------------------------- #
# NEW: Data serialization tools (msgpack, ujson, ijson, dirtyjson)
# --------------------------------------------------------------------------- #

def read_msgpack(file_path: str) -> str:
    """Read a MessagePack file."""
    try:
        msgpack_lib = _lazy("msgpack")
        if not msgpack_lib:
            return "Error: msgpack not installed."
        with open(file_path, "rb") as f:
            data = msgpack_lib.unpack(f)
        return f"--- MsgPack: {file_path} ---\n{json.dumps(data, indent=2, ensure_ascii=False)[:8000]}"
    except Exception as e:
        return f"Error reading msgpack: {e}"


def read_json_fast(file_path: str) -> str:
    """Fast JSON parsing with ujson."""
    try:
        ujson_lib = _lazy("ujson")
        if not ujson_lib:
            return "Error: ujson not installed."
        with open(file_path) as f:
            data = ujson_lib.load(f)
        return f"--- JSON (ujson): {file_path} ---\n{json.dumps(data, indent=2, ensure_ascii=False)[:8000]}"
    except Exception as e:
        return f"Error reading JSON: {e}"


# --------------------------------------------------------------------------- #
# NEW: Security / Encryption tools (cryptography, certifi, keyring)
# --------------------------------------------------------------------------- #

def encrypt_text(plaintext: str) -> str:
    """Generate a Fernet key and encrypt text (demo only)."""
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        f = Fernet(key)
        token = f.encrypt(plaintext.encode())
        return f"Key: {key.decode()}\nEncrypted: {token.decode()}"
    except Exception as e:
        return f"Error encrypting: {e}"


# --------------------------------------------------------------------------- #
# NEW: UI Automation (pyautogui, opencv, pynput, screeninfo, mss)
# --------------------------------------------------------------------------- #

def screen_info() -> str:
    """Get monitor information using screeninfo."""
    try:
        si = _lazy("screeninfo")
        if not si:
            return "Error: screeninfo not installed."
        monitors = si.get_monitors()
        lines = [f"Monitor {i}: {m.name} {m.width}x{m.height}@{m.width_mm}x{m.height_mm}mm"
                 for i, m in enumerate(monitors)]
        return "--- Screens ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def capture_screen() -> str:
    """Capture screenshot using mss and return path."""
    try:
        mss_lib = _lazy("mss")
        if not mss_lib:
            return "Error: mss not installed."
        ts = time.strftime("%Y%m%d_%H%M%S")
        tmp = tempfile.gettempdir()
        path = os.path.join(tmp, f"screenshot_{ts}.png")
        with mss_lib.mss() as sct:
            sct.shot(output=path)
        return f"Screenshot saved to {path} (os.path.getsize={os.path.getsize(path)} bytes)"
    except Exception as e:
        return f"Error capturing screen: {e}"


def mouse_click(x: int, y: int, button: str = "left") -> str:
    """Click at screen coordinates using pyautogui."""
    try:
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        pag.click(x, y, button=button)
        return f"Clicked ({x}, {y}) with {button} button."
    except Exception as e:
        return f"Error clicking: {e}"


def type_text(text: str) -> str:
    """Type text using pyautogui."""
    try:
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        pag.write(text, interval=0.02)
        return f"Typed: {text[:200]}"
    except Exception as e:
        return f"Error typing: {e}"


def locate_on_screen(image_path: str) -> str:
    """Locate an image on screen using OpenCV + pyautogui."""
    try:
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        if not os.path.exists(image_path):
            return f"Error: '{image_path}' not found."
        pos = pag.locateOnScreen(image_path, confidence=0.8)
        if pos:
            return f"Found at: left={pos.left}, top={pos.top}, width={pos.width}, height={pos.height}"
        return "Image not found on screen."
    except Exception as e:
        return f"Error locating image: {e}"


def pynput_click(x: int, y: int, button: str = "left") -> str:
    """Click at coordinates using pynput (works without display)."""
    try:
        from pynput.mouse import Button, Controller
        btn = {"left": Button.left, "right": Button.right, "middle": Button.middle}.get(button, Button.left)
        mouse = Controller()
        mouse.position = (x, y)
        mouse.click(btn)
        return f"pynput clicked ({x}, {y}) with {button}."
    except Exception as e:
        return f"Error with pynput click: {e}"


def pynput_type(text: str) -> str:
    """Type text using pynput keyboard controller."""
    try:
        from pynput.keyboard import Controller as KbdController
        kb = KbdController()
        kb.type(text)
        return f"pynput typed {len(text)} characters."
    except Exception as e:
        return f"Error with pynput type: {e}"


# --------------------------------------------------------------------------- #
# NEW: Web Scraping advanced (cloudscraper, mechanicalsoup, requests-html, playwright, selenium)
# --------------------------------------------------------------------------- #

def cloudscrape(url: str) -> str:
    """Bypass Cloudflare protection using cloudscraper."""
    try:
        cs = _lazy("cloudscraper")
        if not cs:
            return "Error: cloudscraper not installed."
        scraper = cs.create_scraper()
        resp = scraper.get(url, timeout=30)
        soup = BeautifulSoup(resp.content, "html.parser")
        for el in soup(["script", "style"]):
            el.extract()
        return " ".join(soup.get_text().split())[:4000]
    except Exception as e:
        return f"Error cloudscraping: {e}"


def browse_website(url: str) -> str:
    """Navigate and scrape JS-rendered sites using requests-html."""
    try:
        rh = _lazy("requests_html")
        if not rh:
            return "Error: requests-html not installed."
        session = rh.HTMLSession()
        resp = session.get(url)
        resp.html.render(timeout=20, sleep=1)
        return resp.html.text[:4000]
    except Exception as e:
        return f"Error browsing: {e}"


def mechanical_browse(url: str) -> str:
    """Stateful browser navigation using MechanicalSoup."""
    try:
        ms = _lazy("mechanicalsoup")
        if not ms:
            return "Error: mechanicalsoup not installed."
        browser = ms.StatefulBrowser()
        browser.open(url)
        text = browser.page.get_text()[:4000] if browser.page else "No page loaded."
        form_links = browser.page.find_all("a")[:20] if browser.page else []
        links = "\n".join(f"  {a.get('href','')}: {a.text.strip()[:60]}" for a in form_links)
        browser.close()
        return f"--- Browsed: {url} ---\n{text}\nLinks:\n{links}"
    except Exception as e:
        return f"Error browsing: {e}"


def browser_automate(url: str, actions: str = "") -> str:
    """Automate a browser using Playwright."""
    try:
        _lazy("playwright")
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Error: playwright not installed."
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            output = [f"Title: {page.title()}", f"URL: {page.url}"]
            for line in actions.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if parts[0] == "click": page.click(parts[1])
                elif parts[0] == "fill": page.fill(parts[1], " ".join(parts[2:]))
                elif parts[0] == "wait": page.wait_for_timeout(int(parts[1]) * 1000)
                elif parts[0] == "screenshot":
                    page.screenshot(path=os.path.join(tempfile.gettempdir(), "playwright_screenshot.png"))
                    output.append("Screenshot saved.")
                else:
                    output.append(f"Unknown action: {line}")
            output.append(f"Content: {page.content()[:2000]}")
            browser.close()
            return "\n".join(output)
    except Exception as e:
        return f"Error in Playwright: {e}"


def browser_selenium(url: str, actions: str = "") -> str:
    """Control browser via Selenium WebDriver."""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
    except ImportError:
        return "Error: selenium not installed."
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            output = [f"Title: {driver.title}", f"URL: {driver.current_url}"]
            for line in actions.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if parts[0] == "click": driver.find_element(By.CSS_SELECTOR, parts[1]).click()
                elif parts[0] == "fill":
                    el = driver.find_element(By.CSS_SELECTOR, parts[1])
                    el.clear(); el.send_keys(" ".join(parts[2:]))
                elif parts[0] == "wait": driver.implicitly_wait(int(parts[1]))
                elif parts[0] == "screenshot":
                    driver.save_screenshot(os.path.join(tempfile.gettempdir(), "selenium_screenshot.png"))
                    output.append("Screenshot saved.")
                else:
                    output.append(f"Unknown action: {line}")
            output.append(f"Body: {driver.find_element(By.TAG_NAME, 'body').text[:2000]}")
            return "\n".join(output)
        finally:
            driver.quit()
    except Exception as e:
        return f"Error in Selenium: {e}"


# --------------------------------------------------------------------------- #
# NEW: Database tools (sqlalchemy, redis, pymongo, motor, paho-mqtt)
# --------------------------------------------------------------------------- #

def redis_exec(command: str, host: str = "localhost", port: int = 6379, db: int = 0) -> str:
    """Execute a Redis command."""
    try:
        r = _lazy("redis")
        if not r:
            return "Error: redis not installed."
        client = r.Redis(host=host, port=port, db=db, socket_timeout=5)
        parts = command.strip().split()
        if not parts:
            return "Error: empty command."
        method = parts[0].lower()
        args = parts[1:]
        func = getattr(client, method, None)
        if not func:
            return f"Error: unknown Redis command '{method}'."
        result = func(*args)
        return f"--- Redis {host}:{port}/{db} ---\n{command}\nResult: {result}"
    except Exception as e:
        return f"Error executing Redis: {e}"


def mongodb_query(connection_string: str, database: str, collection: str,
                  query: str = "{}", limit: int = 10) -> str:
    """Query MongoDB using pymongo."""
    try:
        pm = _lazy("pymongo")
        if not pm:
            return "Error: pymongo not installed."
        client = pm.MongoClient(connection_string, serverSelectionTimeoutMS=5000)
        db = client[database]
        col = db[collection]
        q = json.loads(query) if isinstance(query, str) else query
        docs = list(col.find(q).limit(min(limit, 50)))
        if not docs:
            return f"No documents found in '{database}.{collection}'."
        for d in docs:
            d["_id"] = str(d["_id"])
        return f"--- MongoDB: {database}.{collection} ({len(docs)} docs) ---\n" + \
               json.dumps(docs, indent=2, ensure_ascii=False)[:8000]
    except Exception as e:
        return f"Error querying MongoDB: {e}"


async def mongodb_async_query(connection_string: str, database: str, collection: str,
                              query: str = "{}", limit: int = 10) -> str:
    """Async MongoDB query using Motor."""
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        return "Error: motor not installed."
    try:
        client = AsyncIOMotorClient(connection_string, serverSelectionTimeoutMS=5000)
        db = client[database]
        col = db[collection]
        q = json.loads(query) if isinstance(query, str) else query
        cursor = col.find(q).limit(min(limit, 50))
        docs = await cursor.to_list(length=limit)
        if not docs:
            return f"No documents found in '{database}.{collection}'."
        for d in docs:
            d["_id"] = str(d["_id"])
        return f"--- Motor MongoDB: {database}.{collection} ({len(docs)} docs) ---\n" + \
               json.dumps(docs, indent=2, ensure_ascii=False)[:8000]
    except Exception as e:
        return f"Error with Motor: {e}"


def sql_query(connection_string: str, query: str) -> str:
    """Execute SQL query using SQLAlchemy."""
    try:
        sa = _lazy("sqlalchemy")
        if not sa:
            return "Error: sqlalchemy not installed."
        engine = sa.create_engine(connection_string)
        with engine.connect() as conn:
            result = conn.execute(sa.text(query))
            rows = [dict(r._mapping) for r in result.fetchmany(50)]
        return f"--- SQL ({len(rows)} rows) ---\n" + json.dumps(rows, indent=2, ensure_ascii=False, default=str)[:8000]
    except Exception as e:
        return f"Error executing SQL: {e}"


def mqtt_publish(topic: str, message: str, host: str = "localhost", port: int = 1883) -> str:
    """Publish an MQTT message."""
    try:
        mqtt = _lazy("paho.mqtt.client") or _lazy("paho.mqtt")
        if not mqtt:
            return "Error: paho-mqtt not installed."
        client = mqtt.Client()
        client.connect(host, port, 60)
        client.publish(topic, message)
        client.disconnect()
        return f"Published to {topic} on {host}:{port}"
    except Exception as e:
        return f"Error publishing MQTT: {e}"


# --------------------------------------------------------------------------- #
# NEW: IoT / Home Automation (broadlink, pyitunes)
# --------------------------------------------------------------------------- #

def broadlink_discover() -> str:
    """Discover Broadlink devices on the network."""
    try:
        bl = _lazy("broadlink")
        if not bl:
            return "Error: broadlink not installed."
        devices = bl.discover(timeout=5)
        if not devices:
            return "No Broadlink devices found."
        lines = []
        for d in devices:
            lines.append(f"{d.host[0]}:{d.host[1]} | type={d.type} | name={d.name} | mac={d.mac.hex()}")
        return "--- Broadlink Devices ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error discovering Broadlink: {e}"


# --------------------------------------------------------------------------- #
# NEW: Data Science (scikit-learn, numpy, scipy, networkx)
# --------------------------------------------------------------------------- #

def analyze_data_stats(file_path: str) -> str:
    """Basic statistical analysis using numpy/scipy."""
    try:
        np = _lazy("numpy")
        if not np:
            return "Error: numpy not installed."
        pd = _lazy("pandas")
        if not pd:
            return "Error: pandas not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        ext = Path(file_path).suffix.lower()
        if ext in (".csv", ".tsv"):
            df = pd.read_csv(file_path, sep="\t" if ext == ".tsv" else ",")
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        else:
            return f"Unsupported: {ext}"
        num_cols = df.select_dtypes(include=[np.number]).columns
        if len(num_cols) == 0:
            return "No numeric columns found."
        stats = df[num_cols].describe().to_string()
        corr = df[num_cols].corr().to_string() if len(num_cols) > 1 else ""
        return f"--- Stats: {file_path} ({len(df)} rows) ---\n{stats}\n\nCorrelation:\n{corr}"
    except Exception as e:
        return f"Error analyzing data: {e}"


def train_model(data_path: str, target_column: str, test_size: float = 0.2) -> str:
    """Train a simple ML model using scikit-learn."""
    try:
        sk = _lazy("sklearn")
        if not sk:
            return "Error: scikit-learn not installed."
        pd = _lazy("pandas")
        if not pd:
            return "Error: pandas not installed."
        np = _lazy("numpy")
        if not np:
            return "Error: numpy not installed."
        if not os.path.exists(data_path):
            return f"Error: '{data_path}' not found."
        df = pd.read_csv(data_path)
        if target_column not in df.columns:
            return f"Error: column '{target_column}' not in {list(df.columns)}."
        X = df.select_dtypes(include=[np.number]).drop(columns=[target_column], errors="ignore")
        y = df[target_column]
        if X.empty:
            return "No numeric features for training."
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=42)
        if y.nunique() < 10:
            model = RandomForestClassifier(n_estimators=50, random_state=42)
        else:
            model = RandomForestRegressor(n_estimators=50, random_state=42)
        model.fit(X_train, y_train)
        score = model.score(X_test, y_test)
        return (f"--- ML Model ---\nModel: {type(model).__name__}\n"
                f"Features: {list(X.columns)}\nTarget: {target_column}\n"
                f"Train samples: {len(X_train)}, Test samples: {len(X_test)}\n"
                f"R² Score: {score:.4f}")
    except Exception as e:
        return f"Error training model: {e}"


def analyze_network(data: str = "") -> str:
    """Analyze a graph/network using networkx (basic demo)."""
    try:
        nx = _lazy("networkx")
        if not nx:
            return "Error: networkx not installed."
        G = nx.Graph()
        G.add_edge("A", "B", weight=1)
        G.add_edge("B", "C", weight=2)
        G.add_edge("C", "A", weight=3)
        G.add_edge("C", "D", weight=1)
        return (f"--- NetworkX Graph ---\nNodes: {G.nodes()}\nEdges: {G.edges(data=True)}\n"
                f"Density: {nx.density(G):.3f}\nDegree centrality: {nx.degree_centrality(G)}")
    except Exception as e:
        return f"Error analyzing network: {e}"


# --------------------------------------------------------------------------- #
# NEW: Audio tools (sounddevice, gTTS, SpeechRecognition, pydub)
# --------------------------------------------------------------------------- #

def text_to_speech(text: str, lang: str = "id", filename: str = "") -> str:
    """Convert text to speech using gTTS."""
    filename = filename or os.path.join(tempfile.gettempdir(), "tts_output.mp3")
    if not text.strip():
        return "Error: text must not be empty."
    try:
        gtts = _lazy("gtts")
        if not gtts:
            return "Error: gTTS not installed."
        from gtts import gTTS as TTS
        tts = TTS(text=text[:500], lang=lang)
        tts.save(filename)
        size = os.path.getsize(filename)
        return f"Audio saved to {filename} ({size} bytes)"
    except Exception as e:
        return f"Error generating speech: {e}"


def speech_to_text(audio_file: str) -> str:
    """Transcribe audio file using SpeechRecognition."""
    try:
        sr = _lazy("speech_recognition")
        if not sr:
            return "Error: SpeechRecognition not installed."
        r = sr.Recognizer()
        with sr.AudioFile(audio_file) as source:
            audio = r.record(source)
        try:
            text = r.recognize_google(audio, language="id-ID")
            return f"Transcription: {text}"
        except sr.UnknownValueError:
            return "Could not understand audio."
        except sr.RequestError as e:
            return f"Recognition service error: {e}"
    except Exception as e:
        return f"Error transcribing: {e}"


def play_audio(file_path: str) -> str:
    """Play audio file info using pydub."""
    try:
        pdub = _lazy("pydub")
        if not pdub:
            return "Error: pydub not installed."
        from pydub import AudioSegment
        audio = AudioSegment.from_file(file_path)
        return (f"--- Audio: {file_path} ---\nDuration: {len(audio)/1000:.1f}s\n"
                f"Channels: {audio.channels}\nFrame rate: {audio.frame_rate}Hz\n"
                f"Sample width: {audio.sample_width} bytes")
    except Exception as e:
        return f"Error reading audio: {e}"


def record_audio(duration: int = 3, samplerate: int = 44100, filename: str = "") -> str:
    """Record audio from microphone using sounddevice."""
    filename = filename or os.path.join(tempfile.gettempdir(), "recorded.wav")
    if duration <= 0 or samplerate <= 0:
        return "Error: duration and samplerate must be positive."
    try:
        sd = _lazy("sounddevice")
        if not sd:
            return "Error: sounddevice not installed."
        import numpy as np
        recording = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype="int16")
        sd.wait()
        from scipy.io.wavfile import write
        write(filename, samplerate, recording)
        return f"Recorded {duration}s audio to {filename} ({os.path.getsize(filename)} bytes)."
    except Exception as e:
        return f"Error recording audio: {e}"


# --------------------------------------------------------------------------- #
# NEW: Scheduling & RPC (schedule, rpyc, python-crontab)
# --------------------------------------------------------------------------- #

def schedule_add(time_str: str, command_text: str) -> str:
    """Add a scheduled task using schedule library."""
    try:
        sch = _lazy("schedule")
        if not sch:
            return "Error: schedule not installed."
        parts = time_str.lower().split()
        job = None
        if "every" in time_str:
            parts = time_str.split()
            if len(parts) >= 2 and parts[1].isdigit():
                n = int(parts[1])
                if "seconds" in time_str: job = sch.every(n).seconds
                elif "minutes" in time_str: job = sch.every(n).minutes
                elif "hours" in time_str: job = sch.every(n).hours
            elif "day" in time_str: job = sch.every().day
            elif "hour" in time_str: job = sch.every().hour
        if not job:
            return f"Could not parse schedule: {time_str}"
        job.do(lambda: execute_command(command_text))
        return f"Scheduled: '{command_text}' every {time_str}"
    except Exception as e:
        return f"Error scheduling: {e}"


def crontab_add(schedule_expr: str, command_text: str) -> str:
    """Add a crontab entry using python-crontab."""
    try:
        ct = _lazy("crontab")
        if not ct:
            return "Error: python-crontab not installed."
        from crontab import CronTab
        cron = CronTab(user=True)
        job = cron.new(command=command_text, comment="homelab-ai")
        job.setall(schedule_expr)
        cron.write()
        return f"Added crontab: {schedule_expr} {command_text}"
    except Exception as e:
        return f"Error adding crontab: {e}"


def rpyc_call(host: str, port: int = 18812, function: str = "", arg: str = "") -> str:
    """Call a remote function via RPyC."""
    try:
        m = _lazy("rpyc")
        if not m:
            return "Error: rpyc not installed."
        conn = m.connect(host, port, config={"sync_request_timeout": 10})
        if function:
            result = getattr(conn.root, function)(arg)
        else:
            result = "Connected."
        conn.close()
        return f"--- RPyC {host}:{port} ---\n{result}"
    except Exception as e:
        return f"Error in RPC call: {e}"


# --------------------------------------------------------------------------- #
# NEW: Utility tools (qrcode, pyotp, pyarrow, configparser)
# --------------------------------------------------------------------------- #

def generate_qrcode(data: str, file_path: str = "") -> str:
    """Generate a QR code image."""
    file_path = file_path or os.path.join(tempfile.gettempdir(), "qrcode.png")
    try:
        qr = _lazy("qrcode")
        if not qr:
            return "Error: qrcode not installed."
        img = qr.make(data)
        img.save(file_path)
        return f"QR code saved to {file_path} (size={os.path.getsize(file_path)} bytes)"
    except Exception as e:
        return f"Error generating QR: {e}"


def generate_otp(secret: str = "JBSWY3DPEHPK3PXP") -> str:
    """Generate a TOTP code using pyotp."""
    try:
        otp = _lazy("pyotp")
        if not otp:
            return "Error: pyotp not installed."
        totp = otp.TOTP(secret)
        return f"Current OTP: {totp.now()} (valid for {30 - (int(time.time()) % 30)}s)"
    except Exception as e:
        return f"Error generating OTP: {e}"


def parquet_info(file_path: str) -> str:
    """Read Parquet file metadata using pyarrow."""
    try:
        pa = _lazy("pyarrow")
        if not pa:
            return "Error: pyarrow not installed."
        from pyarrow import parquet as pq
        pf = pq.ParquetFile(file_path)
        meta = pf.metadata
        return (f"--- Parquet: {file_path} ---\nRows: {meta.num_rows}\n"
                f"Columns: {[meta.schema.field(i).name for i in range(meta.schema.num_columns)]}\n"
                f"Row groups: {meta.num_row_groups}")
    except Exception as e:
        return f"Error reading parquet: {e}"


def config_read(file_path: str, section: Optional[str] = None) -> str:
    """Read an INI configuration file using configparser."""
    try:
        cp = _lazy("configparser")
        if not cp:
            return "Error: configparser not installed."
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' not found."
        config = cp.ConfigParser()
        config.read(file_path)
        if section:
            if section not in config:
                return f"Section '{section}' not found. Sections: {list(config.sections())}"
            items = dict(config[section])
            return f"--- [{section}] ---\n{json.dumps(items, indent=2)}"
        result = {}
        for s in config.sections():
            result[s] = dict(config[s])
        return f"--- Config: {file_path} ---\n{json.dumps(result, indent=2, ensure_ascii=False)[:8000]}"
    except Exception as e:
        return f"Error reading config: {e}"

# --------------------------------------------------------------------------- #
# Phase 4 – Additional Libraries (pyproxmox, wakeonlan, ping3, netifaces, scapy, dnspython, humanize, slugify, parse, arrow, croniter, blinker, sentry, prometheus, watchdog)
# --------------------------------------------------------------------------- #

def proxmox_list_nodes(host: str, token_id: str, token_secret: str, verify_ssl: bool = True) -> str:
    """List Proxmox VE nodes."""
    try:
        px = _lazy("pyproxmox")
        if not px:
            return "Error: pyproxmox not installed."
        prox = px.ProxmoxAPI(host, user=token_id, token_name=token_id, token_value=token_secret, verify_ssl=verify_ssl)
        nodes = prox.nodes.get()
        if not nodes:
            return "No nodes found."
        lines = [f"{n['node']} | status={n.get('status','?')} | cpu={n.get('cpu',0)*100:.1f}% | mem={n.get('mem',0)/1024**3:.1f}GB/{n.get('maxmem',1)/1024**3:.1f}GB" for n in nodes]
        return "--- Proxmox Nodes ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing Proxmox nodes: {e}"


def proxmox_list_vms(host: str, token_id: str, token_secret: str, node: str = "", verify_ssl: bool = True) -> str:
    """List VMs/containers on Proxmox node(s)."""
    try:
        px = _lazy("pyproxmox")
        if not px:
            return "Error: pyproxmox not installed."
        prox = px.ProxmoxAPI(host, user=token_id, token_name=token_id, token_value=token_secret, verify_ssl=verify_ssl)
        nodes = [node] if node else [n["node"] for n in prox.nodes.get()]
        output = []
        for n in nodes:
            guests = prox.nodes(n).qemu.get() + prox.nodes(n).lxc.get()
            for g in guests:
                output.append(f"{n}/{g.get('vmid','?')} | {g.get('name','?')} | status={g.get('status','?')} | mem={g.get('mem',0)/1024**3:.1f}GB/{g.get('maxmem',1)/1024**3:.1f}GB")
        return "--- Proxmox VMs ---\n" + "\n".join(output) if output else f"No VMs found on {nodes}."
    except Exception as e:
        return f"Error listing VMs: {e}"


def wake_on_lan(mac_address: str, broadcast_ip: str = "255.255.255.255") -> str:
    """Send Wake-on-LAN magic packet."""
    try:
        wol = _lazy("wakeonlan")
        if not wol:
            return "Error: wakeonlan not installed."
        wol.send_magic_packet(mac_address, ip_address=broadcast_ip)
        return f"WOL packet sent to {mac_address} via {broadcast_ip}."
    except Exception as e:
        return f"Error sending WOL: {e}"


def ping_host(host: str, count: int = 4) -> str:
    """ICMP ping using ping3."""
    try:
        p3 = _lazy("ping3")
        if not p3:
            return "Error: ping3 not installed."
        results = []
        for i in range(count):
            rtt = p3.ping(host, timeout=2)
            if rtt is None:
                results.append(f"  #{i+1}: timeout")
            else:
                results.append(f"  #{i+1}: {rtt*1000:.1f}ms")
        return f"--- Ping {host} ---\n" + "\n".join(results)
    except Exception as e:
        return f"Error pinging: {e}"


def ssh_scp_upload(host: str, username: str, local_path: str, remote_path: str,
                   password: str = "", port: int = 22) -> str:
    """Upload file via SCP over SSH."""
    try:
        pm = _lazy("paramiko")
        if not pm:
            return "Error: paramiko not installed."
        scp = _lazy("scp")
        if not scp:
            return "Error: scp not installed."
        if not os.path.exists(local_path):
            return f"Error: local file '{local_path}' not found."
        ssh = pm.SSHClient()
        ssh.set_missing_host_key_policy(pm.AutoAddPolicy())
        if password:
            ssh.connect(host, port=port, username=username, password=password, timeout=10)
        else:
            ssh.connect(host, port=port, username=username, timeout=10)
        with scp.SCPClient(ssh.get_transport()) as client:
            client.put(local_path, remote_path)
        ssh.close()
        return f"Uploaded {local_path} -> {username}@{host}:{remote_path}"
    except Exception as e:
        return f"Error uploading: {e}"


def ssh_scp_download(host: str, username: str, remote_path: str, local_path: str,
                     password: str = "", port: int = 22) -> str:
    """Download file via SCP over SSH."""
    try:
        pm = _lazy("paramiko")
        if not pm:
            return "Error: paramiko not installed."
        scp = _lazy("scp")
        if not scp:
            return "Error: scp not installed."
        ssh = pm.SSHClient()
        ssh.set_missing_host_key_policy(pm.AutoAddPolicy())
        if password:
            ssh.connect(host, port=port, username=username, password=password, timeout=10)
        else:
            ssh.connect(host, port=port, username=username, timeout=10)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        with scp.SCPClient(ssh.get_transport()) as client:
            client.get(remote_path, local_path)
        ssh.close()
        return f"Downloaded {username}@{host}:{remote_path} -> {local_path} ({os.path.getsize(local_path)} bytes)"
    except Exception as e:
        return f"Error downloading: {e}"


def pexpect_spawn(command: str, timeout: int = 30) -> str:
    """Spawn an interactive process using pexpect."""
    if platform.system() == "Windows":
        return "Error: pexpect not available on Windows. Use execute_command instead."
    try:
        px = _lazy("pexpect")
        if not px:
            return "Error: pexpect not installed."
        shell = "/bin/sh"
        child = px.spawn(shell, ["-c", command], timeout=timeout)
        child.expect(px.EOF)
        output = child.before.decode(errors="replace") if child.before else ""
        return f"--- Pexpect: {command} ---\n{output[:4000]}"
    except Exception as e:
        return f"Error spawning process: {e}"


def network_interfaces() -> str:
    """List network interfaces info using netifaces."""
    try:
        ni = _lazy("netifaces")
        if not ni:
            return "Error: netifaces not installed."
        lines = []
        for iface in ni.interfaces():
            addrs = ni.ifaddresses(iface)
            ipv4 = addrs.get(ni.AF_INET, [{}])[0].get("addr", "-")
            mac = addrs.get(ni.AF_LINK, [{}])[0].get("addr", "-")
            lines.append(f"{iface}: IP={ipv4} MAC={mac}")
        return "--- Network Interfaces ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing interfaces: {e}"


def scapy_traceroute(target: str, max_hops: int = 15) -> str:
    """Traceroute using scapy."""
    try:
        scapy = _lazy("scapy")
        if not scapy:
            return "Error: scapy not installed."
        from scapy.all import traceroute as tr
        result = tr(target, maxttl=max_hops, verbose=False)
        lines = []
        for snd, rcv in result[0].items():
            ttl = snd.ttl
            src = rcv.src if rcv else "*"
            rtt = f"{((rcv.time - snd.sent_time)*1000):.1f}ms" if rcv and hasattr(rcv, 'time') else "*"
            lines.append(f"  {ttl:2d}: {src:15s} {rtt}")
        return f"--- Scapy Traceroute to {target} ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error in traceroute: {e}"


def dns_lookup(domain: str, record_type: str = "A") -> str:
    """DNS lookup using dnspython."""
    try:
        dns_mod = _lazy("dns")
        if not dns_mod:
            return "Error: dnspython not installed."
        from dns import resolver, rdatatype
        res = resolver.Resolver()
        answers = res.resolve(domain, record_type)
        lines = [f"{domain} {record_type} -> {rdata.to_text()}" for rdata in answers]
        return f"--- DNS Lookup ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error in DNS lookup: {e}"


def humanize_value(value: str, type_name: str = "number") -> str:
    """Humanize numbers or dates using humanize."""
    try:
        h = _lazy("humanize")
        if not h:
            return "Error: humanize not installed."
        if type_name == "number":
            try:
                n = float(value)
                return f"{n} -> {h.intword(n)} ({h.intcomma(n)})"
            except ValueError:
                return f"Cannot parse '{value}' as number."
        elif type_name == "bytes":
            try:
                n = float(value)
                return f"{n} bytes -> {h.naturalsize(n)}"
            except ValueError:
                return f"Cannot parse '{value}' as bytes."
        elif type_name == "date":
            from datetime import datetime
            dt = datetime.fromisoformat(value)
            return f"{value} -> {h.naturaldate(dt)} ({h.naturaltime(dt)})"
        else:
            return f"Unsupported type '{type_name}'. Use: number, bytes, date."
    except Exception as e:
        return f"Error humanizing: {e}"


def slugify_text(text: str) -> str:
    """Convert text to URL-friendly slug."""
    try:
        sl = _lazy("slugify")
        if not sl:
            return "Error: python-slugify not installed."
        from slugify import slugify as _slugify
        result = _slugify(text)
        return f"Original: {text}\nSlug: {result}"
    except Exception as e:
        return f"Error slugifying: {e}"


def parse_string(pattern: str, text: str) -> str:
    """Parse a string using a pattern (like scanf)."""
    try:
        p = _lazy("parse")
        if not p:
            return "Error: parse not installed."
        result = p.parse(pattern, text)
        if result:
            return f"Pattern: {pattern}\nText: {text}\nResult: {result.named if result.named else result.fixed}"
        return f"No match. Pattern: {pattern}  Text: {text}"
    except Exception as e:
        return f"Error parsing: {e}"


def arrow_time(expression: str = "now") -> str:
    """Date/time operations using arrow: 'now', '2024-01-01', 'now - 3 days', etc."""
    try:
        ar = _lazy("arrow")
        if not ar:
            return "Error: arrow not installed."
        try:
            dt = ar.get(expression)
        except Exception:
            dt = ar.now()
        return (f"Expression: {expression}\nISO: {dt.isoformat()}\n"
                f"Human: {dt.humanize()}\nTimestamp: {dt.timestamp()}\n"
                f"Format: {dt.format('YYYY-MM-DD HH:mm:ss')}")
    except Exception as e:
        return f"Error with arrow: {e}"


def cron_next(cron_expression: str) -> str:
    """Compute next execution time for a cron expression."""
    try:
        ci = _lazy("croniter")
        if not ci:
            return "Error: croniter not installed."
        from croniter import croniter
        from datetime import datetime
        cron = croniter(cron_expression, datetime.now())
        next_time = cron.get_next(datetime)
        prev_time = cron.get_prev(datetime)
        return (f"Cron: {cron_expression}\nPrevious: {prev_time.isoformat()}\n"
                f"Next: {next_time.isoformat()}")
    except Exception as e:
        return f"Error computing cron: {e}"


def send_signal(name: str, data: str = "") -> str:
    """Send a signal via blinker."""
    try:
        bl = _lazy("blinker")
        if not bl:
            return "Error: blinker not installed."
        from blinker import signal
        sig = signal(name)
        sent = sig.send(data)
        return f"Signal '{name}' sent to {len(sent)} receivers."
    except Exception as e:
        return f"Error sending signal: {e}"


def watch_directory(path: str, pattern: str = "", timeout: int = 5) -> str:
    """Watch a directory for file changes (watchdog, blocks up to timeout sec)."""
    try:
        wd = _lazy("watchdog")
        if not wd:
            return "Error: watchdog not installed."
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        if not os.path.isdir(path):
            return f"Error: '{path}' is not a directory."

        class _Handler(FileSystemEventHandler):
            def __init__(self):
                self.events = []
            def on_modified(self, e): self.events.append(f"modified: {e.src_path}")
            def on_created(self, e): self.events.append(f"created: {e.src_path}")
            def on_deleted(self, e): self.events.append(f"deleted: {e.src_path}")
            def on_moved(self, e): self.events.append(f"moved: {e.src_path} -> {e.dest_path}")

        handler = _Handler()
        observer = Observer()
        observer.schedule(handler, path, recursive=True)
        observer.start()
        time.sleep(timeout)
        observer.stop()
        observer.join()
        if not handler.events:
            return f"Watched '{path}' for {timeout}s — no changes detected."
        filtered = [e for e in handler.events if not pattern or pattern in e]
        return f"--- Watchdog: {path} ({timeout}s) ---\n" + "\n".join(filtered[-20:])
    except Exception as e:
        return f"Error watching directory: {e}"


def prometheus_metrics() -> str:
    """Generate sample Prometheus metrics data."""
    try:
        pm = _lazy("prometheus_client")
        if not pm:
            return "Error: prometheus-client not installed."
        from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
        registry = CollectorRegistry()
        c = Counter("requests_total", "Total requests", registry=registry)
        g = Gauge("cpu_usage_percent", "CPU usage", registry=registry)
        c.inc(42)
        g.set(65.5)
        return generate_latest(registry).decode()
    except Exception as e:
        return f"Error generating metrics: {e}"


def ask_codebase(question: str, top_k: int = 5) -> str:
    """Query the codebase with a natural-language question using vector RAG."""
    try:
        from homelab_ai.rag import get_rag
        rag = get_rag()
        status = rag.ensure_indexed()
        if "Error" in status:
            return status
        return rag.query(question, top_k)
    except Exception as e:
        return f"Error querying codebase: {e}"




def list_dir(directory_path: str = ".") -> str:
    try:
        directory_path = directory_path or "."
        files = os.listdir(directory_path)
        filtered = [f for f in files if f not in {"venv", ".git", "__pycache__"}]
        return f"Files in '{directory_path}': {', '.join(filtered)}"
    except Exception as e:
        return f"Error listing directory: {e}"


def view_file(file_path: str) -> str:
    try:
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            return f"Error: File '{file_path}' does not exist."
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"--- Content of '{file_path}' ---\n{content}\n--------------------"
    except Exception as e:
        return f"Error viewing file: {e}"


def write_file(file_path: str, content: str) -> str:
    try:
        dir_name = os.path.dirname(file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        backup_path = _backup_file(file_path)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        written_size = os.path.getsize(file_path)
        backup_note = f" Backup: {backup_path}." if backup_path else ""
        return f"SUCCESS: wrote {file_path} ({written_size} bytes).{backup_note} Do not retry this write."
    except Exception as e:
        return f"Error writing file: {e}"


def compute_patch(file_path: str, search_text: str, replace_text: str) -> dict:
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"Error: File '{file_path}' does not exist."}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if search_text not in content:
            return {"ok": False, "error": "Search text not found."}
        new_content = content.replace(search_text, replace_text)
        diff = "\n".join(difflib.unified_diff(
            content.splitlines(), new_content.splitlines(),
            fromfile=f"a/{file_path}", tofile=f"b/{file_path}", lineterm=""))
        return {"ok": True, "file_path": file_path, "old": search_text,
                "new": replace_text, "diff": diff, "new_content": new_content}
    except Exception as e:
        return {"ok": False, "error": f"Error: {e}"}


def apply_patch(file_path: str, new_content: str) -> str:
    try:
        backup_path = _backup_file(file_path)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        backup_note = f" Backup: {backup_path}." if backup_path else ""
        return f"Success: modified '{file_path}'.{backup_note}"
    except Exception as e:
        return f"Error applying patch: {e}"


def _backup_file(file_path: str) -> str:
    """Create a single adjacent backup before overwriting an existing file."""
    if not os.path.isfile(file_path):
        return ""
    backup_path = f"{file_path}.bak"
    shutil.copy2(file_path, backup_path)
    return backup_path


# --------------------------------------------------------------------------- #
# System tools
# --------------------------------------------------------------------------- #

def get_system_stats() -> str:
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        _, _, free = shutil.disk_usage("/")
        return (f"=== SYSTEM STATS ===\nOS: {platform.system()} {platform.release()}\n"
                f"CPU: {cpu}%\nRAM: {mem.percent}% (Free: {mem.available/1024**2:.1f} MB)\n"
                f"Disk Free: {free/1024**3:.2f} GB")
    except Exception as e:
        return f"Error getting system stats: {e}"


ALLOWED_COMMANDS = {
    "xdg-open", "start", "open", "powershell", "pwsh", "cmd", "code", "browser",
    "python3", "python", "pip", "pip3", "ls", "dir", "pwd", "cat", "type",
    "echo", "git", "ping", "mkdir", "touch", "uname", "ipconfig", "ip",
    "whoami", "date", "df", "free", "fastfetch",
    "copy", "move", "del", "ren", "find", "findstr", "more", "sort",
    "where", "tree", "systeminfo", "tasklist", "netstat", "nslookup",
    "chdir", "cd", "pushd", "popd", "set", "path", "help", "ver",
    "node", "npm", "npx",
}


def check_command_safety(command: str) -> bool:
    try:
        inst = (f"You are a strict security subsystem. Analyze this terminal command. "
                f"If it contains highly destructive actions reply with 'DANGEROUS', "
                f"otherwise 'SAFE'. Command: '{command}'\nReply only with ONE WORD:")
        resp = get_deepseek_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": inst}],
            temperature=0.0, max_tokens=5)
        return "SAFE" in resp.choices[0].message.content.strip().upper()
    except Exception:
        return False


def plugin_install(source: str, name: str = "") -> str:
    """Install a plugin from a URL or GitHub ref."""
    from .plugin_installer import install_plugin, hot_reload
    n = name or None
    result = install_plugin(source, name=n)
    if result["ok"]:
        hot_reload()
        return f"Plugin installed: {result['path']}"
    return f"Error: {result.get('error', 'unknown error')}"


def plugin_remove(name: str) -> str:
    """Remove an installed plugin."""
    from .plugin_installer import remove_plugin, hot_reload
    result = remove_plugin(name)
    if result["ok"]:
        hot_reload()
        return f"Plugin removed: {name}"
    return f"Error: {result.get('error', 'unknown error')}"


# --------------------------------------------------------------------------- #
# NEW: Docker Compose tools
# --------------------------------------------------------------------------- #
def docker_compose_up(file_path: str = "docker-compose.yml", service: str = "", detach: bool = True) -> str:
    try:
        cmd = f"docker compose -f {shlex.quote(file_path)} up {'-d ' if detach else ''}{service}".strip()
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=120)
        out = result.stdout or result.stderr
        return f"Exit Code: {result.returncode}\n{out[:2000]}"
    except Exception as e:
        return f"Error: docker compose up failed — {e}"

def docker_compose_down(file_path: str = "docker-compose.yml", volumes: bool = False) -> str:
    try:
        cmd = f"docker compose -f {shlex.quote(file_path)} down {'-v' if volumes else ''}"
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=60)
        return f"Exit Code: {result.returncode}\n{result.stdout[:2000]}"
    except Exception as e:
        return f"Error: docker compose down failed — {e}"

def docker_compose_logs(file_path: str = "docker-compose.yml", service: str = "", tail: int = 50) -> str:
    try:
        cmd = f"docker compose -f {shlex.quote(file_path)} logs --tail={tail} {service}".strip()
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        return result.stdout[-4000:] or result.stderr[-4000:]
    except Exception as e:
        return f"Error: docker compose logs failed — {e}"

def docker_compose_ps(file_path: str = "docker-compose.yml") -> str:
    try:
        cmd = f"docker compose -f {shlex.quote(file_path)} ps"
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        return result.stdout[:3000] or result.stderr[:3000]
    except Exception as e:
        return f"Error: docker compose ps failed — {e}"

# --------------------------------------------------------------------------- #
# NEW: Kubernetes tools
# --------------------------------------------------------------------------- #
def kubectl_get(resource: str, namespace: str = "", output: str = "") -> str:
    try:
        ns = f"-n {shlex.quote(namespace)} " if namespace else ""
        out = f"-o {shlex.quote(output)} " if output else ""
        cmd = f"kubectl get {resource} {ns}{out}".strip()
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        return result.stdout[:4000] or result.stderr[:4000]
    except Exception as e:
        return f"Error: kubectl get failed — {e}"

def kubectl_logs(pod: str, container: str = "", namespace: str = "", tail: int = 100, follow: bool = False) -> str:
    try:
        ns = f"-n {shlex.quote(namespace)} " if namespace else ""
        c = f"-c {shlex.quote(container)} " if container else ""
        f_flag = "-f " if follow else ""
        cmd = f"kubectl logs {pod} {ns}{c}--tail={tail} {f_flag}".strip()
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        return result.stdout[-4000:] or result.stderr[-4000:]
    except Exception as e:
        return f"Error: kubectl logs failed — {e}"

def kubectl_describe(resource: str, name: str, namespace: str = "") -> str:
    try:
        ns = f"-n {shlex.quote(namespace)} " if namespace else ""
        cmd = f"kubectl describe {resource} {shlex.quote(name)} {ns}".strip()
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        return result.stdout[:4000] or result.stderr[:4000]
    except Exception as e:
        return f"Error: kubectl describe failed — {e}"

# --------------------------------------------------------------------------- #
# NEW: Network Port Scanner
# --------------------------------------------------------------------------- #
def scan_ports(host: str, ports: str = "1-1024", timeout: float = 1.0) -> str:
    try:
        import socket
        open_ports = []
        ranges = ports.split(",")
        all_ports = []
        for r in ranges:
            if "-" in r:
                a, b = r.split("-", 1)
                all_ports.extend(range(int(a.strip()), int(b.strip()) + 1))
            else:
                all_ports.append(int(r.strip()))
        for port in all_ports[:200]:  # cap at 200 ports
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                result = s.connect_ex((host, port))
                if result == 0:
                    try:
                        service = socket.getservbyport(port)
                    except OSError:
                        service = "unknown"
                    open_ports.append(f"{port}/{service}")
            finally:
                s.close()
        if open_ports:
            return f"Open ports on {host} ({len(open_ports)} found):\n" + "\n".join(open_ports)
        return f"No open ports found on {host} in range {ports}."
    except Exception as e:
        return f"Error scanning ports: {e}"

# --------------------------------------------------------------------------- #
# NEW: Log Viewer tools
# --------------------------------------------------------------------------- #
def tail_log_file(file_path: str, lines: int = 50, follow: bool = False) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        out = "".join(tail)
        if not out.strip():
            return f"(empty log: {file_path})"
        return out[-4000:]
    except Exception as e:
        return f"Error tailing log: {e}"

def search_log_file(file_path: str, pattern: str, context_lines: int = 3) -> str:
    try:
        import re
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        matches = []
        for i, line in enumerate(all_lines):
            if re.search(pattern, line):
                start = max(0, i - context_lines)
                end = min(len(all_lines), i + context_lines + 1)
                matches.append("---")
                for j in range(start, end):
                    prefix = ">" if j == i else " "
                    matches.append(f"{prefix}{j+1}: {all_lines[j].rstrip()}")
        if not matches:
            return f"No matches found for '{pattern}' in {file_path}."
        out = "\n".join(matches)
        return out[-4000:]
    except Exception as e:
        return f"Error searching log: {e}"

# --------------------------------------------------------------------------- #
# NEW: Vision – Advanced Image Understanding (Gemini Vision)
# --------------------------------------------------------------------------- #
def analyze_image_advanced(file_path: str, prompt: str = "Describe this image in detail.") -> str:
    try:
        from .config import GEMINI_API_KEY, logger as cfg_logger
        if not GEMINI_API_KEY:
            try:
                from .config import _lazy_install
                _lazy_install("Pillow")
                from PIL import Image
                img = Image.open(file_path)
                return f"[Vision offline — no Gemini key] Image: {file_path}\nSize: {img.size}\nFormat: {img.format}\nMode: {img.mode}"
            except Exception:
                return f"[Vision offline — no Gemini key] File: {file_path}"
        import google.genai as genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        import mimetypes
        mime, _ = mimetypes.guess_type(file_path)
        mime = mime or "image/jpeg"
        with open(file_path, "rb") as f:
            data = f.read()
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, genai.types.Part.from_bytes(data=data, mime_type=mime)],
        )
        return resp.text or "(no response)"
    except Exception as e:
        return f"Error analyzing image: {e}"


def execute_command(command: str) -> str:
    try:
        args = shlex.split(command)
        if not args:
            return "Error: No command provided."
        base = args[0].lower()
        if platform.system() == "Windows" and base == "type" and len(args) == 2:
            return view_file(args[1])
        if base not in ALLOWED_COMMANDS:
            if check_command_safety(command):
                ALLOWED_COMMANDS.add(base)
                logger.info("[Auto-Learned] Integrated '%s'.", base)
            else:
                return f"Error: '{base}' flagged as dangerous."
        if platform.system() == "Windows" and base == "start":
            args = ["powershell", "-Command", f"Start-Process {' '.join(args[1:])}"]
        result = subprocess.run(args, shell=False, text=True, capture_output=True, timeout=30)
        return f"Exit Code: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
    except Exception as e:
        return f"Error executing command: {e}"
