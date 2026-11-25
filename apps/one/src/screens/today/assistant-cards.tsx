"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useId, type ReactNode } from "react";
import { undoReceipt } from "@/features/assistant/api";
import type {
  AssistantCard,
  ClarificationCard,
  ClarificationOption,
  ErrorCard,
  QuoteDraftCard,
  ReceiptCard,
  RecordLinkCard,
} from "@/features/assistant/types";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { useNow } from "@/lib/session/context";
import { Badge, Button, ButtonLink, DateText, GlassPanel, Icon, KeyValue, Money, Qty, TextLink } from "~/ui";

/**
 * Cards the server builds from tool results. Every figure is the server's, formatted from its
 * decimal string; nothing is added up here. Inner surfaces are solid: they sit on a glass reply.
 */

const DEMO_HINT = "Answers come from a deterministic demo engine, not a live AI model.";

export function DemoBadge() {
  return (
    <span title={DEMO_HINT}>
      <Badge size="sm" outline>
        Demo
      </Badge>
      <span className="lk-sr-only">: {DEMO_HINT}</span>
    </span>
  );
}

function CardShell({ titleId, title, demo, kind, children }: { titleId: string; title: ReactNode; demo: boolean; kind: string; children: ReactNode }) {
  return (
    <GlassPanel as="section" variant="solid" padding="sm" aria-labelledby={titleId} data-card={kind} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={titleId} className="t-h4">
          {title}
        </h4>
        {demo ? <DemoBadge /> : null}
      </div>
      {children}
    </GlassPanel>
  );
}

function QuoteDraft({ card }: { card: QuoteDraftCard }) {
  const titleId = useId();
  return (
    <CardShell titleId={titleId} demo={card.demo} kind="quote_draft" title={card.quote_number ? `Draft ${card.quote_number}` : "Totals preview"}>
      {card.party_name ? <p className="t-body-sm text-ink-2 -mt-3">For {card.party_name}</p> : null}
      {card.lines.length > 0 ? (
        <ul aria-label="Lines" className="m-0 flex list-none flex-col p-0">
          {card.lines.map((line) => (
            <li key={line.line_no} className="border-line flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-t py-3 first:border-t-0 first:pt-0">
              <span className="flex min-w-0 flex-col">
                <span className="t-body text-ink">{line.label}</span>
                {line.product_key ? <span className="t-code-sm lk-mono text-ink-3">{line.product_key}</span> : null}
              </span>
              <span className="t-body-sm text-ink-2 flex items-baseline gap-2">
                <Qty value={{ value: line.quantity, uom: line.unit_code }} />
                <span aria-hidden="true">×</span>
                <span className="lk-sr-only">at</span>
                <Money value={line.unit_price} />
                <span aria-hidden="true">=</span>
                <span className="lk-sr-only">line total</span>
                <Money value={line.line_total} className="t-label text-ink" />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <KeyValue
        rows
        items={[
          ...(card.subtotal ? [{ label: "Subtotal", value: <Money value={card.subtotal} /> }] : []),
          ...(card.surcharge ? [{ label: "Minimum order surcharge", value: <Money value={card.surcharge} /> }] : []),
          { label: "Grand total, before taxes", value: <Money value={card.grand_total} />, total: true },
        ]}
      />
      {card.notes.length > 0 ? (
        <ul className="t-body-sm text-ink-2 m-0 flex list-none flex-col gap-1 p-0">
          {card.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {card.preview_only ? <p className="t-body-sm text-ink-2">A preview only: nothing was saved. Apply the change in the quotation to keep it.</p> : null}
      {card.requires_confirmation ? (
        <p className="t-body-sm text-amber-text flex items-start gap-2">
          <Icon name="alert" size={16} />
          This used text from a customer message. Check every line before you request review or send it.
        </p>
      ) : null}
      {card.open_href ? (
        <div className="flex flex-wrap gap-2">
          <ButtonLink href={card.open_href as Route} variant="inverse" size="sm" iconRight="arrowRight">
            Open the draft
          </ButtonLink>
          {card.review_href && card.review_href !== card.open_href ? (
            <ButtonLink href={card.review_href as Route} variant="secondary" size="sm">
              Review and request approval
            </ButtonLink>
          ) : null}
        </div>
      ) : null}
    </CardShell>
  );
}

function Clarification({ card, onChoose, busy }: { card: ClarificationCard; onChoose?: (option: ClarificationOption) => void; busy: boolean }) {
  const titleId = useId();
  return (
    <CardShell titleId={titleId} demo={card.demo} kind="clarification" title={card.question}>
      <ul aria-label="Choose one" className="m-0 flex list-none flex-col gap-2 p-0">
        {card.options.map((option) => (
          <li key={option.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {onChoose ? (
              <Button variant="secondary" size="sm" isDisabled={busy} onPress={() => onChoose(option)}>
                {option.label}
              </Button>
            ) : (
              <span className="t-body text-ink">{option.label}</span>
            )}
            {option.detail ? <span className="t-body-sm text-ink-3">{option.detail}</span> : null}
          </li>
        ))}
      </ul>
    </CardShell>
  );
}

function ErrorNote({ card }: { card: ErrorCard }) {
  const titleId = useId();
  return (
    <CardShell titleId={titleId} demo={card.demo} kind="error" title="Lamikraft could not complete this">
      <p className="t-body text-ink">{card.message}</p>
      {card.recoverable || card.controls.length > 0 ? (
        <ul className="t-body-sm m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
          {card.recoverable ? (
            <li>
              <TextLink href={card.recoverable.href as Route}>{card.recoverable.label}</TextLink>
            </li>
          ) : null}
          {card.controls.map((control) => (
            <li key={control.href}>
              <TextLink href={control.href as Route}>{control.label}</TextLink>
            </li>
          ))}
        </ul>
      ) : null}
    </CardShell>
  );
}

function RecordLink({ card }: { card: RecordLinkCard }) {
  return (
    <GlassPanel as="section" variant="solid" padding="sm" aria-label={card.label} data-card="record_link" className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <TextLink href={card.href as Route} className="t-h4">
          {card.label}
        </TextLink>
        {card.demo ? <DemoBadge /> : null}
      </div>
      {card.detail ? <p className="t-body-sm text-ink-2">{card.detail}</p> : null}
    </GlassPanel>
  );
}

/** Undo is offered while the server allowed it and the window is open; the server checks again. */
function canOfferUndo(card: Pick<ReceiptCard, "undo">, now: Date | null): boolean {
  const undo = card.undo;
  if (!undo?.allowed) return false;
  return undo.until === null || now === null || new Date(undo.until).getTime() > now.getTime();
}

function ReceiptUndo({ card }: { card: ReceiptCard }) {
  const client = useQueryClient();
  const undo = useMutation({
    mutationFn: () => undoReceipt(card.undo!.receiptId),
    onSuccess: () => {
      for (const key of invalidationMap["agents.receipt_undone"]) void client.invalidateQueries({ queryKey: key });
    },
  });
  if (undo.isSuccess) {
    return (
      <p role="status" className="t-label text-ink">
        Undone
        {undo.data && undo.data.kind === "receipt" ? <span className="t-body-sm text-ink-2"> · {undo.data.title}</span> : null}
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" size="sm" iconLeft="undo" loading={undo.isPending} onPress={() => undo.mutate()}>
        Undo this change
      </Button>
      {card.undo?.until ? (
        <span className="t-caption text-ink-3">
          Available until <DateText value={card.undo.until} style="dayTime" />
        </span>
      ) : null}
      {undo.isError ? (
        <p role="alert" className="t-body-sm text-ember-text w-full">
          {undo.error instanceof ProblemError && undo.error.detail ? undo.error.detail : "This change could not be undone. Open the record to reverse it by hand."}
        </p>
      ) : null}
    </div>
  );
}

function Receipt({ card }: { card: ReceiptCard }) {
  const titleId = useId();
  const now = useNow();
  return (
    <CardShell titleId={titleId} demo={card.demo} kind="receipt" title={card.title}>
      {card.detail ? <p className="t-body-sm text-ink-2 -mt-2">{card.detail}</p> : null}
      {card.link ? (
        <p className="t-body-sm">
          <TextLink href={card.link.href as Route}>{card.link.label}</TextLink>
        </p>
      ) : null}
      {canOfferUndo(card, now) ? <ReceiptUndo card={card} /> : null}
    </CardShell>
  );
}

export function AssistantCardView({ card, onChoose, busy = false }: { card: AssistantCard; onChoose?: (option: ClarificationOption) => void; busy?: boolean }) {
  switch (card.kind) {
    case "quote_draft":
      return <QuoteDraft card={card} />;
    case "clarification":
      return <Clarification card={card} onChoose={onChoose} busy={busy} />;
    case "error":
      return <ErrorNote card={card} />;
    case "record_link":
      return <RecordLink card={card} />;
    case "receipt":
      return <Receipt card={card} />;
  }
}
