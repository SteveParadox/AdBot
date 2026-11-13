import asyncio
import socket
from datetime import datetime, timezone

import httpx
import pytest

from app.browser import retry_delay
from app.egress import egress_proxy
from app.jobs import next_occurrence
from app.security import Policy, PolicyError, normalize


def test_normalization_and_domain_boundaries():
    assert normalize("https://EXAMPLE.com:443/a#fragment") == "https://example.com/a"
    policy = Policy(["example.com", "*.example.com"])
    assert policy.check("https://docs.example.com/")
    for url in [
        "https://example.com.evil.org/",
        "https://evil-example.com/",
        "http://example.com:8080/",
        "javascript:alert(1)",
        "https://example.com\\@evil.org/",
    ]:
        with pytest.raises(PolicyError):
            policy.check(url)


async def test_dns_mixed_private_addresses_denied(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ["8.8.8.8", "127.0.0.1"]]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(PolicyError):
        await Policy(["example.com"]).resolve("https://example.com/")


async def test_proxy_denies_non_allowlisted_destinations():
    async with egress_proxy(Policy(["example.com"])) as proxy:
        async with httpx.AsyncClient(proxy=proxy, trust_env=False) as client:
            result = await client.get("http://169.254.169.254/")
            assert result.status_code == 403
            result = await client.post("http://example.com/", content="mutation")
            assert result.status_code == 403


def test_retry_after_and_timezone_schedule():
    assert retry_delay("120", 1) == 120
    # The existing retry implementation applies bounded jitter to the exponential delay.
    assert 6.4 <= retry_delay(None, 3) <= 9.6
    base = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc).timestamp()
    assert datetime.fromtimestamp(next_occurrence("0 8 * * *", "Africa/Lagos", base), timezone.utc).hour == 7
