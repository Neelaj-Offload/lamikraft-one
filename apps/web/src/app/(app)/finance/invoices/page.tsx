import type { Metadata } from "next";
import { DocumentList } from "@/features/finance/finance-screens";
import { docStateFrom } from "@/features/finance/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-invoices");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function InvoicesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <DocumentList kind="invoice" state={docStateFrom(await searchParams)} />;
}
