import type { Metadata } from "next";
import { DocumentList } from "@/features/finance/finance-screens";
import { docStateFrom } from "@/features/finance/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-credit-notes");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function CreditNotesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <DocumentList kind="credit_note" state={docStateFrom(await searchParams)} />;
}
