"""Deterministic briefing engine: collect (DB, as the member) → visibility → priority → sections → rank.

Everything except ``collect`` is pure and property-tested; no LLM is used in Slice 1.
"""

PRIORITY_RULE_VERSION = "s1.1"
