import type { Metadata } from "next";
import { IntegrationsScreen } from "~/screens/settings-ai/integrations-screen";

export const metadata: Metadata = { title: "Integrations · Settings" };

/** Which connections run live and which are simulated. Read-only. */
export default function SettingsIntegrationsPage() {
  return <IntegrationsScreen />;
}
