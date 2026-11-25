"use client";

import type { FormEvent } from "react";
import type { PlanDetail, PlanItem } from "@/features/cutting/types";
import { GRAIN_LABEL, MODE_LABEL, type PlanEditor } from "~/data/cutting";
import { Banner, Button, Code, DataTable, Dash, EmptyState, FormActions, GlassPanel, KeyValue, type Column } from "~/ui";
import { Measure, mm, Size } from "./parts";
import { BoardSection, NameSection, PiecesSection } from "./plan-form";

/**
 * The cut list and the board. An editable plan opens as the form (only what changed is saved, with
 * the expected version); a released or archived plan shows the same facts read-only.
 */
export function PiecesView({ plan, editor, editable }: { plan: PlanDetail; editor: PlanEditor; editable: boolean }) {
  if (!editable) return <ReadOnly plan={plan} />;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void editor.save();
  };

  const note = editor.offline
    ? "Offline. Changes save once the connection is back."
    : editor.dirty
      ? "Unsaved changes. Save them before you calculate."
      : plan.stale
        ? "Saved. Calculate again to update the layout."
        : "Everything is saved.";

  return (
    <form onSubmit={onSubmit} className="stack" noValidate>
      <NameSection editor={editor} />
      <PiecesSection editor={editor} />
      <BoardSection editor={editor} oversizeMm={plan.settings.oversize_mm} usable={{ length: plan.settings.usable_length_mm, width: plan.settings.usable_width_mm }} />
      <FormActions note={note}>
        {editor.dirty ? (
          <Button variant="ghost" onPress={editor.discard} isDisabled={editor.pending !== null}>
            Discard changes
          </Button>
        ) : null}
        <Button type="submit" variant={editor.dirty ? "primary" : "secondary"} loading={editor.pending === "save"} isDisabled={editor.offline || !editor.dirty}>
          Save changes
        </Button>
      </FormActions>
    </form>
  );
}

const ITEM_COLUMNS: Column<PlanItem>[] = [
  {
    key: "piece",
    header: "Piece",
    primary: true,
    cell: (item) => (
      <span className="flex min-w-0 items-start gap-3">
        <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{item.line_no}</span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{item.sku}</Code>
          {item.label ? <span className="t-caption truncate text-ink-3">{item.label}</span> : null}
        </span>
      </span>
    ),
  },
  { key: "decor", header: "Decor", cell: (item) => (item.decor ? item.decor : <Dash />) },
  { key: "thickness", header: "Thickness", numeric: true, cell: (item) => <Measure value={item.thickness_mm} unit="mm" /> },
  { key: "size", header: "Length × width", numeric: true, cell: (item) => <Size length={item.length_mm} width={item.width_mm} /> },
  { key: "quantity", header: "Quantity", numeric: true, cell: (item) => <span className="t-label lk-tnum text-ink">{item.quantity}</span> },
  { key: "grain", header: "Grain", hideOnMobile: true, cell: (item) => GRAIN_LABEL[item.grain_rule] ?? item.grain_rule },
];

function ReadOnly({ plan }: { plan: PlanDetail }) {
  const s = plan.settings;
  return (
    <div className="stack">
      <Banner tone="neutral" icon="lock" title="You can read this plan but not change it.">
        {plan.status === "archived"
          ? "It is archived."
          : plan.status === "released"
            ? "It is released for cutting, so the layout is fixed."
            : "Changing cut plans is not part of your role."}
        {plan.capabilities.duplicate?.allowed ? " Duplicate it to start a new draft from the same pieces." : ""}
      </Banner>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Pieces to cut</h2>
        <p className="t-body-sm text-ink-3">Length runs along the grain of the board.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Pieces of ${plan.plan_number}`}
          columns={ITEM_COLUMNS}
          rows={plan.items}
          rowKey={(item) => item.id ?? String(item.line_no)}
          empty={<EmptyState compact icon="shapes" title="No pieces on this plan" text="It was saved without a cut list." />}
        />
      </GlassPanel>
      <GlassPanel padding="md" className="rise" title="Board and machine" titleAs="h2">
        <KeyValue
          columns={2}
          items={[
            { label: "Board", value: <Size length={s.board_length_mm} width={s.board_width_mm} /> },
            { label: "Usable area", value: <Size length={s.usable_length_mm} width={s.usable_width_mm} /> },
            { label: "Edge margin", value: <Measure value={s.margin_mm} unit="mm" digits={1} /> },
            { label: "Cutting gap", value: <Measure value={s.gap_mm} unit="mm" digits={1} /> },
            { label: "Layout", value: MODE_LABEL[s.mode] ?? s.mode },
            { label: "Oversize boards", value: s.oversize_enabled ? `Yes, ${mm(s.oversize_mm)} mm each side` : "No" },
            { label: "Extra pieces", value: s.overproduction_enabled ? `Up to ${s.max_extra_qty} a row, ${mm(s.max_extra_pct)}% of required` : "No" },
          ]}
        />
      </GlassPanel>
    </div>
  );
}
