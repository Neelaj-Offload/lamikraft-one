import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testQuoteWire } from "@/lib/test-support/sales";
import { testBootstrap } from "@/lib/test-support/session";
import { changeQuoteCurrency, quoteLinesCsvHref, quotesExportHref, transitionQuote } from "./api";
import { parseQuoteDetail, parseRevisions } from "./parse";
import { QuoteSettingsPage, type QuoteSettings } from "./quote-settings";
import { QuoteWorkspace } from "./quote-workspace";
import { commandButtons, isEditable } from "./workspace-model";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/quotes/0192a000-0000-7000-8000-000000000009",
  useSearchParams: () => new URLSearchParams(),
}));

const QUOTE = "0192a000-0000-7000-8000-000000000009";
const bootstrap = testBootstrap({
  permissions: [
    { key: "sales.quote.read", scope: "own" },
    { key: "sales.quote.create", scope: "own" },
    { key: "sales.quote.update", scope: "own" },
    { key: "sales.quote.export", scope: "own" },
  ],
});

function client(respond: (request: Request) => Response, seen: Request[]) {
  return createApiClient({
    baseUrl: "http://127.0.0.1:3060",
    getCsrfToken: () => "csrf",
    fetch: async (request) => {
      seen.push(request.clone());
      return respond(request);
    },
  });
}

describe("Slice 2 quote lifecycle in the workspace", () => {
  it("labels the new actions and treats a revised working copy as editable", () => {
    const sent = parseQuoteDetail(
      testQuoteWire({
        status: "sent",
        capabilities: { update: { allowed: false, reason_code: "quote_sent_not_editable" } },
        transitions: [
          { action: "revise", to_status: "revised", requires_reason: false },
          { action: "extend_validity", to_status: "sent", requires_reason: false },
          { action: "mark_won", to_status: "won", requires_reason: false },
          { action: "mark_lost", to_status: "lost", requires_reason: true },
          { action: "cancel", to_status: "cancelled", requires_reason: true },
        ],
      }),
    );
    expect(commandButtons(sent).map((b) => [b.label, b.variant])).toEqual([
      ["Revise", "secondary"],
      ["Extend validity", "secondary"],
      ["Mark as won", "primary"],
      ["Mark as lost", "danger"],
      ["Cancel quote", "danger"],
    ]);
    expect(isEditable(sent)).toBe(false);
    const revised = parseQuoteDetail(testQuoteWire({ status: "revised", transitions: [{ action: "discard_revision", to_status: "sent", requires_reason: false }] }));
    expect(isEditable(revised)).toBe(true);
    expect(commandButtons(revised)[0]).toMatchObject({ label: "Discard revision", variant: "danger" });
    const won = parseQuoteDetail(testQuoteWire({ status: "won", transitions: [{ action: "archive", to_status: "archived", requires_reason: false }, { action: "correct_status", to_status: "sent", requires_reason: true }] }));
    expect(commandButtons(won).map((b) => [b.label, b.requiresReason])).toEqual([["Archive", false], ["Correct status", true]]);
  });

  it("shows duplicate, currency change and the lines CSV only when the server allows them", () => {
    const wire = testQuoteWire({
      capabilities: {
        update: { allowed: true },
        duplicate: { allowed: true },
        change_currency: { allowed: true },
        export_lines: { allowed: true },
        restore: { allowed: false, reason_code: "quote_not_issued" },
      },
    });
    const html = renderWithQueries(
      <QuoteWorkspace quoteId={QUOTE} />,
      (c) => {
        c.setQueryData(queryKeys.sales.quote(QUOTE), parseQuoteDetail(wire));
        c.setQueryData(queryKeys.sales.quoteHistory(QUOTE), []);
        c.setQueryData(queryKeys.sales.quoteRevisions(QUOTE), parseRevisions([], QUOTE));
      },
      bootstrap,
    );
    const text = textOf(html);
    expect(text).toContain("Duplicate");
    expect(text).toContain("Change currency");
    expect(html).toContain(`href="/api/v1/sales/quotes/${QUOTE}/lines.csv"`);
    const locked = textOf(
      renderWithQueries(
        <QuoteWorkspace quoteId={QUOTE} />,
        (c) => {
          c.setQueryData(queryKeys.sales.quote(QUOTE), parseQuoteDetail(testQuoteWire({ capabilities: { update: { allowed: true } } })));
          c.setQueryData(queryKeys.sales.quoteHistory(QUOTE), []);
          c.setQueryData(queryKeys.sales.quoteRevisions(QUOTE), parseRevisions([], QUOTE));
        },
        bootstrap,
      ),
    );
    expect(locked).not.toContain("Change currency");
    expect(locked).not.toContain("Lines as CSV");
  });

  it("sends extend_validity with the new date, and a currency change with the version", async () => {
    const seen: Request[] = [];
    const api = client(() => Response.json(testQuoteWire({ status: "sent", version: 5 })), seen);
    const quote = parseQuoteDetail(testQuoteWire({ version: 4 }));
    await transitionQuote(quote, { action: "extend_validity", valid_until: "2026-12-01", reason: " asked " }, "k1", api);
    expect(await seen[0]!.json()).toEqual({ action: "extend_validity", expected_version: 4, reason: "asked", valid_until: "2026-12-01" });
    await changeQuoteCurrency(quote, "USD", "k2", api);
    expect(await seen[1]!.json()).toEqual({ to_currency: "USD", expected_version: 4 });
    expect(seen[1]!.headers.get("Idempotency-Key")).toBe("k2");
    expect(quotesExportHref({ q: "oak", status: "won", scope: "all" })).toBe("/api/v1/sales/quotes/export.csv?q=oak&status=won&scope=all");
    expect(quoteLinesCsvHref(QUOTE)).toBe(`/api/v1/sales/quotes/${QUOTE}/lines.csv`);
  });
});

describe("quote settings", () => {
  const settings = (manage: boolean): QuoteSettings => ({
    defaults: { currency: "EUR", incoterm: "FOB", validity_days: 30, brand: "LK", price_type: "export", duplicate_copies_assignee: true },
    version: 0,
    brands: ["LK", "CR"],
    next_quote_numbers: { LK: "LK-QT-2026-0010", CR: "CR-QT-2026-0010" },
    next_custom_product_code: "CP-0001",
    next_sample_number: "SMP-2026-0001",
    quote_sequence_reset_policy: "never",
    capabilities: { manage: { allowed: manage, reason_code: manage ? null : "permission_denied" } },
  });

  it("shows numbering previews and is read-only without the manage key", () => {
    const text = textOf(renderWithQueries(<QuoteSettingsPage />, (c) => c.setQueryData(queryKeys.sales.quoteSettings(), settings(false)), bootstrap));
    expect(text).toContain("LK-QT-2026-0010");
    expect(text).toContain("CP-0001");
    expect(text).toContain("Quote numbers never reset");
    expect(text).toContain("Only people who manage quote settings can change these.");
    expect(text).not.toMatch(/\bSave\b/);
    const manager = textOf(renderWithQueries(<QuoteSettingsPage />, (c) => c.setQueryData(queryKeys.sales.quoteSettings(), settings(true)), bootstrap));
    expect(manager).toContain("Save");
    expect(textOf(renderWithQueries(<QuoteSettingsPage />, () => undefined, testBootstrap({ permissions: [] })))).toContain("You don't have access to Quote settings");
  });
});
