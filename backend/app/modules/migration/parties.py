"""Candidate party links from the legacy free-text customer names (never an automatic merge).

Legacy quotes and custom products name the customer as text (``customer_name``, ``customer_country``). The dry run
groups the spellings by a normalised name (NFKC, casefold, punctuation and legal-form words such as GmbH / Ltd / Pvt
removed) and the country, then suggests at most one existing party:

- ``exact_name``: the normalised display or legal name is equal (score 0.9, 1.0 when the country also matches);
- ``name_tokens``: every word of one name is in the other (score 0.6, 0.7 with the country);
- two parties with the same best score: no suggestion (``ambiguous``).

A candidate is decided by a person (link to a party, create a new party later, or reject) through
``migration.party_candidate.update``. A rerun refreshes the counts and the suggestion of undecided candidates only.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.modules.migration.analysis import Analysis, text

LEGAL_FORMS = frozenset(
    {
        "gmbh",
        "ag",
        "kg",
        "ltd",
        "limited",
        "pvt",
        "private",
        "llc",
        "inc",
        "co",
        "company",
        "corp",
        "corporation",
        "bv",
        "nv",
        "sarl",
        "sas",
        "sa",
        "srl",
        "spa",
        "plc",
        "oy",
        "ab",
        "as",
        "aps",
        "kft",
        "sro",
        "the",
        "and",
    }
)
COUNTRIES = {
    "germany": "DE",
    "deutschland": "DE",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "france": "FR",
    "india": "IN",
    "netherlands": "NL",
    "holland": "NL",
    "the netherlands": "NL",
    "italy": "IT",
    "spain": "ES",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "belgium": "BE",
    "denmark": "DK",
    "sweden": "SE",
    "austria": "AT",
    "switzerland": "CH",
    "norway": "NO",
    "finland": "FI",
    "poland": "PL",
    "ireland": "IE",
    "portugal": "PT",
    "australia": "AU",
    "canada": "CA",
    "united arab emirates": "AE",
    "uae": "AE",
}
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
MAX_SOURCES = 50


def normalise_name(name: str) -> str:
    value = unicodedata.normalize("NFKC", name).casefold().replace("&", " and ")
    words = [w for w in _PUNCT.sub(" ", value).split() if w]
    core = [w for w in words if w not in LEGAL_FORMS]
    return " ".join(core or words)[:200]


def country_code(text_value: str | None) -> str | None:
    if not text_value:
        return None
    t = " ".join(text_value.split()).casefold()
    if len(t) == 2 and t.isalpha():
        return t.upper()
    return COUNTRIES.get(t)


@dataclass
class CandidateAgg:
    name_key: str
    country_key: str
    legacy_country: str | None
    variants: Counter[str] = field(default_factory=Counter)
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def occurrences(self) -> int:
        return sum(self.variants.values())

    @property
    def legacy_name(self) -> str:
        return self.variants.most_common(1)[0][0]


@dataclass
class Suggestion:
    party_id: Any
    match_kind: str
    score: Decimal


def collect(an: Analysis) -> dict[tuple[str, str], CandidateAgg]:
    out: dict[tuple[str, str], CandidateAgg] = {}
    for entity, number_field in (("quotes", "quote_number"), ("custom_products", "custom_code")):
        for key, acc in an.accepted[entity].items():
            name = text(acc.row.values, "customer_name")
            if not name:
                continue
            country_text = text(acc.row.values, "customer_country")
            nk = normalise_name(name)
            if not nk:
                continue
            ck = country_code(country_text) or (
                " ".join(country_text.split()).casefold() if country_text else ""
            )
            agg = out.setdefault((nk, ck), CandidateAgg(nk, ck, country_text))
            agg.variants[" ".join(name.split())] += 1
            if len(agg.sources) < MAX_SOURCES:
                agg.sources.append(
                    {
                        "entity": entity,
                        "source_key": key,
                        "document_number": text(acc.row.values, number_field),
                    }
                )
    return out


def suggest(
    an: Analysis, candidates: dict[tuple[str, str], CandidateAgg]
) -> dict[tuple[str, str], Suggestion | None]:
    from app.modules.parties.models import Party

    parties = list(
        an.uow.session.execute(
            select(Party.id, Party.display_name, Party.legal_name, Party.country_code).where(
                Party.archived_at.is_(None)
            )
        )
    )
    index: list[tuple[Any, set[str], set[str], str]] = []
    for pid, display, legal, cc in parties:
        keys = {normalise_name(display), normalise_name(legal)}
        tokens = set(" ".join(keys).split())
        index.append((pid, keys, tokens, cc))
    by_key: dict[str, list[int]] = defaultdict(list)
    for i, (_pid, keys, _t, _cc) in enumerate(index):
        for k in keys:
            by_key[k].append(i)
    out: dict[tuple[str, str], Suggestion | None] = {}
    for ck, agg in candidates.items():
        scored: list[tuple[Decimal, str, Any]] = []
        words = set(agg.name_key.split())
        for pid, keys, tokens, cc in index:
            country_bonus = Decimal("0.1") if agg.country_key and agg.country_key == cc else Decimal(0)
            if agg.name_key in keys:
                scored.append((Decimal("0.9") + country_bonus, "exact_name", pid))
            elif words and (words <= tokens or tokens <= words) and tokens:
                scored.append((Decimal("0.6") + country_bonus, "name_tokens", pid))
        if not scored:
            out[ck] = None
            continue
        scored.sort(key=lambda s: s[0], reverse=True)
        best = scored[0]
        if len(scored) > 1 and scored[1][0] == best[0]:
            out[ck] = Suggestion(None, "ambiguous", best[0])
        else:
            out[ck] = Suggestion(best[2], best[1], best[0])
    return out


def analyse_parties(an: Analysis) -> dict[tuple[str, str], tuple[CandidateAgg, Suggestion | None]]:
    candidates = collect(an)
    suggestions = suggest(an, candidates)
    an.report["party_candidates"] = {
        "names": len(candidates),
        "with_suggestion": sum(1 for s in suggestions.values() if s and s.party_id),
        "ambiguous": sum(1 for s in suggestions.values() if s and s.match_kind == "ambiguous"),
        "without_suggestion": sum(1 for s in suggestions.values() if s is None),
        "occurrences": sum(c.occurrences for c in candidates.values()),
        "spelling_variants": sum(len(c.variants) for c in candidates.values()),
    }
    return {k: (candidates[k], suggestions[k]) for k in candidates}


__all__ = ["CandidateAgg", "Suggestion", "analyse_parties", "country_code", "normalise_name"]
