import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import type { Metadata } from "next";
import { VoiceSpeechProvider } from "@/features/briefing/listen/voice-speech";
import { parseBriefingView } from "@/features/briefing/parse";
import { TodayView } from "@/features/briefing/today-view";
import { queryKeys } from "@/lib/api/query-keys";
import { getRoute } from "@/lib/routes";
import { serverGetJson } from "@/lib/session/server";

const route = getRoute("today");

export const metadata: Metadata = { title: route.label };

/**
 * The briefing is fetched on the server (with the browser's cookies) so the greeting and the
 * first items are in the HTML; the same query key hydrates the client. If the call fails or
 * the payload is unreadable, nothing is prefetched: the client fetches again and shows the
 * problem instead of an empty page.
 */
export default async function TodayPage() {
  const queryClient = new QueryClient();
  const raw = await serverGetJson("/api/v1/briefings/today");
  if (raw !== null) {
    try {
      queryClient.setQueryData(queryKeys.briefings.today(), parseBriefingView(raw));
    } catch {
      // Left to the client, which reports the unreadable response with Retry.
    }
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <VoiceSpeechProvider>
        <TodayView />
      </VoiceSpeechProvider>
    </HydrationBoundary>
  );
}
