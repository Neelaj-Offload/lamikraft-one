"use client";

import type { ProductCost, ProductPrice } from "@/features/price-lists/types";
import type { ProductDetail } from "@/features/products/types";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { COST_READ, PRICES_READ, useProductCosts, useProductPrices } from "~/data/products";
import { PageSection } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Badge, Code, DataTable, DateText, EmptyState, GlassPanel, KeyValue, Qty, type Column } from "~/ui";
import { PRICE_TYPE_LABEL, priceGapText, scopeText, UnitPrice, validityText } from "./format";
import { priceListHref } from "./links";
import { riseStyle } from "./motion";

/** What this product sells for: the standard price in each currency, then every list that prices it today. */

const columns: Column<ProductPrice>[] = [
  {
    key: "list",
    header: "Price list",
    primary: true,
    cell: (row) => (
      <span className="flex flex-col">
        <span className="t-label text-ink">{row.price_list_name}</span>
        <Code>{row.price_list_code}</Code>
      </span>
    ),
  },
  {
    key: "for",
    header: "Applies to",
    mobileLabel: "Applies to",
    cell: (row) => (
      <span className="flex flex-col">
        <span>{scopeText(row.scope_kind, row.party, row.customer_type)}</span>
        <span className="t-caption text-ink-3">{PRICE_TYPE_LABEL[row.price_type] ?? row.price_type}</span>
      </span>
    ),
  },
  { key: "price", header: "Unit price", mobileLabel: "Unit price", numeric: true, cell: (row) => <UnitPrice value={row.unit_price} unit={row.unit_code} /> },
  { key: "moq", header: "Minimum order", mobileLabel: "Minimum order", numeric: true, hideOnMobile: true, cell: (row) => (row.moq ? <Qty value={row.moq} /> : <span className="text-ink-3">None</span>) },
  {
    key: "valid",
    header: "Valid",
    mobileLabel: "Valid",
    hideOnMobile: true,
    cell: (row) => validityText(<DateText value={row.valid_from} style="business" />, row.valid_to ? <DateText value={row.valid_to} style="business" /> : null),
  },
  {
    key: "status",
    header: "Status",
    cell: (row) => (
      <Badge tone={row.status === "active" ? "leaf" : "neutral"} size="sm" dot>
        {row.status === "active" ? "Active" : "Retired"}
      </Badge>
    ),
  },
];

function CostPanel({ productId, cost }: { productId: string; cost: ProductCost }) {
  const { permissionKeys, zone } = useSession();
  const canReadCost = permissionKeys.has(COST_READ);
  const history = useProductCosts(productId, canReadCost);
  const earlier = history.data?.items.filter((entry) => entry.id !== cost.id) ?? [];
  return (
    // Cost is restricted: the whole panel is blacked out in masked screenshots.
    <GlassPanel
      padding="lg"
      data-restricted="true"
      title="Cost of record"
      titleAs="h3"
      action={
        <Badge size="sm" icon="lock">
          Cost access only
        </Badge>
      }
      className="flex flex-col gap-5"
    >
      <KeyValue
        columns={3}
        items={[
          { label: "Unit cost", value: <UnitPrice value={cost.unit_cost} unit={cost.unit_code} /> },
          { label: "In effect from", value: <DateText value={cost.effective_from} style="business" /> },
          { label: "Recorded", value: <DateText value={cost.recorded_at} style="dayTime" /> },
          { label: "Version", value: <span className="lk-tnum">{formatCount(cost.cost_version, zone.locale)}</span> },
          { label: "Source", value: cost.source_kind },
        ]}
      />
      {cost.cost_components && cost.cost_components.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h4 className="t-label m-0 text-ink-2">What the cost is made of</h4>
          <KeyValue
            rows
            items={cost.cost_components.map((component) => ({
              label: component.label,
              value: <UnitPrice value={{ amount: component.amount, currency: cost.unit_cost?.currency ?? "" }} />,
            }))}
          />
        </div>
      ) : null}
      {canReadCost && history.isError ? <ErrorBlock error={history.error} what="Cost history" onRetry={() => void history.refetch()} /> : null}
      {earlier.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h4 className="t-label m-0 text-ink-2">Earlier costs</h4>
          <KeyValue
            rows
            items={earlier.map((entry) => ({
              label: (
                <span>
                  <DateText value={entry.effective_from} style="business" /> · version {formatCount(entry.cost_version, zone.locale)} · {entry.source_kind}
                </span>
              ),
              value: <UnitPrice value={entry.unit_cost} unit={entry.unit_code} />,
            }))}
          />
        </div>
      ) : null}
    </GlassPanel>
  );
}

export function ProductPricing({ product }: { product: ProductDetail }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRICES_READ);
  const query = useProductPrices(product.id, allowed);

  if (!allowed) return <NotPermitted what="Prices" icon="tag" />;

  return (
    <>
      {product.prices !== null && product.prices.length > 0 ? (
        <PageSection title="Standard prices" description="The price a quotation starts from, one per currency. Nothing is converted between currencies.">
          <div className="tiles">
            {product.prices.map((column, index) => (
              <GlassPanel key={column.currency} className="rise-plain flex flex-col gap-3" style={riseStyle(index)}>
                <p className="t-overline m-0 text-ink-3">{column.currency}</p>
                {column.status === "found" && column.unit_price ? (
                  <>
                    <p className="t-stat-sm m-0 text-ink">
                      <UnitPrice value={column.unit_price} unit={column.unit_code} />
                    </p>
                    <div className="t-body-sm flex flex-col gap-1 text-ink-2">
                      {column.price_list_code ? (
                        <span>
                          From <Code>{column.price_list_code}</Code>
                        </span>
                      ) : null}
                      {column.product_moq ? (
                        <span>
                          Minimum order <Qty value={column.product_moq} />
                        </span>
                      ) : null}
                      {column.recommendation ? <span>{column.recommendation.label}</span> : null}
                    </div>
                  </>
                ) : (
                  <>
                    <p className="t-h4 m-0 text-ink-2">{priceGapText(column)}</p>
                    <p className="t-body-sm m-0 text-ink-3">
                      {column.status === "ambiguous"
                        ? "More than one active list prices this product. Give one of them priority and the price appears."
                        : column.status === "unavailable"
                          ? "The standard list has no price for this product."
                          : `No active standard list prices this product in ${column.currency}.`}
                    </p>
                  </>
                )}
              </GlassPanel>
            ))}
          </div>
        </PageSection>
      ) : null}

      <PageSection title="On price lists today" description="Every list that prices this product right now, standard or agreed with a customer.">
        {query.isError ? (
          <ErrorBlock error={query.error} what="Prices" onRetry={() => void query.refetch()} />
        ) : (
          <GlassPanel padding="none">
            <DataTable
              label="Prices of this product"
              columns={columns}
              rows={query.data?.prices ?? []}
              rowKey={(row) => row.id}
              rowHref={(row) => priceListHref(row.price_list_id)}
              loading={query.isPending}
              skeletonRows={3}
              empty={<EmptyState compact icon="tag" title="No price list prices this product today" text="Open a draft price list and add a price for it." />}
            />
          </GlassPanel>
        )}
      </PageSection>

      {query.data?.current_cost ? <CostPanel productId={product.id} cost={query.data.current_cost} /> : null}
    </>
  );
}
