"use client";

import type { Route } from "next";
import { useEffect, useId, useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { useSpeechPort } from "@/features/briefing/listen/speech-context";
import { useListen } from "@/features/briefing/listen/use-listen";
import { MAIN_SECTIONS, sectionModels, type SectionModel } from "@/features/briefing/model";
import type { BriefingFallback, BriefingItem, BriefingView, SectionCode } from "@/features/briefing/types";
import { queryKeys } from "@/lib/api/query-keys";
import { formatBusinessDate, formatDayTime, formatLongDate, formatTime, parseInstant, type ZoneOptions } from "@/lib/format/time";
import { useSession } from "@/lib/session/context";
import {
  dueText,
  primaryAction,
  SECTION_LABEL,
  summaryStatus,
  updateSentence,
  useAnnounceUpdate,
  useItemCommands,
  useTodayBriefing,
  type ItemCommands,
} from "~/data/today";
import { riseAt } from "./rise";
import { Page } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  CountUp,
  EmptyState,
  GlassPanel,
  Icon,
  IconButton,
  Menu,
  Skeleton,
  SkeletonText,
  StatTile,
  TextLink,
  type MenuItem,
} from "~/ui";
import { allHref } from "./all-state";
import { TodayAssistant } from "./assistant";
import { TodayHero } from "./hero";
import { ItemDialogs } from "./item-dialogs";
import { CompactItem, ItemRow } from "./item-row";
import { ListenPanel } from "./listen";

/** How many items a group shows before "See all": the most important few, in the server's order. */
const SHOWN: Record<string, number> = { needs_you_now: 4, plan_for_today: 3, recommendations: 3, handled_for_you: 4, coming_next: 4 };

/** The four counts beside the greeting; each opens "All of today" on that group. */
const TILES: readonly SectionCode[] = ["needs_you_now", "plan_for_today", "recommendations", "handled_for_you"];

/** A count that runs up from zero once the screen is mounted (straight to the figure under reduced motion). */
function Count({ value }: { value: number }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  return <CountUp value={shown ? value : 0} />;
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? `1 ${one}` : `${count} ${many}`;
}

/** The sentence under the greeting when the server sent none: written from the briefing's own counts. */
function leadFromCounts(view: BriefingView): string {
  const total = (code: SectionCode) => view.sections.find((section) => section.code === code)?.total ?? 0;
  const needs = total("needs_you_now");
  const planned = total("plan_for_today");
  if (needs === 0 && planned === 0) return "Nothing needs you right now.";
  if (needs === 0) return `Nothing is waiting on you. ${plural(planned, "item is", "items are")} planned for today.`;
  if (planned === 0) return `${plural(needs, "item needs", "items need")} you now.`;
  return `${plural(needs, "item needs", "items need")} you now, and ${plural(planned, "more is", "more are")} planned for today.`;
}

/**
 * Today answers one question: what needs me now? The greeting and the day's counts come first,
 * then the items that need action, grouped as the briefing groups them, each group showing only
 * its most important few. What changed since the last visit is one line that leads to its own
 * screen. The assistant sits at the foot of the column.
 */
export function TodayScreen() {
  const { bootstrap } = useSession();
  const briefing = useTodayBriefing();
  const { view, now, zone, offline } = briefing;
  const listId = useId();

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

  // Listening pins the version on screen: nothing re-sorts and the update notice waits.
  const speech = useSpeechPort();
  const refresh = briefing.refresh;
  const listen = useListen({
    briefingId: view?.briefing_id ?? null,
    speech,
    onEnded: () => void refresh([queryKeys.ui.poll()]),
  });

  const update = briefing.pendingUpdate(listen.active);
  useAnnounceUpdate(update);

  const commands = useItemCommands({
    version: view?.version ?? null,
    offline,
    onChanged: (alsoInvalidate) => briefing.refresh(alsoInvalidate),
  });

  if (!view) {
    return (
      <Page>
        <TodayHero
          date={formatLongDate(now, zone)}
          lead={briefing.isError ? "Your briefing did not arrive." : "Putting your briefing together."}
          aside={
            briefing.isError ? null : (
              <GlassPanel padding="md" className="grid grid-cols-2 gap-x-5 gap-y-6" aria-hidden="true">
                {TILES.map((code) => (
                  <div key={code} className="flex flex-col gap-3">
                    <Skeleton width="70%" height={12} />
                    <Skeleton width={36} height={28} />
                  </div>
                ))}
              </GlassPanel>
            )
          }
        />
        {briefing.isError ? <ErrorBlock error={briefing.error} what="Your briefing" onRetry={briefing.retry} /> : <LoadingBriefing />}
      </Page>
    );
  }

  const isFallback = view.status === "fallback";
  const sections = isFallback ? [] : sectionModels(view, true);
  const main = sections.filter((section) => MAIN_SECTIONS.has(section.code));
  const side = sections.filter((section) => section.code === "handled_for_you" || section.code === "coming_next");
  const changes = sections.find((section) => section.code === "changes_since_last_visit");
  const total = (code: SectionCode) => view.sections.find((section) => section.code === code)?.total ?? 0;

  // The single gold button on the screen belongs to the first item that has something to do.
  const leadItem = main.flatMap((section) => section.items).find((item) => {
    const action = primaryAction(item);
    return action !== null && action.action !== "explain";
  });

  const day = (view.work_date && formatBusinessDate(view.work_date, zone.locale, "long")) || formatLongDate(now, zone);
  const generated = parseInstant(view.generated_at);
  const asOfIso = view.data_as_of || view.generated_at || view.fallback?.error_at || "";
  const asOf = formatDayTime(asOfIso, now, zone) ?? asOfIso;
  const summary = summaryStatus(view, (iso) => formatTime(parseInstant(iso) ?? now, zone));
  const whatsappDemo = bootstrap.integration_modes?.whatsapp === "demo";
  const lastSeen = view.last_ack ? formatDayTime(view.last_ack.acknowledged_at, now, zone) : null;
  const overdue = main.find((section) => section.code === "needs_you_now")?.items.filter((item) => item.overdue).length ?? 0;

  const menu: MenuItem[] = [
    { id: "refresh", label: "Refresh the briefing", icon: "refresh", onAction: () => void briefing.refresh(), isDisabled: briefing.isFetching },
    ...(briefing.canSendSummary
      ? [
          {
            id: "summary",
            label: "Send the summary to WhatsApp",
            icon: "send" as const,
            description: whatsappDemo ? "Demo: not delivered to a phone" : undefined,
            onAction: () => void briefing.sendSummary(),
            isDisabled: offline || briefing.sendingSummary,
          },
        ]
      : []),
    { separator: true, id: "sep" },
    { id: "changes", label: "What changed", icon: "history", href: "/today/changes" as Route },
    { id: "all", label: "All of today", icon: "list", href: allHref() },
  ];

  return (
    <Page>
      <TodayHero
        date={day}
        lead={isFallback ? "Today's briefing could not be prepared. Your open tasks are below." : (view.overview?.text ?? leadFromCounts(view))}
        meta={
          <>
            {generated ? <span className="lk-tnum">Updated {formatTime(generated, zone)}</span> : null}
            {view.ai_status === "demo" ? (
              <span title="Worded by the Demo phraser from the same facts. No AI provider is connected.">
                <Badge size="sm" outline>
                  Demo
                </Badge>
                <span className="lk-sr-only">: worded by the Demo phraser from the same facts. No AI provider is connected.</span>
              </span>
            ) : view.ai_status === "unavailable" && view.overview?.text_source === "template" ? (
              <span title="The assistant's phrasing is unavailable, so this is the standard template text.">
                <Badge size="sm" outline>
                  Standard wording
                </Badge>
              </span>
            ) : null}
            {summary ? (
              <span className="flex flex-wrap items-center gap-2" data-testid="whatsapp-summary">
                <Icon name="message" size={14} />
                {summary.text}
                {summary.demo ? (
                  <Badge size="sm" outline>
                    Demo
                  </Badge>
                ) : null}
              </span>
            ) : null}
          </>
        }
        aside={
          isFallback ? null : (
            <GlassPanel as="section" padding="md" aria-label="Today at a glance" className="grid grid-cols-2 gap-x-5 gap-y-6">
              {TILES.map((code) => (
                <StatTile
                  key={code}
                  className="min-w-0"
                  label={SECTION_LABEL[code]}
                  value={<Count value={total(code)} />}
                  dot={code === "needs_you_now" && total(code) > 0}
                  foot={code === "needs_you_now" && overdue > 0 ? <span className="text-ember-text">{overdue} overdue</span> : undefined}
                  href={allHref({ group: code })}
                />
              ))}
            </GlassPanel>
          )
        }
        actions={
          <>
            {!isFallback && listen.state.phase === "idle" ? (
              <Button variant="secondary" iconLeft="play" isDisabled={offline || view.briefing_id === null} onPress={() => void listen.start()}>
                Listen to my day
              </Button>
            ) : null}
            <Menu label="Briefing actions" items={menu} trigger={<IconButton icon="more" label="Briefing actions" />} />
          </>
        }
      />

      {!isFallback ? <ListenPanel listen={listen} voiceLabel={speech.label} /> : null}

      {update ? (
        <Banner
          tone="gold"
          title={updateSentence(update)}
          action={
            <Button variant="inverse" size="sm" onPress={briefing.showLatest}>
              {update.kind === "updates" ? "Show updates" : "Show briefing"}
            </Button>
          }
        >
          The list stays as it is until you ask.
        </Banner>
      ) : null}

      {offline ? (
        <Banner
          tone="amber"
          icon="globe"
          title="You are offline."
          action={
            <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => void briefing.refresh()}>
              Try again
            </Button>
          }
        >
          This is the briefing as of {asOf}. Actions wait until the connection is back.
        </Banner>
      ) : briefing.isError ? (
        <Banner
          tone="amber"
          title="The briefing could not refresh."
          action={
            <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => void briefing.refresh()}>
              Refresh
            </Button>
          }
        >
          You are looking at the version from {asOf}.
        </Banner>
      ) : null}

      {view.day_type !== "working" ? <Banner icon="calendar">Today is not a working day. Only deadlines that cannot wait are shown.</Banner> : null}
      {view.partial_families.length > 0 ? (
        <Banner tone="amber" title="Some checks are unavailable.">
          Missing for now: {view.partial_families.map((family) => family.label).join(", ")}. Everything else below is complete.
        </Banner>
      ) : null}

      {isFallback && view.fallback ? (
        <Fallback fallback={view.fallback} now={now} zone={zone} retrying={briefing.isFetching} onRetry={() => void briefing.refresh()} />
      ) : (
        <>
          <ChangesLine
            count={changes?.total ?? 0}
            lastSeen={lastSeen}
            canAcknowledge={briefing.canAcknowledge}
            acknowledging={briefing.acknowledging}
            offline={offline}
            onAcknowledge={() => void briefing.acknowledge()}
          />

          {main.length === 0 && side.length === 0 ? (
            <GlassPanel padding="lg" className="rise" style={riseAt(6)}>
              <EmptyState
                icon="checkCircle"
                title="Nothing needs you right now"
                text="New approvals, customer replies and deadlines appear here as they happen."
                actions={
                  <ButtonLink href="/inbox" variant="secondary" iconRight="arrowRight">
                    Open the Inbox
                  </ButtonLink>
                }
              />
            </GlassPanel>
          ) : (
            <div id={listId} className={side.length > 0 ? "split" : undefined}>
              <div className="stack gap-8">
                {main.length === 0 ? (
                  <GlassPanel padding="lg" className="rise" style={riseAt(6)}>
                    <EmptyState icon="checkCircle" title="Nothing is waiting on you" text="The rest of the day is on the right." compact />
                  </GlassPanel>
                ) : (
                  main.map((section, index) => (
                    <Group key={section.code} section={section} index={index} now={now} zone={zone} commands={commands} leadItemId={leadItem?.id ?? null} />
                  ))
                )}
              </div>
              <aside className="stack gap-8">
                {side.map((section, index) => (
                  <QuietGroup key={section.code} section={section} index={index} now={now} zone={zone} />
                ))}
              </aside>
            </div>
          )}
        </>
      )}

      {bootstrap.capabilities.assistant ? <TodayAssistant /> : null}

      <ItemDialogs commands={commands} />
    </Page>
  );
}

function GroupHead({ id, section, shown }: { id: string; section: SectionModel; shown: number }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-3">
      <h2 id={id} className="t-h2 flex items-baseline gap-3">
        {section.title}
        <span className="t-stat-sm text-ink-3">
          <Count value={section.total} />
        </span>
      </h2>
      {section.total > shown ? (
        <TextLink href={allHref({ group: section.code })} className="t-label">
          See all {section.total}
        </TextLink>
      ) : null}
    </div>
  );
}

/** A group of items that need action, showing its first few; the rest are one link away. */
function Group({
  section,
  index,
  now,
  zone,
  commands,
  leadItemId,
}: {
  section: SectionModel;
  index: number;
  now: Date;
  zone: ZoneOptions;
  commands: ItemCommands;
  leadItemId: string | null;
}) {
  const headingId = useId();
  const items = section.items.slice(0, SHOWN[section.code] ?? 3);
  const titled: SectionModel = { ...section, title: SECTION_LABEL[section.code] ?? section.title };
  return (
    <section aria-labelledby={headingId} className="rise flex flex-col gap-4" style={riseAt(5 + index)}>
      <GroupHead id={headingId} section={titled} shown={items.length} />
      <GlassPanel padding="none">
        <ol className="m-0 list-none p-0">
          {items.map((item, row) => (
            <ItemRow key={item.id} item={item} now={now} zone={zone} commands={commands} emphasis={item.id === leadItemId} index={row} />
          ))}
        </ol>
      </GlassPanel>
    </section>
  );
}

/** The groups that need nothing from the person: handled for you, coming next. */
function QuietGroup({ section, index, now, zone }: { section: SectionModel; index: number; now: Date; zone: ZoneOptions }) {
  const headingId = useId();
  const items = section.items.slice(0, SHOWN[section.code] ?? 4);
  const handled = section.code === "handled_for_you";
  return (
    <section aria-labelledby={headingId} className="rise flex flex-col gap-4" style={riseAt(6 + index)}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id={headingId} className="t-h3 flex items-center gap-2">
          <span className={handled ? "text-leaf-text flex" : "text-ink-3 flex"}>
            <Icon name={handled ? "checkCircle" : "clock"} size={18} />
          </span>
          {SECTION_LABEL[section.code] ?? section.title}
        </h2>
        {section.total > items.length ? (
          <TextLink href={allHref({ group: section.code })} className="t-label">
            See all {section.total}
          </TextLink>
        ) : null}
      </div>
      <GlassPanel padding="none">
        <ol className="m-0 list-none p-0">
          {items.map((item, row) => (
            <CompactItem key={item.id} item={item} now={now} zone={zone} index={row} />
          ))}
        </ol>
      </GlassPanel>
    </section>
  );
}

/** What moved since the last visit, as one line that leads to its own screen. */
function ChangesLine({
  count,
  lastSeen,
  canAcknowledge,
  acknowledging,
  offline,
  onAcknowledge,
}: {
  count: number;
  lastSeen: string | null;
  canAcknowledge: boolean;
  acknowledging: boolean;
  offline: boolean;
  onAcknowledge: () => void;
}) {
  return (
    <GlassPanel padding="sm" className="rise flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6" style={riseAt(5)}>
      <div className="flex items-center gap-3 sm:pl-1">
        <span className="text-ink-3 flex flex-none">
          <Icon name="history" size={20} />
        </span>
        <p className="t-body text-ink">
          <span className="t-h4">{count === 0 ? "Nothing new since your last visit" : `${plural(count, "thing", "things")} changed since your last visit`}</span>
          {lastSeen ? <span className="text-ink-3 lk-tnum"> · last seen {lastSeen}</span> : null}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {canAcknowledge ? (
          <Button variant="ghost" size="sm" iconLeft="check" loading={acknowledging} isDisabled={offline} onPress={onAcknowledge}>
            Mark as seen
          </Button>
        ) : null}
        <ButtonLink href={(count === 0 ? "/today/changes?since=yesterday" : "/today/changes") as Route} variant="secondary" size="sm" iconRight="arrowRight">
          {count === 0 ? "Look back to yesterday" : "See what changed"}
        </ButtonLink>
      </div>
    </GlassPanel>
  );
}

/** Skeletons shaped like the screen: four counts, then a group of items beside the quieter column. */
function LoadingBriefing() {
  return (
    <div role="status" aria-label="Loading your briefing" className="flex flex-col gap-6">
      <GlassPanel padding="sm">
        <Skeleton width="40%" height={16} />
      </GlassPanel>
      <Skeleton width={180} height={24} />
      <GlassPanel padding="lg" className="flex flex-col gap-8">
        <SkeletonText lines={3} />
        <SkeletonText lines={3} />
        <SkeletonText lines={3} />
      </GlassPanel>
    </div>
  );
}

/**
 * The briefing could not be prepared: say so with the time, offer another try, and still give the
 * person a list to work from (their open tasks, then the last briefing, read-only).
 */
function Fallback({
  fallback,
  now,
  zone,
  retrying,
  onRetry,
}: {
  fallback: BriefingFallback;
  now: Date;
  zone: ZoneOptions;
  retrying: boolean;
  onRetry: () => void;
}) {
  const failedAt = formatDayTime(fallback.error_at, now, zone) ?? fallback.error_at;
  const last = fallback.last_successful;
  const lastAt = last ? (formatDayTime(last.generated_at, now, zone) ?? last.generated_at) : null;
  return (
    <>
      <Banner
        tone="amber"
        title="Today's briefing could not be prepared."
        action={
          <Button variant="secondary" size="sm" iconLeft="refresh" loading={retrying} onPress={onRetry}>
            Try again
          </Button>
        }
      >
        The last attempt was at {failedAt}. {lastAt ? `Below are your open tasks and the last briefing, from ${lastAt}.` : "Below are your open tasks."}
      </Banner>

      <section aria-labelledby="fallback-tasks" className="rise flex flex-col gap-4" style={riseAt(4)}>
        <h2 id="fallback-tasks" className="t-h2">
          Your open tasks
        </h2>
        <GlassPanel padding="none">
          {fallback.tasks.length === 0 ? (
            <EmptyState icon="checkCircle" title="No open tasks" text="Nothing is assigned to you right now." compact />
          ) : (
            <ol className="m-0 list-none p-0">
              {fallback.tasks.map((task, index) => {
                const due = dueText(task, now, zone);
                return (
                  <li key={task.id} className="rise-plain border-line flex flex-col gap-1 border-t px-5 py-4 first:border-t-0" style={riseAt(index)}>
                    {task.source?.href ? (
                      <TextLink href={task.source.href as Route} className="t-h4">
                        {task.title}
                      </TextLink>
                    ) : (
                      <span className="t-h4 text-ink">{task.title}</span>
                    )}
                    <span className="t-body-sm text-ink-3 flex flex-wrap gap-x-3">
                      {due ? <span className={task.overdue ? "lk-tnum text-ember-text" : "lk-tnum"}>{due}</span> : null}
                      {task.source ? <span>{task.source.label}</span> : null}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </GlassPanel>
      </section>

      {last && last.items.length > 0 ? (
        <section aria-labelledby="fallback-last" className="rise flex flex-col gap-4" style={riseAt(5)}>
          <div className="flex flex-col gap-1">
            <h2 id="fallback-last" className="t-h2">
              Last briefing, {lastAt}
            </h2>
            {last.overview ? <p className="t-body text-ink-2">{last.overview.text}</p> : null}
          </div>
          <GlassPanel padding="none">
            <ol className="m-0 list-none p-0">
              {last.items.map((item: BriefingItem, index) => (
                <ItemRow key={item.id} item={item} now={now} zone={zone} index={index} />
              ))}
            </ol>
          </GlassPanel>
        </section>
      ) : null}
    </>
  );
}
