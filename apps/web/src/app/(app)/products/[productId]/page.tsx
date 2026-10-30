import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ProductDetailView } from "@/features/catalogue/product-detail";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("product");

export const metadata: Metadata = { title: `${route.label} · Products` };

export default async function ProductPage({ params }: { params: Promise<{ productId: string }> }) {
  const { productId } = await params;
  if (!UUID_PATTERN.test(productId)) notFound();
  return <ProductDetailView key={productId} productId={productId} section="overview" />;
}
