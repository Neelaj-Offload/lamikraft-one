"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate, LocalDateTime, Money, Quantity } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { financeMessages as m } from "@/messages/finance";
import {
  createCreditNote,
  fetchDocument,
  fetchTaxProfiles,
  pdfHref,
  transitionDocument,
  updateTaxProfile,
  type InvoiceAction,
  type InvoiceDetail,
  type InvoiceLine,
  type TransitionResult,
} from "./api";
import { FinanceStatus } from "./finance-screens";
import { docBase, type DocKind } from "./list-state";
import { useFinanceCommand } from "./use-finance-command";

const d = m.doc;
type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];

const REJECT_REASONS = [
  { id: "needs_changes", label: "Needs changes" },
  { id: "change_tax", label: "Tax profile to change" },
  { id: "wrong_quantities", label: "Wrong quantities" },
] as const;
const CANCEL_REASONS = [
  { id: "duplicate", label: "Duplicate draft" },
  { id: "not_billable", label: "Not billable" },
  { id: "entered_in_error", label: "Entered in error" },
] as const;
const CREDIT_REASONS = [
  { id: "returned_goods", label: "Goods returned" },
  { id: "damaged", label: "Damaged in transit" },
  { id: "price_correction", label: "Price correction" },
] as const;

/** An invoice or credit note. 404 and out-of-scope documents are the same "not available" state on purpose. */
export function DocWorkspace({ kind, id }: { kind: DocKind; id: string }) {
  const query = useQuery({ queryKey: queryKeys.finance.document(kind, id), queryFn: ({ signal }) => fetchDocument(kind, id, signal) });
  if (query.isPending) return <Loading label={d.loading} variant="detail" />;
  if (query.isError) {
    const error = query.error;
    if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
    if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={d.permissionArea} />;
    return <ErrorState error={error} what={d.loading} onRetry={() => void query.refetch()} />;
  }
  return <Workspace kind={kind} doc={query.data} />;
}

function Workspace({ kind, doc }: { kind: DocKind; doc: InvoiceDetail }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.finance.document(kind, doc.id), [kind, doc.id]);
  const { run, pending, offline } = useFinanceCommand<InvoiceDetail>(key);
  const [dialog, setDialog] = useState<null | "reject" | "cancel" | "credit">(null);
  const allowed = new Set(doc.allowed_transitions.map((t) => t.action));
  const caps = doc.capabilities;
  const credit = kind === "credit_note";
  const number = doc.document_number ?? d.draftRef(doc.draft_ref);

  useScreenContribution({ focus: { type: "finance.invoice", id: doc.id, version: doc.version } });

  const act = (action: InvoiceAction, done: string, reason?: { code: string | null; note: string }) =>
    void run(action, (k) => transitionDocument(doc, action, k, reason ? { code: reason.code, note: reason.note } : {}), {
      failed: m.hub.failed,
      write: (r: TransitionResult) => {
        if (r.issued === false) toast.error(d.issueBlocked);
        else if (r.issued) toast.success(d.issued(r.detail.document_number ?? ""));
        else toast.success(done);
        return r.detail;
      },
    });

  const actions = (
    <>
      <Link href={pdfHref(doc)} target="_blank" rel="noopener">
        {d.pdf}
      </Link>
      {allowed.has("submit") ? (
        <Button variant="primary" isPending={pending === "submit"} {...unavailableWhen(offline)} onPress={() => act("submit", d.submitted)}>
          {d.submit}
        </Button>
      ) : null}
      {allowed.has("approve") ? (
        <Button variant="primary" isPending={pending === "approve"} {...unavailableWhen(offline)} onPress={() => act("approve", d.approved)}>
          {d.approve}
        </Button>
      ) : null}
      {allowed.has("issue") ? (
        <Button variant="primary" isPending={pending === "issue"} {...unavailableWhen(offline)} onPress={() => act("issue", d.approved)}>
          {d.issue}
        </Button>
      ) : null}
      {allowed.has("reject") ? <Button onPress={() => setDialog("reject")}>{d.reject}</Button> : null}
      {caps.create_credit_note?.allowed ? <Button onPress={() => setDialog("credit")}>{d.createCreditNote}</Button> : null}
      {allowed.has("cancel") ? (
        <Button variant="quiet" onPress={() => setDialog("cancel")}>
          {d.cancel}
        </Button>
      ) : null}
    </>
  );

  const facts: KeyValue[] = [
    { term: d.subtotal, description: <Money value={doc.subtotal} />, numeric: true },
    { term: d.tax, description: doc.tax ? <Money value={doc.tax} /> : m.taxStatus.not_configured, numeric: true },
    { term: d.total, description: <Money value={doc.total} />, numeric: true },
    { term: d.allocated, description: <Money value={doc.allocated} />, numeric: true },
  ];
  if (!credit) {
    facts.push({ term: d.credited, description: <Money value={doc.credited} />, numeric: true });
    facts.push({ term: d.outstanding, description: doc.outstanding ? <Money value={doc.outstanding} /> : "—", numeric: true });
    facts.push({ term: d.due, description: doc.due_date ? <LocalDate value={doc.due_date} /> : doc.payment_due_days != null ? d.dueAfter(doc.payment_due_days) : "—" });
  }
  facts.push({ term: d.taxProfile, description: doc.tax_profile ? `${doc.tax_profile.code} · ${m.taxStatus[doc.tax_status] ?? doc.tax_status}` : d.noTaxProfile });

  const lineColumns: DataTableColumn<InvoiceLine>[] = [
    { id: "no", header: d.columns.no, numeric: true, cell: (l) => l.line_no },
    {
      id: "item",
      header: d.columns.item,
      isRowHeader: true,
      mobile: "title",
      cell: (l) => (
        <span className="flex flex-col">
          <span>{l.description}</span>
          {l.item_code ? <span className="font-mono text-xs text-ink-muted">{l.item_code}</span> : null}
        </span>
      ),
    },
    { id: "hsn", header: d.columns.hsn, cell: (l) => l.hsn_sac ?? "—" },
    { id: "qty", header: d.columns.quantity, numeric: true, cell: (l) => <Quantity value={{ value: l.quantity, uom: l.uom_code }} /> },
    { id: "price", header: d.columns.price, numeric: true, cell: (l) => <Money value={l.unit_price} maxFractionDigits={4} /> },
    { id: "amount", header: d.columns.amount, numeric: true, mobile: "amount", cell: (l) => <Money value={l.amount} /> },
  ];
  if (doc.lines.some((l) => l.creditable_quantity != null)) {
    lineColumns.push({ id: "creditable", header: d.columns.creditable, numeric: true, cell: (l) => (l.creditable_quantity != null ? <Quantity value={{ value: l.creditable_quantity, uom: l.uom_code }} /> : "—") });
  }

  const billing = doc.billing as { legal_name?: string; address_lines?: string[] };
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: docBase(kind), label: credit ? d.backCreditNotes : d.backInvoices }}
        recordKey={number}
        title={doc.party.display_name}
        status={<FinanceStatus status={doc.status} />}
        meta={
          <>
            <span>{credit ? d.creditNote : d.invoice}</span>
            {doc.document_date ? (
              <>
                <MetaDot />
                <LocalDate value={doc.document_date} />
              </>
            ) : null}
            {doc.owner?.display_name ? (
              <>
                <MetaDot />
                <span>{doc.owner.display_name}</span>
              </>
            ) : null}
          </>
        }
        actions={actions}
      />
      {doc.label ? <p className="rounded-md border border-warning-text/40 bg-warning-bg p-3 text-sm font-semibold text-warning-text">{doc.label}</p> : null}
      {doc.status !== "issued" && doc.status !== "cancelled" ? <GateCard doc={doc} /> : null}
      {caps.update?.allowed ? <TaxProfilePicker doc={doc} run={run} pending={pending} offline={offline} /> : null}
      <SectionCard title={d.totals}>
        <KeyValueGrid items={facts} columns={2} />
      </SectionCard>
      <SectionCard title={d.billing}>
        <p className="text-sm">{billing.legal_name ?? doc.party.display_name}</p>
        <p className="text-sm text-ink-muted">{billing.address_lines?.length ? billing.address_lines.join(", ") : d.billingMissing}</p>
      </SectionCard>
      <SectionCard title={d.lines}>
        <DataTable caption={d.linesCaption} hideCaption columns={lineColumns} rows={doc.lines} rowId={(l) => l.id} />
      </SectionCard>
      <SectionCard title={d.allocations}>
        {doc.allocations.length === 0 ? (
          <p className="text-sm text-ink-muted">{d.allocationsEmpty}</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {doc.allocations.map((a) => (
              <li key={a.id} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
                <span>
                  {a.receipt_id ? (
                    <Link href={`/finance/receipts/${a.receipt_id}`} className="font-mono">
                      {a.receipt_number}
                    </Link>
                  ) : (
                    <span className="font-mono">{a.credit_note_number}</span>
                  )}{" "}
                  · <LocalDate value={a.allocated_on} />
                  {a.reverses_allocation_id ? ` · ${d.reversal}` : a.reversed ? ` · ${d.reversed}` : ""}
                </span>
                <Money value={a.amount} />
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
      {doc.related.length ? (
        <SectionCard title={d.related}>
          <ul className="flex flex-wrap gap-4 text-sm">
            {doc.related.map((r) => (
              <li key={`${r.kind}:${r.id}`}>
                <Link href={r.path} className="font-mono">
                  {r.number}
                </Link>
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
      <SectionCard title={d.history}>
        <ol className="flex flex-col gap-2 text-sm">
          {doc.history.map((h, i) => (
            <li key={`${h.occurred_at}-${i}`} className="flex flex-wrap gap-x-2">
              <LocalDateTime value={h.occurred_at} />
              <span>{d.actions[h.action] ?? h.action}</span>
              {h.actor?.display_name ? <span className="text-ink-muted">· {h.actor.display_name}</span> : null}
              {h.reason_code ? <span className="text-ink-muted">· {h.reason_code}</span> : null}
              {h.blocker_codes.length ? <span className="text-ink-muted">· {h.blocker_codes.length} blocker(s)</span> : null}
            </li>
          ))}
        </ol>
      </SectionCard>
      <ReasonDialog
        title={d.rejectTitle}
        reasons={REJECT_REASONS}
        noteLabel={d.reasonNote}
        confirmLabel={d.reject}
        isOpen={dialog === "reject"}
        disabledReason={offline}
        onOpenChange={(open) => (open ? null : setDialog(null))}
        onConfirm={(code, note) => {
          setDialog(null);
          act("reject", d.rejected, { code, note });
        }}
      />
      <ReasonDialog
        title={d.cancelTitle}
        reasons={CANCEL_REASONS}
        noteLabel={d.reasonNote}
        confirmLabel={d.cancel}
        isOpen={dialog === "cancel"}
        disabledReason={offline}
        onOpenChange={(open) => (open ? null : setDialog(null))}
        onConfirm={(code, note) => {
          setDialog(null);
          act("cancel", d.cancelled, { code, note });
        }}
      />
      <CreditDialog
        doc={doc}
        isOpen={dialog === "credit"}
        onOpenChange={(open) => setDialog(open ? "credit" : null)}
        onCreate={(lines, reason) =>
          void run("credit", (k) => createCreditNote(doc.id, lines, reason, k), { done: d.creditCreated, failed: m.hub.failed }).then((cn) => {
            if (cn) router.push(`/finance/credit-notes/${cn.id}` as Push);
          })
        }
        pending={pending === "credit"}
      />
    </div>
  );
}

/** The issue gate in plain words: every blocker with its fix, or "ready". */
function GateCard({ doc }: { doc: InvoiceDetail }) {
  const blockers = doc.gate.blockers;
  return (
    <SectionCard title={d.gateTitle} description={m.hub.gateBody}>
      {blockers.length === 0 ? (
        <p className="text-sm">{d.gateReady}</p>
      ) : (
        <ul className="flex list-disc flex-col gap-1 ps-5 text-sm">
          {blockers.map((b) => (
            <li key={b.code}>
              {m.blockers[b.code] ?? b.code}
              {b.code === "not_approved" && doc.capabilities.approve?.reason_code === "creator_cannot_approve" ? ` ${d.creatorCannotApprove}` : ""}
              {b.fix_path ? (
                <>
                  {" "}
                  <Link href={b.fix_path}>{m.blockerFix}</Link>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function TaxProfilePicker({
  doc,
  run,
  pending,
  offline,
}: {
  doc: InvoiceDetail;
  run: ReturnType<typeof useFinanceCommand<InvoiceDetail>>["run"];
  pending: string | null;
  offline: string | null;
}) {
  const profiles = useQuery({ queryKey: queryKeys.finance.taxProfiles(), queryFn: ({ signal }) => fetchTaxProfiles(signal) });
  const [choice, setChoice] = useState<string>(doc.tax_profile?.id ?? "");
  const options = [{ id: "", label: d.noProfile }, ...(profiles.data ?? []).map((p) => ({ id: p.id, label: `${p.code} · ${Number(p.rate_percent)} % · ${m.taxStatus[p.status] ?? p.status}` }))];
  return (
    <SectionCard title={d.chooseProfile}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64">
          <Select label={d.chooseProfile} options={options} value={choice} onChange={(v) => setChoice(v ?? "")} />
        </div>
        <Button
          isPending={pending === "profile"}
          {...unavailableWhen(offline ?? (choice === (doc.tax_profile?.id ?? "") ? d.profileUnchanged : null))}
          onPress={() => void run("profile", (k) => updateTaxProfile(doc, choice || null, k), { done: d.profileSaved, failed: m.hub.failed, write: (r) => r })}
        >
          {d.saveProfile}
        </Button>
      </div>
    </SectionCard>
  );
}

function CreditDialog({
  doc,
  isOpen,
  onOpenChange,
  onCreate,
  pending,
}: {
  doc: InvoiceDetail;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (lines: { invoice_line_id: string; quantity: string }[], reason: string) => void;
  pending: boolean;
}) {
  const [qty, setQty] = useState<Record<string, string | null>>({});
  const [reason, setReason] = useState<string>(CREDIT_REASONS[0].id);
  const lines = Object.entries(qty)
    .filter(([, v]) => v && Number(v) > 0)
    .map(([invoice_line_id, quantity]) => ({ invoice_line_id, quantity: quantity as string }));
  return (
    <Dialog
      title={d.creditTitle}
      description={doc.document_number ?? undefined}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending}
            {...unavailableWhen(lines.length === 0 ? d.creditNothing : null)}
            onPress={() => {
              close();
              onCreate(lines, reason);
            }}
          >
            {d.creditCreate}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <Select label={d.creditReason} options={CREDIT_REASONS.map((r) => ({ id: r.id, label: r.label }))} value={reason} onChange={(v) => setReason(v ?? CREDIT_REASONS[0].id)} />
        {doc.lines
          .filter((l) => l.creditable_quantity != null && Number(l.creditable_quantity) > 0)
          .map((l) => (
            <NumberField
              key={l.id}
              label={d.creditQuantity(l.line_no)}
              description={`${l.description} · ${d.columns.creditable}: ${l.creditable_quantity}`}
              value={qty[l.id] ?? null}
              uom={l.uom_code}
              onChange={(v) => setQty({ ...qty, [l.id]: v })}
            />
          ))}
      </div>
    </Dialog>
  );
}
