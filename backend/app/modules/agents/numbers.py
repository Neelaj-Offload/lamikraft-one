"""Number literals in user text: digits (with Indian or Western grouping and decimals), English number words and a
small, explicitly untested Hinglish vocabulary (ai-routing.md section 6).

Used by numeric provenance (a model-supplied quantity must occur literally in the user's turn) and by the Demo
slot extractor.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

#: digits with optional grouping (1,00,000 or 1,000) and an optional decimal part; never attached to letters/hyphens
DIGIT_LITERAL = re.compile(r"(?<![\w.\-/])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w.\-/]|,\d)")

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
MULTIPLIERS = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "crore": 10_000_000,
               "crores": 10_000_000, "million": 1_000_000}
#: Hinglish number words: recognised for slot extraction, labelled untested (no speech corpus yet)
HINGLISH_UNITS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6, "saat": 7,
    "aath": 8, "nau": 9, "das": 10, "bees": 20, "tees": 30, "chaalis": 40, "chalis": 40, "pachas": 50,
    "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
}
HINGLISH_MULTIPLIERS = {"sau": 100, "hazaar": 1_000, "hazar": 1_000, "lakh": 100_000, "crore": 10_000_000}
_WORD = re.compile(r"[a-z]+")


def parse_decimal(literal: str) -> Decimal | None:
    try:
        value = Decimal(literal.replace(",", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def digit_literals(text: str) -> list[Decimal]:
    out: list[Decimal] = []
    for match in DIGIT_LITERAL.finditer(text):
        value = parse_decimal(match.group(1))
        if value is not None:
            out.append(value)
    return out


def _words_to_numbers(words: list[str], units: dict[str, int], multipliers: dict[str, int]) -> list[int]:
    """Greedy left-to-right phrase parser: 'two hundred forty' -> 240, 'five thousand seven hundred sixty' -> 5760."""
    results: list[int] = []
    total = current = 0
    active = False
    for word in words:
        if word in units:
            current += units[word]
            active = True
        elif word in TENS and units is UNITS:
            current += TENS[word]
            active = True
        elif word in multipliers and active:
            factor = multipliers[word]
            if factor >= 1000:
                total += (current or 1) * factor
                current = 0
            else:
                current = (current or 1) * factor
        elif word in ("and",) and active:
            continue
        else:
            if active:
                results.append(total + current)
            total = current = 0
            active = False
    if active:
        results.append(total + current)
    return results


def word_literals(text: str) -> list[Decimal]:
    words = _WORD.findall(text.lower().replace("-", " "))
    values = [Decimal(v) for v in _words_to_numbers(words, UNITS, MULTIPLIERS)]
    return values


def hinglish_word_literals(text: str) -> list[Decimal]:
    """Hinglish number words (untested vocabulary, see module docstring)."""
    words = _WORD.findall(text.lower())
    return [Decimal(v) for v in _words_to_numbers(words, HINGLISH_UNITS, HINGLISH_MULTIPLIERS)]


def literals(text: str, *, hinglish: bool = True) -> set[Decimal]:
    """Every numeric value the text states, as Decimals (``240``, ``5760.00``, ``1,00,000``, 'two hundred forty')."""
    found = set(digit_literals(text)) | set(word_literals(text))
    if hinglish:
        found |= set(hinglish_word_literals(text))
    return found


def mentions(text: str, value: Decimal | int | str) -> bool:
    """True when ``value`` occurs literally in ``text`` (digits in any grouping, or number words)."""
    target = value if isinstance(value, Decimal) else Decimal(str(value))
    return any(v == target for v in literals(text))


def first_quantity(text: str) -> Decimal | None:
    """The first number stated in the text (digits first, then English words, then Hinglish words)."""
    digits = digit_literals(text)
    if digits:
        return digits[0]
    words = word_literals(text)
    if words:
        return words[0]
    hinglish = hinglish_word_literals(text)
    return hinglish[0] if hinglish else None
