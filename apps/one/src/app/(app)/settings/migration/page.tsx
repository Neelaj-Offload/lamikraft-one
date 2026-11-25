import type { Metadata } from "next";
import { Migration } from "~/screens/settings-data/migration";
import { migrationViewFrom } from "~/screens/settings-data/migration-shared";

export const metadata: Metadata = { title: "Migration · Settings" };

/** Migration: runs, legacy customer names and opening balances, chosen with `?view=`; the run page offset is in the URL. */
export default async function MigrationPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const search = await searchParams;
  const raw = Number.parseInt(typeof search.offset === "string" ? search.offset : "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % 25) : 0;
  const view = migrationViewFrom(search.view);
  return <Migration key={`${view}|${offset}`} view={view} offset={offset} />;
}
