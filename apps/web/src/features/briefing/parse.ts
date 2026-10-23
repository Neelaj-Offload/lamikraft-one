/**
 * Runtime check of `GET /api/v1/briefings/today` against the interim BriefingView type. The
 * endpoint is written by another lane in parallel; a payload that misses required fields is
 * reported as an error (with the field names) instead of rendering a half-empty briefing.
 * Optional collections default to empty, never to invented content.
 */

import type {
  BriefingAction,
  BriefingFallback,
  BriefingItem,
  BriefingSection,
  BriefingView,
  DueKind,
  PriorityBand,
  SectionCode,
  SourceRef,
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
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const SECTIONS: readonly SectionCode[] = [
  "needs_you_now",
  "plan_for_today",
  "recommendations",
  "changes_since_last_visit",
  "handled_for_you",
  "coming_next",
];
const BANDS: readonly PriorityBand[] = ["P1", "P2", "P3", "P4"];
const DUE: readonly DueKind[] = ["hard", "soft", "none"];

function sourceRef(value: unknown): SourceRef | null {
  if (!isObject(value)) return null;
  const id = str(value.id);
  const label = str(value.label);
  if (!id || !label) return null;
  const href = str(value.href);
  return {
    type: str(value.type) ?? "",
    id,
    label,
    // Only in-app absolute paths are linked.
    href: href && href.startsWith("/") && !href.startsWith("//") ? href : null,
    updated_at: str(value.updated_at),
  };
}

function action(value: unknown): BriefingAction | null {
  if (!isObject(value)) return null;
  const code = str(value.action);
  if (!code) return null;
  const href = str(value.href);
  return {
    action: code,
    label: str(value.label),
    primary: value.primary === true,
    href: href && href.startsWith("/") && !href.startsWith("//") ? href : null,
    requires_reason: value.requires_reason === true,
    reasons: arr(value.reasons).flatMap((reason) =>
      isObject(reason) && str(reason.code) && str(reason.label) ? [{ code: str(reason.code)!, label: str(reason.label)! }] : [],
    ),
  };
}

function item(value: unknown, problems: string[], path: string): BriefingItem | null {
  if (!isObject(value)) {
    problems.push(path);
    return null;
  }
  const id = str(value.id);
  const issueId = str(value.issue_id);
  const title = str(value.title);
  const section = SECTIONS.find((code) => code === value.section);
  // Actions are bound to the fingerprint the person saw, so it is required, never synthesised.
  const fingerprint = str(value.fingerprint);
  if (!id || !issueId || !title || !section || !fingerprint) {
    problems.push(`${path}.${!id ? "id" : !issueId ? "issue_id" : !title ? "title" : !section ? "section" : "fingerprint"}`);
    return null;
  }
  const recommendation = isObject(value.recommendation) && str(value.recommendation.label) ? value.recommendation : null;
  const proposal = isObject(value.proposal_ref) && str(value.proposal_ref.id) && typeof value.proposal_ref.version === "number" ? value.proposal_ref : null;
  const onBehalf = isObject(value.on_behalf_of) && str(value.on_behalf_of.display_name) ? value.on_behalf_of : null;
  return {
    id,
    issue_id: issueId,
    section,
    display_ordinal: typeof value.display_ordinal === "number" ? value.display_ordinal : 0,
    priority_band: BANDS.find((band) => band === value.priority_band) ?? "P4",
    family: str(value.family) ?? "",
    title,
    summary_text: str(value.summary_text),
    fact_at: str(value.fact_at),
    due_at: str(value.due_at),
    due_kind: DUE.find((kind) => kind === value.due_kind) ?? "none",
    overdue: value.overdue === true,
    source_refs: arr(value.source_refs).map(sourceRef).filter((ref): ref is SourceRef => ref !== null),
    recommendation: recommendation
      ? {
          id: str(recommendation.id) ?? "",
          action_code: str(recommendation.action_code) ?? "",
          label: str(recommendation.label)!,
          reason_text: str(recommendation.reason_text),
          effect_text: str(recommendation.effect_text),
          alternatives: arr(recommendation.alternatives).filter((alt): alt is string => typeof alt === "string"),
        }
      : null,
    uncertainty_flags: arr(value.uncertainty_flags).flatMap((flag) =>
      isObject(flag) && str(flag.code) ? [{ code: str(flag.code)!, label: str(flag.label) }] : typeof flag === "string" ? [{ code: flag, label: null }] : [],
    ),
    allowed_actions: arr(value.allowed_actions).map(action).filter((a): a is BriefingAction => a !== null),
    proposal_ref: proposal
      ? { id: str(proposal.id)!, version: proposal.version as number, expires_at: str(proposal.expires_at) }
      : null,
    member_count: typeof value.member_count === "number" ? value.member_count : 1,
    change_kind: value.change_kind === "new" || value.change_kind === "changed" ? value.change_kind : "unchanged",
    is_reminder: value.is_reminder === true,
    fingerprint,
    on_behalf_of: onBehalf ? { id: str(onBehalf.id) ?? "", display_name: str(onBehalf.display_name)! } : null,
    snoozed_until: str(value.snoozed_until),
  };
}

function fallback(value: unknown, problems: string[]): BriefingFallback | null {
  if (!isObject(value)) return null;
  const errorAt = str(value.error_at);
  if (!errorAt) {
    problems.push("fallback.error_at");
    return null;
  }
  const last = isObject(value.last_successful) ? value.last_successful : null;
  return {
    error_at: errorAt,
    tasks: arr(value.tasks).flatMap((task) => {
      if (!isObject(task) || !str(task.id) || !str(task.title)) return [];
      return [
        {
          id: str(task.id)!,
          title: str(task.title)!,
          due_at: str(task.due_at),
          due_kind: DUE.find((kind) => kind === task.due_kind) ?? "none",
          overdue: task.overdue === true,
          source: sourceRef(task.source),
        },
      ];
    }),
    last_successful:
      last && typeof last.version === "number" && str(last.generated_at)
        ? {
            version: last.version,
            generated_at: str(last.generated_at)!,
            data_as_of: str(last.data_as_of) ?? str(last.generated_at)!,
            overview:
              isObject(last.overview) && str(last.overview.text)
                ? {
                    greeting: str(last.overview.greeting) ?? "",
                    text: str(last.overview.text)!,
                    text_source: last.overview.text_source === "llm" ? "llm" : "template",
                    facts: isObject(last.overview.facts) ? last.overview.facts : {},
                  }
                : null,
            items: arr(last.items).flatMap((entry, index) => {
              const parsed = item(entry, problems, `fallback.last_successful.items[${index}]`);
              return parsed ? [parsed] : [];
            }),
          }
        : null,
  };
}

export function parseBriefingView(raw: unknown): BriefingView {
  const problems: string[] = [];
  if (!isObject(raw)) throw new BriefingShapeError(["<body>"]);
  const overview = isObject(raw.overview) ? raw.overview : null;
  if (typeof raw.version !== "number") problems.push("version");
  if (!overview || !str(overview.greeting) || typeof overview.text !== "string") problems.push("overview");
  if (!Array.isArray(raw.sections)) problems.push("sections");
  if (!Array.isArray(raw.items)) problems.push("items");

  const items = arr(raw.items).flatMap((entry, index) => {
    const parsed = item(entry, problems, `items[${index}]`);
    return parsed ? [parsed] : [];
  });
  const sections: BriefingSection[] = arr(raw.sections).flatMap((entry) => {
    if (!isObject(entry)) return [];
    const code = SECTIONS.find((candidate) => candidate === entry.code);
    if (!code) return [];
    const ids = arr(entry.item_ids).filter((id): id is string => typeof id === "string");
    return [{ code, total: typeof entry.total === "number" ? entry.total : ids.length, item_ids: ids }];
  });
  const status = raw.status === "fallback" ? "fallback" : "ready";
  const parsedFallback = fallback(raw.fallback, problems);
  if (status === "fallback" && !parsedFallback) problems.push("fallback");
  if (problems.length > 0) throw new BriefingShapeError(problems);

  const lastAck = isObject(raw.last_ack) && typeof raw.last_ack.version === "number" ? raw.last_ack : null;
  return {
    briefing_id: str(raw.briefing_id) ?? "",
    work_date: str(raw.work_date) ?? "",
    day_type: raw.day_type === "non_working" || raw.day_type === "holiday" || raw.day_type === "leave" ? raw.day_type : "working",
    version: raw.version as number,
    status,
    generated_at: str(raw.generated_at) ?? "",
    data_as_of: str(raw.data_as_of) ?? str(raw.generated_at) ?? "",
    ai_status: raw.ai_status === "unavailable" || raw.ai_status === "demo" ? raw.ai_status : "ok",
    overview: {
      greeting: str(overview!.greeting)!,
      text: overview!.text as string,
      text_source: overview!.text_source === "llm" ? "llm" : "template",
      facts: isObject(overview!.facts) ? overview!.facts : {},
    },
    sections,
    items,
    initial_item_ids: arr(raw.initial_item_ids).filter((id): id is string => typeof id === "string").slice(0, 5),
    pending_updates: typeof raw.pending_updates === "number" ? raw.pending_updates : 0,
    last_ack: lastAck
      ? {
          version: lastAck.version as number,
          acknowledged_at: str(lastAck.acknowledged_at) ?? "",
          method:
            lastAck.method === "explicit" || lastAck.method === "voice" || lastAck.method === "whatsapp" ? lastAck.method : "viewed",
        }
      : null,
    partial_families: arr(raw.partial_families).flatMap((family) =>
      isObject(family) && str(family.family)
        ? [{ family: str(family.family)!, label: str(family.label) ?? str(family.family)!, since: str(family.since) }]
        : typeof family === "string"
          ? [{ family, label: family, since: null }]
          : [],
    ),
    fallback: parsedFallback,
  };
}
