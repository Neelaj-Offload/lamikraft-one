"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { challanCsvHref, CHALLANS_PAGE_SIZE, fetchChallans, fetchChallanSummary } from "@/features/challans/api";
import {
  challanListHref,
  challanListParams,
  challanListQueryKey,
  challanSummaryParams,
  challanSummaryQueryKey,
  type ChallanListState,
} from "@/features/challans/list-state";
import { CHALLAN_STATUSES, CHALLAN_TYPES, DESTINATION_TYPES, type ChallanSummaryRow } from "@/features/challans/types";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { useSession } from "@/lib/session/context";
import { asRoute, challanStatus, DESTINATION_LABEL, RETURN_LABEL, TYPE_LABEL } from "~/data/challans";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  ButtonLink,
  ChipGroup,
  ChipLink,
  Code,
  Dash,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  Select,
  type Column,
} from "~/ui";
import { QuantityList, StatusBadge } from "./parts";

const ANY = "any";

function columns(scope: ChallanListState["scope"]): Column<ChallanSummaryRow>[] {
  return [
    {
      key: "number",
      header: "Challan",
      primary: true,
      cell: (challan) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-2">
            <Code>{challan.challan_number}</Code>
            {challan.deleted_at ? <Badge size="sm">Deleted</Badge> : null}
          </span>
          <span className="t-caption text-ink-3">
            <DateText value={challan.challan_date} style="business" />
            {scope === "all" && challan.owner.display_name ? ` · ${challan.owner.display_name}` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "destination",
      header: "Going to",
      cell: (challan) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-ink" title={challan.destination_party}>
            {challan.destination_party}
          </span>
          <span className="t-caption truncate text-ink-3">
            {[DESTINATION_LABEL[challan.destination_type] ?? challan.destination_type, challan.reference_no ? `Ref. ${challan.reference_no}` : null].filter(Boolean).join(" · ")}
          </span>
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      cell: (challan) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-ink">{TYPE_LABEL[challan.challan_type] ?? challan.challan_type}</span>
          <span className="t-caption text-ink-3">{RETURN_LABEL[challan.return_type] ?? challan.return_type}</span>
        </span>
      ),
    },
    { key: "status", header: "Status", cell: (challan) => <StatusBadge status={challan.status} /> },
    {
      key: "quantity",
      header: "Quantity",
      numeric: true,
      cell: (challan) => (
        <span className="flex flex-col items-end gap-0.5">
          <QuantityList value={challan.quantity_by_unit} className="justify-end text-ink" />
          <span className="t-caption text-ink-3">{challan.line_count === 1 ? "1 line" : `${challan.line_count} lines`}</span>
        </span>
      ),
    },
    {
      key: "outstanding",
      header: "Still out",
      numeric: true,
      hideOnMobile: true,
      cell: (challan) =>
        challan.status === "issued" && challan.return_type === "returnable" ? (
          <span className="flex flex-col items-end gap-0.5">
            <QuantityList value={challan.outstanding_by_unit} className="justify-end" />
            {challan.expected_return_date ? (
              <span className="t-caption text-ink-3">
                Back by <DateText value={challan.expected_return_date} style="business" />
              </span>
            ) : null}
          </span>
        ) : (
          <Dash />
        ),
    },
  ];
}

/** Challans: every delivery document. Search, quick view, filters, scope and page all live in the URL. */
export function ChallanList({ state }: { state: ChallanListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const [text, setText] = useState(state.q);
  const params = challanListParams(state);
  const query = useQuery({ queryKey: challanListQueryKey(state), queryFn: ({ signal }) => fetchChallans(params, signal) });

  // The quick views each replace date, status and "still out", so their counts are taken without those three.
  const base: ChallanListState = { ...state, period: null, pending: false, status: null, offset: 0 };
  const summary = useQuery({
    queryKey: challanSummaryQueryKey(base),
    queryFn: ({ signal }) => fetchChallanSummary(challanSummaryParams(base), signal),
    staleTime: 30_000,
  });

  const href = (next: Partial<ChallanListState>) => asRoute(challanListHref({ ...state, offset: 0, ...next }));
  const quick = (next: Partial<ChallanListState>) => href({ period: null, pending: false, status: null, ...next });
  const go = (next: Partial<ChallanListState>) => router.push(href(next));

  const canCreate = permissionKeys.has("challans.challan.create");
  const canExport = permissionKeys.has("challans.challan.export");
  const filtered = Boolean(state.q.trim() || state.status || state.type || state.destination || state.period || state.pending);
  const limit = query.data?.limit || CHALLANS_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const counts = summary.data;
  const stillOut = counts ? Object.keys(counts.pending_returnable_quantity).length > 0 : false;

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: "challans",
              rows: query.data.items.map((challan, index) => ({ type: "challans.challan", id: challan.id, version: challan.version, ordinal: state.offset + index + 1 })),
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
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Challans"
        lead={
          state.scope === "mine"
            ? "The delivery challans you raised: goods out, goods in, job work and samples."
            : "Every delivery challan: goods out, goods in, job work and samples."
        }
        actions={
          <>
            {canExport ? (
              <ButtonLink external href={challanCsvHref(params)} download variant="ghost" iconLeft="download">
                Export CSV
              </ButtonLink>
            ) : null}
            {canCreate ? (
              <ButtonLink href="/operations/challans/new" iconLeft="plus">
                Create challan
              </ButtonLink>
            ) : null}
          </>
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={{ "--i": 1 } as React.CSSProperties}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SearchField
            className="min-w-0 flex-1 basis-64"
            label="Search challans"
            placeholder="Number, destination or reference"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) go({ q: "" });
            }}
            onSubmit={(value) => go({ q: value })}
          />
          <SegmentedLinks
            label="Whose challans"
            value={state.scope}
            options={[
              { value: "all", label: "Everyone's", href: href({ scope: "all" }) },
              { value: "mine", label: "Mine", href: href({ scope: "mine" }) },
            ]}
          />
        </div>

        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3 lg:max-w-3xl">
          <Select
            label="Status"
            hideLabel
            size="sm"
            options={[{ value: ANY, label: "Any status" }, ...CHALLAN_STATUSES.map((status) => ({ value: status, label: challanStatus(status).label }))]}
            value={state.status ?? ANY}
            onChange={(value) => go({ status: CHALLAN_STATUSES.find((status) => status === value) ?? null })}
          />
          <Select
            label="Type"
            hideLabel
            size="sm"
            options={[{ value: ANY, label: "Any type" }, ...CHALLAN_TYPES.map((type) => ({ value: type, label: TYPE_LABEL[type] ?? type }))]}
            value={state.type ?? ANY}
            onChange={(value) => go({ type: CHALLAN_TYPES.find((type) => type === value) ?? null })}
          />
          <Select
            label="Going to"
            hideLabel
            size="sm"
            options={[{ value: ANY, label: "Any destination" }, ...DESTINATION_TYPES.map((destination) => ({ value: destination, label: DESTINATION_LABEL[destination] ?? destination }))]}
            value={state.destination ?? ANY}
            onChange={(value) => go({ destination: DESTINATION_TYPES.find((destination) => destination === value) ?? null })}
          />
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <ChipGroup label="Quick views">
            <ChipLink href={quick({})} selected={!state.period && !state.pending && !state.status} count={counts?.total} scroll={false}>
              All
            </ChipLink>
            <ChipLink href={quick({ period: "this_week" })} selected={state.period === "this_week"} count={counts?.this_week} scroll={false}>
              This week
            </ChipLink>
            <ChipLink href={quick({ period: "this_month" })} selected={state.period === "this_month"} count={counts?.this_month} scroll={false}>
              This month
            </ChipLink>
            <ChipLink href={quick({ pending: true })} selected={state.pending} count={counts?.pending_returnable} scroll={false}>
              Still to come back
            </ChipLink>
            <ChipLink href={quick({ status: "issued" })} selected={state.status === "issued" && !state.pending && !state.period} count={counts?.issued} scroll={false}>
              Issued
            </ChipLink>
          </ChipGroup>
          {counts && stillOut ? (
            <p className="t-caption text-ink-3">
              Out with others now: <QuantityList value={counts.pending_returnable_quantity} className="text-ink-2" />
            </p>
          ) : null}
        </div>
        {summary.isError ? <ErrorBlock error={summary.error} what="The challan counts" onRetry={() => void summary.refetch()} /> : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Challans" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={{ "--i": 2 } as React.CSSProperties}>
          <DataTable
            label="Challans"
            columns={columns(state.scope)}
            rows={query.data?.items ?? []}
            rowKey={(challan) => challan.id}
            rowHref={(challan) => asRoute(challan.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No challans match"
                  text="Nothing fits this search and these filters. Clear them to see the full list."
                  actions={
                    <ButtonLink href={asRoute(challanListHref({ scope: state.scope }))} variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="fileCheck"
                  title={state.scope === "mine" ? "You have not raised a challan yet" : "No challans yet"}
                  text="A challan travels with the goods. Start a draft, add its lines, then issue it and print."
                  actions={
                    canCreate ? (
                      <ButtonLink href="/operations/challans/new" iconLeft="plus">
                        Create your first challan
                      </ButtonLink>
                    ) : state.scope === "mine" ? (
                      <ButtonLink href={href({ scope: "all" })} variant="secondary">
                        See everyone&apos;s
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
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="challans" />
          {total > limit ? (
            <Pagination
              label="Challan pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(challanListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
