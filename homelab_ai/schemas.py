"""Typed tool contracts powered by pydantic."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Original tool parameter models
# --------------------------------------------------------------------------- #
class ScrapeWebsiteParams(BaseModel):
    url: str = Field(description="Absolute URL to scrape.")

class ReadPdfParams(BaseModel):
    file_path: str = Field(description="Path to a local PDF file.")

class ListDirParams(BaseModel):
    directory_path: str = Field(default=".", description="Directory to list.")

class ViewFileParams(BaseModel):
    file_path: str = Field(description="Exact path to a local file, including paths outside the app directory.")

class WriteFileParams(BaseModel):
    file_path: str = Field(description="Destination path.")
    content: str = Field(description="Full file content to write.")

class ExecuteCommandParams(BaseModel):
    command: str = Field(description="Command to execute; do not use this to read files, use view_file instead.")

class SummarizeYoutubeParams(BaseModel):
    url: str = Field(description="YouTube video URL.")

class ReadLocalVideoParams(BaseModel):
    file_path: str = Field(description="Path to a local video file.")

class WebSearchParams(BaseModel):
    query: str = Field(description="Search query.")

class GetWeatherParams(BaseModel):
    location: str = Field(description="City or location name.")

class GetSystemStatsParams(BaseModel):
    pass

class PatchFileParams(BaseModel):
    file_path: str = Field(description="File to patch.")
    search_text: str = Field(description="Exact text to find.")
    replace_text: str = Field(description="Replacement text.")

# --------------------------------------------------------------------------- #
# Enhanced tool parameter models (Phase 1)
# --------------------------------------------------------------------------- #
class AnalyzeCodeParams(BaseModel):
    file_path: str = Field(description="Path to source code file.")
    language: Optional[str] = Field(default=None, description="Language (auto-detected if not given).")

class SearchFilesParams(BaseModel):
    pattern: str = Field(description="Gitignore-style pattern (e.g., **/*.py).")
    root_dir: str = Field(default=".", description="Root directory.")

class CountTokensParams(BaseModel):
    text: str = Field(description="Text to count tokens for.")
    model: str = Field(default="cl100k_base", description="Tiktoken encoding model.")

class ResolveJsonRefParams(BaseModel):
    file_path: str = Field(description="Path to JSON file with $ref.")

class WebFetchAsyncParams(BaseModel):
    url: str = Field(description="URL to fetch.")
    method: str = Field(default="GET", description="HTTP method.")
    headers: Optional[dict] = Field(default=None, description="Optional HTTP headers.")

class GetAppPathsParams(BaseModel):
    app_name: str = Field(default="homelab-ai", description="Application name.")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – Deep code analysis & formatting
# --------------------------------------------------------------------------- #
class AnalyzePythonParams(BaseModel):
    file_path: str = Field(description="Python file to analyse with jedi.")

class CalculateComplexityParams(BaseModel):
    file_path: str = Field(description="Python file to analyse for complexity.")

class FormatCodeParams(BaseModel):
    file_path: str = Field(description="Python file to auto-format with black.")

class SortImportsParams(BaseModel):
    file_path: str = Field(description="Python file to sort imports in.")

class LintCodeParams(BaseModel):
    file_path: str = Field(description="Python file to lint with pylint.")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – Git / VCS
# --------------------------------------------------------------------------- #
class GitStatusParams(BaseModel):
    repo_path: str = Field(default=".", description="Repository path.")

class GitLogParams(BaseModel):
    count: int = Field(default=10, description="Number of commits.")
    repo_path: str = Field(default=".", description="Repository path.")

class GitDiffParams(BaseModel):
    file_path: Optional[str] = Field(default=None, description="Specific file to diff.")
    repo_path: str = Field(default=".", description="Repository path.")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – Documents & data
# --------------------------------------------------------------------------- #
class ReadSpreadsheetParams(BaseModel):
    file_path: str = Field(description="CSV/Excel/TSV/JSON file path.")

class ReadExcelSheetsParams(BaseModel):
    file_path: str = Field(description="Excel workbook path.")

class AnalyzeImageParams(BaseModel):
    file_path: str = Field(description="Image file path.")

class ReadPdfDetailedParams(BaseModel):
    file_path: str = Field(description="PDF file path.")

class ReadYamlParams(BaseModel):
    file_path: str = Field(description="YAML file path.")

class ParseMarkdownParams(BaseModel):
    file_path: str = Field(description="Markdown file path.")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – SSH / Remote
# --------------------------------------------------------------------------- #
class SshExecuteParams(BaseModel):
    host: str = Field(description="Remote host.")
    command: str = Field(description="Command to execute.")
    username: str = Field(description="SSH username.")
    port: int = Field(default=22, description="SSH port.")
    key_path: Optional[str] = Field(default=None, description="Path to SSH key.")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – Docker
# --------------------------------------------------------------------------- #
class DockerPsParams(BaseModel):
    all_containers: bool = Field(default=False, description="Show all containers.")

class DockerImagesParams(BaseModel):
    pass

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – ASCII / TUI
# --------------------------------------------------------------------------- #
class GenerateAsciiBannerParams(BaseModel):
    text: str = Field(description="Text to render.")
    font: str = Field(default="standard", description="Figlet font name.")

class DisplayColorTextParams(BaseModel):
    text: str = Field(description="Text to colour.")
    color: str = Field(default="green", description="Colour name (red, green, blue, etc.).")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – Data serialization
# --------------------------------------------------------------------------- #
class ReadMsgpackParams(BaseModel):
    file_path: str = Field(description="MsgPack file path.")

class ReadJsonFastParams(BaseModel):
    file_path: str = Field(description="JSON file path.")

# --------------------------------------------------------------------------- #
# NEW: Phase 2 – Security
# --------------------------------------------------------------------------- #
class EncryptTextParams(BaseModel):
    plaintext: str = Field(description="Text to encrypt.")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – UI Automation
# --------------------------------------------------------------------------- #
class ScreenInfoParams(BaseModel):
    pass

class CaptureScreenParams(BaseModel):
    pass

class MouseClickParams(BaseModel):
    x: int = Field(description="X coordinate.")
    y: int = Field(description="Y coordinate.")
    button: str = Field(default="left", description="Mouse button (left, right, middle).")

class TypeTextParams(BaseModel):
    text: str = Field(description="Text to type.")

class LocateOnScreenParams(BaseModel):
    image_path: str = Field(description="Path to image file.")

class PynputClickParams(BaseModel):
    x: int = Field(description="X coordinate.")
    y: int = Field(description="Y coordinate.")
    button: str = Field(default="left", description="Mouse button (left, right, middle).")

class PynputTypeParams(BaseModel):
    text: str = Field(description="Text to type.")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – Web Scraping
# --------------------------------------------------------------------------- #
class CloudscrapeParams(BaseModel):
    url: str = Field(description="URL to scrape (Cloudflare bypass).")

class BrowseWebsiteParams(BaseModel):
    url: str = Field(description="URL to browse with JS rendering.")

class MechanicalBrowseParams(BaseModel):
    url: str = Field(description="URL to browse statefully.")

class BrowserAutomateParams(BaseModel):
    url: str = Field(description="URL to open.")
    actions: str = Field(default="", description="Actions per line: click .sel, fill input text, wait N, screenshot.")

class BrowserSeleniumParams(BaseModel):
    url: str = Field(description="URL to open.")
    actions: str = Field(default="", description="Actions per line: click .sel, fill input text, wait N, screenshot.")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – Databases
# --------------------------------------------------------------------------- #
class RedisExecParams(BaseModel):
    command: str = Field(description="Redis command (e.g. 'GET key', 'PING').")
    host: str = Field(default="localhost", description="Redis host.")
    port: int = Field(default=6379, description="Redis port.")
    db: int = Field(default=0, description="Redis DB number.")

class MongodbQueryParams(BaseModel):
    connection_string: str = Field(description="MongoDB connection string.")
    database: str = Field(description="Database name.")
    collection: str = Field(description="Collection name.")
    query: str = Field(default="{}", description="Query JSON.")
    limit: int = Field(default=10, description="Max documents.")

class SqlQueryParams(BaseModel):
    connection_string: str = Field(description="SQLAlchemy connection string.")
    query: str = Field(description="SQL query string.")

class MqttPublishParams(BaseModel):
    topic: str = Field(description="MQTT topic.")
    message: str = Field(description="MQTT message payload.")
    host: str = Field(default="localhost", description="MQTT broker host.")
    port: int = Field(default=1883, description="MQTT broker port.")

class MongodbAsyncQueryParams(BaseModel):
    connection_string: str = Field(description="MongoDB connection string.")
    database: str = Field(description="Database name.")
    collection: str = Field(description="Collection name.")
    query: str = Field(default="{}", description="Query JSON.")
    limit: int = Field(default=10, description="Max documents.")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – IoT
# --------------------------------------------------------------------------- #
class BroadlinkDiscoverParams(BaseModel):
    pass

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – Data Science
# --------------------------------------------------------------------------- #
class AnalyzeDataStatsParams(BaseModel):
    file_path: str = Field(description="CSV/Excel file path.")

class TrainModelParams(BaseModel):
    data_path: str = Field(description="CSV file path.")
    target_column: str = Field(description="Target column name.")
    test_size: float = Field(default=0.2, description="Test split ratio.")

class AnalyzeNetworkParams(BaseModel):
    data: str = Field(default="", description="Graph data (optional).")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – Audio
# --------------------------------------------------------------------------- #
class TextToSpeechParams(BaseModel):
    text: str = Field(description="Text to convert to speech.")
    lang: str = Field(default="id", description="Language code.")
    filename: str = Field(default="", description="Output file path (empty = temp dir).")

class SpeechToTextParams(BaseModel):
    audio_file: str = Field(description="Audio file path to transcribe.")

class PlayAudioParams(BaseModel):
    file_path: str = Field(description="Audio file path.")

class RecordAudioParams(BaseModel):
    duration: int = Field(default=3, description="Recording duration in seconds.")
    samplerate: int = Field(default=44100, description="Sample rate in Hz.")
    filename: str = Field(default="/tmp/recorded.wav", description="Output WAV file path.")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – Scheduling
# --------------------------------------------------------------------------- #
class ScheduleAddParams(BaseModel):
    time_str: str = Field(description="Schedule (e.g. 'every 10 minutes', 'every day').")
    command_text: str = Field(description="Command to run.")

class CrontabAddParams(BaseModel):
    schedule_expr: str = Field(description="Cron expression (e.g. '0 9 * * *').")
    command_text: str = Field(description="Command to run.")

class RpycCallParams(BaseModel):
    host: str = Field(description="RPyC server host.")
    port: int = Field(default=18812, description="RPyC server port.")
    function: str = Field(default="", description="Remote function name.")
    arg: str = Field(default="", description="Argument to pass.")

# --------------------------------------------------------------------------- #
# NEW: Phase 3 – Utilities
# --------------------------------------------------------------------------- #
class GenerateQrcodeParams(BaseModel):
    data: str = Field(description="Data to encode.")
    file_path: str = Field(default="/tmp/qrcode.png", description="Output PNG path.")

class GenerateOtpParams(BaseModel):
    secret: str = Field(default="JBSWY3DPEHPK3PXP", description="Base32 secret.")

class ParquetInfoParams(BaseModel):
    file_path: str = Field(description="Parquet file path.")

class ConfigReadParams(BaseModel):
    file_path: str = Field(description="INI config file path.")
    section: Optional[str] = Field(default=None, description="Specific section.")

# --------------------------------------------------------------------------- #
# NEW: Phase 4 – Additional Libraries (pyproxmox, wakeonlan, ping3, netifaces, scapy, dnspython, humanize, slugify, parse, arrow, croniter, blinker, prometheus, watchdog)
# --------------------------------------------------------------------------- #

class ProxmoxListNodesParams(BaseModel):
    host: str = Field(description="Proxmox host/IP.")
    token_id: str = Field(description="API token ID.")
    token_secret: str = Field(description="API token secret.")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificate.")

class ProxmoxListVmsParams(BaseModel):
    host: str = Field(description="Proxmox host/IP.")
    token_id: str = Field(description="API token ID.")
    token_secret: str = Field(description="API token secret.")
    node: str = Field(default="", description="Node name (empty = all nodes).")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificate.")

class WakeOnLanParams(BaseModel):
    mac_address: str = Field(description="Target MAC address (e.g. '00:11:22:33:44:55').")
    broadcast_ip: str = Field(default="255.255.255.255", description="Broadcast IP.")

class PingHostParams(BaseModel):
    host: str = Field(description="Hostname or IP to ping.")
    count: int = Field(default=4, description="Number of pings.")

class SshScpUploadParams(BaseModel):
    host: str = Field(description="Remote host.")
    username: str = Field(description="SSH username.")
    local_path: str = Field(description="Local file path.")
    remote_path: str = Field(description="Remote destination path.")
    password: str = Field(default="", description="SSH password (optional).")
    port: int = Field(default=22, description="SSH port.")

class SshScpDownloadParams(BaseModel):
    host: str = Field(description="Remote host.")
    username: str = Field(description="SSH username.")
    remote_path: str = Field(description="Remote file path.")
    local_path: str = Field(description="Local destination path.")
    password: str = Field(default="", description="SSH password (optional).")
    port: int = Field(default=22, description="SSH port.")

class PexpectSpawnParams(BaseModel):
    command: str = Field(description="Command to execute.")
    timeout: int = Field(default=30, description="Timeout in seconds.")

class NetworkInterfacesParams(BaseModel):
    pass

class ScapyTracerouteParams(BaseModel):
    target: str = Field(description="Target hostname or IP.")
    max_hops: int = Field(default=15, description="Maximum TTL.")

class DnsLookupParams(BaseModel):
    domain: str = Field(description="Domain to query.")
    record_type: str = Field(default="A", description="DNS record type (A, AAAA, MX, CNAME, etc.).")

class HumanizeValueParams(BaseModel):
    value: str = Field(description="Value to humanize (e.g. '1500000', '2024-01-01', '1048576').")
    type_name: str = Field(default="number", description="Type: number, bytes, or date.")

class SlugifyTextParams(BaseModel):
    text: str = Field(description="Text to convert to slug.")

class ParseStringParams(BaseModel):
    pattern: str = Field(description="Pattern with {} placeholders (e.g. 'Hello {name}!').")
    text: str = Field(description="Text to parse.")

class ArrowTimeParams(BaseModel):
    expression: str = Field(default="now", description="Date expression: 'now', '2024-01-01', 'now - 3 days'.")

class CronNextParams(BaseModel):
    cron_expression: str = Field(description="Cron expression (e.g. '*/5 * * * *').")

class SendSignalParams(BaseModel):
    name: str = Field(description="Signal name.")
    data: str = Field(default="", description="Payload data.")

class WatchDirectoryParams(BaseModel):
    path: str = Field(description="Directory path to watch.")
    pattern: str = Field(default="", description="Optional event filter pattern.")
    timeout: int = Field(default=5, description="Watch duration in seconds.")

class PrometheusMetricsParams(BaseModel):
    pass

# --------------------------------------------------------------------------- #
# NEW: Phase 5 – Vector RAG
# --------------------------------------------------------------------------- #
class AskCodebaseParams(BaseModel):
    question: str = Field(description="Natural-language question about the codebase.")
    top_k: int = Field(default=5, description="Number of relevant chunks to retrieve.")

# --------------------------------------------------------------------------- #
# NEW: Plugin Installer
# --------------------------------------------------------------------------- #
class PluginInstallParams(BaseModel):
    source: str = Field(description="URL, GitHub ref (gh:owner/repo), or registry name.")
    name: str = Field(default="", description="Optional custom plugin name.")

class PluginRemoveParams(BaseModel):
    name: str = Field(description="Plugin name (with or without .py).")

# --------------------------------------------------------------------------- #
# NEW: Phase 6 – Docker Compose
# --------------------------------------------------------------------------- #
class DockerComposeUpParams(BaseModel):
    file_path: str = Field(default="docker-compose.yml", description="Path to compose file.")
    service: str = Field(default="", description="Optional specific service to start.")
    detach: bool = Field(default=True, description="Run containers in background.")

class DockerComposeDownParams(BaseModel):
    file_path: str = Field(default="docker-compose.yml", description="Path to compose file.")
    volumes: bool = Field(default=False, description="Remove named volumes.")

class DockerComposeLogsParams(BaseModel):
    file_path: str = Field(default="docker-compose.yml", description="Path to compose file.")
    service: str = Field(default="", description="Optional specific service logs.")
    tail: int = Field(default=50, description="Number of lines to show.")

class DockerComposePsParams(BaseModel):
    file_path: str = Field(default="docker-compose.yml", description="Path to compose file.")

# --------------------------------------------------------------------------- #
# NEW: Phase 6 – Kubernetes
# --------------------------------------------------------------------------- #
class KubectlGetParams(BaseModel):
    resource: str = Field(description="Resource type (pods, deployments, services, nodes, etc.).")
    namespace: str = Field(default="", description="Kubernetes namespace.")
    output: str = Field(default="", description="Output format (yaml, json, wide).")

class KubectlLogsParams(BaseModel):
    pod: str = Field(description="Pod name.")
    container: str = Field(default="", description="Specific container name.")
    namespace: str = Field(default="", description="Pod namespace.")
    tail: int = Field(default=100, description="Number of lines to show.")
    follow: bool = Field(default=False, description="Follow log output.")

class KubectlDescribeParams(BaseModel):
    resource: str = Field(description="Resource type.")
    name: str = Field(description="Resource name.")
    namespace: str = Field(default="", description="Resource namespace.")

# --------------------------------------------------------------------------- #
# NEW: Phase 6 – Network Port Scanner
# --------------------------------------------------------------------------- #
class ScanPortsParams(BaseModel):
    host: str = Field(description="Target hostname or IP address.")
    ports: str = Field(default="1-1024", description="Port range (e.g. '22,80,443' or '1-1000').")
    timeout: float = Field(default=1.0, description="Timeout per port in seconds.")

# --------------------------------------------------------------------------- #
# NEW: Phase 6 – Log Viewer
# --------------------------------------------------------------------------- #
class TailLogParams(BaseModel):
    file_path: str = Field(description="Path to log file.")
    lines: int = Field(default=50, description="Number of recent lines.")
    follow: bool = Field(default=False, description="Stream new lines in real-time.")

class SearchLogParams(BaseModel):
    file_path: str = Field(description="Path to log file.")
    pattern: str = Field(description="Regex or text pattern to search.")
    context_lines: int = Field(default=3, description="Lines of context around each match.")

# --------------------------------------------------------------------------- #
# NEW: Phase 6 – Vision: Image Understanding (Gemini)
# --------------------------------------------------------------------------- #
class AnalyzeImageAdvancedParams(BaseModel):
    file_path: str = Field(description="Path to image file (jpg, png, gif, webp).")
    prompt: str = Field(default="Describe this image in detail.", description="Question or instruction about the image.")

# --------------------------------------------------------------------------- #
# Master tool registry
# --------------------------------------------------------------------------- #
TOOL_MODELS: dict[str, type[BaseModel]] = {
    # Original
    "scrape_website": ScrapeWebsiteParams, "read_pdf": ReadPdfParams,
    "list_dir": ListDirParams, "view_file": ViewFileParams,
    "write_file": WriteFileParams, "execute_command": ExecuteCommandParams,
    "summarize_youtube": SummarizeYoutubeParams,
    "read_local_video": ReadLocalVideoParams, "web_search": WebSearchParams,
    "get_weather": GetWeatherParams, "get_system_stats": GetSystemStatsParams,
    "patch_file": PatchFileParams,
    # Phase 1
    "analyze_code": AnalyzeCodeParams, "search_files": SearchFilesParams,
    "count_tokens": CountTokensParams, "resolve_jsonref": ResolveJsonRefParams,
    "web_fetch_async": WebFetchAsyncParams, "get_app_paths": GetAppPathsParams,
    # Phase 2 – Code
    "analyze_python": AnalyzePythonParams,
    "calculate_complexity": CalculateComplexityParams,
    "format_code": FormatCodeParams, "sort_imports": SortImportsParams,
    "lint_code": LintCodeParams,
    # Phase 2 – Git
    "git_status": GitStatusParams, "git_log": GitLogParams, "git_diff": GitDiffParams,
    # Phase 2 – Documents
    "read_spreadsheet": ReadSpreadsheetParams,
    "read_excel_sheets": ReadExcelSheetsParams,
    "analyze_image": AnalyzeImageParams,
    "read_pdf_detailed": ReadPdfDetailedParams,
    "read_yaml": ReadYamlParams, "parse_markdown": ParseMarkdownParams,
    # Phase 2 – SSH / Docker
    "ssh_execute": SshExecuteParams,
    "docker_ps": DockerPsParams, "docker_images": DockerImagesParams,
    # Phase 2 – ASCII / Data
    "generate_ascii_banner": GenerateAsciiBannerParams,
    "display_color_text": DisplayColorTextParams,
    "read_msgpack": ReadMsgpackParams, "read_json_fast": ReadJsonFastParams,
    "encrypt_text": EncryptTextParams,
    # Phase 3 – UI Automation
    "screen_info": ScreenInfoParams,
    "capture_screen": CaptureScreenParams,
    "mouse_click": MouseClickParams,
    "type_text": TypeTextParams,
    "locate_on_screen": LocateOnScreenParams,
    "pynput_click": PynputClickParams,
    "pynput_type": PynputTypeParams,
    # Phase 3 – Web Scraping
    "cloudscrape": CloudscrapeParams,
    "browse_website": BrowseWebsiteParams,
    "mechanical_browse": MechanicalBrowseParams,
    "browser_automate": BrowserAutomateParams,
    "browser_selenium": BrowserSeleniumParams,
    # Phase 3 – Databases
    "redis_exec": RedisExecParams,
    "mongodb_query": MongodbQueryParams,
    "sql_query": SqlQueryParams,
    "mqtt_publish": MqttPublishParams,
    "mongodb_async_query": MongodbAsyncQueryParams,
    # Phase 3 – IoT
    "broadlink_discover": BroadlinkDiscoverParams,
    # Phase 3 – Data Science
    "analyze_data_stats": AnalyzeDataStatsParams,
    "train_model": TrainModelParams,
    "analyze_network": AnalyzeNetworkParams,
    # Phase 3 – Audio
    "text_to_speech": TextToSpeechParams,
    "speech_to_text": SpeechToTextParams,
    "play_audio": PlayAudioParams,
    "record_audio": RecordAudioParams,
    # Phase 3 – Scheduling
    "schedule_add": ScheduleAddParams,
    "crontab_add": CrontabAddParams,
    "rpyc_call": RpycCallParams,
    # Phase 3 – Utilities
    "generate_qrcode": GenerateQrcodeParams,
    "generate_otp": GenerateOtpParams,
    "parquet_info": ParquetInfoParams,
    "config_read": ConfigReadParams,
    # Phase 4 – Additional Libraries
    "proxmox_list_nodes": ProxmoxListNodesParams,
    "proxmox_list_vms": ProxmoxListVmsParams,
    "wake_on_lan": WakeOnLanParams,
    "ping_host": PingHostParams,
    "ssh_scp_upload": SshScpUploadParams,
    "ssh_scp_download": SshScpDownloadParams,
    "pexpect_spawn": PexpectSpawnParams,
    "network_interfaces": NetworkInterfacesParams,
    "scapy_traceroute": ScapyTracerouteParams,
    "dns_lookup": DnsLookupParams,
    "humanize_value": HumanizeValueParams,
    "slugify_text": SlugifyTextParams,
    "parse_string": ParseStringParams,
    "arrow_time": ArrowTimeParams,
    "cron_next": CronNextParams,
    "send_signal": SendSignalParams,
    "watch_directory": WatchDirectoryParams,
    "prometheus_metrics": PrometheusMetricsParams,
    # Phase 5 – Vector RAG
    "ask_codebase": AskCodebaseParams,
    # Plugin management
    "plugin_install": PluginInstallParams,
    "plugin_remove": PluginRemoveParams,
    # Phase 6 – Docker Compose
    "docker_compose_up": DockerComposeUpParams,
    "docker_compose_down": DockerComposeDownParams,
    "docker_compose_logs": DockerComposeLogsParams,
    "docker_compose_ps": DockerComposePsParams,
    # Phase 6 – Kubernetes
    "kubectl_get": KubectlGetParams,
    "kubectl_logs": KubectlLogsParams,
    "kubectl_describe": KubectlDescribeParams,
    # Phase 6 – Network Port Scanner
    "scan_ports": ScanPortsParams,
    # Phase 6 – Log Viewer
    "tail_log_file": TailLogParams,
    "search_log_file": SearchLogParams,
    # Phase 6 – Vision Image Understanding
    "analyze_image_advanced": AnalyzeImageAdvancedParams,
}

# --------------------------------------------------------------------------- #
# Validation & manifest helpers
# --------------------------------------------------------------------------- #

def validate_tool_params(name: str, raw_params: dict) -> tuple[Optional[BaseModel], Optional[str]]:
    from pydantic import ValidationError

    if not isinstance(raw_params, dict):
        return None, f"Error: invalid parameters for '{name}' -> payload must be an object."

    payload = raw_params.copy()
    for key in ("parameters", "arguments", "args"):
        if key in payload and isinstance(payload[key], dict):
            payload = payload[key]
            break

    # Some models emit the tool name and parameters in a wrapped object rather than
    # the flat schema the executor expects. Unwrap those common shapes before validation.
    if "name" in payload and isinstance(payload["name"], str) and not name:
        name = payload["name"]
    if "tool" in payload and isinstance(payload["tool"], str) and not name:
        name = payload["tool"]
    if "tool_name" in payload and isinstance(payload["tool_name"], str) and not name:
        name = payload["tool_name"]

    model_cls = TOOL_MODELS.get(name)
    if model_cls is None:
        return None, f"Error: Tool '{name}' not recognized."
    try:
        return model_cls.model_validate(payload or {}), None
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        return None, f"Error: invalid parameters for '{name}' -> {details}"


def tool_manifest() -> list[dict]:
    manifest = []
    for name, model_cls in TOOL_MODELS.items():
        manifest.append({"name": name, "schema": model_cls.model_json_schema()})
    return manifest
