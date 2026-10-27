import { describe, expect, it } from "vitest";
import { forAllSeeds, int, pick } from "@/lib/test-support/random";
import { resolveConflicts, sameValue, threeWayMerge } from "./merge";

describe("threeWayMerge", () => {
  const base = { remarks: "Ship in two lots", incoterm: "FOB", validity_days: 30, tags: ["export"] };

  it("adopts their changes, keeps mine and reports true conflicts", () => {
    const mine = { remarks: "Ship in one lot", validity_days: 45 };
    const theirs = { ...base, remarks: "Ship by sea", incoterm: "CIF" };
    const result = threeWayMerge(base, mine, theirs);

    expect(result.adopted).toEqual(["incoterm"]);
    expect(result.conflicts).toEqual([
      { field: "remarks", base: "Ship in two lots", mine: "Ship in one lot", theirs: "Ship by sea" },
    ]);
    expect(result.merged).toEqual({ ...theirs, remarks: "Ship in one lot", validity_days: 45 });
    expect(result.dirty).toEqual({ remarks: "Ship in one lot", validity_days: 45 });
  });

  it("does not treat identical edits as a conflict", () => {
    const result = threeWayMerge(base, { incoterm: "CIF" }, { ...base, incoterm: "CIF" });
    expect(result.conflicts).toEqual([]);
    expect(result.dirty).toEqual({});
  });

  it("compares arrays and objects structurally", () => {
    expect(sameValue({ a: [1, { b: "2" }] }, { a: [1, { b: "2" }] })).toBe(true);
    expect(sameValue(["a"], { 0: "a" })).toBe(false);
    const result = threeWayMerge(base, { tags: ["export"] }, { ...base, tags: ["export", "priority"] });
    expect(result.adopted).toEqual(["tags"]);
    expect(result.dirty).toEqual({});
  });

  it("resolves conflicts by the user's choice and never drops an unresolved edit", () => {
    const result = threeWayMerge(base, { remarks: "Mine", incoterm: "EXW" }, { ...base, remarks: "Theirs", incoterm: "CIF" });
    const partly = resolveConflicts(result, { incoterm: { use: "theirs" } });
    expect(partly.conflicts.map((c) => c.field)).toEqual(["remarks"]);
    expect(partly.merged).toMatchObject({ incoterm: "CIF", remarks: "Mine" });
    expect(partly.dirty).toEqual({ remarks: "Mine" });

    const done = resolveConflicts(partly, { remarks: { use: "value", value: "Mine and theirs" } });
    expect(done.conflicts).toEqual([]);
    expect(done.dirty).toEqual({ remarks: "Mine and theirs" });
  });

  it("never silently loses a user edit (property)", () => {
    const fields = ["a", "b", "c", "d", "e"];
    const values = ["x", "y", "z", null, "5760.00"];
    forAllSeeds(500, (random) => {
      const baseRecord: Record<string, unknown> = {};
      const theirs: Record<string, unknown> = {};
      const mine: Record<string, unknown> = {};
      for (const field of fields) {
        baseRecord[field] = pick(random, values);
        theirs[field] = int(random, 0, 1) ? pick(random, values) : baseRecord[field];
        if (int(random, 0, 1)) mine[field] = pick(random, values);
      }
      const result = threeWayMerge(baseRecord, mine, theirs);
      for (const [field, value] of Object.entries(mine)) {
        const edited = !sameValue(value, baseRecord[field]);
        if (!edited) continue;
        // Every real edit is either still pending in `dirty` or already equal on the server.
        const kept = sameValue(result.dirty[field], value) || sameValue(theirs[field], value);
        expect(kept).toBe(true);
        expect(sameValue(result.merged[field], value)).toBe(true);
      }
      for (const field of result.adopted) {
        expect(Object.prototype.hasOwnProperty.call(result.dirty, field)).toBe(false);
        expect(sameValue(result.merged[field], theirs[field])).toBe(true);
      }
    });
  });
});
