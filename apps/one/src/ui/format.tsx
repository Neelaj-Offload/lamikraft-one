"use client";

import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { isDecimalStr } from "@/lib/format/decimal";
import { formatMoney, formatQuantity, type MoneyValue, type QuantityValue } from "@/lib/format/money";
import { formatBusinessDate, formatDate, formatDayTime, formatRelative, parseInstant } from "@/lib/format/time";
import { useNow, useZone } from "@/lib/session/context";

/*
 * Display components for server values, in the signed-in user's locale and time zone. Money and
 * quantities arrive as decimal strings and are only ever formatted, never parsed to a float.
 * A missing or malformed value renders the en dash placeholder, never a made-up zero.
 */

/** The placeholder for a value that is not set: an en dash that screen readers hear as "not set". */
export function Dash({ className }: { className?: string }) {
  return (
    <span className={cx("lk-dash", className)} role="img" aria-label="not set">
      –
    </span>
  );
}

const BUSINESS_DATE = /^\d{4}-\d{2}-\d{2}$/;

function compactMoney(value: MoneyValue, locale: string): string | null {
  if (!isDecimalStr(value.amount) || !/^[A-Z]{3}$/.test(value.currency)) return null;
  try {
    // Intl formats a decimal string exactly; TypeScript's lib still types the argument as a number.
    const formatter = new Intl.NumberFormat(locale, {
      style: "currency",
      currency: value.currency,
      notation: "compact",
      maximumFractionDigits: 1,
    }) as unknown as { format(amount: string): string };
    return formatter.format(value.amount);
  } catch {
    return null;
  }
}

export interface MoneyProps {
  value: MoneyValue | null | undefined;
  /** Abbreviates large amounts for tiles and chart labels; the exact amount stays in the tooltip. */
  compact?: boolean;
  /** Shows more decimals than the currency's own, for unit costs and cost roll-ups ("₹12.3456"). */
  maxFractionDigits?: number;
  className?: string;
}

export function Money({ value, compact = false, maxFractionDigits, className }: MoneyProps) {
  const { locale } = useZone();
  const exact = formatMoney(value, { locale, maxFractionDigits });
  if (!value || exact === null) return <Dash className={className} />;
  const short = compact ? compactMoney(value, locale) : null;
  return (
    <span className={cx("lk-tnum whitespace-nowrap", className)} title={short && short !== exact ? exact : undefined}>
      {short ?? exact}
    </span>
  );
}

export interface QtyProps {
  /** `{ value: "240", uom: "pcs" }`, the API's quantity shape. */
  value: QuantityValue | null | undefined;
  /** Overrides the unit text, for a display name from the unit master. */
  unitLabel?: string;
  className?: string;
}

export function Qty({ value, unitLabel, className }: QtyProps) {
  const { locale } = useZone();
  const text = formatQuantity(value, { locale, unitLabel });
  if (text === null) return <Dash className={className} />;
  return <span className={cx("lk-tnum whitespace-nowrap", className)}>{text}</span>;
}

export interface DateTextProps {
  /** An RFC 3339 instant, or a business date `YYYY-MM-DD`. */
  value: string | null | undefined;
  /**
   * `date`: "12 Oct 2026". `dayTime`: "Today, 5:00 PM". `relative`: "5 minutes ago" (the exact time
   * is in the tooltip). `business`: a calendar date with no zone shift.
   */
  style?: "date" | "dayTime" | "relative" | "business";
  className?: string;
}

export function DateText({ value, style = "date", className }: DateTextProps) {
  const zone = useZone();
  const now = useNow();
  if (!value) return <Dash className={className} />;

  let text: string | null;
  let exact: string | null = null;
  if (BUSINESS_DATE.test(value)) {
    // A business date has no time of day: every style shows the calendar date as written.
    text = formatBusinessDate(value, zone.locale);
  } else if (style === "business" || !parseInstant(value)) {
    text = null;
  } else if (style === "date") {
    text = formatDate(value, zone);
  } else {
    exact = now ? formatDayTime(value, now, zone) : formatDate(value, zone);
    text = style === "relative" && now ? formatRelative(value, now, zone.locale) : exact;
  }
  if (text === null) return <Dash className={className} />;

  return (
    <time
      dateTime={value}
      title={style === "relative" && exact && exact !== text ? exact : undefined}
      className={cx("lk-tnum whitespace-nowrap", className)}
    >
      {text}
    </time>
  );
}

/** Identifiers people copy and compare: SKUs, document numbers, batch codes. */
export function Code({ children, className }: { children: ReactNode; className?: string }) {
  if (children === null || children === undefined || children === "") return <Dash className={className} />;
  return <code className={cx("t-code lk-mono lk-code", className)}>{children}</code>;
}
