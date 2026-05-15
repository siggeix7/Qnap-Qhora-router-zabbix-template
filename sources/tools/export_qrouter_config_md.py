#!/usr/bin/env python3
"""Export a QNAP QuRouter configuration snapshot to Markdown.

The script prompts for router URL/IP, username and password, performs the same
local-account login used by the QuRouter web UI, then collects read-only GET API
responses and writes a Markdown report plus a redacted JSON companion file.

The output is intended as documentation for change tracking and future manual
reconfiguration. It is not an official restorable backup.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DEFAULT_TIMEOUT = 8.0
DEFAULT_DELAY = 0.2


@dataclass(frozen=True)
class ApiEndpoint:
    name: str
    title: str
    path: str
    group: str
    description: str = ""


KNOWN_ENDPOINTS = [
    ApiEndpoint("basic_info", "Basic system information", "/miro/api/v1/debugmode/information", "System"),
    ApiEndpoint("cloud_service", "Cloud service", "/miro/api/v1/cloud_service", "System"),
    ApiEndpoint("connection_status", "Connection status", "/miro/api/v1/connection_status", "Network"),
    ApiEndpoint("deployment_progress", "QuWAN deployment progress", "/miro/api/v1/quwan/deployment_progress", "QuWAN"),
    ApiEndpoint("quwan_status", "QuWAN status", "/miro/api/v1/quwan/status", "QuWAN"),
    ApiEndpoint("machine_info", "Machine information", "/miro/api/v2/system/machine_info", "System"),
    ApiEndpoint("network_status", "Internet status", "/miro/api/v2/network_status", "Network"),
    ApiEndpoint("hardware_status", "Hardware status", "/miro/api/v2/system/hardware_status", "System"),
    ApiEndpoint("ports_config", "Network ports configuration", "/miro/api/v2/network/ports", "Ports"),
    ApiEndpoint("ports_status", "Network ports status", "/miro/api/v2/network/ports_status", "Ports"),
    ApiEndpoint("port_statistic", "Switch port statistics", "/miro/api/v2/debugmode/port_statistic", "Ports"),
    ApiEndpoint("wan_status", "WAN status", "/miro/api/v2/network/wan/status", "WAN"),
    ApiEndpoint("clients", "Known clients", "/miro/api/v2/clients", "Clients"),
    ApiEndpoint("firmware", "Firmware", "/miro/api/v2/firmware", "System"),
    ApiEndpoint("load_balancing_status", "Load balancing status", "/miro/api/v2/load_balancing_status", "WAN"),
    ApiEndpoint("ddns_info", "DDNS information", "/miro/api/v2/ddns/info", "Network"),
    ApiEndpoint("wireless_status", "Wireless status", "/miro/api/v2/wireless/status", "Wireless"),
    ApiEndpoint("wireless_band_status", "Wireless band status", "/miro/api/v2/wireless/band/status", "Wireless"),
    ApiEndpoint("vap_status", "Wireless VAP status", "/miro/api/v2/wireless/vap/status", "Wireless"),
    ApiEndpoint("eventlogs", "Event logs", "/miro/api/v2/eventlogs", "Logs"),
]


KNOWN_UNSTABLE_PATHS = {
    "/miro/api/v1/laninfo",
}

DANGEROUS_PATH_WORDS = {
    "activate",
    "apply",
    "backup",
    "connect",
    "delete",
    "disconnect",
    "factory",
    "format",
    "import",
    "logout",
    "reboot",
    "remove",
    "reset",
    "restart",
    "restore",
    "shutdown",
    "start",
    "stop",
    "upgrade",
}

SENSITIVE_KEY_CONTAINS = (
    "password",
    "passwd",
    "passphrase",
    "token",
    "secret",
    "session",
    "credential",
    "authorization",
    "cookie",
    "privatekey",
    "sharedkey",
    "encryptionkey",
    "apikey",
    "accesskey",
    "refreshtoken",
)
SENSITIVE_KEY_EXACT = {"key", "psk", "pwd", "sid"}


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        raise ValueError("router URL/IP is required")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if not parsed.hostname:
        raise ValueError(f"invalid router URL/IP: {value}")
    return value


def prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def prompt_bool(label: str, default: bool) -> bool:
    suffix = "[S/n]" if default else "[s/N]"
    while True:
        value = input(f"{label} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"s", "si", "y", "yes", "true", "1"}:
            return True
        if value in {"n", "no", "false", "0"}:
            return False
        print("Rispondi con 's' oppure 'n'.")


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    verify_tls: bool = False,
) -> tuple[int | None, dict[str, str], bytes, Any | None, str | None]:
    ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "qrouter-config-export/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, raw, decode_json(raw), None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, raw, decode_json(raw), None
    except Exception as exc:
        return None, {}, b"", None, f"{type(exc).__name__}: {exc}"


def decode_json(raw: bytes) -> Any | None:
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def login(
    base_url: str,
    username: str,
    password: str,
    force: bool,
    timeout: float,
    verify_tls: bool,
) -> dict[str, Any]:
    encoded_password = base64.b64encode(password.encode("utf-8")).decode("ascii")
    payload = {
        "username": username,
        "password": encoded_password,
        "force": force,
        "remember_me": False,
        "qid_login": False,
    }
    status, headers, raw, parsed, error = request_json(
        "POST",
        base_url + "/miro/api/v1/login",
        payload=payload,
        timeout=timeout,
        verify_tls=verify_tls,
    )
    result = parsed.get("result") if isinstance(parsed, dict) else None
    token = result.get("access_token") if isinstance(result, dict) else None
    return {
        "status": status,
        "error": error,
        "error_code": parsed.get("error_code") if isinstance(parsed, dict) else None,
        "error_message": parsed.get("error_message") if isinstance(parsed, dict) else None,
        "had_session": result.get("had_session") if isinstance(result, dict) else None,
        "has_access_token": bool(token),
        "access_token": token,
        "body_bytes": len(raw),
        "content_type": headers.get("content-type", ""),
    }


def normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_key(key: Any) -> bool:
    norm = normalized_key(key)
    if norm in SENSITIVE_KEY_EXACT:
        return True
    if norm.endswith("key") and norm not in {"keyid", "keyindex", "monkey"}:
        return True
    return any(part in norm for part in SENSITIVE_KEY_CONTAINS)


def redact(value: Any, parent_key: Any | None = None) -> Any:
    if parent_key is not None and is_sensitive_key(parent_key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(key): redact(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, parent_key) for item in value]
    return value


def is_safe_config_get_path(path: str) -> bool:
    if path in KNOWN_UNSTABLE_PATHS:
        return False
    if "${" in path or "{" in path or "}" in path:
        return False
    if not re.match(r"^/miro/api/v[12]/[a-zA-Z0-9_/-]+$", path):
        return False
    parts = {part.lower() for part in path.split("/") if part}
    return not bool(parts & DANGEROUS_PATH_WORDS)


def slug_from_path(path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    slug = re.sub(r"^miro_api_v[12]_", "", slug)
    return slug or "endpoint"


def discover_extra_endpoints(base_url: str) -> tuple[list[ApiEndpoint], dict[str, Any]]:
    try:
        import discover_qnap_api as discovery
    except Exception as exc:
        return [], {"error": f"could not import discover_qnap_api: {exc}"}

    stats: dict[str, Any] = {"downloaded_assets": 0, "discovered_endpoints": 0, "discovered_operations": 0, "selected_extra": 0}
    downloaded = discovery.crawl_assets(base_url)
    endpoints = discovery.extract_endpoints_from_js()
    operations = discovery.extract_operations(endpoints)
    stats.update(
        {
            "downloaded_assets": len(downloaded),
            "discovered_endpoints": len(endpoints),
            "discovered_operations": len(operations),
        }
    )

    get_refs = {(op.version, op.key) for op in operations if op.method == "GET" and op.version and op.key}
    selected: list[ApiEndpoint] = []
    for endpoint in endpoints:
        if endpoint.path == "/miro/api/v1/login" or not is_safe_config_get_path(endpoint.path):
            continue
        if get_refs and (endpoint.version, endpoint.key) not in get_refs:
            continue
        selected.append(
            ApiEndpoint(
                name=slug_from_path(endpoint.path),
                title=f"Discovered: {endpoint.key}",
                path=endpoint.path,
                group="Discovered",
                description=f"Discovered from frontend asset {endpoint.source}",
            )
        )
    stats["selected_extra"] = len(selected)
    return selected, stats


def merge_endpoints(known: list[ApiEndpoint], extra: list[ApiEndpoint]) -> list[ApiEndpoint]:
    merged: list[ApiEndpoint] = []
    seen: set[str] = set()
    for endpoint in known + extra:
        if endpoint.path in seen:
            continue
        seen.add(endpoint.path)
        merged.append(endpoint)
    return merged


def collect_endpoint(
    base_url: str,
    token: str,
    endpoint: ApiEndpoint,
    timeout: float,
    verify_tls: bool,
) -> dict[str, Any]:
    start = time.time()
    status, headers, raw, parsed, error = request_json(
        "GET",
        base_url + endpoint.path,
        token=token,
        timeout=timeout,
        verify_tls=verify_tls,
    )
    entry: dict[str, Any] = {
        "name": endpoint.name,
        "title": endpoint.title,
        "path": endpoint.path,
        "group": endpoint.group,
        "description": endpoint.description,
        "status": status,
        "error": error,
        "content_type": headers.get("content-type", ""),
        "body_bytes": len(raw),
        "elapsed_ms": int((time.time() - start) * 1000),
    }
    if isinstance(parsed, dict):
        safe_response = redact(parsed)
        entry["error_code"] = parsed.get("error_code")
        entry["error_message"] = parsed.get("error_message")
        entry["response"] = safe_response
        if isinstance(safe_response, dict) and "result" in safe_response:
            entry["result"] = safe_response["result"]
    elif parsed is not None:
        entry["response"] = redact(parsed)
    elif raw:
        entry["body_preview"] = raw.decode("utf-8", errors="replace")[:1000]
    return entry


def collect_all(
    base_url: str,
    token: str,
    endpoints: list[ApiEndpoint],
    timeout: float,
    delay: float,
    verify_tls: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, endpoint in enumerate(endpoints, start=1):
        print(f"[{index}/{len(endpoints)}] GET {endpoint.path}", flush=True)
        results.append(collect_endpoint(base_url, token, endpoint, timeout, verify_tls))
        if delay > 0 and index < len(endpoints):
            time.sleep(delay)
    return results


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def compact_value(value: Any, max_len: int = 220) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif is_scalar(value):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = text.replace("\n", "<br>").replace("\r", "")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def md_escape(value: Any) -> str:
    text = compact_value(value)
    return text.replace("|", "\\|")


def flatten_scalars(value: Any, prefix: str = "", depth: int = 0, max_depth: int = 3) -> list[tuple[str, Any]]:
    if is_scalar(value):
        return [(prefix or "value", value)]
    if depth >= max_depth:
        return []
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(flatten_scalars(item, child_prefix, depth + 1, max_depth))
    elif isinstance(value, list) and all(is_scalar(item) for item in value):
        rows.append((prefix or "values", ", ".join(compact_value(item) for item in value)))
    return rows


def render_kv_table(rows: list[tuple[str, Any]], max_rows: int) -> list[str]:
    if not rows:
        return []
    lines = ["| Campo | Valore |", "| --- | --- |"]
    for key, value in rows[:max_rows]:
        lines.append(f"| `{md_escape(key)}` | {md_escape(value)} |")
    if len(rows) > max_rows:
        lines.append(f"| `_truncated` | {len(rows) - max_rows} altri valori nel JSON completo |")
    return lines


def scalar_columns(items: list[dict[str, Any]], max_columns: int = 12) -> list[str]:
    columns: list[str] = []
    for item in items:
        for key, value in item.items():
            if key not in columns and (is_scalar(value) or isinstance(value, (list, dict))):
                columns.append(str(key))
            if len(columns) >= max_columns:
                return columns
    return columns


def render_list_table(items: list[Any], max_rows: int) -> list[str]:
    if not items:
        return ["_Lista vuota._"]
    if all(isinstance(item, dict) for item in items):
        dict_items = [item for item in items if isinstance(item, dict)]
        columns = scalar_columns(dict_items)
        if not columns:
            return []
        lines = ["| " + " | ".join(f"`{md_escape(col)}`" for col in columns) + " |"]
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for item in dict_items[:max_rows]:
            lines.append("| " + " | ".join(md_escape(item.get(col, "")) for col in columns) + " |")
        if len(items) > max_rows:
            row = [md_escape(f"... {len(items) - max_rows} altre righe nel JSON completo")] + [""] * (len(columns) - 1)
            lines.append("| " + " | ".join(row) + " |")
        return lines
    if all(is_scalar(item) for item in items):
        return render_kv_table([(str(index), item) for index, item in enumerate(items)], max_rows)
    return []


def render_result_summary(result: Any, max_rows: int) -> list[str]:
    lines: list[str] = []
    if isinstance(result, dict):
        scalar_rows = flatten_scalars(result, max_depth=2)
        if scalar_rows:
            lines.extend(["", "Valori principali:", ""])
            lines.extend(render_kv_table(scalar_rows, max_rows))
        for key, item in result.items():
            if isinstance(item, list):
                table = render_list_table(item, max_rows)
                if table:
                    lines.extend(["", f"Lista `{key}`:", ""])
                    lines.extend(table)
            elif isinstance(item, dict):
                nested_rows = flatten_scalars(item, max_depth=1)
                if nested_rows and not all(row[0].startswith(f"{key}.") for row in scalar_rows):
                    lines.extend(["", f"Oggetto `{key}`:", ""])
                    lines.extend(render_kv_table(nested_rows, max_rows))
    elif isinstance(result, list):
        table = render_list_table(result, max_rows)
        if table:
            lines.extend(["", "Valori:", ""])
            lines.extend(table)
    elif result is not None:
        lines.extend(["", f"Valore: `{md_escape(result)}`"])
    return lines


def get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def first_available(collected_by_name: dict[str, dict[str, Any]], candidates: list[tuple[str, str]]) -> Any:
    for endpoint_name, path in candidates:
        endpoint = collected_by_name.get(endpoint_name)
        if not endpoint:
            continue
        value = get_path(endpoint.get("response"), path)
        if value not in (None, ""):
            return value
    return None


def render_high_level_summary(collected: list[dict[str, Any]]) -> list[str]:
    by_name = {item.get("name"): item for item in collected}
    rows = [
        (
            "Nome dispositivo",
            first_available(by_name, [("machine_info", "result.deviceName"), ("basic_info", "result.device_name")]),
        ),
        ("Modello", first_available(by_name, [("machine_info", "result.model"), ("basic_info", "result.model")]),),
        ("Firmware", first_available(by_name, [("firmware", "result.currentVersion"), ("basic_info", "result.firmware_version")]),),
        ("Uptime", first_available(by_name, [("hardware_status", "result.uptime"), ("basic_info", "result.uptime")]),),
        ("Internet connesso", first_available(by_name, [("network_status", "result.isInternetConnected")]),),
        ("Client noti", list_length(by_name.get("clients", {}).get("result")),),
        ("Porte configurate", list_length(by_name.get("ports_config", {}).get("result")),),
        ("WAN", list_length(by_name.get("wan_status", {}).get("result")),),
    ]
    rows = [(key, value) for key, value in rows if value not in (None, "")]
    if not rows:
        return []
    return ["## Sintesi", "", *render_kv_table(rows, max_rows=50), ""]


def list_length(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("clients", "data", "items", "list", "ports", "wan"):
            item = value.get(key)
            if isinstance(item, list):
                return len(item)
    return None


def render_markdown(
    base_url: str,
    login_result: dict[str, Any],
    collected: list[dict[str, Any]],
    discovery_stats: dict[str, Any] | None,
    include_raw: bool,
    max_rows: int,
) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %z")
    ok = [item for item in collected if item.get("status") == 200 and item.get("error_code") in (0, None) and not item.get("error")]
    failed = [item for item in collected if item not in ok]
    safe_login = {key: value for key, value in login_result.items() if key != "access_token"}

    lines = [
        "# QuRouter Configuration Export",
        "",
        f"Generated: {timestamp}",
        "",
        "## Scope",
        "",
        "This report was generated from read-only QuRouter API GET endpoints after one login POST.",
        "It is a documentation snapshot for change tracking and manual reconfiguration, not an official restorable backup.",
        "The file can contain private network data. Do not publish it without reviewing it first.",
        "",
        "## Collection Summary",
        "",
        "| Campo | Valore |",
        "| --- | --- |",
        f"| Router URL | `{md_escape(base_url)}` |",
        f"| Login HTTP status | {md_escape(safe_login.get('status'))} |",
        f"| Login error_code | {md_escape(safe_login.get('error_code'))} |",
        f"| Login had_session | {md_escape(safe_login.get('had_session'))} |",
        f"| Endpoints collected | {len(collected)} |",
        f"| Endpoints successful | {len(ok)} |",
        f"| Endpoints failed | {len(failed)} |",
        "",
    ]
    if discovery_stats:
        lines.extend(["## Extended Discovery", ""])
        lines.extend(render_kv_table(sorted(discovery_stats.items()), max_rows=50))
        lines.append("")

    lines.extend(render_high_level_summary(collected))

    if failed:
        lines.extend(["## Failed Or Partial Endpoints", ""])
        lines.extend(render_kv_table([(item.get("path"), item.get("error") or item.get("error_message") or item.get("status")) for item in failed], max_rows=200))
        lines.append("")

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in collected:
        groups.setdefault(str(item.get("group") or "Other"), []).append(item)

    for group in sorted(groups):
        lines.extend([f"## {group}", ""])
        for item in groups[group]:
            lines.extend(render_endpoint_markdown(item, include_raw=include_raw, max_rows=max_rows))

    return "\n".join(lines).rstrip() + "\n"


def render_endpoint_markdown(item: dict[str, Any], include_raw: bool, max_rows: int) -> list[str]:
    lines = [
        f"### {item.get('title') or item.get('name')}",
        "",
        "| Campo | Valore |",
        "| --- | --- |",
        f"| API | `{md_escape(item.get('path'))}` |",
        f"| HTTP status | {md_escape(item.get('status'))} |",
        f"| error_code | {md_escape(item.get('error_code'))} |",
        f"| body bytes | {md_escape(item.get('body_bytes'))} |",
        f"| elapsed ms | {md_escape(item.get('elapsed_ms'))} |",
    ]
    if item.get("description"):
        lines.append(f"| Note | {md_escape(item.get('description'))} |")
    if item.get("error"):
        lines.append(f"| Transport error | {md_escape(item.get('error'))} |")
    if item.get("error_message"):
        lines.append(f"| API message | {md_escape(item.get('error_message'))} |")

    result = item.get("result") if "result" in item else item.get("response")
    lines.extend(render_result_summary(result, max_rows=max_rows))

    if item.get("body_preview"):
        lines.extend(["", "Body preview:", "", "```text", str(item.get("body_preview")), "```"])
    if include_raw and "response" in item:
        lines.extend(["", "Raw redacted JSON:", "", "```json"])
        lines.append(json.dumps(item["response"], ensure_ascii=False, indent=2, sort_keys=True))
        lines.extend(["```", ""])
    else:
        lines.append("")
    return lines


def safe_output_prefix(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "router"
    host = re.sub(r"[^A-Za-z0-9_.-]+", "_", host)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"qrouter_config_{host}_{stamp}"


def write_outputs(
    output_dir: Path,
    prefix: str,
    base_url: str,
    login_result: dict[str, Any],
    collected: list[dict[str, Any]],
    discovery_stats: dict[str, Any] | None,
    include_raw: bool,
    max_rows: int,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{prefix}.md"
    json_path = output_dir / f"{prefix}.json"
    safe_login = {key: value for key, value in login_result.items() if key != "access_token"}
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "base_url": base_url,
        "login": safe_login,
        "discovery": discovery_stats,
        "endpoints": collected,
    }
    md_path.write_text(
        render_markdown(base_url, safe_login, collected, discovery_stats, include_raw=include_raw, max_rows=max_rows),
        encoding="utf-8",
    )
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Router URL or IP. IP values are normalized to https://<IP>.")
    parser.add_argument("--username", help="Local QuRouter username.")
    parser.add_argument("--password", help="Local QuRouter password. Prefer interactive prompt to avoid shell history.")
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS, help="Directory for Markdown and JSON output.")
    parser.add_argument("--output-prefix", help="Output file prefix. Defaults to qrouter_config_<host>_<timestamp>.")
    parser.add_argument("--extended-discovery", dest="extended_discovery", action="store_true", default=None, help="Download frontend assets and probe extra discovered safe GET endpoints.")
    parser.add_argument("--no-extended-discovery", dest="extended_discovery", action="store_false", help="Only collect the curated endpoint set.")
    parser.add_argument("--force-login", dest="force_login", action="store_true", default=None, help="Force login if another session is active.")
    parser.add_argument("--no-force-login", dest="force_login", action="store_false", help="Do not force login if another session is active.")
    parser.add_argument("--verify-tls", action="store_true", help="Verify router TLS certificate instead of accepting self-signed certificates.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds.")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between GET requests in seconds.")
    parser.add_argument("--max-table-rows", type=int, default=100, help="Maximum rows per Markdown summary table.")
    parser.add_argument("--no-raw-json", action="store_true", help="Do not include raw redacted JSON blocks in the Markdown file.")
    parser.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting for missing values.")
    return parser.parse_args()


def resolve_runtime_options(args: argparse.Namespace) -> tuple[str, str, str, bool, bool]:
    interactive = not args.non_interactive and sys.stdin.isatty()
    base_url = args.base_url or (prompt_text("Router IP o URL", "https://192.168.1.1") if interactive else "")
    username = args.username or (prompt_text("Username") if interactive else "")
    password = args.password or (getpass.getpass("Password: ") if interactive else "")
    if not base_url or not username or not password:
        raise ValueError("base URL, username and password are required")

    force_login = args.force_login
    if force_login is None:
        force_login = prompt_bool("Forzare il login se esiste gia una sessione web?", True) if interactive else True

    extended_discovery = args.extended_discovery
    if extended_discovery is None:
        extended_discovery = prompt_bool("Eseguire discovery estesa degli endpoint dal frontend?", True) if interactive else False

    return normalize_base_url(base_url), username, password, bool(force_login), bool(extended_discovery)


def main() -> int:
    args = parse_args()
    try:
        base_url, username, password, force_login, extended_discovery = resolve_runtime_options(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Login QuRouter...", flush=True)
    login_result = login(base_url, username, password, force=force_login, timeout=args.timeout, verify_tls=args.verify_tls)
    print(
        "login_status={status} error_code={error_code} has_access_token={has_access_token} had_session={had_session}".format(
            **{key: login_result.get(key) for key in ("status", "error_code", "has_access_token", "had_session")}
        ),
        flush=True,
    )
    token = login_result.get("access_token")
    if not token:
        if login_result.get("had_session") and not force_login:
            print("Il router segnala una sessione attiva. Riesegui con --force-login oppure rispondi 's' al prompt.", file=sys.stderr)
        elif login_result.get("error"):
            print(f"Login fallito: {login_result['error']}", file=sys.stderr)
        else:
            print(f"Login fallito: {login_result.get('error_message') or 'token assente'}", file=sys.stderr)
        return 2

    discovery_stats: dict[str, Any] | None = None
    extra_endpoints: list[ApiEndpoint] = []
    if extended_discovery:
        print("Discovery estesa frontend/API...", flush=True)
        extra_endpoints, discovery_stats = discover_extra_endpoints(base_url)
        if discovery_stats.get("error"):
            print(f"warning: {discovery_stats['error']}", file=sys.stderr)
        else:
            print(
                "discovered_endpoints={discovered_endpoints} selected_extra={selected_extra}".format(**discovery_stats),
                flush=True,
            )

    endpoints = merge_endpoints(KNOWN_ENDPOINTS, extra_endpoints)
    print(f"Raccolta endpoint: {len(endpoints)}", flush=True)
    collected = collect_all(
        base_url,
        token,
        endpoints,
        timeout=args.timeout,
        delay=args.delay,
        verify_tls=args.verify_tls,
    )

    prefix = args.output_prefix or safe_output_prefix(base_url)
    md_path, json_path = write_outputs(
        args.output_dir,
        prefix,
        base_url,
        login_result,
        collected,
        discovery_stats,
        include_raw=not args.no_raw_json,
        max_rows=args.max_table_rows,
    )
    ok = sum(1 for item in collected if item.get("status") == 200 and item.get("error_code") in (0, None) and not item.get("error"))
    failed = len(collected) - ok
    print(f"success={ok} failed={failed}", flush=True)
    print(f"markdown={md_path}", flush=True)
    print(f"json={json_path}", flush=True)
    print("Nota: i file generati possono contenere dati sensibili della rete. Non pubblicarli senza controllarli.", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
