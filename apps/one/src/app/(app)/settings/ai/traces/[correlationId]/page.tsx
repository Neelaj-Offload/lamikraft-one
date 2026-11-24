import type { Metadata } from "next";
import { parseCorrelationId } from "@/features/ai-admin/parse";
import { TraceScreen } from "~/screens/settings-ai/trace-screen";

export const metadata: Metadata = { title: "Trace · AI · Settings" };

/** One assistant request, step by step. An id that does not parse shows the "no trace" state. */
export default async function SettingsAiTracePage({ params }: { params: Promise<{ correlationId: string }> }) {
  const { correlationId } = await params;
  return <TraceScreen correlationId={parseCorrelationId(correlationId)} />;
}
