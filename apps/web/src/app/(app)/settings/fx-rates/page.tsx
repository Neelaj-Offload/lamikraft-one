import type { Metadata } from "next";
import { FxRates } from "@/features/pricing/fx-rates";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-fx-rates");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function FxRatesRoute() {
  return <FxRates />;
}
