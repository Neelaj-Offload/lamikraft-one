"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchInspections, INSPECTION_STATUSES, PAGE_SIZE, type InspectionSummary } from "@/features/quality/api";
import { inspectionListHref, type InspectionListState } from "@/features/quality/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { ListFooter, stagger, StatusBadge } from "~/screens/purchasing/parts";
import { asRoute } from "~/screens/purchasing/views";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, Qty, type Column } from "~/ui";
import { inspectionStatus, subjectLabel } from "./labels";

const COLUMNS: Column<InspectionSummary>[] = [
  {
    key: "number",
    header: "Inspection",
    primary: true,
    cell: (i) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{i.inspection_number}</Code>
        <span className="t-caption text-ink-3">
          Asked <DateText value={i.requested_at} style="dayTime" />
        </span>
      </span>
    ),
  },
  {
    key: "product",
    header: "Product",
    cell: (i) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={i.product.name}>
          {i.product.name}
        </span>
        <span className="t-caption lk-mono text-ink-3">{i.product.product_key}</span>
      </span>
    ),
  },
  {
    key: "subject",
    header: "From",
    cell: (i) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-ink">{subjectLabel(i.subject_type)}</span>
        <span className="t-caption truncate text-ink-3" title={i.subject_label}>
          {i.subject_label}
        </span>
      </span>
    ),
  },
  { key: "warehouse", header: "Warehouse", hideOnMobile: true, cell: (i) => <span title={i.warehouse.name}>{i.warehouse.code}</span> },
  { key: "quantity", header: "Quantity", numeric: true, cell: (i) => <Qty value={{ value: i.quantity, uom: i.unit }} className="t-label text-ink" /> },
  { key: "status", header: "Status", cell: (i) => <StatusBadge look={inspectionStatus(i.status)} /> },
];

/** Quality: goods held in QC, waiting ones first. The status filter and the page live in the URL. */
export function InspectionList({ state }: { state: InspectionListState }) {
  const query = useQuery({
    queryKey: queryKeys.quality.inspections({ status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchInspections(state, signal),
  });
  const known = INSPECTION_STATUSES.find((status) => status === state.status) ?? null;
  const href = (status: string | null) => asRoute(inspectionListHref({ status, offset: 0 }));

  return (
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Quality"
        lead="Goods held for inspection. What you accept is released to stock; what you reject moves to the rejected location."
      />

      <div className="rise min-w-0" style={stagger(1)}>
        <ChipGroup label="Filter inspections by status">
          {INSPECTION_STATUSES.map((status) => (
            <ChipLink key={status} href={href(status)} selected={known === status} scroll={false}>
              {inspectionStatus(status).label}
            </ChipLink>
          ))}
          <ChipLink href={href(null)} selected={known === null} scroll={false}>
            All inspections
          </ChipLink>
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Inspections" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Quality inspections"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(i) => i.id}
            rowHref={(i) => asRoute(i.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={<Empty status={known} />}
          />
        </GlassPanel>
      )}

      <ListFooter page={query.data} noun="inspections" label="Inspection pages" pageSize={PAGE_SIZE} hrefFor={(offset) => asRoute(inspectionListHref({ ...state, offset }))} />
    </Page>
  );
}

function Empty({ status }: { status: string | null }) {
  const all = (
    <ButtonLink href={asRoute(inspectionListHref({ status: null, offset: 0 }))} variant="secondary" size="sm">
      See every inspection
    </ButtonLink>
  );
  if (status === "pending") {
    return <EmptyState icon="checkCircle" title="Nothing waiting for inspection" text="Goods that need a quality check appear here the moment they are received." actions={all} />;
  }
  if (status) {
    return <EmptyState compact icon="filter" title={`No inspections are ${inspectionStatus(status).label.toLowerCase()}`} text="Other inspections may be at a different stage." actions={all} />;
  }
  return (
    <EmptyState
      icon="flask"
      title="No inspections yet"
      text="An inspection opens when goods that need QC are received, or when stock is put on hold."
      actions={
        <ButtonLink href="/operations/purchasing/receipts" variant="secondary" iconRight="arrowRight">
          See goods receipts
        </ButtonLink>
      }
    />
  );
}
