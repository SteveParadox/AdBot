"""Read-only public source policy, independent of website-agent authorization."""

import asyncio
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import settings
from ..security import PolicyError, domain_match, normalize


def public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved or getattr(address, "scope_id", None):
        return False
    if address.version == 6:
        # Public sources can use native global IPv6. Reject translation and
        # tunneling prefixes whose embedded destination may be non-public.
        return address in ipaddress.ip_network("2000::/3") and address not in ipaddress.ip_network("2002::/16")
    return True


AUTH_QUERY_KEYS = {
    "access_token", "api_key", "apikey", "auth", "authorization", "jwt", "password",
    "secret", "session", "session_id", "signature", "token", "x-amz-signature", "x-goog-signature",
}


class PublicPolicy:
    def check(self, url, navigation=True):
        if not isinstance(url, str) or any(char in url for char in "<>"):
            raise PolicyError("Invalid public URL")
        raw = urlsplit(url)
        if raw.username is not None or raw.password is not None or raw.port == 0:
            raise PolicyError("Unsafe public URL authority")
        value = normalize(url)
        parsed = urlsplit(value)
        host = parsed.hostname
        if any(key.casefold() in AUTH_QUERY_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise PolicyError("Credential-bearing research URL is forbidden")
        if "%" in host or parsed.port not in (None, 80 if parsed.scheme == "http" else 443):
            raise PolicyError("Research requires standard public HTTP(S) ports")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or len(host) > 253 or
                    not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))
                    or host.split(".")[-1].isdigit() or host.endswith((".local", ".internal", ".localhost", ".test"))):
                raise PolicyError("Research requires a public DNS name")
        else:
            if not public_ip(str(literal)):
                raise PolicyError("Forbidden address")
        excluded = [domain.strip().lower() for domain in settings().research_excluded_domains.split(",") if domain.strip()]
        if any(domain_match(host, domain) for domain in excluded):
            raise PolicyError("Research destination excluded by operator")
        return value

    async def resolve(self, url):
        parsed = urlsplit(self.check(url))
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                parsed.hostname, 443 if parsed.scheme == "https" else 80, type=socket.SOCK_STREAM
            ), 5
        )
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or not all(public_ip(address) for address in addresses):
            raise PolicyError("Research DNS returned a forbidden destination")
        return addresses


def canonical_key(url):
    parsed = urlsplit(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(k, v) for k, v in params if not k.casefold().startswith("utm_")
            and k.casefold() not in {"gclid", "fbclid", "msclkid"}]
    return urlunsplit(parsed._replace(query=urlencode(kept), fragment=""))
