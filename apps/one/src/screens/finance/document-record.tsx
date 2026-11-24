"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { createCreditNote, pdfHref, transitionDocument, type InvoiceAction, type InvoiceDetail, type TransitionResult } from "@/features/finance/api";
import { docBase, type DocKind } from "@/features/finance/list-state";
import { useFinanceCommand } from "@/features/finance/use-finance-command";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, CANCEL_REASONS, documentStatus, REJECT_REASONS, TAX_STATUS_LABEL, useFinanceDocument } from "~/data/finance";
import { Page, RecordHeader } from "~/shell/page";
import { Badge, Banner, Button, ButtonLink, DateText, FactStrip, Menu, Money, Tabs, toast, type IconName, type MenuAction } from "~/ui";
import { CreditNoteDialog } from "./credit-note-dialog";
import { ActivityView, LinesView, OverviewView, SettlementsView } from "./document-views";
import { CodeReasonDialog, RecordLoading, RecordProblem, StatusBadge } from "./parts";
import { viewHref, type DocumentView } from "./views";

const FAILED = "That did not go through";

/** An invoice or a credit note: where it stands, its lines, what settled it and its history. */
export function DocumentRecord({ kind, id, view }: { kind: DocKind; id: string; view: DocumentView }) {
  const query = useFinanceDocument(kind, id);
  const credit = kind === "credit_note";
  if (query.isPending) return <RecordLoading what={credit ? "the credit note" : "the invoice"} />;
  if (query.isError) {
    return (
      <RecordProblem
        error={query.error}
        what={credit ? "This credit note" : "This invoice"}
        onRetry={() => void query.refetch()}
        backHref={docBase(kind)}
        backLabel={credit ? "All credit notes" : "All invoices"}
      />
    );
  }
  return <Loaded kind={kind} doc={query.data} view={view} />;
}

type Step = { id: InvoiceAction; label: string; icon: IconName; run: () => void };

function Loaded({ kind, doc, view }: { kind: DocKind; doc: InvoiceDetail; view: DocumentView }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.finance.document(kind, doc.id), [kind, doc.id]);
  const { run, pending, offline } = useFinanceCommand<InvoiceDetail>(key);
  const [dialog, setDialog] = useState<null | "reject" | "cancel" | "credit">(null);
  const allowed = new Set(doc.allowed_transitions.map((transition) => transition.action));
  const caps = doc.capabilities;
  const credit = kind === "credit_note";
  const noun = credit ? "credit note" : "invoice";
  const number = doc.document_number ?? `Draft ${doc.draft_ref}`;
  const path = `${docBase(kind)}/${doc.id}`;

  useScreenContribution({ focus: { type: "finance.invoice", id: doc.id, version: doc.version } });

  // One transition at a time. A refused issue is an answer, not an error: the record comes back with its blockers.
  const act = (action: InvoiceAction, done: string, reason?: { code: string; note: string }) =>
    run(action, (k) => transitionDocument(doc, action, k, reason ?? {}), {
      failed: FAILED,
      write: (result: TransitionResult) => {
        if (result.issued === false) toast.error("Not issued", { description: "The issue check on the overview lists what is still missing." });
        else if (result.issued) toast.success(`Issued as ${result.detail.document_number ?? ""}`.trim());
        else toast.success(done);
        return result.detail;
      },
    });

  // The forward steps in the order they happen; the first one available leads.
  const steps: Step[] = [];
  if (allowed.has("submit")) steps.push({ id: "submit", label: "Submit for approval", icon: "send", run: () => void act("submit", "Submitted for approval") });
  if (allowed.has("approve")) steps.push({ id: "approve", label: `Approve ${noun}`, icon: "check", run: () => void act("approve", "Approved") });
  if (allowed.has("issue")) steps.push({ id: "issue", label: `Issue ${noun}`, icon: "badgeCheck", run: () => void act("issue", "Issued") });
  const [lead, second, ...others] = steps;

  const menu: MenuAction[] = others.map((step) => ({ id: step.id, label: step.label, icon: step.icon, isDisabled: Boolean(offline), onAction: step.run }));
  if (allowed.has("reject")) menu.push({ id: "reject", label: "Send back to draft", icon: "undo", isDisabled: Boolean(offline), onAction: () => setDialog("reject") });
  if (caps.create_credit_note?.allowed) menu.push({ id: "credit", label: "Create credit note", icon: "filePlus", isDisabled: Boolean(offline), onAction: () => setDialog("credit") });
  if (allowed.has("cancel")) menu.push({ id: "cancel", label: `Cancel ${noun}`, icon: "xCircle", tone: "danger", isDisabled: Boolean(offline), onAction: () => setDialog("cancel") });
  const only = menu.length === 1 ? menu[0] : null;

  const due = doc.due_date ? <DateText value={doc.due_date} style="business" /> : doc.payment_due_days != null ? `${doc.payment_due_days} days after issue` : null;
  const taxFact = doc.tax_profile ? `${doc.tax_profile.code} · ${TAX_STATUS_LABEL[doc.tax_status] ?? doc.tax_status}` : "None chosen";

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Finance", href: "/finance" }, { label: credit ? "Credit notes" : "Invoices", href: docBase(kind) }, { label: number }]}
        code={number}
        title={doc.party.display_name}
        status={
          <>
            <StatusBadge look={documentStatus(doc.status)} />
            {doc.is_overdue ? (
              <Badge tone="ember" icon="clock">
                Overdue
              </Badge>
            ) : null}
          </>
        }
        lead={
          <>
            {credit ? "Credit note" : "Invoice"}
            {doc.document_date ? (
              <>
                {" dated "}
                <DateText value={doc.document_date} style="business" />
              </>
            ) : (
              ", not yet dated"
            )}
            {doc.customer_reference ? ` · their ref. ${doc.customer_reference}` : ""}
          </>
        }
        facts={
          <FactStrip
            items={
              credit
                ? [
                    { label: "Total", icon: "banknote", value: <Money value={doc.total} className="t-stat-sm" /> },
                    { label: "Settled", icon: "checkCircle", value: <Money value={doc.allocated} /> },
                    { label: "Tax profile", icon: "percent", value: taxFact },
                    { label: "Owner", icon: "user", value: doc.owner?.display_name },
                  ]
                : [
                    { label: "Total", icon: "banknote", value: <Money value={doc.total} className="t-stat-sm" /> },
                    { label: "Outstanding", icon: "wallet", value: doc.outstanding ? <Money value={doc.outstanding} /> : null },
                    { label: "Due", icon: "calendar", value: due },
                    { label: "Tax profile", icon: "percent", value: taxFact },
                    { label: "Owner", icon: "user", value: doc.owner?.display_name },
                  ]
            }
          />
        }
        actions={
          <>
            {lead ? (
              <Button iconLeft={lead.icon} loading={pending === lead.id} isDisabled={Boolean(offline)} onPress={lead.run}>
                {lead.label}
              </Button>
            ) : null}
            {second ? (
              <Button variant="secondary" iconLeft={second.icon} loading={pending === second.id} isDisabled={Boolean(offline)} onPress={second.run}>
                {second.label}
              </Button>
            ) : null}
            <ButtonLink external href={pdfHref(doc)} target="_blank" type="application/pdf" variant="secondary" iconLeft="fileText">
              Open PDF
            </ButtonLink>
            {only ? (
              <Button variant={only.tone === "danger" ? "danger" : "secondary"} iconLeft={only.icon} isDisabled={only.isDisabled} onPress={only.onAction}>
                {only.label}
              </Button>
            ) : menu.length > 1 ? (
              <Menu
                label={`More ${noun} actions`}
                items={menu}
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
          label={`Views of this ${noun}`}
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Lines", count: doc.lines.length, href: asRoute(viewHref(path, "lines")) },
            { id: "settlements", label: "Settlements", count: doc.allocations.length || undefined, href: asRoute(viewHref(path, "settlements")) },
            { id: "activity", label: "Activity", href: asRoute(viewHref(path, "activity")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this {noun}. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {doc.label ? <Banner tone="amber" icon="flag" title={doc.label} /> : null}

      {view === "overview" ? <OverviewView doc={doc} credit={credit} run={run} pending={pending} offline={offline} /> : null}
      {view === "lines" ? <LinesView doc={doc} number={number} /> : null}
      {view === "settlements" ? <SettlementsView doc={doc} credit={credit} /> : null}
      {view === "activity" ? <ActivityView doc={doc} /> : null}

      <CodeReasonDialog
        isOpen={dialog === "reject"}
        onClose={() => setDialog(null)}
        title="Send back to draft"
        description={`The drafter can change the ${noun} and submit it again. Your reason is kept in its history.`}
        reasons={REJECT_REASONS}
        confirmLabel="Send back"
        onConfirm={async (code, note) => Boolean(await act("reject", "Sent back to draft", { code, note }))}
      />
      <CodeReasonDialog
        isOpen={dialog === "cancel"}
        onClose={() => setDialog(null)}
        tone="danger"
        title={`Cancel this ${noun}`}
        description="A cancelled document cannot be issued. It stays on record with your reason."
        reasons={CANCEL_REASONS}
        confirmLabel={`Cancel ${noun}`}
        onConfirm={async (code, note) => Boolean(await act("cancel", "Cancelled", { code, note }))}
      />
      {caps.create_credit_note?.allowed ? (
        <CreditNoteDialog
          doc={doc}
          isOpen={dialog === "credit"}
          onClose={() => setDialog(null)}
          onCreate={async (lines, reason) => {
            const creditNote = await run("credit", (k) => createCreditNote(doc.id, lines, reason, k), { done: "Credit note draft created", failed: FAILED });
            if (creditNote) router.push(asRoute(`/finance/credit-notes/${creditNote.id}`));
            return Boolean(creditNote);
          }}
        />
      ) : null}
    </Page>
  );
}
