import { describe, expect, it } from "vitest";
import { runEventsUrl } from "./api";
import { openRunStream, sseEnabled } from "./run-stream";
import type { AgentRun } from "./types";

const RUN = "0192a000-0000-7000-8000-000000000001";

class FakeSource {
  listeners = new Map<string, (event: unknown) => void>();
  onerror: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  addEventListener(name: string, listener: (event: unknown) => void) {
    this.listeners.set(name, listener);
  }
  emit(name: string, data: unknown) {
    this.listeners.get(name)?.({ data: JSON.stringify(data) });
  }
  close() {
    this.closed = true;
  }
}

const detail = (status: string, done: boolean) => ({
  run: { id: RUN, status, provider: "demo", tainted: false, error_code: null },
  steps: [{ seq: 1, kind: "route", name: "router", output: { request_type: "data_or_action" } }],
  after_seq: 0, last_seq: 1, done, text: done ? "Demo: done." : null, cards: [],
});

describe("run progress over SSE (ADR-059)", () => {
  it("streams updates, closes on done and never falls back on success", () => {
    let source: FakeSource | null = null;
    const updates: AgentRun[] = [];
    let fellBack = false;
    openRunStream(RUN, 0, { onUpdate: (run) => updates.push(run), onFallback: () => (fellBack = true) }, (url) => {
      source = new FakeSource(url);
      return source as unknown as EventSource;
    });
    expect(source!.url).toBe(runEventsUrl(RUN, 0));
    source!.emit("run", detail("running", false));
    source!.emit("done", detail("succeeded", true));
    expect(updates.map((run) => run.status)).toEqual(["running", "succeeded"]);
    expect(source!.closed).toBe(true);
    expect(fellBack).toBe(false);
  });

  it("falls back to polling on an error, a timeout or an unreadable event", () => {
    for (const trigger of ["error", "timeout", "garbage"] as const) {
      let source: FakeSource | null = null;
      let fellBack = 0;
      openRunStream(RUN, 3, { onUpdate: () => undefined, onFallback: () => (fellBack += 1) }, (url) => {
        source = new FakeSource(url);
        return source as unknown as EventSource;
      });
      if (trigger === "error") source!.onerror?.();
      else if (trigger === "timeout") source!.listeners.get("timeout")?.({ data: "{}" });
      else source!.listeners.get("run")?.({ data: "not json" });
      source!.onerror?.();
      expect(fellBack).toBe(1);
      expect(source!.closed).toBe(true);
    }
  });

  it("is off with NEXT_PUBLIC_LK_ASSISTANT_SSE=0", () => {
    expect(sseEnabled("0")).toBe(false);
  });
});
