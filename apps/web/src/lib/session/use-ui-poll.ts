"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api/client";
import { isEndpointUnavailable } from "@/lib/api/errors";
import { createEtagFetcher, UI_POLL_MS } from "@/lib/api/polling";
import { queryKeys } from "@/lib/api/query-keys";
import { parseUiPoll } from "./parse";
import type { UiPollState } from "./types";

/**
 * Polls `GET /api/v1/ui/poll` every 60 s while the tab is visible (TanStack Query pauses
 * interval refetches in background tabs), revalidating with ETag. A server without the
 * endpoint answers 404 once and polling stops instead of retrying every minute.
 */
export function useUiPoll(enabled = true) {
  const [fetcher] = useState(() => createEtagFetcher<unknown>(api, "/api/v1/ui/poll"));
  return useQuery<UiPollState>({
    queryKey: queryKeys.ui.poll(),
    queryFn: async ({ signal }) => parseUiPoll(await fetcher(signal)),
    enabled,
    refetchInterval: (query) => (query.state.error && isEndpointUnavailable(query.state.error) ? false : UI_POLL_MS),
    refetchIntervalInBackground: false,
    staleTime: UI_POLL_MS,
  });
}
