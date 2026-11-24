"use client";

import { useId, useState } from "react";
import type { Board, Calculation, Group, ItemResult, PlanDetail, Placement } from "@/features/cutting/types";
import { formatCount } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { GROUP_WARNING, isCalculating, MODE_LABEL, UNFIT_LABEL, type PlanEditor } from "~/data/cutting";
import { Badge, Banner, Button, Chip, ChipGroup, Code, DataTable, DateText, EmptyState, GlassPanel, Icon, type Column } from "~/ui";
import { BoardDrawing } from "./board-drawing";
import { Figure, Measure, mm, Pct, Size, stagger } from "./parts";

/**
 * The stored latest layout: the plan's totals, then one panel per decor and thickness with its
 * pieces, its figures and every board drawn to scale.
 */
export function LayoutView({ plan, canCalculate, editor }: { plan: PlanDetail; canCalculate: boolean; editor: PlanEditor }) {
  const calc = plan.latest_calculation;
  if (!calc) {
    const busy = isCalculating(plan);
    return (
      <GlassPanel padding="lg" className="rise">
        <EmptyState
          icon="grid"
          title={busy ? "The layout is on its way" : "No layout yet"}
          text={
            busy
              ? "The pieces are being laid out in the background. This view fills in when it is ready."
              : plan.items.length === 0
                ? "Add the pieces to cut, save, then calculate. Every board appears here, drawn to scale."
                : "Calculate to lay the pieces out on boards. Every board appears here, drawn to scale."
          }
          actions={
            canCalculate && !busy && plan.items.length > 0 ? (
              <Button
                variant="inverse"
                iconLeft="calculator"
                loading={editor.pending === "calculate"}
                isDisabled={editor.offline || editor.dirty || editor.pending !== null}
                onPress={() => void editor.calculate()}
              >
                Calculate layout
              </Button>
            ) : undefined
          }
        />
      </GlassPanel>
    );
  }
  return <Results calc={calc} stale={plan.stale} />;
}

function Results({ calc, stale }: { calc: Calculation; stale: boolean }) {
  const { locale } = useZone();
  const t = calc.totals;
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3">{calc.groups.length === 1 ? "One decor and thickness" : `${calc.groups.length} decors and thicknesses`}</h2>
          <p className="t-body-sm text-ink-3">
            {calc.calc_no ? `Calculation ${calc.calc_no}` : "Latest calculation"}
            {calc.created_at ? (
              <>
                {", "}
                <DateText value={calc.created_at} style="dayTime" />
              </>
            ) : null}
            {calc.created_by?.display_name ? ` by ${calc.created_by.display_name}` : ""}. A heuristic layout: good, not guaranteed to be the best possible.
          </p>
        </div>
      </div>

      {stale ? (
        <Banner tone="amber" icon="refresh" title="This layout is out of date.">
          The pieces, the board or the offcut choice changed after it was calculated. Calculate again to update it.
        </Banner>
      ) : null}

      <GlassPanel padding="md" className="rise" style={stagger(1)}>
        <dl className="grid min-w-0 grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 xl:grid-cols-7">
          <Figure label="Boards" foot={`at least ${formatCount(t.lower_bound_boards, locale)} by area`}>
            {formatCount(t.boards, locale)}
          </Figure>
          {t.offcut_boards > 0 ? (
            <Figure label="From offcuts" foot={`${formatCount(t.boards - t.offcut_boards, locale)} standard ${t.boards - t.offcut_boards === 1 ? "sheet" : "sheets"}`}>
              {formatCount(t.offcut_boards, locale)}
            </Figure>
          ) : null}
          <Figure label="Pieces placed">
            {formatCount(t.placed_required, locale)} <span className="text-ink-3">of {formatCount(t.required, locale)}</span>
          </Figure>
          <Figure label="Extra pieces">{formatCount(t.extra, locale)}</Figure>
          <Figure label="Did not fit">
            <span className={t.unfit > 0 ? "text-ember-text" : undefined}>{formatCount(t.unfit, locale)}</span>
          </Figure>
          <Figure label="Board used">
            <Pct value={t.efficiency_usable_pct} />
          </Figure>
          <Figure label="Scrap" foot={<Measure value={t.scrap_area_m2} unit="m²" />}>
            <Pct value={t.scrap_pct} />
          </Figure>
        </dl>
      </GlassPanel>

      {calc.groups.map((group, index) => (
        <GroupPanel key={group.group_no} group={group} index={index} locked={!group.decor_key || calc.grain_locked_decors.includes(group.decor_key)} />
      ))}
    </div>
  );
}

function itemColumns(): Column<ItemResult>[] {
  return [
    {
      key: "piece",
      header: "Piece",
      primary: true,
      cell: (item) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{item.sku}</Code>
          <span className="t-caption text-ink-3">
            <Size length={item.length_mm} width={item.width_mm} /> · {item.rotation_allowed ? "may rotate" : "never rotated"}
          </span>
        </span>
      ),
    },
    { key: "required", header: "Required", numeric: true, cell: (item) => item.required },
    { key: "placed", header: "Placed", numeric: true, cell: (item) => item.placed_required },
    { key: "extra", header: "Extra", numeric: true, hideOnMobile: true, cell: (item) => item.extra },
    { key: "produced", header: "Produced", numeric: true, cell: (item) => <span className="t-label text-ink">{item.produced}</span> },
    {
      key: "unfit",
      header: "Did not fit",
      numeric: true,
      cell: (item) =>
        item.unfit > 0 ? (
          <span className="flex flex-col items-end gap-0.5 text-ember-text">
            <span className="t-label">{item.unfit}</span>
            {item.unfit_reason ? <span className="t-caption">{UNFIT_LABEL[item.unfit_reason] ?? item.unfit_reason}</span> : null}
          </span>
        ) : (
          <span className="text-ink-3">0</span>
        ),
    },
  ];
}

function GroupPanel({ group, index, locked }: { group: Group; index: number; locked: boolean }) {
  const { locale } = useZone();
  const [boardIndex, setBoardIndex] = useState(group.boards[0]?.index ?? 0);
  const board = group.boards.find((candidate) => candidate.index === boardIndex) ?? group.boards[0] ?? null;
  const lines = group.items.map((item) => item.line_no);
  const skus = new Map(group.items.map((item) => [item.line_no, item.sku] as const));
  const placed = group.items.reduce((sum, item) => sum + item.placed_required, 0);
  const required = group.items.reduce((sum, item) => sum + item.required, 0);
  const unfit = group.items.reduce((sum, item) => sum + item.unfit, 0);
  const title = `${group.decor_key ? `Decor ${group.decor_key}` : "No decor"}, ${mm(group.thickness_mm)} mm`;

  return (
    <GlassPanel
      as="section"
      padding="lg"
      className="rise flex min-w-0 flex-col gap-6"
      style={stagger(index + 2)}
      eyebrow={MODE_LABEL[group.mode] ?? group.mode}
      title={title}
      titleAs="h2"
      action={
        locked ? (
          <Badge tone="amber" icon="lock">
            Grain-locked
          </Badge>
        ) : undefined
      }
    >
      <dl className="grid min-w-0 grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
        <Figure label="Boards" foot={`at least ${formatCount(group.lower_bound_boards, locale)} by area`}>
          {formatCount(group.board_count, locale)}
        </Figure>
        <Figure label="Pieces placed">
          {formatCount(placed, locale)} <span className="text-ink-3">of {formatCount(required, locale)}</span>
        </Figure>
        <Figure label="Board used">
          <Pct value={group.efficiency_usable_pct} />
        </Figure>
        <Figure label="Scrap">
          <Pct value={group.scrap_pct} />
        </Figure>
        <Figure label="Area used">
          <Measure value={group.placed_area_m2} unit="m²" />
        </Figure>
        <Figure label="Did not fit">
          <span className={unfit > 0 ? "text-ember-text" : undefined}>{formatCount(unfit, locale)}</span>
        </Figure>
      </dl>

      {group.warnings.length > 0 ? (
        <Banner tone="amber" title="Worth knowing">
          {group.warnings.map((warning) => GROUP_WARNING[warning] ?? warning).join(" ")}
        </Banner>
      ) : null}

      <div className="min-w-0 overflow-hidden rounded-md border border-line">
        <DataTable label={`Pieces for ${title}`} columns={itemColumns()} rows={group.items} rowKey={(item) => String(item.line_no)} dense />
      </div>

      {board ? (
        <div className="flex min-w-0 flex-col gap-4">
          {group.boards.length > 1 ? (
            <ChipGroup label={`Boards for ${title}`}>
              {group.boards.map((candidate) => (
                <Chip key={candidate.index} selected={candidate.index === board.index} onChange={() => setBoardIndex(candidate.index)} icon={candidate.source === "offcut" ? "layers" : undefined}>
                  Board {candidate.index}
                  {candidate.source === "offcut" && candidate.lot_code ? ` · ${candidate.lot_code}` : ""}
                </Chip>
              ))}
            </ChipGroup>
          ) : null}
          <BoardPanel key={board.index} board={board} lines={lines} skus={skus} />
        </div>
      ) : null}
    </GlassPanel>
  );
}

const PLACEMENT_COLUMNS: Column<Placement>[] = [
  {
    key: "piece",
    header: "Piece",
    primary: true,
    cell: (piece) => (
      <span className="flex min-w-0 items-baseline gap-3">
        <span className="t-caption lk-tnum w-6 flex-none text-right text-ink-3">{piece.seq}</span>
        <Code>{piece.sku}</Code>
      </span>
    ),
  },
  { key: "position", header: "From the corner", numeric: true, cell: (piece) => <span className="lk-tnum whitespace-nowrap">{`${mm(piece.x_mm)}, ${mm(piece.y_mm)} mm`}</span> },
  { key: "size", header: "Along length × width", numeric: true, cell: (piece) => <Size length={piece.along_length_mm} width={piece.along_width_mm} /> },
  {
    key: "notes",
    header: "Notes",
    cell: (piece) =>
      piece.rotated || piece.is_extra ? (
        <span className="flex flex-wrap gap-1.5">
          {piece.rotated ? (
            <Badge size="sm" icon="refresh">
              Rotated 90°
            </Badge>
          ) : null}
          {piece.is_extra ? (
            <Badge size="sm" tone="cobalt">
              Extra
            </Badge>
          ) : null}
        </span>
      ) : (
        <span className="text-ink-3">None</span>
      ),
  },
];

function BoardPanel({ board, lines, skus }: { board: Board; lines: readonly number[]; skus: ReadonlyMap<number, string> }) {
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
        <h3 className="t-h4 text-ink">
          Board {board.index}
          <span className="t-body-sm ml-2 text-ink-3">
            <Size length={board.raw_length_mm} width={board.raw_width_mm} />
          </span>
        </h3>
        {board.source === "offcut" ? (
          <span className="t-body-sm text-ink-2">
            Cut from offcut {board.lot_code ? <Code>{board.lot_code}</Code> : "lot"}, with no edge margin (its edges are measured).
          </span>
        ) : null}
      </div>

      <BoardDrawing board={board} lines={lines} skus={skus} />

      <div className="flex min-w-0 flex-col gap-2">
        <h4 className="t-label text-ink">Predicted offcuts</h4>
        {board.offcuts.length > 0 ? (
          <ul className="t-body-sm flex flex-wrap gap-x-5 gap-y-1 text-ink-2">
            {board.offcuts.map((offcut) => (
              <li key={offcut.seq} className="flex items-center gap-1.5">
                <Icon name="layers" size={14} className="text-ink-3" />
                <Size length={offcut.length_mm} width={offcut.width_mm} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="t-body-sm text-ink-3">None of at least 300 × 300 mm.</p>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-3">
        <div>
          <Button variant="ghost" size="sm" iconRight={showTable ? "chevronUp" : "chevronDown"} aria-expanded={showTable} aria-controls={tableId} onPress={() => setShowTable((open) => !open)}>
            {showTable ? "Hide the placement table" : `Show the placement table (${board.placements.length})`}
          </Button>
        </div>
        <div id={tableId} hidden={!showTable} className="min-w-0 overflow-hidden rounded-md border border-line">
          {showTable ? <DataTable label={`Pieces on board ${board.index}`} columns={PLACEMENT_COLUMNS} rows={board.placements} rowKey={(piece) => String(piece.seq)} dense /> : null}
        </div>
      </div>
    </div>
  );
}
