"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Key } from "react-aria-components";
import { RailContent } from "@/components/shell/context-rail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDateTime, Money } from "@/components/ui/format";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { fetchProduct as fetchProductRecord, setArchived } from "@/features/catalogue/api";
import {
  DECOR_FIELDS,
  MASTER_FIELDS,
  PACKAGING_FIELDS,
  PROVENANCE_FIELDS,
  SPEC_FIELDS,
  masterValues,
  packagingValues,
  specValues,
} from "@/features/catalogue/form-model";
import { MediaPanel } from "@/features/catalogue/media-panel";
import { ProductHistory } from "@/features/catalogue/product-history";
import { SectionEditor } from "@/features/catalogue/section-editor";
import type { ProductDetail as ProductRecord } from "@/features/catalogue/types";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useRecentRecord } from "@/lib/recent/recent-records";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { parseProductDetail } from "./parse";
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

/** The cache keeps the server record as sent (the editors round-trip every field); the views read the parsed record. */
function selectRecord(raw: ProductRecord): { raw: ProductRecord; product: ProductDetail } {
  return { raw, product: parseProductDetail(raw) };
}

/**
 * The product record: header with the archive/restore actions the server allows, in-page tabs mirrored in `?tab=`
 * (overview, specification, packaging, prices, material, and media and history when the server lists those
 * sections), inline editors on the overview, specification and packaging tabs, and a compact context in the rail.
 */
export function ProductDetailView({ productId, tab }: { productId: string; tab: ProductTab }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const query = useQuery({
    queryKey: queryKeys.catalogue.product(productId),
    queryFn: ({ signal }) => fetchProductRecord(productId, signal),
    select: selectRecord,
    enabled: allowed,
  });
  useRecentRecord("catalogue.product", productId, query.isSuccess);
  useScreenContribution(query.data ? { focus: { type: "catalogue.product", id: query.data.product.id, version: query.data.product.version } } : null);

  if (!allowed) return <PermissionDenied area={m.list.title.toLowerCase()} />;
  if (query.isPending) return <Loading label={m.detail.loading} variant="detail" />;
  if (query.isError) {
    if (query.error instanceof ProblemError && query.error.status === 404) return <NotAvailable />;
    return <ErrorState error={query.error} what={m.detail.loading} onRetry={() => void query.refetch()} />;
  }
  return <Record raw={query.data.raw} product={query.data.product} tab={tab} />;
}

function Record({ raw, product, tab }: { raw: ProductRecord; product: ProductDetail; tab: ProductTab }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [archiveOpen, setArchiveOpen] = useState(false);
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
  const serverSections = new Set(product.sections.map((section) => section.key));

  const refresh = (next?: ProductRecord) => {
    if (next) queryClient.setQueryData(queryKeys.catalogue.product(product.id), next);
    for (const key of invalidationMap["catalogue.changed"]) void queryClient.invalidateQueries({ queryKey: key });
  };
  const onSaved = (next: ProductRecord, warnings: string[]) => {
    refresh(next);
    toast.success("Saved", warnings.length ? { description: `${warnings.length} warning(s): ${warnings.slice(0, 3).join("; ")}` } : {});
  };
  const archive = useMutation({
    mutationFn: ({ archived, reason }: { archived: boolean; reason: string | null }) => setArchived(product.id, archived, product.version, reason),
    onSuccess: (next) => {
      setArchiveOpen(false);
      refresh(next);
      toast.success(next.archived_at ? "Product archived" : "Product restored");
    },
    onError: (error) => toast.error(conflictFromError(error) ? "The product changed; reload and try again" : "The change was not saved"),
  });

  const onTab = (key: Key) => {
    const next = PRODUCT_TABS.find((candidate) => candidate === String(key)) ?? "overview";
    setSelected({ fromUrl: tab, value: next });
    router.replace(productTabHref(product.id, next) as Parameters<typeof router.replace>[0], { scroll: false });
  };

  const tabs = [
    {
      id: "overview",
      label: m.detail.tabs.overview,
      content: (
        <SectionEditor
          key={`master-${raw.version}`}
          product={raw}
          mode="master"
          groups={[
            { title: "Master data", fields: MASTER_FIELDS },
            { title: "Decor", fields: DECOR_FIELDS },
            { title: "Source and provenance", fields: PROVENANCE_FIELDS },
          ]}
          initial={masterValues(raw)}
          onSaved={onSaved}
        >
          <ProductOverview product={product} />
        </SectionEditor>
      ),
    },
    {
      id: "specification",
      label: m.detail.tabs.specification,
      content: (
        <SectionEditor key={`spec-${raw.version}`} product={raw} mode="specification" groups={[{ title: "Specification", fields: SPEC_FIELDS }]} initial={specValues(raw)} onSaved={onSaved}>
          <ProductSpecification product={product} />
        </SectionEditor>
      ),
    },
    {
      id: "packaging",
      label: m.detail.tabs.packaging,
      content: (
        <SectionEditor key={`pack-${raw.version}`} product={raw} mode="packaging" groups={[{ title: "Packaging", fields: PACKAGING_FIELDS }]} initial={packagingValues(raw)} onSaved={onSaved}>
          <ProductPackaging product={product} />
        </SectionEditor>
      ),
    },
    { id: "prices", label: m.detail.tabs.prices, content: <ProductPricesTab product={product} /> },
    { id: "material", label: m.detail.tabs.material, content: <ProductMaterial product={product} /> },
    ...(serverSections.has("media")
      ? [
          {
            id: "media",
            label: raw.media_count ? `${m.detail.tabs.media} (${raw.media_count})` : m.detail.tabs.media,
            content: <MediaPanel productId={product.id} canManage={Boolean(raw.capabilities.manage_media?.allowed)} />,
          },
        ]
      : []),
    ...(serverSections.has("history") ? [{ id: "history", label: m.detail.tabs.history, content: <ProductHistory productId={product.id} /> }] : []),
  ];
  const selectedKey = tabs.some((entry) => entry.id === selected.value) ? selected.value : "overview";

  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/products", label: m.detail.back }}
        recordKey={product.product_key}
        title={product.product_name}
        status={
          <span className="inline-flex items-center gap-2">
            <ProductStatusPill status={product.status} />
            {product.archived_at ? <Badge>{m.detail.archived}</Badge> : null}
          </span>
        }
        meta={meta.map((part, index) => (
          <span key={part} className="contents">
            {index > 0 ? <MetaDot /> : null}
            <span>{part}</span>
          </span>
        ))}
        actions={
          product.capabilities.archive?.allowed || product.capabilities.restore?.allowed ? (
            <>
              {product.capabilities.archive?.allowed ? (
                <Button variant="danger" onPress={() => setArchiveOpen(true)}>
                  {m.detail.archive}
                </Button>
              ) : null}
              {product.capabilities.restore?.allowed ? (
                <Button onPress={() => archive.mutate({ archived: false, reason: null })} isPending={archive.isPending}>
                  {m.detail.restore}
                </Button>
              ) : null}
            </>
          ) : undefined
        }
      />
      <ReasonDialog
        title="Archive product"
        description={`${product.product_key} disappears from lists and pickers; quotes keep their snapshot.`}
        requireNote={false}
        noteLabel="Reason (optional)"
        confirmLabel={m.detail.archive}
        isOpen={archiveOpen}
        isPending={archive.isPending}
        onOpenChange={setArchiveOpen}
        onConfirm={(_code, note) => archive.mutate({ archived: true, reason: note.trim() || null })}
      />
      <Tabs label={m.detail.tabsLabel} selectedKey={selectedKey} onSelectionChange={onTab} tabs={tabs} />
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
