import { describe, expect, it } from "vitest";
import { DEFAULT_LEAD_STATE, hasLeadFilters, leadListHref, leadListStateFrom, leadQueryOf } from "./list-state";
import { followUpState, isoToday } from "./labels";

describe("leadListStateFrom", () => {
  it("reads every filter from the URL", () => {
    const state = leadListStateFrom({
      status: "prospect",
      q: " harbour ",
      stage: "new,qualified",
      source: "NRA_Chicago_2026",
      interest: "table_top",
      priority: "A",
      temperature: "hot",
      follow_up: "overdue",
      mine: "1",
      sort: "recent",
      offset: "30",
    });
    expect(state).toEqual({
      q: " harbour ",
      stages: ["new", "qualified"],
      source: "nra_chicago_2026",
      interest: "table_top",
      priority: "A",
      temperature: "hot",
      follow_up: "overdue",
      mine: true,
      sort: "recent",
      offset: 25,
    });
  });

  it("drops unknown values instead of forwarding them", () => {
    const state = leadListStateFrom({ stage: "new,bogus", source: "Not a code!", interest: "spoons", priority: "Z", sort: "x", offset: "-5" });
    expect(state).toEqual({ ...DEFAULT_LEAD_STATE, stages: ["new"] });
  });

  it("round-trips through the href", () => {
    const state = { ...DEFAULT_LEAD_STATE, stages: ["contacted" as const], source: "website", mine: true, offset: 50 };
    const url = new URL(leadListHref(state), "http://127.0.0.1");
    expect(url.pathname).toBe("/sales/parties");
    expect(url.searchParams.get("status")).toBe("prospect");
    expect(leadListStateFrom(Object.fromEntries(url.searchParams))).toEqual(state);
    expect(leadListHref(DEFAULT_LEAD_STATE)).toBe("/sales/parties?status=prospect");
  });
});

describe("leadQueryOf", () => {
  it("sends the owner only for Mine", () => {
    expect(leadQueryOf({ ...DEFAULT_LEAD_STATE, mine: true }, "u-1").owner_user_id).toBe("u-1");
    expect(leadQueryOf(DEFAULT_LEAD_STATE, "u-1").owner_user_id).toBeNull();
    expect(hasLeadFilters(DEFAULT_LEAD_STATE)).toBe(false);
    expect(hasLeadFilters({ ...DEFAULT_LEAD_STATE, follow_up: "today" })).toBe(true);
  });
});

describe("follow-up helpers", () => {
  it("classifies dates against today", () => {
    expect(followUpState("2026-10-11", "2026-10-12")).toBe("overdue");
    expect(followUpState("2026-10-12", "2026-10-12")).toBe("today");
    expect(followUpState("2026-10-13", "2026-10-12")).toBeNull();
    expect(followUpState(null, "2026-10-12")).toBeNull();
  });

  it("computes today in the company zone", () => {
    expect(isoToday("Asia/Kolkata", new Date("2026-10-11T20:00:00Z"))).toBe("2026-10-12");
  });
});
