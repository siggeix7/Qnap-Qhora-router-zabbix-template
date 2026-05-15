#!/usr/bin/env python3
"""Export a QNAP QuRouter configuration snapshot to Markdown.

The script prompts for router URL/IP, username, password and output directory,
performs the same local-account login used by the QuRouter web UI, then collects
read-only GET API responses and writes a structured Markdown report plus a full
JSON companion file.

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
DEFAULT_OUTPUT_DIR_TEXT = "~/qrouter_exports"
DEFAULT_OUTPUT_DIR = Path(DEFAULT_OUTPUT_DIR_TEXT).expanduser()
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
    ApiEndpoint("operation_setting", "Operation mode", "/miro/api/v2/system/operation_setting", "System"),
    ApiEndpoint("region_setting", "Region setting", "/miro/api/v2/system/region", "System"),
    ApiEndpoint("device_name", "Device name", "/miro/api/v2/system/device_name", "System"),
    ApiEndpoint("network_status", "Internet status", "/miro/api/v2/network_status", "Network"),
    ApiEndpoint("hardware_status", "Hardware status", "/miro/api/v2/system/hardware_status", "System"),
    ApiEndpoint("network_profiles", "Network profiles", "/miro/api/v2/network/profiles", "Network"),
    ApiEndpoint("ports_config", "Network ports configuration", "/miro/api/v2/network/ports", "Ports"),
    ApiEndpoint("ports_status", "Network ports status", "/miro/api/v2/network/ports_status", "Ports"),
    ApiEndpoint("ports_mac_addr", "Network ports MAC addresses", "/miro/api/v2/network/ports_mac_addr", "Ports"),
    ApiEndpoint("lan_config", "LAN configuration", "/miro/api/v2/network/lan", "Network"),
    ApiEndpoint("vlan_interfaces", "VLAN interfaces", "/miro/api/v2/network/vlanif", "Network"),
    ApiEndpoint("vlan_status", "VLAN interface status", "/miro/api/v2/network/vlanif_status", "Network"),
    ApiEndpoint("bridges", "Bridge interfaces", "/miro/api/v2/network/bridge", "Network"),
    ApiEndpoint("bridge_status", "Bridge status", "/miro/api/v2/network/bridge_status", "Network"),
    ApiEndpoint("network_settings", "Network settings", "/miro/api/v2/network/settings", "Network"),
    ApiEndpoint("dhcp_clients", "DHCP clients and reservations", "/miro/api/v2/network/dhcp_client", "DHCP"),
    ApiEndpoint("available_lan_interfaces", "Available LAN interfaces", "/miro/api/v2/network/available_lan_interfaces", "Network"),
    ApiEndpoint("available_wan_interfaces", "Available WAN interfaces", "/miro/api/v2/network/available_wan_interfaces", "Network"),
    ApiEndpoint("port_statistic", "Switch port statistics", "/miro/api/v2/debugmode/port_statistic", "Ports"),
    ApiEndpoint("wan_status", "WAN status", "/miro/api/v2/network/wan/status", "WAN"),
    ApiEndpoint("clients", "Known clients", "/miro/api/v2/clients", "Clients"),
    ApiEndpoint("firmware", "Firmware", "/miro/api/v2/firmware", "System"),
    ApiEndpoint("firmware_schedule", "Firmware schedule", "/miro/api/v2/firmware/schedule", "System"),
    ApiEndpoint("load_balancing_status", "Load balancing status", "/miro/api/v2/load_balancing_status", "WAN"),
    ApiEndpoint("ddns_info", "DDNS information", "/miro/api/v2/ddns/info", "Network"),
    ApiEndpoint("ddns_setting", "DDNS setting", "/miro/api/v2/ddns/setting", "Network"),
    ApiEndpoint("ddns_wan_status", "DDNS WAN status", "/miro/api/v2/ddns/wan_status", "Network"),
    ApiEndpoint("nat_alg", "NAT ALG", "/miro/api/v2/nat/alg", "NAT"),
    ApiEndpoint("nat_dmz", "NAT DMZ", "/miro/api/v2/nat/dmz", "NAT"),
    ApiEndpoint("nat_port_forwarding", "NAT port forwarding", "/miro/api/v2/nat/port_forwarding", "NAT"),
    ApiEndpoint("routing_ipv4", "IPv4 static routes", "/miro/api/v2/routing/ipv4", "Routing"),
    ApiEndpoint("routing_ipv6", "IPv6 static routes", "/miro/api/v2/routing/ipv6", "Routing"),
    ApiEndpoint("policy_route", "Policy routes", "/miro/api/v2/policy-route", "Routing"),
    ApiEndpoint("access_setting", "Access setting", "/miro/api/v2/access_setting", "Security"),
    ApiEndpoint("blocked_clients", "Blocked clients", "/miro/api/v2/blocklist", "Security"),
    ApiEndpoint("service_ports", "Custom service ports", "/miro/api/v2/service_ports/custom", "Security"),
    ApiEndpoint("certificate_info", "Certificate information", "/miro/api/v2/certificate/info", "Security"),
    ApiEndpoint("wireless_status", "Wireless status", "/miro/api/v2/wireless/status", "Wireless"),
    ApiEndpoint("wireless_profile", "Wireless profile", "/miro/api/v2/wireless/profile", "Wireless"),
    ApiEndpoint("wireless_band", "Wireless band settings", "/miro/api/v2/wireless/band/setting", "Wireless"),
    ApiEndpoint("wireless_band_status", "Wireless band status", "/miro/api/v2/wireless/band/status", "Wireless"),
    ApiEndpoint("vap_setting", "Wireless VAP settings", "/miro/api/v2/wireless/vap/setting", "Wireless"),
    ApiEndpoint("vap_status", "Wireless VAP status", "/miro/api/v2/wireless/vap/status", "Wireless"),
    ApiEndpoint("wps_setting", "WPS setting", "/miro/api/v2/wireless/wps/setting", "Wireless"),
    ApiEndpoint("wps_status", "WPS status", "/miro/api/v2/wireless/wps/status", "Wireless"),
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


def normalize_output_dir(value: str | Path) -> Path:
    text = str(value).strip()
    if not text:
        raise ValueError("output directory is required")
    return Path(text).expanduser()


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


def discover_extra_endpoints(base_url: str, output_dir: Path) -> tuple[list[ApiEndpoint], dict[str, Any]]:
    try:
        import discover_qnap_api as discovery
    except Exception as exc:
        return [], {"error": f"could not import discover_qnap_api: {exc}"}

    if hasattr(discovery, "set_output_dir"):
        discovery.set_output_dir(output_dir)

    stats: dict[str, Any] = {
        "downloaded_assets": 0,
        "discovered_endpoints": 0,
        "discovered_operations": 0,
        "selected_extra": 0,
        "raw_dir": str(output_dir / "raw"),
        "artifacts_dir": str(output_dir / "artifacts"),
    }
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
        entry["error_code"] = parsed.get("error_code")
        entry["error_message"] = parsed.get("error_message")
        entry["response"] = parsed
        if "result" in parsed:
            entry["result"] = parsed["result"]
    elif parsed is not None:
        entry["response"] = parsed
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


def endpoint_by_name(collected: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("name")): item for item in collected}


def endpoint_result(by_name: dict[str, dict[str, Any]], name: str) -> Any:
    item = by_name.get(name)
    return item.get("result") if item else None


def endpoint_ok(item: dict[str, Any]) -> bool:
    return item.get("status") == 200 and item.get("error_code") in (0, None) and not item.get("error")


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in (
            "clientsData",
            "eventLogList",
            "data",
            "items",
            "list",
            "rules",
            "routes",
            "wan",
            "lan",
            "vlan",
            "bridge",
            "profiles",
            "portStatistics",
        ):
            item = value.get(key)
            if isinstance(item, list):
                return item
    return []


def value_at(value: Any, path: str, default: Any = "") -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return default
    return default if current is None else current


def pick_first(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        item = value_at(value, key)
        if item not in (None, "", []):
            return item
    return ""


def csv_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(compact_value(item, max_len=120) for item in value)
    return compact_value(value, max_len=220)


def render_table(
    title: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    max_rows: int,
    empty: str = "_Nessun dato raccolto._",
) -> list[str]:
    lines = [f"### {title}", ""]
    if not rows:
        lines.extend([empty, ""])
        return lines
    lines.append("| " + " | ".join(label for label, _ in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(md_escape(value_at(row, selector)) for _, selector in columns) + " |")
    if len(rows) > max_rows:
        overflow = [f"... {len(rows) - max_rows} altre righe nel JSON completo"] + [""] * (len(columns) - 1)
        lines.append("| " + " | ".join(md_escape(item) for item in overflow) + " |")
    lines.append("")
    return lines


def interface_ip(config: dict[str, Any]) -> str:
    address = config.get("ip4Address") or config.get("ip") or ""
    prefix = config.get("ip4Prefix")
    if address and prefix not in (None, ""):
        return f"{address}/{prefix}"
    return str(address)


def dhcp_service(config: dict[str, Any]) -> dict[str, Any]:
    service = config.get("dhcpService")
    return service if isinstance(service, dict) else {}


def dhcp_gateway(service: dict[str, Any]) -> Any:
    if service.get("defaultGatewayIp"):
        return service.get("defaultGatewayIp")
    routers = service.get("routers")
    if isinstance(routers, list):
        return csv_value(routers)
    return routers or ""


def dhcp_reserved_count(service: dict[str, Any]) -> int:
    reserved = service.get("reservedIps")
    return len(reserved) if isinstance(reserved, list) else 0


def interface_base_row(source: str, item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    service = dhcp_service(config)
    return {
        "source": source,
        "type": item.get("type") or config.get("type") or "lan",
        "id": pick_first(item, "portName", "vlanIfId", "bridgeId", "interfaceId", "name"),
        "vlanId": item.get("vlanId", ""),
        "name": pick_first(item, "name", "description", "label"),
        "description": pick_first(item, "description", "label"),
        "enabled": config.get("enabled", item.get("enabled", "")),
        "portsTagged": csv_value(item.get("tags", [])),
        "portsUntagged": csv_value(item.get("untags", [])),
        "ip4Type": config.get("ip4Type", ""),
        "ip4": interface_ip(config),
        "mtu": config.get("mtu", item.get("mtu", "")),
        "dhcpType": service.get("serviceType", ""),
        "dhcpRange": format_range(service.get("startIp"), service.get("endIp")),
        "dhcpLease": service.get("leaseTime", ""),
        "dhcpDns": csv_value(service.get("dnsServers", [])),
        "dhcpGateway": dhcp_gateway(service),
        "reservedCount": dhcp_reserved_count(service),
    }


def format_range(start: Any, end: Any) -> str:
    if start and end:
        return f"{start} - {end}"
    return str(start or end or "")


def iter_lan_interfaces(by_name: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    ports = endpoint_result(by_name, "ports_config")
    if isinstance(ports, dict):
        for item in as_list(ports.get("lan")):
            if isinstance(item, dict):
                rows.append(("LAN fisica", item, item))

    for source, endpoint_name, nested_key in (
        ("VLAN", "vlan_interfaces", "lan"),
        ("Bridge", "bridges", "lan"),
    ):
        for item in as_list(endpoint_result(by_name, endpoint_name)):
            if not isinstance(item, dict):
                continue
            config = item.get(nested_key)
            if isinstance(config, dict):
                rows.append((source, item, config))

    settings = endpoint_result(by_name, "network_settings")
    if isinstance(settings, dict):
        for source, key, nested_key in (
            ("Settings LAN", "lan", None),
            ("Settings VLAN", "vlan", "lan"),
            ("Settings Bridge", "bridge", "lan"),
        ):
            for item in as_list(settings.get(key)):
                if not isinstance(item, dict):
                    continue
                config = item.get(nested_key) if nested_key else item
                if isinstance(config, dict):
                    rows.append((source, item, config))
    return dedupe_interface_configs(rows)


def dedupe_interface_configs(rows: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for source, item, config in rows:
        canonical_source = source.replace("Settings ", "").replace("LAN fisica", "LAN")
        key = (
            canonical_source,
            str(pick_first(item, "portName", "vlanIfId", "bridgeId", "interfaceId", "name")),
            str(item.get("vlanId", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append((source, item, config))
    return out


def collect_lan_rows(by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [interface_base_row(source, item, config) for source, item, config in iter_lan_interfaces(by_name)]


def collect_dhcp_reserved_rows(by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, item, config in iter_lan_interfaces(by_name):
        service = dhcp_service(config)
        for reserved in as_list(service.get("reservedIps")):
            if not isinstance(reserved, dict):
                continue
            base = interface_base_row(source, item, config)
            rows.append(
                {
                    "interface": base.get("name") or base.get("id"),
                    "source": source,
                    "vlanId": base.get("vlanId"),
                    "ip": pick_first(reserved, "ip", "ip4Address", "address"),
                    "mac": pick_first(reserved, "mac", "macAddress", "macAddr"),
                    "name": pick_first(reserved, "name", "hostname", "description"),
                    "description": pick_first(reserved, "description", "comment"),
                }
            )
    return sorted(rows, key=lambda row: (str(row.get("interface", "")), ip_sort_key(str(row.get("ip", "")))))


def ip_sort_key(value: str) -> tuple[int, ...]:
    parts = value.split("/")[0].split(".")
    if len(parts) != 4:
        return (999, 999, 999, 999)
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return (999, 999, 999, 999)


def collect_wan_rows(by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ports = endpoint_result(by_name, "ports_config")
    status = endpoint_result(by_name, "wan_status")
    status_by_port: dict[str, dict[str, Any]] = {}
    if isinstance(status, dict):
        for item in as_list(status.get("wan")):
            if isinstance(item, dict):
                ifname = str(item.get("ifname", ""))
                match = re.search(r"(\d+)$", ifname)
                if match:
                    status_by_port[match.group(1)] = item

    rows: list[dict[str, Any]] = []
    if isinstance(ports, dict):
        for item in as_list(ports.get("wan")):
            if not isinstance(item, dict):
                continue
            port = str(item.get("portName", ""))
            stat = status_by_port.get(port, {})
            rows.append(
                {
                    "port": port,
                    "name": pick_first(item, "name", "description"),
                    "description": item.get("description", ""),
                    "enabled": item.get("enabled", ""),
                    "type": item.get("ip4Type", ""),
                    "ip": interface_ip(item),
                    "gateway": item.get("ip4Gateway", ""),
                    "dns": csv_value(item.get("ip4DnsServers", [])),
                    "realIp": stat.get("ip4RealAddress", ""),
                    "link": stat.get("linkStatus", ""),
                    "tier": item.get("tier", ""),
                    "weight": item.get("weight", ""),
                    "mtu": item.get("mtu", ""),
                    "username": item.get("username", ""),
                    "password": item.get("password", ""),
                }
            )
    return rows


def collect_dhcp_client_rows(by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = endpoint_result(by_name, "dhcp_clients")
    rows: list[dict[str, Any]] = []
    for item in as_list(result):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "interface": pick_first(item, "interfaceId", "interface", "interfaceName"),
                "hostname": item.get("hostname", ""),
                "ip": pick_first(item, "ip4Address", "ip", "dhcpIp"),
                "mac": pick_first(item, "macAddress", "macAddr"),
                "expires": pick_first(item, "expireTime", "expires", "leaseExpire"),
                "lastAccess": pick_first(item, "lastAccess", "lastConnTime"),
                "reserved": item.get("isReserved", ""),
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("interface", "")), ip_sort_key(str(row.get("ip", "")))))


def collect_known_client_rows(by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(endpoint_result(by_name, "clients")):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "interface": item.get("interface", ""),
                "hostname": item.get("hostname", ""),
                "description": item.get("description", ""),
                "ip": item.get("ip", ""),
                "dhcpIp": item.get("dhcpIp", ""),
                "mac": item.get("macAddr", ""),
                "connection": item.get("connectionType", ""),
                "status": item.get("status", ""),
                "lastSeen": item.get("lastConnTime", ""),
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("interface", "")), ip_sort_key(str(row.get("ip") or row.get("dhcpIp") or ""))))


def collect_port_rows(by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ports = endpoint_result(by_name, "ports_config")
    status = endpoint_result(by_name, "ports_status")
    status_rows: dict[str, dict[str, Any]] = {}
    if isinstance(status, dict):
        for key in ("lan", "wan", "occupied"):
            for item in as_list(status.get(key)):
                if isinstance(item, dict):
                    port = str(item.get("portName") or item.get("port") or "")
                    if port:
                        status_rows[port] = item

    rows: list[dict[str, Any]] = []
    if isinstance(ports, dict):
        for kind in ("wan", "lan"):
            for item in as_list(ports.get(kind)):
                if not isinstance(item, dict):
                    continue
                port = str(item.get("portName", ""))
                stat = status_rows.get(port, {})
                rows.append(
                    {
                        "port": port,
                        "kind": kind.upper(),
                        "name": pick_first(item, "name", "description"),
                        "description": item.get("description", ""),
                        "enabled": item.get("enabled", ""),
                        "speed": item.get("speed", ""),
                        "link": pick_first(stat, "linkStatus", "status"),
                        "linkRate": pick_first(stat, "linkRate", "rate"),
                        "mac": pick_first(stat, "mac", "macAddr", "macAddress"),
                    }
                )
    return sorted(rows, key=lambda row: str(row.get("port", "")))


def render_system_section(by_name: dict[str, dict[str, Any]]) -> list[str]:
    machine = endpoint_result(by_name, "machine_info") if isinstance(endpoint_result(by_name, "machine_info"), dict) else {}
    basic = endpoint_result(by_name, "basic_info") if isinstance(endpoint_result(by_name, "basic_info"), dict) else {}
    hardware = endpoint_result(by_name, "hardware_status") if isinstance(endpoint_result(by_name, "hardware_status"), dict) else {}
    firmware = endpoint_result(by_name, "firmware") if isinstance(endpoint_result(by_name, "firmware"), dict) else {}
    mem_total = basic.get("mem_total")
    mem_used = basic.get("mem_used")
    mem_pct = ""
    if isinstance(mem_total, (int, float)) and isinstance(mem_used, (int, float)) and mem_total:
        mem_pct = round(mem_used * 100 / mem_total, 2)
    rows = [
        ("Hostname", machine.get("hostname", "")),
        ("Device name", machine.get("deviceName", "")),
        ("Model", machine.get("model", "")),
        ("Firmware", pick_first(firmware, "currentVersion", "localFwInfo.0.version") or basic.get("firmware_version", "")),
        ("Firmware build", basic.get("firmware_build_time", "")),
        ("Operation mode", basic.get("operation_mode", "")),
        ("Region", machine.get("region", "")),
        ("Country", machine.get("countryCode", "")),
        ("Language", machine.get("language", "")),
        ("Uptime", pick_first(hardware, "upTime", "uptime") or basic.get("uptime", "")),
        ("CPU load", basic.get("cpu_load", "")),
        ("CPU temperature", pick_first(hardware, "cpuMetadata.temperature") or basic.get("cpu_temp", "")),
        ("Memory total", mem_total or ""),
        ("Memory used", mem_used or ""),
        ("Memory used %", mem_pct),
    ]
    rows = [(key, value) for key, value in rows if value not in (None, "", [])]
    return ["## Sistema", "", *render_kv_table(rows, max_rows=100), ""]


def render_network_section(by_name: dict[str, dict[str, Any]], max_rows: int) -> list[str]:
    lines = ["## Rete", ""]
    network_status = endpoint_result(by_name, "network_status")
    if isinstance(network_status, dict):
        lines.extend(render_kv_table([("Internet connected", network_status.get("isInternetConnected", ""))], max_rows=20))
        lines.append("")
    lines.extend(
        render_table(
            "WAN",
            collect_wan_rows(by_name),
            [
                ("Porta", "port"),
                ("Nome", "name"),
                ("Abilitata", "enabled"),
                ("IPv4", "ip"),
                ("Gateway", "gateway"),
                ("DNS", "dns"),
                ("IP reale", "realIp"),
                ("Link", "link"),
                ("Tier", "tier"),
                ("Weight", "weight"),
                ("Username", "username"),
                ("Password", "password"),
            ],
            max_rows=max_rows,
        )
    )
    lines.extend(
        render_table(
            "Interfacce LAN, VLAN e bridge",
            collect_lan_rows(by_name),
            [
                ("Origine", "source"),
                ("Tipo", "type"),
                ("ID", "id"),
                ("VLAN", "vlanId"),
                ("Nome", "name"),
                ("Descrizione", "description"),
                ("Abilitata", "enabled"),
                ("Tagged", "portsTagged"),
                ("Untagged", "portsUntagged"),
                ("IPv4 type", "ip4Type"),
                ("IPv4", "ip4"),
                ("MTU", "mtu"),
            ],
            max_rows=max_rows,
        )
    )
    lines.extend(
        render_table(
            "Porte fisiche",
            collect_port_rows(by_name),
            [
                ("Porta", "port"),
                ("Tipo", "kind"),
                ("Nome", "name"),
                ("Descrizione", "description"),
                ("Abilitata", "enabled"),
                ("Speed config", "speed"),
                ("Link", "link"),
                ("Link rate", "linkRate"),
                ("MAC", "mac"),
            ],
            max_rows=max_rows,
        )
    )
    return lines


def render_dhcp_section(by_name: dict[str, dict[str, Any]], max_rows: int) -> list[str]:
    lines = ["## DHCP", ""]
    lines.extend(
        render_table(
            "Servizi DHCP per interfaccia",
            collect_lan_rows(by_name),
            [
                ("Interfaccia", "name"),
                ("Origine", "source"),
                ("VLAN", "vlanId"),
                ("Service", "dhcpType"),
                ("Range", "dhcpRange"),
                ("Lease", "dhcpLease"),
                ("Gateway", "dhcpGateway"),
                ("DNS", "dhcpDns"),
                ("Reserved IP", "reservedCount"),
            ],
            max_rows=max_rows,
        )
    )
    lines.extend(
        render_table(
            "IP statici DHCP / reserved IP",
            collect_dhcp_reserved_rows(by_name),
            [
                ("Interfaccia", "interface"),
                ("Origine", "source"),
                ("VLAN", "vlanId"),
                ("IP", "ip"),
                ("MAC", "mac"),
                ("Nome", "name"),
                ("Descrizione", "description"),
            ],
            max_rows=max_rows,
            empty="_Nessuna reservation DHCP trovata negli endpoint LAN/VLAN/bridge raccolti._",
        )
    )
    lines.extend(
        render_table(
            "Client DHCP",
            collect_dhcp_client_rows(by_name),
            [
                ("Interfaccia", "interface"),
                ("Hostname", "hostname"),
                ("IP", "ip"),
                ("MAC", "mac"),
                ("Riservato", "reserved"),
                ("Scadenza", "expires"),
                ("Ultimo accesso", "lastAccess"),
            ],
            max_rows=max_rows,
            empty="_Endpoint DHCP client non disponibile o senza dati._",
        )
    )
    return lines


def render_clients_section(by_name: dict[str, dict[str, Any]], max_rows: int) -> list[str]:
    return [
        "## Client",
        "",
        *render_table(
            "Client conosciuti dal router",
            collect_known_client_rows(by_name),
            [
                ("Interfaccia", "interface"),
                ("Hostname", "hostname"),
                ("Descrizione", "description"),
                ("IP", "ip"),
                ("DHCP IP", "dhcpIp"),
                ("MAC", "mac"),
                ("Connessione", "connection"),
                ("Status", "status"),
                ("Last seen", "lastSeen"),
            ],
            max_rows=max_rows,
        ),
    ]


def render_wireless_section(by_name: dict[str, dict[str, Any]], max_rows: int) -> list[str]:
    lines = ["## Wi-Fi", ""]
    status = endpoint_result(by_name, "wireless_status")
    if isinstance(status, dict):
        lines.extend(render_kv_table(sorted(status.items()), max_rows=50))
        lines.append("")
    for title, endpoint_name, columns in (
        ("Bande Wi-Fi configurate", "wireless_band", [("Band", "band"), ("Enabled", "enabled"), ("Channel", "channel"), ("Bandwidth", "bandwidth"), ("Mode", "mode")]),
        ("Stato bande Wi-Fi", "wireless_band_status", [("Band", "band"), ("Channel", "channel"), ("Bandwidth", "bandwidth")]),
        ("VAP / SSID configurati", "vap_setting", [("Type", "type"), ("Group", "vapGroupIdx"), ("SSID", "ssid"), ("Band", "band"), ("Enabled", "enabled"), ("VLAN", "vlanId"), ("Security", "security")]),
        ("Stato VAP", "vap_status", [("Type", "type"), ("Group", "vapGroupIdx"), ("Band", "band"), ("Status", "status"), ("WPS", "supportWps")]),
    ):
        result = endpoint_result(by_name, endpoint_name)
        rows = [row for row in as_list(result) if isinstance(row, dict)]
        lines.extend(render_table(title, rows, columns, max_rows=max_rows))
    return lines


def render_nat_routing_section(by_name: dict[str, dict[str, Any]], max_rows: int) -> list[str]:
    lines = ["## NAT e routing", ""]
    for endpoint_name in ("nat_alg", "nat_dmz", "nat_port_forwarding", "routing_ipv4", "routing_ipv6", "policy_route"):
        item = by_name.get(endpoint_name)
        if item:
            lines.extend(render_endpoint_markdown(item, include_raw=False, max_rows=max_rows))
    return lines


def render_services_security_section(by_name: dict[str, dict[str, Any]], max_rows: int) -> list[str]:
    lines = ["## Servizi e sicurezza", ""]
    for endpoint_name in ("ddns_info", "ddns_setting", "ddns_wan_status", "access_setting", "blocked_clients", "service_ports", "certificate_info"):
        item = by_name.get(endpoint_name)
        if item:
            lines.extend(render_endpoint_markdown(item, include_raw=False, max_rows=max_rows))
    return lines


def render_markdown(
    base_url: str,
    login_result: dict[str, Any],
    collected: list[dict[str, Any]],
    discovery_stats: dict[str, Any] | None,
    include_raw: bool,
    max_rows: int,
) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %z")
    ok = [item for item in collected if endpoint_ok(item)]
    failed = [item for item in collected if item not in ok]
    safe_login = {key: value for key, value in login_result.items() if key != "access_token"}
    by_name = endpoint_by_name(collected)

    lines = [
        "# QuRouter Configuration Export",
        "",
        f"Generated: {timestamp}",
        "",
        "## Scope",
        "",
        "This report was generated from read-only QuRouter API GET endpoints after one login POST.",
        "It is a documentation snapshot for change tracking and manual reconfiguration, not an official restorable backup.",
        "The Markdown file is organized by configuration area. The companion JSON contains the full collected API responses.",
        "No router configuration fields are redacted by this exporter.",
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
    lines.extend(render_system_section(by_name))
    lines.extend(render_network_section(by_name, max_rows=max_rows))
    lines.extend(render_dhcp_section(by_name, max_rows=max_rows))
    lines.extend(render_clients_section(by_name, max_rows=max_rows))
    lines.extend(render_wireless_section(by_name, max_rows=max_rows))
    lines.extend(render_nat_routing_section(by_name, max_rows=max_rows))
    lines.extend(render_services_security_section(by_name, max_rows=max_rows))

    if failed:
        lines.extend(["## Failed Or Partial Endpoints", ""])
        lines.extend(render_kv_table([(item.get("path"), item.get("error") or item.get("error_message") or item.get("status")) for item in failed], max_rows=200))
        lines.append("")

    handled = {
        "basic_info",
        "machine_info",
        "operation_setting",
        "region_setting",
        "device_name",
        "hardware_status",
        "firmware",
        "network_status",
        "ports_config",
        "ports_status",
        "ports_mac_addr",
        "lan_config",
        "vlan_interfaces",
        "vlan_status",
        "bridges",
        "bridge_status",
        "network_settings",
        "dhcp_clients",
        "wan_status",
        "clients",
        "wireless_status",
        "wireless_band",
        "wireless_band_status",
        "vap_setting",
        "vap_status",
        "nat_alg",
        "nat_dmz",
        "nat_port_forwarding",
        "routing_ipv4",
        "routing_ipv6",
        "policy_route",
        "ddns_info",
        "ddns_setting",
        "ddns_wan_status",
        "access_setting",
        "blocked_clients",
        "service_ports",
        "certificate_info",
    }
    other = [item for item in collected if item.get("name") not in handled]
    if other:
        lines.extend(["## Altri endpoint raccolti", ""])
        for item in other:
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
        lines.extend(["", "Raw JSON:", "", "```json"])
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
    parser.add_argument("--output-dir", type=Path, help=f"Directory for Markdown and JSON output. Defaults to {DEFAULT_OUTPUT_DIR_TEXT} in non-interactive mode.")
    parser.add_argument("--output-prefix", help="Output file prefix. Defaults to qrouter_config_<host>_<timestamp>.")
    parser.add_argument("--extended-discovery", dest="extended_discovery", action="store_true", default=None, help="Download frontend assets and probe extra discovered safe GET endpoints.")
    parser.add_argument("--no-extended-discovery", dest="extended_discovery", action="store_false", help="Only collect the curated endpoint set.")
    parser.add_argument("--force-login", dest="force_login", action="store_true", default=None, help="Force login if another session is active.")
    parser.add_argument("--no-force-login", dest="force_login", action="store_false", help="Do not force login if another session is active.")
    parser.add_argument("--verify-tls", action="store_true", help="Verify router TLS certificate instead of accepting self-signed certificates.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds.")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between GET requests in seconds.")
    parser.add_argument("--max-table-rows", type=int, default=100, help="Maximum rows per Markdown summary table.")
    parser.add_argument("--include-raw-json", action="store_true", help="Also include full raw JSON blocks in the Markdown file. The JSON companion is always written.")
    parser.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting for missing values.")
    return parser.parse_args()


def resolve_runtime_options(args: argparse.Namespace) -> tuple[str, str, str, Path, bool, bool]:
    interactive = not args.non_interactive and sys.stdin.isatty()
    base_url = args.base_url or (prompt_text("Router IP o URL", "https://192.168.1.1") if interactive else "")
    username = args.username or (prompt_text("Username") if interactive else "")
    password = args.password or (getpass.getpass("Password: ") if interactive else "")
    if not base_url or not username or not password:
        raise ValueError("base URL, username and password are required")

    if args.output_dir is not None:
        output_dir = normalize_output_dir(args.output_dir)
    elif interactive:
        output_dir = normalize_output_dir(prompt_text("Cartella output report", DEFAULT_OUTPUT_DIR_TEXT))
    else:
        output_dir = DEFAULT_OUTPUT_DIR

    force_login = args.force_login
    if force_login is None:
        force_login = prompt_bool("Forzare il login se esiste gia una sessione web?", True) if interactive else True

    extended_discovery = args.extended_discovery
    if extended_discovery is None:
        extended_discovery = prompt_bool("Eseguire discovery estesa degli endpoint dal frontend?", True) if interactive else False

    return normalize_base_url(base_url), username, password, output_dir, bool(force_login), bool(extended_discovery)


def main() -> int:
    args = parse_args()
    try:
        base_url, username, password, output_dir, force_login, extended_discovery = resolve_runtime_options(args)
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
        extra_endpoints, discovery_stats = discover_extra_endpoints(base_url, output_dir)
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
        output_dir,
        prefix,
        base_url,
        login_result,
        collected,
        discovery_stats,
        include_raw=args.include_raw_json,
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
