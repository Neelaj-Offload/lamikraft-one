import type { Metadata } from "next";
import { FactoryOrders } from "~/screens/stock/factory-orders";

export const metadata: Metadata = { title: "Factory orders" };

export default function FactoryOrdersPage() {
  return <FactoryOrders />;
}
