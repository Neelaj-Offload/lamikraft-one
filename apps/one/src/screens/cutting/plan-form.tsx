"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { isBlankRow } from "@/features/cutting/editor-model";
import { GRAIN_RULES, MODES, type GrainRule, type Mode } from "@/features/cutting/types";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format/time";
import { useSession } from "@/lib/session/context";
import { GRAIN_LABEL, MODE_LABEL, useCuttingProductSearch, type EditorRow, type PlanEditor } from "~/data/cutting";
import { Banner, Button, ComboBox, DecimalField, FormSection, IconButton, Select, Switch, TextField } from "~/ui";
import { mm, stagger } from "./parts";

/*
 * The parts of the cut plan form, shared by "New cut plan" and the Pieces view of a saved plan:
 * the name, the cut list (one row per piece, filled from the catalogue or typed) and the board
 * settings. State, checks and saving live in `usePlanEditor`.
 */

/** One grid for the column headings and every row, from 1280px; below that each piece is a card. */
const ROW_GRID =
  "xl:grid-cols-[1.75rem_minmax(0,2.2fr)_minmax(0,1fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_minmax(0,0.7fr)_minmax(0,1.4fr)_2.5rem]";

const HEADINGS = ["SKU or part", "Decor", "Thickness, mm", "Length, mm", "Width, mm", "Quantity", "Grain"] as const;

/** A 409 on save or calculate: someone else changed the plan. Take theirs, or keep mine and save over it. */
export function ConflictBanner({ editor }: { editor: PlanEditor }) {
  const { zone } = useSession();
  const [busy, setBusy] = useState<"theirs" | "mine" | null>(null);
  const conflict = editor.conflict;
  if (!conflict) return null;
  const who = conflict.changedBy ? `${conflict.changedBy} saved` : "Someone else saved";
  const when = conflict.changedAt ? ` on ${formatDate(conflict.changedAt, zone)}` : "";
  const settle = async (which: "theirs" | "mine") => {
    setBusy(which);
    try {
      await (which === "theirs" ? editor.loadTheirs() : editor.keepMine());
    } finally {
      setBusy(null);
    }
  };
  return (
    <Banner
      tone="amber"
      title={`${who} this plan${when} while you were editing.`}
      action={
        <span className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" loading={busy === "theirs"} isDisabled={busy !== null} onPress={() => void settle("theirs")}>
            Load their version
          </Button>
          <Button variant="inverse" size="sm" loading={busy === "mine"} isDisabled={busy !== null} onPress={() => void settle("mine")}>
            Keep my changes
          </Button>
        </span>
      }
    >
      Load their version to drop your edits, or keep yours and save again to replace theirs.
    </Banner>
  );
}

export function NameSection({ editor }: { editor: PlanEditor }) {
  return (
    <FormSection title="What is it for?" description="A name the shop floor will recognise: the order, the customer or the job.">
      <TextField
        className="col-span-full"
        label="Plan name"
        placeholder="Kitchen & Co. order, 18 mm oak"
        value={editor.form.name}
        onChange={editor.setName}
        maxLength={200}
        isRequired
        error={editor.errors.name}
      />
    </FormSection>
  );
}

function ProductPicker({ onPick }: { onPick: PlanEditor["pickProduct"] }) {
  const [text, setText] = useState("");
  const { allowed, products, isSearching } = useCuttingProductSearch(text);
  if (!allowed) return null;
  return (
    <ComboBox
      className="col-span-full md:max-w-xl"
      label="Add from the catalogue"
      placeholder="Type two letters of a product or SKU"
      help="Fills the decor, thickness and size the catalogue knows. You set the quantity."
      items={products.map((product) => ({
        id: product.product_id,
        label: product.product_name,
        description: [product.product_key, product.decor, product.thickness_mm ? `${mm(product.thickness_mm)} mm` : null, product.grain_locked ? "grain-locked decor" : null]
          .filter(Boolean)
          .join(" · "),
      }))}
      inputValue={text}
      onInputChange={setText}
      selectedKey={null}
      onSelectionChange={(id) => {
        const chosen = products.find((product) => product.product_id === id);
        if (chosen) {
          onPick(chosen);
          setText("");
        }
      }}
      isLoading={isSearching}
      emptyText={text.trim().length < 2 ? "Type at least two letters" : "No product matches. Type the piece into a row instead."}
    />
  );
}

/** The cut list: catalogue search, then one row per piece. Enter moves down a row and adds one after the last. */
export function PiecesSection({ editor }: { editor: PlanEditor }) {
  const firstInputs = useRef(new Map<string, HTMLInputElement>());
  const rows = editor.form.rows;
  const rowErrorCount = Object.keys(editor.errors.rows).length;

  const focusRow = (key: string) => requestAnimationFrame(() => firstInputs.current.get(key)?.focus());
  const addRow = () => focusRow(editor.addRow());

  // Capture phase: the number fields handle Enter themselves and stop it from bubbling.
  const onRowKeyDown = (event: KeyboardEvent<HTMLDivElement>, row: EditorRow, index: number) => {
    if (event.key !== "Enter" || (event.target as HTMLElement).tagName !== "INPUT") return;
    event.preventDefault();
    const next = rows[index + 1];
    if (next) firstInputs.current.get(next.key)?.focus();
    else if (!isBlankRow(row)) addRow();
  };

  return (
    <FormSection title="Pieces to cut" description="One row per piece size. Pick from the catalogue or type the piece yourself. Enter on the last row adds another.">
      <ProductPicker onPick={editor.pickProduct} />

      {editor.errors.general.length > 0 ? (
        <Banner tone="ember" title="The cut list was not accepted." className="col-span-full">
          {editor.errors.general.join(" ")}
        </Banner>
      ) : rowErrorCount > 0 ? (
        <Banner tone="ember" title={rowErrorCount === 1 ? "One row needs attention." : `${rowErrorCount} rows need attention.`} className="col-span-full">
          Each is marked below with what to fix.
        </Banner>
      ) : null}

      <div className="col-span-full flex min-w-0 flex-col gap-3 xl:gap-2">
        <div aria-hidden="true" className={cx("t-overline hidden gap-2 px-0 text-ink-3 xl:grid", ROW_GRID)}>
          <span className="text-right">#</span>
          {HEADINGS.map((heading) => (
            <span key={heading}>{heading}</span>
          ))}
          <span />
        </div>

        {rows.map((row, index) => {
          const errors = editor.errors.rows[row.key] ?? {};
          const n = index + 1;
          return (
            <div
              key={row.key}
              role="group"
              aria-label={`Piece ${n}`}
              onKeyDownCapture={(event) => onRowKeyDown(event, row, index)}
              className={cx(
                "rise-plain grid min-w-0 grid-cols-2 items-start gap-3 rounded-md border border-line bg-surface p-4",
                "xl:gap-2 xl:rounded-none xl:border-0 xl:bg-transparent xl:p-0 xl:[&_.lk-field-label]:sr-only",
                ROW_GRID,
              )}
              style={stagger(index)}
            >
              <span className="t-label lk-tnum self-center text-ink xl:mt-2.5 xl:self-start xl:text-right xl:text-ink-3">
                <span className="xl:hidden">Piece </span>
                {n}
              </span>
              <TextField
                className="col-span-2 xl:col-span-1"
                label="SKU or part"
                value={row.sku}
                onChange={(value) => editor.setRow(row.key, { sku: value, product_id: null })}
                maxLength={120}
                error={errors.sku}
                ref={(element) => {
                  if (element) firstInputs.current.set(row.key, element);
                  else firstInputs.current.delete(row.key);
                }}
              />
              <TextField label="Decor" value={row.decor} onChange={(value) => editor.setRow(row.key, { decor: value })} maxLength={80} error={errors.decor} />
              <DecimalField
                label="Thickness, mm"
                value={row.thickness_mm ?? ""}
                onChange={(value) => editor.setRow(row.key, { thickness_mm: value || null })}
                maxFractionDigits={3}
                error={errors.thickness_mm}
              />
              <DecimalField
                label="Length, mm"
                value={row.length_mm ?? ""}
                onChange={(value) => editor.setRow(row.key, { length_mm: value || null })}
                maxFractionDigits={1}
                error={errors.length_mm}
              />
              <DecimalField
                label="Width, mm"
                value={row.width_mm ?? ""}
                onChange={(value) => editor.setRow(row.key, { width_mm: value || null })}
                maxFractionDigits={1}
                error={errors.width_mm}
              />
              <DecimalField
                label="Quantity"
                value={row.quantity ?? ""}
                onChange={(value) => editor.setRow(row.key, { quantity: value || null })}
                maxFractionDigits={0}
                error={errors.quantity}
              />
              <Select
                label="Grain"
                options={GRAIN_RULES.map((rule) => ({ value: rule, label: GRAIN_LABEL[rule] ?? rule }))}
                value={row.grain_rule}
                onChange={(value) => editor.setRow(row.key, { grain_rule: (GRAIN_RULES.find((rule) => rule === value) ?? "inherit") as GrainRule })}
                error={errors.grain_rule}
              />
              <IconButton
                icon="trash"
                label={`Remove piece ${n}`}
                variant="ghost"
                className="col-start-2 row-start-1 justify-self-end xl:col-start-auto xl:row-start-auto"
                onPress={() => editor.removeRow(row.key)}
              />
            </div>
          );
        })}

        <div>
          <Button variant="secondary" size="sm" iconLeft="plus" onPress={addRow}>
            Add a row
          </Button>
        </div>
      </div>
    </FormSection>
  );
}

/** The sheet the pieces are cut from and how the machine works it. */
export function BoardSection({ editor, oversizeMm, usable }: { editor: PlanEditor; oversizeMm: string; usable?: { length: string; width: string } | null }) {
  const s = editor.form.settings;
  const errors = editor.errors.settings;
  return (
    <FormSection
      title="Board and machine"
      description={
        usable
          ? `The sheet you cut from. As saved, the usable area is ${mm(usable.length)} × ${mm(usable.width)} mm once the edge margin is trimmed.`
          : "The sheet you cut from. The company's standard board is filled in; change it only when this job uses another."
      }
    >
      <DecimalField label="Board length" suffix="mm" value={s.board_length_mm ?? ""} onChange={(value) => editor.setSetting("board_length_mm", value || null)} maxFractionDigits={1} isRequired error={errors.board_length_mm} />
      <DecimalField label="Board width" suffix="mm" value={s.board_width_mm ?? ""} onChange={(value) => editor.setSetting("board_width_mm", value || null)} maxFractionDigits={1} isRequired error={errors.board_width_mm} />
      <DecimalField
        label="Edge margin"
        suffix="mm"
        value={s.margin_mm ?? ""}
        onChange={(value) => editor.setSetting("margin_mm", value || null)}
        maxFractionDigits={1}
        isRequired
        error={errors.margin_mm}
        help="Trimmed off every side of the board."
      />
      <DecimalField
        label="Cutting gap"
        suffix="mm"
        value={s.gap_mm ?? ""}
        onChange={(value) => editor.setSetting("gap_mm", value || null)}
        maxFractionDigits={1}
        isRequired
        error={errors.gap_mm}
        help="Left between pieces for the blade or the tool."
      />
      <Select
        className="col-span-full md:max-w-md"
        label="Layout"
        options={MODES.map((mode) => ({ value: mode, label: MODE_LABEL[mode] ?? mode }))}
        value={s.mode}
        onChange={(value) => editor.setSetting("mode", (MODES.find((mode) => mode === value) ?? "nested") as Mode)}
        error={errors.mode}
      />
      <Switch
        className="col-span-full"
        label={`Boards are ${mm(oversizeMm)} mm oversize on each side`}
        description="A plan that counts on oversize boards must have its boards measured before it is released."
        isSelected={s.oversize_enabled}
        onChange={(value) => editor.setSetting("oversize_enabled", value)}
      />
      <Switch
        className="col-span-full"
        label="Fill open boards with extra pieces"
        description="Extra pieces only go on boards that are already needed. No board is added for them."
        isSelected={s.overproduction_enabled}
        onChange={(value) => editor.setSetting("overproduction_enabled", value)}
      />
      {s.overproduction_enabled ? (
        <>
          <DecimalField
            label="Most extra pieces per row"
            value={s.max_extra_qty ?? ""}
            onChange={(value) => editor.setSetting("max_extra_qty", value || null)}
            maxFractionDigits={0}
            error={errors.max_extra_qty}
          />
          <DecimalField
            label="Most extra pieces, share of required"
            suffix="%"
            value={s.max_extra_pct ?? ""}
            onChange={(value) => editor.setSetting("max_extra_pct", value || null)}
            maxFractionDigits={2}
            error={errors.max_extra_pct}
          />
        </>
      ) : null}
    </FormSection>
  );
}
