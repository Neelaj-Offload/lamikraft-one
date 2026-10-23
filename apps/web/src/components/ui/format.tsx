"use client";

import { cx } from "@/lib/cx";
import { formatMoney, formatQuantity, type MoneyValue, type QuantityValue } from "@/lib/format/money";
import {
  formatBusinessDate,
  formatDate,
  formatDayTime,
  formatRelative,
  parseInstant,
} from "@/lib/format/time";
import { useNow, useZone } from "@/lib/session/context";

/**
 * Display components for server values. Numbers use tabular figures so columns align; an
 * invalid or missing value renders an explicit "unavailable" marker, never a made-up zero.
 */

function Unavailable({ label }: { label: string }) {
  return (
    <span className="text-ink-muted">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function Money({
  value,
  maxFractionDigits,
  display,
  className,
}: {
  value: MoneyValue | null | undefined;
  maxFractionDigits?: number;
  display?: "symbol" | "code";
  className?: string;
}) {
  const { locale } = useZone();
  const text = formatMoney(value, { locale, maxFractionDigits, display });
  if (text === null) return <Unavailable label="Amount unavailable" />;
  return <span className={cx("tabular whitespace-nowrap", className)}>{text}</span>;
}

export function Quantity({
  value,
  unitLabel,
  className,
}: {
  value: QuantityValue | null | undefined;
  unitLabel?: string;
  className?: string;
}) {
  const { locale } = useZone();
  const text = formatQuantity(value, { locale, unitLabel });
  if (text === null) return <Unavailable label="Quantity unavailable" />;
  return <span className={cx("tabular whitespace-nowrap", className)}>{text}</span>;
}

/** "Today, 5:00 PM" in the user's zone, inside a <time> carrying the exact instant. */
export function LocalDateTime({ value, className }: { value: string | null | undefined; className?: string }) {
  const zone = useZone();
  const now = useNow();
  const instant = parseInstant(value);
  if (!instant || !value) return <Unavailable label="Time unavailable" />;
  const text = now ? formatDayTime(value, now, zone) : formatDate(value, zone);
  return (
    <time dateTime={value} className={cx("tabular whitespace-nowrap", className)}>
      {text}
    </time>
  );
}

/** A business date (`YYYY-MM-DD`) or the calendar date of an instant in the user's zone. */
export function LocalDate({ value, className }: { value: string | null | undefined; className?: string }) {
  const zone = useZone();
  if (!value) return <Unavailable label="Date unavailable" />;
  const text = /^\d{4}-\d{2}-\d{2}$/.test(value) ? formatBusinessDate(value, zone.locale) : formatDate(value, zone);
  if (!text) return <Unavailable label="Date unavailable" />;
  return (
    <time dateTime={value} className={cx("tabular whitespace-nowrap", className)}>
      {text}
    </time>
  );
}

/** "5 minutes ago" relative to the session clock; the exact time is in the title and dateTime. */
export function RelativeTime({ value, className }: { value: string | null | undefined; className?: string }) {
  const zone = useZone();
  const now = useNow();
  if (!value || !parseInstant(value)) return <Unavailable label="Time unavailable" />;
  const exact = now ? formatDayTime(value, now, zone) : formatDate(value, zone);
  const text = now ? formatRelative(value, now, zone.locale) : exact;
  return (
    <time dateTime={value} title={exact ?? undefined} className={cx("whitespace-nowrap", className)}>
      {text}
    </time>
  );
}
