"""Briefing wording through the agents phrasing service (design §11; ai-routing.md §2, §6, §7).

The engine's text stays deterministic and is stored on the version. This module builds phrasing requests from the
**stored, visible, redacted facts** of a version: the overview sentence, each item's recommendation sentence and the
spoken body of each item for "Listen to my day". Facts travel as ``{{a1}}`` placeholders (``agents.phrasing``), so
the model can reword but never restate a number, amount, currency, name or date; the validator rejects anything
else and the template text stands in, labelled "Standard wording". Results are cached by the phrasing service's
fact hash (facts + template code + template version + language), so an unchanged item in a new version costs
nothing. The result is one ``briefings_version_text`` row per version and language; phrasing never creates a
version.

Two paths: ``phrase_version`` (one call per text, used after generation and on demand) and the pre-shift batch
(``submit_version_batch`` / ``collect_version_batch``) through the provider's Message Batches path. Demo mode runs
the Demo phraser behind the same interface, so every path here is exercised without keys.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.modules.agents import phrasing
from app.modules.agents.phrasing import Fact, PhraseRequest, PhraseResult
from app.modules.briefings.engine import overview as overview_engine
from app.modules.briefings.engine.labels import due_label
from app.modules.briefings.engine.recommend import sentence_template
from app.modules.briefings.models import (
    AiStatus,
    Briefing,
    BriefingItem,
    BriefingVersion,
    PhrasingStatus,
    TextSource,
    VersionText,
)
from app.platform.uow import UnitOfWork

LANGUAGE = "en"
#: bump when a briefing phrasing template below changes (part of every fact hash)
TEMPLATE_VERSION = 1

#: spoken label of an item's family (the web shows the same words as the row's status label)
FAMILY_LABELS = {
    "common.approvals": "Decision",
    "sales.customer_replies": "Customer reply",
    "sales.enquiries": "Enquiry",
    "sales.quote_review": "Quote review",
    "sales.quote_expiry": "Quote expiry",
    "sales.commercial_exceptions": "Price change",
    "sales.customer_changes": "Customer update",
    "sales.samples": "Sample",
    "admin.access": "Access request",
    "admin.onboarding": "Onboarding",
    "common.onboarding": "Onboarding",
    "common.handled": "Handled",
}
ORDINAL_WORDS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth",
                 "Eleventh", "Twelfth")


def ai_mode_status() -> str:
    from app.modules.agents.providers import ai_mode

    return AiStatus.DEMO.value if ai_mode() != "live" else AiStatus.OK.value


def _mode() -> str:
    """Part of every template code, so the fact-hash cache never serves a Demo echo as live model wording."""
    return "demo" if ai_mode_status() == AiStatus.DEMO.value else "live"


def ordinal_word(n: int) -> str:
    return ORDINAL_WORDS[n - 1] if 1 <= n <= len(ORDINAL_WORDS) else f"Number {n}"


def family_label(row: BriefingItem) -> str:
    if row.is_reminder:
        return "Reminder"
    return FAMILY_LABELS.get(row.family, "Task")


# ---- requests -------------------------------------------------------------------------------------------------------
def _facts(slots: Any) -> tuple[Fact, ...]:
    return tuple(Fact(key=s[0], text=s[1], kind=s[2], label=s[3] if len(s) > 3 else "") for s in slots)


def overview_request(version: BriefingVersion, first_name: str) -> PhraseRequest | None:
    """The overview sentence as a phrasing request, or None when the stored sentence cannot be rebuilt from its
    facts under the current templates (an older template version: it keeps its deterministic text)."""
    data = version.overview or {}
    code = str(data.get("template_code") or "")
    counts = {k: int(v) for k, v in (data.get("facts") or {}).items() if not isinstance(v, bool)}
    built_code, template, slots = overview_engine.compose_template(counts, first_name=first_name, new_member=code == "welcome")
    request = PhraseRequest(
        template_code=f"briefing.overview.{built_code}:{_mode()}", template=template,
        facts=tuple(Fact(key=s.key, text=s.text, kind=s.kind, label=s.label) for s in slots),  # type: ignore[arg-type]
        template_version=TEMPLATE_VERSION, language=LANGUAGE, kind="phrasing", tone="warm, brief, factual",
    )
    if built_code != code or overview_engine.sentence_case(phrasing.render_template(request)) != data.get("sentence"):
        return None
    return request


def recommendation_request(row: BriefingItem) -> PhraseRequest | None:
    rec = row.recommendation or {}
    if not rec.get("action_code"):
        return None
    template, slots = sentence_template(str(rec["action_code"]), str(rec.get("reason_code") or ""), dict(row.facts or {}))
    return PhraseRequest(
        template_code=f"briefing.recommendation.{rec['action_code']}:{_mode()}", template=template, facts=_facts(slots),
        template_version=TEMPLATE_VERSION, language=LANGUAGE, kind="phrasing", tone="direct, brief",
    )


def _money_texts(row: BriefingItem) -> list[tuple[str, str]]:
    from app.core.money import Money

    out: list[tuple[str, str]] = []
    for m in (row.facts or {}).get("_money", []):
        amount = Money(amount=m["amount"], currency=m["currency"])
        out.append((f"{amount.currency} {amount.amount:,.2f}", amount.currency))
    return out


def narration_request(row: BriefingItem, *, zone: str, work_date: Any) -> PhraseRequest:
    """The spoken body of one item (at most two sentences): title, amounts, due; then the suggestion.
    The lead ("Second. Decision.") is deterministic and never phrased."""
    slots: list[Fact] = [Fact(key="a1", text=row.title, kind="text", label="item title")]
    first = ["{{a1}}"]
    for currency_text, currency in _money_texts(row)[:2]:
        key = f"a{len(slots) + 1}"
        slots.append(Fact(key=key, text=currency_text, kind="money", currency=currency, label="amount"))
        first.append("{{" + key + "}}")
    overdue = "OVERDUE" in (row.reason_codes or []) or "SOFT_OVERDUE" in (row.reason_codes or [])
    due = due_label(row.due_at, zone=zone, work_date=work_date, kind=row.kind, overdue=overdue)
    if due:
        key = f"a{len(slots) + 1}"
        slots.append(Fact(key=key, text=due[0].lower() + due[1:], kind="date", label="when it is due"))
        first.append("{{" + key + "}}")
    template = ", ".join(first) + "."
    rec = row.recommendation or {}
    if rec.get("label"):
        key = f"a{len(slots) + 1}"
        slots.append(Fact(key=key, text=str(rec["label"]), kind="text", label="suggested action"))
        template += " Suggested: {{" + key + "}}."
    return PhraseRequest(
        template_code=f"briefing.narration.{row.kind}:{_mode()}"[:80], template=template, facts=tuple(slots),
        template_version=TEMPLATE_VERSION, language=LANGUAGE, kind="narration", tone="spoken, calm, brief",
    )


def readback_values(row: BriefingItem) -> list[str]:
    """The consequential values a voice confirmation reads back before acting (the record and its amounts)."""
    values = [row.title]
    refs = row.source_refs or []
    if refs and refs[0].get("label") and refs[0]["label"] not in row.title:
        values.append(str(refs[0]["label"]))
    values.extend(text for text, _currency in _money_texts(row))
    return values


@dataclass
class VersionRequests:
    """Every phrasing request of one version, keyed by custom id (``ov``, ``rec:<issue>``, ``nar:<issue>``)."""

    requests: dict[str, PhraseRequest]


def version_requests(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion) -> VersionRequests:
    from app.modules.tasks import responsibility

    name = responsibility.display_names(uow, [briefing.user_id]).get(briefing.user_id, "")
    out: dict[str, PhraseRequest] = {}
    ov = overview_request(version, responsibility.first_name(name))
    if ov is not None:
        out["ov"] = ov
    rows = uow.session.scalars(select(BriefingItem).where(BriefingItem.version_id == version.id).order_by(BriefingItem.display_ordinal))
    for row in rows:
        rec = recommendation_request(row)
        if rec is not None:
            out[f"rec:{row.issue_id}"] = rec
        out[f"nar:{row.issue_id}"] = narration_request(row, zone=briefing.time_zone, work_date=briefing.work_date)
    return VersionRequests(out)


# ---- storing ----------------------------------------------------------------------------------------------------------
def _entry(result: PhraseResult) -> dict[str, Any]:
    return {"text": overview_engine.sentence_case(result.text), "source": TextSource.MODEL.value if result.source == "model" else TextSource.TEMPLATE.value,
            "failures": list(result.failures)}


def version_text(uow: UnitOfWork, version_id: uuid.UUID, language: str = LANGUAGE) -> VersionText | None:
    return uow.session.scalars(
        select(VersionText).where(VersionText.company_id == uow.actor.company_id, VersionText.version_id == version_id,
                                  VersionText.language == language)
    ).first()


def _row(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion) -> VersionText:
    row = version_text(uow, version.id)
    if row is None:
        row = VersionText(company_id=briefing.company_id, briefing_id=briefing.id, version_id=version.id, language=LANGUAGE,
                          status=PhrasingStatus.READY.value, ai_status=ai_mode_status(), item_texts={}, narration={})
        uow.add(row)
    return row


def store_results(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, results: dict[str, PhraseResult], *,
                  model: str = "") -> VersionText:
    row = _row(uow, briefing, version)
    items: dict[str, Any] = dict(row.item_texts or {})
    narration: dict[str, Any] = dict(row.narration or {})
    for custom_id, result in results.items():
        if custom_id == "ov":
            row.overview = _entry(result)
        elif custom_id.startswith("rec:"):
            items[custom_id[4:]] = _entry(result)
        elif custom_id.startswith("nar:"):
            narration[custom_id[4:]] = _entry(result)
    row.item_texts = items
    row.narration = narration
    row.model = (model or next((r.model for r in results.values() if r.model), ""))[:80]
    row.status = PhrasingStatus.READY.value
    row.batch_id = None
    row.ai_status = _ai_status(row)
    uow.flush()
    return row


def _ai_status(row: VersionText) -> str:
    """Demo in demo mode; otherwise ``ok`` when the overview was phrased by the model and ``unavailable`` when the
    template stands in after a failure (an outage, a refusal or a validator rejection: "Standard wording")."""
    if ai_mode_status() == AiStatus.DEMO.value:
        return AiStatus.DEMO.value
    entries = [row.overview] if row.overview else list((row.item_texts or {}).values())
    if any(e and e.get("source") == TextSource.TEMPLATE.value for e in entries):
        return AiStatus.UNAVAILABLE.value
    return AiStatus.OK.value


def outage_only(row: VersionText | None) -> bool:
    """Whether a stored text is template wording only because the provider did not answer (an outage, an open
    circuit, a quota, a missing key): worth phrasing again later. Validator rejections and refusals are final for
    these facts (the phrasing cache keeps them)."""
    if row is None or row.overview is None:
        return False
    failures = set(row.overview.get("failures") or [])
    return row.overview.get("source") == TextSource.TEMPLATE.value and bool(failures) and not failures & VALIDATOR_CODES


#: failure codes of a provider answer that was rejected (``agents.phrasing.validate`` / ``parse_output``)
VALIDATOR_CODES = frozenset({"empty", "unknown_placeholder", "numeral_not_from_facts", "currency_code", "money_fact_dropped",
                             "proper_noun", "new_date", "too_many_sentences", "refusal", "unparseable"})


# ---- the two paths --------------------------------------------------------------------------------------------------
def phrase_version(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, *, provider: Any = None) -> VersionText:
    """Phrase every text of the version now (one validated call per text, cache first)."""
    built = version_requests(uow, briefing, version)
    results = {cid: phrasing.phrase(uow, request, provider=provider) for cid, request in built.requests.items()}
    return store_results(uow, briefing, version, results)


def submit_version_batch(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, *, provider: Any = None) -> tuple[VersionText, dict[str, Any] | None]:
    """Pre-shift phrasing through Message Batches. Returns the text row and, while the batch runs, the state the
    collect job needs (batch id, the pending custom ids with their fact hashes, the model)."""
    built = version_requests(uow, briefing, version)
    batch = phrasing.submit_batch(uow, built.requests, provider=provider)
    done = phrasing.collect_batch(uow, batch, built.requests, provider=provider)
    if done is not None:
        return store_results(uow, briefing, version, done, model=batch.model), None
    row = _row(uow, briefing, version)
    row.status = PhrasingStatus.PENDING.value
    row.batch_id = (batch.batch_id or "")[:120] or None
    uow.flush()
    return row, {"batch_id": batch.batch_id, "pending": dict(batch.pending), "model": batch.model}


def collect_version_batch(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, state: dict[str, Any], *,
                          provider: Any = None) -> VersionText | None:
    """Collect a running batch (None while it runs). Texts resolved from the cache at submit time are read from the
    cache again (it is never cleared), so they cost no provider call."""
    built = version_requests(uow, briefing, version)
    pending = {cid: digest for cid, digest in (state.get("pending") or {}).items() if cid in built.requests}
    cached = {cid: phrasing.phrase(uow, request, provider=provider) for cid, request in built.requests.items() if cid not in pending}
    batch = phrasing.PhrasingBatch(batch_id=state.get("batch_id"), pending=pending, results=cached, model=str(state.get("model") or ""))
    done = phrasing.collect_batch(uow, batch, built.requests, provider=provider)
    if done is None:
        return None
    return store_results(uow, briefing, version, done, model=batch.model)


__all__ = [
    "LANGUAGE",
    "TEMPLATE_VERSION",
    "VALIDATOR_CODES",
    "ai_mode_status",
    "collect_version_batch",
    "family_label",
    "narration_request",
    "ordinal_word",
    "outage_only",
    "overview_request",
    "phrase_version",
    "readback_values",
    "recommendation_request",
    "store_results",
    "submit_version_batch",
    "version_requests",
    "version_text",
]
