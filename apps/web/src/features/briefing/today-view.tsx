"use client";

import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ComposerDock } from "@/components/shell/composer-dock";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Composer } from "@/features/assistant/composer";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { LinkButton } from "@/components/ui/link";
import { EmptyState, ErrorState, Loading, Offline, Stale } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { announce } from "@/lib/a11y/announcer";
import { createIdempotencyKey } from "@/lib/api/client";
import { commandPrefix, commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { isNetworkError, isStalenessConflict, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { GreetingReveal } from "@/lib/motion/showcase/greeting-reveal";
import { formatBusinessDate, formatDayTime, formatLongDate, formatTime, parseInstant } from "@/lib/format/time";
import { useOnline } from "@/lib/hooks";
import { useNow, useSession } from "@/lib/session/context";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { briefingMessages as m } from "@/messages/briefing";
import { acknowledgeBriefing, fetchToday, receiptHref, runItemAction, snoozeItem, snoozeUntil } from "./api";
import { BriefingHeader } from "./briefing-header";
import { BriefingSection, FallbackView, FullListToggle, SnoozedSection, UpdatesBanner, updateAnnouncement } from "./briefing-sections";
import { ExplainDialog, ReasonDialog, SnoozeDialog } from "./item-dialogs";
import {
  actionLabel,
  hasMoreThanInitial,
  MAIN_SECTIONS,
  pendingUpdateFor,
  pollShowsNewerBriefing,
  reconcileDisplayed,
  sectionModels,
  totalItems,
} from "./model";
import { ListenPanel } from "./listen/listen-panel";
import { useSpeechPort } from "./listen/speech-context";
import { useListen } from "./listen/use-listen";
import { refetchBriefing } from "./refresh";
import { sendSummaryNow } from "./slice3-api";
import type { BriefingAction, BriefingItem, BriefingView } from "./types";

/** The open dialog; it stays described after closing so the exit animation keeps its content. */
type DialogState = { kind: "snooze" | "reason" | "explain"; item: BriefingItem; action: BriefingAction; open: boolean } | null;

const TODAY_KEY = queryKeys.briefings.today();

/**
 * Today: the personal briefing (frontend_verification §8, briefing.md §5-§11). Data comes only
 * from `GET /api/v1/briefings/today`; when it is unavailable the page says so. The list on
 * screen is a snapshot: newer versions found by the 60 s UI poll (or another day's briefing
 * after the rollover) wait behind "… · Show"; only the person's Show, their own action, Refresh
 * or Try again replaces it, each with data fetched after that moment.
 */
export function TodayView() {
  const { bootstrap, zone } = useSession();
  const [acknowledging, setAcknowledging] = useState(false);
  const now = useNow() ?? new Date(bootstrap.server_now);
  const online = useOnline();
  const queryClient = useQueryClient();
  const listId = useId();

  const query = useQuery({
    queryKey: TODAY_KEY,
    queryFn: ({ signal }) => fetchToday(signal),
  });
  const latest = query.data ?? null;

  // The snapshot on screen. A background fetch replaces it only for an in-place change.
  const [displayed, setDisplayed] = useState<BriefingView | null>(latest);
  const view = reconcileDisplayed(displayed, latest);
  if (view !== displayed) setDisplayed(view);

  // What the assistant may refer to ("the second item"): the briefing on screen, in its order.
  useScreenContribution(
    view && view.status === "ready"
      ? {
          focus: view.briefing_id ? { type: "briefings.briefing", id: view.briefing_id, version: view.version } : null,
          lists: [
            {
              key: "briefing_items",
              rows: view.items.map((item) => ({ type: "briefings.issue", id: item.issue_id, version: view.version, ordinal: item.display_ordinal })),
            },
          ],
        }
      : null,
  );

  // A newer briefing reported by the UI poll (higher version, or another work date after the
  // rollover) fetches the briefing; it does not touch the list. Each poll state acts once.
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

  // "Listen to my day": the version on screen is pinned while it is read, so nothing below re-sorts and the
  // "N updates" pill waits (motion-system §2-§3); finishing acknowledges it and the newest version is fetched.
  const speech = useSpeechPort();
  const listen = useListen({
    briefingId: view?.briefing_id ?? null,
    speech,
    onEnded: () => void applyFresh([queryKeys.ui.poll()]),
  });
  const listening = listen.active;
  const [sendingSummary, setSendingSummary] = useState(false);

  const update = view && latest && !listen.active ? pendingUpdateFor(view, latest, zone.locale) : null;
  // One announcement per change, through the shared live announcer only.
  const announcement = update ? updateAnnouncement(update) : null;
  useEffect(() => {
    if (announcement) announce(announcement);
  }, [announcement]);

  const applyFresh = useCallback(
    async (alsoInvalidate: readonly QueryKey[] = []) => {
      const fresh = await refetchBriefing(queryClient, TODAY_KEY, alsoInvalidate);
      if (fresh) setDisplayed(fresh);
    },
    [queryClient],
  );
  const refreshNow = () => void applyFresh();


  // briefing.md §11: no connection, so the last version stays, labelled, with actions disabled.
  const offline = !online || isNetworkError(query.error);
  const commandsDisabledReason = offline ? m.offlineActions : null;

  const [showAll, setShowAll] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [pending, setPending] = useState<{ issueId: string; action: string } | null>(null);
  // Idempotency-Keys per command, kept for a retry while an attempt's outcome is unknown.
  const [commandKeys] = useState(() => createCommandKeys());

  const closeDialog = () => {
    if (!dialog) return;
    // Cancelling forgets the command: confirming again later is a new command with a new key.
    commandKeys.discard(commandPrefix(dialog.item.issue_id, dialog.action.action));
    setDialog({ ...dialog, open: false });
  };

  const reportFailure = (item: BriefingItem, action: BriefingAction, error: unknown) => {
    const label = actionLabel(action);
    if (isStalenessConflict(error)) {
      toast.info(m.results.changed);
      void applyFresh(invalidationMap["briefings.item_action"]);
      return;
    }
    if (error instanceof ProblemError) {
      if (error.code === "not_complete") {
        const remaining = Array.isArray(error.problem.remaining) ? error.problem.remaining.map(String).join(", ") : undefined;
        toast.warning(m.results.notComplete, { description: remaining || error.detail || undefined });
        return;
      }
      if (error.code === "snooze_beyond_deadline") {
        const max = typeof error.problem.max_until === "string" ? formatDayTime(error.problem.max_until, now, zone) : null;
        toast.warning(m.results.failed(label), { description: max ? m.snooze.tooLate(max) : (error.detail ?? undefined) });
        return;
      }
      if (error.code === "reauth_required") {
        const review = item.allowed_actions.find((candidate) => candidate.action === "review" && candidate.href);
        toast.warning(m.results.reauth, review?.href ? { action: { label: actionLabel(review), href: review.href } } : {});
        return;
      }
      toast.error(m.results.failed(label), {
        description: [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" "),
      });
      return;
    }
    toast.error(m.results.failed(label), { description: error instanceof Error ? error.message : undefined });
  };

  /**
   * Sends one command. Its Idempotency-Key (and payload) is created when the person first
   * confirms it and reused when they retry after an attempt whose outcome is unknown
   * (api-conventions §6; frontend_verification §5).
   */
  const send = async <P,>(
    item: BriefingItem,
    action: BriefingAction,
    details: ReadonlyArray<string | number | null>,
    payload: () => P,
    run: (key: string, version: number, payload: P) => Promise<unknown>,
    doneText?: (payload: P) => string,
  ) => {
    if (!view || view.version === null || pending || offline) return;
    const version = view.version;
    const signature = commandSignature(item.issue_id, action.action, version, item.fingerprint, ...details);
    const attempt = commandKeys.attempt(signature, payload);
    setPending({ issueId: item.issue_id, action: action.action });
    try {
      const result = await run(attempt.key, version, attempt.payload);
      commandKeys.settle(signature);
      setDialog((current) => (current ? { ...current, open: false } : current));
      const href = receiptHref(result);
      toast.success(doneText ? doneText(attempt.payload) : m.results.done(actionLabel(action)), href ? { action: { label: m.actions.open!, href } } : {});
      await applyFresh(invalidationMap["briefings.item_action"]);
    } catch (error) {
      commandKeys.settle(signature, error);
      reportFailure(item, action, error);
    } finally {
      setPending(null);
    }
  };

  const onCommand = (item: BriefingItem, action: BriefingAction) => {
    if (action.action === "snooze") return setDialog({ kind: "snooze", item, action, open: true });
    if (action.action === "explain") return setDialog({ kind: "explain", item, action, open: true });
    if (action.action === "dismiss" || action.action === "reject" || action.requires_reason) {
      return setDialog({ kind: "reason", item, action, open: true });
    }
    void send(item, action, [], () => null, (key, version) =>
      runItemAction({ item, action: action.action, briefingVersion: version, idempotencyKey: key }),
    );
  };

  if (!view) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-[28px] font-bold tracking-[-0.02em] md:text-[clamp(28px,3vw,40px)]">{m.title}</h1>
        {query.isError ? (
          // On Today itself, "Back to Today" would be a link to this page: Retry is the action.
          <ErrorState error={query.error} what="your briefing" onRetry={() => void query.refetch()} backToToday={false} />
        ) : (
          <Loading label="your briefing" />
        )}
      </div>
    );
  }

  const isFallback = view.status === "fallback";
  const sections = isFallback ? [] : sectionModels(view, showAll);
  const mainSections = sections.filter((section) => MAIN_SECTIONS.has(section.code));
  const sideSections = sections.filter((section) => !MAIN_SECTIONS.has(section.code));
  const generated = parseInstant(view.generated_at);
  const wording =
    view.ai_status === "demo"
      ? { label: m.demoWording, hint: m.demoWordingHint }
      : view.ai_status === "unavailable" && view.overview?.text_source === "template"
        ? { label: m.standardWording, hint: m.standardWordingHint }
        : null;
  // The briefing's own day (its work_date), not the browser's: before the 04:00 rollover the
  // briefing on screen still belongs to the previous date (briefing.md §10).
  const day = (view.work_date && formatBusinessDate(view.work_date, zone.locale, "long")) || formatLongDate(now, zone);
  const asOfIso = view.data_as_of || view.generated_at || view.fallback?.error_at || "";
  const asOf = formatDayTime(asOfIso, now, zone) ?? asOfIso;

  const acknowledge = async () => {
    if (!view.briefing_id || view.version === null || acknowledging || offline) return;
    setAcknowledging(true);
    try {
      await acknowledgeBriefing(view.briefing_id, view.version, createIdempotencyKey());
      toast.success(m.acknowledge.done);
      await applyFresh([queryKeys.ui.poll()]);
    } catch (error) {
      toast.error(m.acknowledge.failed, { description: error instanceof ProblemError ? (error.detail ?? error.title) : undefined });
    } finally {
      setAcknowledging(false);
    }
  };
  const canAcknowledge = !isFallback && view.briefing_id !== null && view.version !== null && !view.up_to_date;

  const summary = view.whatsapp_summary ?? null;
  const summaryLine = summary
    ? summary.outcome === "queued"
      ? [
          (summary.simulated ? m.summary.queuedDemo : m.summary.queued)(formatTime(parseInstant(summary.at) ?? now, zone)),
          summary.acknowledged_at && summary.ack_channel ? m.summary.acknowledged(summary.ack_channel) : null,
        ].filter(Boolean).join(" · ")
      : m.summary.skipped(m.summary.reasons[summary.reason ?? ""] ?? summary.reason ?? "")
    : null;
  const canSendSummary = !isFallback && view.day_type === "working" && summary?.outcome !== "queued";
  const sendSummary = async () => {
    if (sendingSummary || offline) return;
    setSendingSummary(true);
    try {
      await sendSummaryNow(createIdempotencyKey());
      await applyFresh();
    } catch (error) {
      toast.error(m.summary.failed, { description: error instanceof ProblemError ? (error.detail ?? error.title) : undefined });
    } finally {
      setSendingSummary(false);
    }
  };

  const sectionProps = {
    now,
    zone,
    onCommand,
    pending,
    onShowAll: () => setShowAll(true),
    commandsDisabledReason,
  };

  // The greeting reveal plays once per briefing version on first view, never over an offline or
  // stale state (motion-system §2 "Today greeting").
  const revealKey = view.status === "ready" && view.briefing_id && view.version !== null ? `${view.briefing_id}:${view.version}` : null;

  return (
    <GreetingReveal revealKey={revealKey} active={!offline && !query.isError && !listening}>
    <div className="flex flex-col gap-6">
      <BriefingHeader
        // A fallback has no greeting of its own; an older one could name the wrong time of day.
        greeting={view.overview?.greeting ?? m.title}
        overview={view.overview?.text ?? null}
        meta={
          <>
            <span>{day}</span>
            {generated ? (
              <>
                <span aria-hidden="true">·</span>
                <span className="tabular">{m.updated(formatTime(generated, zone))}</span>
              </>
            ) : null}
            {canAcknowledge ? (
              <Button
                variant="quiet"
                size="sm"
                onPress={() => void acknowledge()}
                isPending={acknowledging}
                pendingLabel={m.acknowledge.pending}
                {...unavailableWhen(offline ? m.offlineActions : null)}
              >
                {m.acknowledge.action}
              </Button>
            ) : null}
          </>
        }
        wording={wording}
      />

      <div className="flex flex-col gap-3">
        {!isFallback ? (
          <ListenPanel
            state={listen.state}
            speechLabel={speech.label}
            disabledReason={offline ? m.offlineActions : view.briefing_id === null ? m.listen.starting : null}
            onStart={() => void listen.start()}
            onPause={listen.pause}
            onResume={listen.resume}
            onStop={listen.stop}
            onClose={listen.reset}
          />
        ) : null}
        {listening ? <p className="text-sm text-ink-muted">{m.listen.pinned}</p> : null}
        <nav aria-label="Today" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <LinkButton variant="quiet" size="sm" href="/today/changes">
            {m.links.changes}
          </LinkButton>
          <LinkButton variant="quiet" size="sm" href="/today/all">
            {m.links.all}
          </LinkButton>
          {summaryLine ? <span className="text-ink-muted" data-testid="whatsapp-summary">{summaryLine}</span> : null}
          {canSendSummary ? (
            <Button
              variant="quiet"
              size="sm"
              onPress={() => void sendSummary()}
              isPending={sendingSummary}
              pendingLabel={m.summary.sending}
              {...unavailableWhen(offline ? m.offlineActions : null)}
            >
              {m.summary.send}
            </Button>
          ) : null}
        </nav>
      </div>

      <ComposerDock>
        {/* The command bar is the assistant composer; no voice control in Slice 1. */}
        <div className="md:rounded-lg md:border md:bg-surface md:p-4 md:shadow-sm">
          <Composer variant="today" />
        </div>
      </ComposerDock>

      <UpdatesBanner
        update={update}
        onShow={() => {
          if (latest) setDisplayed(latest);
        }}
      />

      {offline ? (
        <Offline asOf={asOf} onRetry={refreshNow} compact />
      ) : query.isError ? (
        // A refresh failed: keep the last briefing on screen, say how old it is, offer Refresh.
        <Stale asOf={asOf} onRefresh={refreshNow} />
      ) : null}

      {view.day_type !== "working" ? <p className="text-sm text-ink-muted">{m.nonWorkingDay}</p> : null}
      {view.partial_families.length > 0 ? (
        <p className="text-sm text-warning-text">{m.partial(view.partial_families.map((family) => family.label).join(", "))}</p>
      ) : null}

      {isFallback && view.fallback ? (
        <FallbackView fallback={view.fallback} now={now} zone={zone} isRetrying={query.isFetching} onRetry={refreshNow} />
      ) : sections.length === 0 ? (
        <EmptyState title={m.empty} action={<LinkButton href="/inbox">Open the Inbox</LinkButton>}>
          New tasks, approvals and changes appear here as they happen.
        </EmptyState>
      ) : (
        <div id={listId} className="grid grid-cols-1 gap-x-12 gap-y-8 @5xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-8">
            {mainSections.map((section) => (
              <BriefingSection key={section.code} section={section} {...sectionProps} />
            ))}
          </div>
          {sideSections.length > 0 ? (
            <div className="flex min-w-0 flex-col gap-8">
              {sideSections.map((section) => (
                <BriefingSection key={section.code} section={section} {...sectionProps} />
              ))}
            </div>
          ) : null}
        </div>
      )}

      {!isFallback && showAll && view.snoozed.length > 0 ? <SnoozedSection items={view.snoozed} now={now} zone={zone} /> : null}

      {!isFallback && (hasMoreThanInitial(view) || view.snoozed.length > 0) ? (
        <div>
          <FullListToggle expanded={showAll} total={totalItems(view)} controls={listId} onToggle={() => setShowAll((value) => !value)} />
        </div>
      ) : null}

      <SnoozeDialog
        item={dialog?.kind === "snooze" ? dialog.item : null}
        now={now}
        zone={zone}
        isOpen={dialog?.kind === "snooze" && dialog.open}
        isPending={pending !== null}
        disabledReason={commandsDisabledReason}
        onOpenChange={(open) => (open ? undefined : closeDialog())}
        onConfirm={(choice) => {
          if (dialog?.kind !== "snooze") return;
          const { item, action } = dialog;
          void send(
            item,
            action,
            [choice],
            // The instant is fixed by the first attempt, so a retry sends the same body.
            () => snoozeUntil(choice, new Date(), action.max_until),
            (key, version, until) => snoozeItem({ item, until, briefingVersion: version, idempotencyKey: key }),
            (until) => m.snooze.done(formatDayTime(until, now, zone) ?? until),
          );
        }}
      />
      <ReasonDialog
        item={dialog?.kind === "reason" ? dialog.item : null}
        action={dialog?.kind === "reason" ? dialog.action : null}
        isOpen={dialog?.kind === "reason" && dialog.open}
        isPending={pending !== null}
        disabledReason={commandsDisabledReason}
        onOpenChange={(open) => (open ? undefined : closeDialog())}
        onConfirm={(reasonCode, note) => {
          if (dialog?.kind !== "reason") return;
          const { item, action } = dialog;
          void send(item, action, [reasonCode, note], () => null, (key, version) =>
            runItemAction({ item, action: action.action, reasonCode, note, briefingVersion: version, idempotencyKey: key }),
          );
        }}
      />
      <ExplainDialog
        item={dialog?.kind === "explain" ? dialog.item : null}
        isOpen={dialog?.kind === "explain" && dialog.open}
        onOpenChange={(open) => (open ? undefined : closeDialog())}
      />
    </div>
    </GreetingReveal>
  );
}
