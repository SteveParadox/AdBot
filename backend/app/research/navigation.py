"""Read-only semantic links for research, never general browser actions."""

import re
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from .policy import PublicPolicy, canonical_key
from .search import terms

# Conservative navigation: do not follow commercial actions, account routes,
# sponsored links or arbitrary query strings, even if the method is GET.
UNSAFE = re.compile(
    r"(?:^|[\W_])(ads?|advert(?:ising|isement)?|sponsored|promoted|affiliate|"
    r"cart|basket|checkout|buy|purchase|order|payment|subscribe|unsubscribe|"
    r"login|logout|signin|signout|account|admin|register|delete|remove|"
    r"update|edit|submit|download|track|pixel|redirect|share|vote)(?:$|[\W_])", re.I,
)


def safe_link(base, href, label, rel=""):
    if not isinstance(href, str) or not isinstance(label, str) or not href or not label.strip():
        return None
    if (len(href) > 1000 or any(ord(char) < 32 for char in href) or "\\" in href
            or UNSAFE.search(label) or UNSAFE.search(rel)):
        return None
    if href.startswith("#") or "nofollow" in rel.casefold().split():
        return None
    try:
        url = PublicPolicy().check(urljoin(base, href))
        origin, target = urlsplit(base), urlsplit(url)
        if (origin.scheme, origin.netloc) != (target.scheme, target.netloc):
            return None
        decoded = unquote(target.path)
        if '%' in decoded or '\\' in decoded or UNSAFE.search(decoded) or canonical_key(url) == canonical_key(base):
            return None
        # Only explicit numeric pagination is allowed on discovered links.
        params = parse_qsl(target.query, keep_blank_values=True)
        if target.query and (len(params) != 1 or not all(
            k in {"page", "p"} and re.fullmatch(r"[1-9]\d{0,2}", v) for k, v in params
        )):
            return None
        return {"url": canonical_key(url), "label": " ".join(label.split())[:200], "rel": rel[:100]}
    except (ValueError, TypeError):
        return None


def static_links(tree, base):
    result = {}
    for node in tree.xpath("//main//a[@href] | //article//a[@href] | //*[@role='main']//a[@href]")[:150]:
        if node.xpath("ancestor-or-self::*[@hidden or @aria-hidden='true' or @inert or @download or @onclick or @data-ad]"):
            continue
        if node.xpath("ancestor::form | ancestor::aside"):
            continue
        context = " ".join(str(value) for value in node.xpath(
            "ancestor-or-self::*/@class | ancestor-or-self::*/@id | ancestor-or-self::*/@aria-label"
        ))
        if UNSAFE.search(context):
            continue
        label = node.get("aria-label") or " ".join(node.itertext()) or node.get("title") or ""
        link = safe_link(base, node.get("href"), label, node.get("rel", ""))
        if link:
            result.setdefault(link["url"], link)
        if len(result) >= 30:
            break
    return list(result.values())


def rank_links(links, objective, shopping=False):
    keywords = terms(objective)
    scored = []
    for link in links:
        words = terms(link["label"] + " " + unquote(urlsplit(link["url"]).path))
        overlap = len(keywords & words)
        pagination = "next" in link["rel"].casefold().split() or bool(
            re.fullmatch(r"(?:next(?: page)?|page [1-9]\d{0,2})", link["label"].strip(), re.I)
        )
        if overlap or (shopping and pagination):
            scored.append((overlap, pagination, link["url"], link))
    return [row[-1] for row in sorted(scored, key=lambda row: (-row[0], row[1], row[2]))]
