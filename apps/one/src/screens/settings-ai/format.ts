/**
 * Words for the AI figures. Counts are integers from the server; cost is the server's estimate as
 * a decimal string and is only ever formatted, never computed here.
 */

import { formatCount, formatDecimal } from "@/lib/format/money";

export const WORKFLOW_LABEL: Record<string, string> = {
  orchestrate: "Assistant runs",
  route: "Request routing",
  escalate: "Escalation",
  phrase: "Phrasing",
  verify: "Verification",
  vision: "Vision",
};

/** A server key in plain words when there is no label for it: `cache_read` becomes "Cache read". */
export function humanise(key: string): string {
  const words = key.replace(/[_.]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

export const workflowLabel = (key: string) => WORKFLOW_LABEL[key] ?? humanise(key);

/** "≈ USD 0.0123"; demo calls cost nothing; a model without a price row has no estimate, and we say so. */
export function costText(cost: string | null, currency: string, locale: string, provider?: string): string {
  if (provider === "demo") return "No cost in demo";
  if (cost === null) return "No price set";
  return `≈ ${currency} ${formatDecimal(cost, { locale, maxFractionDigits: 4 }) ?? cost}`;
}

export function latencyText(value: number | null, locale: string): string | null {
  return value === null ? null : `${formatCount(value, locale)} ms`;
}

/** "2.5%" from tenths of a percent (see `errorRateTenths`): integer in, text out. */
export function percentText(tenths: number): string {
  return `${Math.trunc(tenths / 10)}.${Math.abs(tenths % 10)}%`;
}
