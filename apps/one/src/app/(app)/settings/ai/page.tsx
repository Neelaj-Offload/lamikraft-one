import type { Metadata } from "next";
import { parseUsageDays } from "@/features/ai-admin/parse";
import { AiScreen } from "~/screens/settings-ai/ai-screen";
import { parseAiView } from "~/screens/settings-ai/views";

export const metadata: Metadata = { title: "AI · Settings" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** The assistant's health, usage and routing; `?view=` picks the view, `?days=` the usage window. */
export default async function SettingsAiPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  return <AiScreen view={parseAiView(params.view)} days={parseUsageDays(params.days)} />;
}
