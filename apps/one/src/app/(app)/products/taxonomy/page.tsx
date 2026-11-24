import type { Metadata } from "next";
import { Taxonomy } from "~/screens/products/taxonomy";

export const metadata: Metadata = { title: "Taxonomy · Catalogue" };

export default function TaxonomyPage() {
  return <Taxonomy />;
}
