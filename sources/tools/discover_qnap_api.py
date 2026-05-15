#!/usr/bin/env python3
"""Discover QuRouter frontend API endpoints and safely probe public GETs.

This script downloads the same static assets the browser loads when accessing
the QuRouter web UI, then reconstructs the API endpoint map from the minified
frontend JavaScript.

Usage:
    python3 discover_qnap_api.py --base-url https://<ROUTER_IP>

The script only performs GET requests and does not require authentication.
"""

from __future__ import annotations

import argparse
import html.parser
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
ARTIFACTS = ROOT / "artifacts"
DEFAULT_BASE_URL = "https://<ROUTER_IP>"


class AssetParser(html.parser.HTMLParser):
    """Extract asset URLs from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        for key in ("src", "href", "data-src"):
            value = attr.get(key)
            if value:
                self.assets.append(value)


@dataclass(frozen=True)
class Endpoint:
    version: str
    key: str
    path: str
    url_template: str
    source: str
    dynamic: bool = False


@dataclass(frozen=True)
class Operation:
    method: str
    endpoint_ref: str
    version: str | None
    key: str | None
    url_template: str | None
    expression: str
    source_file: str
    offset: int


def ensure_dirs() -> None:
    for path in (RAW, RAW / "js", RAW / "css", ARTIFACTS):
        path.mkdir(parents=True, exist_ok=True)


def fetch_text(url: str, timeout: float = 4.0) -> tuple[int | None, str, bytes, dict[str, str]]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={"User-Agent": "qnap-api-discovery/0.1"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            data = resp.read()
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp.geturl(), data, headers
    except urllib.error.HTTPError as exc:
        data = exc.read()
        headers = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, exc.geturl(), data, headers


def safe_asset_path(url_path: str) -> Path:
    parsed = urllib.parse.urlparse(url_path)
    clean = parsed.path.lstrip("/") or "index.html"
    if clean.endswith("/"):
        clean += "index.html"
    parts = [part for part in clean.split("/") if part not in ("", ".", "..")]
    return RAW.joinpath(*parts)


def crawl_assets(base_url: str) -> list[str]:
    """Download frontend assets from the router."""
    ensure_dirs()
    base_url = base_url.rstrip("/")
    status, final_url, body, headers = fetch_text(base_url + "/")
    (RAW / "index.html").write_bytes(body)
    (ARTIFACTS / "root_response.json").write_text(
        json.dumps(
            {
                "url": base_url + "/",
                "final_url": final_url,
                "status": status,
                "headers": headers,
                "body_bytes": len(body),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    parser = AssetParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    queue: list[str] = []
    seen: set[str] = set()

    def enqueue(asset: str, current_path: str = "/") -> None:
        if asset.startswith("http"):
            parsed = urllib.parse.urlparse(asset)
            asset_path = parsed.path
        elif asset.startswith("//"):
            asset_path = urllib.parse.urlparse(asset).path
        elif asset.startswith("/"):
            asset_path = asset
        else:
            asset_path = urllib.parse.urljoin(current_path, asset)
        if asset_path not in seen:
            seen.add(asset_path)
            queue.append(asset_path)

    for asset in parser.assets:
        enqueue(asset)

    downloaded: list[str] = []
    while queue:
        asset_path = queue.pop(0)
        url = base_url + asset_path
        local_path = safe_asset_path(asset_path)
        if local_path.exists():
            continue
        try:
            status, final_url, data, headers = fetch_text(url, timeout=6.0)
            if status == 200:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(data)
                downloaded.append(asset_path)
                if asset_path.endswith(".html"):
                    sub_parser = AssetParser()
                    sub_parser.feed(data.decode("utf-8", errors="ignore"))
                    for sub_asset in sub_parser.assets:
                        enqueue(sub_asset, asset_path)
                time.sleep(0.15)
        except Exception:
            pass

    return downloaded


API_PATH_RE = re.compile(r'["\'](/miro/api/v[12]/[^"\']+)["\']')
API_TEMPLATE_RE = re.compile(r'["\'](/miro/api/v[12]/[^"\']*\$\{[^}]+\}[^"\']*)["\']')
API_KEY_RE = re.compile(r'(?:I\.v[12]\.)?([A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)*)')


def extract_endpoints_from_js() -> list[Endpoint]:
    """Extract API endpoints from downloaded JavaScript files."""
    js_dir = RAW / "js"
    if not js_dir.exists():
        return []

    endpoints: dict[str, Endpoint] = {}

    for js_file in sorted(js_dir.glob("*.js")):
        try:
            content = js_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        source = js_file.name

        for match in API_TEMPLATE_RE.finditer(content):
            path = match.group(1)
            version_match = re.search(r'/miro/api/v([12])/', path)
            version = f"v{version_match.group(1)}" if version_match else "v1"
            key_match = re.search(r'/miro/api/v[12]/(?:[^/]+/)*([^/${}]+)', path)
            key = key_match.group(1) if key_match else "Unknown"
            endpoint = Endpoint(
                version=version,
                key=key,
                path=path,
                url_template=path,
                source=source,
                dynamic=True,
            )
            endpoints[f"{version}:{path}"] = endpoint

        for match in API_PATH_RE.finditer(content):
            path = match.group(1)
            if "${" in path:
                continue
            version_match = re.search(r'/miro/api/v([12])/', path)
            version = f"v{version_match.group(1)}" if version_match else "v1"
            key_match = re.search(r'/miro/api/v[12]/(?:[^/]+/)*([^/${}]+)', path)
            key = key_match.group(1) if key_match else "Unknown"
            endpoint_ref = f"{version}:{path}"
            if endpoint_ref not in endpoints:
                endpoint = Endpoint(
                    version=version,
                    key=key,
                    path=path,
                    url_template=path,
                    source=source,
                    dynamic=False,
                )
                endpoints[endpoint_ref] = endpoint

    return sorted(endpoints.values(), key=lambda e: (e.version, e.path))


def extract_operations(endpoints: list[Endpoint]) -> list[Operation]:
    """Extract API operations (method calls) from JavaScript files."""
    js_dir = RAW / "js"
    if not js_dir.exists():
        return []

    operations: list[Operation] = []
    endpoint_lookup = {(e.version, e.key): e for e in endpoints}

    api_call_re = re.compile(
        r'(?:await\s+)?(?:api|this\.\$api|miroApi)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        re.MULTILINE,
    )

    for js_file in sorted(js_dir.glob("*.js")):
        try:
            content = js_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        source = js_file.name

        for match in api_call_re.finditer(content):
            method = match.group(1).upper()
            url = match.group(2)
            offset = match.start()

            version_match = re.search(r'/miro/api/v([12])/', url)
            version = f"v{version_match.group(1)}" if version_match else None

            key_match = re.search(r'/miro/api/v[12]/(?:[^/]+/)*([^/${}]+)', url)
            key = key_match.group(1) if key_match else None

            endpoint_ref = f"{version}:{key}" if version and key else None

            operations.append(Operation(
                method=method,
                endpoint_ref=endpoint_ref or "",
                version=version,
                key=key,
                url_template=url if "${" in url else None,
                expression=match.group(0),
                source_file=source,
                offset=offset,
            ))

    return operations


SAFE_PATH_RE = re.compile(r'^/miro/api/v[12]/[a-z0-9_/]+$')


def is_safe_probe_path(path: str) -> bool:
    if not SAFE_PATH_RE.match(path):
        return False
    if "${" in path or "{" in path:
        return False
    return True


def probe_public_gets(base_url: str, endpoints: list[Endpoint], delay_seconds: float = 0.2) -> list[dict[str, Any]]:
    """Probe public GET endpoints without authentication."""
    ctx = ssl._create_unverified_context()
    results: list[dict[str, Any]] = []

    for endpoint in endpoints:
        if not is_safe_probe_path(endpoint.path):
            continue
        url = base_url.rstrip("/") + endpoint.path
        print(f"probe=GET {endpoint.path}", flush=True)
        start = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "qnap-api-discovery/0.1"})
            with urllib.request.urlopen(req, context=ctx, timeout=5.0) as resp:
                raw = resp.read()
                entry = {
                    "path": endpoint.path,
                    "status": resp.status,
                    "body_bytes": len(raw),
                    "elapsed_ms": int((time.time() - start) * 1000),
                }
                try:
                    parsed = json.loads(raw)
                    entry["json_keys"] = sorted(str(k) for k in parsed.keys()) if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    entry["body_preview"] = raw.decode("utf-8", errors="replace")[:200]
                results.append(entry)
        except urllib.error.HTTPError as exc:
            results.append({
                "path": endpoint.path,
                "status": exc.code,
                "elapsed_ms": int((time.time() - start) * 1000),
            })
        except Exception as exc:
            results.append({
                "path": endpoint.path,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": int((time.time() - start) * 1000),
            })
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--probe", action="store_true", help="also probe public GET endpoints")
    parser.add_argument("--delay", type=float, default=0.2, help="delay between GET requests in seconds")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"base_url={base_url}", flush=True)

    print("crawling frontend assets...", flush=True)
    downloaded = crawl_assets(base_url)
    print(f"downloaded={len(downloaded)} assets", flush=True)

    print("extracting endpoints...", flush=True)
    endpoints = extract_endpoints_from_js()
    print(f"endpoints={len(endpoints)}", flush=True)

    (ARTIFACTS / "api_endpoints.json").write_text(
        json.dumps([asdict(e) for e in endpoints], indent=2, sort_keys=True) + "\n"
    )

    print("extracting operations...", flush=True)
    operations = extract_operations(endpoints)
    print(f"operations={len(operations)}", flush=True)

    (ARTIFACTS / "api_operations.json").write_text(
        json.dumps([asdict(o) for o in operations], indent=2, sort_keys=True) + "\n"
    )

    if args.probe:
        print("probing public GET endpoints...", flush=True)
        results = probe_public_gets(base_url, endpoints, delay_seconds=args.delay)
        (ARTIFACTS / "public_get_probe.json").write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n"
        )
        ok = sum(1 for r in results if r.get("status") == 200)
        print(f"public_probe={len(results)} ok={ok}", flush=True)

    print(f"artifacts={ARTIFACTS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
