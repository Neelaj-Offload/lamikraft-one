import { describe, expect, it } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { render, renderInSession, textOf } from "@/lib/test-support/render";
import { postTurn } from "./api";
import { AssistantCardView } from "./cards";
import { mergeRun, parseCard, parseRun, runOutput } from "./parse";
import { buildScreenContext, contextBytes, SCREEN_CONTEXT_MAX_BYTES, SCREEN_CONTEXT_MAX_ITEMS, type ListRow } from "./screen-context";
import type { AssistantCard } from "./types";

const QUOTE = "0192a000-0000-7000-8000-000000000009";
const NOW = new Date("2026-10-12T03:30:00.123Z");
const uuid = (n: number) => `0192a000-0000-7000-8000-${n.toString(16).padStart(12, "0")}`;
const rows = (count: number, start = 1): ListRow[] =>
  Array.from({ length: count }, (_, index) => ({ type: "sales.quote", id: uuid(start + index), version: 1, ordinal: start + index }));

describe("screen context builder (ai-routing §4.1)", () => {
  it("captures route params, focus, list refs, selection and filters", () => {
    const context = buildScreenContext({
      pathname: `/sales/quotes/${QUOTE}`,
      now: NOW,
      contributions: [
        {
          focus: { type: "sales.quote", id: QUOTE, version: 4 },
          related: [{ type: "parties.party", id: uuid(900), version: null }],
          lists: [{ key: "lines", rows: rows(3) }],
          selectedIds: [uuid(2)],
          filters: { status: "draft", q: "", empty: [] },
        },
      ],
    });
    expect(context.route).toEqual({ path: "/sales/quotes/[quoteId]", params: { quoteId: QUOTE }, area: "sales" });
    expect(context.captured_at).toBe("2026-10-12T03:30:00Z");
    expect(context.focus).toEqual({ type: "sales.quote", id: QUOTE, version: 4 });
    expect(context.records.map((record) => record.role)).toEqual(["primary", "related"]);
    expect(context.visible_items.map((item) => item.ref)).toEqual(["i1", "i2", "i3"]);
    expect(context.selection).toEqual(["i2"]);
    expect(context.filters).toEqual({ status: "draft" });
  });

  it("never sends more than 50 visible items, keeping the focused list first", () => {
    const context = buildScreenContext({
      pathname: "/sales/quotes",
      now: NOW,
      contributions: [{ lists: [{ key: "other", rows: rows(30, 500) }, { key: "quotes", rows: rows(60) }], selectedIds: [uuid(3)] }],
    });
    expect(context.visible_items).toHaveLength(SCREEN_CONTEXT_MAX_ITEMS);
    expect(context.visible_items[0]).toMatchObject({ list_key: "quotes", ref: "i1" });
    expect(context.visible_items.every((item) => item.list_key === "quotes")).toBe(true);
    expect(context.selection).toEqual(["i3"]);
  });

  it("stays within 16 KB: drops draft values, other lists, related records and filters before focused rows", () => {
    const big = "x".repeat(4000);
    const context = buildScreenContext({
      pathname: "/sales/quotes",
      now: NOW,
      contributions: [
        {
          focus: { type: "sales.quote", id: uuid(7), version: 1 },
          related: Array.from({ length: 40 }, (_, index) => ({ type: "parties.party", id: uuid(2000 + index), version: null })),
          lists: [{ key: "quotes", rows: rows(40) }, { key: "other", rows: rows(10, 900) }],
          filters: { q: big, note: big },
          draft: { form_key: "sales.quote.header", record_ref: uuid(7), dirty_fields: ["remarks"], values: { remarks: big } },
        },
      ],
    });
    expect(contextBytes(context)).toBeLessThanOrEqual(SCREEN_CONTEXT_MAX_BYTES);
    expect(context.draft).toEqual({ form_key: "sales.quote.header", record_ref: uuid(7), dirty_fields: ["remarks"], values: {} });
    expect(context.visible_items.some((item) => item.id === uuid(7))).toBe(true);
    expect(context.focus?.id).toBe(uuid(7));
  });

  it("removes restricted and clean fields from the draft", () => {
    const context = buildScreenContext({
      pathname: "/sales/quotes/new",
      now: NOW,
      contributions: [
        { draft: { form_key: "quote", record_ref: null, dirty_fields: ["incoterm", "cost_price"], values: { incoterm: "CIF", cost_price: "9.00", remarks: "clean" }, restricted: ["cost_price"] } },
      ],
    });
    expect(context.draft).toEqual({ form_key: "quote", record_ref: null, dirty_fields: ["incoterm"], values: { incoterm: "CIF" } });
  });
});

// Shapes as agents/cards.py builds them (model_dump(mode="json")).
const draftCard = {
  kind: "quote_draft",
  provider_label: "Demo",
  tainted: false,
  quote_id: QUOTE,
  quote_number: "LK-QT-2026-0009",
  status: "draft",
  party_id: uuid(900),
  party_label: "Nordhaus Interiors GmbH",
  currency: "EUR",
  lines: [{ line_no: 1, product_key: "LK-OT-0450", product_name: "Oak serving tray 450", quantity: "240", uom: "pcs", unit_price: "24.0000", line_total: "5760.00" }],
  totals: { currency: "EUR", applicable_subtotal: "5760.00", surcharge: "0.00", surcharge_applied: false, grand_total: "5760.00", minimum_status: "MEETS", recommended_quantity: 216, notes: [] },
  capabilities: {},
  review: { resource_type: "sales.quote", resource_id: QUOTE, label: "Review LK-QT-2026-0009", path: `/sales/quotes/${QUOTE}` },
  preview_only: false,
  requires_confirmation: false,
};

describe("cards (ai-routing §5)", () => {
  it("reads a QuoteDraftCard with server totals and the Demo label", () => {
    const card = parseCard(draftCard);
    expect(card).toMatchObject({
      kind: "quote_draft",
      demo: true,
      quote_number: "LK-QT-2026-0009",
      party_name: "Nordhaus Interiors GmbH",
      subtotal: { amount: "5760.00", currency: "EUR" },
      surcharge: null,
      grand_total: { amount: "5760.00", currency: "EUR" },
      open_href: `/sales/quotes/${QUOTE}`,
    });
    expect(card?.kind === "quote_draft" && card.lines[0]).toMatchObject({ label: "Oak serving tray 450", quantity: "240", unit_code: "pcs" });
    expect(card?.kind === "quote_draft" && card.notes).toContain("Recommended quantity: 216 pcs");
  });

  it("renders the draft card: lines, totals from strings, open and Demo badge", () => {
    const html = renderInSession(<AssistantCardView card={parseCard(draftCard)!} />);
    const text = textOf(html);
    expect(text).toContain("Draft LK-QT-2026-0009");
    expect(text).toContain("240 pcs");
    expect(text).toMatch(/Grand total \(excl\. taxes\) €5,760\.00/);
    expect(text).toContain("Demo");
    expect(html).toContain(`href="/sales/quotes/${QUOTE}"`);
    expect(text).not.toContain("Minimum order surcharge");
  });

  it("posts a clarification option back as {slot, value}", () => {
    const card = parseCard({
      kind: "clarification",
      provider_label: "Demo",
      slot: "party",
      question: "Which Nordhaus?",
      options: [
        { ref: "o1", label: "Nordhaus Interiors GmbH", detail: "P-00001 · DE", action: { kind: "select_option", slot: "party", value: uuid(900), label: "Nordhaus", data: {} } },
        { ref: "o2", label: "Broken option" },
      ],
    });
    expect(card).toMatchObject({ kind: "clarification", options: [{ id: "o1", value: { slot: "party", value: uuid(900) } }] });
    const html = renderInSession(<AssistantCardView card={card!} onChoose={() => undefined} />);
    expect(html).toMatch(/<button[^>]*>.*Nordhaus Interiors GmbH/);
    expect(textOf(html)).toContain("Which Nordhaus?");
  });

  it("renders error, record link and receipt cards; drops unknown kinds and off-site links", () => {
    const error = parseCard({
      kind: "error",
      code: "price_missing",
      message: "No price list covers this product.",
      recoverable_draft: { label: "Open the saved draft", path: `/sales/quotes/${QUOTE}` },
      direct_controls: [{ label: "Price lists", path: "/products" }, { label: "Evil", path: "https://evil.example" }],
    });
    expect(error).toMatchObject({ kind: "error", controls: [{ label: "Price lists", href: "/products" }] });
    expect(textOf(renderInSession(<AssistantCardView card={error!} />))).toContain("No price list covers this product.");

    const receipt = parseCard({ kind: "receipt", action: "draft_quote", summary: "Draft LK-QT-2026-0009 saved", record: { label: "Open", path: `/sales/quotes/${QUOTE}` }, at: "2026-10-12T03:30:00Z" });
    expect(receipt).toMatchObject({ kind: "receipt", title: "Draft LK-QT-2026-0009 saved", link: { href: `/sales/quotes/${QUOTE}` } });
    expect(textOf(renderInSession(<AssistantCardView card={receipt!} />))).toContain("Draft LK-QT-2026-0009 saved");

    const link = parseCard({ kind: "record_link", label: "LK-QT-2026-0009", path: `/sales/quotes/${QUOTE}` });
    expect(render(<AssistantCardView card={link!} />)).toContain(`href="/sales/quotes/${QUOTE}"`);
    expect(parseCard({ kind: "record_link", label: "x", path: "//evil.example/x" })).toBeNull();
    expect(parseCard({ kind: "poll", question: "?" })).toBeNull();
  });
});

describe("runs", () => {
  const summary = (status: string) => ({ id: uuid(77), status, provider: "demo", tainted: false, error_code: null });

  it("reads RunDetail and merges polls without repeating steps or cards", () => {
    const first = parseRun({ run: summary("running"), steps: [{ seq: 1, kind: "route", name: "route", output: null, is_error: false }], done: false, text: null, cards: [] });
    const second = parseRun({
      run: summary("succeeded"),
      steps: [
        { seq: 1, kind: "route", name: "route", is_error: false },
        { seq: 2, kind: "card", name: "quote_draft", output: draftCard, is_error: false },
        { seq: 3, kind: "text", name: "final_text", output: { text: "Here is the draft." }, is_error: false },
      ],
      done: true,
      text: "Here is the draft.",
      cards: [draftCard],
    });
    const merged = mergeRun(first, second);
    expect(merged.status).toBe("succeeded");
    expect(merged.steps.map((step) => step.seq)).toEqual([1, 2, 3]);
    const output = runOutput(merged);
    expect(output.cards).toHaveLength(1);
    expect(output.texts).toEqual(["Here is the draft."]);
    // A cancel answers with a bare RunSummary.
    expect(parseRun(summary("cancelled"))).toMatchObject({ status: "cancelled", steps: [], cards: [] });
  });

  it("falls back to the final text and cards when no step carried them", () => {
    const run = parseRun({ run: summary("succeeded"), steps: [], done: true, text: "Done.", cards: [draftCard] });
    const output = runOutput(run);
    expect(output.texts).toEqual(["Done."]);
    expect((output.cards[0] as AssistantCard).kind).toBe("quote_draft");
  });

  it("posts the turn with the context, the selected option and the client utterance id", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json({ run_id: uuid(77), turn_id: uuid(78), conversation_id: uuid(79), status: "queued" }, { status: 202 });
      },
    });
    const context = buildScreenContext({ pathname: "/today", now: NOW, contributions: [] });
    const runId = await postTurn(uuid(79), { text: "Nordhaus Interiors", context, selectedOption: { slot: "party", value: uuid(900) }, clientUtteranceId: uuid(80) }, "key-t", client);
    expect(runId).toBe(uuid(77));
    const body = await seen[0]!.json();
    expect(body).toMatchObject({ text: "Nordhaus Interiors", selected_option: { slot: "party", value: uuid(900) }, client_utterance_id: uuid(80) });
    expect(body.context.route).toEqual({ path: "/today", params: {}, area: "today" });
  });
});
