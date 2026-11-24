"use client";

import type { ReactNode } from "react";
import type { QuoteDetail, QuotePreview } from "@/features/sales/types";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { cx } from "@/lib/cx";
import { Icon, Money } from "~/ui";

const isZero = (amount: string) => isDecimalStr(amount) && compareDecimalStr(amount, "0") === 0;

interface Row {
  label: string;
  value: ReactNode;
}

/**
 * The quotation's totals as the server computed them (or its preview of an unsaved line edit),
 * on the ink panel: the breakdown in quiet rows, the grand total in stat numerals at the right
 * edge. Nothing here adds or multiplies; every figure is a decimal string, formatted.
 */
export function QuotationTotals({
  quote,
  preview = null,
  size = "lg",
  footer,
  className,
}: {
  quote: Pick<QuoteDetail, "totals" | "currency">;
  /** The server's preview while a line edit is open; replaces the saved figures. */
  preview?: QuotePreview | null;
  size?: "lg" | "xl";
  footer?: ReactNode;
  className?: string;
}) {
  const t = quote.totals;
  const currency = quote.currency;
  const money = (amount: string | null) => <Money value={amount ? { amount, currency } : null} />;
  const rows: Row[] = preview
    ? [
        { label: "Subtotal", value: money(preview.applicable_subtotal) },
        ...(isZero(preview.discount_total) ? [] : [{ label: "Discount", value: money(preview.discount_total) }]),
        ...(preview.surcharge_applied ? [{ label: preview.surcharge_label || "Minimum order surcharge", value: money(preview.surcharge_amount) }] : []),
      ]
    : [
        { label: "Subtotal", value: <Money value={t.applicable_subtotal} /> },
        ...(isZero(t.discount_total.amount) ? [] : [{ label: "Discount", value: <Money value={t.discount_total} /> }]),
        ...(t.surcharge_applied ? [{ label: t.surcharge_label || "Minimum order surcharge", value: <Money value={t.surcharge} /> }] : []),
      ];
  const grand = preview ? money(preview.grand_total) : <Money value={t.grand_total} />;
  const note = preview ? preview.recommendation : t.threshold_note;
  const complete = preview ? preview.totals_complete : t.totals_complete;

  return (
    <section
      aria-label={preview ? "Totals while you edit" : "Totals"}
      className={cx("lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6", className)}
      data-totals={preview ? "preview" : "saved"}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="t-overline opacity-70">{preview ? "Totals while you edit" : "Totals"}</h2>
        <span className="t-caption lk-tnum opacity-70">
          {currency} · {t.line_count === 1 ? "1 line" : `${t.line_count} lines`}
        </span>
      </div>
      <dl className="flex flex-col gap-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-4">
            <dt className="t-body-sm opacity-70">{row.label}</dt>
            <dd className="t-body lk-tnum text-right">{row.value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 border-t border-on-inverse/20 pt-5">
        <div className="flex flex-col">
          <span className="t-label">Total</span>
          <span className="t-caption opacity-70">{t.tax_label || "Excluding taxes"}</span>
        </div>
        <span className={cx(size === "xl" ? "t-stat-xl" : "t-stat", "ml-auto text-right")}>{grand}</span>
      </div>
      {!complete ? (
        <p className="t-body-sm flex items-start gap-2">
          <Icon name="alert" size={16} className="mt-0.5 flex-none" />
          Some lines have no price yet, so this total is incomplete.
        </p>
      ) : null}
      {note ? <p className="t-body-sm opacity-80">{note}</p> : null}
      {footer}
    </section>
  );
}
