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
        for kind, singular in _NOUNS.items():
            if terms[-1] in {kind, singular}:
                return {"tools", "products"} if kind == "tools" else {kind}
    return set()


def collection_topic(entity):
    if not entity.startswith("semantic:") or not collection_kinds(entity):
        return ""
    return " ".join(words(entity.removeprefix("semantic:"))[:-1])


def inventory_route(entity):
    name = "table_extraction" if entity == "table rows" else "directory_collection"
    kinds = ", ".join(sorted(collection_kinds(entity)))
    subject = entity.removeprefix("semantic:")
    discovery = (f"Find an authorized catalog of {kinds} relevant to {subject}." if kinds else
                 f"Find an authorized catalog explicitly identifying its records as {subject}.")
    return ExecutionRoute(name, discovery + " Verify the source type before collecting records.", entity)


class RouteAssessment(Strict):
    exhaustive_inventory: bool
    entity_phrase: str = Field(max_length=160)


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


def select_route(objective, options, has_dataset=False):
    entity = directory_intent(objective, options, has_dataset)
    if entity:
        return inventory_route(entity)
    terms = set(words(objective))
    if has_dataset or options.get("output_format") in {"json", "csv"}:
        return ExecutionRoute("configured_extraction", "Use the configured dataset phases and verify the requested record scope and export.")
    if terms & {"then", "workflow", "afterwards"}:
        return ExecutionRoute("workflow", "Execute the ready step and preserve its dependencies. Verify each requested outcome.")
    if terms & {"compare", "comparison", "versus"}:
        return ExecutionRoute("comparison", "Gather independent sources for each entity and requested criterion. Identify missing evidence for either side.")
    if terms & {"download", "pdf", "document", "retrieve"}:
        return ExecutionRoute("document_retrieval", "Locate the observed document link, confirm identity, and use DOWNLOAD only when requested and authorized.")
    if terms & {"fill", "submit", "register"}:
        return ExecutionRoute("form_interaction", "Resolve the visible input and honor form permissions and approval gates. Verify the observed outcome.")
    if terms & {"research", "summarize", "explain", "verify", "cite", "find", "search"}:
        return ExecutionRoute("research", "Find relevant evidence, distinguish direct observations from inference, and cite each supported answer.")
    if terms & {"navigate", "open", "visit"}:
        return ExecutionRoute("navigation", "Prefer a uniquely relevant observed link and verify the destination.")
    return ExecutionRoute("general", "Follow the original requirements and available controls.")
