"use client";

import { useState, type ReactNode } from "react";
import { updateTaxProfile, type AllocationRead, type InvoiceDetail, type InvoiceLine } from "@/features/finance/api";
import type { useFinanceCommand } from "@/features/finance/use-finance-command";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { formatDecimal } from "@/lib/format/money";
import {
  asRoute,
  BLOCKER_FIX_LABEL,
  blockerText,
  documentStatus,
  HISTORY_DID,
  HISTORY_ICON,
  humanise,
  reasonLabel,
  serverPath,
  TAX_STATUS_LABEL,
  useTaxProfiles,
} from "~/data/finance";
import { Split } from "~/shell/page";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { Badge, Button, Code, Dash, DataTable, DateText, EmptyState, GlassPanel, Icon, KeyValue, Money, Qty, Select, TextLink, Timeline, type Column, type TimelineItem } from "~/ui";
import { LedgerLine, UnitPrice } from "./parts";

type Run = ReturnType<typeof useFinanceCommand<InvoiceDetail>>["run"];

// ---------------------------------------------------------------------------------------------
// Overview: where it stands and what is next

function progressOf(doc: InvoiceDetail, credit: boolean): StepItem[] {
  const cancelled = doc.status === "cancelled";
  const submitted = doc.status !== "draft";
  const approved = doc.status === "approved" || doc.status === "issued";
  const issued = doc.status === "issued";
  const settled = issued && doc.outstanding !== null && !isPositiveDecimalStr(doc.outstanding.amount);
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "submitted", label: "Submitted", hint: "Drafted and sent for approval", done: submitted },
    { id: "approved", label: "Approved", hint: doc.approved_at ? <DateText value={doc.approved_at} style="date" /> : "By someone other than the drafter", done: approved },
    { id: "issued", label: "Issued", hint: doc.issued_at ? <DateText value={doc.issued_at} style="date" /> : "Numbered and valid for trade", done: issued },
    ...(credit ? [] : [{ id: "settled", label: "Settled", hint: settled ? "Paid or credited in full" : "Receipts and credit notes", done: settled }]),
  ];
  const current = cancelled ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !cancelled ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(doc: InvoiceDetail, credit: boolean): { headline: ReactNode; body: ReactNode } {
  const noun = credit ? "credit note" : "invoice";
  if (doc.status === "cancelled") return { headline: "Cancelled", body: `Nothing more happens with this ${noun}. It stays on record with the reason it was cancelled.` };
  if (doc.status === "issued") {
    if (credit) return { headline: <>Issued to the <em>customer</em></>, body: "An issued credit note settles the invoice it was raised against first." };
    if (doc.outstanding && isPositiveDecimalStr(doc.outstanding.amount)) {
      return doc.is_overdue
        ? { headline: <>Issued, and now <em>overdue</em></>, body: <><Money value={doc.outstanding} /> is still owed and the due date has passed. Record the receipt when the money arrives.</> }
        : { headline: <>Issued, waiting for <em>payment</em></>, body: <><Money value={doc.outstanding} /> is still owed. Record the receipt when the money arrives, then allocate it here.</> };
    }
    return { headline: <>Settled in <em>full</em></>, body: "Receipts and credit notes cover the whole amount. Nothing is owed on this invoice." };
  }
  if (doc.status === "approved") {
    return doc.gate.can_issue
      ? { headline: <>Approved and ready to <em>issue</em></>, body: `Issuing gives the ${noun} its number and makes it valid for trade.` }
      : { headline: <>Approved, not yet ready to <em>issue</em></>, body: "The issue check below lists what is still missing." };
  }
  if (doc.status === "pending_approval") {
    return {
      headline: <>Waiting for <em>approval</em></>,
      body: doc.capabilities.approve?.reason_code === "creator_cannot_approve" ? "You drafted it, so someone else has to approve it." : `Someone other than the drafter approves the ${noun}. Then it can be issued.`,
    };
  }
  return { headline: <>A draft, not yet <em>submitted</em></>, body: "Check the lines and the tax profile, then submit it for approval." };
}

function IssueCheck({ doc }: { doc: InvoiceDetail }) {
  const blockers = doc.gate.blockers;
  return (
    <GlassPanel
      padding="lg"
      className="rise flex flex-col gap-4"
      title="Issue check"
      titleAs="h2"
      action={
        blockers.length === 0 ? (
          <Badge tone="leaf" icon="check">
            Ready
          </Badge>
        ) : (
          <Badge tone="amber">{blockers.length === 1 ? "1 thing missing" : `${blockers.length} things missing`}</Badge>
        )
      }
    >
      {blockers.length === 0 ? (
        <p className="t-body text-ink-2">Everything needed to issue is in place.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {blockers.map((blocker) => (
            <li key={blocker.code} className="flex min-w-0 items-start gap-3 border-line py-3 [&:not(:first-child)]:border-t">
              <span className="mt-0.5 flex-none text-amber">
                <Icon name="alert" size={16} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="t-body text-ink">
                  {blockerText(blocker.code)}
                  {blocker.code === "not_approved" && doc.capabilities.approve?.reason_code === "creator_cannot_approve" ? " You drafted it, so someone else has to approve it." : ""}
                </span>
                {blocker.fix_path ? (
                  <span>
                    <TextLink href={serverPath(blocker.fix_path)}>{BLOCKER_FIX_LABEL[blocker.code] ?? "Fix this"}</TextLink>
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}

const NO_PROFILE = "none";

function TaxProfilePicker({ doc, run, pending, offline }: { doc: InvoiceDetail; run: Run; pending: string | null; offline: string | null }) {
  const profiles = useTaxProfiles();
  const current = doc.tax_profile?.id ?? NO_PROFILE;
  const [choice, setChoice] = useState<string>(current);
  const options = [
    { value: NO_PROFILE, label: "No tax profile", description: "No tax is calculated" },
    ...(profiles.data ?? []).map((profile) => ({
      value: profile.id,
      label: `${profile.code} · ${formatDecimal(profile.rate_percent) ?? profile.rate_percent}%`,
      description: `${profile.name} · ${profile.status === "verified" ? "Verified" : "Not yet verified"}`,
    })),
  ];
  return (
    <GlassPanel padding="lg" className="rise flex flex-col gap-4" title="Tax profile" titleAs="h2">
      <p className="t-body-sm text-ink-3">The profile sets the tax on every line. Applying a different one recalculates the totals.</p>
      <div className="flex min-w-0 flex-wrap items-end gap-3">
        <Select
          className="min-w-0 flex-1 basis-64"
          label="Tax profile for this document"
          options={options}
          value={choice}
          onChange={setChoice}
          isDisabled={profiles.isPending}
          error={profiles.isError ? "The tax profiles could not load. Reload the page to try again." : undefined}
        />
        <Button
          variant="secondary"
          loading={pending === "profile"}
          isDisabled={Boolean(offline) || choice === current}
          onPress={() => void run("profile", (k) => updateTaxProfile(doc, choice === NO_PROFILE ? null : choice, k), { done: "Tax profile applied. Totals recalculated.", failed: "That did not go through", write: (result) => result })}
        >
          Apply profile
        </Button>
      </div>
    </GlassPanel>
  );
}

export function OverviewView({ doc, credit, run, pending, offline }: { doc: InvoiceDetail; credit: boolean; run: Run; pending: string | null; offline: string | null }) {
  const standing = standingOf(doc, credit);
  const billing = doc.billing as { legal_name?: string; address_lines?: string[] };
  const open = doc.status !== "issued" && doc.status !== "cancelled";
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label={`Progress of this ${credit ? "credit note" : "invoice"}`} steps={progressOf(doc, credit)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>
          {open ? <IssueCheck doc={doc} /> : null}
          {doc.capabilities.update?.allowed ? <TaxProfilePicker doc={doc} run={run} pending={pending} offline={offline} /> : null}
        </>
      }
      aside={
        <>
          <section aria-label="Totals" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="t-overline opacity-70">Totals</h2>
              <span className="t-caption lk-tnum opacity-70">
                {doc.currency} · {doc.lines.length === 1 ? "1 line" : `${doc.lines.length} lines`}
              </span>
            </div>
            <dl className="m-0 flex flex-col gap-2">
              <LedgerLine label="Subtotal">
                <Money value={doc.subtotal} />
              </LedgerLine>
              <LedgerLine label="Tax">{doc.tax ? <Money value={doc.tax} /> : (TAX_STATUS_LABEL.not_configured ?? "Tax not calculated")}</LedgerLine>
            </dl>
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 border-t border-on-inverse/20 pt-5">
              <span className="t-label">Total</span>
              <span className="t-stat-xl ml-auto text-right">
                <Money value={doc.total} />
              </span>
            </div>
            <dl className="m-0 flex flex-col gap-2 border-t border-on-inverse/20 pt-5">
              <LedgerLine label="Settled">
                <Money value={doc.allocated} />
              </LedgerLine>
              {credit ? null : (
                <>
                  <LedgerLine label="Credited">
                    <Money value={doc.credited} />
                  </LedgerLine>
                  <LedgerLine label="Outstanding" strong>
                    <Money value={doc.outstanding} />
                  </LedgerLine>
                </>
              )}
            </dl>
          </section>

          <GlassPanel padding="md" className="rise" title="Bill to" titleAs="h2">
            <div className="flex flex-col gap-1">
              <TextLink href={asRoute(`/sales/parties/${doc.party.id}`)}>{billing.legal_name ?? doc.party.display_name}</TextLink>
              <p className="t-body-sm text-ink-3">{billing.address_lines?.length ? billing.address_lines.join(", ") : "No billing address on file."}</p>
            </div>
          </GlassPanel>

          {doc.related.length > 0 ? (
            <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
              <KeyValue
                rows
                items={doc.related.map((related) => ({
                  label: humanise(related.kind),
                  value: (
                    <TextLink href={serverPath(related.path)}>
                      <Code>{related.number}</Code>
                    </TextLink>
                  ),
                }))}
              />
            </GlassPanel>
          ) : null}
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Lines

export function LinesView({ doc, number }: { doc: InvoiceDetail; number: string }) {
  const columns: Column<InvoiceLine>[] = [
    {
      key: "item",
      header: "Line",
      primary: true,
      cell: (line) => (
        <span className="flex min-w-0 items-start gap-3">
          <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{line.line_no}</span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="t-label text-ink">{line.description}</span>
            {line.item_code ? <Code className="text-ink-3">{line.item_code}</Code> : null}
          </span>
        </span>
      ),
    },
    { key: "hsn", header: "HSN/SAC", hideOnMobile: true, cell: (line) => (line.hsn_sac ? <Code>{line.hsn_sac}</Code> : <Dash />) },
    { key: "quantity", header: "Quantity", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.uom_code }} /> },
    { key: "price", header: "Unit price", numeric: true, cell: (line) => <UnitPrice value={line.unit_price} /> },
    { key: "amount", header: "Amount", numeric: true, cell: (line) => <Money value={line.amount} className="t-label text-ink" /> },
  ];
  if (doc.lines.some((line) => line.creditable_quantity != null)) {
    columns.push({
      key: "creditable",
      header: "Can still be credited",
      mobileLabel: "Creditable",
      numeric: true,
      cell: (line) => (line.creditable_quantity != null ? <Qty value={{ value: line.creditable_quantity, uom: line.uom_code }} /> : <Dash />),
    });
  }
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">What is billed, as delivered. Quantities and prices come from the delivery and its order.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Lines of ${number}`}
          columns={columns}
          rows={doc.lines}
          rowKey={(line) => line.id}
          empty={<EmptyState compact icon="list" title="This document has no lines" text="A document without lines cannot be issued." />}
        />
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Settlements: receipts and credit notes allocated to it

export function SettlementsView({ doc, credit }: { doc: InvoiceDetail; credit: boolean }) {
  const columns: Column<AllocationRead>[] = [
    {
      key: "source",
      header: credit ? "Applied to" : "Settled by",
      primary: true,
      cell: (allocation) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{credit ? allocation.invoice_number : allocation.receipt_id ? allocation.receipt_number : allocation.credit_note_number}</Code>
          <span className="t-caption text-ink-3">{credit ? "Invoice" : allocation.receipt_id ? "Receipt" : "Credit note"}</span>
        </span>
      ),
    },
    { key: "date", header: "Allocated on", cell: (allocation) => <DateText value={allocation.allocated_on} style="business" /> },
    {
      key: "state",
      header: "State",
      cell: (allocation) =>
        allocation.reverses_allocation_id ? (
          <Badge tone="neutral" icon="undo">
            Reversal
          </Badge>
        ) : allocation.reversed ? (
          <Badge tone="neutral" outline>
            Reversed
          </Badge>
        ) : (
          <Badge tone="leaf" icon="check">
            Counted
          </Badge>
        ),
    },
    { key: "by", header: "By", hideOnMobile: true, cell: (allocation) => allocation.actor?.display_name ?? <Dash /> },
    { key: "amount", header: "Amount", numeric: true, cell: (allocation) => <Money value={allocation.amount} className="t-label text-ink" /> },
  ];
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Settlements</h2>
        <p className="t-body-sm text-ink-3">{credit ? "The invoices this credit note has been applied to." : "Receipts and credit notes allocated to this invoice. A receipt is allocated from its own page."}</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label="Settlements"
          columns={columns}
          rows={doc.allocations}
          rowKey={(allocation) => allocation.id}
          rowHref={(allocation) =>
            asRoute(
              credit || (!allocation.receipt_id && !allocation.credit_note_id)
                ? `/finance/invoices/${allocation.invoice_id}`
                : allocation.receipt_id
                  ? `/finance/receipts/${allocation.receipt_id}`
                  : `/finance/credit-notes/${allocation.credit_note_id}`,
            )
          }
          empty={
            <EmptyState
              compact
              icon="banknote"
              title="Nothing has been settled yet"
              text={credit ? "Once this credit note is issued, what it settles is listed here." : "When a receipt or a credit note is allocated to this invoice, it is listed here."}
            />
          }
        />
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Activity

export function ActivityView({ doc }: { doc: InvoiceDetail }) {
  const items: TimelineItem[] = [...doc.history]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .map((entry, index) => {
      const reason = [reasonLabel(entry.reason_code), entry.reason].filter(Boolean).join(": ");
      const refused = entry.blocker_codes.map(blockerText).join(" ");
      return {
        id: `${entry.occurred_at}-${index}`,
        title: `${entry.actor?.display_name ?? "Lamikraft One"} ${HISTORY_DID[entry.action] ?? humanise(entry.action).toLowerCase()}`,
        meta: <DateText value={entry.occurred_at} style="dayTime" />,
        body: [reason, refused].filter(Boolean).join(" ") || undefined,
        icon: HISTORY_ICON[entry.action],
        tone: entry.action === "issue_blocked" ? "amber" : documentStatus(entry.to_status).tone,
      };
    });
  return (
    <GlassPanel padding="lg" title="Activity" titleAs="h2" className="rise">
      {items.length === 0 ? <EmptyState compact icon="history" title="Nothing has happened yet" text="Submissions, approvals and the issue are listed here." /> : <Timeline label="Document activity" items={items} />}
    </GlassPanel>
  );
}
