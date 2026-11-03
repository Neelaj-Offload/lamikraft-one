import type { Metadata } from "next";
import { parseCorrelationId } from "@/features/ai-admin/parse";
import { TraceView } from "@/features/ai-admin/trace-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-ai-trace");

export const metadata: Metadata = { title: `${route.label} · AI · Settings` };

export default async function SettingsAiTracePage({ params }: { params: Promise<{ correlationId: string }> }) {
  const { correlationId } = await params;
  return <TraceView correlationId={parseCorrelationId(correlationId)} />;
}
