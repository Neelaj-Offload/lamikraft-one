"use client";

import type { ReactNode } from "react";
import type { ChallanDetail } from "@/features/challans/types";
import {
  asRoute,
  cancelReasonLabel,
  challanStatus,
  DESTINATION_LABEL,
  issueBlockedText,
  RETURN_LABEL,
  tracksReturns,
  TYPE_LABEL,
} from "~/data/challans";
import { Split } from "~/shell/page";
import { Badge, Button, Code, DateText, EmptyState, GlassPanel, KeyValue, Qty, TextLink, Timeline, type IconName, type KeyValueItem, type TimelineItem } from "~/ui";
import { Steps, type StepItem } from "../sales/quotations/parts";
import { QuantityList, stagger } from "./parts";
import { viewHref } from "./views";

const hasOut = (challan: ChallanDetail) => Object.keys(challan.outstanding_by_unit).length > 0;

// ---------------------------------------------------------------------------------------------
// Overview: where it stands and what is next

function progressOf(challan: ChallanDetail): StepItem[] {
  const stopped = challan.status === "cancelled" || challan.deleted_at !== null;
  const issued = challan.issued_at !== null || challan.status === "issued" || challan.status === "closed";
  const closed = challan.status === "closed";
  const raw = [
    { id: "draft", label: "Drafted", hint: <DateText value={challan.created_at} style="date" />, done: true },
    {
      id: "issued",
      label: "Issued",
      hint: challan.issued_at ? <DateText value={challan.issued_at} style="date" /> : "Fixed and ready to print",
      done: issued,
    },
    {
      id: "closed",
      label: "Closed",
      hint: challan.closed_at ? <DateText value={challan.closed_at} style="date" /> : tracksReturns(challan) ? "Once it is all back" : "Nothing more expected",
      done: closed,
    },
  ];
  const current = stopped ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !stopped ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(challan: ChallanDetail): { headline: ReactNode; body: ReactNode } {
  if (challan.deleted_at) return { headline: "Deleted", body: "This draft was deleted. Its number stays reserved and is never given to another challan." };
  if (challan.status === "cancelled") {
    const reason = cancelReasonLabel(challan.cancel_reason_code);
    return {
      headline: "Cancelled",
      body: [reason ? `${reason}.` : null, challan.cancel_reason, "It stays on file with its number."].filter(Boolean).join(" "),
    };
  }
  if (challan.status === "closed") return { headline: <>Closed and <em>done</em></>, body: challan.close_reason ?? "Nothing more is expected against this challan." };
  if (challan.status === "issued") {
    if (challan.return_type === "returnable" && hasOut(challan)) {
      return {
        headline: <>Out, waiting to come <em>back</em></>,
        body: (
          <>
            Still out: <QuantityList value={challan.outstanding_by_unit} className="text-ink" />.
            {challan.expected_return_date ? (
              <>
                {" "}
                Expected back by <DateText value={challan.expected_return_date} style="business" />.
              </>
            ) : null}{" "}
            Close it once nothing more is expected.
          </>
        ),
      };
    }
    return { headline: <>Issued and on its <em>way</em></>, body: "The challan travels with the goods. Close it once nothing more is expected against it." };
  }
  const blocked = issueBlockedText(challan);
  if (challan.lines.length === 0) return { headline: <>Waiting for its <em>lines</em></>, body: "Add what is travelling, then issue it. Until then you can change anything." };
  if (blocked) return { headline: <>Almost ready to <em>issue</em></>, body: blocked };
  return {
    headline: <>Ready to <em>issue</em></>,
    body: "Check the lines and where it is going. Once issued the challan is fixed, and you can print it to travel with the goods.",
  };
}

export function Overview({ challan }: { challan: ChallanDetail }) {
  const standing = standingOf(challan);
  const path = challan.path;
  const showOut = challan.status !== "draft" && challan.return_type === "returnable";
  const linked: KeyValueItem[] = [
    {
      label: DESTINATION_LABEL[challan.destination_type] ? `${DESTINATION_LABEL[challan.destination_type]} on record` : "On record",
      value: challan.party ? (
        <TextLink href={asRoute(`/sales/parties/${encodeURIComponent(challan.party.id)}`)}>{challan.party.display_name ?? challan.party.party_number}</TextLink>
      ) : null,
    },
    {
      label: "Original challan",
      value: challan.original_challan ? (
        <TextLink href={asRoute(challan.original_challan.path)}>
          <Code>{challan.original_challan.challan_number}</Code>
        </TextLink>
      ) : null,
    },
    {
      label: "Copied from",
      value: challan.duplicated_from ? (
        <TextLink href={asRoute(challan.duplicated_from.path)}>
          <Code>{challan.duplicated_from.challan_number}</Code>
        </TextLink>
      ) : null,
    },
    {
      label: "Returns",
      value:
        challan.return_links.length > 0 ? (
          <TextLink href={asRoute(viewHref(path, "returns"))}>{challan.return_links.length === 1 ? "1 return recorded" : `${challan.return_links.length} returns recorded`}</TextLink>
        ) : null,
    },
  ].filter((item) => item.value !== null);

  const record: KeyValueItem[] = [
    { label: "Owner", value: challan.owner.display_name },
    { label: "Created", value: <DateText value={challan.created_at} style="dayTime" /> },
    ...(challan.issued_at
      ? [
          {
            label: "Issued",
            value: (
              <>
                <DateText value={challan.issued_at} style="dayTime" />
                {challan.issued_by?.display_name ? ` · ${challan.issued_by.display_name}` : null}
              </>
            ),
          },
        ]
      : []),
    ...(challan.closed_at ? [{ label: "Closed", value: <DateText value={challan.closed_at} style="dayTime" /> }] : []),
    ...(challan.cancelled_at ? [{ label: "Cancelled", value: <DateText value={challan.cancelled_at} style="dayTime" /> }] : []),
  ];

  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this challan" steps={progressOf(challan)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>

          <section aria-label="What is travelling" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6" style={stagger(1)}>
            <div className="flex items-center justify-between gap-3">
              <h2 className="t-overline opacity-70">What is travelling</h2>
              <span className="t-caption lk-tnum opacity-70">{challan.line_count === 1 ? "1 line" : `${challan.line_count} lines`}</span>
            </div>
            <p className="t-stat-xl min-w-0 [overflow-wrap:anywhere]">
              <QuantityList value={challan.quantity_by_unit} />
            </p>
            {showOut ? (
              <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 border-t border-on-inverse/20 pt-5">
                <span className="t-label">Still out</span>
                <span className="t-stat ml-auto text-right">
                  <QuantityList value={challan.outstanding_by_unit} />
                </span>
              </div>
            ) : null}
            <p className="t-body-sm opacity-80">
              {TYPE_LABEL[challan.challan_type] ?? challan.challan_type}, {(RETURN_LABEL[challan.return_type] ?? challan.return_type).toLowerCase()}.{" "}
              {challan.inventory_effect === "none" ? "Issuing records the paperwork. It does not move stock." : "Units are counted separately and never added together."}
            </p>
          </section>
        </>
      }
      aside={
        <>
          {linked.length > 0 ? (
            <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
              <KeyValue rows items={linked} />
            </GlassPanel>
          ) : null}
          <GlassPanel padding="md" className="rise" title="On record" titleAs="h2">
            <KeyValue rows items={record} />
          </GlassPanel>
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Details: where from, where to, what the receiver reads

export function DetailsView({ challan, canEdit, onEdit }: { challan: ChallanDetail; canEdit: boolean; onEdit: () => void }) {
  const from: KeyValueItem[] = [
    { label: "Sent from", value: challan.source_location },
    { label: "Challan date", value: <DateText value={challan.challan_date} style="business" /> },
    { label: "Type", value: `${TYPE_LABEL[challan.challan_type] ?? challan.challan_type}, ${(RETURN_LABEL[challan.return_type] ?? challan.return_type).toLowerCase()}` },
    { label: "Reference number", value: challan.reference_no, mono: true },
    { label: "Expected back", value: challan.expected_return_date ? <DateText value={challan.expected_return_date} style="business" /> : null },
  ];
  const to: KeyValueItem[] = [
    { label: "Going to", value: DESTINATION_LABEL[challan.destination_type] ?? challan.destination_type },
    { label: "Name on the challan", value: challan.destination_party },
    {
      label: "On record",
      value: challan.party ? (
        <TextLink href={asRoute(`/sales/parties/${encodeURIComponent(challan.party.id)}`)}>{[challan.party.party_number, challan.party.display_name].filter(Boolean).join(" · ")}</TextLink>
      ) : null,
    },
    { label: "Shipping name", value: challan.shipping_name },
    {
      label: "GSTIN",
      value: challan.gstin ? (
        <span className="flex flex-col gap-0.5">
          <span className="lk-mono">{challan.gstin}</span>
          <span className="t-caption text-ink-3">Format checked, not verified</span>
        </span>
      ) : null,
    },
    { label: "Phone", value: challan.phone },
    { label: "Email", value: challan.email },
    { label: "Address", value: challan.address ? <span className="whitespace-pre-line [overflow-wrap:anywhere]">{challan.address}</span> : null },
  ];
  const present = (items: KeyValueItem[]) => items.filter((item) => item.value !== null && item.value !== undefined && item.value !== "");

  return (
    <div className="stack">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3">Details</h2>
          <p className="t-body-sm text-ink-3">{canEdit ? "Everything printed in the From and To blocks. You can change it until you issue." : "Everything printed in the From and To blocks."}</p>
        </div>
        {canEdit ? (
          <Button variant="secondary" size="sm" iconLeft="edit" onPress={onEdit}>
            Edit details
          </Button>
        ) : null}
      </div>
      <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
        <GlassPanel padding="md" className="rise" title="From" titleAs="h3">
          <KeyValue rows items={present(from)} />
        </GlassPanel>
        <GlassPanel padding="md" className="rise" style={stagger(1)} title="To" titleAs="h3">
          <KeyValue rows items={present(to)} />
        </GlassPanel>
      </div>
      <GlassPanel padding="md" className="rise" style={stagger(2)} title="Remarks" titleAs="h3">
        {challan.remarks ? (
          <p className="t-body whitespace-pre-line text-ink [overflow-wrap:anywhere]">{challan.remarks}</p>
        ) : (
          <p className="t-body-sm text-ink-3">No remarks. Anything written here is printed on the challan.</p>
        )}
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Returns: what came back on which challan

export function ReturnsView({ challan }: { challan: ChallanDetail }) {
  const unitOf = (lineId: string) => challan.lines.find((line) => line.id === lineId)?.unit ?? "";
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Returns</h2>
        <p className="t-body-sm text-ink-3">
          {challan.challan_type === "return" ? "The challans this return brings goods back against." : "Each return challan that brought goods back against this one."}
        </p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0 overflow-hidden">
        {challan.return_links.length === 0 ? (
          <EmptyState
            compact
            icon="undo"
            title="Nothing has come back yet"
            text={hasOut(challan) ? "Returns appear here once a return challan against this one is issued." : "Returns appear here once a return challan is issued."}
          />
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {challan.return_links.map((link, index) => {
              const asOriginal = link.original_challan.id === challan.id;
              const other = asOriginal ? link.return_challan : link.original_challan;
              const unit = unitOf(asOriginal ? link.original_line_id : link.return_line_id);
              return (
                <li key={link.id} className="rise-plain flex min-w-0 flex-wrap items-center gap-4 border-line px-5 py-4 [&:not(:first-child)]:border-t" style={stagger(index)}>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="t-label text-ink">
                      {asOriginal ? "Came back on " : "Brings back goods from "}
                      <TextLink href={asRoute(other.path)}>
                        <Code>{other.challan_number}</Code>
                      </TextLink>
                    </span>
                    <span className="t-caption text-ink-3">
                      <DateText value={link.created_at} style="dayTime" />
                    </span>
                  </span>
                  <span className="flex items-center gap-3">
                    {link.reversed_at ? (
                      <Badge tone="neutral" size="sm">
                        Reversed
                      </Badge>
                    ) : null}
                    <span className="t-label lk-tnum text-ink">{unit ? <Qty value={{ value: link.quantity, uom: unit }} /> : link.quantity}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Activity

const DID: Record<string, string> = {
  issue: "issued it",
  close: "closed it",
  cancel: "cancelled it",
  delete: "deleted the draft",
  create: "created the draft",
};
const DID_ICON: Record<string, IconName> = { issue: "send", close: "checkCircle", cancel: "xCircle", delete: "trash", create: "filePlus" };

export function ActivityView({ challan }: { challan: ChallanDetail }) {
  const items: TimelineItem[] = [...challan.history]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .map((entry, index) => ({
      id: `${entry.occurred_at}-${index}`,
      title: `${entry.actor?.display_name ?? "Lamikraft One"} ${DID[entry.action] ?? `moved it from ${challanStatus(entry.from_status).label.toLowerCase()} to ${challanStatus(entry.to_status).label.toLowerCase()}`}`,
      meta: (
        <>
          <DateText value={entry.occurred_at} style="dayTime" />
          {" · "}
          {challanStatus(entry.from_status).label} to {challanStatus(entry.to_status).label.toLowerCase()}
        </>
      ),
      body: [cancelReasonLabel(entry.reason_code), entry.reason].filter(Boolean).join(": ") || undefined,
      icon: DID_ICON[entry.action],
      tone: challanStatus(entry.to_status).tone,
    }));
  return (
    <GlassPanel padding="lg" title="Activity" titleAs="h2" className="rise">
      {items.length === 0 ? (
        <EmptyState compact icon="history" title="Nothing has happened yet" text="Issuing, closing and cancelling are recorded here, with who did it and why." />
      ) : (
        <Timeline label="Challan activity" items={items} />
      )}
    </GlassPanel>
  );
}
