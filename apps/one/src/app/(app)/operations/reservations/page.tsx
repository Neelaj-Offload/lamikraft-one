import type { Metadata } from "next";
import { firstParam, offsetFrom } from "~/screens/stock/labels";
import { Reservations } from "~/screens/stock/reservations";

export const metadata: Metadata = { title: "Reservations · Operations" };

/** Stock held for orders and the open shortages; the status filter and the page offset live in the URL. */
export default async function ReservationsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <Reservations status={firstParam(params.status)} offset={offsetFrom(params.offset)} />;
}
