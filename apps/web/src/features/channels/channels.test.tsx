import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, nestedInteractive, renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { groupCode, type Account, type DemoThread, type Identity } from "./api";
import { reviewLinkProblem } from "./review-link-view";
import { AccountStatus, WhatsAppView } from "./whatsapp-view";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/settings/whatsapp",
  useSearchParams: () => new URLSearchParams(),
}));

const capability = (allowed: boolean) => ({ allowed, reason_code: allowed ? null : "permission_denied" });

const demoAccount: Account = {
  id: "0192f7a0-0000-7000-8000-000000000001",
  purpose: "employee_assistant",
  provider: "demo",
  mode: "demo",
  status: "configured_unverified",
  label_text: "Demo — not connected",
  phone_number_id: null,
  waba_id: null,
  display_phone: "+910000000000",
  api_version: "v26.0",
  checks: { graph_ok_at: null, handshake_ok_at: null, signed_event_ok_at: null },
  missing_settings: [],
  live_outbound: false,
  last_error: null,
  verified_at: null,
  capabilities: { verify: capability(false), sync_templates: capability(false) },
};

const identity: Identity = {
  id: "0192f7a0-0000-7000-8000-000000000002",
  kind: "employee",
  status: "active",
  wa_id_masked: "••••••••4821",
  phone_masked: "••••••••4821",
  username: null,
  user_id: "0192f7a0-0000-7000-8000-000000000003",
  user_name: "Meera Iyer",
  party_id: null,
  last_inbound_at: "2026-10-12T03:25:00Z",
  session_expires_at: "2026-10-19T03:25:00Z",
  created_at: "2026-10-12T03:25:00Z",
  consents: { assistant_replies: "opted_in" },
  capabilities: { revoke: capability(true), update_consent: capability(true) },
};

const thread: DemoThread = {
  identity,
  mode: "demo",
  label_text: "Demo — not connected",
  wa_id_masked: "••••••••4821",
  messages: [
    {
      id: "m1", identity_id: identity.id, direction: "inbound", type: "text", body: "Prepare Nordhaus's usual oak tray quote", status: "delivered",
      status_provider_ts: null, simulated: true, provider_message_id: null, outbox_id: null, outbox_state: null, blocked_reason: null, last_error: null,
      created_at: "2026-10-12T03:26:00Z", correlation_id: null, buttons: [], capabilities: {},
    },
    {
      id: "m2", identity_id: identity.id, direction: "outbound", type: "interactive", body: "Demo: Draft ready (LK-QT-2026-0009). Total EUR 5,760.00.",
      status: "read", status_provider_ts: null, simulated: true, provider_message_id: null, outbox_id: "o2", outbox_state: "accepted", blocked_reason: null,
      last_error: null, created_at: "2026-10-12T03:26:05Z", correlation_id: null,
      buttons: [{ id: "a:n1", title: "Review quote" }, { id: "a:n2", title: "Open workspace" }], capabilities: {},
    },
  ],
};

const sales = () => testBootstrap({ permissions: [{ key: "agents.assistant.use", scope: "company" }] });

describe("whatsapp settings", () => {
  it("groups the eight-digit code for reading", () => {
    expect(groupCode("12345678")).toBe("1234 5678");
    expect(groupCode("123")).toBe("123");
  });

  it("states Demo — not connected honestly and lists missing live settings", () => {
    expect(textOf(renderWithQueries(<AccountStatus account={demoAccount} />, () => undefined))).toContain("WhatsApp: Demo — not connected");
    const live: Account = { ...demoAccount, mode: "live", status: "not_configured", label_text: "Not configured", missing_settings: ["LK_WHATSAPP_ACCESS_TOKEN"] };
    const text = textOf(renderWithQueries(<AccountStatus account={live} />, () => undefined));
    expect(text).toContain("Not configured");
    expect(text).toContain("LK_WHATSAPP_ACCESS_TOKEN");
  });

  it("shows link, linked numbers with consent switches and the simulator to an assistant user, and no admin sections", () => {
    const html = renderWithQueries(
      <WhatsAppView />,
      (client) => {
        client.setQueryData(queryKeys.channels.account(), demoAccount);
        client.setQueryData(queryKeys.channels.identities("mine"), [identity]);
        client.setQueryData(queryKeys.channels.demoThread(), thread);
      },
      sales(),
    );
    const text = textOf(html);
    expect(text).toContain("Link my WhatsApp");
    expect(text).toContain("Create link code");
    expect(text).toContain("••••••••4821");
    expect(text).toContain("Daily briefing");
    expect(text).toContain("Unlink");
    expect(text).toContain("Simulator");
    expect(text).toContain("Draft ready (LK-QT-2026-0009)");
    expect(text).toContain("Review quote");
    expect(text).not.toContain("Account and checks");
    expect(text).not.toContain("Messages needing attention");
    expect(nestedInteractive(html)).toEqual([]);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("adds the admin sections with channels.account.manage and channels.outbox.manage", () => {
    const admin = testBootstrap({
      permissions: [
        { key: "agents.assistant.use", scope: "company" },
        { key: "channels.account.manage", scope: "company" },
        { key: "channels.outbox.manage", scope: "company" },
      ],
    });
    const html = renderWithQueries(
      <WhatsAppView />,
      (client) => {
        client.setQueryData(queryKeys.channels.account(), { ...demoAccount, capabilities: { verify: capability(true), sync_templates: capability(true) } });
        client.setQueryData(queryKeys.channels.identities("mine"), []);
        client.setQueryData(queryKeys.channels.demoThread(), { ...thread, identity: null, messages: [] });
        client.setQueryData(queryKeys.channels.messages(), []);
        client.setQueryData(queryKeys.channels.templates(), [
          { id: "t1", name: "lk_quote_ready", language: "en", category: "UTILITY", status: "approved", synced_at: "2026-10-12T03:00:00Z" },
        ]);
      },
      admin,
    );
    const text = textOf(html);
    expect(text).toContain("Account and checks");
    expect(text).toContain("Webhook handshake");
    expect(text).toContain("Run checks");
    expect(text).toContain("Nothing needs attention.");
    expect(text).toContain("lk_quote_ready");
    expect(text).toContain("Sync templates");
  });

  it("explains each review-link refusal", () => {
    const problem = (code: string, status: number) => new ProblemError({ type: "about:blank", title: "x", status, code } as never);
    expect(reviewLinkProblem(problem("review_link_wrong_user", 403))).toMatch(/another person/);
    expect(reviewLinkProblem(problem("review_link_expired", 410))).toMatch(/expired/);
    expect(reviewLinkProblem(problem("review_link_used", 410))).toMatch(/already used/);
    expect(reviewLinkProblem(new Error("x"))).toBe("This link is not valid.");
  });
});
