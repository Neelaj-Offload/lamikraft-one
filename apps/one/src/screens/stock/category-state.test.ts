import { describe, expect, it } from "vitest";
import { variantKey } from "../products/design-builder";
import { categoryHref, categoryStateFrom } from "./category-state";

describe("stock by category state", () => {
  it("parses, drops unknown values and round-trips", () => {
    const id = "01a2120a-fdf3-7453-a7ed-f19df50665ab";
    const state = categoryStateFrom({ q: "cb07", warehouse: id, market: "export", category: "exhibition", offset: "55" });
    expect(state).toEqual({ q: "cb07", warehouse: id, market: "export", category: "exhibition", offset: 50 });
    expect(categoryStateFrom(Object.fromEntries(new URL(categoryHref(state), "http://127.0.0.1").searchParams))).toEqual(state);
    expect(categoryStateFrom({ market: "moon", category: "raw", warehouse: "x" })).toEqual({ q: "", warehouse: null, market: null, category: null, offset: 0 });
  });
});

describe("variantKey", () => {
  it("matches the server rule", () => {
    expect(variantKey("cb07", "892", "m")).toBe("CB07-892-M");
    expect(variantKey("RS-01", "959", "XL")).toBe("RS-01-959-XL");
  });
});
