"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Key } from "react-aria-components";
import { RailContent } from "@/components/shell/context-rail";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDateTime, Money } from "@/components/ui/format";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { Tabs } from "@/components/ui/tabs";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useRecentRecord } from "@/lib/recent/recent-records";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { fetchProduct } from "./api";
import { ProductStatusPill } from "./product-format";
import { PRODUCTS_READ } from "./product-list";
import { ProductMaterial } from "./product-material";
import { ProductOverview } from "./product-overview";
import { ProductPackaging } from "./product-packaging";
import { ProductPricesTab } from "./product-prices";
import { ProductSpecification } from "./product-specification";
import type { ProductDetail } from "./types";

import { PRODUCT_TABS, productTabHref, type ProductTab } from "./detail-state";

export { PRODUCT_TABS, productTabFrom, productTabHref, type ProductTab } from "./detail-state";

/**
 * The product record: header, five in-page tabs mirrored in `?tab=`, and a compact context in
 * the rail. There are no product write endpoints in this slice, so no edit controls render,
 * whatever `capabilities.update` says.
 */
export function ProductDetailView({ productId, tab }: { productId: string; tab: ProductTab }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const query = useQuery({ queryKey: queryKeys.catalogue.product(productId), queryFn: ({ signal }) => fetchProduct(productId, signal), enabled: allowed });
  useRecentRecord("catalogue.product", productId, query.isSuccess);
  useScreenContribution(query.data ? { focus: { type: "catalogue.product", id: query.data.id, version: query.data.version } } : null);

  if (!allowed) return <PermissionDenied area={m.list.title.toLowerCase()} />;
  if (query.isPending) return <Loading label={m.detail.loading} variant="detail" />;
  if (query.isError) {
    if (query.error instanceof ProblemError && query.error.status === 404) return <NotAvailable />;
    return <ErrorState error={query.error} what={m.detail.loading} onRetry={() => void query.refetch()} />;
  }
  return <Record product={query.data} tab={tab} />;
}

function Record({ product, tab }: { product: ProductDetail; tab: ProductTab }) {
  const router = useRouter();
  // Selected immediately on press (no server round trip); re-derived when the URL's tab changes (back button).
  const [selected, setSelected] = useState({ fromUrl: tab, value: tab });
  if (selected.fromUrl !== tab) setSelected({ fromUrl: tab, value: tab });
  const decor = [product.decor.decor_no, product.decor.decor_name].filter(Boolean).join(" ");
  const meta = [
    product.subcategory ? `${product.category.name} › ${product.subcategory.name}` : product.category.name,
    product.brand,
    product.unit_of_sale,
    decor || null,
  ].filter((part): part is string => Boolean(part));

  const onTab = (key: Key) => {
    const next = PRODUCT_TABS.find((candidate) => candidate === String(key)) ?? "overview";
    setSelected({ fromUrl: tab, value: next });
    router.replace(productTabHref(product.id, next) as Parameters<typeof router.replace>[0], { scroll: false });
  };

  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/products", label: m.detail.back }}
        recordKey={product.product_key}
        title={product.product_name}
        status={<ProductStatusPill status={product.status} />}
        meta={meta.map((part, index) => (
          <span key={part} className="contents">
            {index > 0 ? <MetaDot /> : null}
            <span>{part}</span>
          </span>
        ))}
      />
      <Tabs
        label={m.detail.tabsLabel}
        selectedKey={selected.value}
        onSelectionChange={onTab}
        tabs={[
          { id: "overview", label: m.detail.tabs.overview, content: <ProductOverview product={product} /> },
          { id: "specification", label: m.detail.tabs.specification, content: <ProductSpecification product={product} /> },
          { id: "packaging", label: m.detail.tabs.packaging, content: <ProductPackaging product={product} /> },
          { id: "prices", label: m.detail.tabs.prices, content: <ProductPricesTab product={product} /> },
          { id: "material", label: m.detail.tabs.material, content: <ProductMaterial product={product} /> },
        ]}
      />
      <RailContent>
        <ProductContext product={product} />
      </RailContent>
    </div>
  );
}

function ProductContext({ product }: { product: ProductDetail }) {
  const r = m.detail.rail;
  const priced = product.prices?.filter((column) => column.status === "found" && column.unit_price) ?? [];
  return (
    <div className="flex flex-col gap-4 text-sm">
      <h2 className="text-base font-[650] text-ink">{r.title}</h2>
      <DescriptionList
        items={[
          { term: r.category, description: product.subcategory ? `${product.category.name} › ${product.subcategory.name}` : product.category.name },
          { term: r.status, description: <ProductStatusPill status={product.status} /> },
          { term: r.updated, description: <LocalDateTime value={product.updated_at} /> },
          { term: r.completeness, description: m.detail.completeness.score(product.completeness.checks_passed, product.completeness.checks_evaluated) },
          ...(product.prices !== null
            ? [
                {
                  term: r.prices,
                  description:
                    priced.length > 0 ? (
                      <ul className="flex flex-col">
                        {priced.map((column) => (
                          <li key={column.currency} className="tabular">
                            <Money value={column.unit_price} maxFractionDigits={4} />
                            {column.unit_code ? <span className="text-ink-muted"> / {column.unit_code}</span> : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-ink-muted">{r.noPrices}</span>
                    ),
                  numeric: true,
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
