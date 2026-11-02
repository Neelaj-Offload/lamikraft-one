import { describe, expect, it } from "vitest";
import { partyListHref, partyListStateFrom } from "./list-state";

describe("partyListStateFrom", () => {
  it("reads every filter from the URL and ignores unknown values", () => {
    expect(partyListStateFrom({ q: "nord", role: "customer", status: "active", country_code: "de", customer_type: "dealer", include_archived: "true", offset: "50" })).toEqual({
      q: "nord",
      role: "customer",
      status: "active",
      country_code: "DE",
      customer_type: "dealer",
      include_archived: true,
      offset: 50,
    });
    expect(partyListStateFrom({ role: "pirate", status: "weird", country_code: "Germany", customer_type: "vip", include_archived: "yes", offset: "-3" })).toEqual({
      q: "",
      role: null,
      status: null,
      country_code: null,
      customer_type: null,
      include_archived: false,
      offset: 0,
    });
  });

  it("snaps the offset to the page size and takes the first value of a repeated param", () => {
    expect(partyListStateFrom({ offset: "37" }).offset).toBe(25);
    expect(partyListStateFrom({ offset: "abc" }).offset).toBe(0);
    expect(partyListStateFrom({ q: ["a", "b"] }).q).toBe("a");
  });
});

describe("partyListHref", () => {
  it("writes only the non-default parts and round-trips", () => {
    expect(partyListHref({})).toBe("/sales/parties");
    const href = partyListHref({ q: " nord ", role: "customer", status: "blocked", country_code: "DE", customer_type: "distributor", include_archived: true, offset: 25 });
    expect(href).toBe("/sales/parties?q=nord&role=customer&status=blocked&country_code=DE&customer_type=distributor&include_archived=true&offset=25");
    const search = Object.fromEntries(new URL(href, "http://x").searchParams);
    expect(partyListStateFrom(search)).toEqual({ q: "nord", role: "customer", status: "blocked", country_code: "DE", customer_type: "distributor", include_archived: true, offset: 25 });
  });
});
