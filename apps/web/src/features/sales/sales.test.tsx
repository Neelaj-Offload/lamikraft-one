import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatMoney } from "@/lib/format/money";
import { controlsWithoutVisibleFocus, renderWithQueries, textOf } from "@/lib/test-support/render";
import { testQuoteWire } from "@/lib/test-support/sales";
import { testBootstrap } from "@/lib/test-support/session";
import { previewQuote, transitionQuote, updateQuoteHeader } from "./api";
import { canMarkReplied, messageListStateFrom } from "./customer-messages";
import { enquiryListStateFrom } from "./enquiries";
import { parseCustomerMessage, parsePreview, parseQuoteDetail, parseRevisions } from "./parse";
import { QuoteList, quoteListHref, quoteListStateFrom } from "./quote-list";
import { QuoteWorkspace } from "./quote-workspace";
import {
  commandButtons,
  dirtyHeaderFields,
  headerChanges,
  headerFormOf,
  lineEditOf,
  lineUpdatePlan,
  mergeHeaderConflict,
  previewRequest,
  priceDiffersFromList,
} from "./workspace-model";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/quotes/0192a000-0000-7000-8000-000000000009",
  useSearchParams: () => new URLSearchParams(),
}));

const QUOTE = "0192a000-0000-7000-8000-000000000009";
const salesBootstrap = () =>
  testBootstrap({
    permissions: [
      { key: "sales.quote.read", scope: "own" },
      { key: "sales.quote.create", scope: "own" },
      { key: "sales.quote.update", scope: "own" },
    ],
  });

function fakeClient(respond: (request: Request) => Response | Promise<Response>, seen: Request[] = []) {
  return createApiClient({
    baseUrl: "http://127.0.0.1:3050",
    getCsrfToken: () => "csrf",
    fetch: async (request) => {
      seen.push(request.clone());
      return respond(request);
    },
  });
}

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new Response(JSON.stringify({ type: "about:blank", title: "Conflict", status, code, detail: "Changed by someone else", request_id: "req-9", ...extra }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });

describe("quote commands come only from allowed_transitions", () => {
  it("renders each allowed action once, with one primary and destructive actions as danger", () => {
    const quote = parseQuoteDetail(testQuoteWire());
    const buttons = commandButtons(quote);
    expect(buttons.map((button) => [button.action, button.variant, button.requiresReason])).toEqual([
      ["submit_review", "primary", false],
      ["mark_sent", "secondary", false],
      ["cancel", "danger", true],
      ["delete", "danger", false],
    ]);
    expect(buttons.map((button) => button.label)).toEqual(["Request review", "Mark as sent", "Cancel quote", "Delete draft"]);
  });

  it("offers nothing the server did not allow, and Delete only on a draft the server lets this user delete", () => {
    const sent = parseQuoteDetail(
      testQuoteWire({
        status: "sent",
        transitions: [
          { action: "mark_won", to_status: "won", requires_reason: false },
          { action: "mark_lost", to_status: "lost", requires_reason: true },
        ],
      }),
    );
    expect(commandButtons(sent).map((button) => button.action)).toEqual(["mark_won", "mark_lost"]);
    const locked = parseQuoteDetail(testQuoteWire({ transitions: [], capabilities: { delete: { allowed: false, reason_code: "issued" } } }));
    expect(commandButtons(locked)).toEqual([]);
    const unknown = parseQuoteDetail(testQuoteWire({ transitions: [{ action: "extend_validity", to_status: "sent", requires_reason: false }], capabilities: {} }));
    expect(commandButtons(unknown)).toEqual([{ action: "extend_validity", label: "Extend validity", requiresReason: false, variant: "secondary" }]);
  });

  it("sends the transition with expected_version and only non-empty reason fields", async () => {
    const seen: Request[] = [];
    const client = fakeClient(() => Response.json(testQuoteWire({ status: "cancelled", version: 3, transitions: [] })), seen);
    const quote = parseQuoteDetail(testQuoteWire({ version: 2 }));
    const result = await transitionQuote(quote, { action: "cancel", reason: "  Customer withdrew ", note: "  " }, "key-1", client);
    expect(await seen[0]!.json()).toEqual({ action: "cancel", expected_version: 2, reason: "Customer withdrew" });
    expect(seen[0]!.headers.get("Idempotency-Key")).toBe("key-1");
    expect(new URL(seen[0]!.url).pathname).toBe(`/api/v1/sales/quotes/${QUOTE}/transitions`);
    expect(result?.status).toBe("cancelled");
  });
});

describe("quote header: dirty fields and the 409 three-way merge", () => {
  const base = headerFormOf(parseQuoteDetail(testQuoteWire()));

  it("sends only the fields the person changed, with expected_version", async () => {
    const form = { ...base, incoterm: "CIF", incoterm_place: " Hamburg ", remarks: "" };
    expect(dirtyHeaderFields(base, form)).toEqual(["incoterm", "incoterm_place"]);
    expect(headerChanges(base, form)).toEqual({ incoterm: "CIF", incoterm_place: "Hamburg" });
    expect(headerChanges(base, { ...base, validity_days: "45" })).toEqual({ validity_days: 45 });
    expect(headerChanges(base, { ...base, validity_days: "4.5" })).toEqual({});

    const seen: Request[] = [];
    const client = fakeClient(() => Response.json(testQuoteWire({ version: 2 })), seen);
    await updateQuoteHeader({ id: QUOTE, version: 1 }, { incoterm: "CIF" }, "key-h", client);
    expect(await seen[0]!.json()).toEqual({ expected_version: 1, incoterm: "CIF" });
  });

  it("turns a 409 version_conflict into conflict info the screen can show", async () => {
    const client = fakeClient(() => problem(409, "version_conflict", { current_version: 3, changed_by: { display_name: "Sahil Rao" }, changed_at: "2026-10-12T04:00:00Z" }));
    const error = await updateQuoteHeader({ id: QUOTE, version: 1 }, { incoterm: "CIF" }, "key-h", client).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ProblemError);
    expect(conflictFromError(error)).toMatchObject({ code: "version_conflict", currentVersion: 3, changedBy: "Sahil Rao", request_id: "req-9" });
  });

  it("keeps my edits, adopts theirs and reports fields both changed", () => {
    const mine = { ...base, incoterm: "CIF", remarks: "Pack in pairs" };
    const theirs = parseQuoteDetail({ ...testQuoteWire({ version: 3 }), incoterm: "EXW", payment_terms: "30 days" });
    const state = mergeHeaderConflict(base, mine, theirs, { changedBy: "Sahil Rao", changedAt: null });
    expect(state.version).toBe(3);
    expect(state.conflicts).toEqual(["incoterm"]);
    expect(state.adopted).toEqual(["payment_terms"]);
    expect(state.form).toMatchObject({ incoterm: "CIF", remarks: "Pack in pairs", payment_terms: "30 days" });
    // From now on the dirty fields are computed against their version.
    expect(headerChanges(state.base, state.form)).toEqual({ incoterm: "CIF", remarks: "Pack in pairs" });
  });
});

describe("quote lines", () => {
  const quote = parseQuoteDetail(testQuoteWire());
  const line = quote.lines[0]!;

  it("asks for a reason when the price differs from the list, and clears the override when it goes back", () => {
    expect(priceDiffersFromList(line, "22.00")).toBe(true);
    expect(priceDiffersFromList(line, "24.0")).toBe(false);
    expect(lineUpdatePlan(line, { ...lineEditOf(line), unit_price: "22.00" })).toEqual({ ok: false, error: "reason" });
    expect(lineUpdatePlan(line, { ...lineEditOf(line), unit_price: "22.00", override_reason: " Long-standing customer " })).toEqual({
      ok: true,
      body: { unit_price: "22.00", override_reason: "Long-standing customer" },
    });
    const overridden = parseQuoteDetail(testQuoteWire({ overridden: true })).lines[0]!;
    expect(lineUpdatePlan(overridden, { ...lineEditOf(overridden), unit_price: "24.0000" })).toEqual({ ok: true, body: { clear_override: true } });
    expect(lineUpdatePlan(line, { ...lineEditOf(line), quantity: "0" })).toEqual({ ok: false, error: "quantity" });
    expect(lineUpdatePlan(line, { ...lineEditOf(line), quantity: "300" })).toEqual({ ok: true, body: { quantity: "300" } });
  });

  it("previews unsaved edits through the calculate endpoint (never adds up on the client)", async () => {
    expect(previewRequest(quote, {})).toBeNull();
    const request = previewRequest(quote, { [line.id]: { ...lineEditOf(line), quantity: "300" } });
    expect(request).toEqual({
      currency: "EUR",
      party_id: quote.party.id,
      price_type: "export",
      surcharge_requested: false,
      lines: [{ line_key: line.line_key, line_type: "catalog", product_id: line.product_id, quantity: "300", unit_code: "pcs" }],
    });
    const seen: Request[] = [];
    const money = (amount: string) => ({ amount, currency: "EUR" });
    const client = fakeClient(
      () =>
        Response.json({
          calculation: {
            currency: "EUR",
            lines: [{ line_key: line.line_key, net: money("7200.00"), recommendation: { label: "" } }],
            applicable_subtotal: money("7200.00"),
            discount_total: money("0.00"),
            surcharge: { applied: false, amount: money("0.00"), reason_code: "NOT_APPLICABLE", label: "Minimum order surcharge" },
            minimum: { status: "MEETS" },
            grand_total: money("7200.00"),
            totals_complete: true,
            warnings: [],
          },
          lines: [],
          warnings: [],
        }),
      seen,
    );
    const preview = await previewQuote(request!, undefined, client);
    expect(new URL(seen[0]!.url).pathname).toBe("/api/v1/sales/quotes/calculate");
    expect(preview).toMatchObject({ applicable_subtotal: "7200.00", grand_total: "7200.00", surcharge_applied: false, line_totals: { [line.line_key]: "7200.00" } });
  });

  it("reads Money objects and bare strings in a preview", () => {
    const preview = parsePreview({
      calculation: { currency: "EUR", applicable_subtotal: "100.00", surcharge: { applied: true, amount: { amount: "400.00", currency: "EUR" }, label: "Surcharge" }, grand_total: null, lines: [] },
    });
    expect(preview).toMatchObject({ applicable_subtotal: "100.00", surcharge_amount: "400.00", surcharge_applied: true, grand_total: null });
  });
});

describe("money from strings", () => {
  it("formats DecimalStr amounts exactly, never through a float", () => {
    expect(formatMoney({ amount: "5760.00", currency: "EUR" }, { locale: "en-IN" })).toBe("€5,760.00");
    expect(formatMoney({ amount: "24.0000", currency: "EUR" }, { locale: "en-IN", maxFractionDigits: 4 })).toBe("€24.00");
    expect(formatMoney({ amount: "99999999999999.99", currency: "EUR" }, { locale: "en-US" })).toBe("€99,999,999,999,999.99");
    expect(formatMoney({ amount: "not-a-number", currency: "EUR" })).toBeNull();
  });
});

describe("QuoteWorkspace (server render)", () => {
  function renderQuote(wire: Record<string, unknown>, revisions: unknown[] = []) {
    return renderWithQueries(
      <QuoteWorkspace quoteId={QUOTE} />,
      (client) => {
        client.setQueryData(queryKeys.sales.quote(QUOTE), parseQuoteDetail(wire));
        client.setQueryData(queryKeys.sales.quoteHistory(QUOTE), []);
        client.setQueryData(queryKeys.sales.quoteRevisions(QUOTE), parseRevisions(revisions, QUOTE));
      },
      salesBootstrap(),
    );
  }

  it("shows the draft with server totals, editable lines and only the allowed commands", () => {
    const html = renderQuote(testQuoteWire());
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>LK-QT-2026-0009<\/h1>/);
    expect(text).toMatch(/Grand total \(excl\. taxes\) €5,760\.00/);
    expect(text).toContain("216 pcs reach EUR 5,000.00");
    expect(html).toMatch(/value="240"/);
    expect(text).toContain("Request review");
    expect(text).toContain("Mark as sent");
    expect(text).not.toContain("Mark as won");
    expect(text).toContain("Add a product");
    expect(text).toContain("Add a manual line");
    expect(text).toContain("Drafted by the assistant");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("is read-only once sent, and links each issued revision's PDF with a real <a href>", () => {
    const html = renderQuote(
      testQuoteWire({
        status: "sent",
        capabilities: { update: { allowed: false, reason_code: "not_draft" } },
        transitions: [{ action: "mark_won", to_status: "won", requires_reason: false }],
      }),
      [{ id: "r1", revision_no: 1, issued_at: "2026-10-12T05:00:00Z", valid_until: "2026-11-11", document_sha256: "c".repeat(64), document_path: `/api/v1/sales/quotes/${QUOTE}/revisions/1/document.pdf` }],
    );
    const text = textOf(html);
    expect(html).toContain(`href="/api/v1/sales/quotes/${QUOTE}/revisions/1/document.pdf"`);
    expect(text).toContain("PDF of revision 1");
    expect(text).toContain("Mark as won");
    expect(text).not.toContain("Request review");
    expect(text).not.toContain("Add a product");
    expect(text).toContain("240 pcs");
    expect(text).toContain("This quote can't be edited in its current status.");
  });

  it("explains the review a quote needs before it can be sent", () => {
    const text = textOf(renderQuote(testQuoteWire({ overridden: true })));
    expect(text).toContain("Needs approval before sending: price override.");
    expect(text).toContain("Long-standing customer");
  });
});

describe("quote list", () => {
  it("normalises the URL state and builds canonical links", () => {
    expect(quoteListStateFrom({ q: " oak ", status: "bogus", scope: "all", offset: "37" })).toEqual({ q: " oak ", status: null, scope: "all", offset: 25 });
    expect(quoteListHref({ q: "oak", status: "draft", scope: "mine", offset: 0 })).toBe("/sales/quotes?q=oak&status=draft");
    expect(enquiryListStateFrom({ status: "closed", offset: "-5" })).toEqual({ q: "", status: "closed", offset: 0 });
    expect(messageListStateFrom({ status: "nope" })).toEqual({ status: "received", offset: 0 });
  });

  it("renders rows with the persisted grand total and a phone list", () => {
    const html = renderWithQueries(
      <QuoteList state={{ q: "", status: null, scope: "mine", offset: 0 }} />,
      (client) =>
        client.setQueryData(queryKeys.sales.quotes({ q: null, status: null, scope: "mine", offset: 0 }), {
          items: [parseQuoteDetail(testQuoteWire())],
          total: 1,
          limit: 25,
          offset: 0,
        }),
      salesBootstrap(),
    );
    const text = textOf(html);
    expect(text).toContain("LK-QT-2026-0009");
    expect(text).toContain("Nordhaus Interiors GmbH");
    expect(text).toContain("€5,760.00");
    expect(text).toContain("New quote");
  });
});

describe("customer messages", () => {
  it("offers Mark replied only when the server allows it", () => {
    const base = {
      id: "m1",
      party: { id: "p1", party_number: "P-00001", display_name: "Nordhaus", country_code: "DE" },
      channel: "email",
      received_at: "2026-10-12T03:00:00Z",
      assignee: { id: "u1", display_name: "Meera" },
      body: "Please quote 240 trays",
      status: "received",
      version: 1,
      path: "/sales/customer-messages",
      capabilities: {},
    };
    expect(canMarkReplied(parseCustomerMessage({ ...base, allowed_transitions: [{ action: "mark_replied", to_status: "replied", requires_reason: false }] })!)).toBe(true);
    expect(canMarkReplied(parseCustomerMessage({ ...base, allowed_transitions: [] })!)).toBe(false);
  });
});
