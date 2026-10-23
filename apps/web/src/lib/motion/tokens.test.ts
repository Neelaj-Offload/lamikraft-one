import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { readRuleDeclarations } from "@/lib/design/css-tokens";
import { cssCubicBezier, duration, easing, showcaseDuration, toSeconds, transition } from "./tokens";

const css = readFileSync(new URL("../../app/globals.css", import.meta.url), "utf8");
const theme = readRuleDeclarations(css, "@theme inline");

describe("motion tokens", () => {
  it("keeps UI durations in the 150-220 ms band", () => {
    expect(Object.values(duration)).toEqual([150, 180, 220]);
  });

  it("keeps showcase choreography between 600 and 1200 ms", () => {
    for (const value of Object.values(showcaseDuration)) {
      expect(value).toBeGreaterThanOrEqual(600);
      expect(value).toBeLessThanOrEqual(1200);
    }
  });

  it("uses valid cubic-bezier control points", () => {
    for (const [x1, , x2] of Object.values(easing)) {
      expect(x1).toBeGreaterThanOrEqual(0);
      expect(x1).toBeLessThanOrEqual(1);
      expect(x2).toBeGreaterThanOrEqual(0);
      expect(x2).toBeLessThanOrEqual(1);
    }
  });

  it("is mirrored by the CSS theme", () => {
    expect(theme.get("--ease-standard")).toBe(cssCubicBezier(easing.standard));
    expect(theme.get("--ease-enter")).toBe(cssCubicBezier(easing.enter));
    expect(theme.get("--ease-exit")).toBe(cssCubicBezier(easing.exit));
    expect(theme.get("--default-transition-duration")).toBe(`${duration.base}ms`);
    expect(theme.get("--default-transition-timing-function")).toBe(cssCubicBezier(easing.standard));
  });

  it("expresses Motion transitions in seconds", () => {
    expect(toSeconds(180)).toBe(0.18);
    expect(transition.base).toEqual({ duration: 0.18, ease: easing.standard });
  });
});
