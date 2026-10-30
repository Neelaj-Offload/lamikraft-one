import type { Metadata } from "next";
import { CompletenessReport } from "@/features/catalogue/completeness";
import { getRoute } from "@/lib/routes";

const route = getRoute("products-completeness");

export const metadata: Metadata = { title: `${route.label} · Products` };

export default function CompletenessPage() {
  return <CompletenessReport />;
}
