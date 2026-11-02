import type { Metadata } from "next";
import { SettingsHub } from "@/features/settings/settings-hub";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings");

export const metadata: Metadata = { title: route.label };

export default function SettingsPage() {
  return <SettingsHub />;
}
