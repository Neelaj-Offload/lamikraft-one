"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { fetchQuote, fetchQuoteHistory } from "@/features/sales/api";
import type { QuoteDetail } from "@/features/sales/types";
import { useQuoteCommand } from "@/features/sales/use-quote-command";
import { isEditable, reviewReasonsText } from "@/features/sales/workspace-model";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, humanise, quotationStatus, useQuotationOrder } from "~/data/sales-deals";
import { Page, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Money,
  Skeleton,
  SkeletonText,
  Tabs,
  TextLink,
  Timeline,
  type IconName,
  type TimelineItem,
} from "~/ui";
import { DocumentsView } from "./documents-view";
import { LinesView } from "./lines-view";
import { StatusBadge, Steps, type StepItem } from "./parts";
import { useQuotationActions, type QuotationActions } from "./quotation-actions";
import { TermsView, useTermsDraft } from "./terms-view";
import { QuotationTotals } from "./totals";
import { viewHref, type QuotationView } from "./views";

const ORIGIN: Record<string, string> = { agent: "Drafted by Lamikraft, the assistant", import: "Imported", migration: "Migrated from the old portal" };
const REASON: Record<string, string> = { price_override: "a changed price", discount: "a discount", below_minimum: "a total below the order minimum" };

/** A quotation: where it stands, its lines, terms, documents and history, each in its own view. */
export function QuotationRecord({ quoteId, view }: { quoteId: string; view: QuotationView }) {
  const query = useQuery({ queryKey: queryKeys.sales.quote(quoteId), queryFn: ({ signal }) => fetchQuote(quoteId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the quotation">
          <Skeleton width="160px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the quotation" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This quotation" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href="/sales/quotes" variant="secondary" iconLeft="arrowLeft">
            All quotations
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded quote={query.data} view={view} />;
}

type Order = ReturnType<typeof useQuotationOrder>;

function Loaded({ quote, view }: { quote: QuoteDetail; view: QuotationView }) {
  const commands = useQuoteCommand(quote.id);
  const actions = useQuotationActions(quote, commands);
  const order = useQuotationOrder(quote.id, quote.status);
  const terms = useTermsDraft(quote, commands);
  const editable = isEditable(quote);
  const emptyDraft = editable && quote.lines.length === 0;
  const path = `/sales/quotes/${quote.id}`;
  const review = quote.review;
  const needsApproval = review.requires_approval && !review.approval_current && !review.review_proposal_id && editable;

  const primary: ReactNode =
    quote.status === "won" ? (
      order.order ? (
        <ButtonLink href={asRoute(order.order.path)} variant="inverse" iconRight="arrowRight">
          Open order {order.order.order_number}
        </ButtonLink>
      ) : order.canConvert ? (
        <Button iconLeft="cart" loading={order.pending} isDisabled={order.offline} onPress={() => void order.convert()}>
          Convert to order
        </Button>
      ) : null
    ) : (
      <>
        {emptyDraft && view !== "lines" ? (
          <ButtonLink href={asRoute(viewHref(path, "lines"))} iconLeft="plus">
            Add lines
          </ButtonLink>
        ) : null}
        {actions.forward ? (
          <Button
            variant={emptyDraft ? "secondary" : "primary"}
            loading={actions.pending === actions.forward.action}
            isDisabled={Boolean(commands.offline)}
            onPress={() => actions.start(actions.forward!)}
          >
            {actions.forward.label}
          </Button>
        ) : null}
      </>
    );

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Quotations", href: "/sales/quotes" }, { label: quote.quote_number }]}
        code={
          <>
            {quote.quote_number}
            {quote.revision_no > 0 ? ` · revision ${quote.revision_no}` : ""}
          </>
        }
        title={quote.party.display_name}
        status={
          <>
            <StatusBadge look={quotationStatus(quote.status)} />
            {quote.is_expired ? (
              <Badge tone="amber" icon="clock">
                Validity passed
              </Badge>
            ) : null}
            {needsApproval ? (
              <Badge tone="amber" icon="alert">
                Needs approval
              </Badge>
            ) : null}
            {review.approval_current && editable ? (
              <Badge tone="leaf" icon="badgeCheck">
                Approved
              </Badge>
            ) : null}
          </>
        }
        lead={[quote.party.party_number, quote.party.country_code, ORIGIN[quote.origin]].filter(Boolean).join(" · ")}
        facts={
          <FactStrip
            items={[
              { label: "Total", icon: "banknote", value: <Money value={quote.totals.grand_total} className="t-stat-sm" /> },
              { label: "Valid until", icon: "calendar", value: quote.valid_until ? <DateText value={quote.valid_until} style="business" /> : null },
              { label: "Incoterm", icon: "truck", value: [quote.incoterm, quote.incoterm_place].filter(Boolean).join(" · ") },
              { label: "Owner", icon: "user", value: quote.owner.display_name },
            ]}
          />
        }
        actions={
          <>
            {primary}
            {actions.surfaced ? (
              <Button
                variant="secondary"
                loading={actions.pending === actions.surfaced.action}
                isDisabled={Boolean(commands.offline)}
                onPress={() => actions.start(actions.surfaced!)}
              >
                {actions.surfaced.label}
              </Button>
            ) : null}
            {actions.menu.length > 0 ? (
              <Menu
                label="More quotation actions"
                items={actions.menu}
                placement="bottom end"
                trigger={
                  <Button variant="secondary" iconRight="chevronDown">
                    More
                  </Button>
                }
              />
            ) : null}
          </>
        }
      >
        <Tabs
          label="Views of this quotation"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Lines", count: quote.lines.length, href: asRoute(viewHref(path, "lines")) },
            { id: "terms", label: terms.dirty.length > 0 ? "Terms · unsaved" : "Terms", href: asRoute(viewHref(path, "terms")) },
            { id: "documents", label: "Documents and revisions", href: asRoute(viewHref(path, "documents")) },
            { id: "activity", label: "Activity", href: asRoute(viewHref(path, "activity")) },
          ]}
        />
      </RecordHeader>

      {commands.offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this quotation. Changes can be saved once the connection is back.
        </Banner>
      ) : null}

      {view === "overview" ? <Overview quote={quote} editable={editable} actions={actions} order={order} path={path} /> : null}
      {view === "lines" ? <LinesView quote={quote} editable={editable} commands={commands} /> : null}
      {view === "terms" ? <TermsView quote={quote} editable={editable} commands={commands} draft={terms} /> : null}
      {view === "documents" ? <DocumentsView quote={quote} /> : null}
      {view === "activity" ? <ActivityView quote={quote} /> : null}

      {actions.dialogs}
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: where it stands, and the one next step

interface Standing {
  headline: ReactNode;
  body: ReactNode;
  link?: { href: string; label: string; icon?: IconName };
}

function standingOf(quote: QuoteDetail, editable: boolean, actions: QuotationActions, order: Order, path: string): Standing {
  const review = quote.review;
  const next = actions.forward?.label;
  switch (quote.status) {
    case "draft":
    case "revised": {
      const revising = quote.status === "revised";
      if (quote.lines.length === 0) {
        return {
          headline: <>Start with the <em>lines</em></>,
          body: "A quotation needs at least one product, custom product or charge. Each line is priced for this customer as you add it.",
          link: editable ? { href: viewHref(path, "lines"), label: "Add lines", icon: "plus" } : undefined,
        };
      }
      if (review.requires_approval && !review.approval_current) {
        const why = review.reasons.map((reason) => REASON[reason] ?? reviewReasonsText([reason])).join(", ");
        return {
          headline: <>Needs <em>approval</em> before it goes out</>,
          body: `It carries ${why || "terms that need a second pair of eyes"}. ${next ? `${next} and an approver gets it in their Inbox.` : "An approver has to look at it first."}`,
        };
      }
      return {
        headline: review.approval_current ? <>Approved and ready to <em>send</em></> : revising ? <>A revision is <em>open</em></> : <>Ready to <em>send</em></>,
        body: revising
          ? "The revision the customer has stays exactly as issued. Change lines or terms here, then send again to issue the next revision."
          : "Send the PDF to the customer, then mark the quotation as sent. That issues a numbered revision and locks lines and terms.",
      };
    }
    case "internal_review":
      return {
        headline: <>Waiting for an <em>approver</em></>,
        body: "The request is in an approver's Inbox. Lines and terms are locked until they decide; withdraw the request if you need to change something.",
        link: review.review_proposal_id ? { href: `/inbox/approvals/${encodeURIComponent(review.review_proposal_id)}`, label: "Open the approval request", icon: "inbox" } : undefined,
      };
    case "sent":
      return quote.is_expired
        ? {
            headline: <>The offer has <em>lapsed</em></>,
            body: "Its validity has passed. Extend the validity to keep these prices open, or revise the quotation with new ones.",
          }
        : {
            headline: <>With the <em>customer</em></>,
            body: "Record the outcome when they decide: won or lost. If they ask for changes, revise it; the issued revision stays on file.",
          };
    case "won":
      if (order.order) {
        return {
          headline: <>Won, and now an <em>order</em></>,
          body: `Order ${order.order.order_number} carries the lines and prices of the accepted revision.`,
          link: { href: order.order.path, label: `Open order ${order.order.order_number}`, icon: "cart" },
        };
      }
      return {
        headline: <>Won. Next, the <em>order</em></>,
        body: order.canConvert
          ? "Convert it to an order. The order takes its lines and prices from the accepted revision, and they never change there."
          : "The customer accepted. Someone with access to orders converts it from here.",
      };
    case "lost":
      return { headline: "Lost", body: quote.lost_reason_code ? `Recorded reason: ${humanise(quote.lost_reason_code).toLowerCase()}.` : "The customer went another way. Duplicate it to quote them again." };
    case "cancelled":
      return { headline: "Cancelled", body: quote.cancelled_reason_code ? `Recorded reason: ${humanise(quote.cancelled_reason_code).toLowerCase()}.` : "Nothing more can be done with it. Duplicate it to start again from the same lines." };
    case "archived":
      return {
        headline: "In the archive",
        body: `Archived from ${quotationStatus(quote.archived_from_status ?? "draft").label.toLowerCase()}. Restore it to work on it again.`,
      };
    default:
      return { headline: quotationStatus(quote.status).label, body: "Nothing can be done with this quotation in its current status." };
  }
}

function stagesOf(quote: QuoteDetail, order: Order): StepItem[] | null {
  const status = quote.status;
  if (status === "lost" || status === "cancelled" || status === "archived") return null;
  const approval = quote.review.requires_approval || status === "internal_review" || quote.review.approved_proposal_id !== null;
  const reached = status === "draft" || status === "revised" ? 0 : status === "internal_review" ? 1 : status === "sent" ? 3 : 4;
  const all = [
    { id: "draft", label: status === "revised" ? "Revision" : "Draft", hint: quote.lines.length === 1 ? "1 line" : `${quote.lines.length} lines`, at: 0 },
    ...(approval ? [{ id: "approval", label: "Approval", hint: quote.review.approval_current ? "Approved" : "By an approver", at: 1 }] : []),
    { id: "sent", label: "Sent", hint: quote.sent_at ? <DateText value={quote.sent_at} style="date" /> : "PDF issued", at: 2 },
    { id: "decision", label: "Decision", hint: status === "won" ? "Won" : "Won or lost", at: 3 },
    { id: "order", label: "Order", hint: order.order ? order.order.order_number : "From the accepted revision", at: 4 },
  ];
  return all.map((stage) => {
    const done = stage.at < reached || (stage.id === "order" && Boolean(order.order)) || (stage.id === "approval" && quote.review.approval_current && reached === 0);
    return { id: stage.id, label: stage.label, hint: stage.hint, state: done ? "done" : stage.at === reached ? "current" : "todo" };
  });
}

function Overview({ quote, editable, actions, order, path }: { quote: QuoteDetail; editable: boolean; actions: QuotationActions; order: Order; path: string }) {
  const standing = standingOf(quote, editable, actions, order, path);
  const stages = stagesOf(quote, order);
  const snapshot = quote.party_snapshot;
  const approvalId = quote.review.review_proposal_id ?? quote.review.approved_proposal_id;
  const contact = snapshot?.contact_name ? [snapshot.contact_name, snapshot.contact_email].filter(Boolean).join(" · ") : null;

  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            {stages ? <Steps label="Progress of this quotation" steps={stages} /> : null}
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
            {standing.link || (approvalId && quote.status !== "internal_review") ? (
              <div className="flex flex-wrap gap-2">
                {standing.link ? (
                  <ButtonLink href={asRoute(standing.link.href)} variant="inverse" iconLeft={standing.link.icon}>
                    {standing.link.label}
                  </ButtonLink>
                ) : null}
                {approvalId && quote.status !== "internal_review" ? (
                  <ButtonLink href={asRoute(`/inbox/approvals/${encodeURIComponent(approvalId)}`)} variant="ghost" iconLeft="badgeCheck">
                    {quote.review.approval_current ? "See the approval" : "Open the approval request"}
                  </ButtonLink>
                ) : null}
              </div>
            ) : null}
          </GlassPanel>
          <QuotationTotals quote={quote} size="xl" />
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Customer" titleAs="h2" style={{ "--i": 1 } as React.CSSProperties}>
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-0.5">
                <TextLink href={asRoute(`/sales/parties/${quote.party.id}`)} className="t-label">
                  {snapshot?.display_name ?? quote.party.display_name}
                </TextLink>
                <span className="t-caption text-ink-3">
                  <Code>{quote.party.party_number}</Code> · {snapshot?.country_code ?? quote.party.country_code}
                </span>
              </div>
              <KeyValue
                rows
                items={[
                  ...(contact ? [{ label: "Contact", value: contact }] : []),
                  { label: "Owner", value: quote.owner.display_name },
                  { label: "Created", value: <DateText value={quote.created_at} style="dayTime" /> },
                  ...(quote.sent_at ? [{ label: "Sent", value: <DateText value={quote.sent_at} style="dayTime" /> }] : []),
                ]}
              />
            </div>
          </GlassPanel>
          {quote.enquiry_id || quote.origin_message_id || quote.duplicated_from_quote_id || quote.restored_from_revision_no ? (
            <GlassPanel padding="md" className="rise" title="Where it came from" titleAs="h2" style={{ "--i": 2 } as React.CSSProperties}>
              <ul className="flex flex-col gap-3">
                {quote.enquiry_id ? (
                  <li>
                    <TextLink href={asRoute(`/sales/enquiries/${encodeURIComponent(quote.enquiry_id)}`)}>The enquiry it answers</TextLink>
                  </li>
                ) : null}
                {quote.origin_message_id ? (
                  <li>
                    <TextLink href="/sales/customer-messages">The customer&apos;s message</TextLink>
                  </li>
                ) : null}
                {quote.duplicated_from_quote_id ? (
                  <li>
                    <TextLink href={asRoute(`/sales/quotes/${encodeURIComponent(quote.duplicated_from_quote_id)}`)}>The quotation it was copied from</TextLink>
                  </li>
                ) : null}
                {quote.restored_from_revision_no ? <li className="t-body-sm text-ink-2">Working copy restored from revision {quote.restored_from_revision_no}.</li> : null}
              </ul>
            </GlassPanel>
          ) : null}
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Activity: every change of status, newest first

const DID: Record<string, string> = {
  submit_review: "asked for approval",
  withdraw_review: "withdrew the approval request",
  mark_sent: "marked it as sent",
  mark_won: "marked it as won",
  mark_lost: "marked it as lost",
  cancel: "cancelled it",
  revise: "opened a revision",
  discard_revision: "discarded the revision",
  extend_validity: "extended the validity",
  archive: "archived it",
  unarchive: "restored it from the archive",
  correct_status: "corrected the status",
  approve: "approved it",
  reject: "sent it back",
  create: "created the draft",
};
const DID_ICON: Record<string, IconName> = {
  submit_review: "badgeCheck",
  mark_sent: "send",
  mark_won: "thumbsUp",
  mark_lost: "thumbsDown",
  cancel: "xCircle",
  revise: "edit",
  extend_validity: "calendar",
  archive: "archive",
  approve: "checkCircle",
};

function ActivityView({ quote }: { quote: QuoteDetail }) {
  const query = useQuery({ queryKey: queryKeys.sales.quoteHistory(quote.id), queryFn: ({ signal }) => fetchQuoteHistory(quote.id, signal) });
  if (query.isPending) return <LoadingBlock label="Loading activity" lines={5} />;
  if (query.isError) return <ErrorBlock error={query.error} what="The activity" onRetry={() => void query.refetch()} />;
  const items: TimelineItem[] = query.data.map((entry) => {
    const from = quotationStatus(entry.from_status);
    const to = quotationStatus(entry.to_status);
    return {
      id: entry.id,
      title: `${entry.actor?.display_name ?? "Lamikraft One"} ${DID[entry.action] ?? humanise(entry.action).toLowerCase()}`,
      meta: (
        <>
          <DateText value={entry.occurred_at} style="dayTime" />
          {entry.from_status !== entry.to_status ? ` · ${from.label} to ${to.label}` : ""}
        </>
      ),
      body: entry.reason ?? undefined,
      icon: DID_ICON[entry.action],
      tone: to.tone,
    };
  });
  return (
    <GlassPanel padding="lg" title="Activity" titleAs="h2" className="rise">
      {items.length === 0 ? (
        <EmptyState compact icon="history" title="No changes of status yet" text="Requests for approval, sends, revisions and outcomes are listed here as they happen." />
      ) : (
        <Timeline label="Quotation activity" items={items} />
      )}
    </GlassPanel>
  );
}
