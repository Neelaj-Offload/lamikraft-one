/**
 * INTERIM hand-written types for `GET /api/v1/briefings/today` (BriefingView) and the briefing
 * item endpoints, derived from docs/design/source/briefing.md §16 (API), §2 (briefings_items
 * columns), §5 (sections, uncertainty flags), §9 (actions) and §11 (fallback). The work lane
 * builds these endpoints in the same wave.
 *
 * INTERIM(api-generate): replace with `components["schemas"]["BriefingView"]` and friends from
 * src/lib/api/schema.d.ts when the briefings module merges; keep field names aligned with it.
 */

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
/** `demo`: the deterministic demo adapter phrased the text; `unavailable`: template wording. */
export type AiStatus = "ok" | "unavailable" | "demo";

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
  /** Navigational actions (open, review, prepare result) carry the canonical URL. */
  href: string | null;
  requires_reason: boolean;
  /** Allowed reason codes for dismiss/reject, from the server's enum. */
  reasons?: ReasonOption[];
}

export interface ProposalRef {
  id: string;
  version: number;
  expires_at: string | null;
}

export interface UncertaintyFlag {
  /** STALE_STOCK_DATA, MISSING_PRICE, FX_UNAVAILABLE, ESTIMATE, DEMO_DATA, ... */
  code: string;
  /** Server-rendered text such as "No warehouse update since yesterday 18:10". */
  label: string | null;
}

export interface BriefingItem {
  /** briefings_items row id (stable within a version). */
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
  /** Snooze overlay for the full list's "Snoozed" filter. */
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
  /** One factual sentence from a backend template; the client never composes it. */
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
  tasks: FallbackTask[];
  last_successful: LastSuccessfulBriefing | null;
}

export interface BriefingAck {
  version: number;
  acknowledged_at: string;
  method: "viewed" | "explicit" | "voice" | "whatsapp";
}

export interface BriefingView {
  briefing_id: string;
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
  /** Null only when `status` is `fallback` (no overview was generated). */
  overview: BriefingOverview | null;
  sections: BriefingSection[];
  items: BriefingItem[];
  /** At most five, in display order. */
  initial_item_ids: string[];
  pending_updates: number;
  last_ack: BriefingAck | null;
  partial_families: PartialFamily[];
  fallback: BriefingFallback | null;
}

/**
 * `GET /api/v1/briefings/items/{issue_id}/explain` (briefing.md §9 "Explain": reason codes as
 * deterministic text, the rule version, the recommendation reason and the sources). The shape
 * is not fixed by §16 yet, so `parseExplanation` reads it defensively.
 */
export interface BriefingExplanation {
  text: string;
  reasons: string[];
  sources: SourceRef[];
  rule_version: string | null;
}
