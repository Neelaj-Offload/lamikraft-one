import type { Metadata } from "next";
import { docStateFrom } from "@/features/finance/list-state";
import { DocumentList } from "~/screens/finance/document-list";

export const metadata: Metadata = { title: "Credit notes · Finance" };

/** Credit notes: search, status, the open switch and the page offset live in the URL. */
export default async function CreditNotesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = docStateFrom(await searchParams);
  return <DocumentList key={`${state.q}|${state.status}|${state.open}|${state.offset}`} kind="credit_note" state={state} />;
}
