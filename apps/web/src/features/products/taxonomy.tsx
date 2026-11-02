"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/choice";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { fetchCategories } from "./api";
import { productListHref } from "./list-state";
import { productsAreaNav, PRODUCTS_READ } from "./product-list";
import type { CategoryRead, SubcategoryRead } from "./types";

import { taxonomyHref } from "./detail-state";

export { includeInactiveFrom, taxonomyHref } from "./detail-state";

function CountLink({ count, href, locale }: { count: number; href: string; locale: string }) {
  const text = count === 1 ? m.taxonomy.product(formatCount(count, locale)) : m.taxonomy.products(formatCount(count, locale));
  return count > 0 ? (
    <Link href={href} className="text-sm whitespace-nowrap tabular">
      {text}
    </Link>
  ) : (
    <span className="text-sm whitespace-nowrap text-ink-muted tabular">{text}</span>
  );
}

function Subcategory({ subcategory, locale }: { subcategory: SubcategoryRead; locale: string }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
      <span className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-ink">{subcategory.name}</span>
        {!subcategory.is_active ? <Badge tone="neutral">{m.taxonomy.inactive}</Badge> : null}
        {subcategory.is_active && !subcategory.effective_active ? <Badge tone="neutral">{m.taxonomy.effectiveInactive}</Badge> : null}
        {subcategory.description ? <span className="text-sm text-ink-muted">{subcategory.description}</span> : null}
      </span>
      <CountLink count={subcategory.product_count} href={productListHref({ subcategory_id: subcategory.id })} locale={locale} />
    </li>
  );
}

function Category({ category, locale }: { category: CategoryRead; locale: string }) {
  const pages = category.source_catalog_page_start ? m.taxonomy.pageRange(category.source_catalog_page_start, category.source_catalog_page_end) : null;
  return (
    <SectionCard
      title={category.name}
      description={[category.description, pages].filter(Boolean).join(" · ") || undefined}
      actions={
        <>
          {!category.is_active ? <Badge tone="neutral">{m.taxonomy.inactive}</Badge> : null}
          <CountLink count={category.product_count} href={productListHref({ category_id: category.id })} locale={locale} />
        </>
      }
    >
      {category.subcategories.length === 0 ? (
        <p className="text-sm text-ink-muted">{m.taxonomy.noSubcategories}</p>
      ) : (
        <ul className="flex flex-col divide-y">
          {category.subcategories.map((subcategory) => (
            <Subcategory key={subcategory.id} subcategory={subcategory} locale={locale} />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

export function TaxonomyView({ includeInactive }: { includeInactive: boolean }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const query = useQuery({
    queryKey: queryKeys.catalogue.categories(includeInactive),
    queryFn: ({ signal }) => fetchCategories(includeInactive, signal),
    enabled: allowed,
  });
  const t = m.taxonomy;
  if (!allowed) return <PermissionDenied area={m.list.title.toLowerCase()} />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t.title}
        intro={t.intro}
        nav={productsAreaNav()}
        actions={
          <Switch isSelected={includeInactive} onChange={(next) => router.push(taxonomyHref(next) as Parameters<typeof router.push>[0])}>
            {t.includeInactive}
          </Switch>
        }
      />
      {query.isPending ? (
        <Loading label={t.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={t.what} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <EmptyState title={t.emptyTitle}>{t.empty}</EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          {query.data.map((category) => (
            <Category key={category.id} category={category} locale={zone.locale} />
          ))}
        </div>
      )}
    </div>
  );
}
