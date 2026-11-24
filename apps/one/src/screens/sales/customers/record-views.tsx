"use client";

import type { Route } from "next";
import type { ReactNode } from "react";
import type { OrderPage, OrderSummary } from "@/features/orders/api";
import { addressLines } from "@/features/parties/form-model";
import type { Address, Contact, PartyDetail } from "@/features/parties/types";
import { quoteListHref } from "@/features/sales/list-state";
import type { Page as PageOf, QuoteSummary } from "@/features/sales/types";
import type { Sample } from "@/features/samples/api";
import { QueryView } from "~/shell/states";
import {
  Avatar,
  Badge,
  Button,
  ButtonLink,
  Code,
  CountUp,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Icon,
  KeyValue,
  Money,
  Qty,
  Skeleton,
  StatTile,
  TableFooter,
  TextLink,
  type Column,
} from "~/ui";
import { SAMPLE_STATUS_LABEL, SAMPLE_STATUS_TONE } from "../samples/labels";
import {
  countryName,
  customerHref,
  ORDER_STATUS_LABEL,
  ORDER_STATUS_TONE,
  QUOTE_STATUS_LABEL,
  QUOTE_STATUS_TONE,
  TAX_SCHEME_LABEL,
  humanise,
  stagger,
} from "./labels";
import { countOf, nextStepFor, type NextStep } from "./overview-model";

interface QueryLike<T> {
  data: T | undefined;
  error: unknown;
  isPending: boolean;
  isError: boolean;
  refetch: () => unknown;
}

const sampleHref = (id: string) => `/sales/samples/${encodeURIComponent(id)}` as Route;
const orderHref = (id: string) => `/sales/orders/${encodeURIComponent(id)}` as Route;

// ---- overview -----------------------------------------------------------------------------------

function StatValue({ value }: { value: number | undefined }) {
  return value === undefined ? <Skeleton width={36} height={28} /> : <CountUp value={value} />;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function NextStepPanel({ step, fallbackAction }: { step: NextStep; fallbackAction?: ReactNode }) {
  return (
    <GlassPanel as="section" padding="lg" variant="strong" className="rise flex flex-col gap-4" aria-label="Next step">
      <div className="flex items-start gap-4">
        <span className="grid size-11 flex-none place-items-center rounded-lg bg-gold-soft text-gold-strong">
          <Icon name={step.icon} size={20} />
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <p className="t-overline text-gold-strong">Next step</p>
          <h2 className="t-display-sm">{step.title}</h2>
          <p className="t-body text-ink-2">{step.text}</p>
        </div>
      </div>
      {step.action ? (
        <div>
          <ButtonLink variant="inverse" href={step.action.href as Route} iconRight="arrowRight">
            {step.action.label}
          </ButtonLink>
        </div>
      ) : fallbackAction ? (
        <div>{fallbackAction}</div>
      ) : null}
    </GlassPanel>
  );
}

function ReachThem({ party }: { party: PartyDetail }) {
  const primary = party.contacts.find((contact) => contact.is_primary) ?? party.contacts[0] ?? null;
  const address = party.addresses.find((entry) => entry.is_default) ?? party.addresses[0] ?? null;
  return (
    <GlassPanel
      as="section"
      title="How to reach them"
      titleAs="h2"
      action={
        <TextLink href={customerHref(party.id, "contacts") as Route} className="t-body-sm">
          All contacts
        </TextLink>
      }
      className="flex flex-col gap-4"
    >
      {primary ? (
        <div className="flex min-w-0 items-start gap-3">
          <Avatar name={primary.name} />
          <ContactLines contact={primary} />
        </div>
      ) : (
        <p className="t-body-sm text-ink-3">No contact on file yet.</p>
      )}
      {address ? (
        <div className="hairline-top flex items-start gap-3 pt-4">
          <span className="mt-0.5 text-ink-3">
            <Icon name="mapPin" size={16} />
          </span>
          <AddressLines address={address} />
        </div>
      ) : null}
    </GlassPanel>
  );
}

export function OverviewView({
  party,
  quotes,
  samples,
  orders,
  quoteCounts,
  sampleCounts,
  can,
  createQuote,
}: {
  party: PartyDetail;
  quotes: QueryLike<PageOf<QuoteSummary>> | null;
  samples: QueryLike<{ items: Sample[]; total: number }> | null;
  orders: QueryLike<OrderPage> | null;
  quoteCounts: Readonly<Record<string, number | undefined>> | undefined;
  sampleCounts: Readonly<Record<string, number | undefined>> | undefined;
  can: { createQuote: boolean };
  /** The record's own "Create quotation" link, repeated in the next-step panel for a lead. */
  createQuote?: ReactNode;
}) {
  const waiting = [quotes, samples, orders].some((query) => query?.isPending);
  const step = nextStepFor(party, { quotes: quotes?.data?.items, samples: samples?.data?.items, orders: orders?.data?.items }, can);
  const quotesOpen = countOf(quoteCounts, ["sent", "revised"]);
  const samplesOut = countOf(sampleCounts, ["requested", "dispatched", "delivered"]);
  const ordersRunning = orders?.data ? orders.data.items.filter((order) => order.status === "confirmed" || order.status === "on_hold").length : undefined;
  const latest = quotes?.data?.items.slice(0, 4) ?? [];

  return (
    <div className="split">
      <div className="stack">
        {waiting ? (
          <GlassPanel padding="lg" variant="strong" className="flex flex-col gap-3" role="status" aria-label="Working out the next step">
            <Skeleton width={90} height={10} />
            <Skeleton width="60%" height={26} />
            <Skeleton width="80%" />
          </GlassPanel>
        ) : (
          <NextStepPanel step={step} fallbackAction={party.status === "prospect" && !party.archived_at ? createQuote : undefined} />
        )}

        <div className="tiles">
          {quotes ? (
            <GlassPanel interactive className="rise" style={stagger(1)}>
              <StatTile
                label="Quotations"
                value={<StatValue value={countOf(quoteCounts, Object.keys(quoteCounts ?? {}))} />}
                foot={quotesOpen === undefined ? undefined : quotesOpen > 0 ? `${quotesOpen} awaiting their reply` : "None awaiting a reply"}
                dot={Boolean(quotesOpen)}
                href={customerHref(party.id, "quotations") as Route}
              />
            </GlassPanel>
          ) : null}
          {samples ? (
            <GlassPanel interactive className="rise" style={stagger(2)}>
              <StatTile
                label="Samples"
                value={<StatValue value={countOf(sampleCounts, Object.keys(sampleCounts ?? {}))} />}
                foot={samplesOut === undefined ? undefined : samplesOut > 0 ? `${samplesOut} still in progress` : "None in progress"}
                dot={Boolean(samplesOut)}
                href={customerHref(party.id, "samples") as Route}
              />
            </GlassPanel>
          ) : null}
          {orders ? (
            <GlassPanel interactive className="rise" style={stagger(3)}>
              <StatTile
                label="Orders"
                value={<StatValue value={orders.data?.total} />}
                foot={ordersRunning === undefined ? undefined : ordersRunning > 0 ? `${ordersRunning} in progress` : "None in progress"}
                dot={Boolean(ordersRunning)}
                href={customerHref(party.id, "orders") as Route}
              />
            </GlassPanel>
          ) : null}
        </div>

        {quotes && latest.length > 0 ? (
          <GlassPanel
            as="section"
            title="Latest quotations"
            titleAs="h2"
            className="rise"
            style={stagger(4)}
            action={
              <TextLink href={customerHref(party.id, "quotations") as Route} className="t-body-sm">
                All {quotes.data?.total ?? ""} quotations
              </TextLink>
            }
          >
            <ul className="m-0 flex list-none flex-col p-0">
              {latest.map((quote) => (
                <li key={quote.id} className="relative flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-line py-3 [&:not(:first-child)]:border-t">
                  <span className="flex min-w-0 flex-col">
                    <TextLink href={quote.path as Route} className="stretched t-label lk-mono">
                      {quote.quote_number}
                    </TextLink>
                    <span className="t-caption text-ink-3">
                      {plural(quote.line_count, "line", "lines")} · changed <DateText value={quote.updated_at} style="relative" />
                    </span>
                  </span>
                  <span className="flex flex-none items-center gap-3">
                    <Money value={quote.grand_total} />
                    <Badge tone={QUOTE_STATUS_TONE[quote.status] ?? "neutral"} dot>
                      {QUOTE_STATUS_LABEL[quote.status] ?? humanise(quote.status)}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </GlassPanel>
        ) : null}
      </div>

      <aside className="stack">
        <div className="rise" style={stagger(2)}>
          <ReachThem party={party} />
        </div>
        <GlassPanel as="section" title="On file" titleAs="h2" className="rise" style={stagger(3)}>
          <KeyValue
            rows
            items={[
              { label: "Customer number", value: party.party_number, mono: true },
              { label: "Legal name", value: party.legal_name },
              { label: "Looked after by", value: party.owner.display_name },
              { label: "Added", value: <DateText value={party.created_at} /> },
              { label: "Last change", value: <DateText value={party.updated_at} style="relative" /> },
              { label: "Tax numbers", value: party.tax_identifiers.length > 0 ? plural(party.tax_identifiers.length, "on file", "on file") : "None on file" },
            ]}
          />
        </GlassPanel>
      </aside>
    </div>
  );
}

// ---- contacts and addresses -------------------------------------------------------------------------

function ContactLines({ contact }: { contact: Contact }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className="flex flex-wrap items-center gap-2">
        <span className="t-label text-ink">{contact.name}</span>
        {contact.is_primary ? (
          <Badge tone="gold" size="sm">
            Main contact
          </Badge>
        ) : null}
      </p>
      {contact.job_title ? <p className="t-body-sm text-ink-3">{contact.job_title}</p> : null}
      {contact.email ? (
        <a href={`mailto:${contact.email}`} className="lk-link t-body-sm inline-flex min-w-0 items-center gap-2 break-all">
          <Icon name="mail" size={14} />
          {contact.email}
        </a>
      ) : null}
      {contact.phone ? (
        <a href={`tel:${contact.phone.replace(/[^\d+]/g, "")}`} className="lk-link t-body-sm lk-tnum inline-flex items-center gap-2">
          <Icon name="phone" size={14} />
          {contact.phone}
        </a>
      ) : null}
    </div>
  );
}

function AddressLines({ address }: { address: Address }) {
  const lines = addressLines(address);
  return (
    <address className="t-body-sm min-w-0 not-italic text-ink-2 [overflow-wrap:anywhere]">
      {lines.map((line, index) => (
        <span key={`${index}-${line}`} className="block">
          {index === lines.length - 1 && /^[A-Z]{2}$/.test(line) ? (countryName(line) ?? line) : line}
        </span>
      ))}
    </address>
  );
}

export function ContactsView({ party, onAddContact }: { party: PartyDetail; onAddContact?: () => void }) {
  const contacts = [...party.contacts].sort((a, b) => (a.is_primary === b.is_primary ? a.name.localeCompare(b.name) : a.is_primary ? -1 : 1));
  const groups = (["billing", "shipping"] as const)
    .map((kind) => ({ kind, items: party.addresses.filter((address) => address.kind === kind).sort((a, b) => (a.is_default === b.is_default ? 0 : a.is_default ? -1 : 1)) }))
    .filter((group) => group.items.length > 0);
  const addButton = onAddContact ? (
    <Button variant="secondary" size="sm" iconLeft="plus" onPress={onAddContact}>
      Add contact
    </Button>
  ) : undefined;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
      <GlassPanel as="section" padding="lg" title="People" titleAs="h2" action={contacts.length > 0 ? addButton : undefined} className="rise lg:row-span-2">
        {contacts.length === 0 ? (
          <EmptyState compact icon="userPlus" title="No one to call yet" text="Add the person the team should speak to first." actions={addButton} />
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {contacts.map((contact, index) => (
              <li key={contact.id} className="rise-plain flex min-w-0 items-start gap-3 border-line py-4 first:pt-0 last:pb-0 [&:not(:first-child)]:border-t" style={stagger(index)}>
                <Avatar name={contact.name} />
                <ContactLines contact={contact} />
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <GlassPanel as="section" padding="lg" title="Addresses" titleAs="h2" className="rise" style={stagger(1)}>
        {groups.length === 0 ? (
          <EmptyState compact icon="mapPin" title="No address on file" text="A billing address is added when the customer is created. Shipping addresses come from their orders." />
        ) : (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            {groups.map((group) => (
              <div key={group.kind} className="flex min-w-0 flex-col gap-3">
                <h3 className="t-overline text-ink-3">{group.kind === "billing" ? "Billing" : "Shipping"}</h3>
                {group.items.map((address) => (
                  <div key={address.id} className="flex flex-col items-start gap-2">
                    <AddressLines address={address} />
                    {address.is_default ? (
                      <Badge size="sm" outline>
                        Default
                      </Badge>
                    ) : null}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </GlassPanel>

      <GlassPanel as="section" padding="lg" title="Tax numbers" titleAs="h2" className="rise" style={stagger(2)}>
        {party.tax_identifiers.length === 0 ? (
          <p className="t-body-sm text-ink-3">No GSTIN, VAT or other tax number is on file for this customer.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {party.tax_identifiers.map((identifier) => (
              <li key={identifier.id} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 border-line py-3 first:pt-0 last:pb-0 [&:not(:first-child)]:border-t">
                <span className="t-label w-16 flex-none text-ink-3">{TAX_SCHEME_LABEL[identifier.scheme] ?? identifier.scheme.toUpperCase()}</span>
                <Code>{identifier.value}</Code>
                {identifier.country_code ? <span className="t-caption text-ink-3">{countryName(identifier.country_code)}</span> : null}
                <Badge size="sm" outline>
                  Not verified
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </div>
  );
}

// ---- quotations, samples, orders ----------------------------------------------------------------------

const QUOTE_COLUMNS: Column<QuoteSummary>[] = [
  {
    key: "number",
    header: "Quotation",
    primary: true,
    cell: (quote) => (
      <span className="flex flex-col">
        <Code>{quote.quote_number}</Code>
        {quote.customer_reference ? <span className="t-caption text-ink-3">Their ref {quote.customer_reference}</span> : null}
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    cell: (quote) => (
      <Badge tone={QUOTE_STATUS_TONE[quote.status] ?? "neutral"} dot>
        {QUOTE_STATUS_LABEL[quote.status] ?? humanise(quote.status)}
      </Badge>
    ),
  },
  { key: "lines", header: "Lines", numeric: true, hideOnMobile: true, cell: (quote) => quote.line_count },
  { key: "total", header: "Total", numeric: true, cell: (quote) => <Money value={quote.grand_total} /> },
  { key: "valid", header: "Valid until", hideOnMobile: true, cell: (quote) => <DateText value={quote.valid_until} style="business" /> },
  { key: "updated", header: "Last change", mobileLabel: "Last change", cell: (quote) => <DateText value={quote.updated_at} style="relative" className="text-ink-3" /> },
];

export function QuotationsView({ party, query, create }: { party: PartyDetail; query: QueryLike<PageOf<QuoteSummary>>; create?: ReactNode }) {
  return (
    <QueryView query={query} what="Quotations" loading={<TableSkeleton label="Quotations" columns={QUOTE_COLUMNS} />}>
      {(page) => (
        <GlassPanel padding="none" className="rise">
          <DataTable
            label={`Quotations for ${party.display_name}`}
            columns={QUOTE_COLUMNS}
            rows={page.items}
            rowKey={(quote) => quote.id}
            rowHref={(quote) => quote.path as Route}
            empty={<EmptyState icon="fileText" title="Nothing offered yet" text={`Every price you offer ${party.display_name} will be listed here, newest first.`} actions={create} />}
            footer={
              page.items.length > 0 ? (
                <TableFooter
                  left={<span className="t-caption text-ink-3">{page.total > page.items.length ? `The newest ${page.items.length} of ${page.total}` : plural(page.total, "quotation", "quotations")}</span>}
                  right={
                    <TextLink href={quoteListHref({ q: party.display_name, scope: "all" }) as Route} className="t-body-sm">
                      Open in Quotations
                    </TextLink>
                  }
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </QueryView>
  );
}

const SAMPLE_COLUMNS: Column<Sample>[] = [
  {
    key: "number",
    header: "Sample",
    primary: true,
    cell: (sample) => (
      <span className="flex min-w-0 flex-col">
        <Code>{sample.sample_number}</Code>
        <span className="t-caption truncate text-ink-3" title={sample.description}>
          {sample.description}
        </span>
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    cell: (sample) => (
      <Badge tone={SAMPLE_STATUS_TONE[sample.status] ?? "neutral"} dot>
        {SAMPLE_STATUS_LABEL[sample.status] ?? humanise(sample.status)}
      </Badge>
    ),
  },
  { key: "qty", header: "Quantity", numeric: true, cell: (sample) => <Qty value={{ value: sample.quantity, uom: sample.unit_code }} /> },
  { key: "requested", header: "Requested", cell: (sample) => <DateText value={sample.requested_on} style="business" /> },
  { key: "courier", header: "Courier or reference", hideOnMobile: true, cell: (sample) => sample.dispatch_reference ?? "" },
];

export function SamplesView({ party, query, create }: { party: PartyDetail; query: QueryLike<{ items: Sample[]; total: number }>; create?: ReactNode }) {
  return (
    <QueryView query={query} what="Samples" loading={<TableSkeleton label="Samples" columns={SAMPLE_COLUMNS} />}>
      {(page) => (
        <GlassPanel padding="none" className="rise">
          <DataTable
            label={`Samples sent to ${party.display_name}`}
            columns={SAMPLE_COLUMNS}
            rows={page.items}
            rowKey={(sample) => sample.id}
            rowHref={(sample) => sampleHref(sample.id)}
            empty={
              <EmptyState
                icon="packageOpen"
                title="No samples sent yet"
                text={`When ${party.display_name} asks to see a product, add the sample here and follow it until they answer.`}
                actions={create}
              />
            }
            footer={
              page.items.length > 0 ? (
                <TableFooter
                  left={<span className="t-caption text-ink-3">{page.total > page.items.length ? `The newest ${page.items.length} of ${page.total}` : plural(page.total, "sample", "samples")}</span>}
                  right={create}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </QueryView>
  );
}

const ORDER_COLUMNS: Column<OrderSummary>[] = [
  {
    key: "number",
    header: "Order",
    primary: true,
    cell: (order) => (
      <span className="flex flex-col">
        <Code>{order.order_number}</Code>
        <span className="t-caption text-ink-3">{plural(order.line_count, "line", "lines")}</span>
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    cell: (order) => (
      <Badge tone={ORDER_STATUS_TONE[order.status] ?? "neutral"} dot>
        {ORDER_STATUS_LABEL[order.status] ?? humanise(order.status)}
      </Badge>
    ),
  },
  { key: "shipped", header: "Shipped", hideOnMobile: true, cell: (order) => (order.fulfilment_state === "complete" ? "In full" : order.fulfilment_state === "partial" ? "In part" : "Not yet") },
  { key: "total", header: "Total", numeric: true, cell: (order) => <Money value={order.total} /> },
  { key: "date", header: "Ordered", cell: (order) => <DateText value={order.order_date} style="business" /> },
  { key: "promised", header: "Promised", hideOnMobile: true, cell: (order) => <DateText value={order.promised_date} style="business" /> },
];

export function OrdersView({ party, query }: { party: PartyDetail; query: QueryLike<OrderPage> }) {
  return (
    <QueryView query={query} what="Orders" loading={<TableSkeleton label="Orders" columns={ORDER_COLUMNS} />}>
      {(page) => (
        <GlassPanel padding="none" className="rise">
          <DataTable
            label={`Orders from ${party.display_name}`}
            columns={ORDER_COLUMNS}
            rows={page.items}
            rowKey={(order) => order.id}
            rowHref={(order) => orderHref(order.id)}
            empty={<EmptyState icon="cart" title="Nothing bought yet" text="An order appears here when one of their quotations is won and converted." />}
            footer={
              page.items.length > 0 ? (
                <TableFooter left={<span className="t-caption text-ink-3">{page.total > page.items.length ? `The newest ${page.items.length} of ${page.total}` : plural(page.total, "order", "orders")}</span>} />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </QueryView>
  );
}

function TableSkeleton<Row>({ label, columns }: { label: string; columns: readonly Column<Row>[] }) {
  return (
    <GlassPanel padding="none">
      <DataTable label={label} columns={columns} rows={[]} rowKey={() => ""} loading skeletonRows={5} />
    </GlassPanel>
  );
}
