/**
 * Test-only bootstrap payloads modelled on the canonical fixture world
 * (docs/architecture/fixtures.md: Meera Iyer, sales, own scope, at D0 08:55 IST).
 * Never imported by product code.
 */

import { parseBootstrap } from "@/lib/session/parse";
import type { SessionBootstrap } from "@/lib/session/types";

export function rawBootstrap(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user: { id: "0192a000-0000-7000-8000-00000000000a", display_name: "Meera Iyer", email: "meera.iyer@demo.lamikraft.test" },
    membership: { id: "0192a000-0000-7000-8000-0000000000b1", role_names: ["Sales"], is_demo: true },
    company: {
      id: "0192a000-0000-7000-8000-0000000000c1",
      display_name: "Crown Decor (Demo)",
      legal_name: "Crown Decor Pvt. Ltd. (Demo)",
      is_demo: true,
    },
    branches: [{ id: "0192a000-0000-7000-8000-0000000000d1", code: "HO", name: "Head office" }],
    time_zone: "Asia/Kolkata",
    locale: "en-IN",
    server_now: "2026-10-12T03:25:00Z",
    greeting_period: "morning",
    permissions: [
      { key: "sales.quote.read", scope: "own" },
      { key: "catalogue.product.read", scope: "company" },
      { key: "tasks.task.read", scope: "own" },
      { key: "briefings.briefing.read", scope: "own" },
    ],
    ui_preferences: {
      theme: "system",
      motion: "full",
      sidebar_collapsed: false,
      context_rail_open: false,
      density: "comfortable",
      shortcuts_enabled: true,
    },
    nav: [{ key: "today" }, { key: "inbox" }, { key: "sales" }, { key: "products" }, { key: "settings" }],
    features: { assistant: false, voice: false },
    inbox_counts: { total: 4, tabs: { tasks: 3, approvals: 1 } },
    briefing: { version: 1, work_date: "2026-10-12" },
    integrations: { items: [{ key: "whatsapp", label: "WhatsApp", mode: "demo" }] },
    csrf_token: "csrf-test-value",
    ...overrides,
  };
}

export function testBootstrap(overrides: Record<string, unknown> = {}): SessionBootstrap {
  return parseBootstrap(rawBootstrap(overrides));
}
