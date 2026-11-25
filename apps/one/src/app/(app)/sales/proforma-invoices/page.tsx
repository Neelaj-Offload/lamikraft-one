import type { Metadata } from "next";
import { ProformaList } from "~/screens/sales/proforma/list";
import { proformaListHref, proformaListStateFrom } from "~/screens/sales/proforma/list-state";

export const metadata: Metadata = { title: "Proforma invoices" };

/** Proforma invoices, newest first; `?status=` and `?q=` filter. */
export default async function ProformaInvoicesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = proformaListStateFrom(await searchParams);
  return <ProformaList key={proformaListHref(state)} state={state} />;
}
