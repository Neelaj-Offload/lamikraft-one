/**
 * Money and quantity formatting from server DecimalStr values.
 *
 * `Intl.NumberFormat#format` accepts a decimal string and formats it exactly (ECMA-402
 * "Intl.NumberFormat v3"), so `5760.0000` becomes `€5,760.00` without passing through a
 * float. Values are never summed, converted or rounded for anything but display.
 */

import { isDecimalStr } from "./decimal";

export const CURRENCIES = ["INR", "EUR", "USD", "GBP"] as const;
export type CurrencyCode = (typeof CURRENCIES)[number];

export interface MoneyValue {
  amount: string;
  currency: string;
}

export interface QuantityValue {
  value: string;
  uom: string;
}

export const DEFAULT_LOCALE = "en-IN";

type DecimalFormatter = { format(value: string): string };

const formatterCache = new Map<string, DecimalFormatter>();

function formatter(locale: string, options: Intl.NumberFormatOptions): DecimalFormatter {
  const key = `${locale}|${JSON.stringify(options)}`;
  let cached = formatterCache.get(key);
  if (!cached) {
    // The string overload is ES2023 Intl; TypeScript's lib still types it as number | bigint.
    cached = new Intl.NumberFormat(locale, options) as unknown as DecimalFormatter;
    formatterCache.set(key, cached);
  }
  return cached;
}

export interface MoneyFormatOptions {
  locale?: string;
  /** Unit prices keep up to 4 places (EUR 24.0000 → €24.00, 9.4950 → €9.495). */
  maxFractionDigits?: number;
  /** "code" shows `EUR 5,760.00` where symbols would be ambiguous. */
  display?: "symbol" | "code";
}

/** Returns null when the value is not a valid money object, so callers render "unavailable". */
export function formatMoney(money: MoneyValue | null | undefined, options: MoneyFormatOptions = {}): string | null {
  if (!money || !isDecimalStr(money.amount) || !/^[A-Z]{3}$/.test(money.currency)) return null;
  const minor = new Intl.NumberFormat("en", { style: "currency", currency: money.currency }).resolvedOptions()
    .minimumFractionDigits ?? 2;
  return formatter(options.locale ?? DEFAULT_LOCALE, {
    style: "currency",
    currency: money.currency,
    currencyDisplay: options.display ?? "symbol",
    minimumFractionDigits: minor,
    maximumFractionDigits: Math.max(minor, options.maxFractionDigits ?? minor),
    roundingMode: "halfExpand",
  } as Intl.NumberFormatOptions).format(money.amount);
}

export interface QuantityFormatOptions {
  locale?: string;
  /** Overrides the unit label, e.g. a pluralised display name from the UOM master. */
  unitLabel?: string;
}

/** `{value: "240", uom: "pcs"}` → `240 pcs`; up to 6 fraction digits, trailing zeros dropped. */
export function formatQuantity(quantity: QuantityValue | null | undefined, options: QuantityFormatOptions = {}): string | null {
  if (!quantity || !isDecimalStr(quantity.value) || !quantity.uom) return null;
  const number = formatter(options.locale ?? DEFAULT_LOCALE, {
    maximumFractionDigits: 6,
    roundingMode: "halfExpand",
  } as Intl.NumberFormatOptions).format(quantity.value);
  return `${number} ${options.unitLabel ?? quantity.uom}`;
}

/** Plain decimal (percentages, dimensions) with grouping; null when invalid. */
export function formatDecimal(value: string | null | undefined, options: { locale?: string; maxFractionDigits?: number } = {}): string | null {
  if (!isDecimalStr(value)) return null;
  return formatter(options.locale ?? DEFAULT_LOCALE, {
    maximumFractionDigits: options.maxFractionDigits ?? 6,
    roundingMode: "halfExpand",
  } as Intl.NumberFormatOptions).format(value);
}

/** Integer counts (Inbox badges, "N updates"); counts are integers from the server, never money. */
export function formatCount(count: number, locale: string = DEFAULT_LOCALE): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(count);
}
