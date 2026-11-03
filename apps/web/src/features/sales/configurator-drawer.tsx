"use client";

import { useId, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Money } from "@/components/ui/format";
import { NumberField } from "@/components/ui/number-field";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { useSession } from "@/lib/session/context";
import { salesMessages } from "@/messages/sales";
import { addQuoteLine } from "./api";
import {
  ANY,
  CONFIGURATOR_FILTERS,
  CONFIGURATOR_PAGE_SIZE,
  EMPTY_FILTERS,
  activeFilterCount,
  filterOptions,
  pageLabel,
  pickAdvisories,
  pickLine,
  useConfigurator,
  type ConfiguratorFilters,
  type ConfiguratorRow,
  type PickError,
} from "./configurator";
import type { QuoteDetail } from "./types";
import type { useQuoteCommand } from "./use-quote-command";

const m = salesMessages.configurator;
const w = salesMessages.workspace;
type Commands = ReturnType<typeof useQuoteCommand>;

/** UI-60: the configurator drawer — type-ahead, six cascading filters, priced and paged results, then the pick form. */
export function ConfiguratorDrawer({
  quote,
  commands,
  isOpen,
  onOpenChange,
}: {
  quote: QuoteDetail;
  commands: Commands;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Drawer
      width="lg"
      title={m.title}
      description={m.description(quote.party.display_name, quote.currency)}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
    >
      <ConfiguratorPanel
        quote={quote}
        commands={commands}
        onAdded={() => onOpenChange(false)}
      />
    </Drawer>
  );
}

/** The drawer's content (state lives here, so closing the drawer resets it). */
export function ConfiguratorPanel({
  quote,
  commands,
  onAdded,
}: {
  quote: QuoteDetail;
  commands: Commands;
  onAdded: () => void;
}) {
  const [filters, setFilters] = useState<ConfiguratorFilters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [picked, setPicked] = useState<ConfiguratorRow | null>(null);
  const result = useConfigurator(quote, filters, offset, true);
  const data = result.data;

  const setFilter = (change: Partial<ConfiguratorFilters>) => {
    setFilters((current) => ({ ...current, ...change }));
    setOffset(0);
  };
  const exact = data?.exact_match
    ? (data.items.find((row) => row.product.id === data.exact_match) ?? null)
    : null;
  const range = data ? pageLabel(data) : null;

  return picked ? (
    <PickForm
      key={picked.product.id}
      quote={quote}
      row={picked}
      commands={commands}
      onBack={() => setPicked(null)}
      onAdded={onAdded}
    />
  ) : (
    <div className="flex flex-col gap-4">
      <SearchField
        label={m.search}
        placeholder={m.searchPlaceholder}
        value={filters.q}
        onChange={(q) => setFilter({ q })}
        onSubmit={() => (exact ? setPicked(exact) : undefined)}
        autoFocus
      />
      <p className="-mt-2 text-sm text-ink-muted">{m.searchHint}</p>
      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <legend className="sr-only">{m.filters}</legend>
        {CONFIGURATOR_FILTERS.map(({ key, facet }) => (
          <Select
            key={key}
            label={m.filter[key] ?? key}
            placeholder={m.any}
            options={filterOptions(
              data?.facets[facet] ?? [],
              filters[key],
              m.any,
            )}
            value={filters[key] ?? ANY}
            onChange={(value) =>
              setFilter({
                [key]: value === null || value === ANY ? null : value,
              })
            }
          />
        ))}
      </fieldset>
      {activeFilterCount(filters) > 0 || filters.q ? (
        <div>
          <Button variant="quiet" onPress={() => setFilter(EMPTY_FILTERS)}>
            {m.clearFilters}
          </Button>
        </div>
      ) : null}
      <section
        aria-label={m.results}
        aria-busy={result.isFetching}
        className="flex flex-col gap-3"
      >
        {result.isError && !data ? (
          <ErrorState
            error={result.error}
            what={m.loading}
            onRetry={() => void result.refetch()}
            backToToday={false}
            compact
            headingLevel={3}
          />
        ) : !data ? (
          <Loading label={m.loading} rows={3} />
        ) : data.items.length === 0 ? (
          <EmptyState title={m.empty} headingLevel={3} />
        ) : (
          <ol className="flex flex-col divide-y border-y">
            {data.items.map((row) => (
              <ResultRow
                key={row.product.id}
                row={row}
                exact={row.product.id === data.exact_match}
                onChoose={() => setPicked(row)}
              />
            ))}
          </ol>
        )}
        {range ? (
          <nav
            aria-label={m.results}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <p className="text-sm text-ink-muted tabular" aria-live="polite">
              {m.showing(range.from, range.to, range.total)}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onPress={() =>
                  setOffset(Math.max(0, offset - CONFIGURATOR_PAGE_SIZE))
                }
                {...unavailableWhen(offset === 0 ? m.firstPage : null)}
              >
                {m.previous}
              </Button>
              <Button
                variant="secondary"
                onPress={() => setOffset(offset + CONFIGURATOR_PAGE_SIZE)}
                {...unavailableWhen(
                  range.to >= range.total ? m.lastPage : null,
                )}
              >
                {m.next}
              </Button>
            </div>
          </nav>
        ) : null}
      </section>
    </div>
  );
}

function facts(row: ConfiguratorRow): string[] {
  const p = row.product;
  const size =
    p.size.diameter_mm != null
      ? `Ø ${p.size.diameter_mm} mm`
      : p.size.length_mm != null && p.size.width_mm != null
        ? `${p.size.length_mm} × ${p.size.width_mm} mm`
        : null;
  return [
    size,
    p.thickness_mm != null ? m.thickness(String(p.thickness_mm)) : null,
    [p.decor_no, p.decor_name].filter(Boolean).join(" ") || null,
    p.finish,
  ].filter((part): part is string => Boolean(part));
}

function ResultRow({
  row,
  exact,
  onChoose,
}: {
  row: ConfiguratorRow;
  exact: boolean;
  onChoose: () => void;
}) {
  const p = row.product;
  return (
    <li
      className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between"
      data-product-key={p.product_key}
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="font-semibold text-ink">
          {p.product_name}{" "}
          {exact ? <Badge tone="forest">{m.exactMatch}</Badge> : null}
        </p>
        <p className="font-mono text-sm text-ink-muted">
          {p.display_sku || p.product_key}
        </p>
        {facts(row).length > 0 ? (
          <p className="text-sm text-ink-muted">{facts(row).join(" · ")}</p>
        ) : null}
        <p className="text-sm text-ink-muted">
          {row.packaging_summary ?? m.noPackaging}
        </p>
        {row.recommendation?.label ? (
          <p className="text-sm text-ink-muted">{row.recommendation.label}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
        <PriceCell row={row} />
        <Button
          variant="secondary"
          onPress={onChoose}
          aria-label={m.choose(p.product_name)}
        >
          {m.chooseShort}
        </Button>
      </div>
    </li>
  );
}

function PriceCell({ row }: { row: ConfiguratorRow }) {
  const price = row.price;
  if (!price) return null; // no pricing.price.read: the row is still listed
  if (!price.unit_price) {
    return (
      <p className="text-sm text-warning-text" title={price.explanation}>
        {m.unpriced}
      </p>
    );
  }
  return (
    <div className="flex flex-col items-start gap-0.5 sm:items-end">
      <p className="font-semibold tabular">
        <Money value={price.unit_price} maxFractionDigits={4} />
        {price.unit_code ? (
          <span className="text-sm font-normal text-ink-muted">
            {" "}
            / {price.unit_code}
          </span>
        ) : null}
      </p>
      {price.converted_with_fx ? (
        <p className="text-xs text-ink-muted">{m.converted}</p>
      ) : null}
    </div>
  );
}

function PickForm({
  quote,
  row,
  commands,
  onBack,
  onAdded,
}: {
  quote: QuoteDetail;
  row: ConfiguratorRow;
  commands: Commands;
  onBack: () => void;
  onAdded: () => void;
}) {
  const titleId = useId();
  const { permissionKeys } = useSession();
  const canOverride = permissionKeys.has("sales.quote_price.override");
  const listed = row.price?.unit_price?.amount ?? null;
  const [quantity, setQuantity] = useState<string | null>(null);
  const [price, setPrice] = useState<string | null>(listed);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<PickError | null>(null);
  const advisories = pickAdvisories(row, quantity, price);
  const recommended = row.recommendation?.quantity?.value ?? "";
  const p = row.product;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const plan = pickLine(row, {
      quantity,
      unitPrice: canOverride ? price : null,
      reason,
    });
    if (!plan.ok) {
      setError(plan.error);
      return;
    }
    setError(null);
    const outcome = await commands.run(
      "add_line",
      [quote.version, p.id, quantity, plan.line.unit_price ?? null],
      (key) => addQuoteLine(quote, plan.line, key),
      {
        done: w.added,
        failed: w.failed(w.addLine),
        conflictMessage: w.lineConflict,
      },
    );
    if (outcome.ok) onAdded();
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <h3 id={titleId} className="text-lg font-[650] text-ink">
          {p.product_name}
        </h3>
        <p className="font-mono text-sm text-ink-muted">
          {p.display_sku || p.product_key}
        </p>
        {facts(row).length > 0 ? (
          <p className="text-sm text-ink-muted">{facts(row).join(" · ")}</p>
        ) : null}
      </div>
      <dl className="grid grid-cols-1 gap-2 rounded-lg border bg-surface p-3 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-ink-muted">{m.packaging}</dt>
          <dd className="font-semibold">
            {row.packaging_summary ?? m.noPackaging}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-ink-muted">{m.defaultPrice}</dt>
          <dd className="font-semibold">
            {row.price?.unit_price ? (
              <Money value={row.price.unit_price} maxFractionDigits={4} />
            ) : (
              m.unpriced
            )}
          </dd>
        </div>
        {row.recommendation?.label ? (
          <p className="text-sm text-ink-muted sm:col-span-2">
            {row.recommendation.label}
          </p>
        ) : null}
        {row.price && !row.price.unit_price ? (
          <p className="text-sm text-ink-muted sm:col-span-2">
            {row.price.explanation}
          </p>
        ) : null}
      </dl>
      <Form
        onSubmit={submit}
        className="flex flex-col gap-3"
        validationBehavior="aria"
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NumberField
            label={
              p.unit_of_sale ? `${w.quantity} (${p.unit_of_sale})` : w.quantity
            }
            value={quantity}
            onChange={setQuantity}
            uom={p.unit_of_sale ?? undefined}
            isRequired
            errorMessage={error === "quantity" ? m.quantityInvalid : undefined}
          />
          <NumberField
            label={m.unitPrice}
            value={price}
            onChange={setPrice}
            currency={quote.currency}
            isDisabled={!canOverride}
            description={canOverride ? undefined : m.priceReadOnly}
            errorMessage={error === "price" ? m.priceInvalid : undefined}
          />
        </div>
        {advisories.includes("price_differs") ? (
          <TextField
            label={m.reason}
            value={reason}
            onChange={setReason}
            maxLength={500}
            isRequired
            errorMessage={error === "reason" ? m.reasonRequired : undefined}
          />
        ) : null}
        {advisories.length > 0 ? (
          <ul className="flex flex-col gap-1" aria-live="polite">
            {advisories.map((code) => (
              <li key={code} className="text-sm text-warning-text">
                {code === "below_recommendation"
                  ? m.advisories.below_recommendation(recommended)
                  : m.advisories[code]}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            variant="primary"
            isPending={commands.pending === "add_line"}
            pendingLabel={w.saving}
            {...unavailableWhen(commands.offline)}
          >
            {m.add}
          </Button>
          <Button variant="quiet" onPress={onBack}>
            {m.change}
          </Button>
        </div>
      </Form>
    </section>
  );
}
