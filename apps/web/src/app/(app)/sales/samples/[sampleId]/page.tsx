import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SampleView } from "@/features/samples/samples";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-sample");

export const metadata: Metadata = { title: `${route.label} · Sales` };

export default async function SamplePage({ params }: { params: Promise<{ sampleId: string }> }) {
  const { sampleId } = await params;
  if (!UUID_PATTERN.test(sampleId)) notFound();
  return <SampleView key={sampleId} sampleId={sampleId} />;
}
