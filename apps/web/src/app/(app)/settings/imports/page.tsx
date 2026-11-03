import type { Metadata } from "next";
import { DemoResetPanel } from "@/features/imports/demo-reset";
import { ImportHistory } from "@/features/imports/workbench";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-imports");

export const metadata: Metadata = { title: `${route.label} · Settings` };

/** Import history (durable, filtered by type in the URL) and, for demo companies, the catalogue reset. */
export default async function ImportsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const search = await searchParams;
  const type = typeof search.type === "string" ? search.type.slice(0, 40) : null;
  const raw = Number.parseInt(typeof search.offset === "string" ? search.offset : "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % 25) : 0;
  return (
    <div className="flex flex-col gap-10">
      <ImportHistory key={`${type}|${offset}`} importType={type} offset={offset} />
      <DemoResetPanel />
    </div>
  );
}
