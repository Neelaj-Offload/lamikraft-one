"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchRequisitions, PAGE_SIZE, REQUISITION_STATUSES, type RequisitionSummary } from "@/features/procurement/api";
import { requisitionListHref, type RequisitionListState } from "@/features/procurement/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Button, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, type Column } from "~/ui";
import { count, requisitionStatus } from "./labels";
import { ListFooter, PurchasingSwitch, stagger, StatusBadge } from "./parts";
import { RequisitionNew } from "./requisition-new";
import { asRoute } from "./views";

const COLUMNS: Column<RequisitionSummary>[] = [
  {
    key: "number",
    header: "Requisition",
    primary: true,
    cell: (r) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{r.requisition_number}</Code>
        <span className="t-caption text-ink-3">{count(r.line_count, "line", "lines")}</span>
      </span>
    ),
  },
  {
    key: "warehouse",
    header: "For",
    cell: (r) => (
      <span className="block truncate text-ink" title={`${r.warehouse.code} · ${r.warehouse.name}`}>
        {r.warehouse.name}
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (r) => <StatusBadge look={requisitionStatus(r.status)} /> },
  { key: "required", header: "Needed by", cell: (r) => <DateText value={r.required_by} style="business" /> },
  { key: "owner", header: "Raised by", hideOnMobile: true, cell: (r) => r.owner.display_name ?? "" },
  { key: "created", header: "Raised", hideOnMobile: true, cell: (r) => <DateText value={r.created_at} style="dayTime" /> },
];

/** Requisitions: what needs buying, for which warehouse and by when. Status and page live in the URL. */
export function RequisitionList({ state }: { state: RequisitionListState }) {
  const { permissionKeys } = useSession();
  const canCreate = permissionKeys.has("procurement.requisition.create");
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const query = useQuery({
    queryKey: queryKeys.procurement.requisitions({ status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchRequisitions(state, signal),
  });
  const href = (next: Partial<RequisitionListState>) => asRoute(requisitionListHref({ ...state, offset: 0, ...next }));
  const known = REQUISITION_STATUSES.find((status) => status === state.status) ?? null;
  const raise = () => {
    setAttempt((n) => n + 1);
    setOpen(true);
  };
  const raiseButton = canCreate ? (
    <Button iconLeft="plus" onPress={raise}>
      Raise requisition
    </Button>
  ) : null;

  return (
    <Page>
      <PageHeader eyebrow="Purchasing" title="Requisitions" lead="What needs buying, for which warehouse and by when. An approved requisition becomes a purchase order." actions={raiseButton} />

      <div className="rise flex min-w-0 flex-col gap-4" style={stagger(1)}>
        <PurchasingSwitch current="requisitions" />
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={known === null} scroll={false}>
            All
          </ChipLink>
          {REQUISITION_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={known === status} scroll={false}>
              {requisitionStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Requisitions" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Requisitions"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(r) => r.id}
            rowHref={(r) => asRoute(r.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              known ? (
                <EmptyState
                  compact
                  icon="filter"
                  title={`No requisitions are ${requisitionStatus(known).label.toLowerCase()}`}
                  text="Other requisitions may be at a different stage."
                  actions={
                    <ButtonLink href="/operations/purchasing/requisitions" variant="secondary" size="sm">
                      Show all requisitions
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="clipboard"
                  title="No requisitions yet"
                  text="Raise one when stock runs short or a job needs material. Once it is approved, it becomes a purchase order."
                  actions={
                    canCreate ? (
                      <Button variant="inverse" iconLeft="plus" onPress={raise}>
                        Raise the first one
                      </Button>
                    ) : null
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      <ListFooter page={query.data} noun="requisitions" label="Requisition pages" pageSize={PAGE_SIZE} hrefFor={(offset) => asRoute(requisitionListHref({ ...state, offset }))} />

      {canCreate ? <RequisitionNew key={attempt} isOpen={open} onOpenChange={setOpen} /> : null}
    </Page>
  );
}
