"use client";

import { useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Board, Placement } from "@/features/cutting/types";
import { cx } from "@/lib/cx";
import { nextZoom, pieceShowsLabel, ZOOM_STEPS } from "~/data/cutting";
import { Button, ExternalLink, IconButton } from "~/ui";
import { mm, Pct } from "./parts";

/** Piece label height in board millimetres: about 13px when a 2440 mm board fits an 800px frame. */
const LABEL_MM = 40;
/** One quiet tint per cut-list row, repeating after five; the label and the table name every piece. */
const PIECE_FILLS = ["fill-cobalt-soft", "fill-leaf-soft", "fill-amber-soft", "fill-sand-soft", "fill-sand"] as const;
const SWATCH_BG = ["bg-cobalt-soft", "bg-leaf-soft", "bg-amber-soft", "bg-sand-soft", "bg-sand"] as const;

function tintIndex(lineNo: number, lines: readonly number[]): number {
  const index = lines.indexOf(lineNo);
  return (index < 0 ? 0 : index) % PIECE_FILLS.length;
}

/** What a piece says about itself, to the eye under the drawing and to a screen reader on focus. */
export function describePiece(piece: Placement): string {
  return [
    `${piece.sku}, ${mm(piece.along_length_mm)} × ${mm(piece.along_width_mm)} mm`,
    `at ${mm(piece.x_mm)}, ${mm(piece.y_mm)} mm`,
    piece.rotated ? "rotated 90°" : null,
    piece.is_extra ? "extra piece" : null,
  ]
    .filter(Boolean)
    .join(", ");
}

/**
 * The rotated-piece mark: a short 45° line across the bottom-right corner, sized from the piece's
 * shorter side so tall and wide pieces get the same mark. Drawing coordinates only, never quantities.
 */
function RotatedMark({ length, width }: { length: string; width: string }) {
  const l = Number(length);
  const w = Number(width);
  const c = Math.min(l, w) * 0.22;
  return <line x1={l - c} y1={w} x2={l} y2={w - c} className="stroke-ink" strokeWidth={2} vectorEffect="non-scaling-stroke" />;
}

function LegendItem({ children, swatch }: { children: string; swatch: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden="true" className="flex h-4 w-6 flex-none items-center justify-center">
        {swatch}
      </span>
      {children}
    </li>
  );
}

/**
 * One board drawn at true proportion. The viewBox is the raw board in millimetres (x along the
 * length, which is the grain), the same coordinates the exported drawing and the PDF use. Zoom
 * widens the drawing inside a scrolling frame; drag or the arrow keys pan. Every piece takes focus
 * and names itself; the placement table beside it is the full alternative to the picture.
 */
export function BoardDrawing({ board, lines, skus }: { board: Board; lines: readonly number[]; skus: ReadonlyMap<number, string> }) {
  const uid = useId();
  const hatchId = `${uid}-hatch`;
  const keysId = `${uid}-keys`;
  const [zoom, setZoom] = useState<number>(1);
  const [active, setActive] = useState<number | null>(null);
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const activePiece = board.placements.find((piece) => piece.seq === active) ?? null;
  const fitted = zoom === ZOOM_STEPS[0];
  const largest = zoom === ZOOM_STEPS[ZOOM_STEPS.length - 1];
  const usedLines = lines.filter((lineNo) => board.placements.some((piece) => piece.line_no === lineNo));
  const hasRotated = board.placements.some((piece) => piece.rotated);
  const hasExtra = board.placements.some((piece) => piece.is_extra);

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
    if (fitted || !frame.current || event.pointerType === "touch") return;
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
    <figure className="flex min-w-0 flex-col gap-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <IconButton icon="minus" label="Zoom out" size="sm" isDisabled={fitted} onPress={() => setZoom((z) => nextZoom(z, -1))} />
        <IconButton icon="plus" label="Zoom in" size="sm" isDisabled={largest} onPress={() => setZoom((z) => nextZoom(z, 1))} />
        <Button variant="ghost" size="sm" isDisabled={fitted} onPress={() => setZoom(1)}>
          Fit the board
        </Button>
        <span className="t-caption lk-tnum text-ink-3" aria-live="polite">
          {zoom * 100}%
        </span>
        {board.svg_path ? (
          <ExternalLink href={board.svg_path} className="t-body-sm ml-auto">
            Open the drawing
          </ExternalLink>
        ) : null}
      </div>

      <div
        ref={frame}
        role="group"
        aria-label={`Board ${board.index}, ${mm(board.raw_length_mm)} × ${mm(board.raw_width_mm)} mm, drawn to scale`}
        aria-describedby={keysId}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        className={cx("max-h-[70vh] min-w-0 overflow-auto rounded-md border border-line-strong bg-ground-deep p-2", !fitted && "cursor-grab")}
      >
        <svg viewBox={`0 0 ${board.raw_length_mm} ${board.raw_width_mm}`} preserveAspectRatio="xMinYMin meet" className="block h-auto" style={{ width: `${zoom * 100}%` }}>
          <defs>
            <pattern id={hatchId} width="36" height="36" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="36" className="stroke-ink-3" strokeWidth="6" />
            </pattern>
          </defs>
          {/* the raw board: what shows around the usable area is the edge margin that gets trimmed */}
          <rect x="0" y="0" width={board.raw_length_mm} height={board.raw_width_mm} className="fill-line-strong" />
          <rect x={board.margin_mm} y={board.margin_mm} width={board.usable_length_mm} height={board.usable_width_mm} className="fill-surface" />
          {board.offcuts.map((offcut) => (
            <rect
              key={`offcut-${offcut.seq}`}
              x={offcut.x_mm}
              y={offcut.y_mm}
              width={offcut.length_mm}
              height={offcut.width_mm}
              className="fill-none stroke-ink-3"
              strokeWidth={1.5}
              strokeDasharray="6 4"
              vectorEffect="non-scaling-stroke"
            >
              <title>{`Predicted offcut, ${mm(offcut.length_mm)} × ${mm(offcut.width_mm)} mm`}</title>
            </rect>
          ))}
          {board.placements.map((piece) => {
            const isActive = piece.seq === active;
            return (
              <svg key={piece.seq} x={piece.x_mm} y={piece.y_mm} width={piece.along_length_mm} height={piece.along_width_mm}>
                <g
                  tabIndex={0}
                  role="img"
                  aria-label={describePiece(piece)}
                  onFocus={() => setActive(piece.seq)}
                  onMouseEnter={() => setActive(piece.seq)}
                  className="cursor-default outline-hidden"
                >
                  <rect width="100%" height="100%" className={PIECE_FILLS[tintIndex(piece.line_no, lines)]} />
                  {piece.is_extra ? <rect width="100%" height="100%" fill={`url(#${hatchId})`} opacity="0.35" /> : null}
                  <rect
                    width="100%"
                    height="100%"
                    className={cx("fill-none", isActive ? "stroke-ink" : "stroke-ink-3")}
                    strokeWidth={isActive ? 3 : 1}
                    vectorEffect="non-scaling-stroke"
                  />
                  {piece.rotated ? <RotatedMark length={piece.along_length_mm} width={piece.along_width_mm} /> : null}
                  {pieceShowsLabel(piece) ? (
                    <text x="50%" y="50%" fontSize={LABEL_MM} textAnchor="middle" dominantBaseline="central" className="lk-mono fill-ink">
                      {piece.sku}
                    </text>
                  ) : null}
                </g>
              </svg>
            );
          })}
        </svg>
      </div>

      <figcaption className="flex min-w-0 flex-col gap-3">
        <p className="t-body-sm min-h-5 text-ink" aria-live="polite">
          {activePiece ? describePiece(activePiece) : <span className="text-ink-3">Point at a piece, or Tab to it, to read its size and position.</span>}
        </p>
        <ul className="t-caption flex min-w-0 flex-wrap gap-x-5 gap-y-2 text-ink-2" aria-label="Key to the drawing">
          {usedLines.map((lineNo) => (
            <LegendItem key={lineNo} swatch={<span className={cx("h-3.5 w-5 rounded-xs border border-line-strong", SWATCH_BG[tintIndex(lineNo, lines)])} />}>
              {skus.get(lineNo) ?? `Row ${lineNo}`}
            </LegendItem>
          ))}
          <LegendItem swatch={<span className="h-3.5 w-5 rounded-xs bg-line-strong" />}>Edge margin, trimmed</LegendItem>
          {board.offcuts.length > 0 ? <LegendItem swatch={<span className="h-3.5 w-5 rounded-xs border border-dashed border-ink-3" />}>Predicted offcut</LegendItem> : null}
          {hasRotated ? (
            <LegendItem
              swatch={
                <svg viewBox="0 0 20 14" className="h-3.5 w-5">
                  <rect x="0.5" y="0.5" width="19" height="13" className="fill-none stroke-ink-3" />
                  <line x1="14" y1="14" x2="20" y2="8" className="stroke-ink" strokeWidth="1.5" />
                </svg>
              }
            >
              Corner line: rotated 90°
            </LegendItem>
          ) : null}
          {hasExtra ? (
            <LegendItem
              swatch={
                <svg viewBox="0 0 20 14" className="h-3.5 w-5">
                  <rect x="0.5" y="0.5" width="19" height="13" className="fill-none stroke-ink-3" />
                  <path d="M2 14 L14 0 M8 14 L20 0 M-4 14 L8 0" className="stroke-ink-3" strokeWidth="1.5" />
                </svg>
              }
            >
              Hatched: extra piece
            </LegendItem>
          ) : null}
        </ul>
        <p className="t-caption text-ink-3">
          <Pct value={board.efficiency_pct} /> of this board is used
          {board.cut_count ? ` · ${board.cut_count} guillotine ${board.cut_count === 1 ? "cut" : "cuts"}` : ""}
          <span id={keysId}> · Tab moves between pieces, plus and minus zoom, 0 fits the board, the arrow keys scroll.</span>
        </p>
      </figcaption>
    </figure>
  );
}
