import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { productViewFrom, productViewHref } from "~/screens/products/links";
import { ProductRecord } from "~/screens/products/product-record";

export const metadata: Metadata = { title: "Product · Catalogue" };

/**
 * One view of a product. The server's section paths (`/specifications`, `/packaging`, `/pricing`,
 * `/media`, `/history`) are the record's tabs, joined by `/details` and `/material`.
 */
export default async function ProductSectionPage({ params }: { params: Promise<{ productId: string; section: string }> }) {
  const { productId, section } = await params;
  if (!UUID_PATTERN.test(productId)) notFound();
  const view = productViewFrom(section);
  if (!view) notFound();
  if (view === "summary") redirect(productViewHref(productId, "summary"));
  return <ProductRecord key={productId} productId={productId} view={view} />;
}
