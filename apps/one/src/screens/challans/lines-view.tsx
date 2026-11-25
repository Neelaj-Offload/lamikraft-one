"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { addChallanLine, fetchChallan, removeChallanLine, updateChallanLine } from "@/features/challans/api";
import { fieldErrorsFrom } from "@/features/challans/form-model";
import { normalisedQuantity } from "@/features/challans/line-save";
import { useProductSearch } from "@/features/challans/pickers";
import { LEGACY_UNITS, type ChallanDetail, type ChallanLine } from "@/features/challans/types";
import type { ChallanCommands } from "@/features/challans/use-challan-command";
import { useDebouncedSaver } from "@/features/challans/use-line-saver";
import { queryKeys } from "@/lib/api/query-keys";
import { EMPTY_LINE, LINE_KIND_LABEL, lineRequest, type LineForm } from "~/data/challans";
import {
  Button,
  Code,
  ComboBox,
  DataTable,
  DecimalField,
  Drawer,
  EmptyState,
  GlassPanel,
  IconButton,
  Qty,
  SegmentedControl,
  Select,
  TextField,
  type Column,
} from "~/ui";
import { QuantityList, stagger } from "./parts";
import { quantityText, saveFailureText } from "./save-text";

/** What a line is, under its name: code, kind, HSN/SAC. */
function lineFacts(line: ChallanLine): string {
  return [line.item_code, LINE_KIND_LABEL[line.line_type] ?? line.line_type, line.hsn_sac ? `HSN ${line.hsn_sac}` : null].filter(Boolean).join(" · ");
}

/**
 * The lines of a challan. On a draft each quantity saves itself a moment after typing stops and a
 * failure stays next to the field; lines are added in a drawer. Once issued the lines are a plain
 * table, with what came back and what is still out for a returnable challan.
 */
export function LinesView({
  challan,
  editable,
  commands,
  onAdd,
}: {
  challan: ChallanDetail;
  editable: boolean;
  commands: ChallanCommands;
  onAdd: () => void;
}) {
  const showReturns = challan.status !== "draft" && challan.return_type === "returnable";
  const heading = (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">
          {editable ? "Quantities save on their own a moment after you stop typing." : "Fixed since the challan was issued. Units are never added together."}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p className="t-body-sm text-ink-2">
          <span className="text-ink-3">Total </span>
          <QuantityList value={challan.quantity_by_unit} className="t-label text-ink" />
        </p>
        {editable && challan.lines.length > 0 ? (
          <Button variant="secondary" size="sm" iconLeft="plus" onPress={onAdd} isDisabled={Boolean(commands.offline)}>
            Add line
          </Button>
        ) : null}
      </div>
    </div>
  );

  if (challan.lines.length === 0) {
    return (
      <div className="stack">
        {heading}
        <GlassPanel padding="lg" className="rise">
          <EmptyState
            icon="list"
            title={editable ? "Add what is travelling" : "This challan has no lines"}
            text={editable ? "A catalogue product brings its code, HSN and unit with it. Anything else can be typed in by hand." : "It was issued without lines."}
            actions={
              editable ? (
                <Button iconLeft="plus" onPress={onAdd} isDisabled={Boolean(commands.offline)}>
                  Add the first line
                </Button>
              ) : undefined
            }
          />
        </GlassPanel>
      </div>
    );
  }

  if (editable) {
    return (
      <div className="stack">
        {heading}
        <GlassPanel padding="none" className="rise min-w-0 overflow-hidden">
          <ol className="m-0 flex list-none flex-col p-0" aria-label={`Lines of ${challan.challan_number}`}>
            {challan.lines.map((line, index) => (
              <EditableLine key={line.id} line={line} index={index} commands={commands} />
            ))}
          </ol>
        </GlassPanel>
      </div>
    );
  }

  const columns: Column<ChallanLine>[] = [
    {
      key: "item",
      header: "Line",
      primary: true,
      cell: (line) => (
        <span className="flex min-w-0 items-start gap-3">
          <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{line.line_no}</span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="t-label text-ink [overflow-wrap:anywhere]">{line.item_name}</span>
            <span className="t-caption text-ink-3">{lineFacts(line)}</span>
            {line.remarks ? <span className="t-caption text-ink-2 [overflow-wrap:anywhere]">{line.remarks}</span> : null}
          </span>
        </span>
      ),
    },
    { key: "quantity", header: "Quantity", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.unit }} /> },
    ...(showReturns
      ? ([
          {
            key: "returned",
            header: "Came back",
            numeric: true,
            cell: (line) => (line.original_line_id ? <span className="text-ink-3">Return line</span> : <Qty value={{ value: line.returned_quantity, uom: line.unit }} />),
          },
          {
            key: "outstanding",
            header: "Still out",
            numeric: true,
            cell: (line) =>
              line.original_line_id ? null : (
                <span className="t-label text-ink">
                  <Qty value={{ value: line.outstanding_quantity, uom: line.unit }} />
                </span>
              ),
          },
        ] satisfies Column<ChallanLine>[])
      : []),
  ];

  return (
    <div className="stack">
      {heading}
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable label={`Lines of ${challan.challan_number}`} columns={columns} rows={challan.lines} rowKey={(line) => line.id} />
      </GlassPanel>
    </div>
  );
}

/** The save state under a quantity; a failure's words sit on the field itself. */
function SaveLine({ status, onRetry }: { status: string; onRetry: () => void }) {
  if (status === "idle" || status === "invalid") return null;
  if (status === "failed") {
    return (
      <Button size="sm" variant="secondary" iconLeft="refresh" onPress={onRetry}>
        Save again
      </Button>
    );
  }
  return (
    <span className="t-caption text-ink-3" data-save={status}>
      {status === "pending" ? "Not saved yet" : status === "saving" ? "Saving" : "Saved"}
    </span>
  );
}

function EditableLine({ line, index, commands }: { line: ChallanLine; index: number; commands: ChallanCommands }) {
  const [text, setText] = useState(line.quantity);
  const saver = useDebouncedSaver<string>(
    async (raw) => {
      const quantity = normalisedQuantity(raw);
      const outcome = await commands.run("update_line", [line.id, quantity], (key, current) => updateChallanLine(current, line.id, { quantity }, key), { failed: null });
      if (!outcome.ok) throw outcome.error;
    },
    { validate: quantityText },
  );
  const state = saver.state;
  const name = [line.item_code, line.item_name].filter(Boolean).join(" · ");
  const remove = () =>
    void commands.run("remove_line", [line.id], (key, current) => removeChallanLine(current, line.id, key), {
      done: "Line removed",
      failed: "The line was not removed",
    });

  return (
    <li className="rise-plain flex min-w-0 flex-col gap-4 border-line px-5 py-5 sm:flex-row sm:items-start [&:not(:first-child)]:border-t" style={stagger(index)} data-line={line.line_no}>
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{line.line_no}</span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="t-label text-ink [overflow-wrap:anywhere]">{line.item_name}</p>
          <p className="t-caption text-ink-3">{lineFacts(line)}</p>
          {line.remarks ? <p className="t-caption text-ink-2 [overflow-wrap:anywhere]">{line.remarks}</p> : null}
        </div>
      </div>
      <div className="flex min-w-0 items-start gap-2 pl-8 sm:pl-0">
        <div className="flex w-full min-w-0 flex-col gap-1 sm:w-48">
          <DecimalField
            label={`Quantity of line ${line.line_no}`}
            hideLabel
            value={text}
            onChange={(value) => {
              setText(value);
              saver.change(value);
            }}
            suffix={line.unit}
            maxFractionDigits={4}
            isDisabled={Boolean(commands.offline)}
            error={state.status === "failed" ? saveFailureText(state.error) : state.status === "invalid" ? state.reason : undefined}
          />
          <div className="min-h-5" aria-live="polite">
            <SaveLine status={state.status} onRetry={() => void saver.retry()} />
          </div>
        </div>
        <IconButton icon="trash" label={`Remove line ${line.line_no}, ${name}`} variant="ghost" onPress={remove} isDisabled={Boolean(commands.offline) || commands.pending === "remove_line"} />
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------------------------
// Add a line

const SHOWN = new Set(["product_id", "item_name", "quantity", "item_code", "hsn_sac", "unit", "remarks", "original_line_id"]);

const REQUIRED: Record<string, string> = {
  product_id: "Choose the product. Type two letters of its name or code to search.",
  item_name: "Name the item. It is printed on the challan.",
  quantity: "Enter how many are travelling.",
};

/**
 * Add a line: a catalogue product (its code, name, HSN/SAC and unit come with it) or an item typed
 * in by hand. On a return, the line can point at the line of the original challan it brings back.
 */
export function AddLineDrawer({ challan, commands, isOpen, onClose }: { challan: ChallanDetail; commands: ChallanCommands; isOpen: boolean; onClose: () => void }) {
  const [form, setForm] = useState<LineForm>(EMPTY_LINE);
  const [productText, setProductText] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const products = useProductSearch(productText);
  const options = [...(form.product ? [form.product] : []), ...(products.data ?? []).filter((product) => product.id !== form.product?.id)];
  const set = <K extends keyof LineForm>(key: K, value: LineForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const request = lineRequest(form);
  const original = challan.challan_type === "return" && challan.original_challan ? challan.original_challan : null;
  const originalQuery = useQuery({
    queryKey: queryKeys.challans.challan(original?.id ?? ""),
    queryFn: ({ signal }) => fetchChallan(original!.id, signal),
    enabled: original !== null && isOpen,
  });
  const busy = commands.pending === "add_line";
  /** A 422 on a field this form does not show (the server checks the whole line). */
  const otherError = Object.entries(errors).find(([field]) => !SHOWN.has(field))?.[1] ?? null;

  const reset = () => {
    setForm({ ...EMPTY_LINE, kind: form.kind });
    setProductText("");
    setErrors({});
    setSubmitted(false);
  };
  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const missing = (field: string, ok: boolean) => (submitted && !ok ? REQUIRED[field] : undefined) ?? errors[field] ?? undefined;

  const submit = async (another: boolean) => {
    setSubmitted(true);
    if (!request) return;
    setErrors({});
    const outcome = await commands.run("add_line", [JSON.stringify(request)], (key, current) => addChallanLine(current, request, key), {
      done: "Line added",
      failed: "The line was not added",
    });
    if (!outcome.ok) {
      setErrors(fieldErrorsFrom(outcome.error));
      return;
    }
    reset();
    if (!another) onClose();
  };

  const [another, setAnother] = useState(false);
  const press = (next: boolean) => {
    setAnother(next);
    void submit(next);
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      title="Add a line"
      description={`${challan.challan_number} · ${challan.destination_party}`}
      footer={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Cancel
          </Button>
          <Button variant="secondary" loading={busy && another} isDisabled={Boolean(commands.offline) || busy} onPress={() => press(true)}>
            Add and next
          </Button>
          <Button loading={busy && !another} isDisabled={Boolean(commands.offline) || busy} onPress={() => press(false)}>
            Add line
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-5"
        noValidate
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          if (!busy) press(false);
        }}
      >
        <SegmentedControl
          label="Kind of line"
          options={[
            { value: "catalog", label: "Catalogue product" },
            { value: "manual", label: "Typed in by hand" },
          ]}
          value={form.kind}
          onChange={(kind) => {
            set("kind", kind === "manual" ? "manual" : "catalog");
            setSubmitted(false);
          }}
        />
        {form.kind === "catalog" ? (
          <ComboBox
            label="Product"
            placeholder="Type a name or code"
            items={options.map((product) => ({ id: product.id, label: product.product_name, description: product.product_key }))}
            inputValue={productText}
            onInputChange={setProductText}
            selectedKey={form.product?.id ?? null}
            onSelectionChange={(id) => {
              const product = options.find((candidate) => candidate.id === id) ?? null;
              set("product", product);
              if (product) setProductText(product.product_name);
            }}
            isLoading={products.isFetching}
            emptyText={productText.trim().length < 2 ? "Type at least two letters" : "No product matches. Check the spelling, or type the item in by hand."}
            help="Its code, HSN/SAC and unit come from the catalogue."
            error={missing("product_id", form.product !== null)}
          />
        ) : (
          <>
            <TextField label="Item" value={form.item_name} onChange={(value) => set("item_name", value)} maxLength={500} error={missing("item_name", form.item_name.trim() !== "")} />
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              <TextField label="Item code" optional value={form.item_code} onChange={(value) => set("item_code", value)} maxLength={120} error={errors.item_code} />
              <TextField label="HSN/SAC" optional inputMode="numeric" value={form.hsn_sac} onChange={(value) => set("hsn_sac", value)} maxLength={8} error={errors.hsn_sac} />
            </div>
          </>
        )}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <DecimalField
            label="Quantity"
            value={form.quantity}
            onChange={(value) => set("quantity", value)}
            maxFractionDigits={4}
            suffix={form.kind === "manual" ? form.unit : undefined}
            help={form.kind === "catalog" ? "In the product's own unit." : undefined}
            error={missing("quantity", form.quantity !== "")}
          />
          {form.kind === "manual" ? (
            <Select label="Unit" options={LEGACY_UNITS.map((unit) => ({ value: unit, label: unit }))} value={form.unit} onChange={(value) => set("unit", value || "pcs")} error={errors.unit} />
          ) : null}
        </div>
        <TextField label="Remarks" optional value={form.remarks} onChange={(value) => set("remarks", value)} help="Printed beside the line." error={errors.remarks} />
        {original ? (
          <Select
            label={`Line of ${original.challan_number}`}
            optional
            placeholder="Choose the line it brings back"
            options={[
              { value: "", label: "Not linked" },
              ...(originalQuery.data?.lines ?? []).map((line) => ({
                value: line.id,
                label: `${line.line_no}. ${line.item_name}`,
                description: `Still out: ${line.outstanding_quantity} ${line.unit}`,
              })),
            ]}
            value={form.original_line_id ?? ""}
            onChange={(value) => set("original_line_id", value || null)}
            help="The server checks it against what is still out."
            error={errors.original_line_id}
          />
        ) : null}
        {otherError ? <p className="t-body-sm text-ember-text">{otherError}</p> : null}
        <p className="t-caption text-ink-3">
          Adding to draft <Code>{challan.challan_number}</Code>.
        </p>
      </form>
    </Drawer>
  );
}
