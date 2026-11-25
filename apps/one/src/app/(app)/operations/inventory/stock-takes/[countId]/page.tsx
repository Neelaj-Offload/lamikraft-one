import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { stockRecordViewFrom } from "~/screens/stock/labels";
import { StockTakeRecord } from "~/screens/stock/stock-take-record";

export const metadata: Metadata = { title: "Stock take · Operations" };

/** A stock take: overview and count sheet (`?view=`). */
export default async function StockTakePage({
  params,
  searchParams,
}: {
  params: Promise<{ countId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { countId } = await params;
  if (!UUID_PATTERN.test(countId)) notFound();
  const view = stockRecordViewFrom((await searchParams).view);
  return <StockTakeRecord key={countId} countId={countId} view={view} />;
}
