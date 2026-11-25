import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import type { Metadata } from "next";
import { VoiceSpeechProvider } from "@/features/briefing/listen/voice-speech";
import { parseBriefingView } from "@/features/briefing/parse";
import { queryKeys } from "@/lib/api/query-keys";
import { serverGetJson } from "@/lib/session/server";
import { TodayScreen } from "~/screens/today/today-screen";

export const metadata: Metadata = { title: "Today" };

/**
 * The briefing is fetched on the server (with the browser's cookies) so the first items are in the
 * HTML; the same query key hydrates the client. If the call fails or the payload is unreadable,
 * nothing is prefetched: the client fetches again and shows the problem in place.
 */
export default async function TodayPage() {
  const queryClient = new QueryClient();
  const raw = await serverGetJson("/api/v1/briefings/today");
  if (raw !== null) {
    try {
      queryClient.setQueryData(queryKeys.briefings.today(), parseBriefingView(raw));
    } catch {
      // Left to the client, which reports the unreadable response with a retry.
    }
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <VoiceSpeechProvider>
        <TodayScreen />
      </VoiceSpeechProvider>
    </HydrationBoundary>
  );
}
