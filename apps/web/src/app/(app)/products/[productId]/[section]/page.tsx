import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PRODUCT_SECTIONS, ProductDetailView } from "@/features/catalogue/product-detail";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("product-section");

export const metadata: Metadata = { title: `${route.label} · Products` };

/** Deep-linked product tabs: /products/<id>/specifications, /packaging, /pricing, /media, /history. */
export default async function ProductSectionPage({ params }: { params: Promise<{ productId: string; section: string }> }) {
  const { productId, section } = await params;
  const known = PRODUCT_SECTIONS.find((s) => s === section);
  if (!UUID_PATTERN.test(productId) || !known) notFound();
  return <ProductDetailView key={productId} productId={productId} section={known} />;
}
