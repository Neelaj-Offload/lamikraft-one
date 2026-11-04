"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { ComboBox, Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { fetchWarehouses } from "@/features/inventory/api";
import { useProductSearch, type ProductOption } from "@/features/sales/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { productionMessages as m } from "@/messages/production";
import { fetchBoms, fetchWorkCentres, runSimulation, type FeasibilityRead, type SimulationRequest } from "./api";
import { OPERATIONS_LEADING, ProductionTabs } from "./common";
import { Outcome } from "./feasibility-panel";

const w = m.whatIf;
const MAX_CHECKS = 5;
const MAX_CHANGES = 10;

interface CheckRow {
  key: number;
  product: string | null;
  quantity: string | null;
  needBy: string | null;
  warehouse: string | null;
}

interface StockRow {
  key: number;
  product: ProductOption | null;
  text: string;
  warehouse: string | null;
  delta: string | null;
}

interface CapacityRow {
  key: number;
  workCentre: string | null;
  machines: string | null;
  extraMinutes: string | null;
}

let nextKey = 1;
const newKey = () => nextKey++;

/** The request the server sees: complete rows only, in the order shown. Pure (unit-tested). */
export function simulationBody(checks: readonly CheckRow[], stock: readonly StockRow[], capacity: readonly CapacityRow[]): SimulationRequest | null {
  const complete = checks.filter((c) => c.product && c.quantity && c.needBy);
  if (complete.length === 0) return null;
  const whole = (value: string | null) => (value != null && /^-?\d+$/.test(value.trim()) ? Number.parseInt(value, 10) : null);
  return {
    checks: complete.map((c) => ({ product_id: c.product!, quantity: c.quantity!, need_by: c.needBy!, warehouse_id: c.warehouse })),
    stock_changes: stock.filter((s) => s.product && s.delta && s.delta !== "0").map((s) => ({ product_id: s.product!.id, warehouse_id: s.warehouse, delta: s.delta! })),
    capacity_changes: capacity
      .filter((c) => c.workCentre && (whole(c.machines) != null || whole(c.extraMinutes) != null))
      .map((c) => ({ work_center_id: c.workCentre!, machine_count: whole(c.machines), extra_minutes_per_day: whole(c.extraMinutes) })),
  };
}

/**
 * What-if (`/operations/production/what-if`): baseline vs scenario for up to five products, with stock and capacity
 * overlays. The server runs the feasibility engine under a read-only guard (any write raises), so a run is safe to
 * repeat; results are cached per request body and the screen says when the form no longer matches the shown run.
 */
export function WhatIfScreen() {
  const { permissionKeys } = useSession();
  if (!permissionKeys.has("production.simulation.run")) return <PermissionDenied area={w.title} />;
  return <WhatIf />;
}

function WhatIf() {
  const boms = useQuery({ queryKey: queryKeys.production.boms({ status: "approved" }), queryFn: ({ signal }) => fetchBoms({}, signal) });
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const centres = useQuery({ queryKey: queryKeys.production.workCentres(), queryFn: ({ signal }) => fetchWorkCentres(signal) });
  const products = useMemo(() => {
    const seen = new Map<string, { id: string; label: string; uom: string | null }>();
    for (const b of boms.data?.items ?? []) {
      if (b.status === "approved") seen.set(b.product.id, { id: b.product.id, label: `${b.product.product_key} · ${b.product.name}`, uom: b.product.stock_uom_code });
    }
    return [...seen.values()];
  }, [boms.data]);
  const warehouseOptions = useMemo(() => (warehouses.data ?? []).map((x) => ({ id: x.id, label: `${x.code} · ${x.name}` })), [warehouses.data]);
  const [checks, setChecks] = useState<CheckRow[]>(() => [{ key: newKey(), product: null, quantity: null, needBy: null, warehouse: null }]);
  const [stock, setStock] = useState<StockRow[]>([]);
  const [capacity, setCapacity] = useState<CapacityRow[]>([]);
  const [submitted, setSubmitted] = useState<SimulationRequest | null>(null);
  const body = simulationBody(checks, stock, capacity);
  const stale = submitted !== null && JSON.stringify(body) !== JSON.stringify(submitted);

  const patchCheck = (key: number, patch: Partial<CheckRow>) => setChecks((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const patchStock = (key: number, patch: Partial<StockRow>) => setStock((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const patchCapacity = (key: number, patch: Partial<CapacityRow>) => setCapacity((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={w.title} intro={w.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <ProductionTabs current="whatIf" />
      {boms.isPending ? (
        <Loading label={m.masters.loading} />
      ) : boms.isError ? (
        <ErrorState error={boms.error} what={m.masters.loading} onRetry={() => void boms.refetch()} />
      ) : products.length === 0 ? (
        <EmptyState title={w.title}>{w.noProducts}</EmptyState>
      ) : (
        <>
          <SectionCard title={w.checksTitle} description={w.checksIntro}>
            <ul className="flex flex-col gap-4">
              {checks.map((c, index) => {
                const uom = products.find((p) => p.id === c.product)?.uom ?? undefined;
                return (
                  <li key={c.key} className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1.5fr_auto]">
                    <Select label={w.product} placeholder={w.productPlaceholder} options={products} value={c.product} onChange={(v) => patchCheck(c.key, { product: v })} isRequired />
                    <NumberField label={w.quantity} value={c.quantity} onChange={(v) => patchCheck(c.key, { quantity: v })} uom={uom} isRequired />
                    <DatePicker label={w.needBy} value={c.needBy} onChange={(v) => patchCheck(c.key, { needBy: v })} isRequired />
                    <Select label={w.warehouse} placeholder={w.defaultWarehouse} options={warehouseOptions} value={c.warehouse} onChange={(v) => patchCheck(c.key, { warehouse: v })} />
                    <Button variant="quiet" aria-label={w.removeRow(index + 1)} {...unavailableWhen(checks.length === 1 ? w.needOne : null)} onPress={() => setChecks((rows) => rows.filter((r) => r.key !== c.key))}>
                      {w.remove}
                    </Button>
                  </li>
                );
              })}
            </ul>
            {checks.length < MAX_CHECKS ? (
              <div className="mt-4">
                <Button onPress={() => setChecks((rows) => [...rows, { key: newKey(), product: null, quantity: null, needBy: null, warehouse: null }])}>{w.addCheck}</Button>
              </div>
            ) : null}
          </SectionCard>

          <SectionCard title={w.scenarioTitle} description={w.scenarioIntro}>
            <div className="flex flex-col gap-6">
              <section aria-label={w.stockTitle} className="flex flex-col gap-3">
                <h3 className="font-[650] text-ink">{w.stockTitle}</h3>
                <p className="text-sm text-ink-muted">{w.stockIntro}</p>
                {stock.map((s, index) => (
                  <StockChangeRow key={s.key} row={s} index={index} warehouses={warehouseOptions} onChange={(patch) => patchStock(s.key, patch)} onRemove={() => setStock((rows) => rows.filter((r) => r.key !== s.key))} />
                ))}
                {stock.length < MAX_CHANGES ? (
                  <div>
                    <Button onPress={() => setStock((rows) => [...rows, { key: newKey(), product: null, text: "", warehouse: null, delta: null }])}>{w.addStock}</Button>
                  </div>
                ) : null}
              </section>
              <section aria-label={w.capacityTitle} className="flex flex-col gap-3">
                <h3 className="font-[650] text-ink">{w.capacityTitle}</h3>
                <p className="text-sm text-ink-muted">{w.capacityIntro}</p>
                {capacity.map((c, index) => (
                  <div key={c.key} className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[2fr_1fr_1fr_auto]">
                    <Select
                      label={w.workCentre}
                      options={(centres.data ?? []).map((x) => ({ id: x.id, label: `${x.code} · ${x.name}` }))}
                      value={c.workCentre}
                      onChange={(v) => patchCapacity(c.key, { workCentre: v })}
                    />
                    <NumberField label={w.machines} value={c.machines} onChange={(v) => patchCapacity(c.key, { machines: v })} maxFractionDigits={0} />
                    <NumberField label={w.extraMinutes} value={c.extraMinutes} onChange={(v) => patchCapacity(c.key, { extraMinutes: v })} maxFractionDigits={0} allowNegative />
                    <Button variant="quiet" aria-label={w.removeRow(index + 1)} onPress={() => setCapacity((rows) => rows.filter((r) => r.key !== c.key))}>
                      {w.remove}
                    </Button>
                  </div>
                ))}
                {capacity.length < MAX_CHANGES ? (
                  <div>
                    <Button onPress={() => setCapacity((rows) => [...rows, { key: newKey(), workCentre: null, machines: null, extraMinutes: null }])}>{w.addCapacity}</Button>
                  </div>
                ) : null}
              </section>
            </div>
          </SectionCard>

          <div>
            <Button variant="primary" {...unavailableWhen(body ? null : w.needOne)} onPress={() => setSubmitted(body)}>
              {w.run}
            </Button>
          </div>
          {submitted ? <SimulationResults body={submitted} stale={stale} /> : null}
        </>
      )}
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
  warehouses: { id: string; label: string }[];
  onChange: (patch: Partial<StockRow>) => void;
  onRemove: () => void;
}) {
  const search = useProductSearch(row.text);
  const options = [...(row.product ? [row.product] : []), ...(search.data ?? []).filter((p) => p.id !== row.product?.id)];
  return (
    <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[2fr_1.5fr_1fr_auto]">
      <ComboBox
        label={w.stockProduct}
        placeholder={w.stockProductHint}
        emptyText={row.text.trim().length < 2 ? w.stockProductHint : w.stockNoProduct}
        options={options.map((p) => ({ id: p.id, label: p.product_name, detail: p.product_key }))}
        value={row.product?.id ?? null}
        inputValue={row.text}
        onInputChange={(text) => onChange({ text })}
        onChange={(id) => {
          const found = options.find((p) => p.id === id) ?? null;
          onChange({ product: found, text: found ? found.product_name : row.text });
        }}
      />
      <Select label={w.warehouse} placeholder={w.defaultWarehouse} options={warehouses} value={row.warehouse} onChange={(v) => onChange({ warehouse: v })} />
      <NumberField label={w.delta} value={row.delta} onChange={(v) => onChange({ delta: v })} allowNegative />
      <Button variant="quiet" aria-label={w.removeRow(index + 1)} onPress={onRemove}>
        {w.remove}
      </Button>
    </div>
  );
}

export function SimulationResults({ body, stale }: { body: SimulationRequest; stale: boolean }) {
  const query = useQuery({ queryKey: queryKeys.production.simulation(body), queryFn: ({ signal }) => runSimulation(body, signal), staleTime: 60_000 });
  if (query.isPending) return <Loading label={w.running} />;
  if (query.isError) return <ErrorState error={query.error} what={w.failed} onRetry={() => void query.refetch()} />;
  const data = query.data;
  return (
    <SectionCard title={w.resultsTitle} description={data.label} actions={<StatusPill tone="info">{w.readOnly}</StatusPill>}>
      <div className="flex flex-col gap-6">
        {stale ? <p className="rounded-md bg-surface-sunken p-3 text-sm text-ink">{w.stale}</p> : null}
        {data.baseline.map((base, i) => (
          <Comparison key={`${base.product.id}-${i}`} baseline={base} scenario={data.scenario[i] ?? null} />
        ))}
      </div>
    </SectionCard>
  );
}

function Comparison({ baseline, scenario }: { baseline: FeasibilityRead; scenario: FeasibilityRead | null }) {
  const changed = scenario !== null && (scenario.outcome !== baseline.outcome || scenario.earliest_completion !== baseline.earliest_completion);
  return (
    <section aria-label={baseline.product.product_key} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-[650] text-ink">
          <span className="font-mono">{baseline.product.product_key}</span> · {baseline.quantity} {baseline.uom_code}
        </h3>
        <StatusPill tone={changed ? "warning" : "neutral"}>{changed ? w.changed : w.unchanged}</StatusPill>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h4 className="text-sm font-[650] text-ink-muted">{w.baseline}</h4>
          <Outcome result={baseline} />
        </div>
        {scenario ? (
          <div className="flex flex-col gap-2">
            <h4 className="text-sm font-[650] text-ink-muted">{w.scenario}</h4>
            <Outcome result={scenario} />
          </div>
        ) : null}
      </div>
    </section>
  );
}
