"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CUSTOM_PAGE_SIZE, CUSTOM_STATUSES, customExportHref, fetchCustomProducts, type CustomProductSummary } from "@/features/custom-products/api";
import { customListHref, type CustomListState } from "@/features/custom-products/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { asRoute, customProductStatus } from "~/data/sales-deals";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import {
  ButtonLink,
  ChipGroup,
  ChipLink,
  Code,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Money,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  type Column,
} from "~/ui";
import { stagger, StatusBadge } from "../quotations/parts";

const COLUMNS: Column<CustomProductSummary>[] = [
  {
    key: "product",
    header: "Custom product",
    primary: true,
    cell: (row) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-label truncate text-ink" title={row.product_name}>
          {row.product_name}
        </span>
        <Code>{row.custom_code}</Code>
      </span>
    ),
  },
  { key: "customer", header: "Customer", cell: (row) => row.party?.display_name ?? row.legacy_customer_name ?? "" },
  { key: "status", header: "Status", cell: (row) => <StatusBadge look={customProductStatus(row.status)} /> },
  {
    key: "spec",
    header: "Specification",
    hideOnMobile: true,
    cell: (row) => <span className="text-ink-2">{[row.dimensions_text, row.decor_no ? `decor ${row.decor_no}` : null, row.finish].filter(Boolean).join(" · ")}</span>,
  },
  { key: "price", header: "Quoted price", numeric: true, cell: (row) => <Money value={row.quoted_price} className="t-label text-ink" /> },
  { key: "updated", header: "Updated", hideOnMobile: true, cell: (row) => <DateText value={row.updated_at} style="relative" className="text-ink-3" /> },
];

/** Custom products: items made to one customer's specification, beside the catalogue. */
export function CustomProductList({ state }: { state: CustomListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const [text, setText] = useState(state.q);
  const canRead = permissionKeys.has("sales.custom_product.read");
  const params = { q: state.q || null, status: state.status, scope: state.scope, offset: state.offset };
  const query = useQuery({
    queryKey: queryKeys.sales.customProducts(params),
    queryFn: ({ signal }) => fetchCustomProducts(params, signal),
    enabled: canRead,
  });
  const href = (next: Partial<CustomListState>) => asRoute(customListHref({ ...state, offset: 0, ...next }));
  const canCreate = permissionKeys.has("sales.custom_product.create");
  const filtered = Boolean(state.q.trim() || state.status);
  const limit = query.data?.limit || CUSTOM_PAGE_SIZE;
  const total = query.data?.total ?? 0;

  if (!canRead) {
    return (
      <Page>
        <PageHeader eyebrow="Sales" title="Custom products" />
        <GlassPanel>
          <NotPermitted what="Custom products" />
        </GlassPanel>
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        eyebrow="Sales"
        title="Custom products"
        lead="Made to one customer's specification: from the first enquiry, through samples, to a place in the catalogue."
        actions={
          <>
            {permissionKeys.has("sales.custom_product.export") ? (
              <ButtonLink external href={customExportHref(params)} download variant="ghost" iconLeft="download">
                Export CSV
              </ButtonLink>
            ) : null}
            {canCreate ? (
              <ButtonLink href="/sales/custom-products/new" iconLeft="plus">
                Create custom product
              </ButtonLink>
            ) : null}
          </>
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SearchField
            className="min-w-0 flex-1 basis-64"
            label="Search custom products"
            placeholder="Name, CP code, decor or customer"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) router.push(href({ q: "" }));
            }}
            onSubmit={(value) => router.push(href({ q: value }))}
          />
          <SegmentedLinks
            label="Whose custom products"
            value={state.scope}
            options={[
              { value: "all", label: "Everyone's", href: href({ scope: "all" }) },
              { value: "mine", label: "Mine", href: href({ scope: "mine" }) },
            ]}
          />
        </div>
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
            All
          </ChipLink>
          {CUSTOM_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
              {customProductStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Custom products" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Custom products"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(row) => row.id}
            rowHref={(row) => asRoute(row.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No custom products match"
                  text="Nothing fits this search and status."
                  actions={
                    <ButtonLink href={asRoute(customListHref({ scope: state.scope }))} variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="shapes"
                  title="No custom products yet"
                  text="When a customer asks for something the catalogue does not hold, such as a riser in another colour, record it here."
                  actions={
                    canCreate ? (
                      <ButtonLink href="/sales/custom-products/new" iconLeft="plus">
                        Create the first custom product
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
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="custom products" />
          {total > limit ? (
            <Pagination
              label="Custom product pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(customListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
