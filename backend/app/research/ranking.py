"""Explainable relevance, source signals, and conservative independence groups.

Scores are retrieval heuristics, not probabilities of factual correctness.
No external reputation service or additional model dependency is required.
"""

import hashlib
import math
import re
from collections import Counter
from urllib.parse import unquote, urlsplit

from courlan import extract_domain

STOP = set("what which where about latest for from with this that those more have find will when were would your best the and of to in is are a an on by how".split())
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
GOVERNMENT = re.compile(r"(?:^|\.)(?:gov|gouv)(?:\.[a-z]{2})?$")
ACADEMIC = re.compile(r"(?:^|\.)(?:edu|ac)(?:\.[a-z]{2})?$")


def tokens(text):
    return [word for word in TOKEN.findall(str(text).casefold()[:24000])
            if word not in STOP and (len(word) >= 2 or word.isdigit())]


def domain_group(url):
    return extract_domain(url, fast=False, blacklist=None) or urlsplit(url).hostname or ""


def source_signals(url, metadata=None, technical=False):
    """Only observable signals. A self-declared publisher is not verified identity."""
    metadata = metadata or {}
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path).casefold()
    signals = []
    score = 0.0
    role = "unclassified"
    if GOVERNMENT.search(host):
        signals.append("government namespace")
        role, score = "government_namespace", 0.12
    elif ACADEMIC.search(host):
        signals.append("academic namespace")
        role, score = "academic_namespace", 0.09
    elif technical and (host.startswith("docs.") or re.search(r"/(?:docs|documentation|reference)(?:/|$)", path)):
        signals.append("documentation path or hostname")
        role, score = "documentation_candidate", 0.06
    elif technical and host == "github.com":
        signals.append("repository hosting platform")
        role, score = "repository_candidate", 0.04
    if metadata.get("author"):
        signals.append("publisher-declared byline")
        score += 0.015
    if metadata.get("published_date_observed"):
        signals.append("publisher-declared publication date")
        score += 0.015
    if metadata.get("document_type") == "pdf":
        signals.append("document with page provenance")
    if metadata.get("extraction_truncated"):
        signals.append("incomplete extraction")
        score -= 0.03
    if metadata.get("sponsored_marker"):
        signals.append("publisher-declared commercial content")
        score -= 0.12
    return {"role_hint": role, "signals": signals, "ranking_adjustment": round(score, 3),
            "assessment": "heuristic_not_verified"}


def lexical_scores(objective, texts):
    """Bounded BM25-style scoring with query coverage and phrase proximity."""
    query = list(dict.fromkeys(tokens(objective)))[:80]
    documents = [tokens(text) for text in texts]
    if not query or not documents:
        return [0.0] * len(documents)
    counts = [Counter(doc) for doc in documents]
    n = len(documents)
    average = max(1.0, sum(map(len, documents)) / n)
    df = Counter(word for counter in counts for word in query if word in counter)
    weights = {word: math.log(1 + (n - df[word] + .5) / (df[word] + .5)) for word in query}
    total_weight = sum(weights.values()) or 1
    result = []
    for doc, counter in zip(documents, counts):
        normalizer = 1.2 * (.25 + .75 * len(doc) / average)
        bm = sum(weights[w] * counter[w] * 2.2 / (counter[w] + normalizer)
                 for w in query if counter[w]) / (2.2 * total_weight)
        coverage = sum(weights[w] for w in query if counter[w]) / total_weight
        bigrams = set(zip(doc, doc[1:]))
        pairs = list(zip(query, query[1:]))
        proximity = sum(pair in bigrams for pair in pairs) / max(1, len(pairs))
        result.append(.55 * bm + .35 * coverage + .10 * proximity)
    return result


def fingerprint(blocks):
    # Keep numeric tokens and stopwords: changing a statistic or negation
    # must not be mistaken for exact identity. Ignore short shared boilerplate.
    text = " ".join(blocks)[:48000].casefold()
    words = TOKEN.findall(text)[:8000]
    if len(words) < 80:
        return None
    shingles = frozenset(tuple(words[i:i + 5]) for i in range(len(words) - 4))
    if len(shingles) < 40:
        return None
    return shingles


def near_copy(left, right):
    if not left or not right:
        return False
    common = len(left & right)
    # Both substantial overlap and coverage of the smaller document are
    # needed. Short quotations and shared topic vocabulary alone do not count.
    return common >= 40 and common / len(left | right) >= .76 and common / min(len(left), len(right)) >= .90


class Independence:
    """Task-local union-find. Same registrable domain or substantial copied text.

    Group names remain stable for ordinary domain groups; merging is transitive.
    Distinct groups are potential independence, not confirmed editorial ownership.
    """

    def __init__(self):
        self.parents = {}
        self.fingerprints = {}
        self.domains = {}

    def root(self, value):
        self.parents.setdefault(value, value)
        while self.parents[value] != value:
            self.parents[value] = self.parents[self.parents[value]]
            value = self.parents[value]
        return value

    def union(self, a, b):
        a, b = self.root(a), self.root(b)
        if a != b:
            first, second = sorted((a, b))
            self.parents[second] = first

    def add(self, source, blocks, *, compare_content=True):
        identifier = source["id"]
        domain = domain_group(source["url"])
        self.domains[identifier] = domain
        self.root(domain)
        current = fingerprint(blocks) if compare_content else None
        if current:
            for other, prior in self.fingerprints.items():
                if near_copy(current, prior):
                    self.union(domain, self.domains[other])
            self.fingerprints[identifier] = current

    def apply(self, sources):
        for source in sources.values():
            identifier = source["id"]
            if identifier not in self.domains:
                continue
            domain = self.domains[identifier]
            group = self.root(domain)
            source["independence_group"] = group
            source["independence_assessment"] = {
                "registrable_domain": domain,
                "possible_shared_origin": any(other != domain and self.root(other) == group
                                              for other in set(self.domains.values())),
                "method": "domain_and_text_similarity",
            }


def supporting_groups(ids, evidence, sources):
    """Copied claim-level excerpts cannot independently corroborate a claim.

    Do not treat shared structured product fields as copied articles.
    """
    union = Independence()
    groups = set()
    seen = {}
    for identifier in ids:
        row = evidence[identifier]
        group = sources[row["source_id"]]["independence_group"]
        groups.add(group)
        union.root(group)
        quote = row["quote"]
        words = TOKEN.findall(quote.casefold())
        if row.get("kind") != "structured" and len(words) >= 12:
            normalized = " ".join(words)
            key = hashlib.sha256(normalized.encode()).hexdigest()
            if key in seen:
                union.union(group, seen[key])
            else:
                seen[key] = group
    return {union.root(group) for group in groups}
