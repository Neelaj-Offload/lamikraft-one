"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { Badge } from "@/components/ui/badge";
import { Checkbox, RadioGroup } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { FactStrip, type Fact } from "@/components/ui/fact-strip";
import { LocalDate } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { buttonClasses, linkClasses } from "@/components/ui/styles";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { formatCount } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { challansMessages as m } from "@/messages/challans";
import { challanCsvHref, CHALLANS_PAGE_SIZE, fetchChallans, fetchChallanSummary } from "./api";
import { ChallanStatusPill, OPERATIONS_NAV_LEADING, QuantityList } from "./challan-bits";
import {
  challanListHref,
  challanListParams,
  challanListQueryKey,
  challanSummaryParams,
  challanSummaryQueryKey,
  DEFAULT_CHALLAN_LIST,
  type ChallanListState,
} from "./list-state";
import { CHALLAN_STATUSES, CHALLAN_TYPES, DESTINATION_TYPES, PERIODS, type ChallanSummary, type ChallanSummaryRow } from "./types";

const dash = <span className="text-ink-muted">—</span>;

export function challanColumns(): DataTableColumn<ChallanSummaryRow>[] {
  return [
    {
      id: "number",
      header: m.list.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (c) => `${c.challan_number} · ${c.destination_party}`,
      cell: (c) => (
        <span className="flex flex-col">
          <RacLink href={c.path} className={`${linkClasses} font-mono`}>
            {c.challan_number}
          </RacLink>
          {c.deleted_at ? (
            <span>
              <Badge>{m.list.deleted}</Badge>
            </span>
          ) : null}
        </span>
      ),
    },
    { id: "date", header: m.list.columns.date, mobile: "meta", cell: (c) => <LocalDate value={c.challan_date} /> },
    {
      id: "type",
      header: m.list.columns.type,
      mobile: "key",
      mobileCell: (c) => `${m.types[c.challan_type] ?? c.challan_type} · ${m.returnTypes[c.return_type] ?? c.return_type}`,
      cell: (c) => (
        <span className="flex flex-col">
          <span>{m.types[c.challan_type] ?? c.challan_type}</span>
          <span className="text-xs text-ink-muted">{m.returnTypes[c.return_type] ?? c.return_type}</span>
        </span>
      ),
    },
    {
      id: "destination",
      header: m.list.columns.destination,
      cell: (c) => (
        <span className="flex flex-col">
          <span>{c.destination_party}</span>
          <span className="text-xs text-ink-muted">
            {[m.destinations[c.destination_type] ?? c.destination_type, c.reference_no].filter(Boolean).join(" · ")}
          </span>
        </span>
      ),
    },
    { id: "status", header: m.list.columns.status, mobile: "status", cell: (c) => <ChallanStatusPill status={c.status} /> },
    { id: "lines", header: m.list.columns.lines, numeric: true, cell: (c) => <span className="tabular">{c.line_count}</span> },
    { id: "quantity", header: m.list.columns.quantity, mobile: "amount", cell: (c) => <QuantityList value={c.quantity_by_unit} /> },
    {
      id: "outstanding",
      header: m.list.columns.outstanding,
      cell: (c) =>
        c.status === "issued" && c.return_type === "returnable" ? (
          <span className="flex flex-col">
            <QuantityList value={c.outstanding_by_unit} />
            {c.expected_return_date ? <span className="text-xs text-ink-muted">{m.list.returnBy(c.expected_return_date)}</span> : null}
          </span>
        ) : (
          dash
        ),
    },
    { id: "owner", header: m.list.columns.owner, cell: (c) => c.owner.display_name ?? dash },
  ];
}

function summaryFacts(summary: ChallanSummary, state: ChallanListState, locale: string): Fact[] {
  const href = (next: Partial<ChallanListState>) => challanListHref({ ...state, offset: 0, period: null, pending: false, status: null, ...next });
  return [
    { label: m.summary.total, value: formatCount(summary.total, locale), href: href({}) },
    { label: m.summary.thisWeek, value: formatCount(summary.this_week, locale), href: href({ period: "this_week" }) },
    { label: m.summary.thisMonth, value: formatCount(summary.this_month, locale), href: href({ period: "this_month" }) },
    { label: m.summary.pending, value: formatCount(summary.pending_returnable, locale), href: href({ pending: true }) },
    { label: m.summary.issued, value: formatCount(summary.issued, locale), href: href({ status: "issued" }) },
  ];
}

export function ChallanList({ state }: { state: ChallanListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const { locale } = useZone();
  const params = challanListParams(state);
  const query = useQuery({ queryKey: challanListQueryKey(state), queryFn: ({ signal }) => fetchChallans(params, signal) });
  const summary = useQuery({
    queryKey: challanSummaryQueryKey(state),
    queryFn: ({ signal }) => fetchChallanSummary(challanSummaryParams(state), signal),
  });
  const go = (next: Partial<ChallanListState>) => router.push(challanListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const canCreate = permissionKeys.has("challans.challan.create");
  const canExport = permissionKeys.has("challans.challan.export");
  const filtered = challanListHref({ ...state, offset: 0 }) !== challanListHref(DEFAULT_CHALLAN_LIST);

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: "challans",
              rows: query.data.items.map((c, index) => ({ type: "challans.challan", id: c.id, version: c.version, ordinal: state.offset + index + 1 })),
            },
          ],
          filters: {
            q: state.q,
            status: state.status ?? "",
            challan_type: state.type ?? "",
            destination_type: state.destination ?? "",
            period: state.period ?? "",
            pending_returnable: state.pending,
            scope: state.scope,
          },
        }
      : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={m.list.title}
        intro={m.list.intro}
        nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_NAV_LEADING} />}
        actions={
          <>
            {canExport ? (
              // A real link: the CSV streams from the API as an attachment with the session cookie.
              <a href={challanCsvHref(params)} className={buttonClasses("secondary")} download>
                {m.list.exportCsv}
              </a>
            ) : null}
            {canCreate ? (
              <LinkButton href="/operations/challans/new" variant="primary">
                {m.list.newChallan}
              </LinkButton>
            ) : null}
          </>
        }
      />
      {summary.isSuccess ? (
        <div className="flex flex-col gap-2">
          <FactStrip label={m.summary.label} facts={summaryFacts(summary.data, state, locale)} />
          {Object.keys(summary.data.pending_returnable_quantity).length > 0 ? (
            <p className="text-sm text-ink-muted">
              {m.summary.pendingQuantity}: <QuantityList value={summary.data.pending_returnable_quantity} />
            </p>
          ) : null}
        </div>
      ) : summary.isError ? (
        <ErrorState error={summary.error} what={m.summary.loading} onRetry={() => void summary.refetch()} compact headingLevel={2} backToToday={false} />
      ) : null}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))] xl:items-end">
        <SearchField label={m.list.search} placeholder={m.list.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={m.list.status}
          options={[{ id: "", label: m.list.anyStatus }, ...CHALLAN_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: CHALLAN_STATUSES.find((status) => status === value) ?? null })}
        />
        <Select
          label={m.list.type}
          options={[{ id: "", label: m.list.anyType }, ...CHALLAN_TYPES.map((type) => ({ id: type, label: m.types[type] ?? type }))]}
          value={state.type ?? ""}
          onChange={(value) => go({ type: CHALLAN_TYPES.find((type) => type === value) ?? null })}
        />
        <Select
          label={m.list.destination}
          options={[{ id: "", label: m.list.anyDestination }, ...DESTINATION_TYPES.map((d) => ({ id: d, label: m.destinations[d] ?? d }))]}
          value={state.destination ?? ""}
          onChange={(value) => go({ destination: DESTINATION_TYPES.find((d) => d === value) ?? null })}
        />
        <Select
          label={m.list.period}
          options={[{ id: "", label: m.list.anyPeriod }, ...PERIODS.map((p) => ({ id: p, label: m.periods[p] ?? p }))]}
          value={state.period ?? ""}
          onChange={(value) => go({ period: PERIODS.find((p) => p === value) ?? null })}
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <Checkbox isSelected={state.pending} onChange={(pending) => go({ pending })}>
          {m.list.pending}
        </Checkbox>
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
        <ErrorState error={query.error} what={m.list.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.list.caption}
          hideCaption
          columns={challanColumns()}
          rows={query.data.items}
          rowId={(c) => c.id}
          rowHref={(c) => c.path}
          empty={<EmptyState title={m.list.emptyTitle}>{filtered ? m.list.empty : m.list.emptyStart}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.list.pages}
              total={query.data.total}
              limit={query.data.limit || CHALLANS_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: challanListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
