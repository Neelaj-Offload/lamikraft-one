import type { Metadata } from "next";
import { docStateFrom } from "@/features/finance/list-state";
import { DocumentList } from "~/screens/finance/document-list";

export const metadata: Metadata = { title: "Invoices · Finance" };

/** Invoices: search, status, the open and overdue switches and the page offset live in the URL. */
export default async function InvoicesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = docStateFrom(await searchParams);
  return <DocumentList key={`${state.q}|${state.status}|${state.open}|${state.overdue}|${state.offset}`} kind="invoice" state={state} />;
}
