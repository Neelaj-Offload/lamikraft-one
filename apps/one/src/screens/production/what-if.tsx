"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { fetchWarehouses } from "@/features/inventory/api";
import { fetchBoms, fetchWorkCentres, runSimulation, type FeasibilityRead, type SimulationRequest } from "@/features/production/api";
import { useProductSearch } from "@/features/sales/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session/context";
import { MAX_CHANGES, MAX_CHECKS, simulationBody, type CapacityRow, type CheckRow, type StockRow } from "~/data/production";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  ComboBox,
  DatePicker,
  DecimalField,
  EmptyState,
  GlassPanel,
  IconButton,
  IntegerField,
  Qty,
  Select,
  SkeletonText,
  type SelectOption,
} from "~/ui";
import { Outcome } from "./feasibility";
import { PATHS, ProductionNav, stagger, useCanOpen } from "./parts";

const DEFAULT_WAREHOUSE = "default";

/**
 * What-if: up to five products, checked today and again with a change in stock or capacity.
 * The server runs the feasibility engine under a read-only guard, so nothing is reserved, posted
 * or saved, and a run is safe to repeat. Offered only to people who may run simulations.
 */
export function WhatIf() {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has("production.simulation.run");
  return (
    <Page>
      <PageHeader
        eyebrow="Production"
        title="What-if"
        lead="Try a change in stock or capacity and see whether the answer moves. Nothing is reserved, posted or saved."
      />
      <ProductionNav current="whatIf" />
      {allowed ? (
        <Planner />
      ) : (
        <GlassPanel padding="lg" className="rise">
          <NotPermitted what="Running simulations" />
        </GlassPanel>
      )}
    </Page>
  );
}

interface ProductChoice {
  id: string;
  key: string;
  name: string;
  uom: string | null;
}

function Planner() {
  const canOpen = useCanOpen();
  const boms = useQuery({ queryKey: queryKeys.production.boms({ status: "approved" }), queryFn: ({ signal }) => fetchBoms({}, signal) });
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const centres = useQuery({ queryKey: queryKeys.production.workCentres(), queryFn: ({ signal }) => fetchWorkCentres(signal) });

  const products = useMemo(() => {
    const seen = new Map<string, ProductChoice>();
    for (const bom of boms.data?.items ?? []) {
      if (bom.status === "approved") seen.set(bom.product.id, { id: bom.product.id, key: bom.product.product_key, name: bom.product.name, uom: bom.product.stock_uom_code });
    }
    return [...seen.values()];
  }, [boms.data]);
  const warehouseOptions: SelectOption[] = useMemo(
    () => [{ value: DEFAULT_WAREHOUSE, label: "Default warehouse" }, ...(warehouses.data ?? []).map((house) => ({ value: house.id, label: house.name, description: house.code }))],
    [warehouses.data],
  );
  const centreOptions: SelectOption[] = useMemo(() => (centres.data ?? []).map((centre) => ({ value: centre.id, label: centre.name, description: centre.code })), [centres.data]);

  const nextKey = useRef(1);
  const newKey = () => nextKey.current++;
  const [checks, setChecks] = useState<CheckRow[]>(() => [{ key: 0, product: null, quantity: "", needBy: null, warehouse: null }]);
  const [stock, setStock] = useState<StockRow[]>([]);
  const [capacity, setCapacity] = useState<CapacityRow[]>([]);
  const [submitted, setSubmitted] = useState<SimulationRequest | null>(null);
  const [attempted, setAttempted] = useState(false);
  const body = simulationBody(checks, stock, capacity);
  const stale = submitted !== null && JSON.stringify(body) !== JSON.stringify(submitted);

  const patchCheck = (key: number, patch: Partial<CheckRow>) => setChecks((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  const patchStock = (key: number, patch: Partial<StockRow>) => setStock((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  const patchCapacity = (key: number, patch: Partial<CapacityRow>) => setCapacity((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  if (boms.isPending) return <LoadingBlock lines={6} label="Loading the products that can be checked" />;
  if (boms.isError) return <ErrorBlock error={boms.error} what="The products that can be checked" onRetry={() => void boms.refetch()} />;
  if (products.length === 0) {
    return (
      <GlassPanel padding="lg" className="rise">
        <EmptyState
          icon="layers"
          title="Nothing to simulate yet"
          text="A product needs an approved bill of materials and routing before it can be checked."
          actions={
            canOpen(PATHS.boms) ? (
              <ButtonLink href={PATHS.boms} variant="secondary" iconRight="arrowRight">
                See bills of materials
              </ButtonLink>
            ) : undefined
          }
        />
      </GlassPanel>
    );
  }

  const run = () => {
    if (!body) {
      setAttempted(true);
      return;
    }
    setAttempted(false);
    setSubmitted(body);
  };

  const productOptions: SelectOption[] = products.map((product) => ({ value: product.id, label: product.name, description: product.key }));

  return (
    <>
      <Panel step={1} title="What to check" text="The products to make, how many and by when. Up to five at a time." index={1}>
        <ol className="flex flex-col">
          {checks.map((check, index) => {
            const uom = products.find((product) => product.id === check.product)?.uom ?? undefined;
            const show = attempted && !body;
            return (
              <li key={check.key} className={cx("grid min-w-0 grid-cols-1 items-start gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto]", index > 0 && "border-t border-line pt-5 mt-5")}>
                <Select
                  label="Product"
                  placeholder="Choose a product"
                  options={productOptions}
                  value={check.product}
                  onChange={(value) => patchCheck(check.key, { product: value })}
                  isRequired
                  error={show && !check.product ? "Choose a product." : undefined}
                />
                <DecimalField
                  label="Quantity"
                  value={check.quantity}
                  onChange={(value) => patchCheck(check.key, { quantity: value })}
                  maxFractionDigits={6}
                  suffix={uom}
                  isRequired
                  error={show && !check.quantity ? "Say how many." : undefined}
                />
                <DatePicker label="Needed by" value={check.needBy} onChange={(value) => patchCheck(check.key, { needBy: value })} isRequired error={show && !check.needBy ? "Choose a date." : undefined} />
                <Select
                  label="Warehouse"
                  options={warehouseOptions}
                  value={check.warehouse ?? DEFAULT_WAREHOUSE}
                  onChange={(value) => patchCheck(check.key, { warehouse: value === DEFAULT_WAREHOUSE ? null : value })}
                />
                {checks.length > 1 ? (
                  <RemoveButton label={`Remove product ${index + 1}`} onPress={() => setChecks((rows) => rows.filter((row) => row.key !== check.key))} />
                ) : (
                  <span aria-hidden className="hidden lg:block lg:w-11" />
                )}
              </li>
            );
          })}
        </ol>
        {checks.length < MAX_CHECKS ? (
          <div>
            <Button variant="secondary" size="sm" iconLeft="plus" onPress={() => setChecks((rows) => [...rows, { key: newKey(), product: null, quantity: "", needBy: null, warehouse: null }])}>
              Add another product
            </Button>
          </div>
        ) : null}
      </Panel>

      <Panel step={2} title="The change to try" text="Leave it empty to see today's answer twice." index={2}>
        <SubSection title="Stock" text="Add or take away free stock. A negative change takes it away.">
          {stock.map((row, index) => (
            <StockChangeRow
              key={row.key}
              row={row}
              index={index}
              warehouses={warehouseOptions}
              onChange={(patch) => patchStock(row.key, patch)}
              onRemove={() => setStock((rows) => rows.filter((candidate) => candidate.key !== row.key))}
            />
          ))}
          {stock.length < MAX_CHANGES ? (
            <div>
              <Button variant="secondary" size="sm" iconLeft="plus" onPress={() => setStock((rows) => [...rows, { key: newKey(), product: null, text: "", warehouse: null, delta: "" }])}>
                Add a stock change
              </Button>
            </div>
          ) : null}
        </SubSection>

        <SubSection title="Capacity" text="Replace a work centre's machine count, or add minutes to each of its working days." divided>
          {centres.isError ? <ErrorBlock error={centres.error} what="Work centres" onRetry={() => void centres.refetch()} /> : null}
          {capacity.map((row, index) => (
            <div key={row.key} className="grid min-w-0 grid-cols-1 items-start gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
              <Select
                label="Work centre"
                placeholder={centres.isPending ? "Loading work centres" : "Choose a work centre"}
                options={centreOptions}
                value={row.workCentre}
                onChange={(value) => patchCapacity(row.key, { workCentre: value })}
                isDisabled={centres.isPending}
              />
              <IntegerField label="Machines" optional minValue={0} value={row.machines} onChange={(value) => patchCapacity(row.key, { machines: value })} />
              <IntegerField label="Extra minutes a day" optional step={30} value={row.extraMinutes} onChange={(value) => patchCapacity(row.key, { extraMinutes: value })} />
              <RemoveButton label={`Remove capacity change ${index + 1}`} onPress={() => setCapacity((rows) => rows.filter((candidate) => candidate.key !== row.key))} />
            </div>
          ))}
          {capacity.length < MAX_CHANGES ? (
            <div>
              <Button variant="secondary" size="sm" iconLeft="plus" onPress={() => setCapacity((rows) => [...rows, { key: newKey(), workCentre: null, machines: null, extraMinutes: null }])}>
                Add a capacity change
              </Button>
            </div>
          ) : null}
        </SubSection>
      </Panel>

      <div className="rise flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center" style={stagger(3)}>
        <Button iconLeft="play" onPress={run}>
          Run the simulation
        </Button>
        {attempted && !body ? (
          <p className="t-body-sm text-ember-text" role="alert">
            Fill in a product, a quantity and a date for at least one row.
          </p>
        ) : (
          <p className="t-body-sm text-ink-3">Read-only. Run it as often as you like.</p>
        )}
      </div>

      {submitted ? <Results body={submitted} stale={stale} /> : null}
    </>
  );
}

function Panel({ step, title, text, index, children }: { step: number; title: string; text: string; index: number; children: ReactNode }) {
  return (
    <GlassPanel padding="lg" className="rise flex min-w-0 flex-col gap-5" style={stagger(index)}>
      <div className="flex min-w-0 items-start gap-4">
        <span className="t-label lk-tnum flex h-8 w-8 flex-none items-center justify-center rounded-pill border border-line-strong text-ink-2" aria-hidden>
          {step}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3 text-ink">{title}</h2>
          <p className="t-body-sm text-ink-3">{text}</p>
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-5">{children}</div>
    </GlassPanel>
  );
}

function SubSection({ title, text, divided = false, children }: { title: string; text: string; divided?: boolean; children: ReactNode }) {
  return (
    <section aria-label={title} className={cx("flex min-w-0 flex-col gap-4", divided && "border-t border-line pt-5")}>
      <div className="flex flex-col gap-1">
        <h3 className="t-h4 text-ink">{title}</h3>
        <p className="t-body-sm text-ink-3">{text}</p>
      </div>
      {children}
    </section>
  );
}

function RemoveButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <div className="flex sm:pt-7">
      <IconButton icon="trash" label={label} variant="ghost" onPress={onPress} />
    </div>
  );
}

function StockChangeRow({
  row,
  index,
  warehouses,
  onChange,
  onRemove,
}: {
  row: StockRow;
  index: number;
  warehouses: readonly SelectOption[];
  onChange: (patch: Partial<StockRow>) => void;
  onRemove: () => void;
}) {
  const search = useProductSearch(row.text);
  const options = [...(row.product ? [row.product] : []), ...(search.data ?? []).filter((product) => product.id !== row.product?.id)];
  const short = row.text.trim().length < 2;
  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_minmax(0,1fr)_auto]">
      <ComboBox
        label="Component or product"
        placeholder="Type 2 letters or more"
        emptyText={short ? "Type at least 2 letters to search." : "No product matches. Try the product key."}
        items={options.map((product) => ({ id: product.id, label: product.product_name, description: product.product_key }))}
        inputValue={row.text}
        onInputChange={(text) => onChange({ text })}
        selectedKey={row.product?.id ?? null}
        onSelectionChange={(id) => {
          const found = options.find((product) => product.id === id) ?? null;
          onChange({ product: found, text: found ? found.product_name : row.text });
        }}
        isLoading={search.isFetching}
      />
      <Select
        label="Warehouse"
        options={warehouses}
        value={row.warehouse ?? DEFAULT_WAREHOUSE}
        onChange={(value) => onChange({ warehouse: value === DEFAULT_WAREHOUSE ? null : value })}
      />
      <DecimalField label="Change in stock" value={row.delta} onChange={(delta) => onChange({ delta })} allowNegative maxFractionDigits={6} />
      <RemoveButton label={`Remove stock change ${index + 1}`} onPress={onRemove} />
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Results

function Results({ body, stale }: { body: SimulationRequest; stale: boolean }) {
  const query = useQuery({ queryKey: queryKeys.production.simulation(body), queryFn: ({ signal }) => runSimulation(body, signal), staleTime: 60_000 });
  return (
    <GlassPanel
      padding="lg"
      className="rise flex min-w-0 flex-col gap-6"
      eyebrow="Result"
      title="Today, and with the change"
      titleAs="h2"
      action={
        <Badge tone="cobalt" icon="lock">
          Read-only
        </Badge>
      }
    >
      {query.isPending ? (
        <div role="status" aria-label="Running the simulation" className="flex flex-col gap-4">
          <SkeletonText lines={4} />
        </div>
      ) : query.isError ? (
        <ErrorBlock error={query.error} what="The simulation" onRetry={() => void query.refetch()} />
      ) : (
        <>
          {query.data.label ? <p className="t-body text-ink-2">{query.data.label}</p> : null}
          {stale ? (
            <Banner tone="amber" title="The inputs changed since this run.">
              Run the simulation again to see what they do.
            </Banner>
          ) : null}
          <div className="flex min-w-0 flex-col">
            {query.data.baseline.map((baseline, index) => (
              <Comparison key={`${baseline.product.id}-${index}`} baseline={baseline} scenario={query.data.scenario[index] ?? null} first={index === 0} />
            ))}
          </div>
        </>
      )}
    </GlassPanel>
  );
}

function Comparison({ baseline, scenario, first }: { baseline: FeasibilityRead; scenario: FeasibilityRead | null; first: boolean }) {
  const changed = scenario !== null && (scenario.outcome !== baseline.outcome || scenario.earliest_completion !== baseline.earliest_completion);
  return (
    <section aria-label={`${baseline.product.name}, ${baseline.product.product_key}`} className={cx("flex min-w-0 flex-col gap-4", !first && "mt-6 border-t border-line pt-6")}>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <h3 className="t-h4 text-ink">{baseline.product.name}</h3>
        <Code className="t-code-sm text-ink-3">{baseline.product.product_key}</Code>
        <span className="t-body-sm text-ink-2">
          <Qty value={{ value: baseline.quantity, uom: baseline.uom_code }} />
        </span>
        {changed ? (
          <Badge tone="amber" icon="zap" size="sm">
            The answer changes
          </Badge>
        ) : (
          <Badge size="sm" outline>
            Same answer
          </Badge>
        )}
      </div>
      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
        <GlassPanel variant="outline" padding="md" className="min-w-0">
          <p className="t-overline mb-3 text-ink-3">Today</p>
          <Outcome result={baseline} />
        </GlassPanel>
        {scenario ? (
          <GlassPanel variant="solid" padding="md" className={cx("min-w-0", changed && "border-amber")}>
            <p className="t-overline mb-3 text-ink-3">With the change</p>
            <Outcome result={scenario} />
          </GlassPanel>
        ) : null}
      </div>
    </section>
  );
}
