"use client";

/**
 * The data layer for the Today screens. Calls, parsers, models and the Listen and assistant hooks
 * come from the old app's non-visual modules (`@/features/briefing/*`, `@/features/assistant/*`);
 * this file adds the hooks that used to live inside the old view components, with the same
 * endpoints, bodies, Idempotency-Keys, version handling and cache invalidation.
 */

import { useInfiniteQuery, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type { RunStep } from "@/features/assistant/types";
import {
  acknowledgeBriefing,
  fetchExplanation,
  fetchToday,
  receiptHref,
  runItemAction,
  snoozeItem,
  snoozeUntil,
} from "@/features/briefing/api";
import {
  isNavigationAction,
  pendingUpdateFor,
  pollShowsNewerBriefing,
  primaryAction,
  reconcileDisplayed,
  secondaryActions,
  type PendingUpdate,
} from "@/features/briefing/model";
import { parseBriefingItem, parseExplanation } from "@/features/briefing/parse";
import { refetchBriefing } from "@/features/briefing/refresh";
import {
  fetchDelta,
  fetchItemDetail,
  sendSummaryNow,
  type DeltaSince,
  type WireDeltaGroup,
} from "@/features/briefing/slice3-api";
import type { BriefingAction, BriefingItem, BriefingView, PriorityBand } from "@/features/briefing/types";
import { announce } from "@/lib/a11y/announcer";
import { createIdempotencyKey } from "@/lib/api/client";
import { commandPrefix, commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { isNetworkError, isStalenessConflict, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { useOnline } from "@/lib/hooks";
import { useNow, useSession } from "@/lib/session/context";
import type { SessionBootstrap } from "@/lib/session/types";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { toast } from "~/ui";
import type { Tone } from "~/ui";

export const TODAY_KEY = queryKeys.briefings.today();

// ---------------------------------------------------------------------------------------------
// Words. Server text (titles, summaries, action labels, deadlines) is shown as sent; these are
// the labels the web supplies, in the team's vocabulary.

export const SECTION_LABEL: Record<string, string> = {
  needs_you_now: "Needs you now",
  plan_for_today: "Planned for today",
  recommendations: "Suggestions",
  changes_since_last_visit: "Since your last visit",
  handled_for_you: "Handled for you",
  coming_next: "Coming next",
  snoozed: "Snoozed",
};

const KIND_LABEL: Record<string, string> = {
  "common.approvals": "Approval",
  "sales.customer_replies": "Customer reply",
  "sales.enquiries": "Enquiry",
  "sales.quote_review": "Quotation review",
  "sales.quote_expiry": "Quotation expiring",
  "sales.commercial_exceptions": "Price change",
  "sales.customer_changes": "Customer update",
  "sales.samples": "Sample",
  "admin.access": "Access request",
  "admin.onboarding": "Onboarding",
  "common.onboarding": "Onboarding",
  "common.handled": "Handled",
  "ops.returnables": "Returnable",
  "ops.cut_plans": "Cut plan",
  "ops.shortages": "Shortage",
  "ops.production_dependencies": "Production",
  "ops.dispatch_cutoffs": "Dispatch",
  "ops.receipts": "Receipt",
  "ops.qc": "Quality check",
};

/** What kind of thing an item is ("Quotation review"); never a raw rule key. */
export function kindLabel(item: Pick<BriefingItem, "family" | "is_reminder">): string {
  if (item.is_reminder) return "Reminder";
  return KIND_LABEL[item.family] ?? "Task";
}

export function familyLabel(family: string): string {
  return KIND_LABEL[family] ?? "Task";
}

const ACTION_LABEL: Record<string, string> = {
  open: "Open",
  prepare: "Prepare",
  assign: "Assign",
  review: "Review",
  approve: "Approve",
  reject: "Reject",
  snooze: "Snooze",
  mark_handled: "Mark as handled",
  unsnooze: "Bring back",
  dismiss: "Dismiss",
  explain: "Why is this here?",
};

/** The server's label ("Review quote") when it sent one, else ours. */
export function actionText(action: Pick<BriefingAction, "action" | "label">): string {
  if (action.action === "explain") return ACTION_LABEL.explain!;
  return action.label ?? ACTION_LABEL[action.action] ?? action.action;
}

const UNCERTAINTY_LABEL: Record<string, string> = {
  STALE_STOCK_DATA: "Stock figures may be out of date",
  MISSING_PRICE: "A price is missing",
  FX_UNAVAILABLE: "No exchange rate for this currency",
  ESTIMATE: "Estimated figure",
  DEMO_DATA: "Demo data",
  PERMISSIONS_CHANGED: "Some details are hidden after an access change",
};

export function uncertaintyText(flag: { code: string; label: string | null }): string {
  return flag.label ?? UNCERTAINTY_LABEL[flag.code] ?? flag.code.replaceAll("_", " ").toLowerCase();
}

const OFFLINE_REASON = "You are offline. Actions wait until the connection is back.";

/** Colour by urgency; the kind label always carries the meaning in words. */
export function itemTone(item: Pick<BriefingItem, "priority_band" | "overdue" | "section">): Tone {
  if (item.section === "handled_for_you") return "leaf";
  if (item.overdue) return "ember";
  const band: Record<PriorityBand, Tone> = { P1: "ember", P2: "amber", P3: "cobalt", P4: "neutral" };
  return band[item.priority_band];
}

/** The server's deadline text when it sent one, else ours in the person's zone. */
export function dueText(
  item: Pick<BriefingItem, "due_at" | "due_kind" | "overdue"> & { due_label?: string | null },
  now: Date,
  zone: ZoneOptions,
): string | null {
  if (item.due_label) return item.due_label;
  if (!item.due_at || item.due_kind === "none") return null;
  const when = formatDayTime(item.due_at, now, zone);
  if (!when) return null;
  if (item.overdue) return `Overdue, was due ${when}`;
  return item.due_kind === "hard" ? `Due ${when}` : `Target ${when}`;
}

export function itemHref(issueId: string): string {
  return `/today/items/${encodeURIComponent(issueId)}`;
}

/** Commands POST to the server; navigation and the explanation only read. */
export function isCommandAction(action: BriefingAction): boolean {
  return !isNavigationAction(action) && action.action !== "explain";
}

export { isNavigationAction, primaryAction, secondaryActions };

// ---------------------------------------------------------------------------------------------
// Today's briefing: the snapshot on screen, newer versions, refresh, acknowledge, WhatsApp summary.

export interface TodayBriefing {
  /** The snapshot on screen, or null before the first answer. */
  view: BriefingView | null;
  isLoading: boolean;
  error: unknown;
  isError: boolean;
  isFetching: boolean;
  /** No connection: the last version stays, labelled, and commands wait. */
  offline: boolean;
  /** A newer briefing the person has not applied yet (never applied for them). */
  latest: BriefingView | null;
  pendingUpdate: (hold: boolean) => PendingUpdate | null;
  showLatest: () => void;
  /** Fetches now and shows what that fetch returned. */
  refresh: (alsoInvalidate?: readonly QueryKey[]) => Promise<void>;
  retry: () => void;
  canAcknowledge: boolean;
  acknowledging: boolean;
  acknowledge: () => Promise<void>;
  canSendSummary: boolean;
  sendingSummary: boolean;
  sendSummary: () => Promise<void>;
  now: Date;
  zone: ZoneOptions;
}

/**
 * The list on screen is a snapshot. A newer version found by the 60-second poll (or another day's
 * briefing after the rollover) waits until the person asks for it; only their own Show, action,
 * Refresh or Try again replaces it, each with data fetched after that moment.
 */
export function useTodayBriefing(): TodayBriefing {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const online = useOnline();
  const queryClient = useQueryClient();

  const query = useQuery({ queryKey: TODAY_KEY, queryFn: ({ signal }) => fetchToday(signal) });
  const latest = query.data ?? null;

  const [displayed, setDisplayed] = useState<BriefingView | null>(latest);
  const view = reconcileDisplayed(displayed, latest);
  if (view !== displayed) setDisplayed(view);

  // A newer briefing reported by the poll fetches the briefing; it never touches the list.
  const poll = useUiPoll();
  const polled = poll.data?.briefing.status === "ok" ? poll.data.briefing.value : null;
  const polledVersion = polled?.version ?? null;
  const polledDate = polled?.work_date ?? null;
  const actedOnPoll = useRef<string | null>(null);
  useEffect(() => {
    if (!latest || !pollShowsNewerBriefing({ version: polledVersion, work_date: polledDate }, latest)) return;
    const seen = `${polledDate}|${polledVersion}`;
    if (actedOnPoll.current === seen) return;
    actedOnPoll.current = seen;
    void queryClient.invalidateQueries({ queryKey: TODAY_KEY });
  }, [polledVersion, polledDate, latest, queryClient]);

  const refresh = useCallback(
    async (alsoInvalidate: readonly QueryKey[] = []) => {
      const fresh = await refetchBriefing(queryClient, TODAY_KEY, alsoInvalidate);
      if (fresh) setDisplayed(fresh);
    },
    [queryClient],
  );

  const offline = !online || isNetworkError(query.error);
  const isFallback = view?.status === "fallback";

  const [acknowledging, setAcknowledging] = useState(false);
  const canAcknowledge = Boolean(view && !isFallback && view.briefing_id !== null && view.version !== null && !view.up_to_date);
  const acknowledge = async () => {
    if (!view || !view.briefing_id || view.version === null || acknowledging || offline) return;
    setAcknowledging(true);
    try {
      await acknowledgeBriefing(view.briefing_id, view.version, createIdempotencyKey());
      toast.success("Marked as seen", { description: "New changes are counted from now." });
      await refresh([queryKeys.ui.poll()]);
    } catch (error) {
      toast.error("The briefing could not be marked as seen", {
        description: error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection, then try again.",
      });
    } finally {
      setAcknowledging(false);
    }
  };

  const [sendingSummary, setSendingSummary] = useState(false);
  const summary = view?.whatsapp_summary ?? null;
  const canSendSummary = Boolean(view && !isFallback && view.day_type === "working" && summary?.outcome !== "queued");
  const sendSummary = async () => {
    if (sendingSummary || offline) return;
    setSendingSummary(true);
    try {
      await sendSummaryNow(createIdempotencyKey());
      await refresh();
    } catch (error) {
      toast.error("The WhatsApp summary could not be sent", {
        description: error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection, then try again.",
      });
    } finally {
      setSendingSummary(false);
    }
  };

  return {
    view,
    isLoading: !view && !query.isError,
    error: query.error,
    isError: query.isError,
    isFetching: query.isFetching,
    offline,
    latest,
    pendingUpdate: (hold) => (view && latest && !hold ? pendingUpdateFor(view, latest, zone.locale) : null),
    showLatest: () => {
      if (latest) setDisplayed(latest);
    },
    refresh,
    retry: () => void query.refetch(),
    canAcknowledge,
    acknowledging,
    acknowledge,
    canSendSummary,
    sendingSummary,
    sendSummary,
    now,
    zone,
  };
}

/** The sentence the live announcer reads once when a newer briefing is waiting. */
export function updateSentence(update: PendingUpdate): string {
  if (update.kind === "updates") {
    return update.count === 1 ? "1 update to your briefing is ready." : `${update.count} updates to your briefing are ready.`;
  }
  return update.day ? `Your briefing for ${update.day} is ready.` : "Your new briefing is ready.";
}

export function useAnnounceUpdate(update: PendingUpdate | null): void {
  const sentence = update ? `${updateSentence(update)} Press Show to see it.` : null;
  useEffect(() => {
    if (sentence) announce(sentence);
  }, [sentence]);
}

const SUMMARY_REASON: Record<string, string> = {
  not_linked: "WhatsApp is not linked yet",
  session_expired: "the WhatsApp link needs a new message from your phone",
  consent_missing: "the daily briefing is switched off in your WhatsApp settings",
  consent_opted_out: "you opted out with STOP",
  template_missing: "there is no approved summary template",
  template_not_utility: "the summary template is not a utility template",
  non_working_day: "today is not a working day",
  briefing_unavailable: "the briefing could not be prepared",
};

/** Today's WhatsApp summary in words, plus whether it was simulated (the Demo label). */
export function summaryStatus(view: BriefingView, time: (iso: string) => string): { text: string; demo: boolean } | null {
  const summary = view.whatsapp_summary ?? null;
  if (!summary) return null;
  if (summary.outcome === "queued") {
    const seen = summary.acknowledged_at && summary.ack_channel ? `, seen on ${summary.ack_channel === "whatsapp" ? "WhatsApp" : "the web"}` : "";
    return {
      text: summary.simulated ? `WhatsApp summary sent at ${time(summary.at)}, not delivered to a phone${seen}` : `WhatsApp summary sent at ${time(summary.at)}${seen}`,
      demo: summary.simulated,
    };
  }
  const reason = SUMMARY_REASON[summary.reason ?? ""] ?? summary.reason ?? "";
  return { text: reason ? `No WhatsApp summary today: ${reason}` : "No WhatsApp summary today", demo: false };
}

// ---------------------------------------------------------------------------------------------
// Item commands: snooze, mark as handled, dismiss with a reason, bring back, explain.

export type SnoozeChoice = "1h" | "3h" | "24h";

export type ItemDialog = { kind: "snooze" | "reason" | "explain"; item: BriefingItem; action: BriefingAction; open: boolean } | null;

export interface ItemCommands {
  /** The command being sent, if any; every other command waits for it. */
  pending: { issueId: string; action: string } | null;
  dialog: ItemDialog;
  /** Why commands cannot be sent right now (offline), or null. */
  disabledReason: string | null;
  /** Starts a command: opens its dialog, or sends it when it needs nothing more. */
  run: (item: BriefingItem, action: BriefingAction) => void;
  closeDialog: () => void;
  confirmSnooze: (choice: SnoozeChoice) => void;
  confirmReason: (reasonCode: string | null, note: string) => void;
}

/**
 * Sends item commands for the briefing version on screen. Each command's Idempotency-Key and
 * payload are created when the person first confirms it and reused when they retry after an
 * attempt whose outcome is unknown. A 409 means the item moved: the latest version is fetched.
 */
export function useItemCommands({
  version,
  offline,
  onChanged,
}: {
  /** The briefing version the item was read from; commands are refused without one. */
  version: number | null;
  offline: boolean;
  /** After a command succeeded or the item turned out to be stale: refetch what is on screen. */
  onChanged: (alsoInvalidate: readonly QueryKey[], outcome: "done" | "stale") => Promise<void> | void;
}): ItemCommands {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const [dialog, setDialog] = useState<ItemDialog>(null);
  const [pending, setPending] = useState<{ issueId: string; action: string } | null>(null);
  const [commandKeys] = useState(() => createCommandKeys());

  const closeDialog = () => {
    if (!dialog) return;
    // Cancelling forgets the command: confirming again later is a new command with a new key.
    commandKeys.discard(commandPrefix(dialog.item.issue_id, dialog.action.action));
    setDialog({ ...dialog, open: false });
  };

  const reportFailure = (item: BriefingItem, action: BriefingAction, error: unknown) => {
    const label = actionText(action);
    if (isStalenessConflict(error)) {
      toast.info("This item changed while you were looking at it", { description: "You now see the latest version." });
      void onChanged(invalidationMap["briefings.item_action"], "stale");
      return;
    }
    if (error instanceof ProblemError) {
      if (error.code === "not_complete") {
        const remaining = Array.isArray(error.problem.remaining) ? error.problem.remaining.map(String).join(", ") : undefined;
        toast.warning("The record does not show this as complete yet", { description: remaining || error.detail || undefined });
        return;
      }
      if (error.code === "snooze_beyond_deadline") {
        const max = typeof error.problem.max_until === "string" ? formatDayTime(error.problem.max_until, now, zone) : null;
        toast.warning("That is too long to snooze", {
          description: max ? `The deadline is close, so the latest is ${max}.` : (error.detail ?? undefined),
        });
        return;
      }
      if (error.code === "reauth_required") {
        const review = item.allowed_actions.find((candidate) => candidate.action === "review" && candidate.href);
        toast.warning(
          "Confirm it is you to continue",
          review?.href ? { description: "Open the review screen to carry on.", action: { label: actionText(review), href: review.href } } : {},
        );
        return;
      }
      toast.error(`${label} did not go through`, {
        description: [error.detail ?? error.title, error.request_id ? `Reference ${error.request_id}` : null].filter(Boolean).join(" "),
      });
      return;
    }
    toast.error(`${label} did not go through`, { description: error instanceof Error ? error.message : "Try again." });
  };

  const send = async <P,>(
    item: BriefingItem,
    action: BriefingAction,
    details: ReadonlyArray<string | number | null>,
    payload: () => P,
    request: (key: string, briefingVersion: number, payload: P) => Promise<unknown>,
    doneText?: (payload: P) => string,
  ) => {
    if (version === null || pending || offline) return;
    const signature = commandSignature(item.issue_id, action.action, version, item.fingerprint, ...details);
    const attempt = commandKeys.attempt(signature, payload);
    setPending({ issueId: item.issue_id, action: action.action });
    try {
      const result = await request(attempt.key, version, attempt.payload);
      commandKeys.settle(signature);
      setDialog((current) => (current ? { ...current, open: false } : current));
      const href = receiptHref(result);
      toast.success(doneText ? doneText(attempt.payload) : `${actionText(action)}: done`, href ? { action: { label: "Open", href } } : {});
      await onChanged(invalidationMap["briefings.item_action"], "done");
    } catch (error) {
      commandKeys.settle(signature, error);
      reportFailure(item, action, error);
    } finally {
      setPending(null);
    }
  };

  const run = (item: BriefingItem, action: BriefingAction) => {
    if (action.action === "snooze") return setDialog({ kind: "snooze", item, action, open: true });
    if (action.action === "explain") return setDialog({ kind: "explain", item, action, open: true });
    if (action.action === "dismiss" || action.action === "reject" || action.requires_reason) {
      return setDialog({ kind: "reason", item, action, open: true });
    }
    void send(item, action, [], () => null, (key, briefingVersion) =>
      runItemAction({ item, action: action.action, briefingVersion, idempotencyKey: key }),
    );
  };

  const confirmSnooze = (choice: SnoozeChoice) => {
    if (dialog?.kind !== "snooze") return;
    const { item, action } = dialog;
    void send(
      item,
      action,
      [choice],
      // The instant is fixed by the first attempt, so a retry sends the same body.
      () => snoozeUntil(choice, new Date(), action.max_until),
      (key, briefingVersion, until) => snoozeItem({ item, until, briefingVersion, idempotencyKey: key }),
      (until) => `Snoozed until ${formatDayTime(until, now, zone) ?? until}`,
    );
  };

  const confirmReason = (reasonCode: string | null, note: string) => {
    if (dialog?.kind !== "reason") return;
    const { item, action } = dialog;
    void send(item, action, [reasonCode, note], () => null, (key, briefingVersion) =>
      runItemAction({ item, action: action.action, reasonCode, note, briefingVersion, idempotencyKey: key }),
    );
  };

  return { pending, dialog, disabledReason: offline ? OFFLINE_REASON : null, run, closeDialog, confirmSnooze, confirmReason };
}

/** The rule-based explanation behind "Why is this here?". Read-only: each request has its own key. */
export function useExplanation(issueId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.briefings.explain(issueId),
    queryFn: ({ signal }) => fetchExplanation(issueId, signal),
    enabled: enabled && issueId !== "",
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------------------------
// One item, and the change log.

export function isNotFound(error: unknown): boolean {
  return error instanceof ProblemError && error.status === 404;
}

/** One item of the current briefing with its explanation; 404 once it has left the briefing. */
export function useBriefingItem(issueId: string) {
  return useQuery({
    queryKey: queryKeys.briefings.item(issueId),
    queryFn: async ({ signal }) => {
      const raw = await fetchItemDetail(issueId, signal);
      return { item: parseBriefingItem(raw.item), explanation: parseExplanation(raw.explanation), version: raw.version, workDate: raw.work_date };
    },
    retry: (count, error) => !isNotFound(error) && count < 2,
  });
}

export interface ChangeFamily {
  family: string;
  label: string;
  groups: WireDeltaGroup[];
}

/** Issues grouped by kind, in the order the server returned them; pages of one issue are merged. */
export function useChanges(since: DeltaSince) {
  const query = useInfiniteQuery({
    queryKey: queryKeys.briefings.delta(since),
    queryFn: ({ pageParam, signal }) => fetchDelta(since, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
  const pages = query.data?.pages ?? [];
  const merged = new Map<string, WireDeltaGroup>();
  for (const page of pages) {
    for (const group of page.groups) {
      const existing = merged.get(group.issue_id);
      if (existing) merged.set(group.issue_id, { ...existing, changes: [...existing.changes, ...group.changes] });
      else merged.set(group.issue_id, group);
    }
  }
  const families = new Map<string, ChangeFamily>();
  for (const group of merged.values()) {
    const existing = families.get(group.family);
    if (existing) existing.groups.push(group);
    else families.set(group.family, { family: group.family, label: familyLabel(group.family), groups: [group] });
  }
  const changeCount = [...merged.values()].reduce((sum, group) => sum + group.changes.length, 0);
  return { query, families: [...families.values()], window: pages[0] ?? null, changeCount };
}

const CHANGE_KIND: Record<string, string> = {
  created: "New",
  changed: "Changed",
  updated: "Updated",
  status_changed: "Status changed",
  resolved: "Resolved",
  reopened: "Reopened",
  assigned: "Assigned",
  revised: "Revised",
};

/** "sales.quote.changed" becomes "Changed"; unknown codes become readable words. */
export function changeKind(code: string): { key: string; label: string } {
  const key = code.split(".").pop() ?? code;
  return { key, label: CHANGE_KIND[key] ?? (key.charAt(0).toUpperCase() + key.slice(1)).replaceAll("_", " ") };
}

/** The plain values of a before or after record, as "status: sent" pairs. */
export function changeValues(record: Record<string, unknown> | null | undefined): { key: string; value: string }[] {
  if (!record) return [];
  return Object.entries(record)
    .filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
    .map(([key, value]) => ({ key: key.replaceAll("_", " "), value: String(value) }));
}

// ---------------------------------------------------------------------------------------------
// The assistant.

/** True when the AI integration runs in demo mode: the composer and its replies carry "Demo". */
export function assistantIsDemo(bootstrap: Pick<SessionBootstrap, "integration_modes" | "integrations">): boolean {
  if (bootstrap.integration_modes) return bootstrap.integration_modes.ai === "demo";
  return bootstrap.integrations.status === "ok" && bootstrap.integrations.value.some((item) => item.key === "ai" && item.mode === "demo");
}

const STEP_NAME: Record<string, string> = {
  resolve_party: "Found the customer",
  find_usual_order: "Looked up the usual order",
  resolve_product: "Found the product",
  resolve_price: "Checked the price list",
  calculate_quote: "Calculated the totals",
  draft_quote: "Drafted the quotation",
  route: "Understood the request",
  handoff: "Passed the request on",
};

const STEP_KIND: Record<string, string> = {
  route: "Understood the request",
  tool_call: "Looked something up",
  handoff: "Passed the request on",
};

/** A step as the person reads it: tool names become plain verbs; internal steps are hidden. */
export function stepText(step: RunStep): string | null {
  if (step.kind === "tool_result" || step.kind === "text" || step.kind === "card") return null;
  return (step.name ? STEP_NAME[step.name] : undefined) ?? STEP_KIND[step.kind] ?? null;
}

export const RUN_STATUS: Record<string, string> = {
  queued: "Waiting to start",
  running: "Working on it",
  succeeded: "Done",
  failed: "Stopped with a problem",
  budget_exceeded: "Stopped: the request took too long",
  cancelled: "Stopped",
};

/** The line under a run that ended without success. */
export function runEnding(status: string): string | null {
  if (status === "failed") return "Lamikraft could not finish this. Nothing changed after the last step shown.";
  if (status === "budget_exceeded") return "This took longer than Lamikraft is allowed. Try a smaller request, or do it from the screen.";
  if (status === "cancelled") return "Stopped. Anything already saved stays as a draft.";
  return null;
}
