import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { contrastRatio, readRuleDeclarations } from "./css-tokens";

const css = readFileSync(new URL("../../app/globals.css", import.meta.url), "utf8");

const LIGHT = ':root, :root[data-theme="light"]';
const DARK = ':root[data-theme="dark"]';
const SYSTEM_DARK = ':root:not([data-theme="light"]):not([data-theme="dark"])';

function palette(selector: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const [name, value] of readRuleDeclarations(css, selector)) {
    if (name.startsWith("--lk-") && value.startsWith("#")) tokens[name.slice("--lk-".length)] = value;
  }
  return tokens;
}

/** [foreground, background] pairs that carry text: WCAG 1.4.3 needs 4.5:1. */
const TEXT_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ["ink", "canvas"],
  ["ink", "surface"],
  ["ink", "surface-sunken"],
  ["ink", "sage"],
  ["ink", "forest-tint"],
  ["ink", "sand-tint"],
  ["ink-muted", "canvas"],
  ["ink-muted", "surface"],
  ["ink-muted", "surface-sunken"],
  ["ink-muted", "sage"],
  ["on-forest", "forest"],
  ["on-forest", "forest-strong"],
  ["forest", "canvas"],
  ["forest", "surface"],
  ["forest", "forest-tint"],
  ["forest", "sage"],
  ["warning-text", "warning-bg"],
  ["warning-text", "surface"],
  ["warning-text", "canvas"],
  ["danger", "danger-bg"],
  ["danger", "surface"],
  ["danger", "canvas"],
  ["success", "success-bg"],
  ["success", "surface"],
  ["info", "info-bg"],
  ["info", "surface"],
];

/** Control boundaries and focus indicators: WCAG 1.4.11 / 2.4.13 need 3:1. */
const UI_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ["border-strong", "surface"],
  ["border-strong", "canvas"],
  ["focus", "canvas"],
  ["focus", "surface"],
  ["forest", "canvas"],
  ["forest", "surface"],
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme contrast", (_theme, selector) => {
  const tokens = palette(selector);

  it.each(TEXT_PAIRS)("%s on %s is at least 4.5:1", (fg, bg) => {
    expect(tokens[fg], fg).toBeDefined();
    expect(tokens[bg], bg).toBeDefined();
    expect(contrastRatio(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(UI_PAIRS)("%s on %s is at least 3:1", (fg, bg) => {
    expect(contrastRatio(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(3);
  });
});

describe("theme definitions", () => {
  it("defines every light token in dark", () => {
    const light = readRuleDeclarations(css, LIGHT);
    const dark = readRuleDeclarations(css, DARK);
    expect([...dark.keys()].sort()).toEqual([...light.keys()].sort());
  });

  it("keeps the explicit and system dark themes identical", () => {
    expect(Object.fromEntries(readRuleDeclarations(css, SYSTEM_DARK))).toEqual(
      Object.fromEntries(readRuleDeclarations(css, DARK)),
    );
  });

  it("keeps the brand values from the build brief", () => {
    const light = palette(LIGHT);
    expect(light).toMatchObject({
      canvas: "#f6f5f0",
      surface: "#ffffff",
      ink: "#202723",
      forest: "#214c3c",
      sand: "#c8a064",
      border: "#e0e4dc",
    });
  });

  it("removes the default Tailwind palette", () => {
    const theme = readRuleDeclarations(css, "@theme inline");
    expect(theme.get("--color-*")).toBe("initial");
    for (const name of theme.keys()) {
      expect(name, "palette scales are not semantic tokens").not.toMatch(/^--color-[a-z]+-\d+$/);
    }
  });
});

describe("contrastRatio", () => {
  it("matches reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    expect(contrastRatio("#767676", "#ffffff")).toBeCloseTo(4.54, 2);
  });
});
