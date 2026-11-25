"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { fetchCustomerMessages, fetchEnquiries, fetchQuotes, fetchQuoteStatusCounts } from "@/features/sales/api";
import { enquiryListHref, messageListHref, quoteListHref } from "@/features/sales/list-state";
import { fetchSamples } from "@/features/samples/api";
import { sampleListHref } from "@/features/samples/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { messageHref } from "@/lib/app-links";
import { canAccessRoute, matchRoute } from "~/lib/routes";
import { useSession } from "@/lib/session/context";
import { useLeads, useLeadSummary } from "~/data/leads";
import { useOrderCount } from "~/data/sales-crm";
import { leadListHref } from "../leads/list-state";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { Badge, Banner, Button, ButtonLink, CountUp, DateText, EmptyState, GlassPanel, Icon, Skeleton, StatTile, type IconName, type Tone } from "~/ui";
import { stagger } from "../customers/labels";

/** How many rows each source may add to "Needs attention", and the most the list shows. */
const PER_SOURCE = 3;
const ATTENTION_LIMIT = 8;

interface AttentionRow {
  id: string;
  kind: string;
  icon: IconName;
  title: string;
  detail: string;
  /** What to do about it, as the badge. */
  ask: string;
  tone: Tone;
  at: string;
  href: string;
  mono?: boolean;
}

const SCREENS: { href: string; path: string; label: string; icon: IconName; line: string }[] = [
  { href: "/sales/parties?status=prospect", path: "/sales/parties", label: "Leads", icon: "userPlus", line: "People who have asked but not yet bought or received a sample." },
  { href: "/sales/parties?status=active", path: "/sales/parties", label: "Customers", icon: "users", line: "One profile each: contacts, quotations, samples and orders." },
  { href: "/sales/enquiries", path: "/sales/enquiries", label: "Enquiries", icon: "mail", line: "Incoming requests, from received to quoted or closed." },
  { href: "/sales/quotes", path: "/sales/quotes", label: "Quotations", icon: "fileText", line: "Every price you have offered, and where each one stands." },
  { href: "/sales/orders", path: "/sales/orders", label: "Orders", icon: "cart", line: "Won quotations, confirmed and followed to dispatch." },
  { href: "/sales/samples", path: "/sales/samples", label: "Samples", icon: "packageOpen", line: "Samples taken from stock for customers, until they answer." },
  { href: "/sales/custom-products", path: "/sales/custom-products", label: "Custom products", icon: "shapes", line: "Made-to-order pieces, apart from the catalogue." },
  { href: "/sales/customer-messages", path: "/sales/customer-messages", label: "Messages", icon: "message", line: "What customers have written, with the unanswered first." },
];

function StatFigure({ value }: { value: number | undefined }) {
  return value === undefined ? <Skeleton width={44} height={32} /> : <CountUp value={value} />;
}

/** The sales overview: the numbers that matter, what is waiting, and the way into each screen. */
export function SalesHub() {
  const { permissionKeys, user } = useSession() as ReturnType<typeof useSession> & { user?: { display_name?: string | null } };
  const can = (path: string) => {
    const route = matchRoute(path);
    return route !== null && canAccessRoute(route, permissionKeys);
  };
  const canQuotes = permissionKeys.has("sales.quote.read");
  const canEnquiries = permissionKeys.has("sales.enquiry.read");
  const canMessages = permissionKeys.has("sales.customer_message.read");
  const canSamples = permissionKeys.has("sales.sample.read");
  const canOrders = permissionKeys.has("orders.sales_order.read");

  const counts = useQuery({ queryKey: queryKeys.sales.statusCounts(), queryFn: ({ signal }) => fetchQuoteStatusCounts({ scope: "mine" }, signal), enabled: canQuotes });
  const reviewParams = { status: "internal_review", scope: "mine" as const, offset: 0 };
  const review = useQuery({ queryKey: queryKeys.sales.quotes(reviewParams), queryFn: ({ signal }) => fetchQuotes(reviewParams, signal), enabled: canQuotes });
  const messageParams = { status: "received", offset: 0 };
  const messages = useQuery({ queryKey: queryKeys.sales.messages(messageParams), queryFn: ({ signal }) => fetchCustomerMessages(messageParams, signal), enabled: canMessages });
  const receivedParams = { status: "received", offset: 0 };
  const assignedParams = { status: "assigned", offset: 0 };
  const received = useQuery({ queryKey: queryKeys.sales.enquiries(receivedParams), queryFn: ({ signal }) => fetchEnquiries(receivedParams, signal), enabled: canEnquiries });
  const assigned = useQuery({ queryKey: queryKeys.sales.enquiries(assignedParams), queryFn: ({ signal }) => fetchEnquiries(assignedParams, signal), enabled: canEnquiries });
  const deliveredParams = { status: "delivered", offset: 0 };
  const delivered = useQuery({ queryKey: queryKeys.sales.samples(deliveredParams), queryFn: ({ signal }) => fetchSamples(deliveredParams, signal), enabled: canSamples });
  const requestedParams = { status: "requested", offset: 0 };
  const requested = useQuery({ queryKey: queryKeys.sales.samples(requestedParams), queryFn: ({ signal }) => fetchSamples(requestedParams, signal), enabled: canSamples });
  const ordersConfirmed = useOrderCount("confirmed", canOrders);
  const canLeads = permissionKeys.has("parties.party.read");
  const leadSummary = useLeadSummary(canLeads);
  const overdueLeads = useLeads({ follow_up: "overdue", sort: "follow_up" });

  const sources = [
    ...(canLeads ? [overdueLeads] : []),
    ...(canMessages ? [messages] : []),
    ...(canEnquiries ? [received, assigned] : []),
    ...(canQuotes ? [review] : []),
    ...(canSamples ? [delivered, requested] : []),
  ];
  const attentionLoading = sources.some((source) => source.isPending);
  const failed = sources.filter((source) => source.isError);

  const rows: AttentionRow[] = [
    ...(canLeads ? (overdueLeads.data?.items ?? []) : []).slice(0, PER_SOURCE).map<AttentionRow>((lead) => ({
      id: `lead-${lead.id}`,
      kind: "Follow-up",
      icon: "phone",
      title: lead.display_name,
      detail: `${lead.party_number}${lead.primary_contact ? ` · ${lead.primary_contact}` : ""}`,
      ask: "Follow up",
      tone: "amber",
      at: lead.next_follow_up_on ?? lead.updated_at,
      href: lead.path,
    })),
    ...(messages.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((message) => ({
      id: `message-${message.id}`,
      kind: "Message",
      icon: "message",
      title: message.party.display_name,
      detail: message.subject ?? "No subject",
      ask: "Reply",
      tone: "amber",
      at: message.received_at,
      href: messageHref(message.id),
    })),
    ...(received.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((enquiry) => ({
      id: `enquiry-${enquiry.id}`,
      kind: "Enquiry",
      icon: "mail",
      title: enquiry.subject ?? enquiry.enquiry_number,
      detail: `${enquiry.party.display_name} · ${enquiry.enquiry_number}`,
      ask: "Pick up",
      tone: "amber",
      at: enquiry.received_at,
      href: enquiry.path,
    })),
    ...(review.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((quote) => ({
      id: `quote-${quote.id}`,
      kind: "Quotation",
      icon: "fileText",
      title: quote.quote_number,
      detail: quote.party.display_name,
      ask: "In review",
      tone: "cobalt",
      at: quote.updated_at,
      href: quote.path,
      mono: true,
    })),
    ...(delivered.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((sample) => ({
      id: `sample-${sample.id}`,
      kind: "Sample",
      icon: "packageOpen",
      title: sample.description || sample.sample_number,
      detail: `${sample.party.display_name} · ${sample.sample_number}`,
      ask: "Ask for feedback",
      tone: "amber",
      at: sample.delivered_at ?? sample.updated_at,
      href: `/sales/samples/${encodeURIComponent(sample.id)}`,
    })),
    ...(requested.data?.items ?? []).slice(0, PER_SOURCE).map<AttentionRow>((sample) => ({
      id: `sample-${sample.id}`,
      kind: "Sample",
      icon: "truck",
      title: sample.description || sample.sample_number,
      detail: `${sample.party.display_name} · ${sample.sample_number}`,
      ask: "Dispatch",
      tone: "amber",
      at: sample.updated_at,
      href: `/sales/samples/${encodeURIComponent(sample.id)}`,
    })),
  ].slice(0, ATTENTION_LIMIT);

  const openEnquiries = received.data && assigned.data ? received.data.total + assigned.data.total : undefined;
  const awaitingReply = counts.data ? (counts.data.sent ?? 0) + (counts.data.revised ?? 0) : undefined;
  const inReview = counts.data?.internal_review ?? 0;
  const drafts = counts.data?.draft ?? 0;

  const tiles: ReactNode[] = [];
  if (canLeads && leadSummary.data) {
    const due = leadSummary.data.follow_ups_overdue + leadSummary.data.follow_ups_today;
    tiles.push(
      <StatTile
        key="leads"
        label="Lead follow-ups due"
        value={<StatFigure value={due} />}
        foot={`${leadSummary.data.open} open leads · ${leadSummary.data.conversion_rate}% won`}
        dot={leadSummary.data.follow_ups_overdue > 0}
        href={leadListHref({ follow_up: leadSummary.data.follow_ups_overdue > 0 ? "overdue" : "today" }) as Route}
      />,
    );
  }
  if (canEnquiries) {
    tiles.push(
      <StatTile
        key="enquiries"
        label="Open enquiries"
        value={<StatFigure value={openEnquiries} />}
        foot={received.data ? (received.data.total > 0 ? `${received.data.total} not picked up yet` : "All picked up") : undefined}
        dot={Boolean(received.data?.total)}
        href={enquiryListHref({ status: "received" }) as Route}
      />,
    );
  }
  if (canQuotes) {
    tiles.push(
      <StatTile
        key="quotes"
        label="Quotations awaiting a reply"
        value={<StatFigure value={awaitingReply} />}
        foot={counts.data ? (inReview > 0 ? `${inReview} more in review` : drafts > 0 ? `${drafts} still in draft` : "Yours, sent to customers") : undefined}
        href={quoteListHref({ status: "sent", scope: "mine" }) as Route}
      />,
    );
  }
  if (canOrders) {
    tiles.push(<StatTile key="orders" label="Orders in progress" value={<StatFigure value={ordersConfirmed.data} />} foot="Confirmed, not yet completed" href={"/sales/orders?status=confirmed" as Route} />);
  }
  if (canMessages) {
    tiles.push(
      <StatTile
        key="messages"
        label="Messages waiting"
        value={<StatFigure value={messages.data?.total} />}
        foot={messages.data ? (messages.data.total > 0 ? "Customers without an answer" : "Everyone has an answer") : undefined}
        dot={Boolean(messages.data?.total)}
        href={messageListHref({ status: "received" }) as Route}
      />,
    );
  }
  if (tiles.length < 4 && canSamples) {
    tiles.push(
      <StatTile
        key="samples"
        label="Samples awaiting feedback"
        value={<StatFigure value={delivered.data?.total} />}
        foot={requested.data ? `${requested.data.total} waiting to leave stock` : undefined}
        href={sampleListHref({ status: "delivered" }) as Route}
      />,
    );
  }

  const screens = SCREENS.filter((screen) => can(screen.path));
  const firstName = user?.display_name?.split(" ")[0];

  return (
    <Page>
      <PageHeader
        display
        eyebrow={firstName ? `Sales · ${firstName}` : "Sales"}
        title={
          <>
            From first enquiry to <em>confirmed</em> order
          </>
        }
        lead="Where your enquiries, quotations, samples and orders stand today, and what is waiting on you."
        actions={
          permissionKeys.has("sales.quote.create") ? (
            <ButtonLink href={"/sales/quotes/new" as Route} iconLeft="plus">
              Create quotation
            </ButtonLink>
          ) : null
        }
      />

      {tiles.length > 0 ? (
        <div className="tiles" aria-label="Sales at a glance" role="group">
          {tiles.slice(0, 4).map((tile, index) => (
            <GlassPanel key={index} interactive className="rise" style={stagger(index + 1)}>
              {tile}
            </GlassPanel>
          ))}
        </div>
      ) : null}

      {sources.length > 0 ? (
        <PageSection title="Needs attention" description="The oldest promises first: messages without a reply, enquiries nobody has picked up, samples that need a nudge." index={1}>
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
              <EmptyState compact icon="checkCircle" title="Nothing is waiting on you" text="No unanswered message, no unassigned enquiry, no sample to chase. New ones appear here first." />
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
                    <span className="hidden flex-none sm:block">
                      <Badge tone={row.tone} size="sm">
                        {row.ask}
                      </Badge>
                    </span>
                    <DateText value={row.at} style="relative" className="t-caption flex-none text-ink-3" />
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>
        </PageSection>
      ) : null}

      <PageSection title="Everything in sales" index={2}>
        <ul className="tiles m-0 list-none p-0" data-min="lg">
          {screens.map((screen, index) => (
            <GlassPanel as="li" key={screen.href} variant="outline" interactive className="rise-plain flex items-start gap-4" style={stagger(index)}>
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
