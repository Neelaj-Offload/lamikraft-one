"use client";

import { useMemo, useState } from "react";
import { PAGE_SIZE, releaseReservation, type ReservationRow, type Shortage } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { useSession } from "@/lib/session/context";
import { asRoute, reservationsKey, useCanOpen, useReservations, useShortages } from "~/data/stock";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { stagger, StatusBadge } from "~/screens/sales/quotations/parts";
import { Badge, Banner, Button, ButtonLink, ChipGroup, ChipLink, Code, ConfirmDialog, DataTable, EmptyState, GlassPanel, PageSummary, Pagination, Qty, TextLink, type Column } from "~/ui";
import { humanise, RESERVATION_STATUSES, reservationsHref, reservationStatus } from "./labels";
import { ProductCell } from "./parts";

/** Stock held for orders, and the products where demand has outrun what is free. */
export function Reservations({ status, offset }: { status: string | null; offset: number }) {
  const { permissionKeys } = useSession();
  const canOpen = useCanOpen();
  const listKey = useMemo(() => reservationsKey(status, offset), [status, offset]);
  const query = useReservations(status, offset);
  const { run, pending, offline } = useCommand<null>(listKey);
  const [releasing, setReleasing] = useState<ReservationRow | null>(null);
  const mayRelease = permissionKeys.has("inventory.stock.reserve");
  const releasable = (row: ReservationRow) => mayRelease && Boolean(row.capabilities.release?.allowed);
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const rows = query.data?.items ?? [];

  const columns: Column<ReservationRow>[] = [
    { key: "product", header: "Product", primary: true, cell: (row) => <ProductCell product={row.product} /> },
    {
      key: "warehouse",
      header: "Warehouse",
      cell: (row) => (
        <span className="lk-mono" title={row.warehouse.name}>
          {row.warehouse.code}
        </span>
      ),
    },
    {
      key: "demand",
      header: "Held for",
      cell: (row) => {
        const label = row.demand_label ?? humanise(row.demand_type);
        return row.demand_path && canOpen(row.demand_path) ? <TextLink href={asRoute(row.demand_path)}>{label}</TextLink> : <span className="text-ink">{label}</span>;
      },
    },
    {
      key: "held",
      header: "Still held",
      numeric: true,
      cell: (row) => (
        <span className="flex flex-col items-end gap-0.5">
          <Qty value={{ value: row.remaining, uom: row.unit }} className="t-label text-ink" />
          <span className="t-caption text-ink-3">
            of <Qty value={{ value: row.quantity, uom: row.unit }} /> reserved
          </span>
        </span>
      ),
    },
    { key: "status", header: "Status", cell: (row) => <StatusBadge look={reservationStatus(row.status)} /> },
    // The release column exists only when this page has something this person may release.
    ...(rows.some(releasable)
      ? [
          {
            key: "release",
            header: <span className="sr-only">Release</span>,
            mobileLabel: "Free this stock",
            cell: (row: ReservationRow) =>
              releasable(row) ? (
                <Button size="sm" variant="secondary" iconLeft="undo" loading={pending === row.id} isDisabled={Boolean(offline)} onPress={() => setReleasing(row)}>
                  Release
                </Button>
              ) : null,
          },
        ]
      : []),
  ];

  return (
    <Page>
      <PageHeader eyebrow="Operations" title="Reservations" lead="Stock held for orders, so the same units are never promised twice." />

      <Shortages />

      <PageSection title="Held stock" description="Every reservation in the warehouses you can see, newest first." index={1}>
        <ChipGroup label="Filter by status">
          <ChipLink href={asRoute(reservationsHref(null))} selected={status === null} scroll={false}>
            All
          </ChipLink>
          {RESERVATION_STATUSES.map((value) => (
            <ChipLink key={value} href={asRoute(reservationsHref(value))} selected={status === value} scroll={false}>
              {reservationStatus(value).label}
            </ChipLink>
          ))}
        </ChipGroup>

        {query.isError ? (
          <ErrorBlock error={query.error} what="Reservations" onRetry={() => void query.refetch()} />
        ) : (
          <GlassPanel padding="none" className="min-w-0">
            <DataTable
              label="Reservations"
              columns={columns}
              rows={rows}
              rowKey={(row) => row.id}
              loading={query.isPending}
              skeletonRows={8}
              empty={
                status ? (
                  <EmptyState
                    compact
                    icon="search"
                    title={`No reservations are ${reservationStatus(status).label.toLowerCase()}`}
                    text="Nothing has this status in the warehouses you can see."
                    actions={
                      <ButtonLink href="/operations/reservations" variant="secondary" size="sm">
                        See all reservations
                      </ButtonLink>
                    }
                  />
                ) : (
                  <EmptyState
                    icon="bookmark"
                    title="Nothing is held yet"
                    text="Stock is held when an order reserves it. Open a confirmed order and choose Reserve stock."
                    actions={
                      canOpen("/sales/orders") ? (
                        <ButtonLink href={asRoute("/sales/orders?status=confirmed")} variant="secondary" iconRight="arrowRight">
                          See confirmed orders
                        </ButtonLink>
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
            <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="reservations" />
            {total > limit ? (
              <Pagination
                label="Reservation pages"
                page={Math.floor(query.data.offset / limit) + 1}
                pages={Math.ceil(total / limit)}
                hrefFor={(page) => asRoute(reservationsHref(status, (page - 1) * limit))}
              />
            ) : null}
          </div>
        ) : null}
      </PageSection>

      <ConfirmDialog
        isOpen={releasing !== null}
        onOpenChange={(open) => (open ? undefined : setReleasing(null))}
        title="Release this reservation"
        description={
          releasing
            ? `${releasing.product.product_key} in ${releasing.warehouse.name} stops being held for ${releasing.demand_label ?? "its order"} and is free to promise again.`
            : undefined
        }
        confirmLabel="Release reservation"
        cancelLabel="Keep it held"
        onConfirm={async () => {
          if (!releasing) return;
          const released = await run(releasing.id, (k) => releaseReservation(releasing.id, k), { done: "Reservation released", failed: "The reservation could not be released" });
          if (!released) throw new Error("release failed");
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Shortages: demand beyond free stock, with the orders behind it

function Shortages() {
  const query = useShortages();
  const canOpen = useCanOpen();
  if (query.isPending) return <LoadingBlock lines={2} label="Loading shortages" className="rise" />;
  if (query.isError) return <ErrorBlock error={query.error} what="Shortages" onRetry={() => void query.refetch()} />;
  if (query.data.length === 0) {
    return (
      <Banner tone="leaf" title="No product is short." className="rise">
        Every order is covered by the stock that is free.
      </Banner>
    );
  }
  return (
    <PageSection
      title="Short right now"
      description="More is wanted than is free. Each line names the orders behind it."
      index={0}
      action={
        canOpen("/operations/inventory") ? (
          <ButtonLink href={asRoute("/operations/inventory?short=1")} variant="ghost" size="sm" iconRight="arrowRight">
            Short stock
          </ButtonLink>
        ) : undefined
      }
    >
      <GlassPanel padding="md" className="min-w-0">
        <ul className="m-0 flex list-none flex-col p-0">
          {query.data.map((shortage, index) => (
            <ShortageRow key={shortage.id} shortage={shortage} index={index} canOpen={canOpen} />
          ))}
        </ul>
      </GlassPanel>
    </PageSection>
  );
}

function ShortageRow({ shortage, index, canOpen }: { shortage: Shortage; index: number; canOpen: (path: string) => boolean }) {
  return (
    <li className="rise-plain hairline-top flex flex-wrap items-start justify-between gap-x-6 gap-y-2 py-3 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
      <div className="flex min-w-0 flex-col gap-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Code>{shortage.product.product_key}</Code>
          <span className="t-label truncate text-ink" title={shortage.product.name}>
            {shortage.product.name}
          </span>
        </span>
        <span className="t-caption flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-3">
          <span>{shortage.warehouse.name}</span>
          {shortage.caused_by.length > 0 ? <span aria-hidden="true">·</span> : null}
          {shortage.caused_by.length > 0 ? <span>Wanted by</span> : null}
          {shortage.caused_by.map((cause) =>
            cause.path && canOpen(cause.path) ? (
              <TextLink key={cause.id} href={asRoute(cause.path)}>
                {cause.label ?? humanise(cause.type)}
              </TextLink>
            ) : (
              <span key={cause.id} className="text-ink-2">
                {cause.label ?? humanise(cause.type)}
              </span>
            ),
          )}
        </span>
      </div>
      <Badge tone="ember" icon="alert">
        Short by {shortage.unit ? <Qty value={{ value: shortage.shortfall, uom: shortage.unit }} /> : shortage.shortfall}
      </Badge>
    </li>
  );
}
