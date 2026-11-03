import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ImportJobView } from "@/features/imports/workbench";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-import");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default async function ImportJobPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  if (!UUID_PATTERN.test(jobId)) notFound();
  return <ImportJobView key={jobId} jobId={jobId} />;
}
