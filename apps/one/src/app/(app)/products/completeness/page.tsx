import type { Metadata } from "next";
import { Completeness } from "~/screens/products/completeness";

export const metadata: Metadata = { title: "Completeness · Catalogue" };

export default function CompletenessPage() {
  return <Completeness />;
}
