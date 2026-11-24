import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { sampleViewFrom } from "~/screens/sales/samples/labels";
import { SampleRecord } from "~/screens/sales/samples/record";

export const metadata: Metadata = { title: "Sample" };

export default async function SamplePage({
  params,
  searchParams,
}: {
  params: Promise<{ sampleId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { sampleId } = await params;
  if (!UUID_PATTERN.test(sampleId)) notFound();
  return <SampleRecord key={sampleId} sampleId={sampleId} view={sampleViewFrom((await searchParams).view)} />;
}
