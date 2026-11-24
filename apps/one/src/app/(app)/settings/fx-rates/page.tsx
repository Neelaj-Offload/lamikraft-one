import type { Metadata } from "next";
import { FxRates, type FxView } from "~/screens/settings-data/fx-rates";

export const metadata: Metadata = { title: "Exchange rates · Settings" };

/** Exchange rates: the rates and the conversion policy, chosen with `?view=`. */
export default async function FxRatesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { view } = await searchParams;
  const selected: FxView = view === "policy" ? "policy" : "rates";
  return <FxRates view={selected} />;
}
