"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { ComposerDock } from "@/components/shell/composer-dock";
import { LinkButton } from "@/components/ui/link";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { announce } from "@/lib/a11y/announcer";
import { createIdempotencyKey } from "@/lib/api/client";
import { isStalenessConflict, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { formatDayTime, formatLongDate, formatTime, parseInstant } from "@/lib/format/time";
import { useNow, useSession } from "@/lib/session/context";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { briefingMessages as m } from "@/messages/briefing";
import { fetchToday, runItemAction, snoozeItem } from "./api";
import { BriefingHeader } from "./briefing-header";
import { BriefingSection, FallbackView, FullListToggle, UpdatesBanner } from "./briefing-sections";
import { CommandBar } from "./command-bar";
import { ExplainDialog, ReasonDialog, SnoozeDialog } from "./item-dialogs";
import { actionLabel, countBriefingUpdates, hasMoreThanInitial, MAIN_SECTIONS, sectionModels, totalItems } from "./model";
import type { BriefingAction, BriefingItem, BriefingView } from "./types";

type DialogState =
  | { kind: "snooze"; item: BriefingItem; action: BriefingAction }
  | { kind: "reason"; item: BriefingItem; action: BriefingAction }
  | { kind: "explain"; item: BriefingItem; action: BriefingAction }
  | null;

/**
 * Today: the personal briefing (frontend_verification §8, briefing.md §5-§11). Data comes only
 * from `GET /api/v1/briefings/today`; when it is unavailable the page says so. The list on
 * screen is a snapshot: newer versions found by the 60 s UI poll wait behind "N updates · Show".
 */
export function TodayView() {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const queryClient = useQueryClient();
  const listId = useId();

  const query = useQuery({
    queryKey: queryKeys.briefings.today(),
    queryFn: ({ signal }) => fetchToday(signal),
  });
  const latest = query.data;

  // The snapshot on screen; replaced only by the person (Show) or by their own action.
  const [displayed, setDisplayed] = useState<BriefingView | null>(latest ?? null);
  const [applyNext, setApplyNext] = useState(false);
  if (latest && (displayed === null || (applyNext && latest !== displayed))) {
    setDisplayed(latest);
    if (applyNext) setApplyNext(false);
  }

  // A newer version reported by the UI poll fetches the briefing; it does not touch the list.
  const poll = useUiPoll();
  const polledVersion = poll.data?.briefing.status === "ok" ? poll.data.briefing.value.version : null;
  useEffect(() => {
    if (polledVersion !== null && latest && polledVersion > latest.version) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.briefings.today() });
    }
  }, [polledVersion, latest, queryClient]);

  const updates = displayed && latest ? countBriefingUpdates(displayed, latest) : 0;
  // A new version that moves no item (for example reworded text) is applied in place.
  if (displayed && latest && latest.version !== displayed.version && updates === 0) setDisplayed(latest);

  useEffect(() => {
    if (updates > 0) announce(m.updates.announce(updates));
  }, [updates]);

  const [showAll, setShowAll] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [pending, setPending] = useState<{ issueId: string; action: string; key: string } | null>(null);

  const refreshAfterAction = async () => {
    setApplyNext(true);
    await Promise.all(invalidationMap["briefings.item_action"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
  };

  const reportFailure = (item: BriefingItem, action: BriefingAction, error: unknown) => {
    const label = actionLabel(action);
    if (isStalenessConflict(error)) {
      toast.info(m.results.changed);
      void refreshAfterAction();
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

  const send = async (
    item: BriefingItem,
    action: BriefingAction,
    run: (key: string, version: number) => Promise<unknown>,
    doneText?: string,
  ) => {
    if (!displayed || pending) return;
    // Minted when the person acts (api-conventions §6); a retry of this request reuses it.
    const key = createIdempotencyKey();
    setPending({ issueId: item.issue_id, action: action.action, key });
    try {
      const result = await run(key, displayed.version);
      setDialog(null);
      const href =
        result !== null && typeof result === "object" && typeof (result as { href?: unknown }).href === "string"
          ? (result as { href: string }).href
          : null;
      toast.success(doneText ?? m.results.done(actionLabel(action)), href ? { action: { label: m.actions.open!, href } } : {});
      await refreshAfterAction();
    } catch (error) {
      reportFailure(item, action, error);
    } finally {
      setPending(null);
    }
  };

  const onCommand = (item: BriefingItem, action: BriefingAction) => {
    if (action.action === "snooze") return setDialog({ kind: "snooze", item, action });
    if (action.action === "explain") return setDialog({ kind: "explain", item, action });
    if (action.action === "dismiss" || action.action === "reject" || action.requires_reason) {
      return setDialog({ kind: "reason", item, action });
    }
    void send(item, action, (key, version) => runItemAction({ item, action: action.action, briefingVersion: version, idempotencyKey: key }));
  };

  if (!displayed) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-[28px] font-bold tracking-[-0.02em] md:text-[clamp(28px,3vw,40px)]">{m.title}</h1>
        {query.isError ? (
          <ErrorState error={query.error} what="your briefing" onRetry={() => void query.refetch()} />
        ) : (
          <Loading label="your briefing" />
        )}
      </div>
    );
  }

  const sections = sectionModels(displayed, showAll);
  const mainSections = sections.filter((section) => MAIN_SECTIONS.has(section.code));
  const sideSections = sections.filter((section) => !MAIN_SECTIONS.has(section.code));
  const generated = parseInstant(displayed.generated_at);
  const wording =
    displayed.ai_status === "demo"
      ? { label: m.demoWording, hint: m.standardWordingHint }
      : displayed.ai_status === "unavailable" && displayed.overview.text_source === "template"
        ? { label: m.standardWording, hint: m.standardWordingHint }
        : null;

  const sectionProps = {
    now,
    zone,
    onCommand,
    pending: pending ? { issueId: pending.issueId, action: pending.action } : null,
    onShowAll: () => setShowAll(true),
  };

  return (
    <div className="flex flex-col gap-6">
      <BriefingHeader
        greeting={displayed.overview.greeting}
        overview={displayed.overview.text}
        meta={
          <>
            <span>{formatLongDate(now, zone)}</span>
            {generated ? (
              <>
                <span aria-hidden="true">·</span>
                <span className="tabular">{m.updated(formatTime(generated, zone))}</span>
              </>
            ) : null}
          </>
        }
        wording={wording}
      />

      <ComposerDock>
        <CommandBar voice={null} />
      </ComposerDock>

      <UpdatesBanner
        count={updates}
        onShow={() => {
          if (latest) setDisplayed(latest);
        }}
      />

      {displayed.day_type !== "working" ? <p className="text-sm text-ink-muted">{m.nonWorkingDay}</p> : null}
      {displayed.partial_families.length > 0 ? (
        <p className="text-sm text-warning-text">{m.partial(displayed.partial_families.map((family) => family.label).join(", "))}</p>
      ) : null}

      {displayed.status === "fallback" && displayed.fallback ? (
        <FallbackView
          fallback={displayed.fallback}
          now={now}
          zone={zone}
          isRetrying={query.isFetching}
          onRetry={() => {
            setApplyNext(true);
            void query.refetch();
          }}
        />
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

      {displayed.status !== "fallback" && hasMoreThanInitial(displayed) ? (
        <div>
          <FullListToggle expanded={showAll} total={totalItems(displayed)} controls={listId} onToggle={() => setShowAll((value) => !value)} />
        </div>
      ) : null}

      <SnoozeDialog
        item={dialog?.kind === "snooze" ? dialog.item : null}
        now={now}
        zone={zone}
        isOpen={dialog?.kind === "snooze"}
        isPending={pending !== null}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        onConfirm={(until) => {
          if (dialog?.kind !== "snooze") return;
          const { item, action } = dialog;
          const untilLabel = formatDayTime(until, now, zone) ?? until;
          void send(item, action, (key, version) => snoozeItem({ item, until, briefingVersion: version, idempotencyKey: key }), m.snooze.done(untilLabel));
        }}
      />
      <ReasonDialog
        item={dialog?.kind === "reason" ? dialog.item : null}
        action={dialog?.kind === "reason" ? dialog.action : null}
        isOpen={dialog?.kind === "reason"}
        isPending={pending !== null}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        onConfirm={(reasonCode, note) => {
          if (dialog?.kind !== "reason") return;
          const { item, action } = dialog;
          void send(item, action, (key, version) =>
            runItemAction({ item, action: action.action, reasonCode, note, briefingVersion: version, idempotencyKey: key }),
          );
        }}
      />
      <ExplainDialog
        item={dialog?.kind === "explain" ? dialog.item : null}
        isOpen={dialog?.kind === "explain"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
      />
    </div>
  );
}
