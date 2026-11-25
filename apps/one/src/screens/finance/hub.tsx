"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { dismissSuggestion, draftFromSuggestion, type FinanceSummary, type Suggestion } from "@/features/finance/api";
import { useFinanceCommand } from "@/features/finance/use-finance-command";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, DISMISS_REASONS, useFinanceSummary, useInvoiceSuggestions } from "~/data/finance";
import { Page, PageHeader, PageSection, Split } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, Code, CountUp, DateText, EmptyState, GlassPanel, Icon, KeyValue, Money, Skeleton, StatTile, TextLink, type IconName, type Tone } from "~/ui";
import { CodeReasonDialog, DemoBadge, stagger } from "./parts";

const FAILED = "That did not go through";

const SCREENS: { href: string; label: string; icon: IconName; line: string; demo?: boolean }[] = [
  { href: "/finance/invoices", label: "Invoices", icon: "receipt", line: "Drafts, approvals and issued invoices, with what each still owes." },
  { href: "/finance/receipts", label: "Receipts", icon: "banknote", line: "Money received from customers and the invoices it settled." },
  { href: "/finance/credit-notes", label: "Credit notes", icon: "undo", line: "Credits raised against issued invoices." },
  { href: "/finance/ageing", label: "Ageing", icon: "clock", line: "What each customer owes, by how long it has been due." },
  { href: "/finance/exceptions", label: "Exceptions", icon: "alert", line: "Blocked issues, overdue invoices, loose receipts and thin margins." },
  { href: "/finance/accounting-sync", label: "Accounting sync", icon: "refresh", line: "Hand issued documents to accounting as a journal, then reconcile.", demo: true },
];

interface AttentionRow {
  id: string;
  icon: IconName;
  title: string;
  detail: string;
  ask: string;
  tone: Tone;
  href: string;
}

const plural = (count: number, one: string, many: string) => (count === 1 ? `1 ${one}` : `${count} ${many}`);

function attentionRows(s: FinanceSummary): AttentionRow[] {
  const rows: AttentionRow[] = [];
  if (s.overdue > 0) {
    rows.push({ id: "overdue", icon: "clock", title: plural(s.overdue, "invoice is past due", "invoices are past due"), detail: "Issued, still owed, and beyond the due date.", ask: "Chase", tone: "ember", href: "/finance/invoices?overdue=1" });
  }
  if (s.issue_blocked > 0) {
    rows.push({ id: "blocked", icon: "lock", title: plural(s.issue_blocked, "document cannot be issued yet", "documents cannot be issued yet"), detail: "The issue check lists what each one still needs.", ask: "Unblock", tone: "amber", href: "/finance/exceptions?kind=issue_blocked" });
  }
  if (s.drafts > 0) {
    rows.push({ id: "drafts", icon: "edit", title: plural(s.drafts, "draft to finish", "drafts to finish"), detail: "Not yet submitted for approval.", ask: "Submit", tone: "neutral", href: "/finance/invoices?status=draft" });
  }
  if (s.margin_exceptions > 0) {
    rows.push({ id: "margin", icon: "percent", title: plural(s.margin_exceptions, "quotation is below the margin policy", "quotations are below the margin policy"), detail: "Issued to customers at less than the agreed margin.", ask: "Review", tone: "amber", href: "/finance/exceptions?view=margin" });
  }
  if (s.sync_attention > 0) {
    rows.push({ id: "sync", icon: "refresh", title: plural(s.sync_attention, "accounting export needs a look", "accounting exports need a look"), detail: "An export failed, or its reconciliation did not match.", ask: "Check", tone: "ember", href: "/finance/accounting-sync" });
  }
  return rows;
}

function StatFigure({ value }: { value: number | undefined }) {
  return value === undefined ? <Skeleton width={44} height={32} /> : <CountUp value={value} />;
}

/** The finance overview: the counts that matter, what is waiting, what is owed per currency, and the way into each screen. */
export function FinanceHub() {
  const summary = useFinanceSummary();
  const s = summary.data;
  const rows = s ? attentionRows(s) : [];

  return (
    <Page>
      <PageHeader
        display
        eyebrow="Finance"
        title={
          <>
            From delivery to <em>settled</em> invoice
          </>
        }
        lead="What is waiting to be invoiced, approved, collected and handed to accounting."
      />

      {summary.isError ? (
        <ErrorBlock error={summary.error} what="The finance figures" onRetry={() => void summary.refetch()} />
      ) : (
        <>
          <div className="tiles" aria-label="Finance at a glance" role="group">
            <GlassPanel interactive className="rise" style={stagger(1)}>
              <StatTile
                label="Open invoices"
                value={<StatFigure value={s?.issued_open} />}
                foot={s ? (s.overdue > 0 ? plural(s.overdue, "is overdue", "are overdue") : "None overdue") : undefined}
                dot={Boolean(s?.overdue)}
                href={asRoute("/finance/invoices?open=1")}
              />
            </GlassPanel>
            <GlassPanel interactive className="rise" style={stagger(2)}>
              <StatTile
                label="Awaiting approval"
                value={<StatFigure value={s?.pending_approval} />}
                foot={s ? (s.drafts > 0 ? plural(s.drafts, "more still in draft", "more still in draft") : "No drafts behind them") : undefined}
                href={asRoute("/finance/invoices?status=pending_approval")}
              />
            </GlassPanel>
            <GlassPanel className="rise" style={stagger(3)}>
              <StatTile label="Deliveries to invoice" value={<StatFigure value={s?.open_suggestions} />} foot={s ? "Issued challans with no invoice yet" : undefined} />
            </GlassPanel>
            <GlassPanel interactive className="rise" style={stagger(4)}>
              <StatTile
                label="Unallocated receipts"
                value={<StatFigure value={s?.unallocated_receipts} />}
                foot={s ? (s.unallocated_receipts > 0 ? "Received, not yet matched to an invoice" : "Every receipt is matched") : undefined}
                dot={Boolean(s?.unallocated_receipts)}
                href={asRoute("/finance/receipts?unallocated=1")}
              />
            </GlassPanel>
          </div>

          <Split
            main={
              <>
                <PageSection title="Needs attention" description="Counted by the server just now. Each line opens the list behind it." index={1}>
                  <GlassPanel padding="none" className="overflow-hidden">
                    {!s ? (
                      <RowSkeleton label="Loading what needs attention" />
                    ) : rows.length === 0 ? (
                      <EmptyState compact icon="checkCircle" title="Nothing is waiting on finance" text="No overdue invoice, no blocked issue, no draft left open. New ones appear here first." />
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
                              <Link href={asRoute(row.href)} className="stretched t-label text-ink no-underline">
                                {row.title}
                              </Link>
                              <span className="t-caption text-ink-3">{row.detail}</span>
                            </span>
                            <span className="hidden flex-none sm:block">
                              <Badge tone={row.tone} size="sm">
                                {row.ask}
                              </Badge>
                            </span>
                            <span className="flex-none text-ink-3">
                              <Icon name="chevronRight" size={16} />
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </GlassPanel>
                </PageSection>

                <Suggestions canCreate={Boolean(s?.capabilities?.create_invoice?.allowed)} />
              </>
            }
            aside={
              <>
                <Receivables summary={s} />
                <SetUp summary={s} />
              </>
            }
          />
        </>
      )}

      <PageSection title="Everything in finance" index={3}>
        <ul className="tiles m-0 list-none p-0" data-min="lg">
          {SCREENS.map((screen, index) => (
            <GlassPanel as="li" key={screen.href} variant="outline" interactive className="rise-plain flex items-start gap-4" style={stagger(index)}>
              <span className="mt-0.5 flex-none text-ink-3">
                <Icon name={screen.icon} size={20} />
              </span>
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                  <Link href={asRoute(screen.href)} className="stretched t-h4 text-ink no-underline">
                    {screen.label}
                  </Link>
                  {screen.demo ? <DemoBadge /> : null}
                </span>
                <span className="t-body-sm text-ink-3">{screen.line}</span>
              </span>
            </GlassPanel>
          ))}
        </ul>
      </PageSection>
    </Page>
  );
}

function RowSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label}>
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
  );
}

// ---------------------------------------------------------------------------------------------
// Issued challans waiting for an invoice

function Suggestions({ canCreate }: { canCreate: boolean }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.finance.suggestions(), []);
  const query = useInvoiceSuggestions();
  const { run, pending, offline } = useFinanceCommand<Suggestion[]>(key);
  const [dismissing, setDismissing] = useState<Suggestion | null>(null);

  const draft = (suggestion: Suggestion) =>
    void run(`draft:${suggestion.id}`, (k) => draftFromSuggestion(suggestion.id, k), { done: "Invoice draft created", failed: FAILED }).then((invoice) => {
      if (invoice) router.push(asRoute(`/finance/invoices/${invoice.id}`));
    });

  return (
    <PageSection title="Delivered, not yet invoiced" description="Every issued delivery challan asks for an invoice. Draft it here, or dismiss it with a reason." index={2}>
      {query.isError ? (
        <ErrorBlock error={query.error} what="Deliveries to invoice" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="overflow-hidden">
          {query.isPending ? (
            <RowSkeleton label="Loading deliveries to invoice" />
          ) : query.data.length === 0 ? (
            <EmptyState compact icon="fileCheck" title="Every delivery has its invoice" text="Each issued challan has an invoice draft or was dismissed. The next delivery appears here." />
          ) : (
            <ul className="m-0 flex list-none flex-col p-0">
              {query.data.map((suggestion, index) => (
                <li key={suggestion.id} className="rise-plain flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3 border-line px-5 py-4 [&:not(:first-child)]:border-t" style={stagger(index)}>
                  <span className="grid size-9 flex-none place-items-center rounded-pill border border-line text-ink-2">
                    <Icon name="truck" size={16} />
                  </span>
                  <span className="flex min-w-0 flex-1 basis-48 flex-col gap-0.5">
                    <span className="t-label truncate text-ink" title={suggestion.party.display_name}>
                      {suggestion.party.display_name}
                    </span>
                    <span className="t-caption text-ink-3">
                      Challan{" "}
                      <TextLink href={asRoute(`/operations/challans/${suggestion.challan_id}`)}>
                        <Code>{suggestion.challan_number}</Code>
                      </TextLink>
                      {" · issued "}
                      <DateText value={suggestion.created_at} style="relative" />
                    </span>
                  </span>
                  {canCreate ? (
                    <span className="flex flex-none flex-wrap items-center gap-2">
                      <Button variant="inverse" size="sm" iconLeft="filePlus" loading={pending === `draft:${suggestion.id}`} isDisabled={Boolean(offline)} onPress={() => draft(suggestion)}>
                        Draft invoice
                      </Button>
                      <Button variant="ghost" size="sm" isDisabled={Boolean(offline)} onPress={() => setDismissing(suggestion)}>
                        Dismiss
                      </Button>
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>
      )}

      <CodeReasonDialog
        isOpen={dismissing !== null}
        onClose={() => setDismissing(null)}
        title="Dismiss this delivery"
        description={dismissing ? `No invoice will be drafted for challan ${dismissing.challan_number} (${dismissing.party.display_name}). The reason is kept.` : undefined}
        reasons={DISMISS_REASONS}
        note={false}
        confirmLabel="Dismiss delivery"
        cancelLabel="Keep it"
        onConfirm={async (code) => (dismissing ? Boolean(await run(`dismiss:${dismissing.id}`, (k) => dismissSuggestion(dismissing, code, k), { done: "Delivery dismissed", failed: FAILED })) : false)}
      />
    </PageSection>
  );
}

// ---------------------------------------------------------------------------------------------
// What is owed, per currency

function Receivables({ summary }: { summary: FinanceSummary | undefined }) {
  return (
    <section aria-label="Receivables by currency" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6" style={stagger(2)}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="t-overline opacity-70">Owed to you</h2>
        {summary ? (
          <span className="t-caption opacity-70">
            as of <DateText value={summary.as_of} style="business" />
          </span>
        ) : null}
      </div>
      {!summary ? (
        <div role="status" aria-label="Loading receivables" className="flex flex-col gap-3">
          <Skeleton width="60%" height={32} />
          <Skeleton width="80%" />
        </div>
      ) : summary.by_currency.length === 0 ? (
        <p className="t-body opacity-80">No issued invoice has anything outstanding.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-5 p-0">
          {summary.by_currency.map((figure) => (
            <li key={figure.currency} className="flex min-w-0 flex-col gap-2 border-on-inverse/20 [&:not(:first-child)]:border-t [&:not(:first-child)]:pt-5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="t-label">{figure.currency}</span>
                <span className="t-stat ml-auto text-right">
                  <Money value={figure.receivable} />
                </span>
              </div>
              <dl className="m-0 flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-4">
                  <dt className="t-body-sm opacity-70">Of which overdue</dt>
                  <dd className="t-body lk-tnum m-0">
                    <Money value={figure.overdue} />
                  </dd>
                </div>
                <div className="flex items-baseline justify-between gap-4">
                  <dt className="t-body-sm opacity-70">Receipts not yet allocated</dt>
                  <dd className="t-body lk-tnum m-0">
                    <Money value={figure.unallocated} />
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      )}
      <p className="t-body-sm opacity-80">Each currency stands alone. Amounts are never added across currencies.</p>
    </section>
  );
}

// ---------------------------------------------------------------------------------------------
// What issuing needs, and how this workspace is set up for it

function Connection({ state }: { state: string }) {
  return state === "connected" ? (
    <Badge tone="leaf" dot size="sm">
      Connected
    </Badge>
  ) : (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      Not connected
      <DemoBadge />
    </span>
  );
}

function SetUp({ summary }: { summary: FinanceSummary | undefined }) {
  return (
    <GlassPanel padding="md" className="rise flex flex-col gap-4" title="What issuing needs" titleAs="h2" style={stagger(3)}>
      <p className="t-body-sm text-ink-2">
        A draft can always be prepared and printed, marked as not valid for trade. Issuing a tax invoice needs your company identity, a tax profile verified by a second person, an e-invoice provider when the
        profile calls for one, and approval by someone other than the drafter. Each invoice lists what it still lacks.
      </p>
      {summary ? (
        <KeyValue
          rows
          items={[
            { label: "Accounting system", value: <Connection state={summary.accounting_state} /> },
            { label: "E-invoice provider", value: <Connection state={summary.e_invoice_state} /> },
            {
              label: "Tax profiles",
              value: <TextLink href={asRoute("/finance/accounting-sync#tax-profiles")}>{summary.tax_profiles_verified === 1 ? "1 verified" : `${summary.tax_profiles_verified} verified`}</TextLink>,
            },
          ]}
        />
      ) : (
        <div role="status" aria-label="Loading the set-up">
          <Skeleton width="100%" height={14} />
        </div>
      )}
    </GlassPanel>
  );
}
