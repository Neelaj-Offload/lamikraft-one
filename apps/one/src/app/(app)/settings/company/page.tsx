import type { Metadata } from "next";
import { CompanySettings } from "~/screens/settings-data/company";

export const metadata: Metadata = { title: "Company · Settings" };

/** Company settings: one view per setting, chosen with `?view=<key>`. */
export default async function CompanySettingsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { view } = await searchParams;
  return <CompanySettings view={typeof view === "string" ? view.slice(0, 120) : null} />;
}
