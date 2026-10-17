"""Default-deny URL policy. The egress proxy pins connections to validated IPs."""

import asyncio
import fnmatch
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from .config import settings


class PolicyError(ValueError):
    pass


def normalize(url: str) -> str:
    if len(url.encode("utf-8")) > 1800 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise PolicyError("Invalid URL")
    try:
        p = urlsplit(url)
        host = (p.hostname or "").encode("idna").decode().lower().rstrip(".")
        port = p.port
    except (ValueError, UnicodeError) as exc:
        raise PolicyError("Invalid URL") from exc
    if p.scheme not in {"http", "https"} or not host or p.username or p.password:
        raise PolicyError("Only HTTP(S) URLs without credentials are allowed")
    authority = f"[{host}]" if ":" in host else host
    if port and (p.scheme, port) not in {("http", 80), ("https", 443)}:
        authority += f":{port}"
    return urlunsplit((p.scheme.lower(), authority, p.path or "/", p.query, ""))


def domain_match(host: str, pattern: str) -> bool:
    return host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:]) and host != pattern[2:])


class Policy:
    def __init__(self, domains: list[str], config: dict | None = None):
        self.domains = domains
        self.config = config or {}

    def check(self, url: str, navigation=True) -> str:
        url = normalize(url)
        p = urlsplit(url)
        if not any(domain_match(p.hostname, d) for d in self.domains):
            raise PolicyError("Destination is outside the target allowlist")
        admin = [d.strip().lower() for d in settings().authorized_domains.split(",") if d.strip()]
        fixture = settings().fixture_mode and p.hostname == "127.0.0.1" and p.port == settings().fixture_port
        if admin and not fixture and not any(domain_match(p.hostname, d) for d in admin):
            raise PolicyError("Destination is not authorized by the server operator")
        if not fixture and p.port not in {None, 80, 443}:
            raise PolicyError("Only ports 80 and 443 are allowed")
        if navigation:
            allowed = self.config.get("allowed_patterns", ["*"])
            excluded = self.config.get("excluded_patterns", [])
            if not any(fnmatch.fnmatchcase(url, x) for x in allowed) or any(
                fnmatch.fnmatchcase(url, x) for x in excluded
            ):
                raise PolicyError("URL excluded by target patterns")
        return url

    async def resolve(self, url: str) -> list[str]:
        p = urlsplit(self.check(url, navigation=False))
        if settings().fixture_mode and p.hostname == "127.0.0.1" and p.port == settings().fixture_port:
            return ["127.0.0.1"]
        try:
            records = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM
                ),
                10,
            )
            ips = list(dict.fromkeys(r[4][0] for r in records))
        except (OSError, TimeoutError) as exc:
            raise PolicyError("DNS resolution failed") from exc
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise PolicyError("Private, loopback, link-local and reserved destinations are blocked")
        return ips
