"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { RadioGroup } from "@/components/ui/choice";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { formatDecimal } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { fetchPlans, PLANS_PAGE_SIZE, type PlanListParams } from "./api";
import { planListHref, type PlanListState } from "./list-state";
import { cuttingMessages as m } from "./messages";
import { PLAN_STATUSES, type PlanStatus, type PlanSummary } from "./types";

const STATUS_TONE: Record<string, Tone> = { draft: "neutral", calculated: "success", released: "info", archived: "neutral" };

export function PlanStatusPill({ status }: { status: string }) {
  return <StatusPill tone={STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

export function planListParams(state: PlanListState): PlanListParams {
  return { q: state.q || null, status: state.status, scope: state.scope, offset: state.offset };
}

function Flags({ plan }: { plan: PlanSummary }) {
  const flags: string[] = [
    plan.calc_status === "queued" || plan.calc_status === "running" ? m.list.queued : null,
    plan.stale ? m.list.stale : null,
    plan.requires_physical_verification && !plan.verified ? m.list.verify : null,
  ].flatMap((flag) => (flag ? [flag] : []));
  if (!flags.length) return null;
  return <span className="text-sm text-warning-text"> · {flags.join(" · ")}</span>;
}

export function planColumns(locale: string): DataTableColumn<PlanSummary>[] {
  return [
    {
      id: "number",
      header: m.list.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (plan) => plan.plan_number,
      cell: (plan) => (
        <RacLink href={plan.path} className={`${linkClasses} font-mono`}>
          {plan.plan_number}
        </RacLink>
      ),
    },
    {
      id: "name",
      header: m.list.columns.name,
      mobile: "key",
      cell: (plan) => (
        <span>
          {plan.name}
          <Flags plan={plan} />
        </span>
      ),
    },
    { id: "status", header: m.list.columns.status, mobile: "status", cell: (plan) => <PlanStatusPill status={plan.status} /> },
    { id: "pieces", header: m.list.columns.pieces, numeric: true, cell: (plan) => plan.piece_count },
    { id: "boards", header: m.list.columns.boards, numeric: true, mobile: "amount", cell: (plan) => plan.boards ?? "—" },
    {
      id: "efficiency",
      header: m.list.columns.efficiency,
      numeric: true,
      cell: (plan) => (plan.efficiency_usable_pct ? `${formatDecimal(plan.efficiency_usable_pct, { locale, maxFractionDigits: 2 })} %` : "—"),
    },
    { id: "updated", header: m.list.columns.updated, mobile: "meta", cell: (plan) => <RelativeTime value={plan.updated_at} className="text-ink-muted" /> },
  ];
}

/** Saved cut plans: search, status, scope and page live in the URL; filters apply on the server before paging. */
export function PlanList({ state }: { state: PlanListState }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const query = useQuery({
    queryKey: queryKeys.cutting.plans(planListParams(state)),
    queryFn: ({ signal }) => fetchPlans(planListParams(state), signal),
  });
  const go = (next: Partial<PlanListState>) => router.push(planListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const canCreate = permissionKeys.has("cutting.plan.create");
  const filtered = Boolean(state.q || state.status || state.scope === "mine");

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.list.title}</h1>
          <p className="text-ink-muted">{m.list.intro}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton href="/operations/cutting/grain-locks" variant="quiet">
            {m.list.grainLocks}
          </LinkButton>
          {canCreate ? (
            <LinkButton href="/operations/cutting/new" variant="primary">
              {m.list.newPlan}
            </LinkButton>
          ) : null}
        </div>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
        <SearchField label={m.list.search} placeholder={m.list.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={m.list.status}
          options={[{ id: "", label: m.list.anyStatus }, ...PLAN_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: (PLAN_STATUSES.find((status) => status === value) ?? null) as PlanStatus | null })}
        />
        <RadioGroup
          label={m.list.scope}
          orientation="horizontal"
          options={[
            { value: "all", label: m.list.all },
            { value: "mine", label: m.list.mine },
          ]}
          value={state.scope}
          onChange={(scope) => go({ scope: scope === "mine" ? "mine" : "all" })}
        />
      </div>
      {query.isPending ? (
        <Loading label={m.list.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={`the ${m.list.loading}`} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.list.caption}
          hideCaption
          columns={planColumns(zone.locale)}
          rows={query.data.items}
          rowId={(plan) => plan.id}
          rowHref={(plan) => plan.path}
          empty={<EmptyState title={m.list.emptyTitle}>{filtered ? m.list.empty : m.list.emptyFirst}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.list.pages}
              total={query.data.total}
              limit={query.data.limit || PLANS_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: planListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
