"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { linkClasses } from "@/components/ui/styles";
import { cx } from "@/lib/cx";
import { compareDecimalStr } from "@/lib/format/decimal";
import { formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { cuttingMessages as m } from "./messages";
import type { Board, Placement } from "./types";

/** Zoom steps of the canvas (the SVG width as a share of the frame); 1 fits the board to the frame. */
export const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6] as const;
/** Piece label height in board millimetres: about 13 px when a 2440 mm board fits an 800 px frame. */
const LABEL_MM = "40";
const PIECE_FILLS = ["fill-forest-tint", "fill-sand-tint", "fill-info-bg", "fill-success-bg", "fill-warning-bg", "fill-surface-sunken"] as const;

export function fillFor(lineNo: number, lines: readonly number[]): string {
  const index = lines.indexOf(lineNo);
  return PIECE_FILLS[(index < 0 ? 0 : index) % PIECE_FILLS.length]!;
}

/** Labels only where they fit: at least 250 mm along the length and 80 mm across (the table lists every piece). */
export function showsLabel(p: Pick<Placement, "along_length_mm" | "along_width_mm">): boolean {
  return compareDecimalStr(p.along_length_mm, "250") >= 0 && compareDecimalStr(p.along_width_mm, "80") >= 0;
}

export function pieceLabel(p: Placement): string {
  return [
    m.canvas.piece(p.sku, p.along_length_mm, p.along_width_mm),
    m.canvas.at(p.x_mm, p.y_mm),
    p.rotated ? m.canvas.rotated : null,
    p.is_extra ? m.canvas.extra : null,
  ]
    .filter(Boolean)
    .join(", ");
}

export function nextZoom(current: number, direction: 1 | -1): number {
  const index = ZOOM_STEPS.findIndex((step) => step === current);
  const next = Math.min(Math.max((index < 0 ? 0 : index) + direction, 0), ZOOM_STEPS.length - 1);
  return ZOOM_STEPS[next]!;
}

/**
 * One board drawn at true proportion: the SVG viewBox is the raw board in millimetres (x along the length, the
 * grain), the same coordinates the server's SVG and PDF use. Zoom widens the drawing inside a scrolling frame;
 * drag or the arrow keys pan. Every piece is focusable and names itself; the placement table below is the
 * accessible alternative to the drawing.
 */
export function BoardCanvas({ board, lines }: { board: Board; lines: readonly number[] }) {
  const { locale } = useZone();
  const [zoom, setZoom] = useState<number>(1);
  const [active, setActive] = useState<number | null>(null);
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const activePiece = board.placements.find((p) => p.seq === active) ?? null;
  const pct = (value: string) => formatDecimal(value, { locale, maxFractionDigits: 2 }) ?? value;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      setZoom((z) => nextZoom(z, 1));
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      setZoom((z) => nextZoom(z, -1));
    } else if (event.key === "0") {
      setZoom(1);
    }
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (zoom === 1 || !frame.current || event.pointerType === "touch") return;
    drag.current = { x: event.clientX, y: event.clientY, left: frame.current.scrollLeft, top: frame.current.scrollTop };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current || !frame.current) return;
    frame.current.scrollLeft = drag.current.left - (event.clientX - drag.current.x);
    frame.current.scrollTop = drag.current.top - (event.clientY - drag.current.y);
  };
  const endDrag = () => {
    drag.current = null;
  };

  return (
    <figure className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="quiet" onPress={() => setZoom((z) => nextZoom(z, -1))} {...unavailableWhen(zoom === 1 ? m.canvas.fit : null)}>
          {m.canvas.zoomOut}
        </Button>
        <Button size="sm" variant="quiet" onPress={() => setZoom(1)} {...unavailableWhen(zoom === 1 ? m.canvas.fit : null)}>
          {m.canvas.fit}
        </Button>
        <Button size="sm" variant="quiet" onPress={() => setZoom((z) => nextZoom(z, 1))} {...unavailableWhen(zoom === ZOOM_STEPS[ZOOM_STEPS.length - 1] ? m.canvas.zoom(zoom * 100) : null)}>
          {m.canvas.zoomIn}
        </Button>
        <span className="tabular text-sm text-ink-muted" aria-live="polite">
          {m.canvas.zoom(zoom * 100)}
        </span>
        {board.svg_path ? (
          <a href={board.svg_path} target="_blank" rel="noopener" className={cx(linkClasses, "ms-auto text-sm")}>
            {m.canvas.svg}
          </a>
        ) : null}
      </div>
      <div
        ref={frame}
        role="group"
        aria-label={m.canvas.label(board.index, board.raw_length_mm, board.raw_width_mm)}
        aria-describedby={`board-${board.index}-keys`}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        className="max-h-[70vh] overflow-auto rounded-md border bg-surface-sunken outline-hidden focus-visible:focus-ring"
      >
        <svg
          viewBox={`0 0 ${board.raw_length_mm} ${board.raw_width_mm}`}
          preserveAspectRatio="xMinYMin meet"
          style={{ width: `${zoom * 100}%`, display: "block" }}
          className="h-auto"
        >
          <rect x="0" y="0" width={board.raw_length_mm} height={board.raw_width_mm} className="fill-border" />
          <rect x={board.margin_mm} y={board.margin_mm} width={board.usable_length_mm} height={board.usable_width_mm} className="fill-surface" />
          {board.offcuts.map((o) => (
            <rect
              key={`o${o.seq}`}
              x={o.x_mm}
              y={o.y_mm}
              width={o.length_mm}
              height={o.width_mm}
              className="fill-none stroke-ink-muted"
              strokeWidth={1.5}
              strokeDasharray="6 4"
              vectorEffect="non-scaling-stroke"
            >
              <title>{m.canvas.offcut(o.length_mm, o.width_mm)}</title>
            </rect>
          ))}
          {board.placements.map((p) => {
            const isActive = p.seq === active;
            return (
              <svg key={p.seq} x={p.x_mm} y={p.y_mm} width={p.along_length_mm} height={p.along_width_mm}>
                <g
                  tabIndex={0}
                  role="img"
                  aria-label={pieceLabel(p)}
                  onFocus={() => setActive(p.seq)}
                  onMouseEnter={() => setActive(p.seq)}
                  className="cursor-default outline-hidden"
                >
                  <rect
                    width="100%"
                    height="100%"
                    className={`${p.is_extra ? "fill-sand" : fillFor(p.line_no, lines)} ${isActive ? "stroke-ink" : "stroke-forest"}`}
                    strokeWidth={isActive ? 3 : 1}
                    vectorEffect="non-scaling-stroke"
                  />
                  {p.rotated ? <line x1="78%" y1="100%" x2="100%" y2="78%" className="stroke-forest-strong" strokeWidth={2} vectorEffect="non-scaling-stroke" /> : null}
                  {showsLabel(p) ? (
                    <text x="50%" y="50%" fontSize={LABEL_MM} textAnchor="middle" dominantBaseline="central" className="fill-ink">
                      {p.sku}
                    </text>
                  ) : null}
                </g>
              </svg>
            );
          })}
        </svg>
      </div>
      <figcaption className="flex flex-col gap-1 text-sm">
        <p className="min-h-5 text-ink" aria-live="polite">
          {activePiece ? pieceLabel(activePiece) : <span className="text-ink-muted">{m.canvas.pick}</span>}
        </p>
        <p id={`board-${board.index}-keys`} className="text-ink-muted">
          {m.canvas.keys} {m.canvas.legend}
        </p>
        <p className="text-ink-muted">
          {m.results.boardEfficiency(pct(board.efficiency_pct))}
          {board.cut_count ? ` · ${m.canvas.cuts(board.cut_count)}` : ""}
        </p>
      </figcaption>
    </figure>
  );
}
