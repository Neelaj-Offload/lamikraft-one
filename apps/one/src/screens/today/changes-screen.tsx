"use client";

import type { Route } from "next";
import { DELTA_SINCE, type DeltaSince, type WireDeltaChange, type WireDeltaGroup } from "@/features/briefing/slice3-api";
import { appLinkFor } from "@/lib/app-links";
import { formatDayTime } from "@/lib/format/time";
import { useNow, useSession } from "@/lib/session/context";
import { changeKind, changeValues, useChanges } from "~/data/today";
import { riseAt } from "./rise";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Button, ButtonLink, DateText, EmptyState, GlassPanel, SegmentedLinks, SkeletonText, TextLink, Timeline, type TimelineItem, type Tone } from "~/ui";
import type { IconName } from "~/ui/icon";

const SINCE_LABEL: Record<DeltaSince, string> = {
  last_ack: "Your last visit",
  yesterday: "Yesterday",
  last_workday: "Your last workday",
};

const SINCE_PHRASE: Record<DeltaSince, string> = {
  last_ack: "since your last visit",
  yesterday: "since yesterday",
  last_workday: "since your last workday",
};

const KIND_LOOK: Record<string, { icon: IconName; tone: Tone }> = {
  created: { icon: "plus", tone: "gold" },
  resolved: { icon: "checkCircle", tone: "leaf" },
  reopened: { icon: "undo", tone: "amber" },
  assigned: { icon: "userPlus", tone: "cobalt" },
  status_changed: { icon: "flag", tone: "cobalt" },
  revised: { icon: "edit", tone: "cobalt" },
};

function sinceHref(since: DeltaSince): Route {
  return (since === "last_ack" ? "/today/changes" : `/today/changes?since=${since}`) as Route;
}

/**
 * What changed: the change log behind the briefing since a chosen moment, grouped by kind and by
 * item. Each entry says what happened, who did it, the values before and after, and links to the
 * record. The server only returns changes this person may see.
 */
export function ChangesScreen({ since }: { since: DeltaSince }) {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const { query, families, window, changeCount } = useChanges(since);

  const from = window ? (formatDayTime(window.since_instant, now, zone) ?? window.since_instant) : null;
  const to = window ? (formatDayTime(window.until_instant, now, zone) ?? window.until_instant) : null;
  const more = query.hasNextPage;
  const itemCount = families.reduce((sum, family) => sum + family.groups.length, 0);

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[{ label: "Today", href: "/today" }, { label: "What changed" }]}
        title="What changed"
        lead={
          query.isPending || query.isError
            ? "Every change behind your briefing, with a link to the record."
            : changeCount === 0
              ? `Nothing moved ${SINCE_PHRASE[since]}.`
              : `${changeCount === 1 ? "1 change" : `${changeCount}${more ? " or more" : ""} changes`} across ${itemCount === 1 ? "1 item" : `${itemCount} items`} ${SINCE_PHRASE[since]}.`
        }
      />

      <div className="rise flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <SegmentedLinks
          label="Changes since"
          glass
          value={since}
          options={DELTA_SINCE.map((option) => ({ value: option, label: SINCE_LABEL[option], href: sinceHref(option) }))}
        />
        {from && to ? (
          <p className="t-body-sm lk-tnum text-ink-3">
            {from} to {to}
          </p>
        ) : null}
      </div>

      {query.isPending ? (
        <GlassPanel padding="lg" role="status" aria-label="Loading the changes" className="flex flex-col gap-8">
          <SkeletonText lines={3} />
          <SkeletonText lines={3} />
        </GlassPanel>
      ) : query.isError ? (
        <ErrorBlock error={query.error} what="The changes" onRetry={() => void query.refetch()} />
      ) : families.length === 0 ? (
        <GlassPanel padding="lg" className="rise">
          <EmptyState
            icon="history"
            title="Nothing changed in this period"
            text={since === "last_ack" ? "You are up to date. Look further back to see earlier changes." : "Your briefing is as you left it."}
            actions={
              since === "last_ack" ? (
                <ButtonLink href={sinceHref("yesterday")} variant="secondary">
                  Look back to yesterday
                </ButtonLink>
              ) : (
                <ButtonLink href="/today" variant="secondary">
                  Back to Today
                </ButtonLink>
              )
            }
          />
        </GlassPanel>
      ) : (
        families.map((family, index) => (
          <section key={family.family} aria-label={family.label} className="rise flex flex-col gap-4" style={riseAt(index + 1)}>
            <h2 className="t-h2 flex items-baseline gap-3">
              {family.label}
              <span className="t-stat-sm text-ink-3">{family.groups.length}</span>
            </h2>
            <GlassPanel padding="none">
              <ul className="m-0 list-none p-0">
                {family.groups.map((group) => (
                  <ChangeGroup key={group.issue_id} group={group} />
                ))}
              </ul>
            </GlassPanel>
          </section>
        ))
      )}

      {more ? (
        <div>
          <Button variant="secondary" loading={query.isFetchingNextPage} onPress={() => void query.fetchNextPage()}>
            Show earlier changes
          </Button>
        </div>
      ) : null}
    </Page>
  );
}

function ChangeGroup({ group }: { group: WireDeltaGroup }) {
  const items: TimelineItem[] = group.changes.map((change, index) => {
    const kind = changeKind(change.change_code);
    const look = KIND_LOOK[kind.key];
    return {
      id: `${change.fact_at}:${index}`,
      title: change.actor?.name ? `${kind.label} by ${change.actor.name}` : kind.label,
      meta: <DateText value={change.fact_at} style="dayTime" />,
      body: <ChangeBody change={change} />,
      icon: look?.icon,
      tone: look?.tone,
    };
  });
  return (
    <li className="border-line flex flex-col gap-4 border-t p-5 first:border-t-0 md:p-6" data-testid="delta-group">
      <h3 className="t-h3">{group.title}</h3>
      <Timeline label={`Changes to ${group.title}`} items={items} />
    </li>
  );
}

function ChangeBody({ change }: { change: WireDeltaChange }) {
  const href = change.source?.path ? appLinkFor(change.source.path) : null;
  const before = changeValues(change.before);
  const after = changeValues(change.after);
  if (!href && !change.source?.label && before.length === 0 && after.length === 0) return null;
  return (
    <div className="flex flex-col gap-2" data-testid="delta-change">
      {before.length > 0 || after.length > 0 ? (
        <dl className="t-body-sm m-0 flex flex-col gap-1">
          {before.length > 0 ? (
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-ink-3">Before</dt>
              <dd className="lk-tnum text-ink-2 m-0">{before.map((pair) => `${pair.key}: ${pair.value}`).join(", ")}</dd>
            </div>
          ) : null}
          {after.length > 0 ? (
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-ink-3">After</dt>
              <dd className="lk-tnum text-ink m-0">{after.map((pair) => `${pair.key}: ${pair.value}`).join(", ")}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {href ? (
        <p className="t-body-sm">
          <TextLink href={href as Route}>{change.source?.label || "Open the record"}</TextLink>
        </p>
      ) : change.source?.label ? (
        <p className="t-body-sm text-ink-3">{change.source.label}</p>
      ) : null}
    </div>
  );
}
