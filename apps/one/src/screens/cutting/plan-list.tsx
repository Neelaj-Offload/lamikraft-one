"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchPlans, PLANS_PAGE_SIZE } from "@/features/cutting/api";
import { planListHref, type PlanListState } from "@/features/cutting/list-state";
import { PLAN_STATUSES, type PlanSummary } from "@/features/cutting/types";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { asRoute, planStatus } from "~/data/cutting";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { ButtonLink, ChipGroup, ChipLink, Code, Dash, DataTable, DateText, EmptyState, GlassPanel, PageSummary, Pagination, SearchField, SegmentedLinks, type Column } from "~/ui";
import { Pct, PlanFlags, PlanStatusBadge, stagger } from "./parts";

function columns(locale: string): Column<PlanSummary>[] {
  return [
    {
      key: "plan",
      header: "Plan",
      primary: true,
      cell: (plan) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label truncate text-ink" title={plan.name}>
            {plan.name}
          </span>
          <span className="t-caption text-ink-3">
            <Code>{plan.plan_number}</Code>
            {plan.owner.display_name ? ` · ${plan.owner.display_name}` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (plan) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <PlanStatusBadge status={plan.status} />
          <PlanFlags plan={plan} />
        </span>
      ),
    },
    { key: "pieces", header: "Pieces", numeric: true, cell: (plan) => formatCount(plan.piece_count, locale) },
    { key: "boards", header: "Boards", numeric: true, cell: (plan) => (plan.boards === null ? <Dash /> : <span className="t-label text-ink">{formatCount(plan.boards, locale)}</span>) },
    { key: "used", header: "Board used", numeric: true, hideOnMobile: true, cell: (plan) => <Pct value={plan.efficiency_usable_pct} /> },
    { key: "updated", header: "Updated", hideOnMobile: true, cell: (plan) => <DateText value={plan.updated_at} style="relative" className="text-ink-3" /> },
  ];
}

/** Saved cut plans. Search, status, whose plans and the page all live in the URL and filter on the server. */
export function PlanList({ state }: { state: PlanListState }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const [text, setText] = useState(state.q);
  const params = { q: state.q || null, status: state.status, scope: state.scope, offset: state.offset };
  const query = useQuery({
    queryKey: queryKeys.cutting.plans(params),
    queryFn: ({ signal }) => fetchPlans(params, signal),
  });
  const href = (next: Partial<PlanListState>) => asRoute(planListHref({ ...state, offset: 0, ...next }));
  const canCreate = permissionKeys.has("cutting.plan.create");
  const filtered = Boolean(state.q.trim() || state.status || state.scope === "mine");
  const limit = query.data?.limit || PLANS_PAGE_SIZE;
  const total = query.data?.total ?? 0;

  return (
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Cut plans"
        lead="Pieces laid out on boards, so every sheet is used well before it reaches the saw."
        actions={
          <>
            <ButtonLink href="/operations/cutting/grain-locks" variant="secondary" iconLeft="lock">
              Grain locks
            </ButtonLink>
            {canCreate ? (
              <ButtonLink href="/operations/cutting/new" iconLeft="plus">
                New cut plan
              </ButtonLink>
            ) : null}
          </>
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SearchField
            className="min-w-0 flex-1 basis-64 md:max-w-xl"
            label="Search cut plans"
            placeholder="Plan number or name"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) router.push(href({ q: "" }));
            }}
            onSubmit={(value) => router.push(href({ q: value }))}
          />
          <SegmentedLinks
            label="Whose plans"
            value={state.scope}
            options={[
              { value: "all", label: "Everyone's", href: href({ scope: "all" }) },
              { value: "mine", label: "Mine", href: href({ scope: "mine" }) },
            ]}
          />
        </div>
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
            Open
          </ChipLink>
          {PLAN_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
              {planStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Cut plans" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Cut plans"
            columns={columns(zone.locale)}
            rows={query.data?.items ?? []}
            rowKey={(plan) => plan.id}
            rowHref={(plan) => asRoute(plan.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No cut plans match"
                  text="Nothing fits this search, status and owner."
                  actions={
                    <ButtonLink href="/operations/cutting" variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="scissors"
                  title="No cut plans yet"
                  text="List the pieces to cut and choose the board. The layout, the board count and the offcuts are worked out for you."
                  actions={
                    canCreate ? (
                      <ButtonLink href="/operations/cutting/new" variant="inverse" iconLeft="plus">
                        Create your first cut plan
                      </ButtonLink>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="cut plans" />
          {total > limit ? (
            <Pagination
              label="Cut plan pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(planListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
