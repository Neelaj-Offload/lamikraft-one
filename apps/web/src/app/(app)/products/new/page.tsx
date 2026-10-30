import type { Metadata } from "next";
import { NewProductForm } from "@/features/catalogue/product-form";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-new");

export const metadata: Metadata = { title: `${route.label} · Products` };

export default function NewProductPage() {
  return <NewProductForm />;
}
