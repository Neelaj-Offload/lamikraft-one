/**
 * The one adapter between the briefings API (`Wire*` types, briefings/schemas.py) and Today's
 * view model. A payload that misses required fields is reported as an error (with the field
 * names) instead of rendering a half-empty briefing; optional collections default to empty,
 * never to invented content. Every server-supplied path goes through `appLinkFor`: anything
 * that would leave the app is dropped, and resource paths become this app's routes.
 *
 * The `Wire*` types are the generated API types (types.ts); the mapping stays here.
 */

import { appLinkFor } from "@/lib/app-links";
import { briefingMessages as m } from "@/messages/briefing";
import {
  DISMISSAL_REASON_CODES,
  type BriefingAction,
  type BriefingExplanation,
  type BriefingFallback,
  type BriefingItem,
  type BriefingOverview,
  type BriefingPin,
  type BriefingSection,
  type BriefingView,
  type DueKind,
  type PriorityBand,
  type SectionCode,
  type SourceRef,
  type WhatsappSummaryState,
} from "./types";

export class BriefingShapeError extends Error {
  override readonly name = "BriefingShapeError";

  constructor(readonly problems: string[]) {
    super(`The briefing response could not be read (${problems.slice(0, 5).join(", ")}).`);
  }
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" ? value : null);
const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);

export const SECTION_CODES: readonly SectionCode[] = [
  "needs_you_now",
  "plan_for_today",
  "recommendations",
  "changes_since_last_visit",
  "handled_for_you",
  "coming_next",
];
const BANDS: readonly PriorityBand[] = ["P1", "P2", "P3", "P4"];
const DUE: readonly DueKind[] = ["hard", "soft", "none"];

/** `SourceRefView{type,id,version,label,path}`; `path` becomes an in-app link or nothing. */
function sourceRef(value: unknown): SourceRef | null {
  if (!isObject(value)) return null;
  const id = str(value.id);
  const label = str(value.label);
  if (!id || !label) return null;
  return {
    type: str(value.type) ?? "",
    id,
    label,
    href: appLinkFor(value.path ?? value.href),
    updated_at: str(value.updated_at),
  };
}

const DISMISS_REASONS = DISMISSAL_REASON_CODES.map((code) => ({ code, label: m.dismissReasons[code] ?? code }));

/**
 * `ActionView{action,via,path,requires_reason,max_until,proposal_id,proposal_version}`.
 * Approve and reject arrive `via: "approvals"`: a decision is bound to the proposal's content
 * hash, so it is taken on the review page (which the item's `review` action opens), never
 * from a one-line row. They are therefore not offered on Today.
 */
function action(value: unknown): BriefingAction | null {
  if (!isObject(value)) return null;
  const code = str(value.action);
  if (!code) return null;
  const via = str(value.via) ?? "briefings";
  if (via === "approvals") return null;
  return {
    action: code,
    label: str(value.label),
    primary: value.primary === true,
    href: appLinkFor(value.path ?? value.href),
    requires_reason: value.requires_reason === true,
    reasons: code === "dismiss" ? DISMISS_REASONS : [],
    via,
    max_until: str(value.max_until),
  };
}

function overviewFrom(value: unknown): BriefingOverview | null {
  if (!isObject(value)) return null;
  const sentence = str(value.sentence) ?? str(value.text);
  if (sentence === null) return null;
  return {
    greeting: str(value.greeting) ?? "",
    text: sentence,
    text_source: value.text_source === "llm" ? "llm" : "template",
    facts: isObject(value.facts) ? value.facts : {},
  };
}

function item(value: unknown, problems: string[], path: string): BriefingItem | null {
  if (!isObject(value)) {
    problems.push(path);
    return null;
  }
  const issueId = str(value.issue_id);
  const title = str(value.title);
  const section = SECTION_CODES.find((code) => code === value.section);
  // Actions are bound to the fingerprint the person saw, so it is required, never synthesised.
  const fingerprint = str(value.fingerprint);
  if (!issueId || !title || !section || !fingerprint) {
    problems.push(`${path}.${!issueId ? "issue_id" : !title ? "title" : !section ? "section" : "fingerprint"}`);
    return null;
  }
  const rec = isObject(value.recommendation) && str(value.recommendation.label) ? value.recommendation : null;
  const proposal = isObject(value.proposal_ref) && str(value.proposal_ref.id) && int(value.proposal_ref.version) !== null ? value.proposal_ref : null;
  const state = isObject(value.state) ? value.state : {};
  return {
    id: issueId,
    issue_id: issueId,
    section,
    display_ordinal: int(value.ordinal) ?? 0,
    priority_band: BANDS.find((band) => band === value.band) ?? "P4",
    family: str(value.family) ?? "",
    title,
    summary_text: text(value.summary),
    due_label: text(value.due_label),
    reasons: arr(value.reasons).filter((reason): reason is string => typeof reason === "string" && reason.trim() !== ""),
    fact_at: str(value.fact_at),
    due_at: str(value.due_at),
    due_kind: DUE.find((kind) => kind === value.due_kind) ?? "none",
    overdue: value.overdue === true,
    source_refs: arr(value.source_refs).map(sourceRef).filter((ref): ref is SourceRef => ref !== null),
    recommendation: rec
      ? {
          id: str(rec.id) ?? "",
          action_code: str(rec.action_code) ?? "",
          label: str(rec.label)!,
          reason_text: text(rec.reason),
          effect_text: text(rec.effect),
          // Alternatives are action codes the server already filtered to what this person may do.
          alternatives: arr(rec.alternatives)
            .filter((alt): alt is string => typeof alt === "string")
            .map((alt) => m.actions[alt] ?? alt),
          text: text(rec.text),
          text_source: rec.text_source === "llm" ? "llm" : rec.text_source === "template" ? "template" : null,
        }
      : null,
    uncertainty_flags: arr(value.uncertainty_flags).flatMap((flag) =>
      typeof flag === "string"
        ? [{ code: flag, label: m.uncertainty[flag] ?? null }]
        : isObject(flag) && str(flag.code)
          ? [{ code: str(flag.code)!, label: str(flag.label) }]
          : [],
    ),
    allowed_actions: arr(value.allowed_actions).map(action).filter((a): a is BriefingAction => a !== null),
    proposal_ref: proposal ? { id: str(proposal.id)!, version: int(proposal.version)!, expires_at: str(proposal.expires_at) } : null,
    member_count: int(value.member_count) ?? 1,
    change_kind: value.change_kind === "new" || value.change_kind === "changed" ? value.change_kind : "unchanged",
    is_reminder: value.is_reminder === true,
    fingerprint,
    on_behalf_of: null,
    snoozed_until: str(state.snoozed_until),
  };
}

function items(value: unknown, problems: string[], path: string): BriefingItem[] {
  return arr(value).flatMap((entry, index) => {
    const parsed = item(entry, problems, `${path}[${index}]`);
    return parsed ? [parsed] : [];
  });
}

/** `FallbackView{error_code,failed_at,tasks: InboxItem[],last_successful}`. */
function fallback(value: unknown, problems: string[]): BriefingFallback | null {
  if (!isObject(value)) return null;
  const failedAt = str(value.failed_at);
  if (!failedAt) {
    problems.push("fallback_detail.failed_at");
    return null;
  }
  const last = isObject(value.last_successful) ? value.last_successful : null;
  return {
    error_at: failedAt,
    error_code: str(value.error_code) ?? "",
    tasks: arr(value.tasks).flatMap((task) => {
      if (!isObject(task) || !str(task.id) || !str(task.title)) return [];
      return [
        {
          id: str(task.id)!,
          title: str(task.title)!,
          due_at: str(task.due_at),
          due_kind: DUE.find((kind) => kind === task.due_kind) ?? "none",
          overdue: task.overdue === true,
          source: arr(task.source_refs).map(sourceRef).find((ref): ref is SourceRef => ref !== null) ?? null,
        },
      ];
    }),
    last_successful:
      last && int(last.version) !== null && str(last.generated_at)
        ? {
            version: int(last.version)!,
            generated_at: str(last.generated_at)!,
            data_as_of: str(last.data_as_of) ?? str(last.generated_at)!,
            // briefing.md §11: omitted when permissions changed since it was generated.
            overview: overviewFrom(last.overview),
            items: items(last.items, problems, "fallback_detail.last_successful.items"),
          }
        : null,
  };
}

export function parseBriefingView(raw: unknown): BriefingView {
  const problems: string[] = [];
  if (!isObject(raw)) throw new BriefingShapeError(["<body>"]);
  const status = raw.status === "fallback" ? "fallback" : "ready";
  // briefing.md §11: an engine failure answers 200 with status=fallback and writes no version,
  // so version, sections and items are required only for a ready briefing. The overview may be
  // withheld from a ready briefing too (permissions changed since it was generated).
  if (status === "ready") {
    if (int(raw.version) === null) problems.push("version");
    if (!Array.isArray(raw.sections)) problems.push("sections");
    if (!Array.isArray(raw.items)) problems.push("items");
  }
  if (!str(raw.work_date)) problems.push("work_date");

  const parsedItems = items(raw.items, problems, "items");
  const seen = new Set<SectionCode>();
  const sections: BriefingSection[] = arr(raw.sections).flatMap((entry) => {
    if (!isObject(entry)) return [];
    const code = SECTION_CODES.find((candidate) => candidate === entry.code);
    if (!code || seen.has(code)) return [];
    seen.add(code);
    const ids = arr(entry.issue_ids ?? entry.item_ids).filter((id): id is string => typeof id === "string");
    return [{ code, total: int(entry.total) ?? ids.length, item_ids: ids }];
  });
  const parsedFallback = fallback(raw.fallback_detail, problems);
  if (status === "fallback" && !parsedFallback) problems.push("fallback_detail");
  const snoozed = items(raw.snoozed, problems, "snoozed");
  if (problems.length > 0) throw new BriefingShapeError(problems);

  // Rows show the model's wording only when it is real (live and validated); Demo and template text keep the label.
  if (raw.ai_status === "ok") {
    for (const entry of [...parsedItems, ...snoozed]) {
      const rec = entry.recommendation;
      if (rec && rec.text_source === "llm" && rec.text) rec.display_text = rec.text;
    }
  }
  const lastAck = isObject(raw.last_ack) && int(raw.last_ack.version) !== null ? raw.last_ack : null;
  const dayType = raw.day_type;
  return {
    briefing_id: str(raw.briefing_id),
    work_date: str(raw.work_date)!,
    day_type: dayType === "non_working" || dayType === "holiday" || dayType === "leave" ? dayType : "working",
    version: int(raw.version),
    status,
    generated_at: str(raw.generated_at) ?? "",
    data_as_of: str(raw.data_as_of) ?? str(raw.generated_at) ?? "",
    ai_status: raw.ai_status === "unavailable" || raw.ai_status === "demo" || raw.ai_status === "ok" ? raw.ai_status : "not_used",
    overview: overviewFrom(raw.overview),
    sections,
    items: parsedItems,
    initial_item_ids: arr(raw.initial_view).filter((id): id is string => typeof id === "string").slice(0, 5),
    pending_updates: int(raw.updates_available) ?? 0,
    latest_version: int(raw.latest_version),
    up_to_date: raw.up_to_date === true,
    snoozed,
    last_ack: lastAck
      ? {
          briefing_id: str(lastAck.briefing_id),
          version: int(lastAck.version)!,
          acknowledged_at: str(lastAck.acknowledged_at) ?? "",
          method:
            lastAck.method === "explicit" || lastAck.method === "voice" || lastAck.method === "whatsapp" ? lastAck.method : "viewed",
        }
      : null,
    partial_families: [],
    fallback: parsedFallback,
    pin: pinFrom(raw.pin),
    whatsapp_summary: summaryFrom(raw.whatsapp_summary),
  };
}

function pinFrom(value: unknown): BriefingPin | null {
  if (!isObject(value) || !str(value.id) || int(value.pinned_version) === null) return null;
  return {
    id: str(value.id)!,
    kind: str(value.kind) ?? "voice",
    pinned_version: int(value.pinned_version)!,
    state: str(value.state) ?? "active",
    pending_updates: int(value.pending_updates) ?? 0,
  };
}

function summaryFrom(value: unknown): WhatsappSummaryState | null {
  if (!isObject(value) || (value.outcome !== "queued" && value.outcome !== "skipped") || !str(value.at)) return null;
  return {
    outcome: value.outcome,
    reason: str(value.reason),
    kind: str(value.kind),
    simulated: value.simulated === true,
    at: str(value.at)!,
    acknowledged_at: str(value.acknowledged_at),
    ack_channel: str(value.ack_channel),
  };
}

/** A reason as text: plain strings, or `{text|label|reason|code}` objects (`ExplainView.reasons`). */
function reasonText(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (!isObject(value)) return null;
  for (const key of ["text", "label", "reason", "reason_text", "code"] as const) {
    const found = str(value[key])?.trim();
    if (found) return found;
  }
  return null;
}

/**
 * `ExplainView` (the `explain` action's `explanation`, or the view itself). The text is
 * required; reasons are coerced to text, sources keep only in-app links, and anything else is
 * dropped, so an unexpected shape shows the dialog's error state instead of breaking the page.
 */
export function parseExplanation(raw: unknown): BriefingExplanation {
  const body = isObject(raw) && "explanation" in raw ? raw.explanation : raw;
  if (!isObject(body)) throw new BriefingShapeError(["explanation"]);
  const explanation = str(body.text)?.trim();
  if (!explanation) throw new BriefingShapeError(["explanation.text"]);
  const reasons = [...new Set(arr(body.reasons).map(reasonText).filter((reason): reason is string => reason !== null))];
  return {
    text: explanation,
    reasons,
    sources: arr(body.sources).map(sourceRef).filter((ref): ref is SourceRef => ref !== null),
    rule_version: str(body.rule_version),
  };
}

/** One `ItemView` (the item page, `GET /briefings/items/{issue_id}`), with the same checks as the list. */
export function parseBriefingItem(raw: unknown): BriefingItem {
  const problems: string[] = [];
  const parsed = item(raw, problems, "item");
  if (!parsed || problems.length > 0) throw new BriefingShapeError(problems.length > 0 ? problems : ["item"]);
  return parsed;
}
