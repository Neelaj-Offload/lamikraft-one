"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { Badge, StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { Dialog } from "@/components/ui/dialog";
import { FactStrip } from "@/components/ui/fact-strip";
import { LocalDate, LocalDateTime, Money } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { SearchField } from "@/components/ui/search-field";
import { SectionCard } from "@/components/ui/section-card";
import { ComboBox, Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { useRolePartySearch } from "@/features/challans/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { financeMessages as m } from "@/messages/finance";
import {
  dismissSuggestion,
  documentsCsvHref,
  draftFromSuggestion,
  fetchAccountingStatus,
  fetchAgeing,
  fetchDocuments,
  fetchExceptions,
  fetchExports,
  fetchReceipts,
  fetchSuggestions,
  fetchSummary,
  fetchTaxProfiles,
  journalHref,
  PAGE_SIZE,
  reconcileExport,
  recordReceipt,
  runExport,
  verifyTaxProfile,
  type ExportRead,
  type InvoiceSummary,
  type ReceiptInput,
  type ReceiptSummary,
  type Suggestion,
  type TaxProfile,
} from "./api";
import { docBase, docHref, DOC_STATUSES, receiptHref, type DocKind, type DocListState, type ReceiptListState } from "./list-state";
import { useFinanceCommand } from "./use-finance-command";

export const FINANCE_LEADING = [{ id: "finance", label: m.nav.overview, href: "/finance" }] as const;
const dash = <span className="text-ink-muted">—</span>;
type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];

const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  pending_approval: "info",
  approved: "forest",
  issued: "success",
  cancelled: "neutral",
  recorded: "success",
  reversed: "neutral",
};

export function FinanceStatus({ status }: { status: string }) {
  return <StatusPill tone={STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

function FinanceNav() {
  return <AreaNav area="finance" label={m.area} leading={FINANCE_LEADING} />;
}

function Load<T>({ query, what, children }: { query: { isPending: boolean; isError: boolean; error: unknown; data?: T; refetch: () => unknown }; what: string; children: (data: T) => React.ReactNode }) {
  if (query.isPending) return <Loading label={what} />;
  if (query.isError || query.data === undefined) return <ErrorState error={query.error} what={what} onRetry={() => void query.refetch()} />;
  return <>{children(query.data)}</>;
}

// =====================================================================================================
// /finance
// =====================================================================================================
export function FinanceHub() {
  const { locale } = useZone();
  const summary = useQuery({ queryKey: queryKeys.finance.summary(), queryFn: ({ signal }) => fetchSummary(signal) });
  const h = m.hub;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={h.title} intro={h.intro} nav={<FinanceNav />} />
      <Load query={summary} what={h.title}>
        {(s) => (
          <>
            <FactStrip
              label={h.factsLabel}
              facts={[
                { label: h.drafts, value: formatCount(s.drafts, locale), href: "/finance/invoices?status=draft" },
                { label: h.pending, value: formatCount(s.pending_approval, locale), href: "/finance/invoices?status=pending_approval" },
                { label: h.blocked, value: formatCount(s.issue_blocked, locale), href: "/finance/exceptions" },
                { label: h.open, value: formatCount(s.issued_open, locale), href: "/finance/invoices?open=1" },
                { label: h.overdue, value: formatCount(s.overdue, locale), href: "/finance/invoices?overdue=1" },
                { label: h.suggestions, value: formatCount(s.open_suggestions, locale) },
                { label: h.unallocated, value: formatCount(s.unallocated_receipts, locale), href: "/finance/receipts?unallocated=1" },
                { label: h.margin, value: formatCount(s.margin_exceptions, locale), href: "/finance/exceptions" },
                { label: h.sync, value: formatCount(s.sync_attention, locale), href: "/finance/accounting-sync" },
              ]}
            />
            <SectionCard title={h.gateTitle}>
              <p className="max-w-prose text-sm">{h.gateBody}</p>
            </SectionCard>
            <SectionCard title={h.byCurrency}>
              {s.by_currency.length === 0 ? (
                <p className="text-sm text-ink-muted">{h.byCurrencyEmpty}</p>
              ) : (
                <ul className="flex flex-col divide-y">
                  {s.by_currency.map((c) => (
                    <li key={c.currency} className="grid grid-cols-2 gap-2 py-2 text-sm sm:grid-cols-4">
                      <span className="font-semibold">{c.currency}</span>
                      <span>
                        {h.receivable} <Money value={c.receivable} />
                      </span>
                      <span>
                        {h.overdueAmount} <Money value={c.overdue} />
                      </span>
                      <span>
                        {h.unallocatedAmount} <Money value={c.unallocated} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
            <SectionCard title={h.integrations}>
              <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-ink-muted">{h.accounting}</dt>
                  <dd>{s.accounting_state === "connected" ? h.connected : h.notConnected}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">{h.eInvoice}</dt>
                  <dd>{s.e_invoice_state === "connected" ? h.connected : h.notConnected}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">{m.accounting.taxProfilesTitle}</dt>
                  <dd>
                    <Link href="/finance/accounting-sync#tax-profiles">{h.taxProfiles(s.tax_profiles_verified)}</Link>
                  </dd>
                </div>
              </dl>
            </SectionCard>
            <Suggestions canCreate={Boolean(s.capabilities?.create_invoice?.allowed)} />
          </>
        )}
      </Load>
    </div>
  );
}

const DISMISS_REASONS = [
  { id: "invoiced_elsewhere", label: "Invoiced outside Lamikraft One" },
  { id: "no_charge", label: "No charge for this delivery" },
  { id: "duplicate", label: "Duplicate" },
] as const;

function Suggestions({ canCreate }: { canCreate: boolean }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.finance.suggestions(), []);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchSuggestions(signal) });
  const { run, pending, offline } = useFinanceCommand<Suggestion[]>(key);
  const [dismissing, setDismissing] = useState<Suggestion | null>(null);
  const h = m.hub;
  return (
    <SectionCard title={h.suggestionsTitle}>
      <Load query={query} what={h.suggestionsTitle}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="text-sm text-ink-muted">{h.suggestionsEmpty}</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {rows.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    <Link href={`/operations/challans/${s.challan_id}`} className="font-mono">
                      {s.challan_number}
                    </Link>{" "}
                    · {s.party.display_name} · <LocalDateTime value={s.created_at} />
                  </span>
                  {canCreate ? (
                    <span className="flex gap-2">
                      <Button
                        size="sm"
                        variant="primary"
                        isPending={pending === `draft:${s.id}`}
                        {...unavailableWhen(offline)}
                        onPress={() =>
                          void run(`draft:${s.id}`, (k) => draftFromSuggestion(s.id, k), { done: h.drafted, failed: h.failed }).then((d) => {
                            if (d) router.push(`/finance/invoices/${d.id}` as Push);
                          })
                        }
                      >
                        {h.draftFromSuggestion}
                      </Button>
                      <Button size="sm" variant="quiet" onPress={() => setDismissing(s)}>
                        {h.dismiss}
                      </Button>
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )
        }
      </Load>
      <ReasonDialog
        title={h.dismissTitle}
        description={dismissing ? `${dismissing.challan_number} · ${dismissing.party.display_name}` : undefined}
        reasons={DISMISS_REASONS}
        confirmLabel={h.dismiss}
        isOpen={dismissing !== null}
        disabledReason={offline}
        onOpenChange={(open) => (open ? null : setDismissing(null))}
        onConfirm={(code) => {
          const s = dismissing;
          setDismissing(null);
          if (s && code) void run(`dismiss:${s.id}`, (k) => dismissSuggestion(s, code, k), { done: h.dismissed, failed: h.failed });
        }}
      />
    </SectionCard>
  );
}

// =====================================================================================================
// /finance/invoices, /finance/credit-notes
// =====================================================================================================
function docColumns(kind: DocKind): DataTableColumn<InvoiceSummary>[] {
  const c = m.list.columns;
  return [
    {
      id: "number",
      header: c.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (r) => `${r.document_number ?? r.draft_ref} · ${r.party.display_name}`,
      cell: (r) => (
        <span className="flex flex-col">
          <Link href={`${docBase(kind)}/${r.id}`} className="font-mono">
            {r.document_number ?? r.draft_ref}
          </Link>
          {r.label ? <span className="text-xs text-ink-muted">{r.label}</span> : null}
        </span>
      ),
    },
    { id: "party", header: c.party, cell: (r) => r.party.display_name },
    { id: "status", header: c.status, mobile: "status", cell: (r) => (r.is_overdue ? <StatusPill tone="warning">{m.hub.overdue}</StatusPill> : <FinanceStatus status={r.status} />) },
    { id: "date", header: c.date, cell: (r) => (r.document_date ? <LocalDate value={r.document_date} /> : dash) },
    { id: "due", header: c.due, cell: (r) => (r.due_date ? <LocalDate value={r.due_date} /> : dash) },
    { id: "total", header: c.total, numeric: true, mobile: "amount", cell: (r) => <Money value={r.total} /> },
    { id: "outstanding", header: c.outstanding, numeric: true, cell: (r) => (r.outstanding ? <Money value={r.outstanding} /> : dash) },
  ];
}

export function DocumentList({ kind, state }: { kind: DocKind; state: DocListState }) {
  const router = useRouter();
  const query = useQuery({
    queryKey: queryKeys.finance.documents(kind, { ...state }),
    queryFn: ({ signal }) => fetchDocuments(kind, state, signal),
  });
  const go = (next: Partial<DocListState>) => router.push(docHref(kind, { ...state, offset: 0, ...next }) as Push);
  const filtered = Boolean(state.q || state.status || state.open || state.overdue);
  const credit = kind === "credit_note";
  const l = m.list;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={credit ? l.creditNotesTitle : l.invoicesTitle} intro={credit ? l.creditNotesIntro : l.invoicesIntro} nav={<FinanceNav />} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={l.search} placeholder={l.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={l.status}
          options={[{ id: "", label: l.anyStatus }, ...DOC_STATUSES.map((s) => ({ id: s, label: m.status[s] ?? s }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: value || null })}
        />
      </div>
      <div className="flex flex-wrap items-center gap-6">
        <Checkbox isSelected={state.open} onChange={(open) => go({ open })}>
          {l.openOnly}
        </Checkbox>
        {credit ? null : (
          <Checkbox isSelected={state.overdue} onChange={(overdue) => go({ overdue })}>
            {l.overdueOnly}
          </Checkbox>
        )}
        <Link href={documentsCsvHref(kind, state)} download>
          {l.exportCsv}
        </Link>
      </div>
      <Load query={query} what={credit ? l.creditNotesTitle : l.invoicesTitle}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState title={filtered ? l.empty : credit ? l.emptyCreditNotes : l.emptyAll} />
          ) : (
            <>
              <DataTable caption={l.caption} hideCaption columns={docColumns(kind)} rows={page.items} rowId={(r) => r.id} />
              <OffsetPagination total={page.total} limit={PAGE_SIZE} offset={state.offset} shown={page.items.length} control={(offset) => ({ href: docHref(kind, { ...state, offset }) })} />
            </>
          )
        }
      </Load>
    </div>
  );
}

// =====================================================================================================
// /finance/receipts
// =====================================================================================================
function receiptColumns(): DataTableColumn<ReceiptSummary>[] {
  const c = m.receipts.columns;
  return [
    {
      id: "number",
      header: c.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (r) => `${r.receipt_number} · ${r.party.display_name}`,
      cell: (r) => (
        <Link href={`/finance/receipts/${r.id}`} className="font-mono">
          {r.receipt_number}
        </Link>
      ),
    },
    { id: "party", header: c.party, cell: (r) => r.party.display_name },
    { id: "date", header: c.date, cell: (r) => <LocalDate value={r.received_on} /> },
    { id: "amount", header: c.amount, numeric: true, mobile: "amount", cell: (r) => <Money value={r.amount} /> },
    { id: "allocated", header: c.allocated, numeric: true, cell: (r) => <Money value={r.allocated} /> },
    { id: "unallocated", header: c.unallocated, numeric: true, cell: (r) => <Money value={r.unallocated} /> },
    { id: "status", header: c.status, mobile: "status", cell: (r) => <FinanceStatus status={r.status} /> },
  ];
}

export function ReceiptList({ state }: { state: ReceiptListState }) {
  const router = useRouter();
  const summary = useQuery({ queryKey: queryKeys.finance.summary(), queryFn: ({ signal }) => fetchSummary(signal) });
  const query = useQuery({ queryKey: queryKeys.finance.receipts({ ...state }), queryFn: ({ signal }) => fetchReceipts(state, signal) });
  const [open, setOpen] = useState(false);
  const go = (next: Partial<ReceiptListState>) => router.push(receiptHref({ ...state, offset: 0, ...next }) as Push);
  const r = m.receipts;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={r.title}
        intro={r.intro}
        nav={<FinanceNav />}
        actions={
          summary.data?.capabilities?.record_receipt?.allowed ? (
            <Button variant="primary" onPress={() => setOpen(true)}>
              {r.record}
            </Button>
          ) : null
        }
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={m.list.search} placeholder={m.list.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Checkbox isSelected={state.unallocated} onChange={(unallocated) => go({ unallocated })}>
          {r.unallocatedOnly}
        </Checkbox>
      </div>
      <Load query={query} what={r.title}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState title={state.q || state.unallocated ? r.empty : r.emptyAll} />
          ) : (
            <>
              <DataTable caption={r.caption} hideCaption columns={receiptColumns()} rows={page.items} rowId={(x) => x.id} />
              <OffsetPagination total={page.total} limit={PAGE_SIZE} offset={state.offset} shown={page.items.length} control={(offset) => ({ href: receiptHref({ ...state, offset }) })} />
            </>
          )
        }
      </Load>
      <RecordReceiptDialog isOpen={open} onOpenChange={setOpen} />
    </div>
  );
}

const CURRENCIES = ["EUR", "INR", "USD", "GBP"] as const;
const METHODS = ["bank_transfer", "cheque", "cash", "card", "other"] as const;

function RecordReceiptDialog({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const { run, pending, offline } = useFinanceCommand<null>(queryKeys.finance.receipts({}));
  const [partyText, setPartyText] = useState("");
  const [form, setForm] = useState<Partial<ReceiptInput>>({ currency: "EUR", method: "bank_transfer" });
  const parties = useRolePartySearch(partyText, "customer");
  const options = parties.data ?? [];
  const r = m.receipts;
  const ready = Boolean(form.party_id && form.amount && form.currency && form.received_on && form.method);
  return (
    <Dialog
      title={r.recordTitle}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {m.doc.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "record"}
            {...unavailableWhen(offline ?? (ready ? null : r.missingFields))}
            onPress={() =>
              void run("record", (k) => recordReceipt(form as ReceiptInput, k), { done: r.recorded, failed: m.hub.failed }).then((d) => {
                if (d) {
                  close();
                  router.push(`/finance/receipts/${d.id}` as Push);
                }
              })
            }
          >
            {r.record}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <ComboBox
          label={r.party}
          placeholder={r.partyPlaceholder}
          emptyText={r.partyPlaceholder}
          options={options.map((p) => ({ id: p.id, label: p.display_name, detail: p.party_number }))}
          value={form.party_id ?? null}
          inputValue={partyText}
          onInputChange={setPartyText}
          onChange={(id) => {
            const party = options.find((p) => p.id === id);
            setForm({ ...form, party_id: party?.id });
            if (party) setPartyText(party.display_name);
          }}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <NumberField label={r.amount} value={form.amount ?? null} currency={form.currency} onChange={(amount) => setForm({ ...form, amount: amount ?? undefined })} isRequired />
          <Select
            label={r.currency}
            options={CURRENCIES.map((c) => ({ id: c, label: c }))}
            value={form.currency ?? "EUR"}
            onChange={(value) => setForm({ ...form, currency: (CURRENCIES.find((c) => c === value) ?? "EUR") })}
          />
          <DatePicker label={r.receivedOn} value={form.received_on ?? null} onChange={(value) => setForm({ ...form, received_on: value ?? undefined })} isRequired />
          <Select
            label={r.method}
            options={METHODS.map((x) => ({ id: x, label: r.methods[x] ?? x }))}
            value={form.method ?? "bank_transfer"}
            onChange={(value) => setForm({ ...form, method: METHODS.find((x) => x === value) ?? "bank_transfer" })}
          />
          <TextField label={r.reference} value={form.reference ?? ""} onChange={(reference) => setForm({ ...form, reference })} maxLength={120} />
          <TextField label={r.bankAccount} value={form.bank_account_label ?? ""} onChange={(bank_account_label) => setForm({ ...form, bank_account_label })} maxLength={80} />
        </div>
      </div>
    </Dialog>
  );
}

// =====================================================================================================
// /finance/ageing
// =====================================================================================================
export function AgeingScreen({ asOf }: { asOf: string | null }) {
  const router = useRouter();
  const query = useQuery({ queryKey: queryKeys.finance.ageing(asOf), queryFn: ({ signal }) => fetchAgeing(asOf, signal) });
  const a = m.ageing;
  const c = a.columns;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={a.title} intro={a.intro} nav={<FinanceNav />} />
      <div className="max-w-xs">
        <DatePicker
          label={a.asOf}
          value={asOf ?? query.data?.as_of ?? null}
          onChange={(value) => router.push((value ? `/finance/ageing?as_of=${value}` : "/finance/ageing") as Push)}
        />
      </div>
      <Load query={query} what={a.title}>
        {(report) =>
          report.rows.length === 0 ? (
            <EmptyState title={a.empty} />
          ) : (
            <>
              <DataTable
                caption={a.caption}
                hideCaption
                rows={report.rows}
                rowId={(r) => `${r.party.id}:${r.currency}`}
                columns={[
                  { id: "party", header: c.party, isRowHeader: true, mobile: "title", cell: (r) => r.party.display_name },
                  { id: "currency", header: c.currency, cell: (r) => r.currency },
                  { id: "current", header: c.current, numeric: true, cell: (r) => <Money value={r.buckets.current} /> },
                  { id: "d30", header: c.d30, numeric: true, cell: (r) => <Money value={r.buckets.days_1_30} /> },
                  { id: "d60", header: c.d60, numeric: true, cell: (r) => <Money value={r.buckets.days_31_60} /> },
                  { id: "d90", header: c.d90, numeric: true, cell: (r) => <Money value={r.buckets.days_61_90} /> },
                  { id: "over90", header: c.over90, numeric: true, cell: (r) => <Money value={r.buckets.days_over_90} /> },
                  { id: "total", header: c.total, numeric: true, mobile: "amount", cell: (r) => <Money value={r.buckets.total} /> },
                  { id: "unallocated", header: c.unallocated, numeric: true, cell: (r) => <Money value={r.unallocated_receipts} /> },
                ]}
              />
              <SectionCard title={a.totals}>
                <ul className="flex flex-col gap-1 text-sm">
                  {report.totals.map((t) => (
                    <li key={t.total.currency} className="flex flex-wrap gap-3">
                      <span className="font-semibold">{t.total.currency}</span>
                      <span>
                        {c.current} <Money value={t.current} />
                      </span>
                      <span>
                        {c.d30} <Money value={t.days_1_30} />
                      </span>
                      <span>
                        {c.over90} <Money value={t.days_over_90} />
                      </span>
                      <span>
                        {c.total} <Money value={t.total} />
                      </span>
                    </li>
                  ))}
                </ul>
                {report.no_due_date_invoices.length ? <p className="mt-2 text-sm text-ink-muted">{a.noDueDate(report.no_due_date_invoices.length)}</p> : null}
              </SectionCard>
            </>
          )
        }
      </Load>
    </div>
  );
}

// =====================================================================================================
// /finance/exceptions
// =====================================================================================================
export function ExceptionsScreen() {
  const query = useQuery({ queryKey: queryKeys.finance.exceptions(), queryFn: ({ signal }) => fetchExceptions(signal) });
  const e = m.exceptions;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={e.title} intro={e.intro} nav={<FinanceNav />} />
      <Load query={query} what={e.title}>
        {(data) => (
          <>
            {data.items.length === 0 ? (
              <EmptyState title={e.empty} />
            ) : (
              <ul className="flex flex-col divide-y rounded-md border">
                {data.items.map((x) => (
                  <li key={`${x.kind}:${x.ref.id}`} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3 text-sm">
                    <span className="flex flex-wrap items-baseline gap-2">
                      <Badge tone={x.kind === "overdue" || x.kind === "sync_mismatch" ? "warning" : "neutral"}>{e.kinds[x.kind] ?? x.kind}</Badge>
                      <Link href={x.ref.path} className="font-mono">
                        {x.ref.number}
                      </Link>
                      {x.party_name ? <span>{x.party_name}</span> : null}
                    </span>
                    <span className="text-ink-muted">{x.codes.map((code) => m.blockers[code] ?? e.codes[code] ?? code).join(" ")}</span>
                  </li>
                ))}
              </ul>
            )}
            <SectionCard title={e.marginTitle}>
              {data.margin.length === 0 ? (
                <p className="text-sm text-ink-muted">{e.marginEmpty}</p>
              ) : (
                <DataTable
                  caption={e.marginTitle}
                  hideCaption
                  rows={data.margin}
                  rowId={(x) => x.id}
                  columns={[
                    {
                      id: "quote",
                      header: e.marginColumns.quote,
                      isRowHeader: true,
                      mobile: "title",
                      cell: (x) => (
                        <Link href={`/sales/quotes/${x.quote_id}`} className="font-mono">
                          {x.quote_number}
                        </Link>
                      ),
                    },
                    { id: "party", header: e.marginColumns.party, cell: (x) => x.party_name },
                    { id: "owner", header: e.marginColumns.owner, cell: (x) => x.owner?.display_name ?? dash },
                    {
                      id: "margin",
                      header: e.marginColumns.margin,
                      numeric: true,
                      mobile: "amount",
                      cell: (x) => (x.margin_percent != null ? `${Number(x.margin_percent).toFixed(1)} %` : <span className="text-ink-muted">{e.marginRedacted}</span>),
                    },
                    { id: "threshold", header: e.marginColumns.threshold, numeric: true, cell: (x) => `${Number(x.threshold_percent).toFixed(1)} %` },
                    { id: "missing", header: e.marginColumns.missing, numeric: true, cell: (x) => x.lines_without_cost },
                  ]}
                />
              )}
            </SectionCard>
          </>
        )}
      </Load>
    </div>
  );
}

// =====================================================================================================
// /finance/accounting-sync
// =====================================================================================================
export function AccountingSyncScreen() {
  const status = useQuery({ queryKey: queryKeys.finance.accounting(), queryFn: ({ signal }) => fetchAccountingStatus(signal) });
  const exports = useQuery({ queryKey: queryKeys.finance.exports(), queryFn: ({ signal }) => fetchExports(signal) });
  const summary = useQuery({ queryKey: queryKeys.finance.summary(), queryFn: ({ signal }) => fetchSummary(signal) });
  const { run, pending, offline } = useFinanceCommand<null>(queryKeys.finance.exports());
  const canRun = Boolean(summary.data?.capabilities?.run_export?.allowed);
  const a = m.accounting;
  const exportDone = (x: ExportRead) => (x.status === "completed" ? a.exported(x.export_number) : a.exportFailed(m.exceptions.codes[x.error_code ?? ""] ?? x.error_code ?? ""));
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={a.title}
        intro={a.intro}
        nav={<FinanceNav />}
        actions={
          canRun ? (
            <>
              <Button
                variant="primary"
                isPending={pending === "csv"}
                {...unavailableWhen(offline)}
                onPress={() => void run("csv", (k) => runExport("csv", k), { failed: m.hub.failed, write: (x) => (x ? (notify(exportDone(x)), null) : null) })}
              >
                {a.runCsv}
              </Button>
              <Button
                isPending={pending === "demo"}
                {...unavailableWhen(offline)}
                onPress={() => void run("demo", (k) => runExport("demo", k), { failed: m.hub.failed, write: (x) => (x ? (notify(exportDone(x)), null) : null) })}
              >
                {a.runDemo}
              </Button>
            </>
          ) : null
        }
      />
      <p className="max-w-prose rounded-md border border-info-text/30 bg-info-bg p-3 text-sm text-info-text">{a.demoNotice}</p>
      <Load query={status} what={a.title}>
        {(st) => (
          <SectionCard title={a.status} description={st.label}>
            <p className="text-sm">{a.pending(st.pending_documents)}</p>
            <p className="text-sm">{st.mapping_complete ? a.mappingOk : `${a.mappingMissing} ${st.missing_mapping.join(", ")}`}</p>
          </SectionCard>
        )}
      </Load>
      <SectionCard title={a.exportsTitle}>
        <Load query={exports} what={a.exportsTitle}>
          {(page) =>
            page.items.length === 0 ? (
              <p className="text-sm text-ink-muted">{a.exportsEmpty}</p>
            ) : (
              <DataTable
                caption={a.caption}
                hideCaption
                rows={page.items}
                rowId={(x) => x.id}
                columns={[
                  { id: "number", header: a.columns.number, isRowHeader: true, mobile: "title", cell: (x) => <span className="font-mono">{x.export_number}</span> },
                  { id: "adapter", header: a.columns.adapter, cell: (x) => a.adapters[x.adapter] ?? x.adapter },
                  { id: "status", header: a.columns.status, mobile: "status", cell: (x) => (x.status === "completed" ? <StatusPill tone="success">{x.status}</StatusPill> : <StatusPill tone="danger">{m.exceptions.codes[x.error_code ?? ""] ?? x.error_code}</StatusPill>) },
                  { id: "documents", header: a.columns.documents, numeric: true, cell: (x) => x.document_count },
                  { id: "blocked", header: a.columns.blocked, numeric: true, cell: (x) => x.blocked_count },
                  { id: "reconciliation", header: a.columns.reconciliation, cell: (x) => a.reconciliation[x.reconciliation_status] ?? x.reconciliation_status },
                  { id: "when", header: a.columns.when, cell: (x) => <LocalDateTime value={x.created_at} /> },
                  {
                    id: "actions",
                    header: "",
                    cell: (x) =>
                      x.status === "completed" && canRun ? (
                        <span className="flex flex-wrap gap-2">
                          <Link href={journalHref(x.id)} download>
                            {a.download}
                          </Link>
                          {x.simulated ? (
                            <Button size="sm" isPending={pending === `rec:${x.id}`} onPress={() => void run(`rec:${x.id}`, (k) => reconcileExport(x.id, k), { done: a.reconciled, failed: m.hub.failed })}>
                              {a.reconcile}
                            </Button>
                          ) : (
                            <span className="text-xs text-ink-muted">{a.reconcileCsvHint}</span>
                          )}
                        </span>
                      ) : null,
                  },
                ]}
              />
            )
          }
        </Load>
      </SectionCard>
      <TaxProfiles canVerify={Boolean(summary.data?.capabilities?.verify_tax_profile?.allowed)} />
    </div>
  );
}

function notify(text: string) {
  toast.success(text);
}

function TaxProfiles({ canVerify }: { canVerify: boolean }) {
  const key = useMemo(() => queryKeys.finance.taxProfiles(), []);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchTaxProfiles(signal) });
  const { run, pending, offline } = useFinanceCommand<TaxProfile[]>(key);
  const a = m.accounting;
  return (
    <section id="tax-profiles">
      <SectionCard title={a.taxProfilesTitle} description={a.taxProfilesIntro}>
        <Load query={query} what={a.taxProfilesTitle}>
          {(rows) =>
            rows.length === 0 ? (
              <p className="text-sm text-ink-muted">{a.taxProfilesEmpty}</p>
            ) : (
              <DataTable
                caption={a.taxProfilesTitle}
                hideCaption
                rows={rows}
                rowId={(p) => p.id}
                columns={[
                  { id: "code", header: a.profileColumns.code, isRowHeader: true, mobile: "title", cell: (p) => <span className="font-mono">{p.code}</span> },
                  { id: "name", header: a.profileColumns.name, cell: (p) => p.name },
                  { id: "rate", header: a.profileColumns.rate, numeric: true, cell: (p) => `${Number(p.rate_percent)} %` },
                  { id: "einv", header: a.profileColumns.eInvoice, cell: (p) => (p.requires_e_invoice ? a.yes : a.no) },
                  { id: "source", header: a.profileColumns.source, cell: (p) => p.source_reference },
                  {
                    id: "status",
                    header: a.profileColumns.status,
                    mobile: "status",
                    cell: (p) =>
                      p.status === "verified" ? (
                        <StatusPill tone="success">{m.taxStatus.verified}</StatusPill>
                      ) : canVerify && p.capabilities?.verify?.allowed ? (
                        <Button size="sm" isPending={pending === p.id} {...unavailableWhen(offline)} onPress={() => void run(p.id, (k) => verifyTaxProfile(p, k), { done: a.verified, failed: m.hub.failed })}>
                          {a.verify}
                        </Button>
                      ) : (
                        <StatusPill tone="warning">{m.taxStatus.unverified}</StatusPill>
                      ),
                  },
                ]}
              />
            )
          }
        </Load>
      </SectionCard>
    </section>
  );
}
