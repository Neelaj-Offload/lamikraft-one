import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { BomRecord } from "~/screens/production/bom-record";
import { bomViewFrom } from "~/screens/production/views";

export const metadata: Metadata = { title: "Bill of materials · Operations" };

/** A bill of materials version: its components and its cost per unit (`?view=`). */
export default async function BomPage({
  params,
  searchParams,
}: {
  params: Promise<{ bomId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { bomId } = await params;
  if (!UUID_PATTERN.test(bomId)) notFound();
  const view = bomViewFrom((await searchParams).view);
  return <BomRecord key={bomId} bomId={bomId} view={view} />;
}
