#!/usr/bin/python3

from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

GITHUB_URL = "https://github.com/"
RETRY_DELAYS = (0, 5, 10, 20, 40, 60, 120, 180)


class NetworkUnavailable(RuntimeError):
    """Raised when neither the configured proxy nor direct access is ready."""


class Probe(Protocol):
    def __call__(self, url: str, proxy_url: str | None) -> None: ...


def parse_https_proxy(output: str) -> str | None:
    values: dict[str, str] = {}
    for key in ("HTTPSEnable", "HTTPSProxy", "HTTPSPort"):
        match = re.search(rf"^\s*{key}\s*:\s*(\S+)\s*$", output, re.MULTILINE)
        if match:
            values[key] = match.group(1)
    if values.get("HTTPSEnable") != "1":
        return None
    host = values.get("HTTPSProxy", "")
    port = values.get("HTTPSPort", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", host) or not port.isdigit():
        return None
    return f"http://{host}:{port}"


def configured_https_proxy() -> str | None:
    result = subprocess.run(
        ["/usr/sbin/scutil", "--proxy"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_https_proxy(result.stdout)


def probe_https(url: str, proxy_url: str | None) -> None:
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "agent-trending-preflight/1"},
    )
    with opener.open(request, timeout=10) as response:
        if response.status >= 500:
            raise NetworkUnavailable(f"HTTP {response.status}")


def wait_for_connectivity(
    *,
    url: str = GITHUB_URL,
    proxy_url: str | None,
    delays: Iterable[int] = RETRY_DELAYS,
    probe: Probe = probe_https,
    sleeper: Callable[[float], None] = time.sleep,
    logger: Callable[[str], None] | None = None,
) -> str:
    retry_delays = tuple(delays)
    if not retry_delays:
        raise ValueError("at least one connectivity attempt is required")
    last_error: Exception | None = None
    for attempt, delay in enumerate(retry_delays, start=1):
        if delay:
            sleeper(delay)
        for route_name, route_url in (("proxy", proxy_url), ("direct", None)):
            if route_name == "proxy" and route_url is None:
                continue
            if logger:
                logger(f"network attempt={attempt}/{len(retry_delays)} route={route_name}")
            try:
                probe(url, route_url)
            except Exception as error:
                last_error = error
                if logger:
                    logger(
                        f"network unavailable route={route_name} error={type(error).__name__}"
                    )
            else:
                if logger:
                    logger(f"network ready route={route_name}")
                return route_url or "DIRECT"
    error_name = type(last_error).__name__ if last_error else "unknown"
    raise NetworkUnavailable(
        f"GitHub unavailable after {len(retry_delays)} attempts ({error_name})"
    )


def log(message: str) -> None:
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    print(f"[{timestamp}] stage=preflight {message}", file=sys.stderr, flush=True)


def main() -> int:
    try:
        proxy_url = configured_https_proxy()
    except (OSError, subprocess.SubprocessError):
        proxy_url = None
        log("proxy detection failed; direct fallback enabled")
    try:
        selected_route = wait_for_connectivity(proxy_url=proxy_url, logger=log)
    except NetworkUnavailable as error:
        log(str(error))
        return 1
    print(selected_route)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
