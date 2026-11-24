"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { fetchToday } from "@/features/briefing/api";
import { SECTION_CODES } from "@/features/briefing/parse";
import { useNow, useSession } from "@/lib/session/context";
import { dueText, familyLabel, itemHref, itemTone, kindLabel, SECTION_LABEL, TODAY_KEY } from "~/data/today";
import { Page, PageHeader } from "~/shell/page";
import { QueryView } from "~/shell/states";
import { Badge, ButtonLink, ChipGroup, ChipLink, DataTable, EmptyState, GlassPanel, Select, TableFooter, type Column } from "~/ui";
import { allHref, allRows, filterRows, type AllFilter, type AllRow, type GroupFilter } from "./all-state";

const EVERY_KIND = "all";

/**
 * All of today: every item of the briefing, and the snoozed ones, in the briefing's own order.
 * The group and kind filters live in the URL, so a filtered view can be shared and the back
 * button works. Each row opens the item's own screen.
 */
export function AllItemsScreen({ filter }: { filter: AllFilter }) {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const router = useRouter();
  const query = useQuery({ queryKey: TODAY_KEY, queryFn: ({ signal }) => fetchToday(signal) });

  const columns: Column<AllRow>[] = [
    {
      key: "item",
      header: "Item",
      primary: true,
      cell: ({ item }) => (
        <span className="flex min-w-0 flex-col gap-1">
          <span>{item.title}</span>
          {item.summary_text ? <span className="t-body-sm lk-tnum text-ink-3 line-clamp-1">{item.summary_text}</span> : null}
        </span>
      ),
    },
    {
      key: "kind",
      header: "Kind",
      width: "190px",
      cell: ({ item }) => (
        <Badge tone={itemTone(item)} dot>
          {kindLabel(item)}
        </Badge>
      ),
    },
    { key: "group", header: "Group", width: "170px", cell: ({ group }) => SECTION_LABEL[group] },
    {
      key: "due",
      header: "Due",
      width: "270px",
      cell: ({ item }) => {
        const due = dueText(item, now, zone);
        return due ? <span className={item.overdue ? "lk-tnum text-ember-text" : "lk-tnum"}>{due}</span> : <span className="text-ink-3">No deadline</span>;
      },
    },
    {
      key: "state",
      header: "Since last visit",
      width: "150px",
      hideOnMobile: true,
      cell: ({ item }) =>
        item.change_kind === "new" ? (
          <Badge tone="gold" size="sm">
            New
          </Badge>
        ) : item.change_kind === "changed" ? (
          <Badge tone="cobalt" size="sm">
            Changed
          </Badge>
        ) : (
          <span className="text-ink-3">No change</span>
        ),
    },
  ];

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Today", href: "/today" }, { label: "All of today" }]}
        title="All of today"
        lead="Every item in today's briefing, in the order the briefing ranks them."
      />
      <QueryView
        query={query}
        what="Your briefing"
        loading={
          <GlassPanel padding="none">
            <DataTable label="Briefing items" columns={columns} rows={[]} rowKey={(row) => row.item.id} loading />
          </GlassPanel>
        }
      >
        {(view) => {
          const rows = allRows(view);
          const shown = filterRows(rows, filter);
          const inGroup = (group: GroupFilter) => filterRows(rows, { group, kind: filter.kind }).length;
          const groups: GroupFilter[] = [...SECTION_CODES.filter((code) => rows.some((row) => row.group === code)), ...(view.snoozed.length > 0 ? (["snoozed"] as const) : [])];
          const families = [...new Set(rows.map((row) => row.item.family))];
          const kindKnown = filter.kind !== null && families.includes(filter.kind);

          return (
            <>
              <div className="rise flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
                <ChipGroup label="Filter by group">
                  <ChipLink href={allHref({ kind: filter.kind })} selected={filter.group === "all"} count={inGroup("all")} scroll={false}>
                    Everything
                  </ChipLink>
                  {groups.map((group) => (
                    <ChipLink key={group} href={allHref({ group, kind: filter.kind })} selected={filter.group === group} count={inGroup(group)} scroll={false}>
                      {SECTION_LABEL[group]}
                    </ChipLink>
                  ))}
                </ChipGroup>
                {families.length > 1 ? (
                  <Select
                    label="Kind"
                    hideLabel
                    size="sm"
                    glass
                    className="w-full sm:w-56"
                    options={[{ value: EVERY_KIND, label: "Every kind" }, ...families.map((family) => ({ value: family, label: familyLabel(family) }))]}
                    value={kindKnown ? filter.kind : EVERY_KIND}
                    onChange={(value) => router.replace(allHref({ group: filter.group, kind: value === EVERY_KIND ? null : value }), { scroll: false })}
                  />
                ) : null}
              </div>

              <GlassPanel padding="none" className="rise" style={{ "--i": 1 } as React.CSSProperties}>
                <DataTable
                  label="Briefing items"
                  columns={columns}
                  rows={shown}
                  rowKey={(row) => `${row.group}:${row.item.id}`}
                  rowHref={(row) => itemHref(row.item.issue_id) as Route}
                  empty={
                    rows.length === 0 ? (
                      <EmptyState
                        icon="checkCircle"
                        title="Today's briefing is empty"
                        text="New approvals, customer replies and deadlines appear here as they happen."
                        actions={
                          <ButtonLink href="/today" variant="secondary">
                            Back to Today
                          </ButtonLink>
                        }
                        compact
                      />
                    ) : (
                      <EmptyState
                        icon="filter"
                        title="No items match these filters"
                        text="Clear the filters to see everything in today's briefing."
                        actions={
                          <ButtonLink href={allHref()} variant="secondary">
                            Show everything
                          </ButtonLink>
                        }
                        compact
                      />
                    )
                  }
                  footer={
                    <TableFooter
                      left={
                        <p className="lk-page-summary">
                          {shown.length === rows.length ? `${rows.length} ${rows.length === 1 ? "item" : "items"}` : `${shown.length} of ${rows.length} items`}
                        </p>
                      }
                    />
                  }
                />
              </GlassPanel>
            </>
          );
        }}
      </QueryView>
    </Page>
  );
}
