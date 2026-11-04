"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { LocalDate, Money } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { financeMessages as m } from "@/messages/finance";
import { allocateReceipt, fetchReceipt, reverseAllocation, reverseReceipt, type ReceiptDetail } from "./api";
import { FinanceStatus } from "./finance-screens";
import { useFinanceCommand } from "./use-finance-command";

const r = m.receipts;
const VOID_REASONS = [
  { id: "bounced", label: "Payment bounced" },
  { id: "entered_in_error", label: "Entered in error" },
  { id: "duplicate", label: "Duplicate receipt" },
] as const;

export function ReceiptWorkspace({ receiptId }: { receiptId: string }) {
  const query = useQuery({ queryKey: queryKeys.finance.receipt(receiptId), queryFn: ({ signal }) => fetchReceipt(receiptId, signal) });
  if (query.isPending) return <Loading label={r.loading} variant="detail" />;
  if (query.isError) {
    const error = query.error;
    if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
    if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={m.doc.permissionArea} />;
    return <ErrorState error={error} what={r.loading} onRetry={() => void query.refetch()} />;
  }
  return <Workspace receipt={query.data} />;
}

function Workspace({ receipt }: { receipt: ReceiptDetail }) {
  const key = useMemo(() => queryKeys.finance.receipt(receipt.id), [receipt.id]);
  const { run, pending, offline } = useFinanceCommand<ReceiptDetail>(key);
  const [invoiceId, setInvoiceId] = useState<string>(receipt.open_invoices[0]?.id ?? "");
  const [amount, setAmount] = useState<string | null>(null);
  const [voiding, setVoiding] = useState(false);
  const caps = receipt.capabilities;
  useScreenContribution({ focus: { type: "finance.receipt", id: receipt.id, version: receipt.version } });

  const facts: KeyValue[] = [
    { term: r.columns.amount, description: <Money value={receipt.amount} />, numeric: true },
    { term: r.columns.allocated, description: <Money value={receipt.allocated} />, numeric: true },
    { term: r.columns.unallocated, description: <Money value={receipt.unallocated} />, numeric: true },
    { term: r.method, description: r.methods[receipt.method] ?? receipt.method },
    { term: r.reference, description: receipt.reference ?? "—" },
    { term: r.bankAccount, description: receipt.bank_account_label ?? "—" },
  ];

  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/finance/receipts", label: r.back }}
        recordKey={receipt.receipt_number}
        title={receipt.party.display_name}
        status={<FinanceStatus status={receipt.status} />}
        meta={
          <>
            <LocalDate value={receipt.received_on} />
            {receipt.owner?.display_name ? (
              <>
                <MetaDot />
                <span>{receipt.owner.display_name}</span>
              </>
            ) : null}
          </>
        }
        actions={
          caps.reverse?.allowed ? (
            <Button variant="quiet" onPress={() => setVoiding(true)}>
              {r.reverse}
            </Button>
          ) : null
        }
      />
      <SectionCard title={m.doc.totals}>
        <KeyValueGrid items={facts} columns={2} />
      </SectionCard>
      {caps.allocate?.allowed ? (
        <SectionCard title={r.allocateTitle} description={r.openInvoices}>
          {receipt.open_invoices.length === 0 ? (
            <p className="text-sm text-ink-muted">{r.openInvoicesEmpty}</p>
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-64">
                <Select
                  label={r.invoice}
                  options={receipt.open_invoices.map((i) => ({ id: i.id, label: `${i.document_number} · ${i.outstanding.amount} ${i.outstanding.currency}` }))}
                  value={invoiceId}
                  onChange={(v) => setInvoiceId(v ?? "")}
                />
              </div>
              <NumberField label={r.allocateAmount} value={amount} currency={receipt.amount.currency} onChange={setAmount} />
              <Button
                variant="primary"
                isPending={pending === "allocate"}
                {...unavailableWhen(offline ?? (!invoiceId || !amount ? r.allocateMissing : null))}
                onPress={() =>
                  void run("allocate", (k) => allocateReceipt(receipt.id, invoiceId, amount ?? "0", k), { done: r.allocated, failed: m.hub.failed, write: (x) => x }).then((x) => {
                    if (x) setAmount(null);
                  })
                }
              >
                {r.allocate}
              </Button>
            </div>
          )}
        </SectionCard>
      ) : null}
      <SectionCard title={m.doc.allocations}>
        {receipt.allocations.length === 0 ? (
          <p className="text-sm text-ink-muted">{m.doc.allocationsEmpty}</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {receipt.allocations.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>
                  <Link href={`/finance/invoices/${a.invoice_id}`} className="font-mono">
                    {a.invoice_number}
                  </Link>{" "}
                  · <LocalDate value={a.allocated_on} />
                  {a.reverses_allocation_id ? ` · ${m.doc.reversal}` : a.reversed ? ` · ${m.doc.reversed}` : ""}
                </span>
                <span className="flex items-center gap-3">
                  <Money value={a.amount} />
                  {!a.reverses_allocation_id && !a.reversed && caps.allocate?.reason_code !== "permission_denied" && receipt.status === "recorded" ? (
                    <Button
                      size="sm"
                      variant="quiet"
                      isPending={pending === `rev:${a.id}`}
                      onPress={() => void run(`rev:${a.id}`, (k) => reverseAllocation(a.id, "wrong_invoice", k), { done: r.allocationReversed, failed: m.hub.failed })}
                    >
                      {r.reverseAllocation}
                    </Button>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
      <ReasonDialog
        title={r.reverseTitle}
        reasons={VOID_REASONS}
        noteLabel={m.doc.reasonNote}
        confirmLabel={r.reverse}
        isOpen={voiding}
        disabledReason={offline}
        onOpenChange={setVoiding}
        onConfirm={(code, note) => {
          setVoiding(false);
          if (code) void run("void", (k) => reverseReceipt(receipt, code, note, k), { done: r.reversedDone, failed: m.hub.failed, write: (x) => x });
        }}
      />
    </div>
  );
}
