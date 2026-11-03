import { describe, expect, it } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { getRoute } from "@/lib/routes";
import { controlsWithoutVisibleFocus, nestedInteractive, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { ReceiptCardView, canOfferUndo } from "@/features/assistant/cards";
import { receiptUndo } from "@/features/assistant/parse";
import { AiSettingsView, costText, latencyText } from "./ai-settings-view";
import { errorRateTenths, parseAiStatus, parseAiUsage, parseCorrelationId, parseTrace, parseUsageDays } from "./parse";
import { TraceView, detailText } from "./trace-view";

const CID = "0192a000-0000-7000-8000-00000000c0de";
const STATUS = {
  provider: { mode: "demo", provider: "demo", label: "Demo", state: "demo", verified_at: null, last_checked_at: null, last_error_code: null,
              circuit: { state: "closed", recent_failures: 0 }, readiness: "ok" },
  models: { phrasing: "claude-haiku-5-5", orchestrator: "claude-sonnet-5-5", escalation: "claude-opus-5-5", vision: "gemini-3.8-flash" },
  effort: { orchestration: "medium", escalation: "medium", routing: "low", phrasing: "low" },
  budgets: { orchestration: { steps: 8, seconds: 45, input_tokens: 120000, max_tokens: 8192 } },
  quotas: { orchestrator_runs_per_user: 150, escalations_per_user: 10, vision_calls_per_user: 60, company_escalations: 100 },
  price_currency: "USD",
  prices: [{ model: "claude-sonnet-5-5", input: "2.00", output: "10.00", cache_read: "0.20", cache_write: "2.50" }],
  dpdp: {}, dpdp_text: "Not recorded. Demo mode sends nothing to Anthropic or Google.", can_manage_routing: false,
};
const usageRow = (workflow: string, extra: Record<string, unknown> = {}) => ({
  workflow, calls: 40, runs: 12, errors: 2, refusals: 1, error_rate: "0.0750", p50_latency_ms: 820, p95_latency_ms: 2400,
  input_tokens: 51000, output_tokens: 3200, cache_read_tokens: 42000, cache_write_tokens: 900, estimated_cost: "0.143200", ...extra,
});
const USAGE = {
  window_days: 7, price_currency: "USD", cost_is_estimate: true, totals: usageRow("all"),
  by_workflow: [usageRow("orchestrate"), usageRow("route", { estimated_cost: null })],
  by_model: [{ provider: "anthropic", model: "claude-sonnet-5-5", calls: 40, input_tokens: 1, output_tokens: 2, cache_read_tokens: 3, cache_write_tokens: 4, estimated_cost: "0.1432", priced: true }],
  failures: [{ at: "2026-10-12T03:31:04Z", workflow: "orchestrate", provider: "anthropic", model: "claude-sonnet-5-5", outcome: "error",
               error_type: "server_error", request_id: "req_011CX", run_id: null, correlation_id: CID }],
};
const reader = (extra: string[] = []) => testBootstrap({ permissions: ["agents.assistant.use", "agents.ai_usage.read", ...extra] });

describe("AI admin parsers", () => {
  it("reads status and usage, keeping decimals as strings and dropping unknown states", () => {
    const status = parseAiStatus(STATUS);
    expect(status.provider.state).toBe("demo");
    expect(status.prices[0]?.input).toBe("2.00");
    expect(() => parseAiStatus({ ...STATUS, provider: { ...STATUS.provider, state: "great" } })).toThrow();
    const usage = parseAiUsage(USAGE);
    expect(usage.by_workflow.map((row) => row.estimated_cost)).toEqual(["0.143200", null]);
    expect(usage.failures[0]?.correlation_id).toBe(CID);
  });

  it("reads traces and route parameters defensively", () => {
    expect(parseCorrelationId(CID)).toBe(CID);
    expect(parseCorrelationId("../../etc")).toBeNull();
    expect(parseUsageDays("30")).toBe(30);
    expect(parseUsageDays("365")).toBe(7);
    const trace = parseTrace({ correlation_id: CID, access: "participant", run_ids: ["r1"], entries: [{ at: "2026-10-12T03:31:04Z", kind: "step", name: "draft_quote", status: "ok", detail: { seq: 3 } }, { kind: "x" }] });
    expect(trace.entries).toHaveLength(1);
    expect(detailText({ seq: 3, model_route: "claude-sonnet-5-5", nested: { a: 1 }, empty: null })).toBe("seq: 3 · model_route: claude-sonnet-5-5");
  });

  it("formats rates, latency and estimated cost without inventing figures", () => {
    expect(errorRateTenths(3, 40)).toBe(75);
    expect(errorRateTenths(0, 0)).toBeNull();
    expect(latencyText(null, "en-IN")).toBe("—");
    expect(latencyText(2400, "en-IN")).toBe("2,400 ms");
    expect(costText(null, "USD", "en-IN")).toBe("No price");
    expect(costText("0.143200", "USD", "en-IN")).toBe("≈ USD 0.1432");
    expect(costText("0", "USD", "en-IN", "demo")).toBe("Demo (no cost)");
  });
});

describe("Settings → AI", () => {
  it("is a settings context route of the agents module (the view itself checks agents.ai_usage.read)", () => {
    expect(getRoute("settings-ai")).toMatchObject({ path: "/settings/ai", area: "settings", navGroup: "context", requiredPermission: "agents." });
    expect(getRoute("settings-ai-trace").requiredPermission).toBe("agents.");
  });

  it("shows provider, DPDP text, usage facts, workflows and failures with a trace link", () => {
    const html = renderWithQueries(<AiSettingsView days={7} />, (client) => {
      client.setQueryData(queryKeys.agents.aiStatus(), parseAiStatus(STATUS));
      client.setQueryData(queryKeys.agents.aiUsage(7), parseAiUsage(USAGE));
    }, reader());
    const text = textOf(html);
    expect(text).toContain("Demo mode runs the deterministic Demo assistant");
    expect(text).toContain("Not recorded. Demo mode sends nothing");
    expect(text).toContain("Assistant runs");
    expect(text).toContain("≈ USD 0.1432");
    expect(text).toContain("No price");
    expect(text).toContain("req_011CX");
    expect(html).toContain(`/settings/ai/traces/${CID}`);
    expect(text).not.toContain("Verify connection");
    expect(text).not.toContain("Edit routing");
    expect(nestedInteractive(html)).toEqual([]);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("offers verification only with system.integration.manage, and shows permission denied without the read right", () => {
    const html = renderWithQueries(<AiSettingsView days={7} />, (client) => {
      client.setQueryData(queryKeys.agents.aiStatus(), parseAiStatus(STATUS));
      client.setQueryData(queryKeys.agents.aiUsage(7), parseAiUsage({ ...USAGE, totals: usageRow("all", { calls: 0 }) }));
    }, reader(["system.integration.manage"]));
    expect(textOf(html)).toContain("Verify connection");
    expect(textOf(html)).toContain("No AI calls in this period.");
    const denied = renderWithQueries(<AiSettingsView days={7} />, () => undefined, testBootstrap({ permissions: ["agents.assistant.use"] }));
    expect(textOf(denied)).not.toContain("Provider");
  });

  it("renders a trace timeline, and Not available for a 404 or a bad id", () => {
    const html = renderWithQueries(<TraceView correlationId={CID} />, (client) => {
      client.setQueryData(queryKeys.agents.trace(CID), parseTrace({ correlation_id: CID, access: "auditor", run_ids: ["0192a000-0000-7000-8000-000000000001"],
        entries: [{ at: "2026-10-12T03:31:04Z", kind: "ai_call", name: "anthropic:orchestrate", status: "ok", ref_id: "x", detail: { model: "claude-sonnet-5-5" } }] }));
    }, reader());
    expect(textOf(html)).toContain("anthropic:orchestrate");
    expect(textOf(html)).toContain("Viewed as an auditor");
    const missing = renderWithQueries(<TraceView correlationId={null} />, () => undefined, reader());
    expect(textOf(missing)).not.toContain("anthropic:orchestrate");
    const gone = renderWithQueries(<TraceView correlationId={CID} />, (client) => seedQueryError(client, queryKeys.agents.trace(CID), new Error("boom")), reader());
    expect(textOf(gone)).not.toContain("anthropic:orchestrate");
  });
});

describe("ReceiptCard Undo (design §9)", () => {
  const card = {
    kind: "receipt" as const, demo: true, title: "Draft LK-QT-2026-0009 created by the assistant.", detail: null, link: null,
    undo: receiptUndo({ receipt_id: "0192a000-0000-7000-8000-0000000000aa", allowed: true, until: "2026-10-13T03:31:04Z", kind: "revert_draft" }),
  };

  it("offers Undo while allowed and inside the window", () => {
    expect(canOfferUndo(card, new Date("2026-10-12T05:00:00Z"))).toBe(true);
    expect(canOfferUndo(card, new Date("2026-10-14T05:00:00Z"))).toBe(false);
    expect(canOfferUndo({ undo: { ...card.undo!, allowed: false } }, new Date("2026-10-12T05:00:00Z"))).toBe(false);
    expect(receiptUndo({ receipt_id: "not-an-id", allowed: true })).toBeNull();
  });

  it("renders the Undo button only when it can be offered", () => {
    const now = Date.now();
    const open = { ...card, undo: { ...card.undo!, until: new Date(now + 3_600_000).toISOString() } };
    expect(textOf(renderWithQueries(<ReceiptCardView card={open} />, () => undefined, reader()))).toContain("Undo");
    const closed = { ...card, undo: { ...card.undo!, until: new Date(now - 1000).toISOString() } };
    expect(textOf(renderWithQueries(<ReceiptCardView card={closed} />, () => undefined, reader()))).not.toContain("Undo");
  });
});
