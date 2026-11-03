"use client";

import { useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, IconButton, unavailableWhen } from "@/components/ui/button";
import { DescriptionList } from "@/components/ui/description-list";
import { Money, Quantity } from "@/components/ui/format";
import { CloseIcon } from "@/components/ui/icons";
import { NumberField } from "@/components/ui/number-field";
import { ComboBox, Select } from "@/components/ui/select";
import { TextField } from "@/components/ui/text-field";
import { queryKeys } from "@/lib/api/query-keys";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { useDebouncedValue } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { fetchCustomProducts } from "@/features/custom-products/api";
import { salesMessages as m } from "@/messages/sales";
import { addQuoteLine, previewQuote, removeQuoteLine, updateQuoteLine } from "./api";
import { ConfiguratorDrawer } from "./configurator-drawer";
import { useProductSearch, type ProductOption } from "./pickers";
import { MANUAL_PRESETS, type ManualPreset, type QuoteDetail, type QuoteLine, type QuotePreview } from "./types";
import type { useQuoteCommand } from "./use-quote-command";
import { lineEditIsDirty, lineEditOf, lineUpdatePlan, previewRequest, priceDiffersFromList, type LineEdit } from "./workspace-model";

type Commands = ReturnType<typeof useQuoteCommand>;

const isZero = (amount: string) => isDecimalStr(amount) && compareDecimalStr(amount, "0") === 0;

function lineName(line: Pick<QuoteLine, "product_key" | "description">): string {
  return [line.product_key, line.description].filter(Boolean).join(" · ");
}

/** The lines, the add-line forms and the totals (server totals, or a live preview while editing). */
export function QuoteLines({ quote, editable, commands }: { quote: QuoteDetail; editable: boolean; commands: Commands }) {
  const [edits, setEdits] = useState<Record<string, LineEdit>>({});
  const titleId = useId();
  // Edits for lines that no longer exist (removed elsewhere) are ignored.
  const liveEdits = Object.fromEntries(Object.entries(edits).filter(([id]) => quote.lines.some((line) => line.id === id)));
  const request = previewRequest(quote, liveEdits);
  const debounced = useDebouncedValue(request ? JSON.stringify(request) : null, 400);
  const preview = useQuery({
    queryKey: queryKeys.sales.quotePreview(quote.id, debounced ?? ""),
    queryFn: ({ signal }) => previewQuote(JSON.parse(debounced!) as NonNullable<typeof request>, signal),
    enabled: editable && debounced !== null,
    staleTime: 30_000,
  });

  const setEdit = (line: QuoteLine, change: Partial<LineEdit>) =>
    setEdits((current) => ({ ...current, [line.id]: { ...(current[line.id] ?? lineEditOf(line)), ...change } }));
  const discard = (line: QuoteLine) =>
    setEdits((current) => {
      const next = { ...current };
      delete next[line.id];
      return next;
    });

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-4">
      <h2 id={titleId} className="text-lg font-[650] text-ink">
        {m.workspace.lines}
      </h2>
      {quote.lines.length === 0 ? (
        <p className="text-ink-muted">{m.workspace.noLines}</p>
      ) : (
        <>
          {editable ? <p className="text-sm text-ink-muted">{m.workspace.linesEditHint}</p> : null}
          <ol className="flex flex-col divide-y border-y" aria-label={m.workspace.linesCaption(quote.quote_number)}>
            {quote.lines.map((line) => (
              <LineRow
                key={line.id}
                quote={quote}
                line={line}
                edit={liveEdits[line.id] ?? null}
                previewTotal={request && preview.data ? (preview.data.line_totals[line.line_key] ?? null) : null}
                editable={editable}
                commands={commands}
                onEdit={(change) => setEdit(line, change)}
                onDiscard={() => discard(line)}
              />
            ))}
          </ol>
        </>
      )}
      <Totals quote={quote} preview={request && preview.data && debounced === JSON.stringify(request) ? preview.data : null} previewFailed={request !== null && preview.isError} />
      {editable ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <AddProductLine quote={quote} commands={commands} />
          <AddManualLine quote={quote} commands={commands} />
          <AddCustomLine quote={quote} commands={commands} />
        </div>
      ) : (
        <p className="text-sm text-ink-muted">{m.workspace.readOnly}</p>
      )}
    </section>
  );
}

function LineRow({
  quote,
  line,
  edit,
  previewTotal,
  editable,
  commands,
  onEdit,
  onDiscard,
}: {
  quote: QuoteDetail;
  line: QuoteLine;
  edit: LineEdit | null;
  previewTotal: string | null;
  editable: boolean;
  commands: Commands;
  onEdit: (change: Partial<LineEdit>) => void;
  onDiscard: () => void;
}) {
  const [error, setError] = useState<"quantity" | "price" | "reason" | null>(null);
  const current = edit ?? lineEditOf(line);
  const dirty = edit !== null && lineEditIsDirty(line, edit);
  const differs = priceDiffersFromList(line, current.unit_price);
  const name = lineName(line);
  const money = (amount: string | null) => (amount ? { amount, currency: quote.currency } : null);
  const advisories = line.advisories.map((code) => m.workspace.advisories[code]).filter((text): text is string => Boolean(text));

  const apply = async () => {
    const plan = lineUpdatePlan(line, current);
    if (!plan.ok) {
      setError(plan.error);
      return;
    }
    setError(null);
    if (Object.keys(plan.body).length === 0) {
      onDiscard();
      return;
    }
    const outcome = await commands.run(
      "update_line",
      [line.id, quote.version, JSON.stringify(plan.body)],
      (key) => updateQuoteLine(quote, line.id, plan.body, key),
      { done: m.workspace.updated, failed: m.workspace.failed(m.workspace.applyLine), conflictMessage: m.workspace.lineConflict },
    );
    if (outcome.ok) onDiscard();
  };

  const remove = () =>
    void commands.run("remove_line", [line.id, quote.version], (key) => removeQuoteLine(quote, line.id, key), {
      done: m.workspace.removed,
      failed: m.workspace.failed(m.workspace.remove(name)),
      conflictMessage: m.workspace.lineConflict,
    });

  return (
    <li className="flex flex-col gap-3 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="font-semibold text-ink">
            <span className="text-ink-muted tabular">{line.line_no}. </span>
            {line.description}
          </p>
          {line.product_key ? <p className="font-mono text-sm text-ink-muted">{line.product_key}</p> : null}
          {line.recommendation?.label ? <p className="text-sm text-ink-muted">{line.recommendation.label}</p> : null}
          {advisories.map((text) => (
            <p key={text} className="text-sm text-warning-text">
              {text}
            </p>
          ))}
          {line.is_overridden && line.override_reason && !edit ? (
            <p className="text-sm text-ink-muted">
              {m.workspace.overrideReason} {line.override_reason}
            </p>
          ) : null}
        </div>
        <div className="flex items-start gap-2">
          <div className="text-end">
            <p className="text-sm text-ink-muted">{m.workspace.columns.total}</p>
            <p className="font-semibold">
              <Money value={money(dirty && previewTotal ? previewTotal : line.line_total)} />
            </p>
          </div>
          {editable ? (
            <IconButton label={m.workspace.remove(`${line.line_no}. ${name}`)} onPress={remove} {...unavailableWhen(commands.offline ?? (commands.pending ? m.workspace.saving : null))}>
              <CloseIcon size={18} />
            </IconButton>
          ) : null}
        </div>
      </div>
      {editable ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,2fr)_auto] lg:items-start">
          <NumberField
            label={`${m.workspace.quantity} (${line.unit_code})`}
            value={current.quantity}
            onChange={(quantity) => onEdit({ quantity })}
            uom={line.unit_code}
            maxFractionDigits={4}
            errorMessage={error === "quantity" ? m.workspace.quantityInvalid : undefined}
          />
          <NumberField
            label={m.workspace.unitPrice}
            value={current.unit_price}
            onChange={(unit_price) => onEdit({ unit_price })}
            currency={quote.currency}
            maxFractionDigits={4}
            description={line.default_unit_price ? m.workspace.listPrice(`${line.default_unit_price} ${quote.currency}`) : undefined}
            errorMessage={error === "price" ? m.workspace.priceInvalid : undefined}
          />
          {differs ? (
            <TextField
              label={m.workspace.overrideReason}
              value={current.override_reason}
              onChange={(override_reason) => onEdit({ override_reason })}
              maxLength={500}
              isRequired
              errorMessage={error === "reason" ? m.workspace.overrideRequired : undefined}
            />
          ) : (
            <div className="hidden lg:block" />
          )}
          {dirty ? (
            <div className="flex gap-2 lg:pt-7">
              <Button variant="primary" size="sm" onPress={() => void apply()} isPending={commands.pending === "update_line"} {...unavailableWhen(commands.offline)}>
                {m.workspace.applyLine}
              </Button>
              <Button variant="quiet" size="sm" onPress={onDiscard}>
                {m.workspace.discard}
              </Button>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-ink-muted">
          <Quantity value={{ value: line.quantity, uom: line.unit_code }} /> × <Money value={money(line.unit_price)} maxFractionDigits={4} />
        </p>
      )}
    </li>
  );
}

/** Saved totals from the server; while a line edit is pending, the server's preview of it. */
export function Totals({ quote, preview, previewFailed = false }: { quote: Pick<QuoteDetail, "totals" | "currency">; preview: QuotePreview | null; previewFailed?: boolean }) {
  const titleId = useId();
  const t = quote.totals;
  const currency = quote.currency;
  const asMoney = (amount: string | null) => (amount ? { amount, currency } : null);
  const items = preview
    ? [
        { term: m.workspace.subtotal, description: <Money value={asMoney(preview.applicable_subtotal)} />, numeric: true },
        ...(isZero(preview.discount_total) ? [] : [{ term: m.workspace.discount, description: <Money value={asMoney(preview.discount_total)} />, numeric: true }]),
        ...(preview.surcharge_applied
          ? [{ term: preview.surcharge_label || m.workspace.surcharge, description: <Money value={asMoney(preview.surcharge_amount)} />, numeric: true }]
          : []),
        { term: m.workspace.grandTotal, description: <Money value={asMoney(preview.grand_total)} className="font-semibold" />, numeric: true },
      ]
    : [
        { term: m.workspace.subtotal, description: <Money value={t.applicable_subtotal} />, numeric: true },
        ...(isZero(t.discount_total.amount) ? [] : [{ term: m.workspace.discount, description: <Money value={t.discount_total} />, numeric: true }]),
        ...(t.surcharge_applied ? [{ term: t.surcharge_label || m.workspace.surcharge, description: <Money value={t.surcharge} />, numeric: true }] : []),
        { term: m.workspace.grandTotal, description: <Money value={t.grand_total} className="font-semibold" />, numeric: true },
      ];
  const note = preview ? preview.recommendation : t.threshold_note;
  const complete = preview ? preview.totals_complete : t.totals_complete;
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2 rounded-lg border bg-surface p-4" data-totals={preview ? "preview" : "saved"}>
      <h3 id={titleId} className="font-[650] text-ink">
        {preview ? m.workspace.previewing : m.workspace.totals}
      </h3>
      <DescriptionList items={items} />
      {note ? <p className="text-sm text-ink-muted">{note}</p> : null}
      {complete ? null : <p className="text-sm text-warning-text">{m.workspace.incomplete}</p>}
      {previewFailed ? <p className="text-sm text-ink-muted">{m.workspace.previewUnavailable}</p> : null}
    </section>
  );
}

function AddProductLine({ quote, commands }: { quote: QuoteDetail; commands: Commands }) {
  const titleId = useId();
  const [text, setText] = useState("");
  const [product, setProduct] = useState<ProductOption | null>(null);
  const [quantity, setQuantity] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const products = useProductSearch(text);
  const options = [...(product ? [product] : []), ...(products.data ?? []).filter((candidate) => candidate.id !== product?.id)];
  const quantityOk = quantity !== null && isDecimalStr(quantity) && compareDecimalStr(quantity, "0") > 0;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!product || !quantityOk) return;
    const line = { line_type: "catalog" as const, product_id: product.id, quantity: quantity! };
    const outcome = await commands.run("add_line", [quote.version, product.id, quantity], (key) => addQuoteLine(quote, line, key), {
      done: m.workspace.added,
      failed: m.workspace.failed(m.workspace.addLine),
      conflictMessage: m.workspace.lineConflict,
    });
    if (outcome.ok) {
      setProduct(null);
      setText("");
      setQuantity(null);
      setSubmitted(false);
    }
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={titleId} className="font-[650] text-ink">
          {m.workspace.addProduct}
        </h3>
        <Button variant="secondary" onPress={() => setBrowsing(true)}>
          {m.workspace.browseCatalogue}
        </Button>
      </div>
      <ConfiguratorDrawer quote={quote} commands={commands} isOpen={browsing} onOpenChange={setBrowsing} />
      <Form onSubmit={submit} className="flex flex-col gap-3" validationBehavior="aria">
        <ComboBox
          label={m.workspace.productSearch}
          placeholder={m.workspace.productPlaceholder}
          emptyText={text.trim().length < 2 ? m.workspace.productPlaceholder : m.workspace.productEmpty}
          options={options.map((option) => ({ id: option.id, label: option.product_name, detail: option.product_key }))}
          value={product?.id ?? null}
          inputValue={text}
          onInputChange={setText}
          onChange={(id) => {
            const chosen = options.find((candidate) => candidate.id === id) ?? null;
            setProduct(chosen);
            if (chosen) setText(chosen.product_name);
          }}
          isRequired
          errorMessage={submitted && !product ? m.workspace.productRequired : undefined}
        />
        <NumberField
          label={product?.unit_of_sale ? `${m.workspace.quantity} (${product.unit_of_sale})` : m.workspace.quantity}
          value={quantity}
          onChange={setQuantity}
          uom={product?.unit_of_sale ?? undefined}
          isRequired
          errorMessage={submitted && !quantityOk ? m.workspace.quantityInvalid : undefined}
        />
        <div>
          <Button type="submit" variant="secondary" isPending={commands.pending === "add_line"} pendingLabel={m.workspace.saving} {...unavailableWhen(commands.offline)}>
            {m.workspace.addLine}
          </Button>
        </div>
      </Form>
    </section>
  );
}

function AddManualLine({ quote, commands }: { quote: QuoteDetail; commands: Commands }) {
  const titleId = useId();
  const [preset, setPreset] = useState<ManualPreset>("development");
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState<string | null>("1");
  const [price, setPrice] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const quantityOk = quantity !== null && isDecimalStr(quantity) && compareDecimalStr(quantity, "0") > 0;
  const priceOk = price !== null && isDecimalStr(price);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!quantityOk || !priceOk) return;
    const line = {
      line_type: "manual" as const,
      manual_preset: preset,
      quantity: quantity!,
      unit_price: price!,
      ...(description.trim() ? { description: description.trim() } : {}),
    };
    const outcome = await commands.run("add_manual_line", [quote.version, preset, quantity, price, description.trim()], (key) => addQuoteLine(quote, line, key), {
      done: m.workspace.added,
      failed: m.workspace.failed(m.workspace.addLine),
      conflictMessage: m.workspace.lineConflict,
    });
    if (outcome.ok) {
      setDescription("");
      setQuantity("1");
      setPrice(null);
      setSubmitted(false);
    }
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3 rounded-lg border p-4">
      <h3 id={titleId} className="font-[650] text-ink">
        {m.workspace.addManual}
      </h3>
      <Form onSubmit={submit} className="flex flex-col gap-3" validationBehavior="aria">
        <Select
          label={m.workspace.preset}
          options={MANUAL_PRESETS.map((id) => ({ id, label: m.presets[id] ?? id }))}
          value={preset}
          onChange={(value) => setPreset(MANUAL_PRESETS.find((candidate) => candidate === value) ?? "miscellaneous")}
        />
        <TextField label={m.workspace.description} description={m.workspace.manualDescriptionHint} value={description} onChange={setDescription} maxLength={500} />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NumberField label={m.workspace.quantity} value={quantity} onChange={setQuantity} isRequired errorMessage={submitted && !quantityOk ? m.workspace.quantityInvalid : undefined} />
          <NumberField
            label={m.workspace.unitPriceManual}
            value={price}
            onChange={setPrice}
            currency={quote.currency}
            isRequired
            errorMessage={submitted && !priceOk ? m.workspace.priceInvalid : undefined}
          />
        </div>
        <div>
          <Button type="submit" variant="secondary" isPending={commands.pending === "add_manual_line"} pendingLabel={m.workspace.saving} {...unavailableWhen(commands.offline)}>
            {m.workspace.addLine}
          </Button>
        </div>
      </Form>
    </section>
  );
}


/** A custom-product line (LM-47, UI-61): search the custom-product library the person can see. */
function AddCustomLine({ quote, commands }: { quote: QuoteDetail; commands: Commands }) {
  const titleId = useId();
  const { permissionKeys } = useSession();
  const [text, setText] = useState("");
  const [chosen, setChosen] = useState<{ id: string; label: string } | null>(null);
  const [quantity, setQuantity] = useState<string | null>(null);
  const [price, setPrice] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const q = useDebouncedValue(text.trim(), 250);
  const search = useQuery({
    queryKey: queryKeys.sales.customProducts({ q, status: null, scope: "all", offset: 0 }),
    queryFn: ({ signal }) => fetchCustomProducts({ q, scope: "all" }, signal),
    enabled: q.length >= 2 && permissionKeys.has("sales.custom_product.read"),
    staleTime: 30_000,
  });
  if (!permissionKeys.has("sales.custom_product.read")) return null;
  const options = [
    ...(chosen ? [chosen] : []),
    ...(search.data?.items ?? [])
      .filter((item) => item.id !== chosen?.id && item.status !== "rejected" && item.status !== "converted_to_standard")
      .map((item) => ({ id: item.id, label: `${item.custom_code} · ${item.product_name}` })),
  ];
  const quantityOk = quantity !== null && isDecimalStr(quantity) && compareDecimalStr(quantity, "0") > 0;
  const priceOk = price === null || isDecimalStr(price);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!chosen || !quantityOk || !priceOk) return;
    const line = { line_type: "custom" as const, custom_product_id: chosen.id, quantity: quantity!, ...(price ? { unit_price: price } : {}) };
    const outcome = await commands.run("add_custom_line", [quote.version, chosen.id, quantity, price], (key) => addQuoteLine(quote, line, key), {
      done: m.workspace.added,
      failed: m.workspace.failed(m.workspace.addLine),
      conflictMessage: m.workspace.lineConflict,
    });
    if (outcome.ok) {
      setChosen(null);
      setText("");
      setQuantity(null);
      setPrice(null);
      setSubmitted(false);
    }
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3 rounded-lg border p-4">
      <h3 id={titleId} className="font-[650] text-ink">
        {m.workspace.addCustom}
      </h3>
      <Form onSubmit={submit} className="flex flex-col gap-3" validationBehavior="aria">
        <ComboBox
          label={m.workspace.customSearch}
          placeholder={m.workspace.customPlaceholder}
          emptyText={text.trim().length < 2 ? m.workspace.customPlaceholder : m.workspace.customEmpty}
          options={options}
          value={chosen?.id ?? null}
          inputValue={text}
          onInputChange={setText}
          onChange={(id) => {
            const option = options.find((candidate) => candidate.id === id) ?? null;
            setChosen(option);
            if (option) setText(option.label);
          }}
          isRequired
          errorMessage={submitted && !chosen ? m.workspace.customRequired : undefined}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NumberField label={m.workspace.quantity} value={quantity} onChange={setQuantity} isRequired errorMessage={submitted && !quantityOk ? m.workspace.quantityInvalid : undefined} />
          <NumberField
            label={m.workspace.unitPriceManual}
            description={m.workspace.customPriceHint}
            value={price}
            onChange={setPrice}
            currency={quote.currency}
            errorMessage={submitted && !priceOk ? m.workspace.priceInvalid : undefined}
          />
        </div>
        <div>
          <Button type="submit" variant="secondary" isPending={commands.pending === "add_custom_line"} pendingLabel={m.workspace.saving} {...unavailableWhen(commands.offline)}>
            {m.workspace.addLine}
          </Button>
        </div>
      </Form>
    </section>
  );
}
