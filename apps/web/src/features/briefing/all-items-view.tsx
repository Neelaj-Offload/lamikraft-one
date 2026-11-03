"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { briefingMessages as m } from "@/messages/briefing";
import { fetchToday } from "./api";
import { SECTION_CODES } from "./parse";
import type { BriefingItem, BriefingView, SectionCode } from "./types";

type SectionFilter = SectionCode | "all" | "snoozed";

export interface AllItemsFilter {
  section: SectionFilter;
  family: string | null;
}

/** Every item of the briefing (and the snoozed ones) by section, narrowed by section and kind. */
export function filterItems(view: BriefingView, filter: AllItemsFilter): { code: SectionCode | "snoozed"; items: BriefingItem[] }[] {
  const byFamily = (item: BriefingItem) => filter.family === null || item.family === filter.family;
  const groups: { code: SectionCode | "snoozed"; items: BriefingItem[] }[] = SECTION_CODES.map((code) => ({
    code,
    items: view.items.filter((item) => item.section === code && byFamily(item)),
  }));
  groups.push({ code: "snoozed", items: view.snoozed.filter(byFamily) });
  return groups.filter((group) => group.items.length > 0 && (filter.section === "all" || filter.section === group.code));
}

/**
 * All of today (route `today-all`): every section of the briefing on one page with filters. The order is the
 * briefing's own (the server's display order); nothing is re-ranked here.
 */
export function AllItemsView() {
  const query = useQuery({ queryKey: queryKeys.briefings.today(), queryFn: ({ signal }) => fetchToday(signal) });
  const [filter, setFilter] = useState<AllItemsFilter>({ section: "all", family: null });
  const view = query.data ?? null;

  if (!view) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title={m.all.title} intro={m.all.description} />
        {query.isError ? <ErrorState error={query.error} what="your briefing" onRetry={() => void query.refetch()} /> : <Loading label="your briefing" />}
      </div>
    );
  }
  const families = [...new Set([...view.items, ...view.snoozed].map((item) => item.family))];
  const sectionOptions = [
    { id: "all", label: m.all.everything },
    ...SECTION_CODES.filter((code) => view.items.some((item) => item.section === code)).map((code) => ({ id: code, label: m.sections[code] })),
    ...(view.snoozed.length > 0 ? [{ id: "snoozed", label: m.all.snoozed }] : []),
  ];
  const familyOptions = [{ id: "", label: m.all.everything }, ...families.map((family) => ({ id: family, label: m.status[family] ?? m.status.fallback! }))];
  const groups = filterItems(view, filter);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.all.title} intro={m.all.description} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-2xl">
        <Select
          label={m.all.section}
          options={sectionOptions}
          value={filter.section}
          onChange={(value) => setFilter((current) => ({ ...current, section: (value as SectionFilter | null) ?? "all" }))}
        />
        <Select
          label={m.all.family}
          options={familyOptions}
          value={filter.family ?? ""}
          onChange={(value) => setFilter((current) => ({ ...current, family: value ? value : null }))}
        />
      </div>
      {groups.length === 0 ? (
        <EmptyState title={m.all.empty}>{m.all.description}</EmptyState>
      ) : (
        groups.map((group) => (
          <SectionCard
            key={group.code}
            title={group.code === "snoozed" ? m.all.snoozed : m.sections[group.code]}
            description={m.all.count(group.items.length)}
          >
            <ul className="flex flex-col divide-y divide-border">
              {group.items.map((item) => (
                <li key={item.issue_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3 first:pt-0 last:pb-0">
                  <Badge tone="neutral">{m.status[item.family] ?? m.status.fallback}</Badge>
                  <Link href={`/today/items/${encodeURIComponent(item.issue_id)}`} className="font-medium">
                    {item.title}
                  </Link>
                  {item.due_label ? <span className="text-sm text-ink-muted tabular">{item.due_label}</span> : null}
                  {item.overdue ? <Badge tone="danger">{m.item.overdue}</Badge> : null}
                </li>
              ))}
            </ul>
          </SectionCard>
        ))
      )}
    </div>
  );
}
