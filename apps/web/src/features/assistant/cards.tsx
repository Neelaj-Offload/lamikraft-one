"use client";

import { useId } from "react";
import { DemoBadge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Money, Quantity } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { assistantMessages as m } from "@/messages/assistant";
import type { AssistantCard, ClarificationCard, ClarificationOption, ErrorCard, QuoteDraftCard, ReceiptCard, RecordLinkCard } from "./types";

/**
 * Server-built cards (ai-routing.md §5). Every figure is the server's (persisted totals from the
 * tool output), formatted from its DecimalStr string; the client never adds anything up.
 */
export interface CardProps {
  card: AssistantCard;
  /** Posts a ClarificationCard option as the next turn. */
  onChoose?: (option: ClarificationOption, card: ClarificationCard) => void;
  /** While a turn is being sent or a run is active, options are disabled. */
  isBusy?: boolean;
}

const surface = "flex flex-col gap-3 rounded-lg border bg-surface p-4";

function CardHeading({ id, children, demo }: { id: string; children: React.ReactNode; demo: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <h3 id={id} className="text-base font-[650] text-ink">
        {children}
      </h3>
      {demo ? <DemoBadge label={m.demo} title={m.demoHint} /> : null}
    </div>
  );
}

export function QuoteDraftCardView({ card }: { card: QuoteDraftCard }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className={surface} data-card="quote_draft">
      <div className="flex flex-col gap-0.5">
        <CardHeading id={titleId} demo={card.demo}>
          {card.quote_number ? m.cards.draftTitle(card.quote_number) : m.cards.previewTitle}
        </CardHeading>
        {card.party_name ? <p className="text-sm text-ink-muted">{m.cards.draftFor(card.party_name)}</p> : null}
      </div>
      {card.lines.length > 0 ? (
        <table className="w-full text-sm">
          <caption className="sr-only">{m.cards.linesCaption(card.quote_number ?? m.cards.previewTitle)}</caption>
          <thead>
            <tr className="text-start text-ink-muted">
              <th scope="col" className="py-1 text-start font-semibold">
                {m.cards.line}
              </th>
              <th scope="col" className="py-1 ps-3 text-end font-semibold">
                {m.cards.quantity}
              </th>
              <th scope="col" className="py-1 ps-3 text-end font-semibold">
                {m.cards.unitPrice}
              </th>
              <th scope="col" className="py-1 ps-3 text-end font-semibold">
                {m.cards.lineTotal}
              </th>
            </tr>
          </thead>
          <tbody>
            {card.lines.map((line) => (
              <tr key={line.line_no} className="border-t">
                <th scope="row" className="py-1.5 pe-2 text-start font-normal">
                  <span className="block text-ink">{line.label}</span>
                  {line.product_key ? <span className="block font-mono text-xs text-ink-muted">{line.product_key}</span> : null}
                </th>
                <td className="whitespace-nowrap py-1.5 ps-3 text-end align-top">
                  <Quantity value={{ value: line.quantity, uom: line.unit_code }} />
                </td>
                <td className="whitespace-nowrap py-1.5 ps-3 text-end align-top">
                  <Money value={line.unit_price} maxFractionDigits={4} />
                </td>
                <td className="whitespace-nowrap py-1.5 ps-3 text-end align-top">
                  <Money value={line.line_total} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <dl className="flex flex-col gap-1 border-t pt-2 text-sm">
        {card.subtotal ? (
          <div className="flex justify-between gap-4">
            <dt className="text-ink-muted">{m.cards.subtotal}</dt>
            <dd>
              <Money value={card.subtotal} />
            </dd>
          </div>
        ) : null}
        {card.surcharge ? (
          <div className="flex justify-between gap-4">
            <dt className="text-ink-muted">{m.cards.surcharge}</dt>
            <dd>
              <Money value={card.surcharge} />
            </dd>
          </div>
        ) : null}
        <div className="flex justify-between gap-4 text-base font-[650] text-ink">
          <dt>{m.cards.grandTotal}</dt>
          <dd>
            <Money value={card.grand_total} />
          </dd>
        </div>
      </dl>
      {card.notes.length > 0 ? (
        <ul className="flex flex-col gap-1 text-sm text-ink-muted">
          {card.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {card.preview_only ? <p className="text-sm text-ink-muted">{m.cards.previewOnly}</p> : null}
      {card.requires_confirmation ? <p className="text-sm text-warning-text">{m.cards.confirm}</p> : null}
      {card.open_href ? (
        <div className="flex flex-wrap gap-2">
          <LinkButton href={card.open_href} variant="primary">
            {m.cards.openDraft}
          </LinkButton>
          {card.review_href && card.review_href !== card.open_href ? (
            <LinkButton href={card.review_href} variant="secondary">
              {m.cards.review}
            </LinkButton>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function ClarificationCardView({ card, onChoose, isBusy = false }: { card: ClarificationCard; onChoose?: CardProps["onChoose"]; isBusy?: boolean }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className={surface} data-card="clarification">
      <CardHeading id={titleId} demo={card.demo}>
        {card.question}
      </CardHeading>
      <ul aria-label={m.cards.clarify} className="flex flex-col gap-2">
        {card.options.map((option) => (
          <li key={option.id}>
            {onChoose ? (
              <Button variant="secondary" onPress={() => onChoose(option, card)} {...unavailableWhen(isBusy ? m.working : null)}>
                <span className="flex flex-col items-start text-start">
                  <span>{option.label}</span>
                  {option.detail ? <span className="text-xs font-normal text-ink-muted">{option.detail}</span> : null}
                </span>
              </Button>
            ) : (
              <span>{option.label}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ErrorCardView({ card }: { card: ErrorCard }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className={`${surface} border-warning-text/40`} data-card="error" role="note">
      <CardHeading id={titleId} demo={card.demo}>
        {m.cards.error}
      </CardHeading>
      <p className="text-[15px] text-ink">{card.message}</p>
      {card.recoverable ? <Link href={card.recoverable.href}>{card.recoverable.label}</Link> : null}
      {card.controls.length > 0 ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {card.controls.map((control) => (
            <li key={control.href}>
              <Link href={control.href}>{control.label}</Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function RecordLinkCardView({ card }: { card: RecordLinkCard }) {
  return (
    <section aria-label={card.label} className={surface} data-card="record_link">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={card.href} className="text-base font-semibold">
          {card.label}
        </Link>
        {card.demo ? <DemoBadge label={m.demo} title={m.demoHint} /> : null}
      </div>
      {card.detail ? <p className="text-sm text-ink-muted">{card.detail}</p> : null}
    </section>
  );
}

export function ReceiptCardView({ card }: { card: ReceiptCard }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className={`${surface} bg-sage`} data-card="receipt">
      <CardHeading id={titleId} demo={card.demo}>
        {card.title}
      </CardHeading>
      {card.detail ? <p className="text-sm text-ink">{card.detail}</p> : null}
      {card.link ? <Link href={card.link.href}>{card.link.label}</Link> : null}
    </section>
  );
}

export function AssistantCardView({ card, onChoose, isBusy }: CardProps) {
  switch (card.kind) {
    case "quote_draft":
      return <QuoteDraftCardView card={card} />;
    case "clarification":
      return <ClarificationCardView card={card} onChoose={onChoose} isBusy={isBusy} />;
    case "error":
      return <ErrorCardView card={card} />;
    case "record_link":
      return <RecordLinkCardView card={card} />;
    case "receipt":
      return <ReceiptCardView card={card} />;
  }
}
