import type { Metadata } from "next";
import { AuditPage, type AuditSearchParams } from "@/features/settings/audit-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-audit");

export const metadata: Metadata = { title: `${route.label} · Settings` };

/** The audit log: filters and the keyset cursor live in the URL; the server prefetches the page. */
export default function SettingsAuditPage({ searchParams }: { searchParams: AuditSearchParams }) {
  return <AuditPage searchParams={searchParams} />;
}
