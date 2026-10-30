import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";

import { recordRecentRecord } from "./recent-records";

const ID = "01a18baa-80e8-7324-8318-09a76824077e";

function clientReturning(status: number, body: unknown) {
  const fetch = vi.fn(async (_request: Request) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": status < 400 ? "application/json" : "application/problem+json" } }),
  );
  return { fetch, client: createApiClient({ baseUrl: "http://app.test", fetch }) };
}

describe("recordRecentRecord", () => {
  it("posts the opened record to /ui/recent-records", async () => {
    const { fetch, client } = clientReturning(201, { resource_type: "sales.quote", resource_id: ID, opened_at: "2026-10-12T03:25:00Z" });
    const out = await recordRecentRecord("sales.quote", ID, client);
    expect(out?.resource_id).toBe(ID);
    const request = fetch.mock.calls[0]![0];
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toBe("/api/v1/ui/recent-records");
    expect(await request.json()).toEqual({ resource_type: "sales.quote", resource_id: ID });
  });

  it("never throws: a refused record is ignored", async () => {
    const { client } = clientReturning(404, { type: "about:blank", title: "Not found", status: 404, code: "not_found" });
    await expect(recordRecentRecord("sales.enquiry", ID, client)).resolves.toBeNull();
  });
});
