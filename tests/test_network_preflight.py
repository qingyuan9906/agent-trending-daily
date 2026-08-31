import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "network_preflight.py"
SPEC = importlib.util.spec_from_file_location("network_preflight", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
network_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(network_preflight)

NetworkUnavailable = network_preflight.NetworkUnavailable
parse_https_proxy = network_preflight.parse_https_proxy
wait_for_connectivity = network_preflight.wait_for_connectivity


def test_parse_enabled_https_proxy():
    output = """
    HTTPSEnable : 1
    HTTPSPort : 7890
    HTTPSProxy : 127.0.0.1
    """

    assert parse_https_proxy(output) == "http://127.0.0.1:7890"


def test_disabled_or_invalid_proxy_uses_direct_mode():
    assert parse_https_proxy("HTTPSEnable : 0\nHTTPSProxy : 127.0.0.1\nHTTPSPort : 7890") is None
    assert parse_https_proxy("HTTPSEnable : 1\nHTTPSProxy : bad/value\nHTTPSPort : 7890") is None


def test_proxy_is_preferred_when_available():
    calls = []

    def probe(url, proxy_url):
        calls.append((url, proxy_url))

    selected = wait_for_connectivity(
        proxy_url="http://127.0.0.1:7890",
        delays=(0,),
        probe=probe,
    )

    assert selected == "http://127.0.0.1:7890"
    assert calls == [("https://github.com/", "http://127.0.0.1:7890")]


def test_direct_route_is_used_when_proxy_probe_fails():
    calls = []

    def probe(_url, proxy_url):
        calls.append(proxy_url)
        if proxy_url is not None:
            raise OSError("proxy unavailable")

    selected = wait_for_connectivity(
        proxy_url="http://127.0.0.1:7890",
        delays=(0,),
        probe=probe,
    )

    assert selected == "DIRECT"
    assert calls == ["http://127.0.0.1:7890", None]


def test_dns_failure_recovers_on_later_attempt():
    direct_attempts = 0
    sleeps = []

    def probe(_url, _proxy_url):
        nonlocal direct_attempts
        direct_attempts += 1
        if direct_attempts < 3:
            raise OSError("temporary DNS failure")

    selected = wait_for_connectivity(
        proxy_url=None,
        delays=(0, 5, 10),
        probe=probe,
        sleeper=sleeps.append,
    )

    assert selected == "DIRECT"
    assert sleeps == [5, 10]


def test_retry_exhaustion_reports_only_error_type():
    messages = []

    def probe(_url, _proxy_url):
        raise OSError("DASHSCOPE_API_KEY=do-not-log")

    with pytest.raises(NetworkUnavailable, match=r"after 2 attempts \(OSError\)"):
        wait_for_connectivity(
            proxy_url=None,
            delays=(0, 0),
            probe=probe,
            sleeper=lambda _delay: None,
            logger=messages.append,
        )

    assert "do-not-log" not in "\n".join(messages)
