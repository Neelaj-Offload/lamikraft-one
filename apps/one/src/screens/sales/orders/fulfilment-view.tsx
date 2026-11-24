"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { OrderDetail } from "@/features/orders/api";
import { fetchOrderLineFeasibility, type FeasibilityRead } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { useSession } from "@/lib/session/context";
import { asRoute, humanise, useCanOpen } from "~/data/sales-deals";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, ButtonLink, Code, DatePicker, DateText, EmptyState, GlassPanel, Qty, SkeletonText, TextLink, type Tone } from "~/ui";
import { stagger } from "../quotations/parts";

const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  feasible: { label: "Can be delivered", tone: "leaf" },
  at_risk: { label: "At risk", tone: "amber" },
  not_feasible: { label: "Cannot be delivered by then", tone: "ember" },
  estimate: { label: "Estimate only", tone: "cobalt" },
};
const EVIDENCE_TONE: Record<string, Tone> = { ok: "leaf", short: "ember", missing: "cobalt", late: "amber", info: "neutral" };
const EVIDENCE_KIND: Record<string, string> = {
  stock: "Stock",
  purchase_supply: "Purchases on the way",
  components: "Components",
  capacity: "Capacity",
  routing: "Routing",
  bom: "Bill of materials",
  lead_time: "Lead time",
};
const DOC_STATUS_TONE: Record<string, Tone> = { draft: "neutral", issued: "cobalt", dispatched: "cobalt", delivered: "leaf", completed: "leaf", cancelled: "neutral" };

/** What the warehouse holds for this order, the documents it has gone out on, and a read-only delivery check. */
export function FulfilmentView({ order }: { order: OrderDetail }) {
  const lineNo = (lineId: string) => order.lines.find((line) => line.id === lineId);
  const canOpen = useCanOpen();
  return (
    <div className="stack">
      <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
        <GlassPanel
          padding="lg"
          title="Stock held"
          titleAs="h2"
          className="rise min-w-0"
          action={
            canOpen("/operations/reservations") ? (
              <ButtonLink href="/operations/reservations" variant="ghost" size="sm" iconRight="arrowRight">
                All reservations
              </ButtonLink>
            ) : undefined
          }
        >
          {order.reservations.length === 0 ? (
            <EmptyState compact icon="bookmark" title="Nothing is held yet" text="Reserving stock holds it in the warehouse for this order, so it cannot be promised twice." />
          ) : (
            <ul className="flex flex-col">
              {order.reservations.map((reservation, index) => {
                const line = lineNo(reservation.line_id);
                return (
                  <li key={reservation.id} className="rise-plain hairline-top flex flex-wrap items-center justify-between gap-x-6 gap-y-1 py-3 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <span className="t-label text-ink">{line ? `Line ${line.line_no} · ${line.description}` : "A line of this order"}</span>
                      <span className="t-caption text-ink-3">
                        {reservation.warehouse.name} ({reservation.warehouse.code}) · {humanise(reservation.status).toLowerCase()}
                      </span>
                    </div>
                    <div className="flex flex-col items-end">
                      <Qty value={{ value: reservation.remaining, uom: reservation.unit }} className="t-stat-sm text-ink" />
                      <span className="t-caption text-ink-3">
                        still held of <Qty value={{ value: reservation.quantity, uom: reservation.unit }} />
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </GlassPanel>

        <GlassPanel
          padding="lg"
          title="Dispatch documents"
          titleAs="h2"
          className="rise min-w-0"
          style={stagger(1)}
          action={
            canOpen("/operations/dispatch") ? (
              <ButtonLink href="/operations/dispatch" variant="ghost" size="sm" iconRight="arrowRight">
                Dispatch
              </ButtonLink>
            ) : undefined
          }
        >
          {order.documents.length === 0 ? (
            <EmptyState compact icon="truck" title="Nothing has gone out yet" text="A pick list tells the warehouse what to collect. A delivery challan travels with the goods and records the delivery." />
          ) : (
            <ul className="flex flex-col">
              {order.documents.map((doc, index) => (
                <li key={doc.id} className="rise-plain hairline-top flex flex-wrap items-center justify-between gap-3 py-3 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <TextLink href={asRoute(doc.path)} className="t-label">
                      <Code>{doc.number}</Code>
                    </TextLink>
                    <span className="t-caption text-ink-3">{doc.kind === "challan" ? "Delivery challan" : "Pick list"}</span>
                  </div>
                  <Badge tone={DOC_STATUS_TONE[doc.status] ?? "neutral"} dot>
                    {humanise(doc.status)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>
      </div>

      <Feasibility order={order} />
    </div>
  );
}

/**
 * "Can we deliver this?" for the order's open product lines: a read-only check of stock, supply,
 * components and capacity. It never reserves, posts or saves. Shown to people who may run it.
 */
function Feasibility({ order }: { order: OrderDetail }) {
  const { permissionKeys } = useSession();
  const requested = order.requested_delivery_date ?? order.promised_date ?? null;
  const open = order.lines.filter((line) => line.product_key && line.line_kind !== "charge" && isPositiveDecimalStr(line.qty_remaining));
  const [needBy, setNeedBy] = useState<string | null>(requested);
  const [checking, setChecking] = useState<string | null>(null);
  if (!permissionKeys.has("production.feasibility.run") || open.length === 0) return null;
  return (
    <GlassPanel padding="lg" title="Can we deliver this?" titleAs="h2" className="rise" style={stagger(2)}>
      <div className="flex flex-col gap-5">
        <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
          <DatePicker
            label="Needed by"
            value={needBy}
            onChange={(value) => {
              setNeedBy(value);
              setChecking(null);
            }}
            help={requested ? "From the order. Change it to try another date." : "The order has no requested date. Choose one to check against."}
          />
          <p className="t-body-sm text-ink-3 md:pt-7">A read-only check against stock, purchases on the way, components and capacity. Nothing is reserved, posted or saved.</p>
        </div>
        <ul className="flex flex-col">
          {open.map((line) => (
            <li key={line.id} className="hairline-top flex flex-col gap-3 py-4 first:border-t-0 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="t-label text-ink">{line.description}</span>
                  <span className="t-caption text-ink-3">
                    <Code>{line.product_key}</Code> · <Qty value={{ value: line.qty_remaining, uom: line.unit }} /> still to go
                  </span>
                </div>
                <Button variant="secondary" size="sm" iconLeft="gauge" isDisabled={!needBy} onPress={() => setChecking(line.id)}>
                  Check this line
                </Button>
              </div>
              {checking === line.id && needBy ? <FeasibilityResult lineId={line.id} needBy={needBy} /> : null}
            </li>
          ))}
        </ul>
      </div>
    </GlassPanel>
  );
}

function FeasibilityResult({ lineId, needBy }: { lineId: string; needBy: string }) {
  const query = useQuery({ queryKey: queryKeys.production.feasibility(lineId, needBy), queryFn: ({ signal }) => fetchOrderLineFeasibility(lineId, needBy, signal) });
  if (query.isPending) return <SkeletonText lines={3} />;
  if (query.isError) return <ErrorBlock error={query.error} what="The delivery check" onRetry={() => void query.refetch()} />;
  return <Outcome result={query.data} />;
}

function Outcome({ result }: { result: FeasibilityRead }) {
  const outcome = OUTCOME[result.outcome] ?? { label: humanise(result.outcome), tone: "neutral" as Tone };
  return (
    <div className="rise-plain flex flex-col gap-3 rounded-md border border-line bg-surface p-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Badge tone={outcome.tone} dot>
          {outcome.label}
        </Badge>
        <span className="t-body-sm text-ink-2">
          <Qty value={{ value: result.from_stock, uom: result.uom_code }} className="t-label text-ink" /> from stock
          {isPositiveDecimalStr(result.to_make) ? (
            <>
              , <Qty value={{ value: result.to_make, uom: result.uom_code }} className="t-label text-ink" /> to make
            </>
          ) : null}
        </span>
        {result.earliest_completion ? (
          <span className="t-body-sm text-ink-3">
            Earliest completion <DateText value={result.earliest_completion} style="business" />
          </span>
        ) : null}
      </div>
      <ul aria-label="What the check found" className="flex flex-col gap-2">
        {result.evidence.map((item, index) => (
          <li key={`${item.kind}-${index}`} className="flex flex-wrap items-center gap-2">
            <Badge tone={EVIDENCE_TONE[item.status] ?? "neutral"} size="sm">
              {EVIDENCE_KIND[item.kind] ?? humanise(item.kind)}
            </Badge>
            <span className="t-body-sm text-ink-2">{item.label}</span>
          </li>
        ))}
      </ul>
      {result.missing_inputs.length > 0 ? <p className="t-caption text-ink-3">Missing from the records: {result.missing_inputs.join(", ")}.</p> : null}
    </div>
  );
}
