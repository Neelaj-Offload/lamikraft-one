"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { bomAction, copyBom, fetchBom, fetchCostRollups, runCostRollup, type BomRead, type CostRollupRead } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { asRoute, useProductionCommand } from "~/data/production";
import { Page } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, Code, DataTable, DateText, EmptyState, GlassPanel, Money, Qty, SkeletonText, Tabs, type Column } from "~/ui";
import { PATHS, Percent, RecordFailed, RecordLoading, stagger, ViewHeading } from "./parts";
import { VersionHeader } from "./version-record";
import { viewHref, type BomView } from "./views";

const FAILED = "That did not go through";

/** A bill of materials version: what one unit is made of, and what it costs to make. */
export function BomRecord({ bomId, view }: { bomId: string; view: BomView }) {
  const query = useQuery({ queryKey: queryKeys.production.bom(bomId), queryFn: ({ signal }) => fetchBom(bomId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the bill of materials" />;
  if (query.isError) return <RecordFailed error={query.error} what="This bill of materials" onRetry={() => void query.refetch()} backHref={PATHS.boms} backLabel="All bills of materials" />;
  return <Loaded bom={query.data} view={view} />;
}

function Loaded({ bom, view }: { bom: BomRead; view: BomView }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.production.bom(bom.id), [bom.id]);
  const { run, pending, offline } = useProductionCommand<BomRead>(key);
  const path = `${PATHS.boms}/${bom.id}`;
  const write = (record: BomRead) => record;

  return (
    <Page>
      <VersionHeader
        record={bom}
        list={{ label: "Bills of materials", href: PATHS.boms }}
        countLabel="Components"
        pending={pending}
        offline={Boolean(offline)}
        onApprove={async () => (await run("approve", (k) => bomAction(bom, "approve", k), { done: "Version approved", failed: FAILED, write })) !== null}
        onRetire={async (reason) => (await run("retire", (k) => bomAction(bom, "retire", k, reason), { done: "Version retired", failed: FAILED, write })) !== null}
        onCopy={() =>
          void run("copy", (k) => copyBom(bom, k), { done: "New draft version started", failed: FAILED }).then((created) => {
            if (created) router.push(asRoute(`${PATHS.boms}/${created.id}`));
          })
        }
      >
        <Tabs
          label="Views of this bill of materials"
          selectedKey={view}
          tabs={[
            { id: "components", label: "Components", count: bom.lines.length, href: asRoute(path) },
            { id: "cost", label: "Cost", href: asRoute(viewHref(path, "cost", "components")) },
          ]}
        />
      </VersionHeader>

      {view === "components" ? <ComponentsView bom={bom} /> : <CostView bom={bom} />}
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Components

type Line = BomRead["lines"][number];

function ComponentsView({ bom }: { bom: BomRead }) {
  const columns: Column<Line>[] = [
    { key: "line", header: "Line", numeric: true, width: "72px", hideOnMobile: true, cell: (line) => <span className="text-ink-3">{line.line_no}</span> },
    {
      key: "component",
      header: "Component",
      primary: true,
      cell: (line) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label text-ink">{line.component.name}</span>
          <span className="t-caption text-ink-3">
            <Code className="t-code-sm">{line.component.product_key}</Code>
            <span className="md:hidden"> · line {line.line_no}</span>
          </span>
        </span>
      ),
    },
    { key: "per", header: "Per unit", numeric: true, cell: (line) => <Qty value={{ value: line.qty_per, uom: line.uom_code }} className="t-label text-ink" /> },
    { key: "scrap", header: "Scrap allowance", numeric: true, mobileLabel: "Scrap", cell: (line) => <Percent value={line.scrap_pct} /> },
    {
      key: "notes",
      header: "Notes",
      mobileLabel: "Notes",
      cell: (line) =>
        line.is_sheet_material || line.alternate_for_line_no || line.has_approved_bom ? (
          <span className="flex flex-wrap gap-1.5">
            {line.is_sheet_material ? (
              <Badge tone="cobalt" size="sm" icon="layers">
                Sheet material
              </Badge>
            ) : null}
            {line.alternate_for_line_no ? (
              <Badge size="sm" outline icon="split">
                {`Can replace line ${line.alternate_for_line_no}`}
              </Badge>
            ) : null}
            {line.has_approved_bom ? (
              <Badge size="sm" outline icon="boxes">
                Has its own bill of materials
              </Badge>
            ) : null}
          </span>
        ) : (
          <span className="text-ink-3">None</span>
        ),
    },
  ];
  return (
    <div className="stack">
      <ViewHeading title="Components" text={`What goes into one unit of ${bom.product.name}, with the extra allowed for scrap.`} />
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Components of ${bom.product.product_key}, version ${bom.version_no}`}
          columns={columns}
          rows={bom.lines}
          rowKey={(line) => line.id}
          empty={<EmptyState compact icon="layers" title="This version has no components" text="A bill of materials needs at least one component before it can be approved." />}
        />
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Cost per unit

type CostLine = NonNullable<CostRollupRead["lines"]>[number];

const COST_COLUMNS: Column<CostLine>[] = [
  {
    key: "input",
    header: "Input",
    primary: true,
    cell: (line) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-label text-ink">{line.label}</span>
        <Code className="t-code-sm text-ink-3">{line.path}</Code>
      </span>
    ),
  },
  { key: "kind", header: "Kind", cell: (line) => (line.kind === "material" ? "Material" : "Operation") },
  { key: "quantity", header: "Quantity", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.uom_code }} /> },
  { key: "unit", header: "Unit cost", numeric: true, cell: (line) => <Money value={line.unit_cost} maxFractionDigits={4} /> },
  { key: "amount", header: "Amount", numeric: true, cell: (line) => <Money value={line.amount} maxFractionDigits={4} className="t-label text-ink" /> },
];

function CostView({ bom }: { bom: BomRead }) {
  const { permissionKeys } = useSession();
  const productId = bom.product.id;
  const key = useMemo(() => queryKeys.production.costRollups(productId), [productId]);
  const latest = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchCostRollups(productId, signal) });
  const { run, pending, offline } = useProductionCommand<null>(key);
  const [shown, setShown] = useState<CostRollupRead | null>(null);
  const rollup = shown ?? latest.data?.items[0] ?? null;
  const canRun = permissionKeys.has("production.cost_rollup.run");

  const rollUp = () =>
    void run("rollup", (k) => runCostRollup(productId, k), { done: "Cost rolled up", failed: "The cost was not rolled up" }).then((result) => {
      if (result) setShown(result);
    });

  const action = canRun ? (
    <Button variant="secondary" iconLeft="refresh" loading={pending === "rollup"} isDisabled={Boolean(offline)} onPress={rollUp}>
      Roll up cost
    </Button>
  ) : undefined;

  return (
    <div className="stack">
      <ViewHeading
        title="Cost per unit"
        text="Worked out from the approved bill of materials and routing. The same inputs always give the same answer; anything missing is listed and left out."
        action={rollup ? action : undefined}
      />
      {latest.isPending ? (
        <GlassPanel padding="lg" className="rise" aria-label="Loading the cost" role="status">
          <SkeletonText lines={4} />
        </GlassPanel>
      ) : latest.isError ? (
        <ErrorBlock error={latest.error} what="The cost" onRetry={() => void latest.refetch()} />
      ) : !rollup ? (
        <GlassPanel padding="lg" className="rise">
          <EmptyState
            icon="wallet"
            title="No cost worked out yet"
            text={canRun ? `Roll up the cost to see what one unit of ${bom.product.name} takes in material and operations.` : "Nobody has rolled up the cost of this product yet."}
            actions={action}
          />
        </GlassPanel>
      ) : (
        <CostResult rollup={rollup} />
      )}
    </div>
  );
}

function CostFigure({ label, value, lead = false }: { label: string; value: CostRollupRead["total"]; lead?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="t-overline text-ink-3">{label}</span>
      <Money value={value} maxFractionDigits={4} className={lead ? "t-stat-xl text-ink" : "t-stat text-ink-2"} />
    </div>
  );
}

function CostResult({ rollup }: { rollup: CostRollupRead }) {
  const complete = rollup.status === "complete";
  return (
    <>
      <GlassPanel padding="lg" className="rise flex flex-col gap-6" style={stagger(1)}>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {complete ? (
            <Badge tone="leaf" dot>
              Complete
            </Badge>
          ) : (
            <Badge tone="amber" icon="alert">
              Partial: some inputs are missing
            </Badge>
          )}
          {rollup.reused ? (
            <Badge size="sm" outline icon="history">
              Same inputs as last time
            </Badge>
          ) : null}
          <span className="t-body-sm text-ink-3">
            As of <DateText value={rollup.as_of} style="business" /> · in {rollup.currency}
            {rollup.computed_by?.display_name ? ` · by ${rollup.computed_by.display_name}` : ""}
          </span>
        </div>
        {rollup.total ? (
          <div className="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-3">
            <CostFigure label="Per unit" value={rollup.total} lead />
            <CostFigure label="Material" value={rollup.material_total} />
            <CostFigure label="Operations" value={rollup.operation_total} />
          </div>
        ) : (
          <p className="t-body text-ink-2">The figures are hidden. Seeing them needs the costing permission.</p>
        )}
        {rollup.missing_inputs.length > 0 ? (
          <div className="flex flex-col gap-2 border-t border-line pt-5">
            <h3 className="t-h4 text-ink">Left out of the total</h3>
            <ul className="flex flex-col gap-1.5">
              {rollup.missing_inputs.map((input) => (
                <li key={`${input.kind}-${input.ref_id ?? input.label}`} className="t-body-sm flex min-w-0 items-start gap-2 text-ink-2">
                  <Badge tone="amber" size="sm">
                    Missing
                  </Badge>
                  <span className="min-w-0">{input.label}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </GlassPanel>
      {rollup.lines && rollup.lines.length > 0 ? (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable label="What the cost is made of" columns={COST_COLUMNS} rows={rollup.lines} rowKey={(line) => `${line.path}-${line.label}`} />
        </GlassPanel>
      ) : null}
    </>
  );
}
