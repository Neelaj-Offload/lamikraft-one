import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OrderWorkspace } from "@/features/orders/order-workspace";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-order");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** The sales order workspace: lines, reservations, delivery documents, history and the allowed actions. */
export default async function SalesOrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = await params;
  if (!UUID_PATTERN.test(orderId)) notFound();
  return <OrderWorkspace key={orderId} orderId={orderId} />;
}
