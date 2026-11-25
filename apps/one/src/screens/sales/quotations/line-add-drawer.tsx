"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchCustomProducts } from "@/features/custom-products/api";
import { addQuoteLine } from "@/features/sales/api";
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
} from "@/features/sales/configurator";
import { MANUAL_PRESETS, type LineCreateRequest, type ManualPreset, type QuoteDetail } from "@/features/sales/types";
import { queryKeys } from "@/lib/api/query-keys";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { useDebouncedValue } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  Code,
  ComboBox,
  DecimalField,
  Drawer,
  EmptyState,
  Pagination,
  RadioCards,
  SearchField,
  Select,
  SkeletonRows,
  TextField,
  type RadioCardOption,
} from "~/ui";
import type { QuoteCommands } from "./quotation-actions";
import { Steps, UnitPrice, type StepState } from "./parts";

type Kind = "catalog" | "custom" | "manual";
type Stage = 0 | 1 | 2;

const FILTER_LABEL: Record<string, string> = { category_id: "Category", family: "Family", size: "Size", thickness: "Thickness", decor: "Decor", finish: "Finish" };
const PRESET_LABEL: Record<string, string> = {
  development: "Development charges",
  tooling: "Tooling charges",
  special_packaging: "Special packaging",
  freight: "Freight",
  sample: "Sample",
  miscellaneous: "Miscellaneous charges",
};
const CONFLICT = "Someone changed this quotation while you were adding a line. The latest version is shown; add the line again.";
const positive = (value: string) => isDecimalStr(value) && compareDecimalStr(value, "0") > 0;

/**
 * Add a line in three decisions: what kind of line, which item, how many at what price.
 * The server prices catalogue products for this customer and prices again when the line is added.
 */
export function LineAddDrawer({ quote, commands, isOpen, onOpenChange }: { quote: QuoteDetail; commands: QuoteCommands; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      width="lg"
      title="Add a line"
      description={`${quote.quote_number} · prices for ${quote.party.display_name} in ${quote.currency}`}
    >
      {/* State lives in the flow, so closing the drawer starts it afresh. */}
      {isOpen ? <AddFlow quote={quote} commands={commands} onDone={() => onOpenChange(false)} /> : null}
    </Drawer>
  );
}

function AddFlow({ quote, commands, onDone }: { quote: QuoteDetail; commands: QuoteCommands; onDone: () => void }) {
  const { permissionKeys } = useSession();
  const canCustom = permissionKeys.has("sales.custom_product.read");
  const [stage, setStage] = useState<Stage>(0);
  const [kind, setKind] = useState<Kind>("catalog");
  const [product, setProduct] = useState<ConfiguratorRow | null>(null);
  const [custom, setCustom] = useState<{ id: string; label: string } | null>(null);
  const [preset, setPreset] = useState<ManualPreset>("development");
  const [description, setDescription] = useState("");

  const kinds: RadioCardOption[] = [
    { value: "catalog", label: "Catalogue product", description: "Priced for this customer from the price list.", icon: "box" },
    ...(canCustom ? [{ value: "custom", label: "Custom product", description: "Made to a customer's specification, with its own price.", icon: "shapes" } satisfies RadioCardOption] : []),
    { value: "manual", label: "Charge", description: "Tooling, freight, samples and other one-off amounts.", icon: "receipt" },
  ];
  const stateOf = (index: number): StepState => (index < stage ? "done" : index === stage ? "current" : "todo");
  const itemLabel = kind === "manual" ? "Charge" : kind === "custom" ? "Custom product" : "Product";

  const add = async (name: string, parts: readonly (string | number | null)[], line: LineCreateRequest) => {
    const outcome = await commands.run(name, parts, (key) => addQuoteLine(quote, line, key), {
      done: "Line added",
      failed: "The line was not added",
      conflictMessage: CONFLICT,
    });
    if (outcome.ok) onDone();
  };

  return (
    <div className="flex flex-col gap-6">
      <Steps
        label="Steps to add a line"
        steps={[
          { id: "kind", label: "Kind", state: stateOf(0) },
          { id: "item", label: itemLabel, state: stateOf(1) },
          { id: "price", label: "Quantity and price", state: stateOf(2) },
        ]}
      />

      {stage === 0 ? (
        <div className="flex flex-col gap-5">
          <RadioCards
            label="What are you adding?"
            value={kind}
            onChange={(value) => setKind(value as Kind)}
            options={kinds}
          />
          <div className="flex justify-end">
            <Button variant="inverse" iconRight="arrowRight" onPress={() => setStage(1)}>
              Continue
            </Button>
          </div>
        </div>
      ) : null}

      {stage === 1 && kind === "catalog" ? (
        <ProductFinder
          quote={quote}
          onBack={() => setStage(0)}
          onChoose={(row) => {
            setProduct(row);
            setStage(2);
          }}
        />
      ) : null}

      {stage === 1 && kind === "custom" ? (
        <CustomFinder
          chosen={custom}
          onBack={() => setStage(0)}
          onChoose={(option) => {
            setCustom(option);
            setStage(2);
          }}
        />
      ) : null}

      {stage === 1 && kind === "manual" ? (
        <div className="flex flex-col gap-5">
          <Select
            label="Type of charge"
            options={MANUAL_PRESETS.map((id) => ({ value: id, label: PRESET_LABEL[id] ?? id }))}
            value={preset}
            onChange={(value) => setPreset(MANUAL_PRESETS.find((candidate) => candidate === value) ?? "miscellaneous")}
          />
          <TextField
            label="Wording on the quotation"
            optional
            value={description}
            onChange={setDescription}
            maxLength={500}
            help={`Left empty, the line reads "${PRESET_LABEL[preset]}".`}
          />
          <FlowButtons onBack={() => setStage(0)}>
            <Button variant="inverse" iconRight="arrowRight" onPress={() => setStage(2)}>
              Continue
            </Button>
          </FlowButtons>
        </div>
      ) : null}

      {stage === 2 && kind === "catalog" && product ? (
        <ProductPrice key={product.product.id} quote={quote} row={product} commands={commands} onBack={() => setStage(1)} onAdd={add} />
      ) : null}
      {stage === 2 && kind === "custom" && custom ? (
        <SimplePrice
          title={custom.label}
          subtitle="Custom product"
          currency={quote.currency}
          priceOptional
          priceHelp="Left empty, the custom product's own price in this currency is used."
          pending={commands.pending === "add_custom_line"}
          offline={Boolean(commands.offline)}
          onBack={() => setStage(1)}
          onAdd={(quantity, price) =>
            add("add_custom_line", [quote.version, custom.id, quantity, price], { line_type: "custom", custom_product_id: custom.id, quantity, ...(price ? { unit_price: price } : {}) })
          }
        />
      ) : null}
      {stage === 2 && kind === "manual" ? (
        <SimplePrice
          title={description.trim() || (PRESET_LABEL[preset] ?? preset)}
          subtitle="Charge"
          currency={quote.currency}
          initialQuantity="1"
          pending={commands.pending === "add_manual_line"}
          offline={Boolean(commands.offline)}
          onBack={() => setStage(1)}
          onAdd={(quantity, price) =>
            add("add_manual_line", [quote.version, preset, quantity, price, description.trim()], {
              line_type: "manual",
              manual_preset: preset,
              quantity,
              unit_price: price ?? "0",
              ...(description.trim() ? { description: description.trim() } : {}),
            })
          }
        />
      ) : null}
    </div>
  );
}

function FlowButtons({ onBack, children }: { onBack: () => void; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button variant="ghost" iconLeft="arrowLeft" onPress={onBack}>
        Back
      </Button>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Step 2, catalogue: search first, six narrowing filters, priced and paged results

function facts(row: ConfiguratorRow): string[] {
  const p = row.product;
  const size =
    p.size.diameter_mm != null ? `Ø ${p.size.diameter_mm} mm` : p.size.length_mm != null && p.size.width_mm != null ? `${p.size.length_mm} × ${p.size.width_mm} mm` : null;
  return [size, p.thickness_mm != null ? `${p.thickness_mm} mm thick` : null, [p.decor_no, p.decor_name].filter(Boolean).join(" ") || null, p.finish].filter(
    (part): part is string => Boolean(part),
  );
}

function ProductFinder({ quote, onBack, onChoose }: { quote: QuoteDetail; onBack: () => void; onChoose: (row: ConfiguratorRow) => void }) {
  const [filters, setFilters] = useState<ConfiguratorFilters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const result = useConfigurator(quote, filters, offset, true);
  const data = result.data;
  const setFilter = (change: Partial<ConfiguratorFilters>) => {
    setFilters((current) => ({ ...current, ...change }));
    setOffset(0);
  };
  // Enter takes the exact match only when the page shown answers the current search.
  const exact = data?.exact_match && !result.isPlaceholderData ? (data.items.find((row) => row.product.id === data.exact_match) ?? null) : null;
  const range = data ? pageLabel(data) : null;
  const active = activeFilterCount(filters);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          className="min-w-0 flex-1 basis-56"
          label="Search the catalogue"
          placeholder="Key, name, decor, size or thickness"
          value={filters.q}
          onChange={(q) => setFilter({ q })}
          onSubmit={() => (exact ? onChoose(exact) : undefined)}
          isPending={result.isFetching}
          glass={false}
          autoFocus
        />
        <Button variant="secondary" iconLeft="filter" aria-expanded={showFilters} onPress={() => setShowFilters((open) => !open)}>
          {active > 0 ? `Filters · ${active}` : "Filters"}
        </Button>
      </div>
      {showFilters ? (
        <fieldset className="rise-plain grid grid-cols-1 gap-3 sm:grid-cols-2">
          <legend className="sr-only">Narrow the catalogue</legend>
          {CONFIGURATOR_FILTERS.map(({ key, facet }) => (
            <Select
              key={key}
              size="sm"
              label={FILTER_LABEL[key] ?? key}
              options={filterOptions(data?.facets[facet] ?? [], filters[key], "Any").map((option) => ({
                value: option.id,
                label: option.detail ? `${option.label} · ${option.detail}` : option.label,
              }))}
              value={filters[key] ?? ANY}
              onChange={(value) => setFilter({ [key]: value === ANY ? null : value })}
            />
          ))}
        </fieldset>
      ) : null}
      {active > 0 || filters.q ? (
        <div>
          <Button variant="ghost" size="sm" iconLeft="x" onPress={() => setFilter(EMPTY_FILTERS)}>
            Clear search and filters
          </Button>
        </div>
      ) : null}

      <section aria-label="Matching products" aria-busy={result.isFetching} className="flex flex-col gap-3">
        {result.isError && !data ? (
          <ErrorBlock error={result.error} what="Matching products" onRetry={() => void result.refetch()} />
        ) : !data ? (
          <SkeletonRows rows={4} columns={2} />
        ) : data.items.length === 0 ? (
          <EmptyState compact icon="search" title="No product matches" text="Try fewer filters, or a shorter part of the key or name." />
        ) : (
          <ol className="flex flex-col">
            {data.items.map((row) => (
              <li key={row.product.id} className="hairline-top flex items-start justify-between gap-4 py-4 first:border-t-0 first:pt-0" data-product-key={row.product.product_key}>
                <div className="flex min-w-0 flex-col gap-1">
                  <p className="t-label flex flex-wrap items-center gap-2 text-ink">
                    {row.product.product_name}
                    {row.product.id === data.exact_match ? (
                      <Badge tone="leaf" size="sm">
                        Exact match
                      </Badge>
                    ) : null}
                  </p>
                  <Code>{row.product.display_sku || row.product.product_key}</Code>
                  {facts(row).length > 0 ? <p className="t-caption text-ink-3">{facts(row).join(" · ")}</p> : null}
                  <p className="t-caption text-ink-3">{row.packaging_summary ?? "No packaging recorded"}</p>
                </div>
                <div className="flex flex-none flex-col items-end gap-2">
                  <RowPrice row={row} />
                  <Button variant="secondary" size="sm" aria-label={`Choose ${row.product.product_name}`} onPress={() => onChoose(row)}>
                    Choose
                  </Button>
                </div>
              </li>
            ))}
          </ol>
        )}
        {range && range.total > CONFIGURATOR_PAGE_SIZE ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="t-caption lk-tnum text-ink-3" aria-live="polite">
              {range.from} to {range.to} of {range.total}
            </p>
            <Pagination
              label="Result pages"
              page={Math.floor(offset / CONFIGURATOR_PAGE_SIZE) + 1}
              pages={Math.ceil(range.total / CONFIGURATOR_PAGE_SIZE)}
              onChange={(page) => setOffset((page - 1) * CONFIGURATOR_PAGE_SIZE)}
            />
          </div>
        ) : null}
      </section>
      <FlowButtons onBack={onBack} />
    </div>
  );
}

function RowPrice({ row }: { row: ConfiguratorRow }) {
  const price = row.price;
  if (!price) return null; // no permission to read prices: the row is still listed
  if (!price.unit_price) {
    return (
      <Badge tone="amber" size="sm">
        No price for this customer
      </Badge>
    );
  }
  return (
    <div className="flex flex-col items-end">
      <span className="t-stat-sm text-ink">
        <UnitPrice amount={price.unit_price.amount} currency={price.unit_price.currency} />
      </span>
      <span className="t-caption text-ink-3">
        {price.unit_code ? `per ${price.unit_code}` : ""}
        {price.converted_with_fx ? `${price.unit_code ? " · " : ""}converted` : ""}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Step 2, custom product

function CustomFinder({ chosen, onBack, onChoose }: { chosen: { id: string; label: string } | null; onBack: () => void; onChoose: (option: { id: string; label: string }) => void }) {
  const [text, setText] = useState(chosen?.label ?? "");
  const [picked, setPicked] = useState(chosen);
  const [error, setError] = useState(false);
  const q = useDebouncedValue(text.trim(), 250);
  const search = useQuery({
    queryKey: queryKeys.sales.customProducts({ q, status: null, scope: "all", offset: 0 }),
    queryFn: ({ signal }) => fetchCustomProducts({ q, scope: "all" }, signal),
    enabled: q.length >= 2,
    staleTime: 30_000,
  });
  const options = [
    ...(picked ? [picked] : []),
    ...(search.data?.items ?? [])
      .filter((item) => item.id !== picked?.id && item.status !== "rejected" && item.status !== "converted_to_standard")
      .map((item) => ({ id: item.id, label: `${item.custom_code} · ${item.product_name}` })),
  ];
  return (
    <div className="flex flex-col gap-5">
      <ComboBox
        label="Custom product"
        placeholder="Name or CP code"
        items={options}
        inputValue={text}
        onInputChange={setText}
        selectedKey={picked?.id ?? null}
        onSelectionChange={(id) => {
          const option = options.find((candidate) => candidate.id === id) ?? null;
          setPicked(option);
          setError(false);
          if (option) setText(option.label);
        }}
        isLoading={search.isFetching}
        emptyText={text.trim().length < 2 ? "Type at least two letters" : "No custom product matches"}
        isRequired
        help="Rejected products and those already in the catalogue are left out."
        error={error ? "Choose the custom product to quote." : undefined}
      />
      <FlowButtons onBack={onBack}>
        <Button variant="inverse" iconRight="arrowRight" onPress={() => (picked ? onChoose(picked) : setError(true))}>
          Continue
        </Button>
      </FlowButtons>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Step 3: quantity and price

function ProductPrice({
  quote,
  row,
  commands,
  onBack,
  onAdd,
}: {
  quote: QuoteDetail;
  row: ConfiguratorRow;
  commands: QuoteCommands;
  onBack: () => void;
  onAdd: (name: string, parts: readonly (string | number | null)[], line: LineCreateRequest) => Promise<void>;
}) {
  const { permissionKeys } = useSession();
  const canOverride = permissionKeys.has("sales.quote_price.override");
  const listed = row.price?.unit_price?.amount ?? null;
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState(listed ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<PickError | null>(null);
  const advisories = pickAdvisories(row, quantity || null, price || null);
  const recommended = row.recommendation?.quantity?.value ?? "";
  const p = row.product;

  const submit = async () => {
    const plan = pickLine(row, { quantity: quantity || null, unitPrice: canOverride ? price || null : null, reason });
    if (!plan.ok) {
      setError(plan.error);
      return;
    }
    setError(null);
    await onAdd("add_line", [quote.version, p.id, quantity, plan.line.unit_price ?? null], plan.line);
  };

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4">
        <div className="flex flex-col gap-1">
          <p className="t-h4 text-ink">{p.product_name}</p>
          <Code>{p.display_sku || p.product_key}</Code>
          {facts(row).length > 0 ? <p className="t-caption text-ink-3">{facts(row).join(" · ")}</p> : null}
        </div>
        <dl className="hairline-top grid grid-cols-2 gap-3 pt-3">
          <div className="flex flex-col gap-0.5">
            <dt className="t-caption text-ink-3">Price for this customer</dt>
            <dd className="t-stat-sm text-ink">{row.price?.unit_price ? <UnitPrice amount={row.price.unit_price.amount} currency={row.price.unit_price.currency} /> : "None yet"}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="t-caption text-ink-3">Packaging</dt>
            <dd className="t-body-sm text-ink">{row.packaging_summary ?? "Not recorded"}</dd>
          </div>
        </dl>
        {row.recommendation?.label ? <p className="t-caption text-ink-3">{row.recommendation.label}</p> : null}
        {row.price && !row.price.unit_price ? <p className="t-caption text-ink-3">{row.price.explanation}</p> : null}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <DecimalField
          label="Quantity"
          value={quantity}
          onChange={setQuantity}
          suffix={p.unit_of_sale ?? undefined}
          isRequired
          error={error === "quantity" ? "Enter a quantity above zero." : undefined}
        />
        <DecimalField
          label="Unit price"
          value={price}
          onChange={setPrice}
          prefix={quote.currency}
          maxFractionDigits={4}
          isDisabled={!canOverride}
          help={canOverride ? undefined : "Changing the price needs the price override permission."}
          error={error === "price" ? "Enter a price of zero or more." : undefined}
        />
      </div>
      {advisories.includes("price_differs") ? (
        <TextField
          label="Why does the price differ?"
          value={reason}
          onChange={setReason}
          maxLength={500}
          isRequired
          help="The approver reads this before the quotation can be sent."
          error={error === "reason" ? "Say why the price differs from the customer's price." : undefined}
        />
      ) : null}
      {advisories.length > 0 ? (
        <div className="flex flex-col gap-2" aria-live="polite">
          {advisories.includes("below_recommendation") ? (
            <Banner tone="amber">The quantity is below the recommended order quantity ({recommended}).</Banner>
          ) : null}
          {advisories.includes("price_differs") ? <Banner tone="amber">A changed price sends the quotation for approval before it can be sent.</Banner> : null}
          {advisories.includes("unpriced") ? <Banner tone="amber">There is no price for this customer. The line is added without one and the total stays incomplete.</Banner> : null}
        </div>
      ) : null}
      <FlowButtons onBack={onBack}>
        <Button type="submit" loading={commands.pending === "add_line"} isDisabled={Boolean(commands.offline)}>
          Add to quotation
        </Button>
      </FlowButtons>
    </form>
  );
}

function SimplePrice({
  title,
  subtitle,
  currency,
  initialQuantity = "",
  priceOptional = false,
  priceHelp,
  pending,
  offline,
  onBack,
  onAdd,
}: {
  title: string;
  subtitle: string;
  currency: string;
  initialQuantity?: string;
  priceOptional?: boolean;
  priceHelp?: string;
  pending: boolean;
  offline: boolean;
  onBack: () => void;
  onAdd: (quantity: string, price: string | null) => Promise<void>;
}) {
  const [quantity, setQuantity] = useState(initialQuantity);
  const [price, setPrice] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const quantityOk = positive(quantity);
  const priceOk = price === "" ? priceOptional : isDecimalStr(price);
  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted(true);
        if (quantityOk && priceOk) void onAdd(quantity, price || null);
      }}
    >
      <div className="flex flex-col gap-0.5 rounded-md border border-line bg-surface p-4">
        <span className="t-caption text-ink-3">{subtitle}</span>
        <span className="t-h4 text-ink">{title}</span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <DecimalField label="Quantity" value={quantity} onChange={setQuantity} isRequired error={submitted && !quantityOk ? "Enter a quantity above zero." : undefined} />
        <DecimalField
          label="Price per unit"
          value={price}
          onChange={setPrice}
          prefix={currency}
          maxFractionDigits={4}
          optional={priceOptional}
          isRequired={!priceOptional}
          help={priceHelp}
          error={submitted && !priceOk ? "Enter the price per unit." : undefined}
        />
      </div>
      <FlowButtons onBack={onBack}>
        <Button type="submit" loading={pending} isDisabled={offline}>
          Add to quotation
        </Button>
      </FlowButtons>
    </form>
  );
}
