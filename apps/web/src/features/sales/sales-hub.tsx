"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { FactStrip, type Fact } from "@/components/ui/fact-strip";
import { RelativeTime } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { focusRingInsetClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { messageHref } from "@/lib/app-links";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { salesMessages as m } from "@/messages/sales";
import { fetchCustomerMessages, fetchEnquiries, fetchQuotes, fetchQuoteStatusCounts } from "./api";
import { enquiryListHref, messageListHref, quoteListHref } from "./list-state";
import { QuoteStatusPill } from "./quote-list";
import type { Enquiry, QuoteStatus, QuoteStatusCounts } from "./types";

const AREAS = [
  { href: "/sales/quotes", title: m.hub.quotes, hint: m.hub.quotesHint, permission: "sales.quote.read" },
  { href: "/sales/enquiries", title: m.hub.enquiries, hint: m.hub.enquiriesHint, permission: "sales.enquiry.read" },
  { href: "/sales/customer-messages", title: m.hub.messages, hint: m.hub.messagesHint, permission: "sales.customer_message.read" },
  { href: "/sales/parties", title: m.hub.customers, hint: m.hub.customersHint, permission: "parties.party.read" },
  { href: "/sales/custom-products", title: m.hub.customProducts, hint: m.hub.customProductsHint, permission: "sales.custom_product.read" },
  { href: "/sales/samples", title: m.hub.samples, hint: m.hub.samplesHint, permission: "sales.sample.read" },
] as const;

/** The statuses the strip shows, in flow order, when the server reports them. */
export const HUB_STATUSES: readonly QuoteStatus[] = ["draft", "internal_review", "sent", "won"];
export const NEEDS_YOU_LIMIT = 5;

/** The facts of the strip: only statuses the server returned, each linking to its filtered list. */
export function statusFacts(counts: QuoteStatusCounts, locale: string): Fact[] {
  return HUB_STATUSES.flatMap((status) => {
    const count = counts[status];
    return typeof count === "number"
      ? [{ label: m.status[status] ?? status, value: formatCount(count, locale), href: quoteListHref({ status, scope: "mine" }) }]
      : [];
  });
}

const ENQUIRY_TONE = { received: "info", assigned: "warning", quoted: "success", closed: "neutral" } as const;

/** Open enquiries: received or assigned, newest first, from the two status pages. */
export function openEnquiries(received: readonly Enquiry[], assigned: readonly Enquiry[]): Enquiry[] {
  const byId = new Map<string, Enquiry>();
  for (const enquiry of [...received, ...assigned]) if (enquiry.status === "received" || enquiry.status === "assigned") byId.set(enquiry.id, enquiry);
  return [...byId.values()].sort((a, b) => b.received_at.localeCompare(a.received_at));
}

/** The sales hub: my quotes by status, what needs me, and the areas this role can read. */
export function SalesHub() {
  const { permissionKeys, zone } = useSession();
  const canQuotes = permissionKeys.has("sales.quote.read");
  const canEnquiries = permissionKeys.has("sales.enquiry.read");
  const canMessages = permissionKeys.has("sales.customer_message.read");
  const areas = AREAS.filter((area) => permissionKeys.has(area.permission));

  const counts = useQuery({ queryKey: queryKeys.sales.statusCounts(), queryFn: ({ signal }) => fetchQuoteStatusCounts({ scope: "mine" }, signal), enabled: canQuotes });
  const reviewParams = { status: "internal_review", scope: "mine" as const, offset: 0 };
  const review = useQuery({ queryKey: queryKeys.sales.quotes(reviewParams), queryFn: ({ signal }) => fetchQuotes(reviewParams, signal), enabled: canQuotes });
  const messageParams = { status: "received", offset: 0 };
  const messages = useQuery({ queryKey: queryKeys.sales.messages(messageParams), queryFn: ({ signal }) => fetchCustomerMessages(messageParams, signal), enabled: canMessages });
  const receivedParams = { status: "received", offset: 0 };
  const assignedParams = { status: "assigned", offset: 0 };
  const received = useQuery({ queryKey: queryKeys.sales.enquiries(receivedParams), queryFn: ({ signal }) => fetchEnquiries(receivedParams, signal), enabled: canEnquiries });
  const assigned = useQuery({ queryKey: queryKeys.sales.enquiries(assignedParams), queryFn: ({ signal }) => fetchEnquiries(assignedParams, signal), enabled: canEnquiries });
  // Open enquiries span two status pages; the list is ready once both are, and fails if either does.
  const enquiries: NeedsQuery<Enquiry[]> = {
    isPending: received.isPending || assigned.isPending,
    isError: received.isError || assigned.isError,
    error: received.error ?? assigned.error,
    data: received.data && assigned.data ? openEnquiries(received.data.items, assigned.data.items) : undefined,
    refetch: () => Promise.all([received.refetch(), assigned.refetch()]),
  };

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title={m.hub.title}
        intro={m.hub.intro}
        nav={<AreaNav area="sales" label={m.hub.title} leading={[{ id: "sales", label: m.hub.overview, href: "/sales" }]} />}
        actions={
          permissionKeys.has("sales.quote.create") ? (
            <LinkButton href="/sales/quotes/new" variant="primary">
              {m.hub.newQuote}
            </LinkButton>
          ) : null
        }
      />

      {canQuotes ? (
        <section aria-label={m.hub.quotesByStatus} className="flex flex-col gap-3">
          {counts.isPending ? (
            <Loading label={m.hub.countsLoading} variant="inline" />
          ) : counts.isError ? (
            <ErrorState error={counts.error} what={m.hub.countsWhat} onRetry={() => void counts.refetch()} backToToday={false} compact />
          ) : (
            <FactStrip label={m.hub.quotesByStatus} facts={statusFacts(counts.data, zone.locale)} />
          )}
        </section>
      ) : null}

      {canQuotes || canMessages || canEnquiries ? (
        <section aria-labelledby="sales-needs-you" className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 id="sales-needs-you" className="text-lg font-[650] text-ink">
              {m.hub.needsYou}
            </h2>
            <p className="text-sm text-ink-muted">{m.hub.needsYouIntro}</p>
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {canQuotes ? (
              <NeedsList
                title={m.hub.reviewQuotes}
                what={m.hub.reviewQuotesWhat}
                allHref={quoteListHref({ status: "internal_review", scope: "mine" })}
                query={review}
                empty={m.hub.reviewQuotesEmpty}
                rows={(page) =>
                  page.items.slice(0, NEEDS_YOU_LIMIT).map((quote) => ({
                    id: quote.id,
                    href: quote.path,
                    title: quote.quote_number,
                    mono: true,
                    detail: quote.party.display_name,
                    status: <QuoteStatusPill status={quote.status} />,
                    at: quote.updated_at,
                  }))
                }
              />
            ) : null}
            {canMessages ? (
              <NeedsList
                title={m.hub.waitingMessages}
                what={m.hub.waitingMessagesWhat}
                allHref={messageListHref({ status: "received" })}
                query={messages}
                empty={m.hub.waitingMessagesEmpty}
                rows={(page) =>
                  page.items.slice(0, NEEDS_YOU_LIMIT).map((message) => ({
                    id: message.id,
                    href: messageHref(message.id),
                    title: message.party.display_name,
                    detail: message.subject ?? m.hub.noSubject,
                    status: <StatusPill tone="warning">{m.messages.waiting}</StatusPill>,
                    at: message.received_at,
                  }))
                }
              />
            ) : null}
            {canEnquiries ? (
              <NeedsList
                title={m.hub.openEnquiries}
                what={m.hub.openEnquiriesWhat}
                allHref={enquiryListHref({ status: "received" })}
                query={enquiries}
                empty={m.hub.openEnquiriesEmpty}
                rows={(open) =>
                  open.slice(0, NEEDS_YOU_LIMIT).map((enquiry) => ({
                    id: enquiry.id,
                    href: enquiry.path,
                    title: enquiry.enquiry_number,
                    mono: true,
                    detail: `${enquiry.party.display_name}${enquiry.subject ? ` · ${enquiry.subject}` : ""}`,
                    status: <StatusPill tone={ENQUIRY_TONE[enquiry.status]}>{m.enquiries.status[enquiry.status] ?? enquiry.status}</StatusPill>,
                    at: enquiry.received_at,
                  }))
                }
              />
            ) : null}
          </div>
        </section>
      ) : null}

      <section aria-labelledby="sales-areas" className="flex flex-col gap-3">
        <h2 id="sales-areas" className="text-lg font-[650] text-ink">
          {m.hub.areas}
        </h2>
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {areas.map((area) => (
            <li key={area.href} className="flex flex-col gap-1 rounded-lg border bg-surface p-4">
              <Link href={area.href} className="text-lg font-semibold">
                {area.title}
              </Link>
              <p className="text-sm text-ink-muted">{area.hint}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

interface NeedsRow {
  id: string;
  href: string;
  title: string;
  mono?: boolean;
  detail: string;
  status: ReactNode;
  at: string;
}

interface NeedsQuery<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

/** One compact list of "Needs you": loading, inline error, empty, or up to five linked rows. */
function NeedsList<T>({
  title,
  what,
  allHref,
  query,
  empty,
  rows,
}: {
  title: string;
  what: string;
  allHref: string;
  query: NeedsQuery<T>;
  empty: string;
  rows: (data: T) => NeedsRow[];
}) {
  const ready = !query.isPending && !query.isError && query.data !== undefined;
  const items = ready ? rows(query.data as T) : [];
  return (
    <section aria-label={title} className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-base font-semibold text-ink">{title}</h3>
        <Link href={allHref} className="text-sm">
          {m.hub.allOf(title)}
        </Link>
      </div>
      {query.isError ? (
        <ErrorState error={query.error} what={what} onRetry={() => void query.refetch()} backToToday={false} headingLevel={3} compact />
      ) : !ready ? (
        <Loading label={what} variant="list" rows={2} />
      ) : items.length === 0 ? (
        <EmptyState title={m.hub.emptyTitle} headingLevel={3}>
          {empty}
        </EmptyState>
      ) : (
        <ul className="flex flex-col divide-y rounded-lg border bg-surface">
          {items.map((row) => (
            <li key={row.id}>
              <RacLink href={row.href} className={`flex min-h-14 flex-col justify-center gap-1 px-4 py-3 ${focusRingInsetClasses}`}>
                <span className="flex items-start justify-between gap-3">
                  <span className={`min-w-0 font-semibold text-ink ${row.mono ? "font-mono" : ""}`}>{row.title}</span>
                  {row.status}
                </span>
                <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm text-ink-muted">
                  <span className="min-w-0 truncate">{row.detail}</span>
                  <RelativeTime value={row.at} />
                </span>
              </RacLink>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
