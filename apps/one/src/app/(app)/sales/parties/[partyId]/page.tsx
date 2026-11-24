import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { customerViewFrom } from "~/screens/sales/customers/labels";
import { CustomerRecord } from "~/screens/sales/customers/record";

export const metadata: Metadata = { title: "Customer" };

/** A customer's profile; `?view=` picks contacts, quotations, samples, orders, notes or activity. */
export default async function CustomerPage({
  params,
  searchParams,
}: {
  params: Promise<{ partyId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { partyId } = await params;
  if (!UUID_PATTERN.test(partyId)) notFound();
  const view = customerViewFrom((await searchParams).view);
  return <CustomerRecord key={partyId} partyId={partyId} view={view} />;
}
