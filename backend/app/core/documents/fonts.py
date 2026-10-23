"""Embedded fonts, script runs and complex-script shaping for the document engine.

Two families are embedded (both SIL OFL, see ``fonts/OFL.txt``):

* ``LK-Sans`` - Noto Sans regular/bold/italic. Latin, extended Latin, Greek, Cyrillic, and the
  currency signs the legacy Helvetica output could not print (€ ₹ £).
* ``LK-Deva`` - Noto Sans Devanagari regular/bold, for Hindi/Marathi party names and addresses.

Devanagari needs OpenType shaping (conjuncts, half forms, pre-base matra reordering). ReportLab 5
does this through uharfbuzz when a ``ParagraphStyle`` has ``shaping=1``. Two library gaps are
closed here, once, at registration:

1. ReportLab shapes a whole word with the *first* fragment's font. A word that mixes scripts with
   no space between them (``क्राउन-Decor``) would come out as garbage glyphs. The installed hook
   shapes each same-font run of a word separately.
2. Shaped glyphs that have no cmap entry (conjuncts, matra variants) are given private-use code
   points, so text extraction and copy/paste produced U+E000.. characters. The hook records the
   source characters of each shaped cluster and writes them into the ToUnicode CMap instead.
   Extraction then returns real Devanagari; a pre-base matra (ि) still extracts in visual order,
   before its consonant, because a ToUnicode map cannot reorder.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics, ttfonts
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import paragraph as rl_paragraph

FONT_DIR = Path(__file__).with_name("fonts")

SANS = "LK-Sans"
SANS_BOLD = "LK-Sans-Bold"
SANS_ITALIC = "LK-Sans-Italic"
DEVA = "LK-Deva"
DEVA_BOLD = "LK-Deva-Bold"

_FONT_FILES: dict[str, str] = {
    SANS: "NotoSans-Regular.ttf",
    SANS_BOLD: "NotoSans-Bold.ttf",
    SANS_ITALIC: "NotoSans-Italic.ttf",
    DEVA: "NotoSansDevanagari-Regular.ttf",
    DEVA_BOLD: "NotoSansDevanagari-Bold.ttf",
}

_lock = threading.Lock()
_registered = False
#: ReportLab keeps process-global font and shaping state (shaping adds glyphs to the shared font
#: faces), so layout - anything that wraps a Paragraph - runs under this lock, one at a time.
RENDER_LOCK = threading.RLock()
#: cmap code points of each registered font as shipped (before shaping adds private-use entries).
_SHIPPED_CMAP: dict[str, frozenset[int]] = {}
#: per embedded face name: private-use code point -> the source characters its glyph renders.
_GLYPH_TEXT: dict[str, dict[int, str]] = {}

_original_shape_frag_word: Callable[..., Any] = ttfonts.shapeFragWord
_original_to_unicode_cmap: Callable[[str, Sequence[int]], str] = ttfonts.makeToUnicodeCMap


def register_fonts() -> None:
    """Register the embedded families and install the shaping hooks. Safe to call repeatedly."""
    global _registered
    if _registered:
        return
    with _lock:
        if _registered:
            return
        if ttfonts.uharfbuzz is None:
            raise RuntimeError(
                "uharfbuzz is not importable; install reportlab[shaping] - Devanagari would render unshaped"
            )
        for name, file_name in _FONT_FILES.items():
            path = FONT_DIR / file_name
            if not path.is_file():
                raise FileNotFoundError(f"embedded font missing: {path}")
            font = TTFont(name, str(path), shapable=True)
            pdfmetrics.registerFont(font)
            _SHIPPED_CMAP[name] = frozenset(font.face.charToGlyph)
        # No bold-italic or Devanagari italic files exist; those map to the nearest real face.
        for family, normal, bold, italic, bold_italic in (
            (SANS, SANS, SANS_BOLD, SANS_ITALIC, SANS_BOLD),
            (DEVA, DEVA, DEVA_BOLD, DEVA, DEVA_BOLD),
        ):
            addMapping(family, 0, 0, normal)
            addMapping(family, 1, 0, bold)
            addMapping(family, 0, 1, italic)
            addMapping(family, 1, 1, bold_italic)
        rl_paragraph.shapeFragWord = _shape_frag_word  # type: ignore[attr-defined]
        ttfonts.makeToUnicodeCMap = _to_unicode_cmap
        _registered = True


# --------------------------------------------------------------------------- script runs


_DEVANAGARI = "\u0900-\u097f\ua8e0-\ua8ff\u1cd0-\u1cff\U00011b00-\U00011b5f"
_DEVANAGARI_RE = re.compile(f"[{_DEVANAGARI}]")
_NBSP = "\u00a0"
_JOINERS = frozenset("\u200c\u200d")


def is_devanagari(ch: str) -> bool:
    return _DEVANAGARI_RE.match(ch) is not None


def needs_shaping(text: str) -> bool:
    """True when the text contains a script that renders wrongly without OpenType shaping."""
    return _DEVANAGARI_RE.search(text) is not None


def coverage_gaps(text: str) -> frozenset[str]:
    """Characters neither embedded family can draw (they would print as empty boxes)."""
    register_fonts()
    sans, deva = _SHIPPED_CMAP[SANS], _SHIPPED_CMAP[DEVA]
    return frozenset(
        ch
        for ch in text
        if not ch.isspace() and ord(ch) not in sans and ord(ch) not in deva and ch.isprintable()
    )


def _clean(text: str) -> str:
    """Normalise line breaks and spaces; drop control, format and private-use characters, which
    have no glyph and can break paragraph parsing. Joiners (ZWJ/ZWNJ) and NBSP are kept."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.isprintable():
        return text
    out: list[str] = []
    for ch in text:
        if ch == "\n" or ch == _NBSP or ch in _JOINERS or ch.isprintable():
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
    return "".join(out)


def _word_runs(word: str) -> list[tuple[bool, str]]:
    """Split one whitespace-free word into (is_devanagari_font, text) runs."""
    if not needs_shaping(word):
        return [(False, word)]
    deva_cmap = _SHIPPED_CMAP[DEVA]
    if all(ord(ch) in deva_cmap for ch in word):
        return [(True, word)]
    runs: list[tuple[bool | None, str]] = []
    for ch in word:
        if is_devanagari(ch):
            kind: bool | None = True
        elif ord(ch) in deva_cmap:
            kind = None  # neutral: digits, punctuation, joiners, ₹ - join the surrounding run
        else:
            kind = False
        if runs and (kind is None or runs[-1][0] is None or runs[-1][0] == kind):
            prev_kind, prev_text = runs[-1]
            runs[-1] = (kind if prev_kind is None else prev_kind, prev_text + ch)
        else:
            runs.append((kind, ch))
    return [(bool(kind), text) for kind, text in runs]


def script_markup(text: str, *, bold: bool = False) -> str:
    """Escape plain text for a ReportLab Paragraph and route Devanagari runs to ``LK-Deva``.

    Line breaks become ``<br/>``. Pass ``bold=True`` when the markup sits inside ``<b>`` or in a
    bold style: ReportLab's ``<font face>`` resets the bold flag, so the bold face is named directly.
    Never feed unescaped user text to a Paragraph; use this or ``layout.para``.
    """
    register_fonts()
    cleaned = _clean(text)
    if not needs_shaping(cleaned):
        return escape(cleaned).replace("\n", "<br/>")
    lines = cleaned.split("\n")
    rendered_lines: list[str] = []
    for line in lines:
        parts: list[str] = []
        word = ""
        for ch in line:
            if ch.isspace():
                if word:
                    parts.append(_render_word(word, bold))
                    word = ""
                parts.append(ch)
            else:
                word += ch
        if word:
            parts.append(_render_word(word, bold))
        rendered_lines.append("".join(parts))
    return "<br/>".join(rendered_lines)


def _render_word(word: str, bold: bool) -> str:
    face = DEVA_BOLD if bold else DEVA
    out: list[str] = []
    for deva, text in _word_runs(word):
        escaped = escape(text)
        out.append(f'<font face="{face}">{escaped}</font>' if deva else escaped)
    return "".join(out)


# --------------------------------------------------------------------------- shaping hooks


def _call_original(word: list[Any], features: dict[str, bool] | None, force: bool) -> list[Any]:
    if features is None:
        return _original_shape_frag_word(word, force=force)
    return _original_shape_frag_word(word, features, force)


def _shape_frag_word(w: list[Any], features: dict[str, bool] | None = None, force: bool = False) -> list[Any]:
    """Shape each same-font run of a Paragraph word separately (see module docstring, gap 1)."""
    if isinstance(w, ttfonts.ShapedFragWord):
        return w
    items = w[1:]
    has_special = any(hasattr(f, "cbDefn") for f, _ in items)
    fonts = {f.fontName for f, _ in items if not hasattr(f, "cbDefn")}
    if len(fonts) <= 1 or has_special:
        shaped = _call_original(w, features, force)
        if shaped is not w:
            _remember_clusters("".join(s for f, s in items if not hasattr(f, "cbDefn")), shaped)
        return shaped

    runs: list[list[Any]] = []
    for item in items:
        if runs and runs[-1][-1][0].fontName == item[0].fontName:
            runs[-1].append(item)
        else:
            runs.append([item])
    natural = [sum(pdfmetrics.stringWidth(s, f.fontName, f.fontSize) for f, s in run) for run in runs]
    total = sum(natural) or 1.0
    width = 0.0
    merged: list[Any] = []
    changed = False
    for run, run_natural in zip(runs, natural, strict=True):
        sub = [w[0] * run_natural / total, *run]
        shaped = _call_original(sub, features, force)
        if shaped is not sub:
            changed = True
            _remember_clusters("".join(s for _, s in run), shaped)
        width += shaped[0]
        merged.extend(shaped[1:])
    if not changed:
        return w
    return ttfonts.makeShapedFragWord(w)([width, *merged])


def _face_key(font: Any) -> str:
    face = font.face
    return (face.name + face.subfontNameX).decode("latin-1")


def _remember_clusters(text: str, shaped: list[Any]) -> None:
    """Record which source characters each private-use glyph of a shaped word renders."""
    glyphs: list[tuple[str, int, int]] = []  # (font name, code point, cluster)
    for frag, s in shaped[1:]:
        data = getattr(s, "__shapeData__", None)
        if data is None:
            continue
        for ch, sd in zip(s, data, strict=False):
            glyphs.append((frag.fontName, ord(ch), sd.cluster))
    if not glyphs:
        return
    starts = sorted({c for _, _, c in glyphs if c >= 0})
    by_cluster: dict[int, list[tuple[str, int]]] = {}
    for font_name, cp, cluster in glyphs:
        by_cluster.setdefault(cluster, []).append((font_name, cp))
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        remaining = list(text[start:end])
        private: list[tuple[str, int]] = []
        for font_name, cp in by_cluster.get(start, []):
            shipped = _SHIPPED_CMAP.get(font_name)
            if shipped is not None and cp not in shipped:
                private.append((font_name, cp))
            elif chr(cp) in remaining:
                remaining.remove(chr(cp))
        if not private or not remaining:
            continue
        # A cluster can hold several private glyphs (त्रि = i-matra variant + t_ra conjunct).
        # Attribute the ones whose text is known first; the single glyph left takes the rest.
        unresolved: list[tuple[str, int]] = []
        for font_name, cp in private:
            known = _GLYPH_TEXT.get(_face_key(pdfmetrics.getFont(font_name)), {}).get(cp)
            known = known or _MARK_GLYPH_TEXT.get(_glyph_base_name(font_name, cp))
            if known and _take(remaining, known):
                _learn(font_name, cp, known)
            else:
                unresolved.append((font_name, cp))
        if len(unresolved) == 1 and remaining:
            _learn(*unresolved[0], "".join(remaining))


#: Noto Sans Devanagari glyph-name stems of reordered or attached forms -> the characters they draw.
_MARK_GLYPH_TEXT = {"iMatra": "ि", "reph": "र्", "rakar": "्र"}


def _glyph_base_name(font_name: str, cp: int) -> str:
    font = pdfmetrics.getFont(font_name)
    gid = font.face.charToGlyph.get(cp)
    if gid is None:
        return ""
    name = font.hbFont().glyph_to_string(gid)
    return name.split(".", 1)[0].split("-", 1)[0]


def _take(remaining: list[str], text: str) -> bool:
    """Remove the characters of ``text`` from ``remaining`` if all are present."""
    pool = list(remaining)
    for ch in text:
        if ch not in pool:
            return False
        pool.remove(ch)
    remaining[:] = pool
    return True


def _learn(font_name: str, cp: int, text: str) -> None:
    key = _face_key(pdfmetrics.getFont(font_name))
    _GLYPH_TEXT.setdefault(key, {}).setdefault(cp, text)


def _utf16_hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _chunks(seq: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _to_unicode_cmap(fontname: str, subset: Sequence[int]) -> str:
    """ToUnicode CMap that maps shaped private-use glyphs back to their source text (gap 2).

    Also keeps every bfchar block at or under the 100 entries the PDF specification allows.
    """
    mapping = _GLYPH_TEXT.get(fontname.split("+", 1)[-1], {})
    entries = [f"<{i:02X}> <{_utf16_hex(mapping.get(cp) or chr(cp))}>" for i, cp in enumerate(subset)]
    cmap = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo",
        f"<< /Registry ({fontname})",
        f"/Ordering ({fontname})",
        "/Supplement 0",
        ">> def",
        f"/CMapName /{fontname} def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        f"<00> <{len(subset) - 1:02X}>",
        "endcodespacerange",
    ]
    for chunk in _chunks(entries, 100):
        cmap.append(f"{len(chunk)} beginbfchar")
        cmap.extend(chunk)
        cmap.append("endbfchar")
    cmap += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(cmap)
