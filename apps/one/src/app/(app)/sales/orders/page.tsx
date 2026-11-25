import type { Metadata } from "next";
import { orderListStateFrom } from "@/features/orders/list-state";
import { OrderList } from "~/screens/sales/orders/order-list";

export const metadata: Metadata = { title: "Orders · Sales" };

/** Orders: search, status and the page offset live in the URL. */
export default async function OrdersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = orderListStateFrom(await searchParams);
  return <OrderList key={`${state.q}|${state.status}|${state.offset}`} state={state} />;
}
