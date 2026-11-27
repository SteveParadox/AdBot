"""Interpret read-side objectives and select a strategy without granting permissions."""
from dataclasses import dataclass
import re

from pydantic import Field

from ..schemas import Strict


@dataclass(frozen=True)
class ExecutionRoute:
    name: str
    guidance: str
    entity: str | None = None


_EXHAUSTIVE = {"all", "every", "each", "complete", "comprehensive", "exhaustive", "entire"}
_INVENTORY = {"list", "collect", "show", "find", "give", "provide", "extract", "catalog", "catalogue", "inventory", "enumerate",
              "identify", "surface", "rundown"}
_FRAME = _EXHAUSTIVE | _INVENTORY | {"a", "an", "the", "me", "of", "please", "could", "can", "you", "for", "out"}
_ALIASES = {
    "ai chatbots": ("ai chatbot", "ai chatbots", "chatbot", "chatbots", "conversational ai", "conversational ai platform",
                    "conversational ai platforms", "conversational ai tools", "conversational agents", "conversational agent",
                    "ai conversational agents", "language model interfaces"),
    "ai tools": ("ai tool", "ai tools", "ai products"),
    "products": ("products", "product"),
    "directory entries": ("directory entries", "directory listings", "directory records"),
    "articles": ("articles", "article", "published articles"),
    "prompts": ("prompts", "prompt", "ai prompts", "prompt templates"),
    "table rows": ("rows", "table rows", "rows in the table", "rows from the table", "rows in this table",
                   "table records", "table data", "tables", "data in the table"),
}

_KINDS = {
    "prompts": {"prompts"}, "articles": {"articles"}, "products": {"products"},
    "ai tools": {"tools", "products"}, "ai chatbots": {"tools", "products"}, "table rows": {"rows"},
    "guides": {"guides"}, "reviews": {"reviews"}, "rankings": {"rankings"}, "collections": {"collections"},
}
_NOUNS = {kind: singular for kind, singular in (
    ("prompts", "prompt"), ("articles", "article"), ("products", "product"), ("tools", "tool"),
    ("guides", "guide"), ("reviews", "review"), ("rankings", "ranking"), ("collections", "collection"),
)}
_SCOPE_MODIFIERS = {
    "and", "or", "except", "only", "without", "excluding", "not", "under", "over", "between", "before", "after",
    "then", "sort", "rank", "compare", "download", "latest", "top", "send", "submit", "delete", "extract", "list",
}


def words(value):
    return re.findall(r"[^\W_]+", value.casefold())


def requested_operation(objective):
    tokens = words(objective)
    prefix = {"please", "could", "would", "can", "you", "me", "a", "the"}
    leading = next((token for token in tokens if token not in prefix), "")
    if leading in {"list", "enumerate", "catalog", "catalogue", "collect", "extract", "inventory"} or re.match(
        r"\s*(?:please\s+)?(?:give|show|provide)\s+(?:me\s+)?(?:a\s+|the\s+)?list\b", objective, re.I,
    ):
        return "enumeration"
    if leading in {"rank", "recommend"} or (
        re.match(r"\s*(?:what|which)\s+(?:are|is)\b", objective, re.I)
        and set(tokens) & {"best", "top", "recommended"}
    ):
        return "recommendation"
    if (leading == "compare" or (leading == "comparison" and set(tokens) & {"of", "between"})
            or (leading not in _INVENTORY and "versus" in tokens)):
        return "comparison"
    return None


def exhaustive_request(objective):
    terms = set(words(objective))
    return bool(terms & _EXHAUSTIVE and terms & _INVENTORY)


def task_text_only(objective, options):
    return options.get("output_format") in {None, "answer"} and all(
        words(criterion) == words(objective) for criterion in options.get("success_criteria", [])
    )


def directory_intent(objective, options, has_dataset=False):
    if has_dataset or not task_text_only(objective, options) or not exhaustive_request(objective):
        return None
    terms = words(objective)
    for entity, aliases in _ALIASES.items():
        for alias in aliases:
            phrase = words(alias)
            for index in range(len(terms) - len(phrase) + 1):
                if terms[index:index + len(phrase)] == phrase and set(terms[:index] + terms[index + len(phrase):]) <= _FRAME:
                    return entity
    # A bounded adjective/noun phrase can identify a record type and a topic
    # without asking the model. Leave constraints and multiple goals to planning.
    phrase = [term for term in terms if term not in _FRAME]
    if (2 <= len(phrase) <= 4 and collection_kinds("semantic:" + " ".join(phrase))
            and not set(phrase) & _SCOPE_MODIFIERS and not any(term.isdigit() for term in phrase)):
        start = terms.index(phrase[0])
        if terms[start:start + len(phrase)] == phrase:
            return "semantic:" + " ".join(phrase)
    return None


def collection_kinds(entity):
    if not entity:
        return set()
    if entity in _KINDS:
        return _KINDS[entity]
    terms = words(entity.removeprefix("semantic:"))
    if entity.startswith("semantic:") and terms:
        # Software role nouns describe candidate product records, not a distinct
        # directory type. Individual capabilities must still be verified.
        if "ai" in terms and terms[-1] in {
            "bot", "bots", "generator", "generators", "assistant", "assistants",
            "app", "apps", "application", "applications", "platform", "platforms",
        }:
            return {"tools", "products"}
        for kind, singular in _NOUNS.items():
            if terms[-1] in {kind, singular}:
                return {"tools", "products"} if kind == "tools" else {kind}
    return set()


def collection_topic(entity):
    if not entity.startswith("semantic:"):
        return ""
    terms = words(entity.removeprefix("semantic:"))
    return " ".join(terms[:-1] if collection_kinds(entity) else terms)


def semantic_terms(value):
    """Normalize conservative action-word variants, without dropping scope terms."""
    aliases = {
        "create": "generate", "creates": "generate", "creating": "generate",
        "creation": "generate", "generation": "generate", "generating": "generate",
        "generates": "generate", "generator": "generate", "generators": "generate",
        "images": "image", "videos": "video", "documents": "document",
    }
    return {aliases.get(term, term) for term in words(value)}


def inventory_route(entity):
    name = "table_extraction" if entity == "table rows" else "directory_collection"
    kinds = ", ".join(sorted(collection_kinds(entity)))
    subject = entity.removeprefix("semantic:")
    discovery = (f"Find an authorized catalog of {kinds} relevant to {subject}." if kinds else
                 f"Find an authorized catalog with records potentially relevant to {subject}.")
    return ExecutionRoute(name, discovery + " Inspect candidate records using observed descriptions and capabilities; "
                          "verify record type and coverage separately. Never infer completeness from a related heading.", entity)


class RouteAssessment(Strict):
    exhaustive_inventory: bool
    entity_phrase: str = Field(max_length=160)


class InformationalAssessment(Strict):
    informational: bool
    subject: str = Field(max_length=160)


def ambiguous_subject(objective):
    """A bare subject may be a lookup or shorthand for an unspecified operation."""
    return (bool(re.fullmatch(r"[\w][\w .+-]{0,159}", objective.strip()))
            and 1 <= len(words(objective)) <= 6
            and not set(words(objective)) & (_INVENTORY | _SCOPE_MODIFIERS | _EXHAUSTIVE
                                             | {"login", "password", "buy", "pay", "register", "upload", "open"}))


def assessed_entity(objective, assessment):
    """A model may locate literal wording. Deterministic checks still own eligibility."""
    phrase = assessment.entity_phrase.strip()
    if not assessment.exhaustive_inventory or not phrase or not exhaustive_request(objective):
        return None
    before, found, after = objective.casefold().partition(phrase.casefold())
    if not found or not re.fullmatch(r"[\w -]+", phrase) or len(words(phrase)) > 8:
        return None
    if set(words(before + " " + after)) - _FRAME:
        return None
    if set(words(phrase)) & _SCOPE_MODIFIERS or any(word.isdigit() for word in words(phrase)):
        return None
    # Require evidence-based filtering for inferred entity types. Do not treat
    # the directory contents themselves as proof that they match this phrase.
    return "semantic:" + phrase


def informational_question(objective):
    return bool(re.match(
        r"\s*(?:please\s+)?(?:tell me about|what (?:is|are|does)|how (?:does|do|much|many)"
        r"|who (?:developed|created|built|makes|made|is)|where (?:can|do|is|are)"
        r"|is|are)\s+\S", objective, re.I,
    ))


def execution_intent(objective):
    """Advisory routing metadata. The original specification remains authoritative."""
    hints = (
        ("form_interaction", r"\b(?:fill|submit|register|sign up)\b"),
        ("document_retrieval", r"\b(?:download|retrieve)\b.*\b(?:file|document|pdf)\b"),
        ("comparison", r"\b(?:compare|versus)\b|\bcomparison\s+(?:of|between)\b"),
        ("structured_extraction", r"\b(?:list|collect|extract)\b"),
        ("search", r"\b(?:search|find|look up)\b"),
        ("research", r"\b(?:research|summarize|explain|verify)\b"),
        ("navigation", r"\b(?:navigate|open|visit|go to)\b"),
    )
    operation = requested_operation(objective)
    strategy = {"enumeration": "structured_extraction", "comparison": "comparison",
                "recommendation": "research"}.get(operation) or ("informational" if informational_question(objective) else None) or next(
        (name for name, pattern in hints if re.search(pattern, objective, re.I)), "general",
    )
    quantifiers = re.findall(
        r"\b(?:all|every|first|latest|cheapest|highest rated|at least \d+|exactly \d+|between \d+ and \d+)\b",
        objective, re.I,
    )
    return {"category": strategy, "quantifiers": list(dict.fromkeys(word.casefold() for word in quantifiers))}


def select_route(objective, options, has_dataset=False):
    entity = directory_intent(objective, options, has_dataset)
    if entity:
        return inventory_route(entity)
    terms = set(words(objective))
    operation = requested_operation(objective)
    if has_dataset or options.get("output_format") in {"json", "csv"}:
        return ExecutionRoute("configured_extraction", "Use the configured dataset phases and verify the requested record scope and export.")
    if (terms & {"then", "afterwards"} or ("workflow" in terms and not operation)
            or re.search(r"\band\s+(?:submit|send|register|sign up|purchase|delete|upload)\b", objective, re.I)):
        return ExecutionRoute("workflow", "Execute the ready step and preserve its dependencies. Verify each requested outcome.")
    if operation == "enumeration":
        if exhaustive_request(objective):
            return ExecutionRoute("general", "Discover the requested record structure and establish exhaustive source coverage before completion.")
        return ExecutionRoute("enumeration", "Inspect authorized sources and capture coherent candidate records before further navigation. "
                              "Classify each candidate using its own observed purpose or category. "
                              "A similar category name, mention or related article does not establish membership. "
                              "Prefer new information over repeated scrolling; do not infer exhaustive coverage.")
    if operation == "comparison":
        return ExecutionRoute("comparison", "Gather independent sources for each entity and requested criterion. Identify missing evidence for either side.")
    if operation == "recommendation":
        return ExecutionRoute("research", "Gather relevant options and compare their observed merits against the requested ranking or recommendation criteria.")
    intent = execution_intent(objective)["category"]
    if intent == "informational":
        return ExecutionRoute("informational", "Find a relevant authorized source and answer with verified passages.")
    if intent == "document_retrieval":
        return ExecutionRoute(intent, "Locate the observed document link, confirm identity, and use DOWNLOAD only when requested and authorized.")
    if intent == "form_interaction":
        return ExecutionRoute(intent, "Resolve the visible input and honor form permissions and approval gates. Verify the observed outcome.")
    if intent in {"research", "search"}:
        return ExecutionRoute("research", "Find relevant evidence, distinguish direct observations from inference, and cite each supported answer.")
    if intent == "navigation":
        return ExecutionRoute(intent, "Prefer a uniquely relevant observed link and verify the destination.")
    return ExecutionRoute("general", "Follow the original requirements and available controls.")
