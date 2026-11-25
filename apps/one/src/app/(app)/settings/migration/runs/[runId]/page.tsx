import type { Metadata } from "next";
import { issueFiltersFrom, parseRunId } from "@/features/migration/api";
import { MigrationRun } from "~/screens/settings-data/migration-run";
import { runViewFrom } from "~/screens/settings-data/migration-shared";

export const metadata: Metadata = { title: "Migration run · Settings" };

/** One migration run: its views are chosen with `?view=`; the issue filters live in the URL. */
export default async function MigrationRunPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { runId } = await params;
  const search = await searchParams;
  const id = parseRunId(runId);
  return <MigrationRun key={id ?? "none"} runId={id} view={runViewFrom(search.view)} filters={issueFiltersFrom(search)} />;
}
