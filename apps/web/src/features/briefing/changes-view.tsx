"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { NavTabs } from "@/components/ui/tabs";
import { queryKeys } from "@/lib/api/query-keys";
import { appLinkFor } from "@/lib/app-links";
import { formatDayTime } from "@/lib/format/time";
import { useNow, useSession } from "@/lib/session/context";
import { briefingMessages as m } from "@/messages/briefing";
import { DELTA_SINCE, fetchDelta, type DeltaSince, type WireDeltaChange, type WireDeltaGroup } from "./slice3-api";

export function deltaSinceFrom(value: unknown): DeltaSince {
  const raw = Array.isArray(value) ? value[0] : value;
  return DELTA_SINCE.find((since) => since === raw) ?? "last_ack";
}

/** "sales.quote.changed" -> "Changed"; unknown codes become readable words, never raw identifiers. */
export function changeKindLabel(code: string): string {
  const last = code.split(".").pop() ?? code;
  return m.changes.kinds[last] ?? (last.charAt(0).toUpperCase() + last.slice(1)).replaceAll("_", " ");
}

function values(record: Record<string, unknown> | null | undefined): string | null {
  if (!record) return null;
  const parts = Object.entries(record)
    .filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`);
  return parts.length > 0 ? parts.join(", ") : null;
}

/** Issues grouped by their rule family, in the order the server returned them (fact time). */
export function groupByFamily(groups: readonly WireDeltaGroup[]): { family: string; label: string; groups: WireDeltaGroup[] }[] {
  const out = new Map<string, { family: string; label: string; groups: WireDeltaGroup[] }>();
  for (const group of groups) {
    const existing = out.get(group.family);
    if (existing) existing.groups.push(group);
    else out.set(group.family, { family: group.family, label: m.status[group.family] ?? m.status.fallback!, groups: [group] });
  }
  return [...out.values()];
}

/**
 * "What changed" (briefing.md §8; route `today-changes`): the source-linked change log since the chosen cursor,
 * grouped by family and issue, each row with the change kind, who made it, before and after, and the record.
 * Only changes the member may see are returned (the server re-checks every source).
 */
export function ChangesView({ since }: { since: DeltaSince }) {
  const { zone } = useSession();
  const now = useNow() ?? new Date();
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
  const families = groupByFamily([...merged.values()]);
  const first = pages[0];
  const tabs = DELTA_SINCE.map((option) => ({ id: option, label: m.changes.sinceOptions[option] ?? option, href: `/today/changes?since=${option}` }));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.changes.title} intro={m.changes.description} nav={<NavTabs label={m.changes.since} tabs={tabs} currentId={since} />} />
      {first ? (
        <p className="text-sm text-ink-muted tabular">
          {m.changes.window(formatDayTime(first.since_instant, now, zone) ?? first.since_instant, formatDayTime(first.until_instant, now, zone) ?? first.until_instant)}
        </p>
      ) : null}
      {query.isPending ? (
        <Loading label="the changes" />
      ) : query.isError ? (
        <ErrorState error={query.error} what="the changes" onRetry={() => void query.refetch()} />
      ) : families.length === 0 ? (
        <EmptyState title={m.changes.empty}>{m.changes.description}</EmptyState>
      ) : (
        families.map((family) => (
          <SectionCard key={family.family} title={family.label}>
            <ul className="flex flex-col divide-y divide-border">
              {family.groups.map((group) => (
                <li key={group.issue_id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
                  <p className="font-medium text-ink">{group.title}</p>
                  <ul className="flex flex-col gap-2">
                    {group.changes.map((change, index) => (
                      <ChangeRow key={`${change.fact_at}:${index}`} change={change} now={now} zone={zone} />
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </SectionCard>
        ))
      )}
      {query.hasNextPage ? (
        <div>
          <Button variant="secondary" onPress={() => void query.fetchNextPage()} isPending={query.isFetchingNextPage} pendingLabel={m.changes.more}>
            {m.changes.more}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ChangeRow({ change, now, zone }: { change: WireDeltaChange; now: Date; zone: ReturnType<typeof useSession>["zone"] }) {
  const href = change.source?.path ? appLinkFor(change.source.path) : null;
  const before = values(change.before);
  const after = values(change.after);
  return (
    <li className="flex flex-col gap-1 text-sm" data-testid="delta-change">
      <p className="flex flex-wrap items-center gap-x-2 text-ink">
        <span className="font-medium">{changeKindLabel(change.change_code)}</span>
        <span className="text-ink-muted tabular">{formatDayTime(change.fact_at, now, zone) ?? change.fact_at}</span>
        {change.actor?.name ? <span className="text-ink-muted">{m.changes.by(change.actor.name)}</span> : null}
        {href ? (
          <Link href={href} className="ms-auto">
            {change.source?.label || m.changes.record}
          </Link>
        ) : change.source?.label ? (
          <span className="ms-auto text-ink-muted">{change.source.label}</span>
        ) : null}
      </p>
      {before || after ? (
        <p className="text-ink-muted">
          {before ? <span>{`${m.changes.before}: ${before}`}</span> : null}
          {before && after ? <span aria-hidden="true"> → </span> : null}
          {after ? <span>{`${m.changes.after}: ${after}`}</span> : null}
        </p>
      ) : null}
    </li>
  );
}
