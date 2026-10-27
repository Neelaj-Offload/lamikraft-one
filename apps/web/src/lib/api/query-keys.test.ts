import { describe, expect, it } from "vitest";
import { invalidationMap, queryKeys } from "./query-keys";

describe("query keys", () => {
  it("start with the owning module", () => {
    expect(queryKeys.briefings.today()).toEqual(["briefings", "today"]);
    expect(queryKeys.tasks.inbox({ tab: "tasks" })[0]).toBe("tasks");
    expect(queryKeys.session.bootstrap()[0]).toBe("session");
  });

  it("normalise parameters so equal filters give equal keys", () => {
    expect(queryKeys.tasks.inbox({ tab: "approvals", cursor: null })).toEqual(
      queryKeys.tasks.inbox({ tab: "approvals" }),
    );
    expect(queryKeys.search.query("  oak tray ")).toEqual(["search", "results", { q: "oak tray" }]);
    expect(queryKeys.search.query("")).toEqual(["search", "results", {}]);
  });

  it("invalidate Today and Inbox after briefing actions", () => {
    expect(invalidationMap["briefings.item_action"]).toContainEqual(["briefings", "today"]);
    expect(invalidationMap["briefings.item_action"]).toContainEqual(["tasks"]);
  });
});
