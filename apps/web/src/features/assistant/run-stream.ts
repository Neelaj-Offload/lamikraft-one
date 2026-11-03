/**
 * Run progress over Server-Sent Events (ADR-059, the ADR-050 spike made real). The stream carries the same
 * `RunDetail` payload as polling: `run` per change, `done` with the finished run, `timeout` when the server ends a
 * long stream. Any error or timeout hands over to polling from the last sequence seen; polling stays the fallback
 * and the whole transport can be switched off with `NEXT_PUBLIC_LK_ASSISTANT_SSE=0`.
 */

import { runEventsUrl } from "./api";
import { parseRun } from "./parse";
import type { AgentRun } from "./types";

export function sseEnabled(flag: string | undefined = process.env.NEXT_PUBLIC_LK_ASSISTANT_SSE): boolean {
  return flag !== "0" && typeof window !== "undefined" && typeof window.EventSource === "function";
}

export interface RunStreamHandlers {
  onUpdate: (run: AgentRun) => void;
  /** The stream cannot continue: poll from here. */
  onFallback: () => void;
}

type EventSourceFactory = (url: string) => EventSource;

/** Opens the stream; returns a closer. Unparseable events also fall back (the server's payload is checked). */
export function openRunStream(
  runId: string,
  afterSeq: number,
  handlers: RunStreamHandlers,
  create: EventSourceFactory = (url) => new EventSource(url, { withCredentials: true }),
): () => void {
  const source = create(runEventsUrl(runId, afterSeq));
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    source.close();
  };
  const fallback = () => {
    if (closed) return;
    close();
    handlers.onFallback();
  };
  const read = (event: MessageEvent<string>, last: boolean) => {
    try {
      handlers.onUpdate(parseRun(JSON.parse(event.data)));
    } catch {
      fallback();
      return;
    }
    if (last) close();
  };
  source.addEventListener("run", (event) => read(event as MessageEvent<string>, false));
  source.addEventListener("done", (event) => read(event as MessageEvent<string>, true));
  source.addEventListener("timeout", fallback);
  source.onerror = fallback;
  return close;
}
