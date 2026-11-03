"use client";

import { useId, useState } from "react";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { cx } from "@/lib/cx";
import { BoardCanvas } from "./board-canvas";
import { cuttingMessages as m } from "./messages";
import type { Board, Calculation, Group, ItemResult, Placement } from "./types";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string | null }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border bg-surface px-3 py-2">
      <dt className="text-xs font-semibold tracking-wide text-ink-muted uppercase">{label}</dt>
      <dd className="tabular text-lg font-bold text-ink">{value}</dd>
      {hint ? <dd className="text-xs text-ink-muted">{hint}</dd> : null}
    </div>
  );
}

function itemColumns(): DataTableColumn<ItemResult>[] {
  return [
    { id: "sku", header: m.results.columns.sku, isRowHeader: true, mobile: "title", cell: (i) => i.sku },
    {
      id: "size",
      header: m.results.columns.size,
      mobile: "key",
      cell: (i) => (
        <span>
          {i.length_mm} × {i.width_mm}
          <span className="text-ink-muted"> · {i.rotation_allowed ? m.results.rotates : m.results.noRotation}</span>
        </span>
      ),
    },
    { id: "required", header: m.results.columns.required, numeric: true, cell: (i) => i.required },
    { id: "placed", header: m.results.columns.placed, numeric: true, cell: (i) => i.placed_required },
    { id: "extra", header: m.results.columns.extra, numeric: true, cell: (i) => i.extra },
    { id: "produced", header: m.results.columns.produced, numeric: true, mobile: "amount", cell: (i) => i.produced },
    {
      id: "unfit",
      header: m.results.columns.unfit,
      numeric: true,
      mobile: "status",
      cell: (i) =>
        i.unfit ? (
          <span className="text-danger">
            {i.unfit}
            {i.unfit_reason ? <span className="block text-xs">{m.unfit[i.unfit_reason] ?? i.unfit_reason}</span> : null}
          </span>
        ) : (
          0
        ),
    },
  ];
}

function placementColumns(): DataTableColumn<Placement>[] {
  return [
    { id: "seq", header: m.canvas.columns.seq, numeric: true, cell: (p) => p.seq },
    { id: "sku", header: m.canvas.columns.sku, isRowHeader: true, mobile: "title", cell: (p) => p.sku },
    { id: "x", header: m.canvas.columns.x, numeric: true, cell: (p) => p.x_mm },
    { id: "y", header: m.canvas.columns.y, numeric: true, cell: (p) => p.y_mm },
    { id: "length", header: m.canvas.columns.length, numeric: true, mobile: "key", cell: (p) => p.along_length_mm },
    { id: "width", header: m.canvas.columns.width, numeric: true, cell: (p) => p.along_width_mm },
    { id: "rotated", header: m.canvas.columns.rotated, mobile: "meta", cell: (p) => (p.rotated ? m.canvas.yes : "") },
    { id: "extra", header: m.canvas.columns.extra, cell: (p) => (p.is_extra ? m.canvas.yes : "") },
  ];
}

function BoardView({ board, lines }: { board: Board; lines: readonly number[] }) {
  const tableId = useId();
  return (
    <div className="flex flex-col gap-4">
      <BoardCanvas board={board} lines={lines} />
      <details className="rounded-md border bg-surface px-3 py-2">
        <summary className="cursor-pointer rounded-xs py-1 font-semibold text-ink focus-visible:focus-ring" id={tableId}>
          {m.canvas.table} ({board.placements.length})
        </summary>
        <div className="pt-3">
          <DataTable
            caption={m.canvas.tableCaption(board.index)}
            columns={placementColumns()}
            rows={board.placements}
            rowId={(p) => String(p.seq)}
          />
        </div>
      </details>
      <div className="flex flex-col gap-1 text-sm">
        <h4 className="font-semibold text-ink">{m.canvas.offcuts}</h4>
        {board.offcuts.length ? (
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-ink">
            {board.offcuts.map((o) => (
              <li key={o.seq} className="tabular">
                {m.canvas.offcut(o.length_mm, o.width_mm)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-muted">{m.canvas.noOffcuts}</p>
        )}
      </div>
    </div>
  );
}

function GroupView({ group, locked }: { group: Group; locked: boolean }) {
  const { locale } = useZone();
  const headingId = useId();
  const [boardIndex, setBoardIndex] = useState(group.boards[0]?.index ?? 0);
  const board = group.boards.find((b) => b.index === boardIndex) ?? group.boards[0] ?? null;
  const lines = group.items.map((i) => i.line_no);
  const pct = (v: string) => `${formatDecimal(v, { locale, maxFractionDigits: 2 }) ?? v} %`;
  const placed = group.items.reduce((sum, i) => sum + i.placed_required, 0);
  const required = group.items.reduce((sum, i) => sum + i.required, 0);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 rounded-lg border bg-canvas p-4 md:p-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 id={headingId} className="text-lg font-[650] text-ink">
          {m.results.group(group.decor_key, group.thickness_mm)}
        </h3>
        <span className="text-sm text-ink-muted">{m.modes[group.mode]}</span>
        {locked ? <span className="text-sm font-semibold text-warning-text">{m.results.lockedDecor}</span> : null}
      </header>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label={m.results.boards} value={formatCount(group.board_count, locale)} hint={m.results.lowerBound(group.lower_bound_boards)} />
        <Metric label={m.results.placed} value={`${formatCount(placed, locale)} / ${formatCount(required, locale)}`} />
        <Metric label={m.results.efficiency} value={pct(group.efficiency_usable_pct)} />
        <Metric label={m.results.scrap} value={pct(group.scrap_pct)} />
        <Metric label={m.results.usedArea} value={`${formatDecimal(group.placed_area_m2, { locale, maxFractionDigits: 3 })} m²`} />
        <Metric label={m.results.unfit} value={formatCount(group.items.reduce((sum, i) => sum + i.unfit, 0), locale)} />
      </dl>
      {group.warnings.length ? (
        <ul className="flex flex-col gap-1 rounded-md border border-warning-text/40 bg-warning-bg px-3 py-2 text-sm text-ink" role="note">
          {group.warnings.map((w) => (
            <li key={w}>{m.warnings[w] ?? w}</li>
          ))}
        </ul>
      ) : null}
      <DataTable caption={m.results.itemsCaption(group.decor_key)} columns={itemColumns()} rows={group.items} rowId={(i) => String(i.line_no)} />
      {group.boards.length ? (
        <div className="flex flex-col gap-3">
          <div role="radiogroup" aria-label={m.results.boardPicker} className="flex flex-wrap gap-1.5">
            {group.boards.map((b) => (
              <button
                key={b.index}
                type="button"
                role="radio"
                aria-checked={b.index === board?.index}
                onClick={() => setBoardIndex(b.index)}
                className={cx(
                  "tabular rounded-md border px-2.5 py-1 text-sm outline-hidden focus-visible:focus-ring",
                  b.index === board?.index ? "border-forest bg-forest-tint font-semibold text-ink" : "bg-surface text-ink-muted hover:text-ink",
                )}
              >
                {m.results.boardsOf(b.index)}
              </button>
            ))}
          </div>
          {board ? <BoardView key={board.index} board={board} lines={lines} /> : null}
        </div>
      ) : null}
    </section>
  );
}

/** The stored calculation: totals, then per decor and thickness the pieces, metrics and boards. */
export function Results({ calc }: { calc: Calculation }) {
  const { locale } = useZone();
  const headingId = useId();
  const t = calc.totals;
  const pct = (v: string) => `${formatDecimal(v, { locale, maxFractionDigits: 2 }) ?? v} %`;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id={headingId} className="text-xl font-[650] text-ink">
          {m.results.title}
        </h2>
        {calc.calc_no ? <span className="text-sm text-ink-muted">{m.results.calcNo(calc.calc_no)}</span> : null}
        {calc.created_at ? <LocalDateTime value={calc.created_at} className="text-sm text-ink-muted" /> : null}
        <span className="text-sm text-ink-muted">{m.results.heuristic}</span>
      </header>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label={m.results.boards} value={formatCount(t.boards, locale)} hint={m.results.lowerBound(t.lower_bound_boards)} />
        <Metric label={m.results.placed} value={`${formatCount(t.placed_required, locale)} / ${formatCount(t.required, locale)}`} />
        <Metric label={m.results.extra} value={formatCount(t.extra, locale)} />
        <Metric label={m.results.unfit} value={formatCount(t.unfit, locale)} />
        <Metric label={m.results.efficiency} value={pct(t.efficiency_usable_pct)} />
        <Metric label={m.results.scrap} value={pct(t.scrap_pct)} hint={`${formatDecimal(t.scrap_area_m2, { locale, maxFractionDigits: 3 })} m²`} />
      </dl>
      {calc.groups.map((group) => (
        <GroupView key={group.group_no} group={group} locked={!group.decor_key || calc.grain_locked_decors.includes(group.decor_key)} />
      ))}
    </section>
  );
}
