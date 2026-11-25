"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { copyRouting, fetchRouting, routingAction, type RoutingRead } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, useProductionCommand } from "~/data/production";
import { Page } from "~/shell/page";
import { Badge, Code, DataTable, EmptyState, GlassPanel, Qty, TextLink, type Column } from "~/ui";
import { Minutes, PATHS, RecordFailed, RecordLoading, useCanOpen, ViewHeading } from "./parts";
import { VersionHeader } from "./version-record";

const FAILED = "That did not go through";

/** A routing version: the operations a product goes through, where, and how long each takes. */
export function RoutingRecord({ routingId }: { routingId: string }) {
  const query = useQuery({ queryKey: queryKeys.production.routing(routingId), queryFn: ({ signal }) => fetchRouting(routingId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the routing" />;
  if (query.isError) return <RecordFailed error={query.error} what="This routing" onRetry={() => void query.refetch()} backHref={PATHS.routings} backLabel="All routings" />;
  return <Loaded routing={query.data} />;
}

type Operation = RoutingRead["operations"][number];

function Loaded({ routing }: { routing: RoutingRead }) {
  const router = useRouter();
  const canOpen = useCanOpen();
  const key = useMemo(() => queryKeys.production.routing(routing.id), [routing.id]);
  const { run, pending, offline } = useProductionCommand<RoutingRead>(key);
  const write = (record: RoutingRead) => record;
  const uom = routing.product.stock_uom_code;

  const columns: Column<Operation>[] = [
    { key: "seq", header: "Step", numeric: true, width: "72px", cell: (operation) => <span className="t-label lk-tnum text-ink-2">{operation.seq}</span> },
    { key: "name", header: "Operation", primary: true, cell: (operation) => <span className="t-label text-ink">{operation.name}</span> },
    {
      key: "centre",
      header: "Work centre",
      cell: (operation) => {
        const centrePath = `${PATHS.workCentres}/${operation.work_center.id}`;
        return (
          <span className="flex min-w-0 flex-col gap-0.5">
            {canOpen(centrePath) ? <TextLink href={asRoute(centrePath)}>{operation.work_center.name}</TextLink> : <span className="text-ink">{operation.work_center.name}</span>}
            <Code className="t-code-sm text-ink-3">{operation.work_center.code}</Code>
          </span>
        );
      },
    },
    { key: "setup", header: "Setup", numeric: true, cell: (operation) => <Minutes value={operation.setup_minutes} /> },
    { key: "run", header: "Run per unit", numeric: true, cell: (operation) => <Minutes value={operation.run_minutes_per_unit} className="t-label text-ink" /> },
    {
      key: "notes",
      header: "Notes",
      cell: (operation) =>
        operation.is_board_cutting || operation.is_job_work ? (
          <span className="flex flex-wrap gap-1.5">
            {operation.is_board_cutting ? (
              <Badge tone="cobalt" size="sm" icon="scissors">
                Board cutting, takes a cut plan
              </Badge>
            ) : null}
            {operation.is_job_work ? (
              <Badge size="sm" outline icon="truck">
                Job work
              </Badge>
            ) : null}
          </span>
        ) : (
          <span className="text-ink-3">None</span>
        ),
    },
  ];

  return (
    <Page>
      <VersionHeader
        record={routing}
        list={{ label: "Routings", href: PATHS.routings }}
        countLabel="Operations"
        moreFacts={[{ label: "Setup spread over", icon: "boxes", value: <Qty value={{ value: routing.standard_batch_qty, uom: uom ?? "units" }} /> }]}
        pending={pending}
        offline={Boolean(offline)}
        onApprove={async () => (await run("approve", (k) => routingAction(routing, "approve", k), { done: "Version approved", failed: FAILED, write })) !== null}
        onRetire={async (reason) => (await run("retire", (k) => routingAction(routing, "retire", k, reason), { done: "Version retired", failed: FAILED, write })) !== null}
        onCopy={() =>
          void run("copy", (k) => copyRouting(routing, k), { done: "New draft version started", failed: FAILED }).then((created) => {
            if (created) router.push(asRoute(`${PATHS.routings}/${created.id}`));
          })
        }
      />

      <div className="stack">
        <ViewHeading
          title="Operations"
          text={
            <>
              In the order the floor takes them. Setup time is spread over a batch of <Qty value={{ value: routing.standard_batch_qty, uom: uom ?? "units" }} />; run time counts for every unit.
            </>
          }
        />
        <GlassPanel padding="none" className="rise min-w-0">
          <DataTable
            label={`Operations of ${routing.product.product_key}, version ${routing.version_no}`}
            columns={columns}
            rows={routing.operations}
            rowKey={(operation) => operation.id}
            empty={<EmptyState compact icon="route" title="This version has no operations" text="A routing needs at least one operation before it can be approved." />}
          />
        </GlassPanel>
      </div>
    </Page>
  );
}
