import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { productTabFrom } from "@/features/products/detail-state";
import { ProductDetailView } from "@/features/products/product-detail";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-product");

export const metadata: Metadata = { title: `${route.label} · Products` };

/** The product record; the selected tab is mirrored in `?tab=`. */
export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ productId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { productId } = await params;
  if (!UUID_PATTERN.test(productId)) notFound();
  const tab = productTabFrom((await searchParams).tab);
  return <ProductDetailView key={productId} productId={productId} tab={tab} />;
}
