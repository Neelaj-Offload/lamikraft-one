import type { Metadata } from "next";
import { SalesHub } from "@/features/sales/sales-hub";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales");

export const metadata: Metadata = { title: route.label };

export default function SalesPage() {
  return <SalesHub />;
}
