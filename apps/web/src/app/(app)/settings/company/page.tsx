import type { Metadata } from "next";
import { CompanySettings } from "@/features/settings/company-settings";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-company");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function SettingsCompanyPage() {
  return <CompanySettings />;
}
