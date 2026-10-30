import type { Metadata } from "next";
import { NewCustomProduct } from "@/features/custom-products/detail";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-custom-product-new");

export const metadata: Metadata = { title: `${route.label} · Sales` };

export default function NewCustomProductPage() {
  return <NewCustomProduct />;
}
