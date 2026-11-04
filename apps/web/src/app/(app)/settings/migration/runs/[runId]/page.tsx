import type { Metadata } from "next";
import { issueFiltersFrom, parseRunId } from "@/features/migration/api";
import { RunDetailView } from "@/features/migration/run-detail";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-migration-run");

export const metadata: Metadata = { title: `${route.label} · Settings` };

/** One migration run: reconciliation report and quarantine browser (filters live in the URL). */
export default async function MigrationRunPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { runId } = await params;
  const filters = issueFiltersFrom(await searchParams);
  const id = parseRunId(runId);
  return <RunDetailView key={`${id}|${JSON.stringify(filters)}`} runId={id} filters={filters} />;
}
