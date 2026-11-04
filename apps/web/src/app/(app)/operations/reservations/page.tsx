import type { Metadata } from "next";
import { ReservationsScreen } from "@/features/inventory/stock-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-reservations");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Reservations and the open shortages with their causes. */
export default async function ReservationsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  return <ReservationsScreen status={one("status") ?? null} offset={Number.isFinite(offset) && offset > 0 ? offset : 0} />;
}
