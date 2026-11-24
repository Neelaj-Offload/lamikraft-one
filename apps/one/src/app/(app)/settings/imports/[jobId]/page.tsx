import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ImportJob } from "~/screens/settings-data/import-job";

export const metadata: Metadata = { title: "Import · Settings" };

/** One import, from mapping to result. */
export default async function ImportJobPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  if (!UUID_PATTERN.test(jobId)) notFound();
  return <ImportJob key={jobId} jobId={jobId} />;
}
