import { describe, expect, it } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { testBootstrap } from "@/lib/test-support/session";
import { parseBootstrap, parseUiPoll } from "./parse";
import { currentPreferencesVersion, preferencesVersionFrom, saveUiPreferences, seedPreferencesVersion } from "./preferences";
import { rawBootstrap } from "@/lib/test-support/session";

function client(responses: (() => Response)[], seen: Request[]) {
  let index = 0;
  return createApiClient({
    baseUrl: "http://127.0.0.1:3050",
    getCsrfToken: () => "csrf",
    fetch: async (request) => {
      seen.push(request.clone());
      const next = responses[index] ?? responses.at(-1)!;
      index += 1;
      return next();
    },
  });
}

const conflict = (body: Record<string, unknown>) => () =>
  new Response(JSON.stringify({ type: "about:blank", title: "Conflict", status: 409, code: "version_conflict", ...body }), {
    status: 409,
    headers: { "content-type": "application/problem+json" },
  });

describe("preference writes carry expected_version", () => {
  it("sends the bootstrap's version and remembers the saved one", async () => {
    seedPreferencesVersion(4);
    const seen: Request[] = [];
    await saveUiPreferences({ theme: "dark" }, client([() => Response.json({ changed_fields: ["ui.theme"], preferences: { version: 5 } })], seen));
    expect(await seen[0]!.json()).toEqual({ expected_version: 4, ui: { theme: "dark" } });
    expect(currentPreferencesVersion()).toBe(5);
  });

  it("re-reads the version after a 409 version_conflict and retries the same patch once", async () => {
    seedPreferencesVersion(1);
    const seen: Request[] = [];
    await saveUiPreferences(
      { context_rail_open: true },
      client(
        [conflict({ current: { version: 7 } }), () => Response.json({ changed_fields: ["ui.context_rail_open"], preferences: { version: 8 } })],
        seen,
      ),
    );
    expect(seen).toHaveLength(2);
    expect(await seen[1]!.json()).toEqual({ expected_version: 7, ui: { context_rail_open: true } });
    expect(currentPreferencesVersion()).toBe(8);
  });

  it("falls back to GET /identity/me when the conflict carries no version", async () => {
    seedPreferencesVersion(1);
    const seen: Request[] = [];
    await saveUiPreferences(
      { sidebar_collapsed: true },
      client([conflict({}), () => Response.json({ preferences: { version: 3 } }), () => Response.json({ preferences: { version: 4 } })], seen),
    );
    expect(new URL(seen[1]!.url).pathname).toBe("/api/v1/identity/me");
    expect(await seen[2]!.json()).toEqual({ expected_version: 3, ui: { sidebar_collapsed: true } });
  });

  it("reads versions from every shape the server uses", () => {
    expect(preferencesVersionFrom({ preferences: { version: 2 } })).toBe(2);
    expect(preferencesVersionFrom({ current_version: 9 })).toBe(9);
    expect(preferencesVersionFrom({ current: { preferences: { version: 6 } } })).toBe(6);
    expect(preferencesVersionFrom(null)).toBeNull();
  });
});

describe("bootstrap sections from the real modules", () => {
  it("reads the flat tasks InboxCounts section; exceptions are not added to the badge twice", () => {
    const boot = parseBootstrap(rawBootstrap({ inbox_counts: undefined, sections: { inbox_counts: { tasks: 3, approvals: 1, conversations: 2, exceptions: 2 } } }));
    expect(boot.inbox_counts).toEqual({ status: "ok", value: { total: 6, tabs: { tasks: 3, approvals: 1, conversations: 2, exceptions: 2 } } });
    // No tasks permission: the section is empty and shows as unavailable.
    expect(parseUiPoll({ sections: { inbox_counts: {} } }).inbox_counts).toEqual({ status: "unavailable" });
  });

  it("turns the assistant on with agents.assistant.use and labels the Demo mode", () => {
    const boot = testBootstrap({
      permissions: [{ key: "agents.assistant.use", scope: "company" }],
      integration_modes: { ai: "demo", whatsapp: "demo", email: "demo" },
      integrations: undefined,
      preferences: { version: 3, ui: {} },
    });
    expect(boot.capabilities).toEqual({ assistant: true, voice: false });
    expect(boot.integration_modes?.ai).toBe("demo");
    expect(boot.integrations).toMatchObject({ status: "ok", value: expect.arrayContaining([{ key: "ai", label: "Assistant", mode: "demo" }]) });
    expect(boot.preferences_version).toBe(3);
    expect(testBootstrap().capabilities.assistant).toBe(false);
  });
});
