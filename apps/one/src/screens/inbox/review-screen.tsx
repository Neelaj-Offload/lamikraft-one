"use client";

import type { Route } from "next";
import { useState } from "react";
import type { Proposal } from "@/features/approvals/api";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import type { QuoteDetail, QuoteLine } from "@/features/sales/types";
import { isDecimalStr } from "@/lib/format/decimal";
import { formatMoney } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { OFFLINE_NOTE, useProposal, useProposalDecision, useProposalQuote } from "~/data/inbox";
import { Page, PageHeader, PageSection, RecordHeader, Split, type Crumb } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { staggered } from "./model";
import {
  Avatar,
  Badge,
  Banner,
  Button,
  ButtonLink,
  ConfirmDialog,
  Dash,
  DataTable,
  DateText,
  FactStrip,
  FormActions,
  GlassPanel,
  Icon,
  KeyValue,
  Money,
  Qty,
  ReasonDialog,
  SkeletonText,
  type Column,
  type Fact,
  type KeyValueItem,
  type Tone,
} from "~/ui";

const CRUMBS: readonly Crumb[] = [{ label: "Inbox", href: "/inbox" }, { label: "Approvals", href: "/inbox/approvals" }, { label: "Review request" }];

const STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Waiting for a decision", tone: "amber" },
  approved: { label: "Approved", tone: "leaf" },
  rejected: { label: "Rejected", tone: "ember" },
  expired: { label: "Expired", tone: "neutral" },
  invalidated: { label: "Out of date", tone: "neutral" },
  superseded: { label: "Replaced by a newer request", tone: "neutral" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
};

/** The flags the request carries (`facts`), in the order a reviewer weighs them. */
const FLAGS = [
  { key: "price_override", label: "Price differs from the list" },
  { key: "discount", label: "Discount given" },
  { key: "below_minimum", label: "Below the order minimum" },
] as const;

const isZero = (decimal: string) => /^-?0+(\.0+)?$/.test(decimal);

/**
 * What this person may do with the request, from the server's capabilities only. Someone who
 * asked for a review never decides it; a closed request offers nothing.
 */
function decisionState(proposal: Pick<Proposal, "status" | "capabilities" | "requested_by">, userId: string) {
  const decide = proposal.capabilities.decide;
  const withdraw = proposal.capabilities.withdraw;
  if (proposal.status !== "pending") return { canDecide: false, canWithdraw: false, why: null };
  if (decide?.allowed) return { canDecide: true, canWithdraw: Boolean(withdraw?.allowed), why: null };
  const own = proposal.requested_by === userId || decide?.reason_code === "separation_of_duties";
  return {
    canDecide: false,
    canWithdraw: Boolean(withdraw?.allowed),
    why: own
      ? "You asked for this review, so someone else decides it. Every exception gets a second pair of eyes."
      : "Your role cannot decide this one. It goes to an approver with authority over prices.",
  };
}

function lineName(line: Pick<QuoteLine, "line_no" | "product_key" | "description">): string {
  return `${line.line_no}. ${line.product_key ? `${line.product_key} ` : ""}${line.description}`.trim();
}

/** A unit price keeps up to four decimals; the exact string from the server is only ever formatted. */
function UnitPrice({ amount, currency, className }: { amount: string | null; currency: string; className?: string }) {
  const { locale } = useZone();
  const text = amount ? formatMoney({ amount, currency }, { locale, maxFractionDigits: 4 }) : null;
  if (text === null) return <Dash className={className} />;
  return <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>{text}</span>;
}

/**
 * One review request: a decision screen. What is proposed, by whom and why; the evidence (what
 * differs from the list, then the full quotation); and Approve or Reject as the only loud
 * controls, pinned to the bottom so the evidence is read first and the decision is always at hand.
 */
export function ReviewScreen({ proposalId }: { proposalId: string }) {
  const { bootstrap } = useSession();
  const proposalQuery = useProposal(proposalId);
  const proposal = proposalQuery.data;
  const target = proposal?.targets.find((candidate) => candidate.target_type === "sales.quote") ?? null;
  const quoteQuery = useProposalQuote(target);
  const quote = quoteQuery.data ?? null;
  const decision = useProposalDecision(proposal);
  const [open, setOpen] = useState<"approve" | "reject" | "withdraw" | null>(null);

  useScreenContribution(
    proposal
      ? {
          focus: { type: "approvals.proposal", id: proposal.id, version: proposal.version },
          related: target ? [{ type: "sales.quote", id: target.target_id, version: quote?.version ?? target.target_version }] : [],
        }
      : null,
  );

  if (proposalQuery.isPending || !proposal) {
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title="Review request" />
        {proposalQuery.isPending ? (
          <>
            <LoadingBlock lines={3} label="Loading the review request" />
            <LoadingBlock lines={6} label="Loading the evidence" />
          </>
        ) : (
          <ErrorBlock error={proposalQuery.error} what="This review request" onRetry={() => void proposalQuery.refetch()} />
        )}
      </Page>
    );
  }

  const state = decisionState(proposal, bootstrap.user.id);
  const status = STATUS[proposal.status] ?? { label: proposal.status, tone: "neutral" as Tone };
  const requester = proposal.requested_by_name ?? "The requester";
  const subject = quote ? `quotation ${quote.quote_number}` : "it";
  // The server's title repeats the number and the customer; the header already sets the number above the title.
  const party = target ? (typeof proposal.facts.party_name === "string" ? proposal.facts.party_name : (quote?.party.display_name ?? null)) : null;
  const title = party ? `Quotation for ${party}` : proposal.title || "Review request";
  const number = quote?.quote_number ?? (target && typeof proposal.facts.quote_number === "string" ? proposal.facts.quote_number : undefined);
  const facts = proposal.facts;
  const currency = typeof facts.currency === "string" ? facts.currency : (quote?.currency ?? "");
  const total = isDecimalStr(facts.grand_total) && currency ? { amount: facts.grand_total, currency } : null;
  // The quotation was edited after the request was made: a decision now would be about something else.
  const drift = proposal.status === "pending" && quote !== null && target?.target_version != null && quote.version !== target.target_version;

  const strip: Fact[] = [
    {
      label: "Asked by",
      value: proposal.requested_by_name ? (
        <span className="flex items-center gap-2">
          <Avatar name={proposal.requested_by_name} size="sm" />
          {proposal.requested_by_name}
        </span>
      ) : null,
    },
    { label: "Asked", value: proposal.requested_at ? <DateText value={proposal.requested_at} style="relative" /> : null },
  ];
  strip.push({ label: "Total before tax", value: <Money value={total} /> });
  if (proposal.decided_at) strip.push({ label: "Decided", value: <DateText value={proposal.decided_at} style="dayTime" /> });
  else if (proposal.expires_at) {
    strip.push({ label: proposal.status === "expired" ? "Expired" : "Decide by", value: <DateText value={proposal.expires_at} style="dayTime" /> });
  }

  /** Dialog handlers: resolve to close (decided, or reloaded after a conflict), reject to stay open. */
  const settle = async (outcome: Promise<"done" | "conflict" | "failed">) => {
    if ((await outcome) === "failed") throw new Error("not decided");
  };

  return (
    <Page>
      <RecordHeader
        breadcrumb={CRUMBS}
        code={number}
        title={title}
        status={
          <Badge tone={status.tone} dot>
            {status.label}
          </Badge>
        }
        lead={proposal.summary}
        facts={<FactStrip items={strip} />}
        actions={
          quote ? (
            <ButtonLink href={quote.path as Route} variant="secondary" iconRight="arrowUpRight">
              Open quotation
            </ButtonLink>
          ) : undefined
        }
      />

      {decision.conflict ? (
        <Banner tone="amber" title="Nothing was decided." onClose={decision.clearConflict}>
          This request changed while you were reading it. You are now looking at the latest version: read it again, then decide.
        </Banner>
      ) : null}
      {drift ? (
        <Banner tone="amber" title="The quotation changed after this request was made.">
          A decision now would mark the request out of date. Ask {requester} to send it for review again.
        </Banner>
      ) : null}
      {decision.offline ? <Banner tone="amber">{OFFLINE_NOTE}</Banner> : null}
      <Outcome proposal={proposal} why={state.why} />

      <Split
        main={
          <>
            <Evidence proposal={proposal} quote={quote} quoteQuery={quoteQuery} hasTarget={target !== null} />
            {quote ? <Lines quote={quote} /> : null}
          </>
        }
        aside={
          <>
            {quote ? <Totals quote={quote} /> : null}
            {proposal.status === "pending" && target ? <Consequences requester={requester} canDecide={state.canDecide} canWithdraw={state.canWithdraw} /> : null}
          </>
        }
      />

      {state.canDecide || state.canWithdraw ? (
        <FormActions note={state.canDecide ? "Your decision applies to exactly what is shown here." : "You can take this request back while it waits."}>
          {state.canWithdraw ? (
            <Button variant={state.canDecide ? "ghost" : "secondary"} isDisabled={decision.offline || decision.pending !== null} onPress={() => setOpen("withdraw")}>
              Withdraw request
            </Button>
          ) : null}
          {state.canDecide ? (
            <>
              <Button variant="secondary" iconLeft="x" isDisabled={decision.offline || decision.pending !== null} onPress={() => setOpen("reject")}>
                Reject
              </Button>
              <Button variant="primary" iconLeft="check" isDisabled={decision.offline || decision.pending !== null} onPress={() => setOpen("approve")}>
                Approve
              </Button>
            </>
          ) : null}
        </FormActions>
      ) : null}

      <ConfirmDialog
        isOpen={open === "approve"}
        onOpenChange={(next) => setOpen(next ? "approve" : null)}
        title="Approve this request?"
        description={`${requester} will be able to send ${subject} to the customer as it stands.`}
        confirmLabel="Approve request"
        onConfirm={() => settle(decision.approve(target ? "Approved. The quotation can now be sent." : "Approved."))}
      />
      <ReasonDialog
        isOpen={open === "reject"}
        onOpenChange={(next) => setOpen(next ? "reject" : null)}
        title="Reject this request"
        description={title}
        tone="danger"
        confirmLabel="Reject request"
        reasonLabel="What needs to change?"
        reasonHelp={`${requester} reads this before reworking it.`}
        onConfirm={(reason) => settle(decision.reject(reason, target ? "Rejected. The quotation is back in draft with your reason." : "Rejected, with your reason."))}
      />
      <ConfirmDialog
        isOpen={open === "withdraw"}
        onOpenChange={(next) => setOpen(next ? "withdraw" : null)}
        title="Withdraw this request?"
        description={target ? "The quotation goes back to draft and nobody is asked to decide." : "Nobody will be asked to decide."}
        confirmLabel="Withdraw request"
        onConfirm={() => settle(decision.withdraw(target ? "Withdrawn. The quotation is back in draft." : "Withdrawn."))}
      />
    </Page>
  );
}

/** How it ended, or why this person is not the one to decide. */
function Outcome({ proposal, why }: { proposal: Proposal; why: string | null }) {
  if (proposal.status === "pending") return why ? <Banner tone="cobalt">{why}</Banner> : null;
  const reason = proposal.decision_reason ? <> Reason given: &ldquo;{proposal.decision_reason}&rdquo;</> : null;
  if (proposal.status === "approved") {
    return (
      <Banner tone="leaf" title="Approved.">
        Nothing is left to decide.{reason}
      </Banner>
    );
  }
  if (proposal.status === "rejected") {
    return (
      <Banner tone="neutral" icon="xCircle" title="Rejected.">
        Nothing is left to decide.{reason}
      </Banner>
    );
  }
  return (
    <Banner tone="neutral" title={`${STATUS[proposal.status]?.label ?? "Closed"}.`}>
      This request is closed. Nothing is left to decide.{reason}
    </Banner>
  );
}

interface QuoteQuery {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

/** The before and after: every line whose price left the list, every discount, and the minimum. */
function Evidence({ proposal, quote, quoteQuery, hasTarget }: { proposal: Proposal; quote: QuoteDetail | null; quoteQuery: QuoteQuery; hasTarget: boolean }) {
  const flags = FLAGS.filter((flag) => proposal.facts[flag.key] === true);
  const changed = quote ? quote.lines.filter((line) => line.is_overridden || (line.discount_pct && isDecimalStr(line.discount_pct) && !isZero(line.discount_pct))) : [];
  const minimum = quote?.totals.minimum;
  const shortfall = minimum && minimum.status === "BELOW" && minimum.shortfall ? minimum.shortfall : null;

  return (
    <GlassPanel padding="lg" title={proposal.status === "pending" ? "Why this needs approval" : "Why this needed approval"} titleAs="h2">
      <div className="flex flex-col gap-5">
        {flags.length > 0 ? (
          <ul className="flex flex-wrap gap-2" aria-label="Reasons">
            {flags.map((flag) => (
              <li key={flag.key}>
                <Badge tone="amber" icon="alert">
                  {flag.label}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}

        {!hasTarget ? (
          flags.length === 0 ? <p className="t-body text-ink-2">The request does not say more than its title.</p> : null
        ) : quoteQuery.isPending ? (
          <div role="status" aria-label="Loading the quotation">
            <SkeletonText lines={4} />
          </div>
        ) : quoteQuery.isError || !quote ? (
          <ErrorBlock error={quoteQuery.error} what="The quotation" onRetry={() => void quoteQuery.refetch()} />
        ) : changed.length === 0 && !shortfall ? (
          <p className="t-body text-ink-2">Nothing here departs from the list. Every line is at its list price, with no discount.</p>
        ) : (
          <ul className="flex flex-col" aria-label="What differs from the list">
            {changed.map((line, index) => (
              <li key={line.id} className={`rise-plain flex flex-col gap-2 py-4 md:flex-row md:items-start md:justify-between md:gap-6 ${index > 0 ? "hairline-top" : "pt-0"}`} style={staggered(index)}>
                <div className="flex min-w-0 flex-col gap-1">
                  <p className="t-h4 [overflow-wrap:anywhere]">{lineName(line)}</p>
                  {line.override_reason ? <p className="t-body-sm text-ink-2 [overflow-wrap:anywhere]">&ldquo;{line.override_reason}&rdquo;</p> : null}
                </div>
                <div className="flex flex-none flex-col gap-1 md:items-end">
                  {line.is_overridden ? (
                    <p className="flex items-center gap-2">
                      <span className="lk-sr-only">List price </span>
                      <UnitPrice amount={line.default_unit_price} currency={quote.currency} className="t-body text-ink-3" />
                      <Icon name="arrowRight" size={16} className="text-ink-3" aria-hidden="true" />
                      <span className="lk-sr-only">quoted at </span>
                      <UnitPrice amount={line.unit_price} currency={quote.currency} className="t-stat-sm" />
                    </p>
                  ) : null}
                  {line.discount_pct && isDecimalStr(line.discount_pct) && !isZero(line.discount_pct) ? (
                    <p className="t-body-sm text-ink-2 lk-tnum">{line.discount_pct}% discount on this line</p>
                  ) : null}
                </div>
              </li>
            ))}
            {shortfall ? (
              <li className={`flex flex-col gap-1 py-4 pb-0 md:flex-row md:items-center md:justify-between md:gap-6 ${changed.length > 0 ? "hairline-top" : "pt-0"}`}>
                <p className="t-h4">The order is under the minimum</p>
                <p className="t-body text-ink-2">
                  Short by <UnitPrice amount={shortfall} currency={quote.currency} className="t-stat-sm text-ink" />
                </p>
              </li>
            ) : null}
          </ul>
        )}
      </div>
    </GlassPanel>
  );
}

/** The whole quotation, so the exception is judged in context. */
function Lines({ quote }: { quote: QuoteDetail }) {
  const columns: Column<QuoteLine>[] = [
    {
      key: "line",
      header: "Line",
      primary: true,
      cell: (line) => <span className="[overflow-wrap:anywhere]">{lineName(line)}</span>,
    },
    { key: "quantity", header: "Quantity", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.unit_code }} /> },
    { key: "list", header: "List price", numeric: true, cell: (line) => <UnitPrice amount={line.default_unit_price} currency={quote.currency} /> },
    {
      key: "quoted",
      header: "Quoted price",
      numeric: true,
      cell: (line) => (
        <span className="inline-flex items-center gap-2">
          {line.is_overridden ? (
            <Badge tone="amber" size="sm">
              Changed
            </Badge>
          ) : null}
          <UnitPrice amount={line.unit_price} currency={quote.currency} className={line.is_overridden ? "font-semibold" : undefined} />
        </span>
      ),
    },
    {
      key: "total",
      header: "Line total",
      numeric: true,
      cell: (line) => <Money value={line.line_total ? { amount: line.line_total, currency: quote.currency } : null} />,
    },
  ];
  return (
    <PageSection title="The full quotation" description={`${quote.quote_number} for ${quote.party.display_name}, line by line.`} index={1}>
      <GlassPanel padding="none">
        <DataTable label={`Lines of ${quote.quote_number}`} columns={columns} rows={quote.lines} rowKey={(line) => line.id} />
      </GlassPanel>
    </PageSection>
  );
}

/** The saved totals; the surcharge appears only when the server applied it. */
function Totals({ quote }: { quote: QuoteDetail }) {
  const t = quote.totals;
  const items: KeyValueItem[] = [{ label: "Subtotal", value: <Money value={t.applicable_subtotal} /> }];
  if (isDecimalStr(t.discount_total.amount) && !isZero(t.discount_total.amount)) items.push({ label: "Discount", value: <Money value={t.discount_total} /> });
  if (t.surcharge_applied) items.push({ label: t.surcharge_label || "Minimum order surcharge", value: <Money value={t.surcharge} /> });
  items.push({ label: "Total before tax", value: <Money value={t.grand_total} />, total: true });
  return (
    <GlassPanel title="Totals" titleAs="h2" className="rise" style={staggered(1)}>
      <KeyValue rows items={items} />
      {t.totals_complete ? null : (
        <Banner tone="amber" className="mt-4">
          Some lines have no price yet, so this total is incomplete.
        </Banner>
      )}
    </GlassPanel>
  );
}

/** What each choice sets in motion, said before the choice is made. */
function Consequences({ requester, canDecide, canWithdraw }: { requester: string; canDecide: boolean; canWithdraw: boolean }) {
  const rows: { icon: "check" | "x" | "undo"; verb: string; text: string }[] = [];
  if (canDecide) {
    rows.push({ icon: "check", verb: "Approve", text: `${requester} can send the quotation to the customer as it stands.` });
    rows.push({ icon: "x", verb: "Reject", text: `It goes back to draft with your reason, for ${requester} to rework.` });
  }
  if (canWithdraw) rows.push({ icon: "undo", verb: "Withdraw", text: "The quotation goes back to draft and nobody is asked to decide." });
  if (rows.length === 0) return null;
  return (
    <GlassPanel variant="outline" title="What happens next" titleAs="h2" className="rise" style={staggered(2)}>
      <ul className="flex flex-col gap-4">
        {rows.map((row) => (
          <li key={row.verb} className="flex items-start gap-3">
            <span className="bg-ink/6 text-ink-2 grid size-8 flex-none place-items-center rounded-sm" aria-hidden="true">
              <Icon name={row.icon} size={16} />
            </span>
            <p className="t-body-sm text-ink-2">
              <b className="text-ink font-semibold">{row.verb}.</b> {row.text}
            </p>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}
