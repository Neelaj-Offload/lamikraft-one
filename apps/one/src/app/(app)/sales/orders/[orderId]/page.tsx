import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { OrderRecord } from "~/screens/sales/orders/order-record";
import { orderViewFrom } from "~/screens/sales/quotations/views";

export const metadata: Metadata = { title: "Order · Sales" };

/** An order: overview, lines, stock and dispatch, activity (`?view=`). */
export default async function OrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ orderId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { orderId } = await params;
  if (!UUID_PATTERN.test(orderId)) notFound();
  const view = orderViewFrom((await searchParams).view);
  return <OrderRecord key={orderId} orderId={orderId} view={view} />;
}
