import type { Metadata } from "next";
import { ReferenceData, type ReferenceView } from "~/screens/settings-data/reference";

export const metadata: Metadata = { title: "Reference data · Settings" };

/** Currencies, units of measure and the work calendar, chosen with `?view=`. */
export default async function ReferencePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { view } = await searchParams;
  const selected: ReferenceView = view === "units" || view === "calendar" ? view : "currencies";
  return <ReferenceData view={selected} />;
}
