import type { Metadata, Route } from "next";
import { notFound, redirect } from "next/navigation";
import { productTabForSection, productTabHref } from "@/features/products/detail-state";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("product-section");

export const metadata: Metadata = { title: `${route.label} · Products` };

/**
 * The server's section paths (`/products/{id}/specifications`, `/media`, `/history`, …) open the record on the
 * matching tab; the record keeps its tab in `?tab=`.
 */
export default async function ProductSectionPage({ params }: { params: Promise<{ productId: string; section: string }> }) {
  const { productId, section } = await params;
  if (!UUID_PATTERN.test(productId)) notFound();
  const tab = productTabForSection(section);
  if (!tab) notFound();
  redirect(productTabHref(productId, tab) as Route);
}
