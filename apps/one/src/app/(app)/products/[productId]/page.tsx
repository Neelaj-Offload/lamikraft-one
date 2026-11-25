import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { productViewForOldTab, productViewHref } from "~/screens/products/links";
import { ProductRecord } from "~/screens/products/product-record";

export const metadata: Metadata = { title: "Product · Catalogue" };

/** One product, opened on its summary. Links that still carry the old `?tab=` go to that view's own URL. */
export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ productId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { productId } = await params;
  if (!UUID_PATTERN.test(productId)) notFound();
  const view = productViewForOldTab((await searchParams).tab);
  if (view) redirect(productViewHref(productId, view));
  return <ProductRecord key={productId} productId={productId} view="summary" />;
}
