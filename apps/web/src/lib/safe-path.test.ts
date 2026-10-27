import { describe, expect, it } from "vitest";
import { safeAppPath } from "./safe-path";

describe("safeAppPath (every server-supplied link)", () => {
  it.each([
    ["/sales/quotes/q1", "/sales/quotes/q1"],
    ["/inbox/approvals?cursor=a#top", "/inbox/approvals?cursor=a#top"],
    ["/sales/../today", "/today"],
  ])("keeps in-app path %s", (input, expected) => {
    expect(safeAppPath(input)).toBe(expected);
  });

  it.each(["https://evil.example/q", "//evil.example", "/\\evil.example/phish", "/\t/evil.example", "sales/quotes", "javascript:alert(1)", "", null, 7, {}])(
    "drops %j",
    (input) => {
      expect(safeAppPath(input)).toBeNull();
    },
  );
});
