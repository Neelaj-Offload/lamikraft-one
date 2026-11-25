"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { fetchChallans, fetchChallanSummary } from "@/features/challans/api";
import {
  challanListHref,
  challanListParams,
  challanListQueryKey,
  challanSummaryParams,
  challanSummaryQueryKey,
  DEFAULT_CHALLAN_LIST,
  type ChallanListState,
} from "@/features/challans/list-state";
import { fetchShortages } from "@/features/inventory/api";
import { fetchShipments } from "@/features/logistics/api";
import { shipmentListHref } from "@/features/logistics/list-state";
import { fetchPurchaseOrders } from "@/features/procurement/api";
import { poListHref } from "@/features/procurement/list-state";
import { fetchWorkOrders } from "@/features/production/api";
import { workOrdersHref, type WorkOrderListState } from "@/features/production/list-state";
import { fetchInspections } from "@/features/quality/api";
import { inspectionListHref } from "@/features/quality/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { canAccessRoute, matchRoute } from "~/lib/routes";
import { useSession } from "@/lib/session/context";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { Badge, Banner, Button, ButtonLink, CountUp, DateText, EmptyState, GlassPanel, Icon, Qty, Skeleton, StatTile, type IconName, type Tone } from "~/ui";

/** How many rows each source may add to "Needs attention", and the most the list shows. */
const PER_SOURCE = 3;
const ATTENTION_LIMIT = 8;

const stagger = (index: number) => riseIndex(index) as React.CSSProperties;

interface AttentionRow {
  id: string;
  kind: string;
  icon: IconName;
  title: string;
  detail: ReactNode;
  /** What is wrong or what to do, as the badge. */
  ask: string;
  tone: Tone;
  /** An instant (relative time) or a business date (shown as the date). */
  at: string | null;
  href: string;
  mono?: boolean;
}

const SCREENS: { href: string; label: string; icon: IconName; line: string }[] = [
  { href: "/operations/inventory", label: "Stock", icon: "boxes", line: "What is on hand in each warehouse, free or held." },
  { href: "/operations/reservations", label: "Reservations", icon: "bookmark", line: "Stock held for orders, and the demand it cannot cover." },
  { href: "/operations/production/work-orders", label: "Production", icon: "factory", line: "Work orders from release to finished output." },
  { href: "/operations/cutting", label: "Cutting", icon: "scissors", line: "Cut plans that get the most pieces from each sheet." },
  { href: "/operations/purchasing/orders", label: "Purchasing", icon: "cart", line: "Purchase orders to suppliers, and the goods they bring in." },
  { href: "/operations/quality", label: "Quality", icon: "clipboardCheck", line: "Inspections of received goods and finished output." },
  { href: "/operations/dispatch", label: "Dispatch", icon: "truck", line: "Shipments and packing lists, from booking to delivery." },
  { href: "/operations/challans", label: "Challans", icon: "fileCheck", line: "Delivery challans for goods going out and coming back." },
];

function StatFigure({ value }: { value: number | undefined }) {
  return value === undefined ? <Skeleton width={44} height={32} /> : <CountUp value={value} />;
}

const INSPECTIONS = { status: "pending", offset: 0 } as const;
const IN_PROGRESS = { q: "", status: "in_progress", blocked: false, offset: 0 } as const satisfies WorkOrderListState;
const BLOCKED = { q: "", status: null, blocked: true, offset: 0 } as const satisfies WorkOrderListState;
const OVERDUE_POS = { q: "", status: null, overdue: true, offset: 0 };
const EXCEPTIONS = { q: "", status: "exception", offset: 0 };
const STILL_OUT: ChallanListState = { ...DEFAULT_CHALLAN_LIST, pending: true };

/** The operations overview: the numbers that matter, what is stuck or late, and the way into each screen. */
export function OperationsHub() {
  const { permissionKeys, user } = useSession() as ReturnType<typeof useSession> & { user?: { display_name?: string | null } };
  const can = (path: string) => {
    const route = matchRoute(path);
    return route !== null && canAccessRoute(route, permissionKeys);
  };
  const canStock = permissionKeys.has("inventory.stock.read");
  const canQuality = permissionKeys.has("quality.inspection.read");
  const canProduction = permissionKeys.has("production.work_order.read");
  const canChallans = permissionKeys.has("challans.challan.read");
  const canPurchasing = permissionKeys.has("procurement.purchase_order.read");
  const canDispatch = permissionKeys.has("logistics.shipment.read");

  const shortages = useQuery({ queryKey: queryKeys.inventory.shortages(), queryFn: ({ signal }) => fetchShortages(signal), enabled: canStock });
  const inspections = useQuery({ queryKey: queryKeys.quality.inspections(INSPECTIONS), queryFn: ({ signal }) => fetchInspections(INSPECTIONS, signal), enabled: canQuality });
  const running = useQuery({ queryKey: queryKeys.production.workOrders({ ...IN_PROGRESS }), queryFn: ({ signal }) => fetchWorkOrders(IN_PROGRESS, signal), enabled: canProduction });
  const blocked = useQuery({ queryKey: queryKeys.production.workOrders({ ...BLOCKED }), queryFn: ({ signal }) => fetchWorkOrders(BLOCKED, signal), enabled: canProduction });
  const summary = useQuery({
    queryKey: challanSummaryQueryKey(DEFAULT_CHALLAN_LIST),
    queryFn: ({ signal }) => fetchChallanSummary(challanSummaryParams(DEFAULT_CHALLAN_LIST), signal),
    enabled: canChallans,
    staleTime: 30_000,
  });
  const out = useQuery({ queryKey: challanListQueryKey(STILL_OUT), queryFn: ({ signal }) => fetchChallans(challanListParams(STILL_OUT), signal), enabled: canChallans });
  const overduePos = useQuery({ queryKey: queryKeys.procurement.orders({ ...OVERDUE_POS }), queryFn: ({ signal }) => fetchPurchaseOrders(OVERDUE_POS, signal), enabled: canPurchasing });
  const exceptions = useQuery({ queryKey: queryKeys.logistics.shipments(EXCEPTIONS), queryFn: ({ signal }) => fetchShipments(EXCEPTIONS, signal), enabled: canDispatch });

  const sources = [
    ...(canDispatch ? [exceptions] : []),
    ...(canStock ? [shortages] : []),
    ...(canProduction ? [blocked] : []),
    ...(canQuality ? [inspections] : []),
    ...(canPurchasing ? [overduePos] : []),
    ...(canChallans ? [out, summary] : []),
  ];
  const attentionLoading = sources.some((source) => source.isPending);
  const failed = sources.filter((source) => source.isError);
  const today = summary.data?.today ?? null;
  const lateBack = (out.data?.items ?? []).filter((challan) => challan.expected_return_date !== null && today !== null && challan.expected_return_date < today);

  const rows: AttentionRow[] = [
    ...(exceptions.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((shipment) => ({
      id: `shipment-${shipment.id}`,
      kind: "Shipment",
      icon: "truck",
      title: shipment.shipment_number,
      detail: [shipment.party_name, shipment.transporter_name].filter(Boolean).join(" · "),
      ask: "Exception",
      tone: "ember",
      at: shipment.planned_dispatch_date,
      href: shipment.path,
      mono: true,
    })),
    ...(shortages.data ?? []).slice(0, PER_SOURCE).map<AttentionRow>((shortage) => ({
      id: `shortage-${shortage.id}`,
      kind: "Shortage",
      icon: "boxes",
      title: shortage.product.name,
      detail: (
        <>
          {shortage.warehouse.code} · short by <Qty value={{ value: shortage.shortfall, uom: shortage.unit ?? "" }} />
        </>
      ),
      ask: "Short",
      tone: "ember",
      at: shortage.detected_at,
      href: "/operations/reservations",
    })),
    ...(blocked.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((order) => ({
      id: `work-order-${order.id}`,
      kind: "Work order",
      icon: "factory",
      title: order.wo_number,
      detail: order.product.name,
      ask: "Blocked",
      tone: "amber",
      at: order.updated_at,
      href: `/operations/production/work-orders/${encodeURIComponent(order.id)}`,
      mono: true,
    })),
    ...(inspections.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((inspection) => ({
      id: `inspection-${inspection.id}`,
      kind: "Inspection",
      icon: "clipboardCheck",
      title: inspection.product.name,
      detail: [inspection.inspection_number, inspection.subject_label].filter(Boolean).join(" · "),
      ask: "Inspect",
      tone: "amber",
      at: inspection.requested_at,
      href: inspection.path,
    })),
    ...(overduePos.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((po) => ({
      id: `po-${po.id}`,
      kind: "Purchase order",
      icon: "cart",
      title: po.po_number,
      detail: po.vendor.display_name,
      ask: "Overdue",
      tone: "amber",
      at: po.next_expected_date,
      href: po.path,
      mono: true,
    })),
    ...lateBack.slice(0, PER_SOURCE).map<AttentionRow>((challan) => ({
      id: `challan-${challan.id}`,
      kind: "Challan",
      icon: "undo",
      title: challan.challan_number,
      detail: challan.destination_party,
      ask: "Due back",
      tone: "amber",
      at: challan.expected_return_date,
      href: challan.path,
      mono: true,
    })),
  ].slice(0, ATTENTION_LIMIT);

  const tiles: ReactNode[] = [];
  if (canStock) {
    const count = shortages.data?.length;
    tiles.push(
      <StatTile
        key="shortages"
        label="Short of stock"
        value={<StatFigure value={count} />}
        foot={count === undefined ? undefined : count > 0 ? "Demand the free stock cannot cover" : "Every reservation is covered"}
        dot={Boolean(count)}
        href={"/operations/reservations" as Route}
      />,
    );
  }
  if (canQuality) {
    tiles.push(
      <StatTile
        key="inspections"
        label="Waiting for inspection"
        value={<StatFigure value={inspections.data?.total} />}
        foot={inspections.data ? (inspections.data.total > 0 ? "Received goods and output to check" : "Nothing waiting to be checked") : undefined}
        href={inspectionListHref(INSPECTIONS) as Route}
      />,
    );
  }
  if (canProduction) {
    tiles.push(
      <StatTile
        key="work-orders"
        label="Work orders in progress"
        value={<StatFigure value={running.data?.total} />}
        foot={blocked.data ? (blocked.data.total > 0 ? blocked.data.total === 1 ? "1 work order is blocked" : `${blocked.data.total} work orders are blocked` : "None blocked") : undefined}
        dot={Boolean(blocked.data?.total)}
        href={workOrdersHref(IN_PROGRESS) as Route}
      />,
    );
  }
  if (canChallans) {
    const quantity = summary.data?.pending_returnable_quantity ?? {};
    const units = Object.entries(quantity);
    tiles.push(
      <StatTile
        key="challans"
        label="Challans still out"
        value={<StatFigure value={summary.data?.pending_returnable} />}
        foot={
          summary.data ? (
            units.length > 0 ? (
              <span className="inline-flex flex-wrap gap-x-1.5">
                <span>Out now:</span>
                {units.map(([unit, value], index) => (
                  <span key={unit} className="whitespace-nowrap">
                    {index > 0 ? "· " : ""}
                    <Qty value={{ value, uom: unit }} />
                  </span>
                ))}
              </span>
            ) : (
              "Everything returnable is back"
            )
          ) : undefined
        }
        href={challanListHref(STILL_OUT) as Route}
      />,
    );
  }
  if (tiles.length < 4 && canPurchasing) {
    tiles.push(
      <StatTile
        key="pos"
        label="Purchase orders overdue"
        value={<StatFigure value={overduePos.data?.total} />}
        foot={overduePos.data ? (overduePos.data.total > 0 ? "Past the date the supplier gave" : "Every supplier is on time") : undefined}
        href={poListHref(OVERDUE_POS) as Route}
      />,
    );
  }
  if (tiles.length < 4 && canDispatch) {
    tiles.push(
      <StatTile
        key="shipments"
        label="Shipments with an exception"
        value={<StatFigure value={exceptions.data?.total} />}
        foot={exceptions.data ? (exceptions.data.total > 0 ? "Held up on the way" : "Every shipment is moving") : undefined}
        href={shipmentListHref(EXCEPTIONS) as Route}
      />,
    );
  }

  const screens = SCREENS.filter((screen) => can(screen.href));
  const firstName = user?.display_name?.split(" ")[0];

  return (
    <Page>
      <PageHeader
        display
        eyebrow={firstName ? `Operations · ${firstName}` : "Operations"}
        title={
          <>
            From supplier to <em>dispatch</em>
          </>
        }
        lead="What is short, waiting, blocked or late across stock, production, purchasing and dispatch today."
        actions={
          permissionKeys.has("challans.challan.create") ? (
            <ButtonLink href={"/operations/challans/new" as Route} iconLeft="plus">
              Create challan
            </ButtonLink>
          ) : null
        }
      />

      {tiles.length > 0 ? (
        <div className="tiles" aria-label="Operations at a glance" role="group">
          {tiles.map((tile, index) => (
            <GlassPanel key={index} interactive className="rise" style={stagger(index + 1)}>
              {tile}
            </GlassPanel>
          ))}
        </div>
      ) : null}

      {sources.length > 0 ? (
        <PageSection title="Needs attention" description="Problems first: shipments held up and stock that is short, then blocked work, goods to inspect and anything late." index={1}>
          {failed.length > 0 ? (
            <Banner
              tone="amber"
              title="Part of this list could not load."
              action={
                <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => failed.forEach((source) => void source.refetch())}>
                  Try again
                </Button>
              }
            >
              What you see below may be incomplete.
            </Banner>
          ) : null}
          <GlassPanel padding="none" className="overflow-hidden">
            {attentionLoading && rows.length === 0 ? (
              <div role="status" aria-label="Loading what needs attention">
                {[0, 1, 2].map((row) => (
                  <div key={row} className="flex items-center gap-4 border-line px-5 py-4 [&:not(:first-child)]:border-t">
                    <Skeleton circle width={36} height={36} />
                    <div className="flex flex-1 flex-col gap-2">
                      <Skeleton width="40%" height={14} />
                      <Skeleton width="60%" />
                    </div>
                  </div>
                ))}
              </div>
            ) : rows.length === 0 ? (
              <EmptyState
                compact
                icon="checkCircle"
                title="Nothing is stuck or late"
                text="No shortage, no blocked work order, nothing waiting for inspection or overdue. New problems appear here first."
              />
            ) : (
              <ul className="m-0 flex list-none flex-col p-0">
                {rows.map((row, index) => (
                  <li
                    key={row.id}
                    className="rise-plain relative flex min-w-0 items-center gap-4 border-line px-5 py-4 transition-colors hover:bg-[color-mix(in_srgb,var(--ink)_4%,transparent)] [&:not(:first-child)]:border-t"
                    style={stagger(index)}
                  >
                    <span className="grid size-9 flex-none place-items-center rounded-pill border border-line text-ink-2">
                      <Icon name={row.icon} size={16} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <Link href={row.href as Route} className={`stretched t-label truncate text-ink no-underline ${row.mono ? "lk-mono" : ""}`}>
                        <span className="lk-sr-only">{row.kind}: </span>
                        {row.title}
                      </Link>
                      <span className="t-caption truncate text-ink-3">
                        {row.kind} · {row.detail}
                      </span>
                    </span>
                    <span className="flex-none">
                      <Badge tone={row.tone} size="sm">
                        {row.ask}
                      </Badge>
                    </span>
                    {row.at ? <DateText value={row.at} style="relative" className="t-caption hidden flex-none text-ink-3 sm:block" /> : null}
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>
        </PageSection>
      ) : null}

      <PageSection title="Everything in operations" index={2}>
        <ul className="tiles m-0 list-none p-0" data-min="lg">
          {screens.map((screen, index) => (
            <GlassPanel as="li" key={screen.href} variant="outline" interactive className="rise-plain relative flex items-start gap-4" style={stagger(index)}>
              <span className="mt-0.5 flex-none text-ink-3">
                <Icon name={screen.icon} size={20} />
              </span>
              <span className="flex min-w-0 flex-col gap-1">
                <Link href={screen.href as Route} className="stretched t-h4 text-ink no-underline">
                  {screen.label}
                </Link>
                <span className="t-body-sm text-ink-3">{screen.line}</span>
              </span>
            </GlassPanel>
          ))}
        </ul>
      </PageSection>
    </Page>
  );
}
