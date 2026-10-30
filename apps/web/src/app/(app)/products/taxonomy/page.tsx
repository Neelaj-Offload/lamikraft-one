import type { Metadata } from "next";
import { TaxonomyManager } from "@/features/catalogue/taxonomy";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-taxonomy");

export const metadata: Metadata = { title: `${route.label} · Products` };

export default function TaxonomyPage() {
  return <TaxonomyManager />;
}
