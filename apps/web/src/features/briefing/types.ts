/**
 * Today's data, in two layers:
 *
 * 1. `Wire*` types: the generated briefings API types (`components["schemas"]` from
 *    src/lib/api/schema.d.ts: `BriefingView`, `ItemView`, `ActionView`, `ExplainView`,
 *    `ItemActionRequest`, `ItemActionResult`; `InboxItem` for the fallback task list).
 * 2. The view model the Today components render (`BriefingView`, `BriefingItem`, ...).
 *    `parse.ts` is the single adapter between the two; nothing else reads the wire shape.
 */

import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------------------------
// Wire (briefings/schemas.py)

export type WirePersonRef = Schemas["PersonRef"];

export type WireSourceRef = Schemas["SourceRefView"];

export type WireRecommendation = Schemas["RecommendationView"];

export type WireAction = Schemas["ActionView"];

export type WireItemState = Schemas["ItemStateView"];

export type WireMoney = Schemas["Money"];

export type WireItem = Schemas["ItemView"];

export type WireSection = Schemas["SectionView"];

export type WireOverview = Schemas["OverviewView"];

export type WireAck = Schemas["AckView"];

export type WireInboxItem = Schemas["InboxItem"];

export type WireLastSuccessful = Schemas["LastSuccessfulView"];

export type WireFallback = Schemas["FallbackView"];

export type WireBriefingView = Schemas["BriefingView"];

/** tasks/schemas.py `DismissalReasonCode`: the only reasons a dismissal accepts. */
export const DISMISSAL_REASON_CODES = [
  "handled_outside_system",
  "not_applicable",
  "duplicate",
  "customer_withdrew",
  "no_action_needed",
] as const;
export type DismissalReasonCode = (typeof DISMISSAL_REASON_CODES)[number];

export type WireItemActionRequest = Schemas["ItemActionRequest"];

export type WireExplain = Schemas["ExplainView"];

export type WireItemActionResult = Schemas["ItemActionResult"];

export type WireAcknowledgeRequest = Schemas["AcknowledgeRequest"];

// ---------------------------------------------------------------------------------------------
// View model (what the Today components render)

export type SectionCode =
  | "needs_you_now"
  | "plan_for_today"
  | "recommendations"
  | "changes_since_last_visit"
  | "handled_for_you"
  | "coming_next";

export type DayType = "working" | "non_working" | "holiday" | "leave";
export type BriefingStatus = "ready" | "fallback";
export type PriorityBand = "P1" | "P2" | "P3" | "P4";
export type DueKind = "hard" | "soft" | "none";
export type ChangeKind = "new" | "changed" | "unchanged";
/**
 * `not_used`: the deterministic template wrote the text by design (Slice 1, the only value the
 * server sends today); `demo`: the Demo adapter phrased it; `unavailable`: the model was down
 * and the template text stands in ("Standard wording").
 */
export type AiStatus = "not_used" | "ok" | "unavailable" | "demo";

export interface PersonRef {
  id: string;
  display_name: string;
}

/** A record the item is about or cites as evidence; `href` is its canonical screen. */
export interface SourceRef {
  type: string;
  id: string;
  /** "Quote LK-QT-2026-0041" */
  label: string;
  href: string | null;
  updated_at: string | null;
}

export interface Recommendation {
  id: string;
  action_code: string;
  /** "Review the current terms before sending." */
  label: string;
  reason_text: string | null;
  /** Rendered only from facts, e.g. "Unblocks WO-2026-0031, afternoon shift". */
  effect_text: string | null;
  alternatives: string[];
}

export type BriefingActionCode =
  | "open"
  | "prepare"
  | "assign"
  | "review"
  | "approve"
  | "reject"
  | "snooze"
  | "mark_handled"
  | "dismiss"
  | "explain";

/** Where a command is carried out: the briefings endpoint, or the approvals review page. */
export type ActionVia = "briefings" | "approvals";

export interface ReasonOption {
  code: string;
  label: string;
}

/** One server-decided action (briefing.md §9). Only these are ever offered for the item. */
export interface BriefingAction {
  action: BriefingActionCode | (string & {});
  /** Server label such as "Review quote"; the web falls back to its own copy. */
  label: string | null;
  primary: boolean;
  /** Navigational actions (open, review, assign) carry the in-app URL. */
  href: string | null;
  requires_reason: boolean;
  /** Allowed reason codes for dismiss, from the server's enum. */
  reasons?: ReasonOption[];
  via: ActionVia | (string & {});
  /** Snooze: the latest instant the server accepts (bounded by the deadline). */
  max_until: string | null;
}

export interface ProposalRef {
  id: string;
  version: number;
  expires_at: string | null;
}

export interface UncertaintyFlag {
  /** STALE_STOCK_DATA, MISSING_PRICE, FX_UNAVAILABLE, ESTIMATE, DEMO_DATA, ... */
  code: string;
  /** Server-rendered text, or the web's copy for the code. */
  label: string | null;
}

export interface BriefingItem {
  /** The issue id: a briefing lists each issue once, so it identifies the row too. */
  id: string;
  /** Stable across versions; actions address the issue. */
  issue_id: string;
  section: SectionCode;
  display_ordinal: number;
  priority_band: PriorityBand;
  /** Rule family, e.g. "common.approvals", "sales.quote_expiry". */
  family: string;
  title: string;
  /** Template text with the facts, e.g. "240 oak trays. EUR 5,760. Ready for review." */
  summary_text: string | null;
  /** Server-rendered deadline text in the user's zone ("Due today, 6:30 pm"), when it sent one. */
  due_label: string | null;
  /** Rule reasons as text ("Expires today"), from the priority engine. */
  reasons: string[];
  fact_at: string | null;
  due_at: string | null;
  due_kind: DueKind;
  overdue: boolean;
  source_refs: SourceRef[];
  recommendation: Recommendation | null;
  uncertainty_flags: UncertaintyFlag[];
  allowed_actions: BriefingAction[];
  proposal_ref: ProposalRef | null;
  member_count: number;
  change_kind: ChangeKind;
  is_reminder: boolean;
  fingerprint: string;
  /** Delegated work: "For Ravi". */
  on_behalf_of: PersonRef | null;
  /** Snooze overlay for the full list's "Snoozed" group. */
  snoozed_until: string | null;
}

export interface BriefingSection {
  code: SectionCode;
  total: number;
  item_ids: string[];
}

export interface BriefingOverview {
  /** Server-computed in the user's zone: "Good morning, Meera." */
  greeting: string;
  /** One factual sentence from a backend template (`sentence`); the client never composes it. */
  text: string;
  text_source: "template" | "llm";
  facts: Record<string, unknown>;
}

export interface PartialFamily {
  family: string;
  /** "Shortage checks" */
  label: string;
  since: string | null;
}

export interface FallbackTask {
  id: string;
  title: string;
  due_at: string | null;
  due_kind: DueKind;
  overdue: boolean;
  source: SourceRef | null;
}

export interface LastSuccessfulBriefing {
  version: number;
  generated_at: string;
  data_as_of: string;
  /** Omitted when permissions changed since it was generated. */
  overview: BriefingOverview | null;
  items: BriefingItem[];
}

export interface BriefingFallback {
  /** When generation failed. */
  error_at: string;
  error_code: string;
  tasks: FallbackTask[];
  last_successful: LastSuccessfulBriefing | null;
}

export interface BriefingAck {
  briefing_id: string | null;
  version: number;
  acknowledged_at: string;
  method: "viewed" | "explicit" | "voice" | "whatsapp";
}

export interface BriefingView {
  /** Null only for a fallback written before any briefing existed today. */
  briefing_id: string | null;
  work_date: string;
  day_type: DayType;
  /**
   * Null only when `status` is `fallback`: generation failed and no version was written
   * (briefing.md §11); the page then works from `fallback` alone.
   */
  version: number | null;
  status: BriefingStatus;
  generated_at: string;
  data_as_of: string;
  ai_status: AiStatus;
  /** Null when `status` is `fallback`, or when permissions changed since it was generated. */
  overview: BriefingOverview | null;
  sections: BriefingSection[];
  items: BriefingItem[];
  /** At most five, in display order. */
  initial_item_ids: string[];
  pending_updates: number;
  /** The newest version of this briefing on the server (the one on screen may be older). */
  latest_version: number | null;
  /** The person acknowledged the latest version (nothing new since "Mark as seen"). */
  up_to_date: boolean;
  /** Items the person snoozed; shown in the full list only. */
  snoozed: BriefingItem[];
  last_ack: BriefingAck | null;
  partial_families: PartialFamily[];
  fallback: BriefingFallback | null;
}

/** The `explain` action's `explanation`: deterministic text, reasons, rule version, sources. */
export interface BriefingExplanation {
  text: string;
  reasons: string[];
  sources: SourceRef[];
  rule_version: string | null;
}
