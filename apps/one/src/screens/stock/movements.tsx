"use client";

import { PAGE_SIZE, type MovementRow } from "@/features/inventory/api";
import { asRoute, useCanOpen, useMovements } from "~/data/stock";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { stagger } from "~/screens/sales/quotations/parts";
import { Badge, Code, DataTable, DateText, EmptyState, GlassPanel, PageSummary, Pagination, Qty, TextLink, type Column } from "~/ui";
import { movementSource, movementsHref } from "./labels";
import { LocationCell, ProductCell, StockViews } from "./parts";

/** The stock ledger, newest first: every movement from one location to another. */
export function Movements({ offset }: { offset: number }) {
  const query = useMovements(offset);
  const canOpen = useCanOpen();
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;

  const columns: Column<MovementRow>[] = [
    { key: "when", header: "Posted", cell: (row) => <DateText value={row.posted_at} style="dayTime" /> },
    { key: "product", header: "Product", primary: true, cell: (row) => <ProductCell product={row.product} caption={row.lot ? `Lot ${row.lot.lot_code}` : undefined} /> },
    { key: "from", header: "From", cell: (row) => <LocationCell location={row.from_location} /> },
    { key: "to", header: "To", cell: (row) => <LocationCell location={row.to_location} /> },
    { key: "quantity", header: "Quantity", numeric: true, cell: (row) => <Qty value={{ value: row.quantity, uom: row.unit }} className="t-label text-ink" /> },
    {
      key: "source",
      header: "Because of",
      cell: (row) => {
        const label = row.source_label ?? row.source_id.slice(0, 8);
        return (
          <span className="flex min-w-0 flex-col items-start gap-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-ink-2">{movementSource(row.source_type)}</span>
              {row.source_path && canOpen(row.source_path) ? (
                <TextLink href={asRoute(row.source_path)}>
                  <Code>{label}</Code>
                </TextLink>
              ) : row.source_label ? (
                <Code>{row.source_label}</Code>
              ) : null}
            </span>
            {row.is_reversal ? (
              <Badge tone="amber" size="sm" icon="undo">
                Reversal
              </Badge>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Stock movements"
        lead="Every unit that moved, newest first. A movement is never edited: a mistake is put right with a reversal."
      />

      <StockViews current="movements" />

      {query.isError ? (
        <ErrorBlock error={query.error} what="Stock movements" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(1)}>
          <DataTable
            label="Stock movements"
            columns={columns}
            rows={query.data?.items ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={10}
            empty={
              <EmptyState
                icon="history"
                title="Nothing has moved yet"
                text="Receipts, challans, transfers, stock takes and adjustments each leave a line here, in the warehouses you can see."
              />
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="movements" />
          {total > limit ? (
            <Pagination
              label="Movement pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(movementsHref((page - 1) * limit))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
