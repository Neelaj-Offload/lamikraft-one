"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { createPackingList, fetchPackingLists, PACKING_STATUSES, PAGE_SIZE, type PackingListSummary } from "@/features/logistics/api";
import { packingListHref, type PackingListState } from "@/features/logistics/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { asRoute, FAILED, packingStatus, type OrderOption } from "~/data/dispatch";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, ButtonLink, ChipGroup, ChipLink, Code, DataTable, EmptyState, GlassPanel, Modal, PageSummary, Pagination, type Column } from "~/ui";
import { Decimal, DispatchSwitch, OrderPicker, PackingStatusBadge, stagger } from "./parts";

function columns(locale: string): Column<PackingListSummary>[] {
  return [
    {
      key: "list",
      header: "Packing list",
      primary: true,
      cell: (list) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label truncate text-ink" title={list.party_name}>
            {list.party_name}
          </span>
          <span className="t-caption text-ink-3">
            <Code>{list.packing_list_number}</Code> · order {list.order.number}
          </span>
        </span>
      ),
    },
    { key: "cartons", header: "Cartons", numeric: true, cell: (list) => <span className="t-label text-ink">{formatCount(list.total_cartons, locale)}</span> },
    { key: "cbm", header: "CBM", numeric: true, cell: (list) => <Decimal value={list.total_cbm} unit="m³" /> },
    { key: "gross", header: "Gross weight", numeric: true, hideOnMobile: true, cell: (list) => <Decimal value={list.total_gross_kg} unit="kg" /> },
    {
      key: "status",
      header: "Status",
      cell: (list) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <PackingStatusBadge status={list.status} />
          {list.is_stale ? (
            <Badge tone="amber" size="sm" icon="refresh">
              Packaging changed
            </Badge>
          ) : null}
          {list.totals_partial ? (
            <Badge tone="amber" size="sm" icon="alert">
              Partial totals
            </Badge>
          ) : null}
        </span>
      ),
    },
  ];
}

/** Packing lists: cartons, CBM and weights for an order, worked out from the catalogue packaging. */
export function PackingListList({ state }: { state: PackingListState }) {
  const { permissionKeys, zone } = useSession();
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.logistics.packingLists({ status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchPackingLists(state, signal),
  });
  const href = (next: Partial<PackingListState>) => asRoute(packingListHref({ ...state, offset: 0, ...next }));
  const canCreate = permissionKeys.has("logistics.packing_list.create");
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Dispatch", href: "/operations/dispatch" }, { label: "Packing lists" }]}
        title="Packing lists"
        lead="Cartons, inner packs, CBM and weights for each order, worked out from the catalogue packaging. Missing data is flagged, never guessed."
        actions={
          canCreate ? (
            <Button iconLeft="plus" onPress={() => setCreating(true)}>
              Create packing list
            </Button>
          ) : undefined
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <DispatchSwitch current="packing-lists" />
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
            All
          </ChipLink>
          {PACKING_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
              {packingStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Packing lists" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Packing lists"
            columns={columns(zone.locale)}
            rows={query.data?.items ?? []}
            rowKey={(list) => list.id}
            rowHref={(list) => asRoute(list.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              state.status ? (
                <EmptyState
                  compact
                  icon="search"
                  title={`No ${packingStatus(state.status).label.toLowerCase()} packing lists`}
                  text="No packing list has this status."
                  actions={
                    <ButtonLink href="/operations/dispatch/packing-lists" variant="secondary" size="sm">
                      Show all
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="box"
                  title="No packing lists yet"
                  text="Create one from a confirmed sales order. Cartons, CBM and weights come from the catalogue packaging."
                  actions={
                    canCreate ? (
                      <Button variant="inverse" iconLeft="plus" onPress={() => setCreating(true)}>
                        Create your first packing list
                      </Button>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="packing lists" />
          {total > limit ? (
            <Pagination
              label="Packing list pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(packingListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}

      {canCreate ? <CreatePackingListModal isOpen={creating} onOpenChange={setCreating} /> : null}
    </Page>
  );
}

/** Packs the order's open stock lines into a draft packing list. */
function CreatePackingListModal({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const formId = useId();
  const key = useMemo(() => queryKeys.logistics.all(), []);
  const { run, pending, offline } = useCommand<null>(key);
  const [order, setOrder] = useState<OrderOption | null>(null);
  const [error, setError] = useState<string | undefined>(undefined);

  const close = (open: boolean) => {
    if (open || pending === "pack") return;
    setOrder(null);
    setError(undefined);
    onOpenChange(false);
  };

  const submit = async () => {
    if (!order) {
      setError("Choose the sales order to pack.");
      return;
    }
    const list = await run("pack", (k) => createPackingList(order.id, k), { done: "Packing list created", failed: FAILED });
    if (list) {
      onOpenChange(false);
      router.push(asRoute(list.path));
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={close}
      size="sm"
      title="Create a packing list"
      description="Packs the order's open stock lines. Lines without packaging data are flagged for you to complete."
      actions={
        <>
          <Button variant="ghost" onPress={() => close(false)} isDisabled={pending === "pack"}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={pending === "pack"} isDisabled={Boolean(offline)}>
            Create packing list
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className="flex flex-col gap-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <OrderPicker
          value={order}
          onChange={(next) => {
            setOrder(next);
            if (next) setError(undefined);
          }}
          error={error}
        />
        {offline ? <p className="t-caption text-ink-3">You are offline. The packing list can be created once the connection is back.</p> : null}
      </form>
    </Modal>
  );
}
