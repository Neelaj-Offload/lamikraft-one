"""Deterministic command grammar (no model): open the Nth item, snooze, navigate, stop, "what should I handle
today", help — in English and Hinglish (ai-routing.md section 2, first row).

``parse_command`` returns a typed :class:`Command` or ``None``. It runs before any provider, costs nothing and keeps
working when the AI is down. The fixtures in ``backend/tests/fixtures/demo_intents/commands.json`` are the contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CommandKind = Literal["open_item", "snooze", "navigate", "stop", "today_overview", "help"]
Language = Literal["en", "hinglish"]

ORDINALS_EN = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "last": -1,
}
ORDINALS_HI = {
    "pehla": 1, "pehle": 1, "pahla": 1, "doosra": 2, "dusra": 2, "doosre": 2, "dusre": 2, "teesra": 3, "tisra": 3,
    "teesre": 3, "chautha": 4, "chauthe": 4, "paanchva": 5, "panchva": 5, "paanchwa": 5, "chhatha": 6,
    "saatva": 7, "aathva": 8, "nauva": 9, "dasva": 10, "aakhri": -1, "akhri": -1,
}
#: navigation targets -> canonical web paths (the client resolves the route; paths follow conventions.md)
NAV_TARGETS: dict[str, tuple[str, str]] = {
    "today": ("today", "/today"),
    "briefing": ("today", "/today"),
    "home": ("today", "/today"),
    "inbox": ("inbox", "/inbox"),
    "work": ("work", "/work"),
    "quotes": ("quotes", "/sales/quotes"),
    "quote list": ("quotes", "/sales/quotes"),
    "my quotes": ("quotes", "/sales/quotes"),
    "enquiries": ("enquiries", "/sales/enquiries"),
    "parties": ("parties", "/sales/parties"),
    "customers": ("parties", "/sales/parties"),
    "products": ("products", "/catalogue/products"),
    "catalogue": ("products", "/catalogue/products"),
    "catalog": ("products", "/catalogue/products"),
    "approvals": ("approvals", "/inbox/approvals"),
}


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    language: Language
    pattern: str
    ordinal: int | None = None  # open_item / snooze: 1-based, -1 = last
    target: str | None = None  # navigate: canonical target key
    path: str | None = None  # navigate: web path
    until: str | None = None  # snooze: tomorrow | next_week | later


def _norm(text: str) -> str:
    cleaned = re.sub(r"[^\w\s'’-]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


_ORD_EN = "|".join(ORDINALS_EN)
_ORD_HI = "|".join(ORDINALS_HI)
_NUM = r"(?:no\.?\s*|number\s*|#\s*)?(\d{1,2})(?:st|nd|rd|th)?"
_NAV = "|".join(re.escape(k) for k in sorted(NAV_TARGETS, key=len, reverse=True))

_PATTERNS: tuple[tuple[str, Language, CommandKind, re.Pattern[str]], ...] = (
    # ---- open the Nth item ----------------------------------------------------------------------------------
    ("open_ordinal_en", "en", "open_item",
     re.compile(rf"^(?:please\s+)?(?:open|show|show me|go to|take me to)\s+(?:the\s+)?(?P<ord>{_ORD_EN})\s+(?:item|one|entry|row)$")),
    ("open_number_en", "en", "open_item",
     re.compile(rf"^(?:please\s+)?(?:open|show|show me|go to)\s+(?:the\s+)?(?:item|entry|row)\s+{_NUM}$")),
    ("open_ordinal_hi", "hinglish", "open_item",
     re.compile(rf"^(?:please\s+)?(?P<ord>{_ORD_HI})\s+(?:item|wala|wali|wala item|wali item)?\s*(?:kholo|khol do|kholiye|dikhao|dikha do|open karo|open kar do)$")),
    ("open_number_hi", "hinglish", "open_item",
     re.compile(rf"^(?:item|entry)\s+{_NUM}\s+(?:kholo|khol do|dikhao|open karo)$")),
    # ---- snooze ------------------------------------------------------------------------------------------------
    ("snooze_en", "en", "snooze",
     re.compile(rf"^snooze(?:\s+(?:this|it|that|this one|the\s+(?P<ord>{_ORD_EN})\s+(?:item|one)))?(?:\s+(?:until|till|to)\s+(?P<until>tomorrow|next week|later|this evening))?$")),
    ("snooze_hi", "hinglish", "snooze",
     re.compile(r"^(?:(?:isko|ise|is ko|yeh|ye|isse)\s+)?(?:(?P<until>kal tak|baad mein|baad me|agle hafte|shaam tak)\s+)?snooze\s*(?:karo|kar do|kardo|kar)?(?:\s+(?P<until2>kal tak|baad mein|baad me|agle hafte|shaam tak))?$")),
    # ---- navigate ----------------------------------------------------------------------------------------------
    ("navigate_en", "en", "navigate",
     re.compile(rf"^(?:please\s+)?(?:go to|open|show|show me|take me to|switch to)\s+(?:the\s+|my\s+)?(?P<target>{_NAV})(?:\s+(?:page|list|screen))?$")),
    ("navigate_hi", "hinglish", "navigate",
     re.compile(rf"^(?:mujhe\s+)?(?:(?:the|my)\s+)?(?P<target>{_NAV})\s+(?:par|pe|pr|mein|me)\s+(?:jao|le chalo|chalo|le jao|jaiye|chaliye)$")),
    ("navigate_hi_open", "hinglish", "navigate",
     re.compile(rf"^(?P<target>{_NAV})\s+(?:kholo|khol do|dikhao|dikha do|open karo)$")),
    # ---- stop --------------------------------------------------------------------------------------------------
    ("stop_en", "en", "stop",
     re.compile(r"^(?:please\s+)?(?:stop|stop speaking|stop reading|stop talking|be quiet|quiet|enough|that's enough|cancel that)$")),
    ("stop_hi", "hinglish", "stop",
     re.compile(r"^(?:ruko|ruk jao|rukho|bas|bas karo|bas kar|chup|chup ho jao|bolna band karo|band karo|rehne do)$")),
    # ---- what should I handle today ----------------------------------------------------------------------------
    ("today_en", "en", "today_overview",
     re.compile(r"^(?:so\s+)?what(?:'s| is| should i| do i| must i)?\s*(?:handle|do|focus on|look at|take care of|need to do|on my plate|on today|up today)?\s*(?:today|this morning|now)?$")),
    ("today_hi", "hinglish", "today_overview",
     re.compile(r"^(?:aaj|aj)\s+(?:kya|kya kya|kaunsa|konsa)?\s*(?:karna hai|karna|dekhna hai|dekhna|handle karna hai|handle karna|kaam hai|ka plan hai|ka kaam hai|ka plan|ka kaam)$")),
    # ---- help --------------------------------------------------------------------------------------------------
    ("help", "en", "help",
     re.compile(r"^(?:help|help me|what can you do|what can i say|commands|show commands|madad|madad karo|help karo|kya kar sakte ho)$")),
)

_TODAY_WORDS = ("today", "this morning", "now", "aaj", "aj")
_SNOOZE_UNTIL = {
    "tomorrow": "tomorrow", "kal tak": "tomorrow", "next week": "next_week", "agle hafte": "next_week",
    "later": "later", "baad mein": "later", "baad me": "later", "this evening": "this_evening",
    "shaam tak": "this_evening",
}


def parse_command(text: str) -> Command | None:
    """Return the deterministic command the text expresses, or ``None`` when it needs the router."""
    normalised = _norm(text)
    if not normalised or len(normalised) > 120:
        return None
    for name, language, kind, pattern in _PATTERNS:
        match = pattern.fullmatch(normalised)
        if match is None:
            continue
        groups = match.groupdict()
        if kind == "today_overview":
            # the "what ... today" pattern is deliberately loose; require a verb or a today-word to avoid false hits
            if not any(w in normalised for w in _TODAY_WORDS) and "handle" not in normalised:
                continue
        ordinal = None
        if groups.get("ord"):
            ordinal = ORDINALS_EN.get(groups["ord"]) or ORDINALS_HI.get(groups["ord"])
        elif match.groups() and match.group(1) and match.group(1).isdigit() and kind == "open_item":
            ordinal = int(match.group(1))
        target = path = None
        if groups.get("target"):
            target, path = NAV_TARGETS[groups["target"]]
        until_raw = groups.get("until") or groups.get("until2")
        until = _SNOOZE_UNTIL.get(until_raw) if until_raw else None
        return Command(kind=kind, language=language, pattern=name, ordinal=ordinal, target=target, path=path, until=until)
    return None


HELP_TEXT = (
    "Demo assistant commands: \"Prepare <customer>'s usual <product> quote\", \"change it to <quantity>\", "
    "\"open the second item\", \"snooze this until tomorrow\", \"go to quotes\", \"what should I handle today\", "
    "\"stop\". Hinglish works too: \"Nordhaus ka usual oak tray quote bana do\", \"doosra item kholo\", "
    "\"aaj kya karna hai\"."
)
