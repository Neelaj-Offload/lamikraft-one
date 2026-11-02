import type { Metadata } from "next";
import { IntegrationsView } from "@/features/settings/integrations-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-integrations");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function SettingsIntegrationsPage() {
  return <IntegrationsView />;
}
