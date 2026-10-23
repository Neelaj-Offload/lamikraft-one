"use client";

import { QueryClient, QueryClientProvider, isServer } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { isNetworkError } from "@/lib/api/errors";

/** Lists tolerate 30 s of staleness; detail screens may pass a shorter staleTime. */
export const DEFAULT_STALE_TIME_MS = 30_000;
export const MAX_QUERY_RETRIES = 2;

/**
 * Queries retry only when no HTTP response arrived (offline, connection reset).
 * Every HTTP error, 4xx or 5xx, is a real answer from the server and is shown
 * to the user with its request id instead of being retried silently.
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  return isNetworkError(error) && failureCount < MAX_QUERY_RETRIES;
}

export function retryDelay(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 8000);
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME_MS,
        retry: shouldRetryQuery,
        retryDelay,
        refetchOnWindowFocus: true,
      },
      mutations: {
        // Commands are retried explicitly by the caller with the same Idempotency-Key.
        retry: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

/** One client per browser tab; a fresh one per server request so users never share a cache. */
export function getQueryClient(): QueryClient {
  if (isServer) return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(getQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
