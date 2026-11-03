"""Cut-plan exports: placements and summary CSV (``core/csv_safe``), a PDF with one page per board
(``core/documents``) and a per-board SVG. All of them render the stored calculation; nothing is recomputed.

The SVG viewBox is in millimetres with the origin at the raw board's top-left (x along the length, the grain): a
shaded margin band, labelled pieces (extra pieces hatched), a corner mark on rotated pieces and dashed predicted
offcuts. The web canvas renders the same placements at the same true scale.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from sqlalchemy import select

from app.core.csv_safe import write_csv
from app.core.documents import (
    CONTENT_WIDTH,
    CompanyIdentity,
    board_drawing,
    build_pdf,
    format_datetime,
    line_table,
    para,
    section_heading,
    totals_block,
)
from app.modules.cutting.schemas import HEURISTIC_NOTE, BoardRead, CalculationRead, GroupRead, PlanDetail
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork

_PT_PER_MM = 72 / 25.4
_PIECE_FILLS = ("#CFE0D3", "#E6D9BF", "#D5DDE8", "#E8D3CF", "#DCE5C8", "#E3D6E6", "#C9DEDD", "#EADFCB")

PLACEMENT_HEADERS = (
    "plan_number", "calc_no", "group", "decor", "thickness_mm", "board", "seq", "line_no", "sku", "piece_no",
    "x_mm", "y_mm", "along_length_mm", "along_width_mm", "rotated", "extra",
)
SUMMARY_HEADERS = (
    "plan_number", "calc_no", "group", "decor", "thickness_mm", "line_no", "sku", "length_mm", "width_mm",
    "rotation_allowed", "required", "placed_required", "extra", "produced", "unfit", "unfit_reason",
    "group_boards", "group_efficiency_usable_pct", "group_scrap_pct",
)


def _f(v: Decimal) -> str:
    return format(v, "f")


def placements_csv(plan: PlanDetail, calc: CalculationRead) -> bytes:
    rows: list[list[Any]] = []
    for g in calc.groups:
        for b in g.boards:
            for p in b.placements:
                rows.append([
                    plan.plan_number, calc.calc_no, g.group_no, g.decor_key, g.thickness_mm, b.index, p.seq, p.line_no,
                    p.sku, p.piece_no, p.x_mm, p.y_mm, p.along_length_mm, p.along_width_mm, p.rotated, p.is_extra,
                ])
    return write_csv(PLACEMENT_HEADERS, rows)


def summary_csv(plan: PlanDetail, calc: CalculationRead) -> bytes:
    rows: list[list[Any]] = []
    for g in calc.groups:
        for i in g.items:
            rows.append([
                plan.plan_number, calc.calc_no, g.group_no, g.decor_key, g.thickness_mm, i.line_no, i.sku, i.length_mm,
                i.width_mm, i.rotation_allowed, i.required, i.placed_required, i.extra, i.produced, i.unfit,
                i.unfit_reason or "", g.board_count, g.efficiency_usable_pct, g.scrap_pct,
            ])
    return write_csv(SUMMARY_HEADERS, rows)


# ---- SVG ------------------------------------------------------------------------------------------
def board_svg(plan_number: str, group: GroupRead, board: BoardRead) -> str:
    L, W, m = board.raw_length_mm, board.raw_width_mm, board.margin_mm
    stroke = max(Decimal("1"), (L / 800).quantize(Decimal("0.1")))
    font = max(Decimal("12"), (L / 60).quantize(Decimal("1")))
    title = f"{plan_number} · group {group.group_no} ({group.decor_key or 'no decor'}, {group.thickness_mm} mm) · board {board.index}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_f(L)} {_f(W)}" width="{_f(L)}mm" height="{_f(W)}mm" '
        f'role="img" aria-labelledby="t">',
        f"<title id=\"t\">{escape(title)}</title>",
        '<defs><pattern id="extra" width="40" height="40" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<rect width="40" height="40" fill="#F1E3C6"/><line x1="0" y1="0" x2="0" y2="40" stroke="#C8A064" stroke-width="8"/>'
        "</pattern></defs>",
        f'<rect x="0" y="0" width="{_f(L)}" height="{_f(W)}" fill="#E7EAE3"/>',
        f'<rect x="{_f(m)}" y="{_f(m)}" width="{_f(L - 2 * m)}" height="{_f(W - 2 * m)}" fill="#FBFBF8" '
        f'stroke="#9AA39A" stroke-width="{_f(stroke)}" stroke-dasharray="{_f(stroke * 4)} {_f(stroke * 3)}"/>',
    ]
    fills: dict[int, str] = {}
    for p in board.placements:
        fill = "url(#extra)" if p.is_extra else fills.setdefault(p.line_no, _PIECE_FILLS[len(fills) % len(_PIECE_FILLS)])
        label = f"{p.sku} · {_f(p.along_length_mm)} × {_f(p.along_width_mm)}" + (" · rotated" if p.rotated else "") + (
            " · extra" if p.is_extra else ""
        )
        parts.append(
            f'<g><title>{escape(label)}</title><rect x="{_f(p.x_mm)}" y="{_f(p.y_mm)}" width="{_f(p.along_length_mm)}" '
            f'height="{_f(p.along_width_mm)}" fill={quoteattr(fill)} stroke="#2F5D3A" stroke-width="{_f(stroke)}"/>'
        )
        if p.rotated:
            n = min(p.along_length_mm, p.along_width_mm, Decimal(60)) * Decimal("0.6")
            x2, y2 = p.x_mm + p.along_length_mm, p.y_mm + p.along_width_mm
            parts.append(f'<polygon points="{_f(x2 - n)},{_f(y2)} {_f(x2)},{_f(y2)} {_f(x2)},{_f(y2 - n)}" fill="#2F5D3A"/>')
        if p.along_length_mm >= font * 4 and p.along_width_mm >= font * 2:
            cx, cy = p.x_mm + p.along_length_mm / 2, p.y_mm + p.along_width_mm / 2
            parts.append(
                f'<text x="{_f(cx)}" y="{_f(cy)}" font-family="Noto Sans, sans-serif" font-size="{_f(font)}" '
                f'text-anchor="middle" dominant-baseline="middle" fill="#1F2A22">{escape(p.sku)}</text>'
            )
        parts.append("</g>")
    for o in board.offcuts:
        parts.append(
            f'<rect x="{_f(o.x_mm)}" y="{_f(o.y_mm)}" width="{_f(o.length_mm)}" height="{_f(o.width_mm)}" fill="none" '
            f'stroke="#6B746C" stroke-width="{_f(stroke)}" stroke-dasharray="{_f(stroke * 6)} {_f(stroke * 4)}">'
            f"<title>Predicted offcut {_f(o.length_mm)} × {_f(o.width_mm)} mm</title></rect>"
        )
    parts.append(f'<rect x="0" y="0" width="{_f(L)}" height="{_f(W)}" fill="none" stroke="#1F2A22" stroke-width="{_f(stroke * 2)}"/>')
    parts.append("</svg>")
    return "".join(parts)


# ---- PDF ------------------------------------------------------------------------------------------
def _identity(uow: UnitOfWork) -> CompanyIdentity:
    row = uow.session.execute(
        select(Company.legal_name, Company.display_name).where(Company.id == uow.actor.company_id)
    ).first()
    legal, display = (row[0], row[1]) if row else ("Company", "Company")
    return CompanyIdentity(
        legal_name=legal, display_name=display, address_lines=("Address not configured",),
        footer_terms=f"Cut plan · {HEURISTIC_NOTE}",
    )


def plan_pdf(uow: UnitOfWork, plan: PlanDetail, calc: CalculationRead, zone: str) -> bytes:
    t = calc.totals
    story: list[Any] = []
    story += section_heading("Summary", min_space_below=20)
    story.append(
        totals_block(
            [
                ("Boards", f"{t.boards} (area lower bound {t.lower_bound_boards})"),
                ("Pieces placed / required", f"{t.placed_required} / {t.required}"),
                ("Extra pieces", str(t.extra)),
                ("Unfit pieces", str(t.unfit)),
                ("Scrap", f"{_f(t.scrap_pct)} %"),
                ("Efficiency (usable area)", f"{_f(t.efficiency_usable_pct)} %"),
            ]
        )
    )
    s = calc.settings
    story.append(
        para(
            f"Board {_f(s.board_length_mm)} × {_f(s.board_width_mm)} mm, margin {_f(s.margin_mm)} mm, gap {_f(s.gap_mm)} mm, "
            f"{s.mode} layout. {HEURISTIC_NOTE}.",
            "small",
        )
    )
    if calc.requires_physical_verification:
        story.append(
            para(
                f"Assumes {_f(s.raw_length_mm)} × {_f(s.raw_width_mm)} mm boards (+{_f(s.oversize_mm)} mm oversize per side): "
                "verify the physical boards before release.",
                "small",
            )
        )
    item_rows: list[list[str]] = []
    for g in calc.groups:
        for i in g.items:
            item_rows.append([
                str(g.group_no), g.decor_key or "—", g.thickness_mm, i.sku, f"{_f(i.length_mm)} × {_f(i.width_mm)}",
                str(i.required), str(i.produced), str(i.unfit), (i.unfit_reason or "").replace("_", " "),
            ])
    story += section_heading("Pieces", min_space_below=20)
    story.append(
        line_table(
            ["Group", "Decor", "Thick.", "SKU", "Size (mm)", "Req.", "Prod.", "Unfit", "Reason"],
            item_rows,
            [5, 9, 6, 16, 14, 6, 6, 6, 16],
            numeric_cols=(5, 6, 7),
        )
    )
    for g in calc.groups:
        for b in g.boards:
            story += section_heading(
                f"Board {b.index} · group {g.group_no} ({g.decor_key or 'no decor'}, {g.thickness_mm} mm) · "
                f"{_f(b.efficiency_pct)} % used",
                min_space_below=150 * _PT_PER_MM,
            )
            pieces: list[dict[str, Any]] = [
                {"x": p.x_mm, "y": p.y_mm, "w": p.along_length_mm, "h": p.along_width_mm, "label": p.sku,
                 "rotated": p.rotated, "kind": "extra" if p.is_extra else "piece", "group": str(p.line_no)}
                for p in b.placements
            ] + [
                {"x": o.x_mm, "y": o.y_mm, "w": o.length_mm, "h": o.width_mm, "label": "", "kind": "offcut"}
                for o in b.offcuts
            ]
            story.append(
                board_drawing(b.raw_length_mm, b.raw_width_mm, pieces, CONTENT_WIDTH, margin_mm=b.margin_mm,
                              max_height_pt=95 * _PT_PER_MM)
            )
            story.append(
                line_table(
                    ["#", "SKU", "x", "y", "Along length", "Along width", "Rotated", "Extra"],
                    [
                        [str(p.seq), p.sku, _f(p.x_mm), _f(p.y_mm), _f(p.along_length_mm), _f(p.along_width_mm),
                         "yes" if p.rotated else "", "yes" if p.is_extra else ""]
                        for p in b.placements
                    ],
                    [4, 18, 8, 8, 10, 10, 7, 6],
                    numeric_cols=(0, 2, 3, 4, 5),
                )
            )
    meta = [
        ("Plan", plan.plan_number),
        ("Name", plan.name),
        ("Calculation", f"#{calc.calc_no}"),
        ("Calculated", format_datetime(calc.created_at, zone)),
    ]
    return build_pdf("Cut plan", _identity(uow), meta, story, reference=f"{plan.plan_number} #{calc.calc_no}",
                     subject=f"Cut plan {plan.plan_number} calculation {calc.calc_no}")
