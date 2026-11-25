import { describe, expect, it } from "vitest";
import { proformaListHref, proformaListStateFrom } from "./list-state";

describe("proforma list state", () => {
  it("parses and round-trips", () => {
    const state = proformaListStateFrom({ q: "berg", status: "issued", offset: "26" });
    expect(state).toEqual({ q: "berg", status: "issued", offset: 25 });
    const url = new URL(proformaListHref(state), "http://127.0.0.1");
    expect(proformaListStateFrom(Object.fromEntries(url.searchParams))).toEqual(state);
  });

  it("drops unknown values", () => {
    expect(proformaListStateFrom({ status: "paid", offset: "x" })).toEqual({ q: "", status: null, offset: 0 });
    expect(proformaListHref({})).toBe("/sales/proforma-invoices");
  });
});
