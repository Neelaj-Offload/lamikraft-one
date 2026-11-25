"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { PRICE_LISTS_PAGE_SIZE, priceListListHref, type PriceListListState } from "@/features/price-lists/list-state";
import { PRICE_LIST_STATUSES, PRICE_SCOPES, PRICE_TYPES, type PriceListSummary } from "@/features/price-lists/types";
import { CURRENCIES, formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { PRICE_LIST_MANAGE, PRICES_READ, usePriceLists } from "~/data/products";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Button, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, PageSummary, Pagination, SearchField, Select, type Column } from "~/ui";
import { PRICE_LIST_STATUS_LABEL, PRICE_SCOPE_LABEL, PRICE_TYPE_LABEL, PriceListStatusBadge, scopeText, validityText } from "./format";
import { priceListHref } from "./links";
import { CreatePriceListDialog } from "./price-list-dialogs";

/** Every price list, with who it applies to and when. Status, kind, currency, scope, search and the page all live in the URL. */

const ANY = "any";
const href = (state: Partial<PriceListListState>) => priceListListHref(state) as Route;

function columns(locale: string): Column<PriceListSummary>[] {
  return [
    {
      key: "list",
      header: "Price list",
      primary: true,
      cell: (list) => (
        <span className="flex flex-col">
          <span className="t-label text-ink">{list.name}</span>
          <Code>{list.code}</Code>
        </span>
      ),
    },
    {
      key: "for",
      header: "Applies to",
      mobileLabel: "Applies to",
      cell: (list) => (
        <span className="flex flex-col">
          <span>{scopeText(list.scope_kind, list.party, list.customer_type)}</span>
          <span className="t-caption text-ink-3">
            {PRICE_TYPE_LABEL[list.price_type] ?? list.price_type}
            {list.priority === null ? "" : ` · priority ${formatCount(list.priority, locale)}`}
          </span>
        </span>
      ),
    },
    { key: "currency", header: "Currency", mobileLabel: "Currency", hideOnMobile: true, cell: (list) => <Code>{list.currency}</Code> },
    {
      key: "valid",
      header: "Valid",
      mobileLabel: "Valid",
      cell: (list) => validityText(<DateText value={list.valid_from} style="business" />, list.valid_to ? <DateText value={list.valid_to} style="business" /> : null),
    },
    { key: "items", header: "Prices", mobileLabel: "Prices", numeric: true, cell: (list) => <span className="lk-tnum">{formatCount(list.item_count, locale)}</span> },
    { key: "status", header: "Status", cell: (list) => <PriceListStatusBadge status={list.status} size="sm" /> },
  ];
}

export function PriceLists({ state }: { state: PriceListListState }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(PRICES_READ);
  const canManage = permissionKeys.has(PRICE_LIST_MANAGE);
  const [creating, setCreating] = useState(false);
  const query = usePriceLists(state, allowed);
  const data = query.data;

  useScreenContribution(
    data
      ? {
          lists: [{ key: "price_lists", rows: data.items.map((list, index) => ({ type: "pricing.price_list", id: list.id, version: null, ordinal: state.offset + index + 1 })) }],
          filters: { q: state.q, status: state.status ?? "", price_type: state.price_type ?? "", currency: state.currency ?? "", scope_kind: state.scope_kind ?? "" },
        }
      : null,
  );

  if (!allowed) {
    return (
      <Page>
        <PageHeader breadcrumb={[{ label: "Catalogue", href: "/products" }]} title="Price lists" />
        <NotPermitted what="Price lists" icon="tag" />
      </Page>
    );
  }

  const go = (patch: Partial<PriceListListState>) => router.push(href({ ...state, offset: 0, ...patch }));
  const filtered = Boolean(state.q || state.status || state.price_type || state.currency || state.scope_kind);
  const limit = data?.limit || PRICE_LISTS_PAGE_SIZE;
  const page = data ? Math.floor(data.offset / limit) + 1 : 1;
  const pages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Catalogue", href: "/products" }]}
        title="Price lists"
        lead="What you charge, to whom, and from when. Active prices never change in place: a change is a new price from a date."
        actions={
          canManage ? (
            <Button iconLeft="plus" onPress={() => setCreating(true)}>
              New price list
            </Button>
          ) : undefined
        }
      />

      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SearchField
            key={state.q}
            label="Search price lists"
            placeholder="Search by code or name"
            defaultValue={state.q}
            onSubmit={(q) => go({ q: q.trim() })}
            onChange={(value) => {
              if (value === "" && state.q) go({ q: "" });
            }}
            className="min-w-0 flex-1 basis-64"
          />
          <Select
            label="Kind of price"
            hideLabel
            className="w-44"
            options={[{ value: ANY, label: "Any kind" }, ...PRICE_TYPES.map((type) => ({ value: type, label: PRICE_TYPE_LABEL[type] ?? type }))]}
            value={state.price_type ?? ANY}
            onChange={(value) => go({ price_type: PRICE_TYPES.find((type) => type === value) ?? null })}
          />
          <Select
            label="Currency"
            hideLabel
            className="w-40"
            options={[{ value: ANY, label: "Any currency" }, ...CURRENCIES.map((code) => ({ value: code, label: code }))]}
            value={state.currency ?? ANY}
            onChange={(value) => go({ currency: CURRENCIES.find((code) => code === value) ?? null })}
          />
          <Select
            label="Applies to"
            hideLabel
            className="w-48"
            options={[{ value: ANY, label: "Any scope" }, ...PRICE_SCOPES.map((scope) => ({ value: scope, label: PRICE_SCOPE_LABEL[scope] ?? scope }))]}
            value={state.scope_kind ?? ANY}
            onChange={(value) => go({ scope_kind: PRICE_SCOPES.find((scope) => scope === value) ?? null })}
          />
        </div>
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ ...state, status: null, offset: 0 })} selected={!state.status} scroll={false}>
            All
          </ChipLink>
          {PRICE_LIST_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ ...state, status, offset: 0 })} selected={state.status === status} scroll={false}>
              {PRICE_LIST_STATUS_LABEL[status] ?? status}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError && !data ? (
        <ErrorBlock error={query.error} what="Price lists" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Price lists"
            columns={columns(zone.locale)}
            rows={data?.items ?? []}
            rowKey={(list) => list.id}
            rowHref={(list) => priceListHref(list.id)}
            loading={query.isPending}
            skeletonRows={6}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No price list matches"
                  text="Loosen the search or drop a filter."
                  actions={
                    <ButtonLink href={href({})} variant="secondary" size="sm">
                      Clear search and filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="tag"
                  title="Create your first price list"
                  text="A price list holds what you charge in one currency. Quotations take their prices from the active one."
                  actions={
                    canManage ? (
                      <Button iconLeft="plus" onPress={() => setCreating(true)}>
                        New price list
                      </Button>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {data && data.total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={data.offset + 1} to={data.offset + data.items.length} total={data.total} noun="price lists" />
          {pages > 1 ? <Pagination label="Price list pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
        </div>
      ) : null}

      {canManage ? <CreatePriceListDialog isOpen={creating} onOpenChange={setCreating} /> : null}
    </Page>
  );
}
