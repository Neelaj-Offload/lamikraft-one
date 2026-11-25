import { describe, expect, it } from "vitest";
import { datedTransitionBody } from "./samples-history";

describe("datedTransitionBody", () => {
  it("adds the date only to steps that take one", () => {
    expect(datedTransitionBody({ version: 3 }, { action: "deliver", evidence_kind: "courier_tracking", occurred_on: "2026-05-02" })).toEqual({
      action: "deliver",
      expected_version: 3,
      evidence_kind: "courier_tracking",
      occurred_on: "2026-05-02",
    });
    expect(datedTransitionBody({ version: 3 }, { action: "cancel", reason: "Not needed", occurred_on: "2026-05-02" })).toEqual({
      action: "cancel",
      expected_version: 3,
      reason: "Not needed",
    });
    expect(datedTransitionBody({ version: 1 }, { action: "dispatch", dispatch_reference: "DHL 1" })).toEqual({
      action: "dispatch",
      expected_version: 1,
      dispatch_reference: "DHL 1",
    });
  });
});
