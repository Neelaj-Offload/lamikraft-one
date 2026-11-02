import { describe, expect, it } from "vitest";
import { auditSearch } from "./api";
import { auditListHref, auditListStateFrom, auditQueryFrom, startOfDayUtc } from "./list-state";

describe("audit log URL state", () => {
  it("reads only valid filters from the URL and ignores the rest", () => {
    expect(
      auditListStateFrom({ action_prefix: "sales.quote.", outcome: "denied", occurred_from: "2026-10-01", occurred_to: "2026-10-12", cursor: "MjAyNi0xMC0xMlQwMzoyNTowMFo." }),
    ).toEqual({ action_prefix: "sales.quote.", outcome: "denied", occurred_from: "2026-10-01", occurred_to: "2026-10-12", cursor: "MjAyNi0xMC0xMlQwMzoyNTowMFo." });
    expect(auditListStateFrom({ action_prefix: "drop table;", outcome: "maybe", occurred_from: "2026-13-40", occurred_to: "yesterday", cursor: "a b" })).toEqual({
      action_prefix: "",
      outcome: null,
      occurred_from: null,
      occurred_to: null,
      cursor: null,
    });
    expect(auditListStateFrom({ outcome: ["success", "denied"] }).outcome).toBe("success");
  });

  it("builds links that keep the filters and drop the cursor when asked", () => {
    const state = auditListStateFrom({ action_prefix: "org.", outcome: "success", occurred_from: "2026-10-01", cursor: "abc" });
    expect(auditListHref(state)).toBe("/settings/audit?action_prefix=org.&outcome=success&occurred_from=2026-10-01&cursor=abc");
    expect(auditListHref({ ...state, cursor: null })).toBe("/settings/audit?action_prefix=org.&outcome=success&occurred_from=2026-10-01");
    expect(auditListHref({})).toBe("/settings/audit");
  });

  it("turns the day range into zoned UTC instants with an exclusive end", () => {
    expect(startOfDayUtc("2026-10-12", "Asia/Kolkata")).toBe("2026-10-11T18:30:00Z");
    expect(startOfDayUtc("2026-10-12", "Asia/Kolkata", 1)).toBe("2026-10-12T18:30:00Z");
    const query = auditQueryFrom(auditListStateFrom({ occurred_from: "2026-10-01", occurred_to: "2026-10-12", outcome: "failed" }), "Asia/Kolkata");
    expect(query).toEqual({ action_prefix: null, outcome: "failed", occurred_from: "2026-09-30T18:30:00Z", occurred_to: "2026-10-12T18:30:00Z", cursor: null });
    expect(auditSearch(query).toString()).toBe("limit=50&outcome=failed&occurred_from=2026-09-30T18%3A30%3A00Z&occurred_to=2026-10-12T18%3A30%3A00Z");
  });
});
