import type { Metadata } from "next";
import { ReferenceData } from "@/features/settings/reference-data";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-reference");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function SettingsReferencePage() {
  return <ReferenceData />;
}
