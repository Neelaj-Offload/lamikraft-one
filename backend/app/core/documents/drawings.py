"""True-proportion board drawings for cut-plan PDFs, drawn with ``reportlab.graphics``.

Coordinates follow the cutting module: millimetres, origin at the raw board's top-left, x along
the board length (the grain), y along its width, growing downwards. The drawing flips y for PDF.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal, NotRequired, TypedDict

from reportlab.graphics.shapes import Drawing, Group, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics

from app.core.documents.fonts import DEVA, SANS, SANS_BOLD, needs_shaping, register_fonts
from app.core.documents.layout import BORDER_CONTROL, FOREST, INK, INK_MUTED

Number = int | float | Decimal
PlacementKind = Literal["piece", "extra", "offcut"]


class Placement(TypedDict):
    x: Number
    y: Number
    w: Number
    h: Number
    label: str
    rotated: NotRequired[bool]
    #: piece = required part, extra = bounded overproduction, offcut = predicted reusable remnant
    kind: NotRequired[PlacementKind]
    #: pieces of the same group (e.g. the plan line) share a fill colour; defaults to the label
    group: NotRequired[str]


#: Muted fills for pieces; the same group always gets the same colour within a drawing.
_PIECE_FILLS = tuple(
    colors.HexColor(h)
    for h in ("#CFE0D3", "#E6D9BF", "#D5DDE8", "#E8D3CF", "#DCE5C8", "#E3D6E6", "#C9DEDD", "#EADFCB")
)
_EXTRA_FILL = colors.HexColor("#F1E3C6")
_BOARD_FILL = colors.HexColor("#FBFBF8")
_MARGIN_FILL = colors.HexColor("#E7EAE3")
_CAPTION_HEIGHT = 14.0
_MIN_LABEL_SIZE = 4.0
_MAX_LABEL_SIZE = 8.0
_EPSILON = 1e-6


def _num(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise TypeError(f"{what} must be a number, not {type(value).__name__}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{what} must be finite")
    return number


def _fmt_mm(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _fit_label(text: str, font: str, box_w: float, box_h: float) -> tuple[float, bool] | None:
    """Largest font size (and whether to run the label vertically) that fits the piece."""
    unit = pdfmetrics.stringWidth(text, font, 1)
    if unit <= 0:
        return None
    best: tuple[float, bool] | None = None
    for vertical, along, across in ((False, box_w, box_h), (True, box_h, box_w)):
        size = min(_MAX_LABEL_SIZE, (along - 4) / unit, (across - 2) / 1.2)
        if size >= _MIN_LABEL_SIZE and (best is None or size > best[0] + 0.5):
            best = (size, vertical)
    return best


def board_drawing(
    board_w_mm: Number,
    board_h_mm: Number,
    placements: Sequence[Mapping[str, object]],
    max_width_pt: float,
    *,
    margin_mm: Number = 0,
    max_height_pt: float | None = None,
    caption: str | None = None,
) -> Drawing:
    """Draw one board at true proportion, scaled to ``max_width_pt`` (and ``max_height_pt``).

    The trim margin is a shaded band; pieces are filled and labelled (labels shrink, turn
    vertical, or are omitted when the piece is too small - the plan's table still lists them);
    rotated pieces carry a corner mark; offcuts are dashed. Placements outside the board raise.
    Labels are drawn unshaped (graphics strings have no HarfBuzz path): keep them to part codes.
    """
    register_fonts()
    board_w = _num(board_w_mm, "board_w_mm")
    board_h = _num(board_h_mm, "board_h_mm")
    margin = _num(margin_mm, "margin_mm")
    if board_w <= 0 or board_h <= 0:
        raise ValueError("board dimensions must be positive")
    if margin < 0 or 2 * margin >= min(board_w, board_h):
        raise ValueError("margin must be non-negative and leave a usable area")
    if max_width_pt <= 0:
        raise ValueError("max_width_pt must be positive")

    scale = max_width_pt / board_w
    if max_height_pt is not None:
        if max_height_pt <= _CAPTION_HEIGHT:
            raise ValueError("max_height_pt too small for the board and its caption")
        scale = min(scale, (max_height_pt - _CAPTION_HEIGHT) / board_h)
    width_pt, height_pt = board_w * scale, board_h * scale
    drawing = Drawing(width_pt, height_pt + _CAPTION_HEIGHT)
    drawing.initialFontName = SANS  # the renderer would otherwise reference non-embedded Times-Roman
    drawing.initialFontSize = 7
    top = height_pt + _CAPTION_HEIGHT  # board top edge in drawing coordinates

    def box(x_mm: float, y_mm: float, w_mm: float, h_mm: float) -> tuple[float, float, float, float]:
        return x_mm * scale, top - (y_mm + h_mm) * scale, w_mm * scale, h_mm * scale

    bx, by, bw, bh = box(0, 0, board_w, board_h)
    drawing.add(Rect(bx, by, bw, bh, fillColor=_MARGIN_FILL if margin else _BOARD_FILL, strokeColor=None))
    if margin:
        drawing.add(
            Rect(
                *box(margin, margin, board_w - 2 * margin, board_h - 2 * margin),
                fillColor=_BOARD_FILL,
                strokeColor=BORDER_CONTROL,
                strokeWidth=0.4,
                strokeDashArray=[2, 1.5],
            )
        )

    fills: dict[str, colors.Color] = {}
    for index, raw in enumerate(placements, start=1):
        x = _num(raw.get("x"), f"placement {index} x")
        y = _num(raw.get("y"), f"placement {index} y")
        w = _num(raw.get("w"), f"placement {index} w")
        h = _num(raw.get("h"), f"placement {index} h")
        label = str(raw.get("label") or "")
        rotated = bool(raw.get("rotated", False))
        kind = raw.get("kind", "piece")
        if kind not in ("piece", "extra", "offcut"):
            raise ValueError(f"placement {index}: unknown kind {kind!r}")
        if w <= 0 or h <= 0:
            raise ValueError(f"placement {index}: width and height must be positive")
        if x < -_EPSILON or y < -_EPSILON or x + w > board_w + _EPSILON or y + h > board_h + _EPSILON:
            raise ValueError(f"placement {index} ({label}) lies outside the {board_w:g} x {board_h:g} board")
        px, py, pw, ph = box(x, y, w, h)
        if kind == "offcut":
            drawing.add(
                Rect(
                    px,
                    py,
                    pw,
                    ph,
                    fillColor=None,
                    strokeColor=INK_MUTED,
                    strokeWidth=0.5,
                    strokeDashArray=[3, 2],
                )
            )
            text_color = INK_MUTED
        else:
            if kind == "extra":
                fill = _EXTRA_FILL
            else:
                group = str(raw.get("group") or label)
                fill = fills.setdefault(group, _PIECE_FILLS[len(fills) % len(_PIECE_FILLS)])
            drawing.add(Rect(px, py, pw, ph, fillColor=fill, strokeColor=FOREST, strokeWidth=0.5))
            text_color = INK
        if rotated:
            notch = min(pw, ph, 7.0) * 0.6
            drawing.add(
                Polygon(
                    [px + pw - notch, py + ph, px + pw, py + ph, px + pw, py + ph - notch],
                    fillColor=FOREST,
                    strokeColor=None,
                )
            )
        if label:
            _label(drawing, label, px, py, pw, ph, text_color)

    caption_text = caption or (
        f"{_fmt_mm(board_w)} × {_fmt_mm(board_h)} mm"
        + (f"  ·  {_fmt_mm(margin)} mm trim margin" if margin else "")
        + "  ·  corner mark = rotated 90°  ·  dashed = offcut"
    )
    caption_font = DEVA if needs_shaping(caption_text) else SANS
    caption_size = min(7.0, width_pt / max(pdfmetrics.stringWidth(caption_text, caption_font, 1), _EPSILON))
    drawing.add(String(0, 3, caption_text, fontName=caption_font, fontSize=caption_size, fillColor=INK_MUTED))
    drawing.add(Rect(bx, by, bw, bh, fillColor=None, strokeColor=INK, strokeWidth=0.8))
    return drawing


def _label(
    drawing: Drawing, label: str, px: float, py: float, pw: float, ph: float, color: colors.Color
) -> None:
    font = DEVA if needs_shaping(label) else SANS_BOLD
    fit = _fit_label(label, font, pw, ph)
    if fit is None:
        return
    size, vertical = fit
    cx, cy = px + pw / 2, py + ph / 2
    text = String(0, -size * 0.35, label, fontName=font, fontSize=size, fillColor=color, textAnchor="middle")
    group = Group(text)
    group.translate(cx, cy)
    if vertical:
        group.rotate(90)
    drawing.add(group)
