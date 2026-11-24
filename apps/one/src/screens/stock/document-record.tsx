"use client";

import { useMemo, useState, type ReactNode } from "react";
import { documentAction, type DocumentAction, type DocumentKind, type DocumentRead } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, useCanOpen, useStockDocument } from "~/data/stock";
import { Page, RecordHeader, Split } from "~/shell/page";
import { StatusBadge, Steps, type StepItem } from "~/screens/sales/quotations/parts";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  ConfirmDialog,
  Dash,
  DataTable,
  DateText,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Qty,
  ReasonDialog,
  Tabs,
  type Column,
  type Fact,
  type IconName,
  type KeyValueItem,
  type MenuItem,
} from "~/ui";
import { DOCUMENT_KIND, documentStatus, humanise, lineDirection, MOVEMENTS_PATH, plural, viewHref, type StockRecordView } from "./labels";
import { OfflineBanner, ProductCell, RecordError, RecordLoading } from "./parts";

type DocLine = DocumentRead["lines"][number];

const PATHS: Record<DocumentKind, string> = {
  adjustment: "/operations/inventory/adjustments",
  opening_batch: "/operations/inventory/opening",
  transfer: "/operations/inventory/transfers",
};

/** The actions each kind of document has an endpoint for. Anything else the server names is not offered. */
const ACTIONS: Record<DocumentKind, readonly DocumentAction[]> = {
  adjustment: ["submit", "approve", "reject"],
  opening_batch: ["submit", "approve", "reject"],
  transfer: ["dispatch", "receive", "cancel"],
};

const FAILED = "That did not go through";

/** A stock adjustment, an opening stock batch or a transfer: one shape, three kinds. */
export function StockDocument({ kind, id, view }: { kind: DocumentKind; id: string; view: StockRecordView }) {
  const query = useStockDocument(kind, id);
  if (query.isPending) return <RecordLoading label={`Loading ${DOCUMENT_KIND[kind].what.toLowerCase()}`} />;
  if (query.isError) return <RecordError error={query.error} what={DOCUMENT_KIND[kind].what} onRetry={() => void query.refetch()} backHref="/operations/inventory" backLabel="Stock" />;
  return <Loaded doc={query.data} view={view} />;
}

interface Posting {
  label: string;
  icon: IconName;
  done: string;
  confirmTitle: string;
  confirmBody: string;
}

function postingOf(doc: DocumentRead, action: DocumentAction): Posting | null {
  const from = doc.warehouse.name;
  const to = doc.to_warehouse?.name ?? "the receiving warehouse";
  const lines = plural(doc.lines.length, "line", "lines");
  switch (action) {
    case "approve":
      return {
        label: "Approve and post",
        icon: "check",
        done: doc.kind === "adjustment" ? "Adjustment approved and posted" : "Opening stock approved and posted",
        confirmTitle: doc.kind === "adjustment" ? "Approve this adjustment and post it" : "Approve this opening stock and post it",
        confirmBody: `${lines} go into the stock ledger and stock in ${from} changes at once. A posting is never edited: a mistake is put right with a reversal.`,
      };
    case "dispatch":
      return {
        label: "Dispatch transfer",
        icon: "truck",
        done: "Transfer dispatched",
        confirmTitle: "Dispatch this transfer",
        confirmBody: `${lines} leave ${from} and are in transit until ${to} records the receipt.`,
      };
    case "receive":
      return {
        label: "Record receipt",
        icon: "packageOpen",
        done: "Transfer received",
        confirmTitle: "Record the receipt of this transfer",
        confirmBody: `${lines} go into the stock of ${to}.`,
      };
    default:
      return null;
  }
}

function Loaded({ doc, view }: { doc: DocumentRead; view: StockRecordView }) {
  const canOpen = useCanOpen();
  const key = useMemo(() => queryKeys.inventory.document(doc.kind, doc.id), [doc.kind, doc.id]);
  const { run, pending, offline } = useCommand<DocumentRead>(key);
  const [dialog, setDialog] = useState<null | DocumentAction>(null);
  const kind = DOCUMENT_KIND[doc.kind];
  const path = `${PATHS[doc.kind]}/${doc.id}`;
  const off = Boolean(offline);
  const busy = pending !== null;
  const allowed = (action: DocumentAction) => ACTIONS[doc.kind].includes(action) && Boolean(doc.capabilities[action]?.allowed);
  const act = (action: DocumentAction, done: string, note: string | null = null) => run(action, (k) => documentAction(doc, action, k, note), { done, failed: FAILED, write: (result) => result });

  // The one posting step the document is ready for, if this person may take it.
  const postingAction = (["approve", "dispatch", "receive"] as const).find(allowed) ?? null;
  const posting = postingAction ? postingOf(doc, postingAction) : null;
  const confirming = dialog && dialog !== "reject" && dialog !== "cancel" ? postingOf(doc, dialog) : null;

  const menu: MenuItem[] = [];
  if (allowed("cancel")) menu.push({ id: "cancel", label: "Cancel transfer", icon: "xCircle", tone: "danger", isDisabled: off, onAction: () => setDialog("cancel") });

  const title = doc.kind === "transfer" ? `${doc.warehouse.name} to ${doc.to_warehouse?.name ?? "another warehouse"}` : doc.kind === "adjustment" ? `Adjustment at ${doc.warehouse.name}` : `Opening stock for ${doc.warehouse.name}`;
  const lead =
    doc.kind === "transfer"
      ? "Stock moving from one warehouse to another."
      : doc.kind === "adjustment"
        ? "Puts the records right: units found are added, units lost are removed."
        : "The stock this warehouse starts with in Lamikraft One.";

  const facts: Fact[] =
    doc.kind === "transfer"
      ? [
          { label: "From", icon: "warehouse", value: doc.warehouse.code },
          { label: "To", icon: "mapPin", value: doc.to_warehouse?.code },
          { label: "Lines", icon: "list", value: doc.lines.length },
          { label: "Created by", icon: "user", value: doc.created_by?.display_name },
          { label: "Created", icon: "calendar", value: <DateText value={doc.created_at} style="date" /> },
        ]
      : [
          { label: "Warehouse", icon: "warehouse", value: doc.warehouse.code },
          { label: "Lines", icon: "list", value: doc.lines.length },
          { label: "Created by", icon: "user", value: doc.created_by?.display_name },
          { label: "Created", icon: "calendar", value: <DateText value={doc.created_at} style="date" /> },
          { label: "Decided by", icon: "badgeCheck", value: doc.decided_by?.display_name },
        ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Stock", href: "/operations/inventory" }, { label: `${kind.name} ${doc.number}` }]}
        code={doc.number}
        title={title}
        status={<StatusBadge look={documentStatus(doc.status)} />}
        lead={lead}
        facts={<FactStrip items={facts} />}
        actions={
          <>
            {allowed("submit") ? (
              <Button iconLeft="send" loading={pending === "submit"} isDisabled={off || busy} onPress={() => void act("submit", "Sent for approval")}>
                Submit for approval
              </Button>
            ) : null}
            {posting && postingAction ? (
              <Button iconLeft={posting.icon} isDisabled={off || busy} onPress={() => setDialog(postingAction)}>
                {posting.label}
              </Button>
            ) : null}
            {allowed("reject") ? (
              <Button variant="secondary" iconLeft="x" isDisabled={off || busy} onPress={() => setDialog("reject")}>
                Reject
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label={`More ${kind.name.toLowerCase()} actions`}
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
          label={`Views of ${kind.what.toLowerCase()}`}
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Lines", count: doc.lines.length || undefined, href: asRoute(viewHref(path, "lines")) },
          ]}
        />
      </RecordHeader>

      {offline ? <OfflineBanner what={kind.what.toLowerCase()} /> : null}
      {doc.capabilities.approve?.reason_code === "approver_is_creator" ? (
        <Banner tone="cobalt" title="A second person approves this.">
          You created it, so someone else has to approve and post it.
        </Banner>
      ) : null}
      {doc.status === "rejected" ? (
        <Banner tone="ember" icon="xCircle" title={doc.decided_by?.display_name ? `Rejected by ${doc.decided_by.display_name}.` : "Rejected."}>
          {doc.decision_note ?? "Nothing was posted."}
        </Banner>
      ) : null}

      {view === "overview" ? <Overview doc={doc} canSeeMovements={canOpen(MOVEMENTS_PATH)} /> : null}
      {view === "lines" ? <Lines doc={doc} /> : null}

      <ConfirmDialog
        isOpen={confirming !== null}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title={confirming?.confirmTitle ?? ""}
        description={confirming?.confirmBody}
        confirmLabel={confirming?.label ?? ""}
        cancelLabel="Not yet"
        onConfirm={async () => {
          if (!dialog || !confirming) return;
          if (!(await act(dialog, confirming.done))) throw new Error("posting failed");
        }}
      />
      <ReasonDialog
        isOpen={dialog === "reject"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        tone="danger"
        title={`Reject ${doc.number}`}
        description="Nothing is posted. The reason goes back to the person who created it."
        reasonLabel="Why it is rejected"
        reasonHelp="Say what is wrong, so it can be corrected and raised again."
        confirmLabel={doc.kind === "adjustment" ? "Reject adjustment" : "Reject opening stock"}
        cancelLabel="Keep it open"
        onConfirm={async (reason) => {
          if (!(await act("reject", doc.kind === "adjustment" ? "Adjustment rejected" : "Opening stock rejected", reason))) throw new Error("reject failed");
        }}
      />
      <ConfirmDialog
        isOpen={dialog === "cancel"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        tone="danger"
        title="Cancel this transfer"
        description={`Nothing more moves on ${doc.number}.`}
        confirmLabel="Cancel transfer"
        cancelLabel="Keep it"
        onConfirm={async () => {
          if (!(await act("cancel", "Transfer cancelled"))) throw new Error("cancel failed");
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview

function progressOf(doc: DocumentRead): StepItem[] {
  const closed = doc.status === "rejected" || doc.status === "cancelled";
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] =
    doc.kind === "transfer"
      ? [
          { id: "draft", label: "Raised", hint: <DateText value={doc.created_at} style="date" />, done: true },
          { id: "dispatch", label: "Dispatched", hint: `Leaves ${doc.warehouse.code}`, done: doc.status === "dispatched" || doc.status === "received" },
          { id: "receive", label: "Received", hint: doc.to_warehouse ? `Arrives at ${doc.to_warehouse.code}` : "Arrives", done: doc.status === "received" },
        ]
      : [
          { id: "draft", label: "Raised", hint: <DateText value={doc.created_at} style="date" />, done: true },
          { id: "submit", label: "Submitted", hint: "Sent to a second person", done: doc.status === "submitted" || doc.status === "posted" || doc.status === "rejected" },
          { id: "post", label: "Approved and posted", hint: doc.status === "posted" && doc.decided_at ? <DateText value={doc.decided_at} style="date" /> : "Into the stock ledger", done: doc.status === "posted" },
        ];
  const current = closed ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(doc: DocumentRead): { headline: ReactNode; body: string } {
  const from = doc.warehouse.name;
  const to = doc.to_warehouse?.name ?? "the receiving warehouse";
  if (doc.kind === "transfer") {
    switch (doc.status) {
      case "draft":
        return { headline: <>Ready to <em>dispatch</em></>, body: `Dispatching takes these lines out of ${from} and puts them in transit.` };
      case "dispatched":
        return { headline: <>In <em>transit</em></>, body: `The goods have left ${from}. Recording the receipt puts them into ${to}.` };
      case "received":
        return { headline: <>Received in <em>full</em></>, body: `These lines are now in the stock of ${to}.` };
      case "cancelled":
        return { headline: "Cancelled", body: "Nothing more moves on this transfer." };
      default:
        return { headline: documentStatus(doc.status).label, body: "" };
    }
  }
  switch (doc.status) {
    case "draft":
      return { headline: <>Ready to <em>submit</em></>, body: "Submitting sends it to a second person. Stock changes only once it is approved and posted." };
    case "submitted":
      return { headline: <>Waiting for <em>approval</em></>, body: "Approval posts these lines to the stock ledger. A different person approves what someone creates." };
    case "posted":
      return { headline: <>Approved and <em>posted</em></>, body: `These lines are in the stock ledger and the stock of ${from} reflects them.` };
    case "rejected":
      return { headline: "Rejected", body: "Nothing was posted. The reason is shown above." };
    default:
      return { headline: documentStatus(doc.status).label, body: "" };
  }
}

function Overview({ doc, canSeeMovements }: { doc: DocumentRead; canSeeMovements: boolean }) {
  const standing = standingOf(doc);
  const reason = [doc.reason_code ? humanise(doc.reason_code) : null, doc.reason].filter(Boolean).join(": ");
  const person = (who: DocumentRead["created_by"], when?: string | null) =>
    who?.display_name ? (
      <span className="flex flex-col items-end">
        <span>{who.display_name}</span>
        {when ? <DateText value={when} style="dayTime" className="t-caption text-ink-3" /> : null}
      </span>
    ) : null;
  const details: KeyValueItem[] = [
    { label: doc.kind === "transfer" ? "From" : "Warehouse", value: `${doc.warehouse.code} · ${doc.warehouse.name}` },
    ...(doc.to_warehouse ? [{ label: "To", value: `${doc.to_warehouse.code} · ${doc.to_warehouse.name}` }] : []),
    ...(reason ? [{ label: "Reason", value: reason }] : []),
    ...(doc.notes ? [{ label: "Notes", value: doc.notes }] : []),
    { label: "Created by", value: person(doc.created_by, doc.created_at) },
    ...(doc.kind === "transfer" && !doc.decided_by ? [] : [{ label: "Decided by", value: person(doc.decided_by ?? null, doc.decided_at) }]),
    ...(doc.decision_note && doc.status !== "rejected" ? [{ label: "Decision note", value: doc.decision_note }] : []),
  ];
  return (
    <Split
      main={
        <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
          <Steps label={`Progress of ${DOCUMENT_KIND[doc.kind].what.toLowerCase()}`} steps={progressOf(doc)} />
          <div className="flex max-w-prose flex-col gap-2">
            <h2 className="t-display-sm text-ink">{standing.headline}</h2>
            {standing.body ? <p className="t-body text-ink-2">{standing.body}</p> : null}
          </div>
          {doc.posting_id && canSeeMovements ? (
            <div>
              <ButtonLink href={asRoute(MOVEMENTS_PATH)} variant="secondary" iconRight="arrowRight">
                See stock movements
              </ButtonLink>
            </div>
          ) : null}
        </GlassPanel>
      }
      aside={
        <GlassPanel padding="md" className="rise" title="Details" titleAs="h2">
          <KeyValue rows items={details} />
        </GlassPanel>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Lines

function Lines({ doc }: { doc: DocumentRead }) {
  const directed = doc.lines.some((line) => line.direction);
  const columns: Column<DocLine>[] = [
    { key: "product", header: "Product", primary: true, cell: (line) => <ProductCell product={line.product} /> },
    { key: "location", header: "Location", cell: (line) => (line.location ? <span className="lk-mono text-ink">{line.location.code}</span> : <Dash />) },
    { key: "lot", header: "Lot", cell: (line) => <Code>{line.lot?.lot_code ?? line.lot_code}</Code> },
    ...(directed
      ? [
          {
            key: "direction",
            header: "Change",
            cell: (line: DocLine) => {
              if (!line.direction) return <Dash />;
              const direction = lineDirection(line.direction);
              return (
                <Badge tone={direction.tone} size="sm" icon={line.direction === "in" ? "plus" : line.direction === "out" ? "minus" : undefined}>
                  {direction.label}
                </Badge>
              );
            },
          },
        ]
      : []),
    { key: "quantity", header: "Quantity", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.unit }} className="t-label text-ink" /> },
  ];
  return (
    <GlassPanel padding="none" className="rise min-w-0">
      <DataTable label={`Lines of ${doc.number}`} columns={columns} rows={doc.lines} rowKey={(line) => line.id} />
    </GlassPanel>
  );
}
