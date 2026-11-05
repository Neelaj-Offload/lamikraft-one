import type { Metadata } from "next";
import { DocWorkspace } from "@/features/finance/doc-workspace";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-credit-note");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function CreditNotePage({ params }: { params: Promise<{ creditNoteId: string }> }) {
  const { creditNoteId } = await params;
  return <DocWorkspace kind="credit_note" id={creditNoteId} />;
}
