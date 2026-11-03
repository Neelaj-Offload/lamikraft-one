import type { Metadata } from "next";
import { AiSettingsView } from "@/features/ai-admin/ai-settings-view";
import { parseUsageDays } from "@/features/ai-admin/parse";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-ai");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default async function SettingsAiPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <AiSettingsView days={parseUsageDays(params.days)} />;
}
