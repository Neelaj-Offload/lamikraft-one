import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { CustomProductRecord } from "~/screens/sales/custom-products/custom-product-record";
import { customProductViewFrom } from "~/screens/sales/quotations/views";

export const metadata: Metadata = { title: "Custom product · Sales" };

/** A custom product: overview, specification, samples and revisions, costing, activity (`?view=`). */
export default async function CustomProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ customProductId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { customProductId } = await params;
  if (!UUID_PATTERN.test(customProductId)) notFound();
  const view = customProductViewFrom((await searchParams).view);
  return <CustomProductRecord key={customProductId} customProductId={customProductId} view={view} />;
}
