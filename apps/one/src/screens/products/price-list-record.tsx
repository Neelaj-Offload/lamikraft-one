"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { PRICE_LISTS_PAGE_SIZE, priceListItemsHref, type PriceListItemsState } from "@/features/price-lists/list-state";
import type { PriceListItem } from "@/features/price-lists/types";
import { priceListCommand, type PriceListDetail } from "@/features/pricing/api";
import { useResourceCommand } from "@/features/sales/resource-command";
import { isProblemError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { usePriceList, usePriceListItems } from "~/data/products";
import { Page, PageHeader, PageSection, RecordHeader, type Crumb } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  ConfirmDialog,
  DataTable,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  IconButton,
  Menu,
  PageSummary,
  Pagination,
  Qty,
  ReasonDialog,
  SearchField,
  Skeleton,
  SkeletonText,
  Switch,
  TextLink,
  type Column,
  type MenuItem,
} from "~/ui";
import { PRICE_TYPE_LABEL, PriceListStatusBadge, scopeText, UnitPrice, validityText } from "./format";
import { productViewHref } from "./links";
import { DuplicatePriceListDialog, PriceHistoryDrawer, PriceItemDialog, type PriceDialog } from "./price-list-dialogs";

const CRUMBS: readonly Crumb[] = [
  { label: "Catalogue", href: "/products" },
  { label: "Price lists", href: "/products/price-lists" },
];
const CONFLICT = "Someone else changed this while you were working. The latest version is on screen; check it, then try again.";

const STATE_NOTE: Record<string, string> = {
  draft: "A draft. Prices can be edited freely until you activate it.",
  active: "Active. Its prices are fixed: a change is a new price from a date, and the old one stays in the history.",
  retired: "Retired. Kept as history; it no longer prices anything.",
};

function ItemStatus({ item }: { item: PriceListItem }) {
  if (item.superseded_by_item_id) return <Badge size="sm">Replaced</Badge>;
  return (
    <Badge tone={item.status === "active" ? "leaf" : "neutral"} size="sm" dot>
      {item.status === "active" ? "Active" : "Retired"}
    </Badge>
  );
}

function RecordSkeleton() {
  return (
    <Page>
      <div className="lk-glass record-head" role="status" aria-label="Loading the price list">
        <Skeleton width={120} />
        <Skeleton width="45%" height={28} />
        <SkeletonText lines={2} />
      </div>
      <LoadingBlock lines={6} />
    </Page>
  );
}

/** One price list: its validity, currency and scope up top, then its prices with what you may do to each. */
export function PriceListRecord({ priceListId, items }: { priceListId: string; items: PriceListItemsState }) {
  const query = usePriceList(priceListId);
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError || !query.data) {
    const status = isProblemError(query.error) ? query.error.status : null;
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title={status === 404 ? "This price list does not exist" : "Price list"} />
        {status === 403 ? (
          <NotPermitted what="Price lists" icon="tag" />
        ) : status === 404 ? (
          <GlassPanel>
            <EmptyState icon="tag" title="Nothing lives at this link" text="The price list may have been removed, or the link is out of date." actions={<ButtonLink href="/products/price-lists">See every price list</ButtonLink>} />
          </GlassPanel>
        ) : (
          <ErrorBlock error={query.error} what="This price list" onRetry={() => void query.refetch()} />
        )}
      </Page>
    );
  }
  return <Loaded priceList={query.data} state={items} />;
}

function Loaded({ priceList, state }: { priceList: PriceListDetail; state: PriceListItemsState }) {
  const router = useRouter();
  const { zone } = useSession();
  const items = usePriceListItems(priceList.id, state);
  const keys = useMemo(() => [queryKeys.pricing.all()], []);
  const commands = useResourceCommand(`price_list:${priceList.id}`, keys);
  const [activating, setActivating] = useState(false);
  const [retiring, setRetiring] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const [dialog, setDialog] = useState<PriceDialog | null>(null);
  const [historyOf, setHistoryOf] = useState<PriceListItem | null>(null);
  const [overlap, setOverlap] = useState<{ product_key: string; price_list_code: string }[] | null>(null);

  const can = (name: string) => priceList.capabilities[name]?.allowed === true;
  const transitions = new Set(priceList.allowed_transitions.map((transition) => transition.action));
  const offline = Boolean(commands.offline);
  const hrefFor = (patch: Partial<PriceListItemsState>) => priceListItemsHref(priceList.id, { ...state, ...patch }) as Route;

  const activate = async () => {
    setOverlap(null);
    const outcome = await commands.run("activate", [priceList.version], () => priceListCommand(priceList, "activate", null), {
      done: "Price list activated",
      failed: "The price list was not activated",
      conflictMessage: CONFLICT,
    });
    if (!outcome.ok && outcome.error instanceof ProblemError && outcome.error.code === "price_list_overlap") {
      const conflicts = (outcome.error.problem as { conflicts?: unknown }).conflicts;
      setOverlap(Array.isArray(conflicts) ? (conflicts as { product_key: string; price_list_code: string }[]) : []);
    }
  };

  const rowActions = (item: PriceListItem): MenuItem[] => {
    const live = item.status === "active";
    const current = live && !item.superseded_by_item_id;
    const actions: MenuItem[] = [{ id: "history", label: "See its history", icon: "history", onAction: () => setHistoryOf(item) }];
    if (can("edit_item") && live) actions.push({ id: "edit", label: "Edit price", icon: "edit", onAction: () => setDialog({ kind: "edit", item }), isDisabled: offline });
    if (can("supersede_item") && current) {
      actions.push({ id: "supersede", label: "Change from a date", icon: "calendar", description: "Keeps the old price as history", onAction: () => setDialog({ kind: "supersede", item }), isDisabled: offline });
    }
    if (can("retire_item") && current) {
      actions.push({ id: "sep", separator: true });
      actions.push({ id: "retire", label: "Retire price", icon: "archive", tone: "danger", onAction: () => setDialog({ kind: "retire", item }), isDisabled: offline });
    }
    return actions;
  };

  const columns: Column<PriceListItem>[] = [
    {
      key: "product",
      header: "Product",
      primary: true,
      cell: (item) => (
        <span className="flex flex-col">
          <TextLink href={productViewHref(item.product_id, "pricing")} className="lk-mono">
            {item.product_key}
          </TextLink>
          {item.display_sku && item.display_sku !== item.product_key ? <span className="t-caption text-ink-3">SKU {item.display_sku}</span> : null}
        </span>
      ),
    },
    { key: "price", header: "Unit price", mobileLabel: "Unit price", numeric: true, cell: (item) => <UnitPrice value={item.unit_price} unit={item.unit_code} /> },
    { key: "moq", header: "Minimum order", mobileLabel: "Minimum order", numeric: true, hideOnMobile: true, cell: (item) => (item.moq ? <Qty value={item.moq} /> : <span className="text-ink-3">None</span>) },
    {
      key: "valid",
      header: "Valid",
      mobileLabel: "Valid",
      hideOnMobile: true,
      cell: (item) => validityText(<DateText value={item.valid_from} style="business" />, item.valid_to ? <DateText value={item.valid_to} style="business" /> : null),
    },
    { key: "status", header: "Status", cell: (item) => <ItemStatus item={item} /> },
    {
      key: "actions",
      header: <span className="lk-sr-only">Actions</span>,
      width: "56px",
      cell: (item) => (
        <Menu
          label={`Actions for the price of ${item.product_key}`}
          items={rowActions(item)}
          placement="bottom end"
          trigger={<IconButton icon="more" label={`Actions for the price of ${item.product_key}`} variant="ghost" size="sm" />}
        />
      ),
    },
  ];

  const data = items.data;
  const limit = data?.limit || PRICE_LISTS_PAGE_SIZE;
  const page = data ? Math.floor(data.offset / limit) + 1 : 1;
  const pages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;
  const menu: MenuItem[] = [];
  if (can("duplicate")) menu.push({ id: "duplicate", label: "Copy as a new draft", icon: "copy", description: "Every price comes across", onAction: () => setDuplicating(true), isDisabled: offline });
  if (transitions.has("retire")) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({ id: "retire", label: "Retire list", icon: "archive", tone: "danger", onAction: () => setRetiring(true), isDisabled: offline });
  }
  const canActivate = transitions.has("activate");
  const canAdd = can("add_item");

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...CRUMBS, { label: priceList.code }]}
        code={priceList.code}
        title={priceList.name}
        status={<PriceListStatusBadge status={priceList.status} />}
        lead={STATE_NOTE[priceList.status]}
        facts={
          <FactStrip
            items={[
              { label: "Currency", value: <Code>{priceList.currency}</Code>, icon: "banknote" },
              { label: "Applies to", value: scopeText(priceList.scope_kind, priceList.party, priceList.customer_type), icon: "users" },
              { label: "Kind of price", value: PRICE_TYPE_LABEL[priceList.price_type] ?? priceList.price_type, icon: "tag" },
              {
                label: "Valid",
                value: validityText(<DateText value={priceList.valid_from} style="business" />, priceList.valid_to ? <DateText value={priceList.valid_to} style="business" /> : null),
                icon: "calendar",
              },
              { label: "Priority", value: priceList.priority === null ? null : <span className="lk-tnum">{formatCount(priceList.priority, zone.locale)}</span>, icon: "sort" },
            ]}
          />
        }
        actions={
          canActivate || canAdd || menu.length > 0 ? (
            <>
              {canAdd ? (
                <Button variant={canActivate ? "inverse" : "primary"} iconLeft="plus" onPress={() => setDialog({ kind: "add" })} isDisabled={offline}>
                  Add a price
                </Button>
              ) : null}
              {canActivate ? (
                <Button iconLeft="check" onPress={() => setActivating(true)} loading={commands.pending === "activate"} isDisabled={offline}>
                  Activate list
                </Button>
              ) : null}
              {menu.length > 0 ? <Menu label="More actions for this price list" items={menu} placement="bottom end" trigger={<IconButton icon="more" label="More actions" />} /> : null}
            </>
          ) : undefined
        }
      />

      {commands.offline ? (
        <Banner tone="amber" title="You are offline.">
          Changes are paused until the connection returns.
        </Banner>
      ) : null}
      {overlap ? (
        <Banner tone="ember" title="This list cannot be activated yet." onClose={() => setOverlap(null)}>
          Another active list already prices some of these products for the same customers, kind and currency. Retire those prices or end that list first.
          {overlap.length > 0 ? (
            <span className="mt-2 flex flex-wrap gap-2">
              {overlap.slice(0, 12).map((row) => (
                <Code key={`${row.product_key}-${row.price_list_code}`}>
                  {row.product_key} on {row.price_list_code}
                </Code>
              ))}
              {overlap.length > 12 ? <span className="t-caption">and {overlap.length - 12} more</span> : null}
            </span>
          ) : null}
        </Banner>
      ) : null}
      {priceList.notes || priceList.activated_at || priceList.retired_at ? (
        <p className="t-body-sm m-0 text-ink-2">
          {priceList.activated_at ? (
            <>
              Activated <DateText value={priceList.activated_at} style="dayTime" />.{" "}
            </>
          ) : null}
          {priceList.retired_at ? (
            <>
              Retired <DateText value={priceList.retired_at} style="dayTime" />.{" "}
            </>
          ) : null}
          {priceList.notes}
        </p>
      ) : null}

      <PageSection
        title="Prices"
        description={state.include_history ? "Every price this list has held, including replaced and retired ones." : "The prices this list holds today."}
        action={
          <Switch
            label="Show replaced and retired prices"
            isSelected={state.include_history}
            onChange={(include_history) => router.push(hrefFor({ include_history, offset: 0 }), { scroll: false })}
          />
        }
      >
        <SearchField
          key={state.q}
          label="Search this list's prices"
          placeholder="Search by product code or SKU"
          defaultValue={state.q}
          onSubmit={(q) => router.push(hrefFor({ q: q.trim(), offset: 0 }), { scroll: false })}
          onChange={(value) => {
            if (value === "" && state.q) router.push(hrefFor({ q: "", offset: 0 }), { scroll: false });
          }}
          className="max-w-xl"
        />
        {items.isError && !data ? (
          <ErrorBlock error={items.error} what="This list's prices" onRetry={() => void items.refetch()} />
        ) : (
          <GlassPanel padding="none">
            <DataTable
              label={`Prices on ${priceList.code}`}
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(item) => item.id}
              loading={items.isPending}
              skeletonRows={6}
              empty={
                state.q ? (
                  <EmptyState compact icon="search" title="No price matches" text="Try a shorter product code." />
                ) : (
                  <EmptyState
                    icon="tag"
                    title="Add the first price"
                    text="Pick a product, set what one unit costs in this currency, and it is ready for quotations once the list is active."
                    actions={
                      canAdd ? (
                        <Button variant="secondary" iconLeft="plus" onPress={() => setDialog({ kind: "add" })} isDisabled={offline}>
                          Add a price
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
            <PageSummary from={data.offset + 1} to={data.offset + data.items.length} total={data.total} noun="prices" />
            {pages > 1 ? <Pagination label="Price pages" page={page} pages={pages} hrefFor={(target) => hrefFor({ offset: (target - 1) * limit })} /> : null}
          </div>
        ) : null}
      </PageSection>

      <ConfirmDialog
        isOpen={activating}
        onOpenChange={setActivating}
        title={`Activate ${priceList.code}`}
        description="Quotations start using these prices from the list's first day. After this, a price can only be changed from a date, never edited in place."
        confirmLabel="Activate list"
        onConfirm={activate}
      />
      <ReasonDialog
        isOpen={retiring}
        onOpenChange={setRetiring}
        tone="danger"
        title={`Retire ${priceList.code}`}
        description="The list stops pricing anything. It stays here as history."
        confirmLabel="Retire list"
        reasonLabel="Why is it being retired?"
        reasonHelp="Kept in the list's history."
        onConfirm={async (reason) => {
          const outcome = await commands.run("retire", [priceList.version, reason], () => priceListCommand(priceList, "retire", reason), {
            done: "Price list retired",
            failed: "The price list was not retired",
            conflictMessage: CONFLICT,
          });
          if (!outcome.ok) throw outcome.error;
        }}
      />
      {dialog ? <PriceItemDialog key={dialog.kind === "add" ? "add" : `${dialog.kind}-${dialog.item.id}`} priceList={priceList} dialog={dialog} commands={commands} onClose={() => setDialog(null)} /> : null}
      {can("duplicate") ? <DuplicatePriceListDialog priceList={priceList} isOpen={duplicating} onOpenChange={setDuplicating} /> : null}
      <PriceHistoryDrawer item={historyOf} currency={priceList.currency} onClose={() => setHistoryOf(null)} />
    </Page>
  );
}
