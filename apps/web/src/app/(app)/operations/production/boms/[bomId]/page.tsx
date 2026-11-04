import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BomScreen } from "@/features/production/master-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-bom");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A BOM version with its components and cost rollup. */
export default async function Page({ params }: { params: Promise<{ bomId: string }> }) {
  const { bomId } = await params;
  if (!UUID_PATTERN.test(bomId)) notFound();
  return <BomScreen key={bomId} bomId={bomId} />;
}
