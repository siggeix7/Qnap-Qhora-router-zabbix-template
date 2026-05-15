#!/usr/bin/env python3
"""Authenticated, read-only QuRouter API probe.

Reads credentials from a local file, performs the same local-account login used by
the web UI, and probes only safe GET endpoints. Secrets are never printed or
written to the generated artifacts.

Usage:
    # Create a credentials file (never commit this file)
    echo "username=your_user
    password=your_password
    base_url=https://<ROUTER_IP>" > credentials.txt

    # Run the probe
    python3 authenticated_probe_qnap.py --base-url https://<ROUTER_IP> --credentials credentials.txt --output-dir ~/qrouter_exports/probe --zabbix-candidates

WARNING: This script performs a POST login request and multiple GET requests
against the router. It does NOT perform any PUT, DELETE, or configuration-changing
operations. The login with force=true may close existing web sessions.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

import discover_qnap_api as discovery


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR_TEXT = "~/qrouter_exports/probe"
DEFAULT_OUTPUT_DIR = Path(DEFAULT_OUTPUT_DIR_TEXT).expanduser()
ARTIFACTS = DEFAULT_OUTPUT_DIR / "artifacts"
DEFAULT_BASE_URL = "https://<ROUTER_IP>"
DEFAULT_CREDENTIALS = ROOT / "credentials.txt"
ZABBIX_CANDIDATES = [
    ("v1", "BasicInfo"),
    ("v1", "CloudService"),
    ("v1", "ConnectionStatus"),
    ("v1", "DeploymentProgress"),
    ("v1", "QuwanStatus"),
    ("v2", "MachineInfo"),
    ("v2", "NetworkStatus"),
    ("v2", "SystemHardware"),
    ("v2", "SystemHardwareStatus"),
    ("v2", "Ports"),
    ("v2", "PortsStatus"),
    ("v2", "WanInterfacesStatus"),
    ("v2", "Clients"),
    ("v2", "Firmware"),
    ("v2", "FirmwareSchedule"),
    ("v2", "LoadBalancingStatus"),
    ("v2", "DdnsInfo"),
    ("v2", "WirelessStatus"),
    ("v2", "WirelessBandStatus"),
    ("v2", "VapStatus"),
    ("v2", "EventLogs"),
]
KNOWN_UNSTABLE_PATHS = {
    "/miro/api/v1/laninfo",
}


SECRET_KEY_RE = re.compile(r"(password|passwd|pass|token|secret|key|sid|session|credential|authorization|psk)", re.I)
SENSITIVE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./+=:-]{24,}$")


def set_output_dir(output_dir: Path) -> None:
    """Set where generated probe artifacts and discovery raw data are read/written."""
    global ARTIFACTS
    root = output_dir.expanduser()
    ARTIFACTS = root / "artifacts"
    if hasattr(discovery, "set_output_dir"):
        discovery.set_output_dir(root)


def parse_credentials(path: Path) -> dict[str, Any]:
    """Parse credentials from a text file.

    Supported formats:
    - JSON: {"username": "...", "password": "...", "base_url": "..."}
    - Key-value: username=..., password=..., base_url=...
    - Positional: first line = username, second line = password
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        raise ValueError("credential file is empty")

    data: dict[str, Any] = {}
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("JSON credentials must be an object")
        data.update(parsed)
    else:
        positional: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip().strip('"\'')
            elif ":" in line and not re.match(r"^[a-z]+://", line, re.I):
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip().strip('"\'')
            else:
                positional.append(line)
        if positional and not data:
            data["username"] = positional[0]
            if len(positional) > 1:
                data["password"] = positional[1]

    normalized: dict[str, Any] = {}
    for key, value in data.items():
        norm = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if norm in {"user", "username", "login", "utente", "account"}:
            normalized["username"] = str(value)
        elif norm in {"password", "passwd", "pass", "pwd", "parola", "parolachiave"}:
            normalized["password"] = str(value)
        elif norm in {"url", "baseurl", "router", "host", "hostname"}:
            normalized["base_url"] = str(value).rstrip("/")
        elif norm in {"force", "forcelogin"}:
            normalized["force"] = str(value).lower() in {"1", "true", "yes", "y", "si", "s"}

    if "username" not in normalized or "password" not in normalized:
        keys = sorted(redact_key(k) for k in data.keys())
        raise ValueError(f"could not find username/password in credentials file; parsed keys={keys}")
    return normalized


def redact_key(key: Any) -> str:
    return "<secret-key>" if SECRET_KEY_RE.search(str(key)) else str(key)


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 8.0,
) -> tuple[int | None, dict[str, str], bytes, Any | None]:
    ctx = ssl._create_unverified_context()
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "qnap-api-auth-probe/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, raw, decode_json(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, raw, decode_json(raw)


def decode_json(raw: bytes) -> Any | None:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def login(base_url: str, username: str, password: str, force: bool = False) -> dict[str, Any]:
    """Perform local account login against the QuRouter API.

    The password is base64-encoded UTF-8, matching the web UI behavior.
    """
    encoded_password = base64.b64encode(password.encode("utf-8")).decode("ascii")
    payload = {
        "username": username,
        "password": encoded_password,
        "force": force,
        "remember_me": False,
        "qid_login": False,
    }
    url = base_url.rstrip("/") + "/miro/api/v1/login"
    status, headers, raw, parsed = request_json("POST", url, payload=payload)
    result = parsed.get("result") if isinstance(parsed, dict) else None
    token = result.get("access_token") if isinstance(result, dict) else None
    return {
        "status": status,
        "error_code": parsed.get("error_code") if isinstance(parsed, dict) else None,
        "error_message": parsed.get("error_message") if isinstance(parsed, dict) else None,
        "had_session": result.get("had_session") if isinstance(result, dict) else None,
        "is_qid": result.get("is_qid") if isinstance(result, dict) else None,
        "is_first_login_qid": result.get("IsFirstLoginQID") if isinstance(result, dict) else None,
        "is_local_default_credential": result.get("IsLocalAccountDefaultCred") if isinstance(result, dict) else None,
        "has_access_token": bool(token),
        "access_token": token,
        "body_bytes": len(raw),
        "content_type": headers.get("content-type", ""),
    }


def result_schema(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Describe the structure of a JSON value without exposing actual data."""
    if depth >= max_depth:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(str(k) for k in value.keys()),
            "fields": {str(k): result_schema(v, depth + 1, max_depth) for k, v in sorted(value.items(), key=lambda item: str(item[0]))},
        }
    if isinstance(value, list):
        item_schema = result_schema(value[0], depth + 1, max_depth) if value else None
        return {"type": "array", "length": len(value), "item_schema": item_schema}
    return {"type": type(value).__name__}


def redacted_sample(value: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Return a sample of a JSON value with sensitive fields redacted."""
    if depth >= max_depth:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda item: str(item[0]))[:40]:
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                out[key_text] = "<redacted>"
            else:
                out[key_text] = redacted_sample(item, depth + 1, max_depth)
        return out
    if isinstance(value, list):
        return [redacted_sample(item, depth + 1, max_depth) for item in value[:3]]
    if isinstance(value, str):
        if SENSITIVE_VALUE_RE.match(value):
            return "<redacted-string>"
        if len(value) > 80:
            return value[:77] + "..."
        return value
    return value


def probe_authenticated_gets(
    base_url: str,
    token: str,
    selected_refs: list[tuple[str, str]] | None = None,
    delay_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    """Probe authenticated GET endpoints and collect schema information."""
    endpoints = discovery.extract_endpoints_from_js()
    operations = discovery.extract_operations(endpoints)
    lookup = {(endpoint.version, endpoint.key): endpoint for endpoint in endpoints}
    refs = selected_refs or sorted({(op.version, op.key) for op in operations if op.method == "GET" and op.version and op.key})

    results: list[dict[str, Any]] = []
    for version, key in refs:
        endpoint = lookup.get((version, key))
        if not endpoint or not discovery.is_safe_probe_path(endpoint.path) or endpoint.path in KNOWN_UNSTABLE_PATHS:
            continue
        url = base_url.rstrip("/") + endpoint.path
        print(f"auth_probe=GET {endpoint.path}", flush=True)
        start = time.time()
        try:
            status, headers, raw, parsed = request_json("GET", url, token=token, timeout=8.0)
            entry: dict[str, Any] = {
                "version": version,
                "key": key,
                "path": endpoint.path,
                "status": status,
                "content_type": headers.get("content-type", ""),
                "body_bytes": len(raw),
                "elapsed_ms": int((time.time() - start) * 1000),
            }
            if isinstance(parsed, dict):
                entry["error_code"] = parsed.get("error_code")
                entry["error_message"] = parsed.get("error_message")
                entry["json_keys"] = sorted(str(k) for k in parsed.keys())
                if "result" in parsed:
                    entry["result_schema"] = result_schema(parsed["result"])
                    entry["result_sample_redacted"] = redacted_sample(parsed["result"])
            elif parsed is not None:
                entry["json_type"] = type(parsed).__name__
                entry["json_schema"] = result_schema(parsed)
            else:
                text = raw.decode("utf-8", errors="replace")
                entry["body_preview"] = text[:200]
            results.append(entry)
        except Exception as exc:
            results.append(
                {
                    "version": version,
                    "key": key,
                    "path": endpoint.path,
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_ms": int((time.time() - start) * 1000),
                }
            )
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    return results


def write_reports(login_result: dict[str, Any], probe: list[dict[str, Any]] | None, prefix: str = "authenticated") -> None:
    """Write probe results to artifacts directory."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    safe_login = {k: v for k, v in login_result.items() if k != "access_token"}
    (ARTIFACTS / f"{prefix}_login_result.json").write_text(json.dumps(safe_login, indent=2, sort_keys=True) + "\n")
    if probe is not None:
        (ARTIFACTS / f"{prefix}_get_probe.json").write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n")

    lines = ["# Authenticated QuRouter Probe", "", f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %z')}", ""]
    lines.append("## Login")
    lines.append("")
    lines.append(f"- HTTP status: {safe_login.get('status')}")
    lines.append(f"- error_code: {safe_login.get('error_code')}")
    lines.append(f"- has_access_token: {safe_login.get('has_access_token')}")
    lines.append(f"- had_session: {safe_login.get('had_session')}")
    if probe is not None:
        ok = [item for item in probe if item.get("error_code") == 0]
        token_errors = [item for item in probe if item.get("error_code") == 10032]
        http_404 = [item for item in probe if item.get("status") == 404]
        lines.extend(["", "## Probe", ""])
        lines.append(f"- GET probed: {len(probe)}")
        lines.append(f"- Application success `error_code=0`: {len(ok)}")
        lines.append(f"- Token errors: {len(token_errors)}")
        lines.append(f"- HTTP 404: {len(http_404)}")
        lines.extend(["", "## Successful GET Endpoints", ""])
        lines.append("| Key | Path | Result Type | Top-Level Result Keys |")
        lines.append("| --- | --- | --- | --- |")
        for item in ok:
            schema = item.get("result_schema") or {}
            keys = schema.get("keys") if isinstance(schema, dict) else None
            result_type = schema.get("type") if isinstance(schema, dict) else ""
            key_text = ", ".join(keys[:30]) if isinstance(keys, list) else ""
            lines.append(f"| `{item.get('key')}` | `{item.get('path')}` | `{result_type}` | {key_text} |")
    (ARTIFACTS / f"{prefix}_probe.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"directory for probe artifacts and discovery raw data, default: {DEFAULT_OUTPUT_DIR_TEXT}")
    parser.add_argument("--force", action="store_true", help="force login if the router reports an existing session")
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--zabbix-candidates", action="store_true", help="probe only a conservative monitoring-oriented endpoint list")
    parser.add_argument("--report-prefix", default="authenticated")
    parser.add_argument("--delay", type=float, default=0.25, help="delay between GET requests in seconds")
    args = parser.parse_args()

    set_output_dir(args.output_dir)

    creds = parse_credentials(args.credentials)
    base_url = creds.get("base_url") or args.base_url.rstrip("/")
    force = bool(args.force or creds.get("force"))
    print(f"output_dir={args.output_dir.expanduser()}", flush=True)
    print("credentials=loaded fields=username,password" + (",base_url" if creds.get("base_url") else ""), flush=True)
    login_result = login(base_url, creds["username"], creds["password"], force=force)
    print(
        "login_status={status} error_code={error_code} has_access_token={has_access_token} had_session={had_session}".format(
            **{k: login_result.get(k) for k in ("status", "error_code", "has_access_token", "had_session")}
        ),
        flush=True,
    )
    if not login_result.get("has_access_token"):
        write_reports(login_result, None, prefix=args.report_prefix)
        if login_result.get("had_session") and not force:
            print("login_requires_force=true", flush=True)
        return 2
    selected_refs = ZABBIX_CANDIDATES if args.zabbix_candidates else None
    probe = None if args.login_only else probe_authenticated_gets(base_url, login_result["access_token"], selected_refs=selected_refs, delay_seconds=args.delay)
    write_reports(login_result, probe, prefix=args.report_prefix)
    if probe is not None:
        ok = sum(1 for item in probe if item.get("error_code") == 0)
        print(f"auth_probes={len(probe)} success_error_code_0={ok}", flush=True)
    print(f"artifacts={ARTIFACTS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
