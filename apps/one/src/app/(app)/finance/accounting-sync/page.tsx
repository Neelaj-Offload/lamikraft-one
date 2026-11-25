import type { Metadata } from "next";
import { AccountingSync } from "~/screens/finance/accounting-sync";
import { exportIdFrom } from "~/screens/finance/views";

export const metadata: Metadata = { title: "Accounting sync · Finance" };

/** The accounting hand-off (Demo): status, exports (`?export=` marks one), tax profiles (`#tax-profiles`). */
export default async function AccountingSyncPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <AccountingSync exportId={exportIdFrom((await searchParams).export)} />;
}
