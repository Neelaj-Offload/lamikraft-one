import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { challanCsvHref, challanListQuery } from "./api";
import { commandButtons, issueBlockedText } from "./challan-commands";
import { ChallanList } from "./challan-list";
import { ChallanWorkspace } from "./challan-workspace";
import { createBody, EMPTY_HEADER, fieldErrorsFrom, headerChanges, headerFormOf, headerProblems, withDestination, withType } from "./form-model";
import { createDebouncedSaver, quantityProblem, type SaveState } from "./line-save";
import { challanListHref, challanListParams, challanListQueryKey, challanListStateFrom, challanSummaryQueryKey } from "./list-state";
import { parseChallanDetail, parseChallanPage, parseChallanSummary } from "./parse";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/operations/challans",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000e1";
const LINE = "0192a000-0000-7000-8000-0000000000e2";

function wire(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: ID,
    challan_number: "DC-2026-0003",
    revision_no: 0,
    challan_date: "2026-10-12",
    challan_type: "outward",
    return_type: "non_returnable",
    destination_type: "customer",
    destination_party: "Nordhaus Interiors GmbH",
    party: { id: "0192a000-0000-7000-8000-0000000000f1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH" },
    reference_no: "PO-NH-2211",
    status: "draft",
    line_count: 1,
    quantity_by_unit: { pcs: "40" },
    outstanding_by_unit: {},
    expected_return_date: null,
    owner: { id: "u1", display_name: "Ravi Kulkarni" },
    created_by: null,
    branch_id: null,
    created_at: "2026-10-12T03:00:00Z",
    updated_at: "2026-10-12T03:00:00Z",
    deleted_at: null,
    version: 2,
    path: `/operations/challans/${ID}`,
    source_location: "Crown / Lamikraft Office",
    source_branch: null,
    consignee_party: null,
    office_branch: null,
    shipping_name: null,
    gstin: "27AAACC1234F1Z5",
    phone: null,
    email: null,
    address: "Lindenstraße 4\nHamburg",
    remarks: "Repeat order trays; palletised.",
    direction: "outward",
    inventory_effect: "none",
    original_challan: null,
    duplicated_from: null,
    issued_at: null,
    issued_by: null,
    closed_at: null,
    close_reason: null,
    cancelled_at: null,
    cancel_reason_code: null,
    cancel_reason: null,
    updated_by: null,
    origin: "seed",
    lines: [
      {
        id: LINE,
        line_no: 1,
        line_type: "catalog",
        product_id: "p1",
        custom_product_id: null,
        item_code: "LK-OT-0450",
        item_name: "Oak serving tray 450",
        hsn_sac: "44191900",
        quantity: "40",
        unit: "pcs",
        remarks: null,
        original_line_id: null,
        returned_quantity: "0",
        outstanding_quantity: "40",
      },
    ],
    return_links: [],
    history: [],
    capabilities: {
      update: { allowed: true, reason_code: null },
      delete: { allowed: false, reason_code: "permission_denied" },
      export: { allowed: true, reason_code: null },
      issue: { allowed: true, reason_code: null },
      duplicate: { allowed: true, reason_code: null },
      note: { allowed: true, reason_code: null },
    },
    allowed_transitions: [
      { action: "issue", to_status: "issued", requires_reason: false },
      { action: "cancel", to_status: "cancelled", requires_reason: true },
    ],
    ...overrides,
  };
}

const ravi = () =>
  testBootstrap({
    permissions: [
      { key: "challans.challan.read", scope: "branch" },
      { key: "challans.challan.create", scope: "branch" },
      { key: "challans.challan.update", scope: "branch" },
      { key: "challans.challan.export", scope: "branch" },
    ],
  });

describe("list state", () => {
  it("round-trips every filter and drops unknown values", () => {
    const state = challanListStateFrom({ q: " oak ", status: "issued", type: "job_work", destination: "fabricator", period: "this_week", pending: "1", scope: "mine", offset: "57" });
    expect(state).toEqual({ q: " oak ", status: "issued", type: "job_work", destination: "fabricator", period: "this_week", pending: true, scope: "mine", offset: 50 });
    expect(challanListStateFrom(Object.fromEntries(new URLSearchParams(challanListHref(state).split("?")[1])))).toEqual({ ...state, q: "oak" });
    expect(challanListStateFrom({ status: "archived", type: "gift", destination: "moon", period: "yesterday", scope: "everything", offset: "-3" })).toEqual({
      q: "",
      status: null,
      type: null,
      destination: null,
      period: null,
      pending: false,
      scope: "all",
      offset: 0,
    });
    expect(challanListHref({})).toBe("/operations/challans");
  });

  it("sends the same filters to the list, the summary and the CSV; the summary ignores the page", () => {
    const state = challanListStateFrom({ q: "DC-2026", type: "sample", pending: "1", offset: "25" });
    expect(challanListQuery(challanListParams(state))).toEqual({ q: "DC-2026", challan_type: "sample", pending_returnable: true, offset: 25, limit: 25, status: undefined, destination_type: undefined, period: undefined, scope: undefined });
    expect(challanCsvHref(challanListParams(state))).toBe("/api/v1/challans/challans/export.csv?q=DC-2026&challan_type=sample&pending_returnable=true");
    expect(challanSummaryQueryKey(state)).toEqual(challanSummaryQueryKey({ ...state, offset: 0 }));
    expect(challanListQueryKey(state)[0]).toBe("challans");
  });
});

describe("parse", () => {
  it("reads a detail, keeps DecimalStr quantities and falls back on unknown enums", () => {
    const c = parseChallanDetail(wire({ challan_type: "teleport", quantity_by_unit: { pcs: "40", kg: 2.5 } }));
    expect(c.challan_type).toBe("outward");
    expect(c.quantity_by_unit).toEqual({ pcs: "40" }); // a JSON number is never coerced into a quantity
    expect(c.lines[0]).toMatchObject({ item_code: "LK-OT-0450", quantity: "40", unit: "pcs" });
    expect(c.capabilities.issue).toEqual({ allowed: true, reason_code: null });
  });

  it("rejects a detail without lines and keeps only in-app paths", () => {
    expect(() => parseChallanDetail({ id: ID, challan_number: "x" })).toThrow();
    const page = parseChallanPage({ items: [wire({ path: "https://evil.test/x" })], total: 1, limit: 25, offset: 0 });
    expect(page.items[0]!.path).toBe(`/operations/challans/${ID}`);
    const summary = parseChallanSummary({ total: 3, this_week: 1, this_month: 3, pending_returnable: 2, pending_returnable_quantity: { sheets: "12", pcs: "2" }, issued: 2 });
    expect(summary.pending_returnable_quantity).toEqual({ sheets: "12", pcs: "2" });
  });
});

describe("header form", () => {
  it("follows the movement policy when the type or destination changes", () => {
    const job = withType({ ...EMPTY_HEADER, destination_type: "customer" }, "job_work");
    expect(job).toMatchObject({ return_type: "returnable", destination_type: "fabricator", party: null });
    const transfer = withType(EMPTY_HEADER, "transfer");
    expect(transfer).toMatchObject({ return_type: "non_returnable", destination_type: "warehouse" });
    expect(withDestination({ ...EMPTY_HEADER, party: { id: "p", party_number: "P-1", display_name: "X" } }, "office").party).toBeNull();
  });

  it("requires only the destination and sends only filled fields", () => {
    expect(headerProblems(EMPTY_HEADER)).toEqual({ destination_party: "destination_required" });
    expect(createBody({ ...EMPTY_HEADER, destination_party: " Nordhaus ", reference_no: "  ", expected_return_date: "2026-10-20" })).toEqual({
      challan_type: "outward",
      return_type: "non_returnable",
      destination_type: "customer",
      destination_party: "Nordhaus",
    });
  });

  it("patches only dirty fields and clears emptied optional text", () => {
    const base = headerFormOf(parseChallanDetail(wire()));
    expect(headerChanges(base, base)).toEqual({});
    expect(headerChanges(base, { ...base, gstin: "", reference_no: "PO-9" })).toEqual({ gstin: null, reference_no: "PO-9" });
  });

  it("maps 422 locations to field names", () => {
    const error = new ProblemError({
      title: "Invalid",
      status: 422,
      code: "validation_failed",
      errors: [
        { loc: ["body", "gstin"], msg: "bad gstin", code: "pattern" },
        { loc: ["body", "lines", 0, "quantity"], msg: "whole numbers", code: "not_integer" },
      ],
    });
    expect(fieldErrorsFrom(error)).toEqual({ gstin: "bad gstin", "lines.0.quantity": "whole numbers" });
  });
});

describe("debounced line saves (UI-83, BUG-14: never silent)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function saver(save: (value: string) => Promise<void>) {
    const states: SaveState<string>[] = [];
    const s = createDebouncedSaver<string>({
      validate: (raw) => quantityProblem(raw),
      save,
      onState: (state) => states.push(state),
    });
    return { s, states, last: () => states.at(-1)!.status };
  }

  it("sends one save 600 ms after the last keystroke", async () => {
    const save = vi.fn(async () => undefined);
    const { s, last } = saver(save);
    s.change("4");
    s.change("41");
    s.change("410");
    await vi.advanceTimersByTimeAsync(599);
    expect(save).not.toHaveBeenCalled();
    expect(last()).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("410");
    expect(last()).toBe("saved");
  });

  it("keeps a failure on screen until retried, and the retry sends the same value", async () => {
    let fail = true;
    const save = vi.fn(async () => {
      if (fail) throw new Error("boom");
    });
    const { s, last, states } = saver(save);
    s.change("12");
    await vi.advanceTimersByTimeAsync(600);
    expect(last()).toBe("failed");
    expect(s.hasUnsaved()).toBe(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(last()).toBe("failed"); // nothing hides it
    fail = false;
    await s.retry();
    expect(save).toHaveBeenLastCalledWith("12");
    expect(last()).toBe("saved");
    expect(s.hasUnsaved()).toBe(false);
    expect(states.map((state) => state.status)).toEqual(["pending", "saving", "failed", "saving", "saved"]);
  });

  it("never sends an invalid quantity and never runs two saves at once", async () => {
    let release: () => void = () => undefined;
    const save = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const { s, last } = saver(save);
    s.change("0");
    await vi.advanceTimersByTimeAsync(600);
    expect(save).not.toHaveBeenCalled();
    expect(last()).toBe("invalid");
    s.change("5");
    await vi.advanceTimersByTimeAsync(600);
    expect(save).toHaveBeenCalledTimes(1);
    s.change("6"); // typed while the first save is in flight
    await vi.advanceTimersByTimeAsync(600);
    expect(save).toHaveBeenCalledTimes(1);
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith("6");
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(last()).toBe("saved");
  });

  it("flushes a pending value at once", async () => {
    const save = vi.fn(async () => undefined);
    const { s } = saver(save);
    s.change("7");
    await s.flush();
    expect(save).toHaveBeenCalledWith("7");
  });

  it("checks quantities: positive decimals with up to 4 places", () => {
    expect(quantityProblem("")).toBe("required");
    expect(quantityProblem("0")).toBe("not_positive");
    expect(quantityProblem("-2")).toBe("invalid");
    expect(quantityProblem("1.23456")).toBe("invalid");
    expect(quantityProblem("1,200")).toBeNull();
  });
});

describe("commands come only from the server", () => {
  it("offers the allowed transitions, duplicate when allowed and delete only for admins", () => {
    const draft = parseChallanDetail(wire());
    expect(commandButtons(draft).map((b) => [b.action, b.variant, b.requiresReason])).toEqual([
      ["issue", "primary", false],
      ["cancel", "danger", true],
      ["duplicate", "secondary", false],
    ]);
    const issued = parseChallanDetail(wire({ status: "issued", allowed_transitions: [], capabilities: { duplicate: { allowed: false, reason_code: "permission_denied" } } }));
    expect(commandButtons(issued)).toEqual([]);
    const blocked = parseChallanDetail(wire({ lines: [], capabilities: { issue: { allowed: false, reason_code: "no_lines" } }, allowed_transitions: [] }));
    expect(issueBlockedText(blocked)).toBe("Add at least one line before issuing.");
  });
});

describe("screens (server render)", () => {
  it("shows the list with the summary facts, filters, CSV and New challan", () => {
    const state = challanListStateFrom({});
    const html = renderWithQueries(
      <ChallanList state={state} />,
      (client) => {
        client.setQueryData(challanListQueryKey(state), parseChallanPage({ items: [wire()], total: 1, limit: 25, offset: 0 }));
        client.setQueryData(
          challanSummaryQueryKey(state),
          parseChallanSummary({ total: 3, this_week: 1, this_month: 3, pending_returnable: 2, pending_returnable_quantity: { pcs: "2", sheets: "12" }, issued: 2 }),
        );
      },
      ravi(),
    );
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>Delivery challans<\/h1>/);
    expect(text).toContain("DC-2026-0003");
    expect(text).toContain("Pending returns");
    expect(text).toContain("12 sheets");
    expect(html).toContain('href="/api/v1/challans/challans/export.csv"');
    expect(text).toContain("New challan");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("shows a draft with editable quantities, the allowed commands and no internal note in the document", () => {
    const html = renderWithQueries(
      <ChallanWorkspace challanId={ID} />,
      (client) => {
        client.setQueryData(queryKeys.challans.challan(ID), parseChallanDetail(wire()));
        client.setQueryData(queryKeys.challans.note(ID), { body: "", version: 0, updated_at: null, updated_by: null, canUpdate: true });
      },
      ravi(),
    );
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>Nordhaus Interiors GmbH<\/h1>/);
    expect(text).toContain("DC-2026-0003");
    expect(text).toContain("Issue challan");
    expect(text).toContain("Cancel challan");
    expect(text).not.toContain("Delete draft");
    expect(html).toMatch(/value="40"/);
    expect(text).toContain("Quantity (pcs)");
    expect(text).toContain("Document only");
    expect(html).toContain(`href="/print/challans/${ID}"`);
    expect(html).toContain(`href="/api/v1/challans/challans/${ID}/document.pdf"`);
  });

  it("shows an issued challan read-only", () => {
    const html = renderWithQueries(
      <ChallanWorkspace challanId={ID} />,
      (client) => {
        client.setQueryData(
          queryKeys.challans.challan(ID),
          parseChallanDetail(wire({ status: "issued", capabilities: { export: { allowed: true, reason_code: null } }, allowed_transitions: [{ action: "close", to_status: "closed", requires_reason: false }] })),
        );
        client.setQueryData(queryKeys.challans.note(ID), { body: "x", version: 1, updated_at: null, updated_by: null, canUpdate: false });
      },
      ravi(),
    );
    const text = textOf(html);
    expect(text).toContain("Close challan");
    expect(text).toContain("Issued challans can't be edited");
    expect(html).not.toMatch(/value="40"/);
    expect(text).not.toContain("Add a line");
  });
});

describe("operations overview", () => {
  it("links the delivered challans part and keeps the rest planned", async () => {
    const { AreaOverview } = await import("@/features/areas/area-overview");
    const { renderInSession } = await import("@/lib/test-support/render");
    const { testBootstrap } = await import("@/lib/test-support/session");
    const html = renderInSession(<AreaOverview area="operations" />, testBootstrap({ permissions: [{ key: "challans.challan.read", scope: "company" }] }));
    expect(html).toContain('href="/operations/challans"');
    expect(textOf(html)).toContain("delivery challans are available now");
    expect(textOf(html)).toContain("Planned · Slice 4");
  });
});
