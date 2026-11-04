import type { Metadata } from "next";
import { MovementsScreen } from "@/features/inventory/stock-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-movements");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** The immutable stock ledger, newest first. */
export default async function InventoryMovementsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const raw = (await searchParams).offset;
  const offset = Number.parseInt((Array.isArray(raw) ? raw[0] : raw) ?? "0", 10);
  return <MovementsScreen offset={Number.isFinite(offset) && offset > 0 ? offset : 0} />;
}
