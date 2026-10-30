import type { Metadata } from "next";
import { getRoute } from "@/lib/routes";
import { SettingsHub } from "./_lib/hub";

const route = getRoute("settings");

export const metadata: Metadata = { title: route.label };

export default function SettingsPage() {
  return <SettingsHub />;
}
