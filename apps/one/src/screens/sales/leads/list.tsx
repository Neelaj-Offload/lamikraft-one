"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { useSession, useZone } from "@/lib/session/context";
import { LEADS_PAGE_SIZE, useLeadSources, useLeads, type LeadRow } from "~/data/leads";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Avatar,
  Badge,
  Button,
  ButtonLink,
  ChipGroup,
  ChipLink,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Menu,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  TableFooter,
  type Column,
  type MenuItem,
} from "~/ui";
import { countryName } from "../customers/labels";
import {
  followUpState,
  INTEREST_LABEL,
  INTERESTS,
  isoToday,
  LEAD_STAGE_LABEL,
  LEAD_STAGE_TONE,
  LEAD_STAGES,
  PRIORITIES,
  PRIORITY_LABEL,
  TEMPERATURE_LABEL,
  TEMPERATURES,
} from "./labels";
import { hasLeadFilters, leadListHref, leadQueryOf, type LeadListState, type LeadSort } from "./list-state";

const href = (state: Partial<LeadListState>) => leadListHref(state) as Route;

const SORT_LABEL: Record<LeadSort, string> = {
  follow_up: "Next follow-up first",
  recent: "Newest first contact",
  name: "Name, A to Z",
};

function columns(today: string): Column<LeadRow>[] {
  return [
    {
      key: "name",
      header: "Lead",
      primary: true,
      cell: (lead) => (
        <span className="flex min-w-0 items-center gap-3">
          <Avatar name={lead.display_name} size="sm" />
          <span className="flex min-w-0 flex-col">
            <span className="t-label truncate text-ink" title={lead.display_name}>
              {lead.display_name}
            </span>
            <span className="t-caption truncate text-ink-3">
              <span className="lk-mono">{lead.party_number}</span>
              {lead.lead_source ? ` · ${lead.lead_source.label}` : ""}
            </span>
          </span>
        </span>
      ),
    },
    {
      key: "stage",
      header: "Stage",
      cell: (lead) =>
        lead.lead_stage ? (
          <span className="flex flex-wrap items-center gap-1">
            <Badge tone={LEAD_STAGE_TONE[lead.lead_stage]} dot>
              {LEAD_STAGE_LABEL[lead.lead_stage]}
            </Badge>
            {lead.priority === "A" ? (
              <Badge outline size="sm">
                A
              </Badge>
            ) : null}
            {lead.temperature === "hot" ? (
              <Badge tone="ember" size="sm">
                Hot
              </Badge>
            ) : null}
          </span>
        ) : null,
    },
    {
      key: "follow",
      header: "Next follow-up",
      mobileLabel: "Follow up",
      cell: (lead) => {
        const state = followUpState(lead.next_follow_up_on, today);
        if (!lead.next_follow_up_on) return <span className="text-ink-3">None set</span>;
        return (
          <span className="flex items-center gap-2">
            <DateText value={lead.next_follow_up_on} />
            {state === "overdue" ? (
              <Badge tone="amber" size="sm" icon="clock">
                Overdue
              </Badge>
            ) : state === "today" ? (
              <Badge tone="gold" size="sm">
                Today
              </Badge>
            ) : null}
          </span>
        );
      },
    },
    { key: "contact", header: "Main contact", hideOnMobile: true, cell: (lead) => lead.primary_contact ?? <span className="text-ink-3">Not added</span> },
    { key: "country", header: "Country", hideOnMobile: true, cell: (lead) => countryName(lead.country_code) ?? lead.country_code },
    { key: "owner", header: "Looked after by", hideOnMobile: true, cell: (lead) => lead.owner.display_name ?? "" },
  ];
}

/** The lead pipeline: who to call next, filtered by stage, source, interest and follow-up. */
export function LeadList({ state }: { state: LeadListState }) {
  const router = useRouter();
  const { permissionKeys, bootstrap } = useSession();
  const zone = useZone();
  const today = isoToday(zone.timeZone);
  const query = useLeads(leadQueryOf(state, bootstrap.user.id));
  const sources = useLeadSources();
  const canCreate = permissionKeys.has("parties.party.create");
  const filtered = hasLeadFilters(state);
  const go = (next: Partial<LeadListState>) => router.push(href({ ...state, offset: 0, ...next }));
  const newHref = "/sales/parties/new?status=prospect" as Route;

  useScreenContribution(
    query.data
      ? {
          lists: [{ key: "leads", rows: query.data.items.map((lead, index) => ({ type: "parties.party", id: lead.id, version: null, ordinal: state.offset + index + 1 })) }],
          filters: {
            q: state.q,
            stage: state.stages.join(","),
            source: state.source ?? "",
            interest: state.interest ?? "",
            follow_up: state.follow_up ?? "",
            mine: state.mine,
          },
        }
      : null,
  );

  const tick = (on: boolean) => (on ? ("check" as const) : undefined);
  const activeSources = (sources.data ?? []).filter((s) => s.is_active || s.code === state.source);
  const filterMenu: MenuItem[] = [
    {
      id: "source",
      section: "Source",
      items: [
        { id: "source-any", label: "Any source", icon: tick(!state.source), href: href({ ...state, source: null, offset: 0 }) },
        ...activeSources.map((s) => ({ id: `source-${s.code}`, label: s.label, icon: tick(state.source === s.code), href: href({ ...state, source: s.code, offset: 0 }) })),
      ],
    },
    { id: "sep-interest", separator: true },
    {
      id: "interest",
      section: "Interested in",
      items: [
        { id: "interest-any", label: "Anything", icon: tick(!state.interest), href: href({ ...state, interest: null, offset: 0 }) },
        ...INTERESTS.map((i) => ({ id: `interest-${i}`, label: INTEREST_LABEL[i], icon: tick(state.interest === i), href: href({ ...state, interest: i, offset: 0 }) })),
      ],
    },
    { id: "sep-priority", separator: true },
    {
      id: "priority",
      section: "Priority",
      items: [
        { id: "priority-any", label: "Any priority", icon: tick(!state.priority), href: href({ ...state, priority: null, offset: 0 }) },
        ...PRIORITIES.map((p) => ({ id: `priority-${p}`, label: PRIORITY_LABEL[p], icon: tick(state.priority === p), href: href({ ...state, priority: p, offset: 0 }) })),
      ],
    },
    { id: "sep-temperature", separator: true },
    {
      id: "temperature",
      section: "Temperature",
      items: [
        { id: "temp-any", label: "Any", icon: tick(!state.temperature), href: href({ ...state, temperature: null, offset: 0 }) },
        ...TEMPERATURES.map((t) => ({ id: `temp-${t}`, label: TEMPERATURE_LABEL[t], icon: tick(state.temperature === t), href: href({ ...state, temperature: t, offset: 0 }) })),
      ],
    },
    { id: "sep-sort", separator: true },
    {
      id: "sort",
      section: "Order",
      items: (Object.keys(SORT_LABEL) as LeadSort[]).map((s) => ({ id: `sort-${s}`, label: SORT_LABEL[s], icon: tick(state.sort === s), href: href({ ...state, sort: s, offset: 0 }) })),
    },
  ];

  const limit = query.data?.limit || LEADS_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;
  const sourceLabel = state.source ? (sources.data?.find((s) => s.code === state.source)?.label ?? state.source) : null;
  const toggleStage = (stage: (typeof LEAD_STAGES)[number]) =>
    state.stages.includes(stage) ? state.stages.filter((s) => s !== stage) : [...state.stages, stage];

  return (
    <Page>
      <PageHeader
        eyebrow="Sales"
        title="Leads"
        lead="Everyone you are talking to who has not bought yet, with the next call at the top."
        actions={
          canCreate ? (
            <ButtonLink href={newHref} iconLeft="plus">
              Add lead
            </ButtonLink>
          ) : null
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={{ "--i": 1 } as React.CSSProperties}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SegmentedLinks
            label="Show"
            glass
            value="leads"
            options={[
              { value: "leads", label: "Leads", href: href({}) },
              { value: "customers", label: "Customers", href: "/sales/parties?status=active" as Route },
              { value: "all", label: "All", href: "/sales/parties" as Route },
            ]}
          />
          <SearchField
            key={state.q}
            className="min-w-0 flex-1 basis-64"
            label="Search leads"
            placeholder="Company, number or contact"
            defaultValue={state.q}
            onSubmit={(q) => go({ q })}
            onChange={(q) => {
              if (q === "" && state.q !== "") go({ q: "" });
            }}
          />
          <Menu
            label="More filters"
            items={filterMenu}
            placement="bottom end"
            trigger={
              <Button variant="secondary" iconLeft="filter">
                Filters
              </Button>
            }
          />
        </div>
        <ChipGroup label="Stage and follow-up">
          {LEAD_STAGES.filter((stage) => stage !== "won").map((stage) => (
            <ChipLink key={stage} href={href({ ...state, stages: toggleStage(stage), offset: 0 })} selected={state.stages.includes(stage)}>
              {LEAD_STAGE_LABEL[stage]}
            </ChipLink>
          ))}
          <ChipLink href={href({ ...state, follow_up: state.follow_up === "overdue" ? null : "overdue", offset: 0 })} selected={state.follow_up === "overdue"} icon="clock">
            Overdue
          </ChipLink>
          <ChipLink href={href({ ...state, follow_up: state.follow_up === "today" ? null : "today", offset: 0 })} selected={state.follow_up === "today"}>
            Due today
          </ChipLink>
          <ChipLink href={href({ ...state, follow_up: state.follow_up === "week" ? null : "week", offset: 0 })} selected={state.follow_up === "week"}>
            Next 7 days
          </ChipLink>
          <ChipLink href={href({ ...state, mine: !state.mine, offset: 0 })} selected={state.mine} icon="user">
            Mine
          </ChipLink>
        </ChipGroup>
        {state.source || state.interest || state.priority || state.temperature ? (
          <ChipGroup label="Filters in use">
            {sourceLabel ? (
              <ChipLink href={href({ ...state, source: null, offset: 0 })} selected icon="x">
                {sourceLabel}
              </ChipLink>
            ) : null}
            {state.interest ? (
              <ChipLink href={href({ ...state, interest: null, offset: 0 })} selected icon="x">
                {INTEREST_LABEL[state.interest]}
              </ChipLink>
            ) : null}
            {state.priority ? (
              <ChipLink href={href({ ...state, priority: null, offset: 0 })} selected icon="x">
                {PRIORITY_LABEL[state.priority]}
              </ChipLink>
            ) : null}
            {state.temperature ? (
              <ChipLink href={href({ ...state, temperature: null, offset: 0 })} selected icon="x">
                {TEMPERATURE_LABEL[state.temperature]}
              </ChipLink>
            ) : null}
          </ChipGroup>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Leads" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={{ "--i": 2 } as React.CSSProperties}>
          <DataTable
            label="Leads"
            columns={columns(today)}
            rows={query.data?.items ?? []}
            rowKey={(lead) => lead.id}
            rowHref={(lead) => lead.path as Route}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="Nothing matches"
                  text="No lead fits this search and these filters. Clear them to see every lead."
                  actions={
                    <ButtonLink variant="secondary" size="sm" href={href({})}>
                      Clear search and filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="userPlus"
                  title="No leads yet"
                  text="Add the first company that asked about your boards, platters or risers. Log each call and the next follow-up lands in Today."
                  actions={
                    canCreate ? (
                      <ButtonLink href={newHref} iconLeft="plus">
                        Add lead
                      </ButtonLink>
                    ) : undefined
                  }
                />
              )
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="leads" />}
                  right={pages > 1 ? <Pagination label="Lead pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </Page>
  );
}
