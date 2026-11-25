"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useId, useState, type FormEvent } from "react";
import { useResourceCommand } from "@/features/sales/resource-command";
import { fieldErrorsFrom } from "@/features/parties/form-model";
import { useZone } from "@/lib/session/context";
import {
  cancelProforma,
  issueProforma,
  PROFORMA_INVALIDATE,
  proformaDocumentHref,
  proformaKeys,
  updateProforma,
  useProforma,
  type ProformaDetail,
} from "~/data/proforma";
import { Page, PageHeader, RecordHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  DataTable,
  DatePicker,
  DateText,
  Drawer,
  FactStrip,
  GlassPanel,
  IconButton,
  KeyValue,
  Menu,
  Modal,
  Money,
  ReasonDialog,
  Select,
  Skeleton,
  SkeletonText,
  Textarea,
  TextField,
  toast,
  type Column,
  type MenuItem,
} from "~/ui";
import { isoToday } from "../leads/labels";
import { PROFORMA_STATUS_LABEL, PROFORMA_STATUS_TONE } from "./labels";

type Line = ProformaDetail["lines"][number] & {
  line_no?: number;
  product_key?: string | null;
  description?: string | null;
  decor_no?: string | null;
  decor_name?: string | null;
  size_text?: string | null;
  quantity?: string;
  unit_code?: string;
  unit_price?: string | null;
  line_total?: string | null;
};

const crumbs = [
  { label: "Sales", href: "/sales" as Route },
  { label: "Proforma invoices", href: "/sales/proforma-invoices" as Route },
];

export function ProformaRecord({ proformaId }: { proformaId: string }) {
  const query = useProforma(proformaId);
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the proforma invoice">
          <Skeleton width={90} height={10} />
          <Skeleton width="40%" height={28} />
          <SkeletonText lines={2} />
        </div>
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={crumbs} title="Proforma invoice" />
        <ErrorBlock error={query.error} what="This proforma invoice" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return <Loaded pi={query.data} />;
}

function Loaded({ pi }: { pi: ProformaDetail }) {
  const queryClient = useQueryClient();
  const commands = useResourceCommand(`proforma:${pi.id}`, PROFORMA_INVALIDATE);
  const [editing, setEditing] = useState({ open: false, round: 0 });
  const [issuing, setIssuing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const canUpdate = pi.capabilities.update?.allowed === true;
  const canIssue = pi.capabilities.issue?.allowed === true;
  const canCancel = pi.capabilities.cancel?.allowed === true;
  const number = pi.pi_number ?? pi.draft_ref;

  const cancel = async (reason: string) => {
    const result = await commands.run("cancel", [pi.version], (key) => cancelProforma(pi.id, { expected_version: pi.version, reason }, key), {
      failed: "The proforma invoice was not cancelled",
      conflictMessage: "This proforma invoice changed. The latest version is showing.",
    });
    if (result.ok) {
      queryClient.setQueryData(proformaKeys.detail(pi.id), result.value);
      toast.success(`${number} cancelled`);
      return;
    }
    throw result.error;
  };

  const menu: MenuItem[] = [
    ...(canUpdate ? [{ id: "edit", label: "Edit terms", icon: "edit" as const, onAction: () => setEditing((s) => ({ open: true, round: s.round + 1 })) }] : []),
    ...(canCancel ? [{ id: "cancel", label: "Cancel", icon: "xCircle" as const, tone: "danger" as const, onAction: () => setCancelling(true) }] : []),
  ];

  const lineColumns: Column<Line>[] = [
    { key: "no", header: "#", width: "48px", cell: (ln) => <span className="lk-tnum">{ln.line_no}</span> },
    {
      key: "item",
      header: "Item",
      primary: true,
      cell: (ln) => (
        <span className="flex min-w-0 flex-col">
          <span className="t-label text-ink">{ln.product_key || ln.description}</span>
          <span className="t-caption text-ink-3">{[ln.decor_no && `${ln.decor_no} ${ln.decor_name ?? ""}`.trim(), ln.size_text].filter(Boolean).join(" · ")}</span>
        </span>
      ),
    },
    { key: "qty", header: "Quantity", numeric: true, cell: (ln) => <span className="lk-tnum">{`${Number(ln.quantity ?? 0).toLocaleString()} ${ln.unit_code ?? ""}`}</span> },
    { key: "price", header: "Unit price", numeric: true, hideOnMobile: true, cell: (ln) => (ln.unit_price ? <Money value={{ amount: ln.unit_price, currency: pi.currency }} maxFractionDigits={4} /> : "—") },
    { key: "total", header: "Amount", numeric: true, cell: (ln) => (ln.line_total ? <Money value={{ amount: ln.line_total, currency: pi.currency }} /> : "—") },
  ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...crumbs, { label: number }]}
        code={number}
        title={pi.party.display_name}
        status={
          <>
            <Badge tone={PROFORMA_STATUS_TONE[pi.status]} dot>
              {PROFORMA_STATUS_LABEL[pi.status]}
            </Badge>
            {pi.backfilled ? <Badge outline>Entered from history</Badge> : null}
          </>
        }
        lead={`From quotation ${pi.quote_number}, revision ${pi.revision_no}`}
        facts={
          <FactStrip
            items={[
              { label: "Total", value: pi.grand_total ? <Money value={{ amount: pi.grand_total, currency: pi.currency }} /> : null, icon: "banknote" },
              { label: "Date", value: pi.pi_date ? <DateText value={pi.pi_date} /> : "Not issued", icon: "calendar" },
              { label: "Quotation", value: pi.quote_number, icon: "fileText" },
              { label: "Looked after by", value: pi.owner.display_name, icon: "user" },
            ]}
          />
        }
        actions={
          <>
            {canIssue ? (
              <Button iconLeft="send" onPress={() => setIssuing(true)}>
                Issue
              </Button>
            ) : null}
            <ButtonLink variant={canIssue ? "secondary" : "primary"} href={proformaDocumentHref(pi.id) as Route} iconLeft="download" target="_blank">
              {pi.status === "draft" ? "Preview PDF" : "Download PDF"}
            </ButtonLink>
            <ButtonLink variant="secondary" href={`/sales/quotes/${encodeURIComponent(pi.quote_id)}` as Route} iconLeft="fileText">
              Quotation
            </ButtonLink>
            {menu.length > 0 ? <Menu label="More actions" items={menu} placement="bottom end" trigger={<IconButton icon="more" label="More actions" />} /> : null}
          </>
        }
      />

      {pi.status === "cancelled" ? (
        <Banner tone="neutral" title="Cancelled">
          {pi.cancel_reason}
        </Banner>
      ) : null}

      <GlassPanel padding="none" className="rise">
        <DataTable label="Items" columns={lineColumns} rows={pi.lines as Line[]} rowKey={(ln) => String(ln.line_no)} />
      </GlassPanel>

      <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
        <GlassPanel padding="lg" className="rise flex flex-col gap-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="t-h4 text-ink">Terms</h2>
            {canUpdate ? (
              <Button variant="ghost" size="sm" iconLeft="edit" onPress={() => setEditing((s) => ({ open: true, round: s.round + 1 }))}>
                Edit terms
              </Button>
            ) : null}
          </div>
          <KeyValue
            items={[
              { label: "Delivery terms", value: pi.delivery_terms },
              { label: "Port of loading", value: pi.port_of_loading },
              { label: "Port of discharge", value: pi.port_of_discharge },
              { label: "Payment terms", value: pi.payment_terms },
              { label: "Bank account", value: pi.bank_account_label },
            ]}
          />
        </GlassPanel>
        <GlassPanel padding="lg" className="rise flex flex-col gap-4">
          <h2 className="t-h4 text-ink">Customer and notes</h2>
          <KeyValue
            items={[
              { label: "Customer", value: pi.party.display_name },
              { label: "Their reference", value: pi.customer_reference },
              { label: "Declaration", value: pi.declaration },
              { label: "Notes", value: pi.notes },
              { label: "Issued", value: pi.issued_at ? <DateText value={pi.issued_at} style="relative" /> : null },
            ]}
          />
        </GlassPanel>
      </div>

      {canUpdate ? <TermsDrawer key={`terms-${editing.round}-${pi.version}`} pi={pi} isOpen={editing.open} onOpenChange={(open) => setEditing((s) => ({ ...s, open }))} /> : null}
      {canIssue ? <IssueModal key={`issue-${pi.version}`} pi={pi} isOpen={issuing} onOpenChange={setIssuing} /> : null}
      <ReasonDialog
        isOpen={cancelling}
        onOpenChange={setCancelling}
        tone="danger"
        title={`Cancel ${number}`}
        description="It stays on record, marked cancelled, and can still be printed."
        reasonLabel="Why is it cancelled"
        confirmLabel="Cancel proforma invoice"
        loading={commands.pending === "cancel"}
        onConfirm={cancel}
      />
    </Page>
  );
}

function IssueModal({ pi, isOpen, onOpenChange }: { pi: ProformaDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const zone = useZone();
  const today = isoToday(zone.timeZone);
  const commands = useResourceCommand(`proforma-issue:${pi.id}`, PROFORMA_INVALIDATE);
  const [date, setDate] = useState<string | null>(today);
  const [error, setError] = useState<string | undefined>();

  const issue = async () => {
    const result = await commands.run("issue", [pi.version], (key) => issueProforma(pi.id, { expected_version: pi.version, pi_date: date }, key), {
      failed: "The proforma invoice was not issued",
      conflictMessage: "This proforma invoice changed. The latest version is showing.",
    });
    if (result.ok) {
      queryClient.setQueryData(proformaKeys.detail(pi.id), result.value);
      toast.success(`Issued as ${result.value.pi_number}`);
      onOpenChange(false);
    } else if (!result.conflict) {
      setError(fieldErrorsFrom(result.error).pi_date);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title="Issue this proforma invoice"
      description="It gets its number, and its items and terms are fixed. To change it later, cancel it and make a new one."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Not yet
          </Button>
          <Button loading={commands.pending === "issue"} isDisabled={Boolean(commands.offline)} onPress={() => void issue()}>
            Issue proforma invoice
          </Button>
        </>
      }
    >
      <DatePicker label="Date on the document" value={date} onChange={setDate} maxValue={today} error={error} />
    </Modal>
  );
}

function TermsDrawer({ pi, isOpen, onOpenChange }: { pi: ProformaDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const queryClient = useQueryClient();
  const commands = useResourceCommand(`proforma-terms:${pi.id}`, PROFORMA_INVALIDATE);
  const [form, setForm] = useState({
    delivery_terms: pi.delivery_terms ?? "",
    port_of_loading: pi.port_of_loading ?? "",
    port_of_discharge: pi.port_of_discharge ?? "",
    payment_terms: pi.payment_terms ?? "",
    bank_account_label: pi.bank_account_label ?? "",
    declaration: pi.declaration ?? "",
    notes: pi.notes ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
    const result = await commands.run("terms", [pi.version, JSON.stringify(body)], (key) => updateProforma(pi.id, { expected_version: pi.version, ...body }, key), {
      failed: "The terms were not saved",
      conflictMessage: "Someone else changed this proforma invoice. Close the form and open it again.",
    });
    if (result.ok) {
      queryClient.setQueryData(proformaKeys.detail(pi.id), result.value);
      toast.success("Terms saved");
      onOpenChange(false);
    } else if (!result.conflict) {
      setErrors(fieldErrorsFrom(result.error));
    }
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Terms"
      description={pi.draft_ref}
      footer={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "terms"}>
            Save terms
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-5">
        <TextField label="Delivery terms" optional value={form.delivery_terms} onChange={(v) => set("delivery_terms", v)} maxLength={200} placeholder="FOB Mundra" error={errors.delivery_terms} />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <TextField label="Port of loading" optional value={form.port_of_loading} onChange={(v) => set("port_of_loading", v)} maxLength={120} error={errors.port_of_loading} />
          <TextField label="Port of discharge" optional value={form.port_of_discharge} onChange={(v) => set("port_of_discharge", v)} maxLength={120} error={errors.port_of_discharge} />
        </div>
        <Textarea label="Payment terms" optional value={form.payment_terms} onChange={(v) => set("payment_terms", v)} maxLength={500} rows={2} error={errors.payment_terms} />
        <Select
          label="Bank account"
          optional
          options={[{ value: "", label: "Not shown" }, ...pi.bank_accounts.map((label) => ({ value: label, label }))]}
          value={form.bank_account_label}
          onChange={(v) => set("bank_account_label", v ?? "")}
          help={pi.bank_accounts.length === 0 ? "Add bank accounts in Settings, Company." : undefined}
          error={errors.bank_account_label}
        />
        <Textarea label="Declaration" optional value={form.declaration} onChange={(v) => set("declaration", v)} maxLength={2000} rows={3} error={errors.declaration} />
        <Textarea label="Notes" optional value={form.notes} onChange={(v) => set("notes", v)} maxLength={4000} rows={3} error={errors.notes} />
      </form>
    </Drawer>
  );
}
