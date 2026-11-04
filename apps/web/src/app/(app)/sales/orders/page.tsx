import type { Metadata } from "next";
import { OrderList, orderListStateFrom } from "@/features/orders/order-list";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-orders");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Sales orders: search, status and the page offset live in the URL. */
export default async function SalesOrdersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <OrderList state={orderListStateFrom(await searchParams)} />;
}
