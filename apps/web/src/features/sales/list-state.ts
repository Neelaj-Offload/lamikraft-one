/**
 * URL search params <-> list state for the sales lists. Plain functions (no "use client"), so the server
 * pages can read their search params with them and the client lists can build links with them.
 */

import { QUOTES_PAGE_SIZE } from "./api";
import { QUOTE_STATUSES, type QuoteStatus } from "./types";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export interface QuoteListState {
  q: string;
  status: QuoteStatus | null;
  scope: "mine" | "all";
  offset: number;
}


/** URL → list state; anything unknown falls back to the default, never forwarded raw. */
export function quoteListStateFrom(search: Search): QuoteListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = QUOTE_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const scope = first(search.scope) === "all" ? "all" : "mine";
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % QUOTES_PAGE_SIZE) : 0;
  return { q, status, scope, offset };
}

export function quoteListHref(state: Partial<QuoteListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.scope === "all") query.set("scope", "all");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/quotes?${search}` : "/sales/quotes";
}

export const ENQUIRY_STATUSES = ["received", "assigned", "quoted", "closed"] as const;
type EnquiryStatus = (typeof ENQUIRY_STATUSES)[number];

export interface EnquiryListState {
  q: string;
  status: EnquiryStatus | null;
  offset: number;
}


export function enquiryListStateFrom(search: Search): EnquiryListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = ENQUIRY_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % QUOTES_PAGE_SIZE) : 0;
  return { q, status, offset };
}

export function enquiryListHref(state: Partial<EnquiryListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/enquiries?${search}` : "/sales/enquiries";
}

export type MessageFilter = "received" | "replied" | "all";

export interface MessageListState {
  status: MessageFilter;
  offset: number;
}


/** Waiting for a reply is the default view. */
export function messageListStateFrom(search: Search): MessageListState {
  const raw = first(search.status);
  const status: MessageFilter = raw === "replied" || raw === "all" ? raw : "received";
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % QUOTES_PAGE_SIZE) : 0;
  return { status, offset };
}

export function messageListHref(state: Partial<MessageListState>): string {
  const query = new URLSearchParams();
  if (state.status && state.status !== "received") query.set("status", state.status);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/customer-messages?${search}` : "/sales/customer-messages";
}
