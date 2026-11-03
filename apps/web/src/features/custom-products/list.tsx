"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { RadioGroup } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { Money, RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { isProblemError } from "@/lib/api/errors";
import { useSession } from "@/lib/session/context";
import { commercialMessages as c } from "@/messages/commercial";
import { CUSTOM_PAGE_SIZE, CUSTOM_STATUSES, customExportHref, fetchCustomProducts, type CustomProductSummary } from "./api";

const m = c.customProducts;

export { customListStateFrom, customListHref, type CustomListState } from "./list-state";
import { customListHref, type CustomListState } from "./list-state";

export const CUSTOM_STATUS_TONE: Record<string, Tone> = {
  inquiry: "neutral",
  under_development: "info",
  sample_stage: "info",
  quoted: "info",
  approved: "success",
  rejected: "danger",
  dormant: "neutral",
  converted_to_standard: "forest",
};

export function CustomStatusPill({ status }: { status: string }) {
  return <StatusPill tone={CUSTOM_STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? c.human(status)}</StatusPill>;
}

function columns(): DataTableColumn<CustomProductSummary>[] {
  return [
    {
      id: "code",
      header: m.columns.code,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => `${row.custom_code} · ${row.product_name}`,
      cell: (row) => (
        <RacLink href={row.path} className={`${linkClasses} font-mono`}>
          {row.custom_code}
        </RacLink>
      ),
    },
    { id: "name", header: m.columns.name, cell: (row) => row.product_name },
    { id: "customer", header: m.columns.customer, mobile: "key", cell: (row) => row.party?.display_name ?? row.legacy_customer_name ?? c.common.noValue },
    { id: "status", header: m.columns.status, mobile: "status", cell: (row) => <CustomStatusPill status={row.status} /> },
    { id: "price", header: m.columns.price, numeric: true, mobile: "amount", cell: (row) => (row.quoted_price ? <Money value={row.quoted_price} /> : <span className="text-ink-muted">—</span>) },
    { id: "updated", header: m.columns.updated, mobile: "meta", cell: (row) => <RelativeTime value={row.updated_at} className="text-ink-muted" /> },
  ];
}

export function CustomProductList({ state }: { state: CustomListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const params = { q: state.q || null, status: state.status, scope: state.scope, offset: state.offset };
  const query = useQuery({
    queryKey: queryKeys.sales.customProducts(params),
    queryFn: ({ signal }) => fetchCustomProducts(params, signal),
    enabled: permissionKeys.has("sales.custom_product.read"),
  });
  const go = (next: Partial<CustomListState>) => router.push(customListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  if (!permissionKeys.has("sales.custom_product.read")) return <PermissionDenied area={m.title} />;
  const canCreate = permissionKeys.has("sales.custom_product.create");
  const canExport = permissionKeys.has("sales.custom_product.export");

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.title}</h1>
          <p className="text-ink-muted">{m.intro}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canExport ? (
            <a href={customExportHref(params)} className={linkClasses} download>
              {c.common.exportCsv}
            </a>
          ) : null}
          {canCreate ? (
            <LinkButton href="/sales/custom-products/new" variant="primary">
              {m.newProduct}
            </LinkButton>
          ) : null}
        </div>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
        <SearchField label={c.common.search} placeholder={m.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={c.common.status}
          options={[{ id: "", label: c.common.anyStatus }, ...CUSTOM_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: CUSTOM_STATUSES.find((status) => status === value) ?? null })}
        />
        <RadioGroup
          label={c.common.show}
          orientation="horizontal"
          options={[
            { value: "all", label: c.common.all },
            { value: "mine", label: c.common.mine },
          ]}
          value={state.scope}
          onChange={(scope) => go({ scope: scope === "mine" ? "mine" : "all" })}
        />
      </div>
      {query.isPending ? (
        <Loading label={m.loadingList} />
      ) : query.isError ? (
        isProblemError(query.error) && query.error.status === 403 ? (
          <PermissionDenied area={m.title} headingLevel={2} />
        ) : (
          <ErrorState error={query.error} what={`the ${m.loadingList}`} onRetry={() => void query.refetch()} />
        )
      ) : (
        <DataTable
          caption={m.caption}
          hideCaption
          columns={columns()}
          rows={query.data.items}
          rowId={(row) => row.id}
          rowHref={(row) => row.path}
          empty={<EmptyState title={m.emptyTitle}>{m.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={c.common.pages}
              total={query.data.total}
              limit={query.data.limit || CUSTOM_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: customListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
