"""Phrasing service (ai-routing.md sections 2, 6, 7): Haiku turns facts into one or two natural sentences.

Facts and numbers never pass through the model as values to copy: the model writes ``{{a1}}`` placeholders and
the server substitutes the fact text. The validator then requires that the model wrote no numerals of its own,
preserved currency codes, took proper nouns only from the facts or the template, introduced no dates and kept to
at most two sentences. On any failure (or a refusal, an outage, an open circuit, a quota) the deterministic
template text is used and labelled **"Standard wording"**.

Results are cached by a fact hash (facts + template code + template version + language) in
``agents_phrasing_cache``; unchanged items never regenerate. Pre-shift phrasing uses Message Batches
(``submit_batch`` / ``collect_batch``; results keyed by ``custom_id`` in any order). The Demo phraser implements
the same interface deterministically, so the briefings lane consumes one API in both modes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,15})\s*\}\}")
STANDARD_WORDING = "Standard wording"
PHRASING_PROMPT_VERSION = "phrasing.v1"
MAX_SENTENCES = 2
FactKind = Literal["money", "quantity", "count", "date", "name", "text"]
PhrasingKind = Literal["phrasing", "narration", "explain", "notification"]

_DIGIT = re.compile(r"\d")
_CURRENCY = re.compile(r"\b[A-Z]{3}\b")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_RELATIVE_DATES = ("today", "tomorrow", "yesterday", "tonight", "next week", "last week", "this week")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
#: capitalised words that are not proper nouns when they appear mid-sentence
_COMMON_CAPITALS = frozenset({"I", "OK"})


@dataclass(frozen=True)
class Fact:
    """One fact the sentence may mention, by placeholder key (``a1``...). ``text`` is what the server substitutes."""

    key: str
    text: str
    kind: FactKind = "text"
    currency: str | None = None
    #: what the fact is ("quote total", "customer"); shown to the model instead of the value for money and dates
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "text": self.text, "kind": self.kind, "currency": self.currency, "label": self.label}


@dataclass(frozen=True)
class PhraseRequest:
    template_code: str
    #: the deterministic sentence with ``{{key}}`` placeholders (also the fallback)
    template: str
    facts: tuple[Fact, ...]
    template_version: int = 1
    language: str = "en"
    kind: PhrasingKind = "phrasing"
    #: optional style hint for the model ("warm, brief"); never facts
    tone: str = ""

    @property
    def fact_map(self) -> dict[str, Fact]:
        return {f.key: f for f in self.facts}


@dataclass(frozen=True)
class PhraseResult:
    text: str
    #: ``model`` (validated model output), ``template`` (the deterministic text, labelled "Standard wording")
    source: Literal["model", "template"]
    fact_hash: str
    cached: bool = False
    model: str = ""
    failures: tuple[str, ...] = ()

    @property
    def label(self) -> str | None:
        return STANDARD_WORDING if self.source == "template" else None

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source": self.source, "label": self.label, "fact_hash": self.fact_hash,
                "cached": self.cached, "model": self.model, "failures": list(self.failures)}


@dataclass
class Validation:
    ok: bool
    text: str
    failures: list[str] = field(default_factory=list)


# ---- hashing and rendering -----------------------------------------------------------------------------------------
def fact_hash(request: PhraseRequest) -> str:
    payload = {
        "template_code": request.template_code, "template_version": request.template_version,
        "language": request.language, "kind": request.kind, "template": request.template,
        "facts": sorted((f.as_dict() for f in request.facts), key=lambda d: d["key"]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def substitute(text: str, facts: Mapping[str, Fact]) -> tuple[str, list[str]]:
    """Replace ``{{key}}`` by the fact text; unknown keys are returned (and left visible as a failure)."""
    unknown: list[str] = []

    def repl(match: re.Match[str]) -> str:
        fact = facts.get(match.group(1))
        if fact is None:
            unknown.append(match.group(1))
            return match.group(0)
        return fact.text

    return PLACEHOLDER.sub(repl, text), unknown


def render_template(request: PhraseRequest) -> str:
    text, _ = substitute(request.template, request.fact_map)
    return text


def _sentences(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    count = len(_SENTENCE_END.findall(stripped))
    return count if stripped[-1] in ".!?" else count + 1


def _proper_nouns(raw: str) -> set[str]:
    """Capitalised words that do not start a sentence (outside placeholders)."""
    nouns: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", PLACEHOLDER.sub(" ", raw).strip()):
        words = _WORD.findall(sentence)
        for word in words[1:]:
            if word[0].isupper() and word not in _COMMON_CAPITALS:
                nouns.add(word)
    return nouns


def validate(raw: str, request: PhraseRequest) -> Validation:
    """Section 6: numerals only from facts, currency codes preserved, proper nouns from facts, no new dates, ≤2
    sentences. ``raw`` is the model output with placeholders; the returned text is the substituted sentence."""
    failures: list[str] = []
    facts = request.fact_map
    text, unknown = substitute(raw.strip(), facts)
    if not raw.strip():
        failures.append("empty")
    if unknown:
        failures.append("unknown_placeholder")
    outside = PLACEHOLDER.sub(" ", raw)
    if _DIGIT.search(outside):
        failures.append("numeral_not_from_facts")
    fact_currencies = {f.currency for f in request.facts if f.currency}
    template_outside = PLACEHOLDER.sub(" ", request.template)
    allowed_codes = fact_currencies | set(_CURRENCY.findall(template_outside))
    if set(_CURRENCY.findall(outside)) - allowed_codes - {"OK"}:
        failures.append("currency_code")
    used = set(PLACEHOLDER.findall(raw))
    for fact in request.facts:
        if fact.kind == "money" and fact.key in set(PLACEHOLDER.findall(request.template)) and fact.key not in used:
            failures.append("money_fact_dropped")
            break
    known_words = {w for f in request.facts for w in _WORD.findall(f.text)} | set(_WORD.findall(template_outside))
    if _proper_nouns(raw) - known_words:
        failures.append("proper_noun")
    lowered = f" {outside.lower()} "
    template_lowered = f" {template_outside.lower()} "
    for word in (*_MONTHS, *_WEEKDAYS, *_RELATIVE_DATES):
        if re.search(rf"\b{re.escape(word)}\b", lowered) and not re.search(rf"\b{re.escape(word)}\b", template_lowered):
            failures.append("new_date")
            break
    if _sentences(text) > MAX_SENTENCES:
        failures.append("too_many_sentences")
    return Validation(ok=not failures, text=text, failures=failures)


# ---- the model request ---------------------------------------------------------------------------------------------
PHRASING_SYSTEM = (
    f"{PHRASING_PROMPT_VERSION}\nYou rewrite one deterministic sentence for a manufacturing ERP briefing into natural, "
    "brief wording. Refer to every fact only by its placeholder exactly as written, for example {{a1}}; never write "
    "digits, amounts, currency codes, dates or names yourself. Keep the meaning, add nothing that is not in the "
    'facts, and use at most two sentences. Reply with JSON {"text": ...}.'
)
PHRASING_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["text"],
    "properties": {"text": {"type": "string"}},
}
#: values the model may see verbatim (needed for grammar); money, quantities, counts and dates go by label only
_VISIBLE_KINDS = ("name", "text")


def model_request(request: PhraseRequest, *, model: str, max_tokens: int) -> Any:
    from app.modules.agents.providers.base import Message, ModelRequest, TextBlock

    facts = [
        {"placeholder": "{{" + f.key + "}}", "kind": f.kind, "label": f.label or f.kind,
         **({"value": f.text} if f.kind in _VISIBLE_KINDS else {})}
        for f in sorted(request.facts, key=lambda f: f.key)
    ]
    body = {"template": request.template, "facts": facts, "language": request.language, "tone": request.tone,
            "max_sentences": MAX_SENTENCES}
    return ModelRequest(
        task_class="phrasing", system=PHRASING_SYSTEM, model=model, max_tokens=max_tokens, effort="low",
        messages=(Message(role="user", content=(TextBlock(json.dumps(body, ensure_ascii=False, sort_keys=True)),)),),
        output_schema=PHRASING_SCHEMA,
    )


def parse_output(response: Any) -> str | None:
    if response is None or getattr(response, "stop_reason", None) == "refusal":
        return None
    try:
        data = json.loads(response.text or "")
    except (TypeError, ValueError):
        return None
    text = data.get("text") if isinstance(data, Mapping) else None
    return text if isinstance(text, str) else None


class DemoPhraser:
    """Deterministic phraser with the provider interface: echoes the template as the "model" sentence, so the same
    substitution, validation, cache and batch paths run in demo mode without keys."""

    name = "demo"
    label = "Demo"
    _batches: dict[str, dict[str, Any]] = {}

    def generate(self, request: Any) -> Any:
        from app.modules.agents.providers.base import ModelResponse, TextBlock

        body = json.loads(request.messages[-1].content[0].text)
        return ModelResponse(provider="demo", model="demo-phraser", stop_reason="end_turn",
                             content=(TextBlock(json.dumps({"text": body["template"]})),))

    def submit_batch(self, requests: Mapping[str, Any]) -> str:
        batch_id = "demo-batch-" + hashlib.sha256("|".join(sorted(requests)).encode()).hexdigest()[:16]
        self._batches[batch_id] = {cid: self.generate(r) for cid, r in requests.items()}
        return batch_id

    def collect_batch(self, batch_id: str, *, wait_seconds: float = 0.0) -> dict[str, Any] | None:  # noqa: ARG002
        return self._batches.pop(batch_id, None)


# ---- the service ---------------------------------------------------------------------------------------------------
def _phraser() -> Any:
    from app.modules.agents.providers import ai_mode, get_provider

    return DemoPhraser() if ai_mode() != "live" else get_provider("phrasing")


def _cached(uow: Any, digest: str) -> PhraseResult | None:
    from sqlalchemy import select

    from app.modules.agents.models import PhrasingCache

    row = uow.session.scalars(select(PhrasingCache).where(
        PhrasingCache.company_id == uow.actor.company_id, PhrasingCache.fact_hash == digest)).first()
    if row is None:
        return None
    return PhraseResult(text=row.text, source=row.source, fact_hash=digest, cached=True, model=row.model)  # type: ignore[arg-type]


def _store(uow: Any, request: PhraseRequest, result: PhraseResult) -> None:
    import uuid

    from sqlalchemy.dialects.postgresql import insert

    from app.modules.agents.models import PhrasingCache

    uow.session.execute(insert(PhrasingCache).values(
        id=uuid.uuid7(), company_id=uow.actor.company_id, fact_hash=result.fact_hash,
        template_code=request.template_code[:80], language=request.language[:12], text=result.text,
        source=result.source, model=result.model[:80], created_at=uow.now(),
    ).on_conflict_do_nothing(index_elements=["company_id", "fact_hash"]))


def _template(request: PhraseRequest, digest: str, failures: Sequence[str], model: str = "") -> PhraseResult:
    return PhraseResult(text=render_template(request), source="template", fact_hash=digest, model=model,
                        failures=tuple(failures))


def _log(uow: Any, response: Any, error: Exception | None, provider: Any, model: str) -> None:
    from app.modules.agents.service import log_call

    log_call(uow, None, step_seq=None, response=response, task_class="phrasing", error=error,
             provider=getattr(provider, "name", "demo"), model=model, user_id=uow.actor.user_id,
             correlation_id=uow.actor.correlation_id)
    uow.flush()


def _result_of(request: PhraseRequest, digest: str, response: Any, model: str) -> PhraseResult:
    raw = parse_output(response)
    if raw is None:
        reason = "refusal" if getattr(response, "stop_reason", None) == "refusal" else "unparseable"
        return _template(request, digest, [reason], model)
    checked = validate(raw, request)
    if not checked.ok:
        return _template(request, digest, checked.failures, model)
    return PhraseResult(text=checked.text, source="model", fact_hash=digest, model=getattr(response, "model", model) or model)


def phrase(uow: Any, request: PhraseRequest, *, provider: Any = None) -> PhraseResult:
    """One validated sentence (or the labelled template text). Cached by fact hash; outages are not cached."""
    from app.modules.agents import routing

    digest = fact_hash(request)
    hit = _cached(uow, digest)
    if hit is not None:
        return hit
    model = routing.resolve(uow).model_for("phrasing")
    try:
        provider = provider or _phraser()
        response = provider.generate(model_request(request, model=model, max_tokens=routing.PHRASING_CAPS[request.kind]))
    except Exception as exc:  # outage, circuit open, not configured: template now, regenerate next time
        _log(uow, None, exc, provider, model)
        return _template(request, digest, [getattr(exc, "code", None) or "provider_unavailable"], model)
    _log(uow, response, None, provider, model)
    result = _result_of(request, digest, response, model)
    _store(uow, request, result)
    return result


@dataclass
class PhrasingBatch:
    """A submitted pre-shift batch: cache hits are already resolved, the rest wait for ``collect_batch``."""

    batch_id: str | None
    pending: dict[str, str]
    results: dict[str, PhraseResult]
    model: str


def submit_batch(uow: Any, items: Mapping[str, PhraseRequest], *, provider: Any = None) -> PhrasingBatch:
    """Message Batches for pre-shift phrasing (no ``fallbacks`` on batch requests; results keyed by custom id)."""
    from app.modules.agents import routing

    model = routing.resolve(uow).model_for("phrasing")
    results: dict[str, PhraseResult] = {}
    to_send: dict[str, Any] = {}
    pending: dict[str, str] = {}
    for custom_id, request in items.items():
        digest = fact_hash(request)
        hit = _cached(uow, digest)
        if hit is not None:
            results[custom_id] = hit
            continue
        pending[custom_id] = digest
        to_send[custom_id] = model_request(request, model=model, max_tokens=routing.PHRASING_CAPS[request.kind])
    batch_id: str | None = None
    if to_send:
        try:
            batch_id = (provider or _phraser()).submit_batch(to_send)
        except Exception as exc:  # the briefing keeps its template text
            _log(uow, None, exc, provider, model)
            for custom_id, digest in pending.items():
                results[custom_id] = _template(items[custom_id], digest, [getattr(exc, "code", None) or "batch_unavailable"], model)
            pending = {}
    return PhrasingBatch(batch_id=batch_id, pending=pending, results=results, model=model)


def collect_batch(uow: Any, batch: PhrasingBatch, items: Mapping[str, PhraseRequest], *, provider: Any = None,
                  wait_seconds: float = 0.0) -> dict[str, PhraseResult] | None:
    """All results keyed by custom id once the batch ended (failed items keep template text); None while running."""
    out = dict(batch.results)
    if not batch.pending or batch.batch_id is None:
        return out
    collected = (provider or _phraser()).collect_batch(batch.batch_id, wait_seconds=wait_seconds)
    if collected is None:
        return None
    for custom_id, digest in batch.pending.items():
        response = collected.get(custom_id)
        if response is None or isinstance(response, Exception):
            error = response if isinstance(response, Exception) else RuntimeError("batch item missing")
            _log(uow, None, error, provider, batch.model)
            out[custom_id] = _template(items[custom_id], digest, ["batch_item_failed"], batch.model)
            continue
        _log(uow, response, None, provider, batch.model)
        out[custom_id] = _result_of(items[custom_id], digest, response, batch.model)
        _store(uow, items[custom_id], out[custom_id])
    return out


__all__ = [
    "MAX_SENTENCES",
    "STANDARD_WORDING",
    "DemoPhraser",
    "Fact",
    "PhraseRequest",
    "PhraseResult",
    "PhrasingBatch",
    "collect_batch",
    "fact_hash",
    "model_request",
    "phrase",
    "render_template",
    "submit_batch",
    "substitute",
    "validate",
]
