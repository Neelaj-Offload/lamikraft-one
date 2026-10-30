import type { Metadata } from "next";
import { CustomerTypesManager } from "@/features/parties/parties";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-customer-types");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function CustomerTypesPage() {
  return <CustomerTypesManager />;
}
