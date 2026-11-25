import type { Metadata } from "next";
import { CustomerCreate } from "~/screens/sales/customers/create";

export const metadata: Metadata = { title: "Add a lead or customer" };

/** `?status=prospect` opens the form on "Lead" (the Leads list links here that way). */
export default async function NewCustomerPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const raw = (await searchParams).status;
  const stage = raw === "prospect" ? "prospect" : "active";
  return <CustomerCreate key={stage} stage={stage} />;
}
