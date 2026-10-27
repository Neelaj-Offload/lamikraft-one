"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { isEndpointUnavailable } from "@/lib/api/errors";
import { createEtagFetcher, UI_POLL_MS, type EtagFetcher } from "@/lib/api/polling";
import { queryKeys } from "@/lib/api/query-keys";
import { parseUiPoll } from "./parse";
import type { UiPollState } from "./types";

// One fetcher per tab, so every screen that reads the poll shares one ETag validator.
let fetcher: EtagFetcher<unknown> | null = null;

function pollFetcher(): EtagFetcher<unknown> {
  fetcher ??= createEtagFetcher<unknown>(api, "/api/v1/ui/poll");
  return fetcher;
}

/**
 * The poll's refetch interval: every 60 s, and never again once the server answered that the
 * endpoint does not exist (404/405/501), so a server without the ui module costs one request.
 */
export function uiPollInterval(error: unknown): number | false {
  return error && isEndpointUnavailable(error) ? false : UI_POLL_MS;
}

/**
 * Polls `GET /api/v1/ui/poll` every 60 s while the tab is visible (TanStack Query pauses
 * interval refetches in background tabs), revalidating with ETag. Every caller shares the
 * same query, so the shell's Inbox badge and Today's update check cost one request a minute.
 * A server without the endpoint answers 404 once and polling stops.
 */
export function useUiPoll(enabled = true) {
  return useQuery<UiPollState>({
    queryKey: queryKeys.ui.poll(),
    queryFn: async ({ signal }) => parseUiPoll(await pollFetcher()(signal)),
    enabled,
    refetchInterval: (query) => uiPollInterval(query.state.error),
    refetchIntervalInBackground: false,
    staleTime: UI_POLL_MS,
  });
}
