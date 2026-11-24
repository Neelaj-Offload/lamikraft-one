"use client";

import { useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { conflictFromError, isProblemError } from "@/lib/api/errors";
import { formatCount } from "@/lib/format/money";
import { useRecentRecord } from "@/lib/recent/recent-records";
import { useSession } from "@/lib/session/context";
import { PRODUCTS_READ, useArchiveProduct, useProduct, useProductHistory, type LoadedProduct } from "~/data/products";
import { Page, PageHeader, PageSection, RecordHeader, type Crumb } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  IconButton,
  Menu,
  Modal,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  Timeline,
  toast,
  type Fact,
  type TabItem,
} from "~/ui";
import { ProductStatusBadge, SizeText, StandardPrice } from "./format";
import { productViewHref, type ProductView } from "./links";
import { ProductMaterial } from "./product-material";
import { ProductMedia } from "./product-media";
import { ProductPricing } from "./product-pricing";
import { ProductSummary } from "./product-summary";
import { ProductDetails, ProductPackaging, ProductSpecification } from "./product-views";

const CRUMBS: readonly Crumb[] = [{ label: "Catalogue", href: "/products" }];

const VIEW_LABEL: Record<ProductView, string> = {
  summary: "Summary",
  details: "Details",
  specifications: "Specification",
  packaging: "Packaging",
  pricing: "Prices",
  material: "Material",
  media: "Media",
  history: "History",
};

function humanise(text: string): string {
  const words = text.replace(/^catalogue\./, "").replace(/[._]/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : text;
}

function ProductHistory({ productId }: { productId: string }) {
  const history = useProductHistory(productId);
  return (
    <PageSection title="History" description="Every change to this product: who made it, when, and why.">
      {history.isPending ? (
        <LoadingBlock label="Loading history" lines={6} />
      ) : history.isError || !history.data ? (
        <ErrorBlock error={history.error} what="History" onRetry={() => void history.refetch()} />
      ) : history.data.items.length === 0 ? (
        <GlassPanel>
          <EmptyState icon="history" title="No changes recorded yet" text="Edits, archiving and media changes will be listed here as they happen." compact />
        </GlassPanel>
      ) : (
        <GlassPanel padding="lg">
          <Timeline
            label="Changes to this product"
            items={history.data.items.map((entry) => ({
              id: entry.id,
              title: humanise(entry.action),
              meta: (
                <>
                  <DateText value={entry.occurred_at} style="dayTime" /> · {entry.actor_name ?? humanise(entry.actor_type)}
                </>
              ),
              body:
                entry.changed_fields.length > 0 || entry.reason ? (
                  <>
                    {entry.changed_fields.length > 0 ? <span className="block">Changed: {entry.changed_fields.map((field) => field.replace(/_/g, " ")).join(", ")}.</span> : null}
                    {entry.reason ? <span className="block">Reason: {entry.reason}</span> : null}
                  </>
                ) : undefined,
              icon: /archiv/.test(entry.action) ? "archive" : /restor/.test(entry.action) ? "undo" : /media/.test(entry.action) ? "image" : /creat/.test(entry.action) ? "plus" : "edit",
            }))}
          />
        </GlassPanel>
      )}
    </PageSection>
  );
}

function ArchiveDialog({ product, isOpen, onOpenChange }: { product: LoadedProduct["product"]; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const archive = useArchiveProduct(product);
  const [reason, setReason] = useState("");
  const confirm = () =>
    archive.mutate(
      { archived: true, reason: reason.trim() || null },
      {
        onSuccess: () => {
          onOpenChange(false);
          setReason("");
          toast.success("Product archived", { description: `${product.product_key} is out of lists and pickers.` });
        },
        onError: (error) =>
          toast.error("The product was not archived", {
            description: conflictFromError(error) ? "It changed while this was open. Reload the page, then archive it again." : "Check your connection, then try again.",
          }),
      },
    );
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title={`Archive ${product.product_key}`}
      description="It leaves lists and pickers. Quotations already written keep their own copy, and you can restore it at any time."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)} isDisabled={archive.isPending}>
            Keep it
          </Button>
          <Button variant="danger" onPress={confirm} loading={archive.isPending}>
            Archive product
          </Button>
        </>
      }
    >
      <Textarea label="Reason" optional rows={2} value={reason} onChange={setReason} help="Kept in the product's history." />
    </Modal>
  );
}

function RecordSkeleton() {
  return (
    <Page>
      <div className="lk-glass record-head" role="status" aria-label="Loading the product">
        <Skeleton width={120} />
        <Skeleton width="45%" height={28} />
        <SkeletonText lines={2} />
      </div>
      <LoadingBlock lines={6} />
    </Page>
  );
}

/**
 * One product. The header says what it is and the few facts you always need; each view below has
 * one job and its own URL (the server's section paths), so every view can be linked and bookmarked.
 */
export function ProductRecord({ productId, view }: { productId: string; view: ProductView }) {
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const query = useProduct(productId, allowed);
  const [archiving, setArchiving] = useState(false);
  useRecentRecord("catalogue.product", productId, query.isSuccess);
  useScreenContribution(query.data ? { focus: { type: "catalogue.product", id: query.data.product.id, version: query.data.product.version } } : null);

  if (!allowed) {
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title="Product" />
        <NotPermitted what="The catalogue" icon="box" />
      </Page>
    );
  }
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError || !query.data) {
    const missing = isProblemError(query.error) && query.error.status === 404;
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title={missing ? "This product is not in the catalogue" : "Product"} />
        {missing ? (
          <GlassPanel>
            <EmptyState
              icon="box"
              title="Nothing lives at this link"
              text="The product may have been removed, or the link is out of date."
              actions={<ButtonLink href="/products">Open the catalogue</ButtonLink>}
            />
          </GlassPanel>
        ) : (
          <ErrorBlock error={query.error} what="This product" onRetry={() => void query.refetch()} />
        )}
      </Page>
    );
  }

  const { raw, product } = query.data;
  return <Loaded raw={raw} product={product} view={view} locale={zone.locale} archiving={archiving} setArchiving={setArchiving} />;
}

function Loaded({
  raw,
  product,
  view,
  locale,
  archiving,
  setArchiving,
}: LoadedProduct & { view: ProductView; locale: string; archiving: boolean; setArchiving: (open: boolean) => void }) {
  const restore = useArchiveProduct(product);
  const sections = new Set(product.sections.map((section) => section.key));
  const views: ProductView[] = ["summary", "details", "specifications", "packaging", "pricing", "material"];
  if (sections.has("media")) views.push("media");
  if (sections.has("history")) views.push("history");
  const tabs: TabItem[] = views.map((id) => ({
    id,
    label: VIEW_LABEL[id],
    href: productViewHref(product.id, id),
    count: id === "media" && raw.media_count > 0 ? raw.media_count : undefined,
  }));
  const current: ProductView = views.includes(view) ? view : "summary";

  const decor = [product.decor.decor_no, product.decor.decor_name].filter(Boolean).join(" ");
  const standard = product.prices?.find((column) => column.status === "found" && column.unit_price) ?? product.prices?.[0] ?? null;
  const facts: Fact[] = [
    { label: "Decor", value: decor || null, icon: "swatch" },
    { label: "Size, mm", value: <SizeText size={product.size} thicknessMm={product.thickness_mm} />, icon: "ruler" },
    { label: "Sold by", value: product.unit_of_sale, icon: "box" },
    { label: "Per carton", value: product.carton_qty === null ? null : <span className="lk-tnum">{formatCount(product.carton_qty, locale)}</span>, icon: "packageOpen" },
  ];
  if (product.prices !== null) facts.push({ label: "Standard price", value: <StandardPrice column={standard} />, icon: "tag" });

  const canArchive = product.capabilities.archive?.allowed === true;
  const canRestore = product.capabilities.restore?.allowed === true;
  const onRestore = () =>
    restore.mutate(
      { archived: false, reason: null },
      {
        onSuccess: () => toast.success("Product restored", { description: `${product.product_key} is back in lists and pickers.` }),
        onError: (error) =>
          toast.error("The product was not restored", {
            description: conflictFromError(error) ? "It changed while this was open. Reload the page, then restore it again." : "Check your connection, then try again.",
          }),
      },
    );

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...CRUMBS, { label: product.product_key }]}
        code={product.product_key}
        title={product.product_name}
        status={
          <>
            <ProductStatusBadge status={product.status} />
            {product.archived_at ? <Badge icon="archive">Archived</Badge> : null}
          </>
        }
        lead={[product.subcategory ? `${product.category.name}, ${product.subcategory.name}` : product.category.name, product.brand].filter(Boolean).join(" · ")}
        facts={<FactStrip items={facts} />}
        actions={
          canRestore || canArchive ? (
            <>
              {canRestore ? (
                <Button variant="inverse" iconLeft="undo" onPress={onRestore} loading={restore.isPending}>
                  Restore product
                </Button>
              ) : null}
              {canArchive ? (
                <Menu
                  label="More actions for this product"
                  placement="bottom end"
                  items={[{ id: "archive", label: "Archive product", icon: "archive", tone: "danger", description: "Hides it from lists and pickers", onAction: () => setArchiving(true) }]}
                  trigger={<IconButton icon="more" label="More actions" />}
                />
              ) : null}
            </>
          ) : undefined
        }
      >
        <Tabs label="Views of this product" selectedKey={current} tabs={tabs} />
      </RecordHeader>

      {product.archived_at ? (
        <Banner tone="neutral" icon="archive" title="This product is archived.">
          It is hidden from lists and pickers and cannot be edited{canRestore ? ". Restore it to sell it again." : "."}
        </Banner>
      ) : null}

      {current === "summary" ? <ProductSummary raw={raw} product={product} /> : null}
      {current === "details" ? <ProductDetails key={`details-${raw.version}`} raw={raw} product={product} /> : null}
      {current === "specifications" ? <ProductSpecification key={`spec-${raw.version}`} raw={raw} product={product} /> : null}
      {current === "packaging" ? <ProductPackaging key={`pack-${raw.version}`} raw={raw} product={product} /> : null}
      {current === "pricing" ? <ProductPricing product={product} /> : null}
      {current === "material" ? <ProductMaterial product={product} /> : null}
      {current === "media" ? <ProductMedia productId={product.id} canManage={raw.capabilities.manage_media?.allowed === true} /> : null}
      {current === "history" ? <ProductHistory productId={product.id} /> : null}

      {canArchive ? <ArchiveDialog product={product} isOpen={archiving} onOpenChange={setArchiving} /> : null}
    </Page>
  );
}
