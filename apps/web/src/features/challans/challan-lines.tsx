"use client";

import { useId, useState } from "react";
import { Input, Label, TextField as RacTextField } from "react-aria-components";
import { Button, IconButton, unavailableWhen } from "@/components/ui/button";
import { Quantity } from "@/components/ui/format";
import { CloseIcon } from "@/components/ui/icons";
import { descriptionClasses, fieldErrorClasses, inputClasses, labelClasses } from "@/components/ui/styles";
import { cx } from "@/lib/cx";
import { challansMessages as m } from "@/messages/challans";
import { removeChallanLine, updateChallanLine } from "./api";
import { QuantityList } from "./challan-bits";
import { AddLine } from "./challan-add-line";
import type { SaveState } from "./line-save";
import type { ChallanDetail, ChallanLine } from "./types";
import type { ChallanCommands } from "./use-challan-command";
import { saveFailureText, useQuantitySaver } from "./use-line-saver";

const s = m.workspace.save;

/** The lines: read-only once issued; on a draft, quantities autosave (600 ms debounce) and failures stay inline. */
export function ChallanLines({ challan, editable, commands }: { challan: ChallanDetail; editable: boolean; commands: ChallanCommands }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={titleId} className="text-lg font-[650] text-ink">
          {m.workspace.lines}
        </h2>
        <p className="text-sm text-ink-muted">
          {m.workspace.totalQuantity}: <QuantityList value={challan.quantity_by_unit} />
        </p>
      </div>
      {challan.lines.length === 0 ? (
        <p className="text-ink-muted">{m.workspace.noLines}</p>
      ) : (
        <>
          {editable ? <p className="text-sm text-ink-muted">{m.workspace.lineHint}</p> : null}
          <ol className="flex flex-col divide-y border-y" aria-label={m.workspace.linesCaption(challan.challan_number)}>
            {challan.lines.map((line) => (
              <LineRow key={line.id} challan={challan} line={line} editable={editable} commands={commands} />
            ))}
          </ol>
        </>
      )}
      {editable ? <AddLine challan={challan} commands={commands} /> : null}
    </section>
  );
}

function SaveStatus({ state, onRetry }: { state: SaveState<string>; onRetry: () => void }) {
  if (state.status === "idle") return null;
  if (state.status === "failed" || state.status === "invalid") {
    return (
      <span className="flex flex-wrap items-center gap-2" data-save="failed">
        <span className={fieldErrorClasses}>
          {s.failed}: {state.status === "failed" ? saveFailureText(state.error) : state.reason}
        </span>
        {state.status === "failed" ? (
          <Button size="sm" onPress={onRetry}>
            {s.retry}
          </Button>
        ) : null}
      </span>
    );
  }
  const text = state.status === "pending" ? s.pending : state.status === "saving" ? s.saving : s.saved;
  return (
    <span className={descriptionClasses} data-save={state.status}>
      {text}
    </span>
  );
}

function LineRow({ challan, line, editable, commands }: { challan: ChallanDetail; line: ChallanLine; editable: boolean; commands: ChallanCommands }) {
  const [text, setText] = useState(line.quantity);
  const saver = useQuantitySaver(async (quantity) => {
    const outcome = await commands.run(
      "update_line",
      [line.id, quantity],
      (key, current) => updateChallanLine(current, line.id, { quantity }, key),
      { failed: null },
    );
    if (!outcome.ok) throw outcome.error;
  });
  const name = [line.item_code, line.item_name].filter(Boolean).join(" · ");
  const isReturn = Boolean(line.original_line_id);
  const state = saver.state;
  const invalid = state.status === "failed" || state.status === "invalid";

  const remove = () =>
    void commands.run("remove_line", [line.id], (key, current) => removeChallanLine(current, line.id, key), {
      done: m.workspace.removed,
      failed: m.workspace.failed(m.workspace.remove(name)),
    });

  return (
    <li className="flex flex-col gap-3 py-4" data-line={line.line_no}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="font-semibold text-ink [overflow-wrap:anywhere]">
            <span className="text-ink-muted tabular">{line.line_no}. </span>
            {line.item_name}
          </p>
          <p className="flex flex-wrap gap-x-3 text-sm text-ink-muted">
            {line.item_code ? <span className="font-mono">{line.item_code}</span> : null}
            <span>{m.lineTypes[line.line_type] ?? line.line_type}</span>
            {line.hsn_sac ? (
              <span>
                {m.workspace.hsn} <span className="font-mono">{line.hsn_sac}</span>
              </span>
            ) : null}
          </p>
          {line.remarks ? <p className="text-sm text-ink [overflow-wrap:anywhere]">{line.remarks}</p> : null}
          {challan.status !== "draft" && challan.return_type === "returnable" && !isReturn ? (
            <p className="text-sm text-ink-muted">
              {m.workspace.returned(`${line.returned_quantity} ${line.unit}`)} · {m.workspace.outstanding(`${line.outstanding_quantity} ${line.unit}`)}
            </p>
          ) : null}
        </div>
        <div className="flex items-start gap-2">
          {editable ? null : (
            <p className="font-semibold">
              <Quantity value={{ value: line.quantity, uom: line.unit }} />
            </p>
          )}
          {editable ? (
            <IconButton label={m.workspace.remove(`${line.line_no}. ${name}`)} onPress={remove} {...unavailableWhen(commands.offline)}>
              <CloseIcon size={18} />
            </IconButton>
          ) : null}
        </div>
      </div>
      {editable ? (
        <RacTextField
          value={text}
          onChange={(value) => {
            setText(value);
            saver.change(value);
          }}
          onBlur={() => void saver.flush()}
          onKeyDown={(event) => {
            if (event.key === "Enter") void saver.flush();
          }}
          inputMode="decimal"
          isInvalid={invalid}
          validationBehavior="aria"
          className="flex max-w-xs flex-col gap-1.5"
        >
          <Label className={labelClasses}>{`${m.workspace.quantity} (${line.unit})`}</Label>
          <Input autoComplete="off" spellCheck={false} className={cx(inputClasses, "tabular text-end")} />
        </RacTextField>
      ) : null}
      {editable ? (
        <div className="min-h-6" aria-live="polite">
          <SaveStatus state={state} onRetry={() => void saver.retry()} />
        </div>
      ) : null}
    </li>
  );
}
