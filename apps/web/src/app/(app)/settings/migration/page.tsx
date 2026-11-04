import type { Metadata } from "next";
import { MigrationPage } from "@/features/migration/migration-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-migration");

export const metadata: Metadata = { title: `${route.label} · Settings` };

/** Settings › Migration: run history, the latest reconciliation, candidate customer links and opening balances. */
export default async function SettingsMigrationPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const search = await searchParams;
  const raw = Number.parseInt(typeof search.offset === "string" ? search.offset : "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % 25) : 0;
  return <MigrationPage key={offset} offset={offset} />;
}
