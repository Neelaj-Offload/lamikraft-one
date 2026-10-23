/**
 * Polling policy (docs/architecture/api-conventions.md §12):
 * - agent runs: every 500 ms while the run is active (Slice 1; SSE may replace it later);
 * - briefing and Inbox state: `GET /api/v1/ui/poll` every 60 s while the tab is visible,
 *   revalidated with ETag / If-None-Match so an unchanged state costs a 304.
 */

import { ProblemError } from "./errors";
import type { ApiClient } from "./client";

export const AGENT_RUN_POLL_MS = 500;
export const UI_POLL_MS = 60_000;

/** Run states that are still producing steps. Anything else is terminal. */
const ACTIVE_RUN_STATES: ReadonlySet<string> = new Set(["queued", "running", "in_progress", "awaiting_tool"]);

export function isAgentRunActive(status: string | null | undefined): boolean {
  return typeof status === "string" && ACTIVE_RUN_STATES.has(status);
}

/** TanStack Query `refetchInterval` for an agent run: 500 ms while active, then stop. */
export function agentRunPollInterval(status: string | null | undefined): number | false {
  return isAgentRunActive(status) ? AGENT_RUN_POLL_MS : false;
}

type RawResult = { data?: unknown; error?: unknown; response: Response };
type RawRequest = (method: string, url: string, init?: Record<string, unknown>) => Promise<RawResult>;

export interface EtagFetcher<T> {
  (signal?: AbortSignal): Promise<T>;
  /** The validator sent with the next request (exposed for tests and diagnostics). */
  readonly etag: () => string | null;
  /** Forgets the cached body so the next call is unconditional. */
  readonly reset: () => void;
}

/**
 * A GET that revalidates with the last ETag. On 304 it resolves to the previously
 * received body, so a poller sees an identical value and React re-renders nothing.
 */
export function createEtagFetcher<T>(client: ApiClient, path: `/api/v1/${string}`): EtagFetcher<T> {
  let etag: string | null = null;
  let last: { value: T } | null = null;
  const call = (client.request as unknown as RawRequest).bind(client);

  const fetcher = async (signal?: AbortSignal): Promise<T> => {
    const headers: Record<string, string> = {};
    if (etag && last) headers["If-None-Match"] = etag;
    const result = await call("get", path, { headers, ...(signal ? { signal } : {}) });
    if (result.response.status === 304 && last) return last.value;
    if (!result.response.ok) throw ProblemError.fromResponse(result.response, result.error);
    etag = result.response.headers.get("etag");
    last = { value: result.data as T };
    return last.value;
  };

  return Object.assign(fetcher, {
    etag: () => etag,
    reset: () => {
      etag = null;
      last = null;
    },
  });
}
