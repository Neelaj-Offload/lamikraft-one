import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { DocumentRecord } from "~/screens/finance/document-record";
import { documentViewFrom } from "~/screens/finance/views";

export const metadata: Metadata = { title: "Credit note · Finance" };

/** A credit note: overview, lines, settlements, activity (`?view=`). */
export default async function CreditNotePage({
  params,
  searchParams,
}: {
  params: Promise<{ creditNoteId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { creditNoteId } = await params;
  if (!UUID_PATTERN.test(creditNoteId)) notFound();
  const view = documentViewFrom((await searchParams).view);
  return <DocumentRecord key={creditNoteId} kind="credit_note" id={creditNoteId} view={view} />;
}
