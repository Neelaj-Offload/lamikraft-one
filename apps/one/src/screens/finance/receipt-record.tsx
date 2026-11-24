"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { allocateReceipt, reverseAllocation, reverseReceipt, type AllocationRead, type ReceiptDetail } from "@/features/finance/api";
import { useFinanceCommand } from "@/features/finance/use-finance-command";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { formatMoney } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { ALLOCATION_REVERSE_REASON, asRoute, METHOD_LABEL, reasonLabel, receiptStatus, useReceipt, VOID_REASONS } from "~/data/finance";
import { Page, RecordHeader, Split } from "~/shell/page";
import {
  Badge,
  Banner,
  Button,
  Code,
  ConfirmDialog,
  Dash,
  DataTable,
  DateText,
  DecimalField,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Money,
  Select,
  Tabs,
  TextLink,
  type Column,
} from "~/ui";
import { CodeReasonDialog, LedgerLine, RecordLoading, RecordProblem, StatusBadge } from "./parts";
import { viewHref, type ReceiptView } from "./views";

const FAILED = "That did not go through";

type Run = ReturnType<typeof useFinanceCommand<ReceiptDetail>>["run"];

/** A receipt: how much of it is matched to invoices, and the allocations themselves. */
export function ReceiptRecord({ receiptId, view }: { receiptId: string; view: ReceiptView }) {
  const query = useReceipt(receiptId);
  if (query.isPending) return <RecordLoading what="the receipt" />;
  if (query.isError) return <RecordProblem error={query.error} what="This receipt" onRetry={() => void query.refetch()} backHref="/finance/receipts" backLabel="All receipts" />;
  return <Loaded receipt={query.data} view={view} />;
}

function Loaded({ receipt, view }: { receipt: ReceiptDetail; view: ReceiptView }) {
  const key = useMemo(() => queryKeys.finance.receipt(receipt.id), [receipt.id]);
  const { run, pending, offline } = useFinanceCommand<ReceiptDetail>(key);
  const [voiding, setVoiding] = useState(false);
  const caps = receipt.capabilities;
  const path = `/finance/receipts/${receipt.id}`;
  const live = receipt.allocations.filter((allocation) => !allocation.reversed && !allocation.reverses_allocation_id).length;

  useScreenContribution({ focus: { type: "finance.receipt", id: receipt.id, version: receipt.version } });

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Finance", href: "/finance" }, { label: "Receipts", href: "/finance/receipts" }, { label: receipt.receipt_number }]}
        code={receipt.receipt_number}
        title={receipt.party.display_name}
        status={<StatusBadge look={receiptStatus(receipt.status)} />}
        lead={
          <>
            Received <DateText value={receipt.received_on} style="business" /> by {(METHOD_LABEL[receipt.method] ?? receipt.method).toLowerCase()}
            {receipt.reference ? ` · ref. ${receipt.reference}` : ""}
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Amount", icon: "banknote", value: <Money value={receipt.amount} className="t-stat-sm" /> },
              { label: "Allocated", icon: "checkCircle", value: <Money value={receipt.allocated} /> },
              { label: "Still to allocate", icon: "wallet", value: <Money value={receipt.unallocated} /> },
              { label: "Received into", icon: "building", value: receipt.bank_account_label },
              { label: "Owner", icon: "user", value: receipt.owner?.display_name },
            ]}
          />
        }
        actions={
          caps.reverse?.allowed ? (
            <Button variant="secondary" iconLeft="xCircle" isDisabled={Boolean(offline)} onPress={() => setVoiding(true)}>
              Void receipt
            </Button>
          ) : null
        }
      >
        <Tabs
          label="Views of this receipt"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "allocations", label: "Allocations", count: live || undefined, href: asRoute(viewHref(path, "allocations")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this receipt. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {receipt.status === "reversed" ? (
        <Banner tone="neutral" icon="xCircle" title={`Voided${receipt.reverse_reason_code ? `: ${(reasonLabel(receipt.reverse_reason_code) ?? "").toLowerCase()}` : ""}.`}>
          Its allocations were reversed, so the invoices it paid are owed again.
        </Banner>
      ) : null}

      {view === "overview" ? <Overview receipt={receipt} run={run} pending={pending} offline={offline} /> : null}
      {view === "allocations" ? <Allocations receipt={receipt} run={run} offline={offline} /> : null}

      <CodeReasonDialog
        isOpen={voiding}
        onClose={() => setVoiding(false)}
        tone="danger"
        title="Void this receipt"
        description="Every allocation made from it is reversed, and the invoices it paid are owed again. The receipt stays on record."
        reasons={VOID_REASONS}
        confirmLabel="Void receipt"
        onConfirm={async (code, note) => Boolean(await run("void", (k) => reverseReceipt(receipt, code, note, k), { done: "Receipt voided. Its allocations were reversed.", failed: FAILED, write: (result) => result }))}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: how much is matched, and the next allocation

function standingOf(receipt: ReceiptDetail): { headline: ReactNode; body: ReactNode } {
  if (receipt.status === "reversed") return { headline: "Voided", body: "This receipt no longer counts towards any invoice." };
  if (isPositiveDecimalStr(receipt.unallocated.amount)) {
    return {
      headline: (
        <>
          <Money value={receipt.unallocated} /> still to <em>allocate</em>
        </>
      ),
      body: "Until it is matched to an invoice, this money does not reduce what the customer owes.",
    };
  }
  return { headline: <>Allocated in <em>full</em></>, body: "Every part of this receipt is matched to an invoice." };
}

function AllocateForm({ receipt, run, pending, offline }: { receipt: ReceiptDetail; run: Run; pending: string | null; offline: string | null }) {
  const { locale } = useZone();
  const [chosen, setChosen] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [errors, setErrors] = useState<{ invoice?: string; amount?: string }>({});
  const open = receipt.open_invoices;
  // The chosen invoice can leave the list once it is paid in full; fall back to the first one still open.
  const invoiceId = open.some((invoice) => invoice.id === chosen) ? chosen : (open[0]?.id ?? null);

  const submit = async () => {
    const found: typeof errors = {};
    if (!invoiceId) found.invoice = "Choose the invoice this money pays.";
    if (!isPositiveDecimalStr(amount)) found.amount = "Enter the amount to allocate, above zero.";
    setErrors(found);
    if (!invoiceId || found.amount) return;
    const result = await run("allocate", (k) => allocateReceipt(receipt.id, invoiceId, amount, k), { done: "Allocated", failed: "The allocation was not saved", write: (updated) => updated });
    if (result) setAmount("");
  };

  return (
    <GlassPanel padding="lg" className="rise flex flex-col gap-4" title="Allocate to an invoice" titleAs="h2">
      {open.length === 0 ? (
        <p className="t-body text-ink-2">
          {receipt.party.display_name} has no open invoice in {receipt.amount.currency}. The money stays on this receipt until one is issued.
        </p>
      ) : (
        <>
          <p className="t-body-sm text-ink-3">
            Open invoices of {receipt.party.display_name} in {receipt.amount.currency}. Allocate part of the receipt, or all of it.
          </p>
          <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
            <Select
              label="Invoice"
              options={open.map((invoice) => ({
                value: invoice.id,
                label: invoice.document_number,
                description: `${formatMoney(invoice.outstanding, { locale }) ?? `${invoice.outstanding.amount} ${invoice.outstanding.currency}`} outstanding`,
              }))}
              value={invoiceId}
              onChange={(value) => {
                setChosen(value);
                setErrors((current) => ({ ...current, invoice: undefined }));
              }}
              isRequired
              error={errors.invoice}
            />
            <DecimalField
              label="Amount to allocate"
              value={amount}
              prefix={receipt.amount.currency}
              onChange={(value) => {
                setAmount(value);
                setErrors((current) => ({ ...current, amount: undefined }));
              }}
              isRequired
              help={`Up to ${formatMoney(receipt.unallocated, { locale }) ?? receipt.unallocated.amount} is left on this receipt.`}
              error={errors.amount}
            />
          </div>
          <div>
            <Button iconLeft="check" loading={pending === "allocate"} isDisabled={Boolean(offline)} onPress={() => void submit()}>
              Allocate to invoice
            </Button>
          </div>
        </>
      )}
    </GlassPanel>
  );
}

function Overview({ receipt, run, pending, offline }: { receipt: ReceiptDetail; run: Run; pending: string | null; offline: string | null }) {
  const standing = standingOf(receipt);
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-2" eyebrow="Where it stands">
            <h2 className="t-display-sm text-ink">{standing.headline}</h2>
            <p className="t-body max-w-prose text-ink-2">{standing.body}</p>
          </GlassPanel>
          {receipt.capabilities.allocate?.allowed ? <AllocateForm receipt={receipt} run={run} pending={pending} offline={offline} /> : null}
        </>
      }
      aside={
        <>
          <section aria-label="Receipt amounts" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6">
            <h2 className="t-overline opacity-70">This receipt</h2>
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
              <span className="t-label">Received</span>
              <span className="t-stat-xl ml-auto text-right">
                <Money value={receipt.amount} />
              </span>
            </div>
            <dl className="m-0 flex flex-col gap-2 border-t border-on-inverse/20 pt-5">
              <LedgerLine label="Allocated to invoices">
                <Money value={receipt.allocated} />
              </LedgerLine>
              <LedgerLine label="Still to allocate" strong>
                <Money value={receipt.unallocated} />
              </LedgerLine>
            </dl>
          </section>
          <GlassPanel padding="md" className="rise" title="Details" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Customer", value: <TextLink href={asRoute(`/sales/parties/${receipt.party.id}`)}>{receipt.party.display_name}</TextLink> },
                { label: "Received on", value: <DateText value={receipt.received_on} style="business" /> },
                { label: "Method", value: METHOD_LABEL[receipt.method] ?? receipt.method },
                { label: "Reference", value: receipt.reference },
                { label: "Received into", value: receipt.bank_account_label },
                { label: "Recorded by", value: receipt.owner?.display_name },
                ...(receipt.notes ? [{ label: "Notes", value: receipt.notes }] : []),
                ...(receipt.reversed_at ? [{ label: "Voided", value: <DateText value={receipt.reversed_at} style="dayTime" /> }] : []),
              ]}
            />
          </GlassPanel>
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Allocations

function Allocations({ receipt, run, offline }: { receipt: ReceiptDetail; run: Run; offline: string | null }) {
  const [reversing, setReversing] = useState<AllocationRead | null>(null);
  // The same test the old screen used: a live allocation on a recorded receipt, for someone who may allocate.
  const canReverse = receipt.status === "recorded" && receipt.capabilities.allocate?.reason_code !== "permission_denied";
  const reversible = (allocation: AllocationRead) => canReverse && !allocation.reverses_allocation_id && !allocation.reversed;

  const columns: Column<AllocationRead>[] = [
    {
      key: "invoice",
      header: "Invoice",
      primary: true,
      cell: (allocation) => (
        <TextLink href={asRoute(`/finance/invoices/${allocation.invoice_id}`)}>
          <Code>{allocation.invoice_number}</Code>
        </TextLink>
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
  if (receipt.allocations.some(reversible)) {
    columns.push({
      key: "action",
      header: <span className="lk-sr-only">Actions</span>,
      mobileLabel: "Action",
      numeric: true,
      cell: (allocation) =>
        reversible(allocation) ? (
          <Button variant="ghost" size="sm" iconLeft="undo" isDisabled={Boolean(offline)} onPress={() => setReversing(allocation)}>
            Reverse
          </Button>
        ) : null,
    });
  }

  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Allocations</h2>
        <p className="t-body-sm text-ink-3">Each part of this receipt and the invoice it pays. A reversal is kept as its own line.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Allocations of ${receipt.receipt_number}`}
          columns={columns}
          rows={receipt.allocations}
          rowKey={(allocation) => allocation.id}
          empty={<EmptyState compact icon="banknote" title="Nothing allocated yet" text="Allocate this receipt to an invoice from the overview. Each allocation is listed here." />}
        />
      </GlassPanel>

      <ConfirmDialog
        isOpen={reversing !== null}
        onOpenChange={(open) => (open ? undefined : setReversing(null))}
        tone="danger"
        title="Reverse this allocation"
        description={
          reversing ? (
            <>
              <Money value={reversing.amount} /> goes back onto this receipt, and invoice {reversing.invoice_number} is owed that much again.
            </>
          ) : undefined
        }
        confirmLabel="Reverse allocation"
        cancelLabel="Keep it"
        onConfirm={async () => {
          if (!reversing) return;
          const result = await run(`rev:${reversing.id}`, (k) => reverseAllocation(reversing.id, ALLOCATION_REVERSE_REASON, k), { done: "Allocation reversed", failed: FAILED });
          if (!result) throw new Error("The allocation was not reversed");
        }}
      />
    </div>
  );
}
