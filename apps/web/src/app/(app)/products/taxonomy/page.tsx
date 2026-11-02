import type { Metadata } from "next";
import { includeInactiveFrom } from "@/features/products/detail-state";
import { TaxonomyView } from "@/features/products/taxonomy";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-taxonomy");

export const metadata: Metadata = { title: `${route.label} · Products` };

/** Categories and subcategories; `?include_inactive=true` also lists the inactive ones. */
export default async function TaxonomyPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const includeInactive = includeInactiveFrom((await searchParams).include_inactive);
  return <TaxonomyView key={String(includeInactive)} includeInactive={includeInactive} />;
}
