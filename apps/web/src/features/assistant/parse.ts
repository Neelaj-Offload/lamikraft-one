/**
 * The single adapter between the agents API and the composer (see types.ts for the interim
 * contract). Unknown card kinds and malformed cards are dropped, figures stay DecimalStr
 * strings, and every link must stay inside the app.
 */

import { appLinkFor } from "@/lib/app-links";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import type {
  AgentRun,
  AssistantCard,
  CardLink,
  CardMoney,
  ClarificationOption,
  QuoteDraftCardLine,
  RunStep,
} from "./types";

export class AssistantShapeError extends Error {
  override readonly name = "AssistantShapeError";
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value.trim() !== "" ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);

/** Card kinds accept the server's class names (`QuoteDraftCard`) or snake case (`quote_draft`). */
const KINDS: Record<string, AssistantCard["kind"]> = {
  quotedraftcard: "quote_draft",
  quote_draft: "quote_draft",
  clarificationcard: "clarification",
  clarification: "clarification",
  errorcard: "error",
  error: "error",
  recordlinkcard: "record_link",
  record_link: "record_link",
  receiptcard: "receipt",
  receipt: "receipt",
};

export function cardKind(raw: unknown): AssistantCard["kind"] | null {
  const kind = str(raw);
  return kind ? (KINDS[kind.toLowerCase()] ?? null) : null;
}

/** Money as `{amount, currency}`, or a DecimalStr plus a currency from the card. */
export function cardMoney(value: unknown, currency: string | null): CardMoney | null {
  if (isObject(value) && isDecimalStr(value.amount) && str(value.currency)) {
    return { amount: value.amount, currency: str(value.currency)! };
  }
  if (isDecimalStr(value) && currency) return { amount: value, currency };
  return null;
}

function link(value: unknown, fallbackLabel: string): CardLink | null {
  if (!isObject(value)) return null;
  const href = appLinkFor(value.path ?? value.href);
  return href ? { label: str(value.label) ?? fallbackLabel, href } : null;
}

function quoteLine(value: unknown, currency: string | null, index: number): QuoteDraftCardLine | null {
  if (!isObject(value)) return null;
  const quantity = value.quantity;
  if (!isDecimalStr(quantity)) return null;
  const product = isObject(value.product) ? value.product : value;
  const label =
    str(value.label) ?? str(value.description) ?? str(product.product_name) ?? str(product.name) ?? str(value.product_key) ?? "";
  return {
    line_no: int(value.line_no) ?? index + 1,
    label,
    product_key: str(value.product_key) ?? str(product.product_key),
    quantity,
    unit_code: str(value.unit_code) ?? str(value.uom) ?? "",
    unit_price: cardMoney(value.unit_price, currency),
    line_total: cardMoney(value.line_total, currency),
  };
}

function quoteDraft(raw: Json, demo: boolean): AssistantCard | null {
  const quote = isObject(raw.quote) ? raw.quote : null;
  const quoteId = str(raw.quote_id) ?? (quote ? str(quote.id) : null);
  const number = str(raw.quote_number) ?? (quote ? str(quote.quote_number) : null);
  if (!quoteId || !number) return null;
  const totals = isObject(raw.totals) ? raw.totals : raw;
  const currency = str(raw.currency) ?? str(totals.currency);
  const party = isObject(raw.party) ? raw.party : null;
  const base = `/sales/quotes/${encodeURIComponent(quoteId)}`;
  const recommendation = isObject(raw.recommendation) ? str(raw.recommendation.label) : null;
  const notes = [
    ...arr(raw.notes).filter((note): note is string => typeof note === "string"),
    ...(recommendation ? [recommendation] : []),
    ...(str(totals.threshold_note) ? [str(totals.threshold_note)!] : []),
  ];
  const surcharge = cardMoney(totals.surcharge, currency);
  // A surcharge is shown only when the server applied one.
  const surchargeShown = totals.surcharge_applied !== false && surcharge !== null && compareDecimalStr(surcharge.amount, "0") !== 0;
  return {
    kind: "quote_draft",
    demo,
    quote_id: quoteId,
    quote_number: number,
    status: str(raw.status) ?? "draft",
    party_name: str(raw.party_name) ?? (party ? (str(party.display_name) ?? str(party.name)) : null),
    lines: arr(raw.lines)
      .map((line, index) => quoteLine(line, currency, index))
      .filter((line): line is QuoteDraftCardLine => line !== null),
    subtotal: cardMoney(totals.applicable_subtotal ?? totals.net_subtotal ?? totals.subtotal, currency),
    surcharge: surchargeShown ? surcharge : null,
    grand_total: cardMoney(totals.grand_total, currency),
    notes: [...new Set(notes)],
    open_href: appLinkFor(raw.open_path ?? raw.path) ?? base,
    review_href: appLinkFor(raw.review_path ?? (isObject(raw.links) ? raw.links.review : null)) ?? base,
  };
}

export function parseCard(raw: unknown): AssistantCard | null {
  if (!isObject(raw)) return null;
  const kind = cardKind(raw.kind ?? raw.type);
  if (!kind) return null;
  const demo = raw.demo === true || raw.provider === "demo" || raw.mode === "demo";
  switch (kind) {
    case "quote_draft":
      return quoteDraft(raw, demo);
    case "clarification": {
      const question = str(raw.question) ?? str(raw.text);
      const options = arr(raw.options).flatMap((option, index): ClarificationOption[] => {
        if (!isObject(option)) return [];
        const label = str(option.label) ?? str(option.display_name);
        if (!label) return [];
        return [
          {
            id: str(option.id) ?? str(option.value) ?? `option-${index + 1}`,
            label,
            detail: str(option.detail) ?? str(option.description),
            value: option.action ?? option.value ?? option.id ?? label,
          },
        ];
      });
      if (!question || options.length === 0) return null;
      return { kind, demo, question, options };
    }
    case "error": {
      const message = str(raw.message) ?? str(raw.detail);
      if (!message) return null;
      return {
        kind,
        demo,
        code: str(raw.code) ?? "error",
        message,
        recoverable: link(raw.recoverable_draft ?? raw.draft ?? raw.record, "Open the saved draft"),
      };
    }
    case "record_link": {
      const href = appLinkFor(raw.path ?? raw.href);
      const label = str(raw.label);
      if (!href || !label) return null;
      return { kind, demo, label, detail: str(raw.detail) ?? str(raw.summary), href };
    }
    case "receipt": {
      const title = str(raw.title) ?? str(raw.text) ?? str(raw.label);
      if (!title) return null;
      return { kind, demo, title, detail: str(raw.detail) ?? str(raw.summary), link: link(raw.link ?? raw.record ?? raw, "Open") };
    }
  }
}

function step(value: unknown): RunStep | null {
  if (!isObject(value)) return null;
  const seq = int(value.seq);
  if (seq === null) return null;
  const kind = str(value.kind) ?? "text";
  const output = isObject(value.output) ? value.output : null;
  const cardSource = value.card ?? (kind === "card" ? output : null);
  return {
    seq,
    kind,
    name: str(value.name),
    is_error: value.is_error === true,
    text: kind === "text" ? (str(value.text) ?? (output ? str(output.text) : null) ?? str(value.output)) : null,
    card: cardSource ? parseCard(cardSource) : null,
  };
}

export function parseRun(raw: unknown): AgentRun {
  if (!isObject(raw)) throw new AssistantShapeError("The assistant's run could not be read.");
  const id = str(raw.id) ?? str(raw.run_id);
  const status = str(raw.status);
  if (!id || !status) throw new AssistantShapeError("The assistant's run could not be read (id, status).");
  const steps = arr(raw.steps)
    .map(step)
    .filter((entry): entry is RunStep => entry !== null)
    .sort((a, b) => a.seq - b.seq);
  // Cards may also come as a top-level list: fold them in after the steps.
  const last = steps.at(-1)?.seq ?? 0;
  const extra: RunStep[] = arr(raw.cards)
    .map(parseCard)
    .filter((card): card is AssistantCard => card !== null)
    .map((card, index) => ({ seq: last + index + 1, kind: "card", name: null, is_error: false, text: null, card }));
  return {
    id,
    status,
    error_code: str(raw.error_code),
    tainted: raw.tainted === true,
    steps: extra.length > 0 && !steps.some((entry) => entry.card) ? [...steps, ...extra] : steps,
  };
}

/** `{run_id}` from the 202 of a new turn. */
export function parseTurnAccepted(raw: unknown): string {
  const id = isObject(raw) ? (str(raw.run_id) ?? (isObject(raw.run) ? str(raw.run.id) : null)) : null;
  if (!id) throw new AssistantShapeError("The assistant did not return a run.");
  return id;
}

export function parseConversationId(raw: unknown): string {
  const id = isObject(raw) ? (str(raw.id) ?? str(raw.conversation_id)) : null;
  if (!id) throw new AssistantShapeError("The assistant did not open a conversation.");
  return id;
}

/**
 * Merges a poll result (steps after the last seen seq) into the run on screen: new steps are
 * appended in seq order, repeats are ignored, the status and error follow the server.
 */
export function mergeRun(current: AgentRun | null, update: AgentRun): AgentRun {
  if (!current || current.id !== update.id) return update;
  const known = new Set(current.steps.map((entry) => entry.seq));
  const steps = [...current.steps, ...update.steps.filter((entry) => !known.has(entry.seq))].sort((a, b) => a.seq - b.seq);
  return { ...update, tainted: current.tainted || update.tainted, steps };
}

export function lastSeq(run: AgentRun | null): number {
  return run?.steps.at(-1)?.seq ?? 0;
}
