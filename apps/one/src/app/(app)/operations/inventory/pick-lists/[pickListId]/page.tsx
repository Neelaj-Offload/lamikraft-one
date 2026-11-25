import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { stockRecordViewFrom } from "~/screens/stock/labels";
import { PickListRecord } from "~/screens/stock/pick-list-record";

export const metadata: Metadata = { title: "Pick list · Operations" };

/** A pick list: overview and pick lines (`?view=`). */
export default async function PickListPage({
  params,
  searchParams,
}: {
  params: Promise<{ pickListId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pickListId } = await params;
  if (!UUID_PATTERN.test(pickListId)) notFound();
  const view = stockRecordViewFrom((await searchParams).view);
  return <PickListRecord key={pickListId} pickListId={pickListId} view={view} />;
}
