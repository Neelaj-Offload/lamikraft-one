import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { PackingListRecord } from "~/screens/dispatch/packing-list-record";
import { packingViewFrom } from "~/screens/dispatch/views";

export const metadata: Metadata = { title: "Packing list · Operations" };

/** A packing list: overview, lines, container load (`?view=`). */
export default async function PackingListPage({
  params,
  searchParams,
}: {
  params: Promise<{ packingListId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { packingListId } = await params;
  if (!UUID_PATTERN.test(packingListId)) notFound();
  const view = packingViewFrom((await searchParams).view);
  return <PackingListRecord key={packingListId} packingListId={packingListId} view={view} />;
}
