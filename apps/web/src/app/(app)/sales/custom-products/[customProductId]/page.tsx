import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CustomProductView } from "@/features/custom-products/detail";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-custom-product");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** A custom product: every legacy field, workflow, spec revisions and samples, promotion, protected costing. */
export default async function CustomProductPage({ params }: { params: Promise<{ customProductId: string }> }) {
  const { customProductId } = await params;
  if (!UUID_PATTERN.test(customProductId)) notFound();
  return <CustomProductView key={customProductId} customProductId={customProductId} />;
}
