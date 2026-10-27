/**
 * Today's data, in two layers:
 *
 * 1. `Wire*` types: the briefings API exactly as the work lane's Pydantic models define it
 *    (backend/app/modules/briefings/schemas.py `BriefingView`, `ItemView`, `ActionView`,
 *    `ExplainView`, `ItemActionRequest`, `ItemActionResult`; tasks/schemas.py `InboxItem` for
 *    the fallback task list). INTERIM(api-generate): replace them with
 *    `components["schemas"][...]` from src/lib/api/schema.d.ts once the module merges.
 * 2. The view model the Today components render (`BriefingView`, `BriefingItem`, ...).
 *    `parse.ts` is the single adapter between the two; nothing else reads the wire shape.
 */

// ---------------------------------------------------------------------------------------------
// Wire (briefings/schemas.py)

export interface WirePersonRef {
  user_id: string;
  name: string;
}

export interface WireSourceRef {
  type: string;
  id: string;
  version: number | null;
  label: string;
  path: string | null;
}

export interface WireRecommendation {
  id: string | null;
  action_code: string;
  label: string;
  reason_code: string;
  reason: string;
  effect_code: string;
  effect: string;
  alternatives: string[];
}

export interface WireAction {
  action: string;
  /** "briefings" (POST items/{issue}/actions) or "approvals" (decided on the review page). */
  via: string;
  path: string | null;
  requires_reason: boolean;
  max_until: string | null;
  proposal_id: string | null;
  proposal_version: number | null;
}

export interface WireItemState {
  acknowledged: boolean;
  snoozed_until: string | null;
  handled: boolean;
  dismissed: boolean;
  task_states: Record<string, string>;
  issue_state: string | null;
  blocked_now: boolean | null;
}

export interface WireMoney {
  amount: string;
  currency: string;
}

export interface WireItem {
  issue_id: string;
  ordinal: number;
  section: string;
  band: string;
  score: number;
  reason_codes: string[];
  reasons: string[];
  kind: string;
  family: string;
  title: string;
  summary: string;
  facts: Record<string, unknown>;
  money: WireMoney[];
  source_refs: WireSourceRef[];
  fact_at: string;
  owner: WirePersonRef | null;
  assignee: WirePersonRef | null;
  due_at: string | null;
  due_local: string | null;
  due_label: string | null;
  due_kind: string;
  overdue: boolean;
  recommendation: WireRecommendation | null;
  uncertainty_flags: string[];
  allowed_actions: WireAction[];
  proposal_ref: Record<string, unknown> | null;
  member_count: number;
  members: Record<string, unknown>[];
  fingerprint: string;
  change_kind: string;
  changed_since_last_visit: boolean;
  is_reminder: boolean;
  blocked: boolean;
  blocked_by: Record<string, unknown>[];
  state: WireItemState;
}

export interface WireSection {
  code: string;
  title: string;
  total: number;
  issue_ids: string[];
}

export interface WireOverview {
  greeting: string;
  sentence: string;
  text_source: "template";
  template_code: string;
  facts: Record<string, boolean | number>;
}

export interface WireAck {
  briefing_id: string;
  version: number;
  method: string;
  channel: string;
  acknowledged_at: string;
  accepted: boolean;
}

/** tasks/schemas.py `InboxItem` (the fallback's current tasks). */
export interface WireInboxItem {
  id: string;
  issue_id: string;
  kind: string;
  family: string;
  tab: string;
  title: string;
  state: string;
  due_at: string | null;
  due_kind: string;
  overdue: boolean;
  blocked: boolean;
  owner_user_id: string | null;
  assignee_user_id: string | null;
  queue_code: string | null;
  snoozed_until: string | null;
  source_refs: WireSourceRef[];
  capabilities: Record<string, { allowed: boolean; reason_code: string | null }>;
  version: number;
}

export interface WireLastSuccessful {
  briefing_id: string;
  work_date: string;
  version: number;
  generated_at: string;
  data_as_of: string;
  overview: WireOverview | null;
  items: WireItem[];
}

export interface WireFallback {
  error_code: string;
  failed_at: string;
  tasks: WireInboxItem[];
  last_successful: WireLastSuccessful | null;
}

export interface WireBriefingView {
  briefing_id: string | null;
  work_date: string;
  day_type: string;
  time_zone: string;
  status: "ready" | "fallback";
  fallback: boolean;
  ai_status: "not_used";
  version: number | null;
  latest_version: number | null;
  generated_at: string | null;
  data_as_of: string | null;
  trigger: string | null;
  first_opened_at: string | null;
  overview: WireOverview | null;
  sections: WireSection[];
  items: WireItem[];
  initial_view: string[];
  snoozed: WireItem[];
  updates_available: number;
  up_to_date: boolean;
  last_ack: WireAck | null;
  pin: Record<string, unknown> | null;
  fallback_detail: WireFallback | null;
}

/** tasks/schemas.py `DismissalReasonCode`: the only reasons a dismissal accepts. */
export const DISMISSAL_REASON_CODES = [
  "handled_outside_system",
  "not_applicable",
  "duplicate",
  "customer_withdrew",
  "no_action_needed",
] as const;
export type DismissalReasonCode = (typeof DISMISSAL_REASON_CODES)[number];

/** `POST /api/v1/briefings/items/{issue_id}/actions` body (`ItemActionRequest`, extra="forbid"). */
export interface WireItemActionRequest {
  action: "snooze" | "unsnooze" | "mark_handled" | "dismiss" | "explain";
  until?: string;
  reason_code?: DismissalReasonCode;
  note?: string;
  briefing_version?: number;
  item_fingerprint?: string;
}

export interface WireExplain {
  issue_id: string;
  band: string;
  score: number;
  rule_version: string;
  reasons: Record<string, unknown>[];
  recommendation: WireRecommendation | null;
  sources: WireSourceRef[];
  text: string;
}

export interface WireItemActionResult {
  action: string;
  issue_id: string;
  outcome: string;
  snoozed_until: string | null;
  max_until: string | null;
  task_ids: string[];
  explanation: WireExplain | null;
}

/** `POST /api/v1/briefings/{briefing_id}/acknowledge` body (`AcknowledgeRequest`). */
export interface WireAcknowledgeRequest {
  version: number;
  method: "viewed" | "explicit" | "voice" | "whatsapp";
}

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
