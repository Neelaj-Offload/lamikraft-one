"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDateTime, Money, Quantity } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { fetchQuote } from "@/features/sales/api";
import type { QuoteDetail, QuoteLine } from "@/features/sales/types";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { isDecimalStr } from "@/lib/format/decimal";
import { formatMoney } from "@/lib/format/money";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { briefingMessages } from "@/messages/briefing";
import { approvalMessages as m } from "@/messages/approvals";
import { decideProposal, fetchProposal, isReviewConflict, withdrawProposal, type Proposal } from "./api";

const STATUS_TONE: Record<string, Tone> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
  expired: "neutral",
  invalidated: "neutral",
  superseded: "neutral",
  withdrawn: "neutral",
};

/** The decision controls this person gets, from the server's capabilities only. */
export function decisionState(proposal: Pick<Proposal, "status" | "capabilities" | "requested_by">, userId: string) {
  const decide = proposal.capabilities.decide;
  const withdraw = proposal.capabilities.withdraw;
  if (proposal.status !== "pending") return { canDecide: false, canWithdraw: false, explanation: m.closed };
  if (decide?.allowed) return { canDecide: true, canWithdraw: Boolean(withdraw?.allowed), explanation: null };
  const explanation =
    proposal.requested_by === userId ? m.ownRequest : ((decide?.reason_code ? m.notEligible[decide.reason_code] : undefined) ?? m.notEligible.not_an_eligible_approver!);
  return { canDecide: false, canWithdraw: Boolean(withdraw?.allowed), explanation };
}

/** "What changed": lines whose price differs from the list, discounts, and the minimum. */
export function quoteChanges(quote: Pick<QuoteDetail, "lines" | "totals" | "currency">, locale: string): string[] {
  const out: string[] = [];
  const price = (amount: string | null) => (amount ? (formatMoney({ amount, currency: quote.currency }, { locale, maxFractionDigits: 4 }) ?? amount) : "—");
  for (const line of quote.lines) {
    const name = lineName(line);
    if (line.is_overridden) {
      out.push(
        m.overrideLine(name, price(line.default_unit_price), price(line.unit_price)) + (line.override_reason ? ` · ${m.overrideReason(line.override_reason)}` : ""),
      );
    }
    if (line.discount_pct && isDecimalStr(line.discount_pct) && !/^0+(\.0+)?$/.test(line.discount_pct)) out.push(m.discountLine(name, line.discount_pct));
  }
  if (quote.totals.minimum.status === "BELOW" && quote.totals.minimum.shortfall) out.push(m.belowMinimum(price(quote.totals.minimum.shortfall)));
  return out;
}

function lineName(line: Pick<QuoteLine, "line_no" | "product_key" | "description">): string {
  return `${line.line_no}. ${line.product_key ? `${line.product_key} ` : ""}${line.description}`.trim();
}

function yesNo(value: unknown): string {
  return value === true ? m.yes : m.no;
}

export function ReviewView({ proposalId }: { proposalId: string }) {
  const { bootstrap, zone } = useSession();
  const online = useOnline();
  const queryClient = useQueryClient();
  const proposalQuery = useQuery({ queryKey: queryKeys.approvals.proposal(proposalId), queryFn: ({ signal }) => fetchProposal(proposalId, signal) });
  const target = proposalQuery.data?.targets.find((candidate) => candidate.target_type === "sales.quote") ?? null;
  const quoteQuery = useQuery({
    queryKey: queryKeys.sales.quote(target?.target_id ?? ""),
    queryFn: ({ signal }) => fetchQuote(target!.target_id, signal),
    enabled: target !== null,
  });
  const [pending, setPending] = useState<string | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [commandKeys] = useState(() => createCommandKeys());

  useScreenContribution(
    proposalQuery.data
      ? {
          focus: { type: "approvals.proposal", id: proposalQuery.data.id, version: proposalQuery.data.version },
          related: target ? [{ type: "sales.quote", id: target.target_id, version: quoteQuery.data?.version ?? target.target_version }] : [],
        }
      : null,
  );

  if (proposalQuery.isPending) return <Loading label={m.loading} variant="detail" />;
  if (proposalQuery.isError) return <ErrorState error={proposalQuery.error} what={m.loading} onRetry={() => void proposalQuery.refetch()} />;

  const proposal = proposalQuery.data;
  const quote = quoteQuery.data ?? null;
  const state = decisionState(proposal, bootstrap.user.id);
  const offline = online ? null : briefingMessages.offlineActions;
  const drift = quote !== null && target?.target_version != null && quote.version !== target.target_version;
  const facts = proposal.facts;
  const currency = typeof facts.currency === "string" ? facts.currency : (quote?.currency ?? "");
  const grandTotal = isDecimalStr(facts.grand_total) && currency ? { amount: facts.grand_total, currency } : null;

  const refresh = async () => {
    await Promise.all(invalidationMap["approvals.decide"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
  };

  const act = async (label: string, done: string, call: (key: string) => Promise<unknown>, parts: (string | null)[]) => {
    if (pending || offline) return;
    const signature = commandSignature(proposal.id, proposal.version, proposal.content_hash, ...parts);
    const attempt = commandKeys.attempt(signature, () => null);
    setPending(label);
    setNotice(null);
    try {
      await call(attempt.key);
      commandKeys.settle(signature);
      setRejectOpen(false);
      toast.success(done, { action: { label: m.backToInbox, href: "/inbox/approvals" } });
      await refresh();
    } catch (error) {
      commandKeys.settle(signature, error);
      if (isReviewConflict(error)) {
        setRejectOpen(false);
        setNotice(m.changed);
        await refresh();
      } else {
        toast.error(m.failed(label), {
          description: error instanceof ProblemError ? [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" ") : undefined,
        });
      }
    } finally {
      setPending(null);
    }
  };

  const changes = quote ? quoteChanges(quote, zone.locale) : [];

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Link href="/inbox/approvals" className="text-sm">
          {m.backToInbox}
        </Link>
        <h1 className="text-[28px] leading-tight font-bold tracking-[-0.02em] text-ink md:text-3xl">{proposal.title}</h1>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-muted">
          <StatusPill tone={STATUS_TONE[proposal.status] ?? "neutral"}>{m.status[proposal.status] ?? proposal.status}</StatusPill>
          {proposal.requested_by_name ? <span>{m.requestedBy(proposal.requested_by_name)}</span> : null}
          {proposal.requested_at ? <LocalDateTime value={proposal.requested_at} /> : null}
        </div>
        {proposal.summary ? <p className="max-w-3xl text-ink">{proposal.summary}</p> : null}
      </header>

      {notice ? (
        <p role="alert" className="rounded-md border border-warning-text/40 bg-warning-bg px-4 py-3 text-ink">
          {notice}
        </p>
      ) : null}

      <section aria-labelledby="review-facts" className="flex flex-col gap-3">
        <h2 id="review-facts" className="text-lg font-[650] text-ink">
          {m.factsTitle}
        </h2>
        <DescriptionList
          items={[
            { term: m.facts.price_override, description: yesNo(facts.price_override) },
            { term: m.facts.discount, description: yesNo(facts.discount) },
            { term: m.facts.below_minimum, description: yesNo(facts.below_minimum) },
            { term: m.facts.grand_total, description: <Money value={grandTotal} />, numeric: true },
            ...(proposal.expires_at ? [{ term: m.expires, description: <LocalDateTime value={proposal.expires_at} /> }] : []),
            ...(proposal.decided_at ? [{ term: m.decided, description: <LocalDateTime value={proposal.decided_at} /> }] : []),
            ...(proposal.decision_reason ? [{ term: m.decisionReason, description: proposal.decision_reason }] : []),
          ]}
        />
      </section>

      {target ? (
        <section aria-labelledby="review-quote" className="flex flex-col gap-3">
          <h2 id="review-quote" className="text-lg font-[650] text-ink">
            {m.quoteTitle}
          </h2>
          {quoteQuery.isPending ? (
            <Loading label="the quote" variant="detail" />
          ) : quoteQuery.isError ? (
            <ErrorState error={quoteQuery.error} what="the quote" onRetry={() => void quoteQuery.refetch()} headingLevel={3} compact backToToday={false} />
          ) : quote ? (
            <QuoteUnderReview quote={quote} drift={drift} changes={changes} />
          ) : null}
        </section>
      ) : null}

      <section aria-labelledby="review-decision" className="flex flex-col gap-3 border-t pt-6">
        <h2 id="review-decision" className="text-lg font-[650] text-ink">
          {m.decisionTitle}
        </h2>
        {state.explanation ? <p className="text-ink-muted">{state.explanation}</p> : null}
        {state.canDecide || state.canWithdraw ? (
          <div className="flex flex-wrap gap-2">
            {state.canDecide ? (
              <>
                <Button
                  variant="primary"
                  isPending={pending === m.approve}
                  onPress={() => void act(m.approve, m.approved, (key) => decideProposal(proposal, "approve", null, key), ["approve"])}
                  {...unavailableWhen(offline)}
                >
                  {m.approve}
                </Button>
                <Button variant="danger" onPress={() => setRejectOpen(true)} {...unavailableWhen(offline)}>
                  {m.reject}
                </Button>
              </>
            ) : null}
            {state.canWithdraw ? (
              <Button
                variant="secondary"
                isPending={pending === m.withdraw}
                onPress={() => void act(m.withdraw, m.withdrawn, (key) => withdrawProposal(proposal, key), ["withdraw"])}
                {...unavailableWhen(offline)}
              >
                {m.withdraw}
              </Button>
            ) : null}
          </div>
        ) : null}
        {offline ? <p className="text-sm text-warning-text">{offline}</p> : null}
      </section>

      <ReasonDialog
        title={m.rejectTitle}
        description={proposal.title}
        requireNote
        noteLabel={m.rejectReason}
        confirmLabel={m.reject}
        isOpen={rejectOpen}
        isPending={pending !== null}
        disabledReason={offline}
        onOpenChange={setRejectOpen}
        onConfirm={(_, note) => void act(m.reject, m.rejected, (key) => decideProposal(proposal, "reject", note, key), ["reject", note])}
      />
    </div>
  );
}

function QuoteUnderReview({ quote, drift, changes }: { quote: QuoteDetail; drift: boolean; changes: string[] }) {
  const money = (amount: string | null) => (amount ? { amount, currency: quote.currency } : null);
  return (
    <div className="flex flex-col gap-4">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link href={quote.path} className="font-semibold">
          {m.openQuote(quote.quote_number)}
        </Link>
        <span className="text-ink-muted">{quote.party.display_name}</span>
      </p>
      {drift ? (
        <p role="alert" className="rounded-md border border-warning-text/40 bg-warning-bg px-4 py-3 text-ink">
          {m.versionDrift}
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-[15px]">
          <caption className="sr-only">{m.linesCaption(quote.quote_number)}</caption>
          <thead>
            <tr className="border-b text-sm text-ink-muted">
              <th scope="col" className="py-2 text-start font-semibold">{m.columns.line}</th>
              <th scope="col" className="py-2 text-end font-semibold">{m.columns.quantity}</th>
              <th scope="col" className="py-2 text-end font-semibold">{m.columns.listPrice}</th>
              <th scope="col" className="py-2 text-end font-semibold">{m.columns.quoted}</th>
              <th scope="col" className="py-2 text-end font-semibold">{m.columns.total}</th>
            </tr>
          </thead>
          <tbody>
            {quote.lines.map((line) => (
              <tr key={line.id} className="border-b">
                <th scope="row" className="py-2 pe-3 text-start font-normal">
                  {lineName(line)}
                  {line.override_reason ? <span className="block text-sm text-ink-muted">{m.overrideReason(line.override_reason)}</span> : null}
                </th>
                <td className="py-2 text-end"><Quantity value={{ value: line.quantity, uom: line.unit_code }} /></td>
                <td className="py-2 text-end"><Money value={money(line.default_unit_price)} maxFractionDigits={4} /></td>
                <td className={line.is_overridden ? "py-2 text-end font-semibold text-warning-text" : "py-2 text-end"}>
                  <Money value={money(line.unit_price)} maxFractionDigits={4} />
                </td>
                <td className="py-2 text-end"><Money value={money(line.line_total)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <QuoteTotalsList quote={quote} />
      <div className="flex flex-col gap-2">
        <h3 className="font-semibold text-ink">{m.changesTitle}</h3>
        {changes.length > 0 ? (
          <ul className="list-disc ps-5 text-[15px] text-ink">
            {changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-muted">{m.noChanges}</p>
        )}
      </div>
      <div>
        <LinkButton href={quote.path} variant="secondary">
          {m.openQuote(quote.quote_number)}
        </LinkButton>
      </div>
    </div>
  );
}

/** The persisted totals; the surcharge appears only when the server applied it. */
export function QuoteTotalsList({ quote }: { quote: Pick<QuoteDetail, "totals"> }) {
  const t = quote.totals;
  const hasDiscount = isDecimalStr(t.discount_total.amount) && !/^0+(\.0+)?$/.test(t.discount_total.amount);
  return (
    <div className="flex flex-col gap-1">
      <DescriptionList
        items={[
          { term: m.totals.subtotal, description: <Money value={t.applicable_subtotal} />, numeric: true },
          ...(hasDiscount ? [{ term: m.totals.discount, description: <Money value={t.discount_total} />, numeric: true }] : []),
          ...(t.surcharge_applied ? [{ term: t.surcharge_label || m.totals.surcharge, description: <Money value={t.surcharge} />, numeric: true }] : []),
          { term: m.totals.grand, description: <Money value={t.grand_total} className="font-semibold" />, numeric: true },
        ]}
      />
      {t.totals_complete ? null : <p className="text-sm text-warning-text">{m.incomplete}</p>}
    </div>
  );
}
