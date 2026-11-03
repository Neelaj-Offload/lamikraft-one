"""Phrasing validator (ai-routing.md section 6) and fact hashing: numerals only from facts, currency codes preserved,
proper nouns from facts, no new dates, at most two sentences; anything else falls back to "Standard wording"."""

from __future__ import annotations

import json

from app.modules.agents.phrasing import (
    DemoPhraser,
    Fact,
    PhraseRequest,
    fact_hash,
    model_request,
    render_template,
    validate,
)

FACTS = (
    Fact("a1", "Nordhaus Interiors", "name", label="customer"),
    Fact("a2", "EUR 5,760.00", "money", currency="EUR", label="quote total"),
    Fact("a3", "LK-QT-2026-0009", "text", label="quote number"),
)
REQUEST = PhraseRequest(
    template_code="briefing.quote_expiring", template="Quote {{a3}} for {{a1}} ({{a2}}) expires soon.", facts=FACTS,
)


def test_valid_rewrite_is_substituted() -> None:
    result = validate("{{a1}}'s quote {{a3}} worth {{a2}} is about to expire.", REQUEST)
    assert result.ok, result.failures
    assert result.text == "Nordhaus Interiors's quote LK-QT-2026-0009 worth EUR 5,760.00 is about to expire."


def test_model_numerals_currency_names_dates_and_length_are_rejected() -> None:
    cases = {
        "Quote {{a3}} for {{a1}} is worth 5760 euros.": "numeral_not_from_facts",
        "Quote {{a3}} for {{a1}} is worth {{a2}} or USD equivalent.": "currency_code",
        "Quote {{a3}} for {{a1}} and Maison ({{a2}}) expires soon.": "proper_noun",
        "Quote {{a3}} for {{a1}} ({{a2}}) expires on Friday.": "new_date",
        "Quote {{a3}}. For {{a1}}. Worth {{a2}}. Expires soon.": "too_many_sentences",
        "Quote {{a9}} for {{a1}} ({{a2}}) expires soon.": "unknown_placeholder",
        "Quote {{a3}} for {{a1}} expires soon.": "money_fact_dropped",
        "": "empty",
    }
    for raw, failure in cases.items():
        result = validate(raw, REQUEST)
        assert not result.ok and failure in result.failures, (raw, result.failures)


def test_template_render_and_hash_are_deterministic() -> None:
    assert render_template(REQUEST) == "Quote LK-QT-2026-0009 for Nordhaus Interiors (EUR 5,760.00) expires soon."
    assert fact_hash(REQUEST) == fact_hash(PhraseRequest(REQUEST.template_code, REQUEST.template, tuple(reversed(FACTS))))
    changed = PhraseRequest(REQUEST.template_code, REQUEST.template, (*FACTS[:1], Fact("a2", "EUR 6,000.00", "money", "EUR"), FACTS[2]))
    assert fact_hash(changed) != fact_hash(REQUEST)
    assert fact_hash(PhraseRequest(REQUEST.template_code, REQUEST.template, FACTS, template_version=2)) != fact_hash(REQUEST)


def test_model_request_hides_money_values_and_uses_structured_output() -> None:
    request = model_request(REQUEST, model="claude-haiku-5-5", max_tokens=600)
    assert request.task_class == "phrasing" and request.effort == "low" and request.max_tokens == 600
    assert request.output_schema and request.output_schema["required"] == ["text"]
    body = json.loads(request.messages[-1].content[0].text)
    assert "5,760" not in json.dumps(body["facts"]) and any(f.get("value") == "Nordhaus Interiors" for f in body["facts"])


def test_demo_phraser_is_deterministic_and_valid() -> None:
    demo = DemoPhraser()
    response = demo.generate(model_request(REQUEST, model="demo", max_tokens=600))
    assert json.loads(response.text)["text"] == REQUEST.template
    assert validate(json.loads(response.text)["text"], REQUEST).ok
    batch_id = demo.submit_batch({"x": model_request(REQUEST, model="demo", max_tokens=600)})
    assert set(demo.collect_batch(batch_id) or {}) == {"x"}
