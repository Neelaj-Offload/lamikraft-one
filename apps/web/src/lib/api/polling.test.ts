import { describe, expect, it } from "vitest";
import { createApiClient } from "./client";
import { ProblemError } from "./errors";
import { AGENT_RUN_POLL_MS, UI_POLL_MS, agentRunPollInterval, createEtagFetcher, isAgentRunActive } from "./polling";

describe("agent run polling", () => {
  it("polls every 500 ms while the run is active and stops when it ends", () => {
    expect(AGENT_RUN_POLL_MS).toBe(500);
    for (const status of ["queued", "running", "in_progress", "awaiting_tool"]) {
      expect(agentRunPollInterval(status), status).toBe(500);
    }
    for (const status of ["completed", "failed", "cancelled", undefined, null, ""]) {
      expect(agentRunPollInterval(status), String(status)).toBe(false);
      expect(isAgentRunActive(status)).toBe(false);
    }
  });
});

describe("ETag fetcher", () => {
  it("revalidates with If-None-Match and reuses the body on 304", async () => {
    expect(UI_POLL_MS).toBe(60_000);
    const seen: Array<string | null> = [];
    let version = 1;
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3100",
      fetch: async (request) => {
        const sent = request.headers.get("if-none-match");
        seen.push(sent);
        const etag = `"v${version}"`;
        if (sent === etag) return new Response(null, { status: 304, headers: { ETag: etag } });
        return Response.json({ briefing: { version } }, { headers: { ETag: etag } });
      },
    });
    const fetcher = createEtagFetcher<{ briefing: { version: number } }>(client, "/api/v1/ui/poll");

    const first = await fetcher();
    const second = await fetcher();
    expect(second).toBe(first);
    version = 2;
    const third = await fetcher();

    expect(third).toEqual({ briefing: { version: 2 } });
    expect(seen).toEqual([null, '"v1"', '"v1"']);
    expect(fetcher.etag()).toBe('"v2"');
    fetcher.reset();
    expect(fetcher.etag()).toBeNull();
  });

  it("throws problems instead of returning stale data", async () => {
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3100",
      fetch: async () =>
        new Response(JSON.stringify({ title: "Unavailable", status: 503, code: "service_unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/problem+json" },
        }),
    });
    await expect(createEtagFetcher(client, "/api/v1/ui/poll")()).rejects.toBeInstanceOf(ProblemError);
  });
});
