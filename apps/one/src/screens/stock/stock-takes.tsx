"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { createCount, type DocumentSummary } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { useSession } from "@/lib/session/context";
import { asRoute, stockTakesKey, useStockTakes, useWarehouses } from "~/data/stock";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { stagger, StatusBadge } from "~/screens/sales/quotations/parts";
import { Button, Code, DataTable, DateText, EmptyState, GlassPanel, Modal, Select, type Column } from "~/ui";
import { stockTakeStatus, viewHref } from "./labels";
import { StockViews } from "./parts";

const COLUMNS: Column<DocumentSummary>[] = [
  { key: "number", header: "Stock take", primary: true, cell: (take) => <Code>{take.number}</Code> },
  {
    key: "warehouse",
    header: "Warehouse",
    cell: (take) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={take.warehouse.name}>
          {take.warehouse.name}
        </span>
        <span className="t-caption lk-mono text-ink-3">{take.warehouse.code}</span>
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (take) => <StatusBadge look={stockTakeStatus(take.status)} /> },
  { key: "lines", header: "Lines", numeric: true, cell: (take) => take.line_count },
  { key: "created", header: "Started", cell: (take) => <DateText value={take.created_at} style="dayTime" /> },
];

/** Stock takes: counting a warehouse against what Lamikraft One holds. The newest 50, as the old screen listed. */
export function StockTakes() {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const query = useStockTakes();
  const warehouses = useWarehouses();
  const listKey = useMemo(() => stockTakesKey(), []);
  const { run, pending, offline } = useCommand<null>(listKey);
  const [starting, setStarting] = useState(false);
  const [warehouse, setWarehouse] = useState<string | null>(null);
  const canStart = permissionKeys.has("inventory.stock_count.create") && (warehouses.data?.length ?? 0) > 0;
  const chosen = warehouse ?? warehouses.data?.[0]?.id ?? null;

  const start = async () => {
    if (!chosen) return;
    const created = await run("create", (k) => createCount(chosen, k), { done: "Stock take started", failed: "The stock take could not be started" });
    if (created) router.push(asRoute(`/operations/inventory/stock-takes/${created.id}`));
  };

  const startButton = canStart ? (
    <Button iconLeft="plus" isDisabled={Boolean(offline)} onPress={() => setStarting(true)}>
      Start stock take
    </Button>
  ) : null;

  return (
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Stock takes"
        lead="Count a warehouse against the records. Freeze what Lamikraft One holds, enter what you find, and approval posts the difference."
        actions={startButton}
      />

      <StockViews current="stock-takes" />

      {query.isError ? (
        <ErrorBlock error={query.error} what="Stock takes" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(1)}>
          <DataTable
            label="Stock takes"
            columns={COLUMNS}
            rows={query.data ?? []}
            rowKey={(take) => take.id}
            // A count in progress opens on its count sheet: that is where the work is.
            rowHref={(take) => asRoute(take.status === "frozen" ? viewHref(take.path, "lines") : take.path)}
            loading={query.isPending}
            skeletonRows={6}
            empty={
              <EmptyState
                icon="clipboardCheck"
                title="No stock takes yet"
                text={
                  canStart
                    ? "Start one to count a warehouse. Stock keeps moving while you count."
                    : "A stock take checks what a warehouse holds against the records. None has been started in the warehouses you can see."
                }
                actions={
                  canStart ? (
                    <Button variant="secondary" iconLeft="plus" isDisabled={Boolean(offline)} onPress={() => setStarting(true)}>
                      Start stock take
                    </Button>
                  ) : undefined
                }
              />
            }
          />
        </GlassPanel>
      )}

      <Modal
        isOpen={starting}
        onOpenChange={(open) => (pending ? undefined : setStarting(open))}
        size="sm"
        title="Start a stock take"
        description="It begins as a draft. Nothing is frozen and no stock changes until you start counting."
        actions={
          <>
            <Button variant="ghost" isDisabled={pending !== null} onPress={() => setStarting(false)}>
              Not now
            </Button>
            <Button variant="inverse" loading={pending === "create"} isDisabled={!chosen} onPress={() => void start()}>
              Start stock take
            </Button>
          </>
        }
      >
        <Select
          label="Warehouse to count"
          options={(warehouses.data ?? []).map((item) => ({ value: item.id, label: item.name, description: item.code }))}
          value={chosen}
          onChange={setWarehouse}
        />
      </Modal>
    </Page>
  );
}
