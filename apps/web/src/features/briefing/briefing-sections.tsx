"use client";

import { useId } from "react";
import { Button } from "@/components/ui/button";
import { AlertIcon, RefreshIcon } from "@/components/ui/icons";
import { Link } from "@/components/ui/link";
import { sectionLabelClasses } from "@/components/ui/styles";
import { cx } from "@/lib/cx";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { briefingMessages as m } from "@/messages/briefing";
import { BriefingItemRow, dueLabel, type BriefingItemRowProps } from "./briefing-item-row";
import type { PendingUpdate, SectionModel } from "./model";
import type { BriefingFallback, BriefingItem } from "./types";

export interface BriefingSectionProps {
  section: SectionModel;
  now: Date;
  zone: ZoneOptions;
  onCommand: BriefingItemRowProps["onCommand"];
  pending: { issueId: string; action: string } | null;
  onShowAll: () => void;
  /** Set while commands cannot be sent (offline); see BriefingItemRow. */
  commandsDisabledReason?: string | null;
}

/** A labelled group of items (Needs you now, Plan for today, …); "Handled for you" is a sage box. */
export function BriefingSection({ section, now, zone, onCommand, pending, onShowAll, commandsDisabledReason = null }: BriefingSectionProps) {
  const headingId = useId();
  const handled = section.code === "handled_for_you";
  return (
    <section aria-labelledby={headingId} className={cx("flex flex-col", handled && "rounded-lg bg-sage px-4 pt-4 pb-1")}>
      <h2 id={headingId} className={cx(sectionLabelClasses, "pb-1")}>
        {section.title}
      </h2>
      {section.items.length > 0 ? (
        <ol className={cx("flex flex-col", handled ? "divide-y divide-border" : "divide-y")}>
          {section.items.map((item) => (
            <li key={item.id}>
              <BriefingItemRow
                item={item}
                now={now}
                zone={zone}
                onCommand={onCommand}
                pendingAction={pending?.issueId === item.issue_id ? pending.action : null}
                commandsDisabledReason={commandsDisabledReason}
              />
            </li>
          ))}
        </ol>
      ) : null}
      {section.hidden > 0 ? (
        <div className={cx("py-3", section.items.length > 0 && "border-t")}>
          <Button variant="quiet" size="sm" onPress={onShowAll}>
            {m.hiddenInSection(section.hidden)}
          </Button>
        </div>
      ) : null}
      {section.total > section.listed ? <p className="py-2 text-sm text-ink-muted">{m.sectionMore(section.listed, section.total)}</p> : null}
    </section>
  );
}

/**
 * "N updates · Show" (or "Your briefing for Tuesday, 13 October is ready · Show"): appears when
 * a newer briefing exists. The list on screen never re-sorts by itself. The page announces the
 * change once through the shared live announcer, so this pill is not a live region itself.
 */
export function UpdatesBanner({ update, onShow }: { update: PendingUpdate | null; onShow: () => void }) {
  if (!update || (update.kind === "updates" && update.count <= 0)) return null;
  return (
    <div className="flex w-fit items-center gap-3 rounded-md border bg-surface py-1.5 ps-3 pe-1.5 shadow-sm animate-rise-in">
      <span className="font-semibold text-ink">{update.kind === "updates" ? m.updates.pill(update.count) : m.updates.newBriefing(update.day)}</span>
      <Button size="sm" variant="primary" onPress={onShow}>
        {m.updates.show}
      </Button>
    </div>
  );
}

/** The sentence the live announcer reads when an update becomes available. */
export function updateAnnouncement(update: PendingUpdate): string {
  return update.kind === "updates" ? m.updates.announce(update.count) : m.updates.newBriefingAnnounce(update.day);
}

/** The full-list toggle: from the top five to every item, without leaving the page. */
export function FullListToggle({
  expanded,
  total,
  controls,
  onToggle,
}: {
  expanded: boolean;
  total: number;
  controls: string;
  onToggle: () => void;
}) {
  return (
    <Button variant="secondary" onPress={onToggle} aria-expanded={expanded} aria-controls={controls}>
      {expanded ? m.showTop : m.showAll(total)}
    </Button>
  );
}

/**
 * Engine failure (briefing.md §11): a timestamped banner, the independent task list and the
 * last successful briefing, so the person still has a permission-safe list to work from.
 */
export function FallbackView({
  fallback,
  now,
  zone,
  onRetry,
  isRetrying,
}: {
  fallback: BriefingFallback;
  now: Date;
  zone: ZoneOptions;
  onRetry: () => void;
  isRetrying: boolean;
}) {
  const failedAt = formatDayTime(fallback.error_at, now, zone) ?? fallback.error_at;
  const last = fallback.last_successful;
  const lastAt = last ? formatDayTime(last.generated_at, now, zone) : null;
  return (
    <div className="flex flex-col gap-6">
      <section role="alert" className="flex flex-col gap-3 rounded-lg border border-warning-text/40 bg-warning-bg p-4 text-ink">
        <div className="flex gap-3">
          <AlertIcon className="mt-0.5 shrink-0 text-warning-text" />
          <div className="flex flex-col gap-1">
            <h2 className="font-bold">{m.fallback.title}</h2>
            <p className="text-sm">{m.fallback.body(failedAt, lastAt)}</p>
          </div>
        </div>
        <div className="ps-9">
          <Button size="sm" onPress={onRetry} isPending={isRetrying} icon={<RefreshIcon size={16} />}>
            {m.fallback.retry}
          </Button>
        </div>
      </section>

      <section aria-labelledby="fallback-tasks" className="flex flex-col">
        <h2 id="fallback-tasks" className={cx(sectionLabelClasses, "pb-1")}>
          {m.fallback.tasksTitle}
        </h2>
        {fallback.tasks.length === 0 ? (
          <p className="py-3 text-ink-muted">{m.fallback.noTasks}</p>
        ) : (
          <ol className="flex flex-col divide-y">
            {fallback.tasks.map((task) => {
              const due = dueLabel(task, now, zone);
              return (
                <li key={task.id} className="flex flex-col gap-1 py-4">
                  {task.source?.href ? (
                    <Link href={task.source.href} className="text-[17px] font-semibold">
                      {task.title}
                    </Link>
                  ) : (
                    <span className="text-[17px] font-semibold text-ink">{task.title}</span>
                  )}
                  <span className="flex flex-wrap gap-x-3 text-sm text-ink-muted">
                    {due ? <span className={cx("tabular", task.overdue && "font-semibold text-danger")}>{due}</span> : null}
                    {task.source ? <span>{task.source.label}</span> : null}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {last && last.items.length > 0 ? (
        <section aria-labelledby="fallback-last" className="flex flex-col">
          <h2 id="fallback-last" className={cx(sectionLabelClasses, "pb-1")}>
            {m.fallback.lastTitle(lastAt ?? last.generated_at)}
          </h2>
          {last.overview ? <p className="pb-2 text-ink-muted">{last.overview.text}</p> : null}
          <ol className="flex flex-col divide-y">
            {last.items.map((item: BriefingItem) => (
              <li key={item.id}>
                <BriefingItemRow item={item} now={now} zone={zone} onCommand={() => undefined} readOnly />
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}
