/**
 * Banned visual patterns and import boundaries (docs/architecture/motion-system.md §3 and §5,
 * frontend_verification §14, conventions §11). Scans every source file under src/.
 */

import { globSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcDir = fileURLToPath(new URL("..", import.meta.url));
const SELF = "lib/design-lint.test.ts";

const files = globSync("**/*.{ts,tsx,css}", { cwd: srcDir })
  .map((file) => file.split(path.sep).join("/"))
  .filter((file) => file !== SELF && !file.endsWith(".d.ts"));

const sources = new Map(files.map((file) => [file, readFileSync(path.join(srcDir, file), "utf8")]));

const isTest = (file: string) => /\.test\.tsx?$/.test(file);
const isComment = (line: string) => /^\s*(\/\/|\/\*|\*)/.test(line);

/** Matching code lines (comments and test files, which quote the banned patterns, are skipped). */
function offenders(pattern: RegExp, allow: (file: string) => boolean = () => false): string[] {
  const out: string[] = [];
  for (const [file, source] of sources) {
    if (allow(file) || isTest(file)) continue;
    source.split("\n").forEach((line, index) => {
      if (!isComment(line) && pattern.test(line)) out.push(`${file}:${index + 1}: ${line.trim()}`);
    });
  }
  return out;
}

describe("design lint: banned patterns", () => {
  it("scans the source tree", () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it("has no glass panels (backdrop blur or backdrop-filter)", () => {
    expect(offenders(/backdrop-blur|backdrop-filter/)).toEqual([]);
  });

  it("has no CSS gradients", () => {
    expect(offenders(/\bbg-(gradient|linear|radial|conic)-|(linear|radial|conic)-gradient\(/)).toEqual([]);
  });

  it("has no purple, violet or fuchsia colours", () => {
    expect(offenders(/\b(purple|violet|fuchsia)\b/i)).toEqual([]);
  });

  it("has no spinners or decorative infinite animations; pulses only in skeletons", () => {
    expect(offenders(/animate-(spin|ping|bounce)\b|animation[^;]*infinite/)).toEqual([]);
    expect(offenders(/animate-pulse/, (file) => file === "components/ui/skeleton.tsx")).toEqual([]);
  });

  it("keeps rounded-full off buttons (circles only for dots, avatars, radios and the switch)", () => {
    const allowed = new Set([
      "components/ui/badge.tsx", // status dots
      "components/ui/choice.tsx", // radio and switch geometry
      "components/ui/tabs.tsx", // the current-tab underline
      "components/shell/user-menu.tsx", // initials avatar
    ]);
    expect(offenders(/rounded-full/, (file) => allowed.has(file))).toEqual([]);
  });

  it("has no 'AI-powered' filler copy", () => {
    expect(offenders(/ai[- ]powered/i)).toEqual([]);
  });

  it("formats money and quantities without converting strings to floats", () => {
    const moneyCode = new Set([
      "lib/format/money.ts",
      "lib/format/decimal.ts",
      "components/ui/number-field.tsx",
      "components/ui/format.tsx",
    ]);
    expect(offenders(/parseFloat\(|Number\(|parseInt\(|\+\s*value\b|Math\.round\(/, (file) => !moneyCode.has(file))).toEqual([]);
  });

  it("never builds CSV files in the browser (exports come from the server's csv_safe writer)", () => {
    expect(offenders(/text\/csv/)).toEqual([]);
  });
});

describe("design lint: import boundaries", () => {
  it("loads three.js only in the material viewer", () => {
    expect(
      offenders(/from ["'](three|@react-three\/[^"']+)["']|import\(["'](three|@react-three)/, (file) =>
        file.startsWith("features/material-viewer/") || file === "lib/motion/lazy-canvas.tsx",
      ),
    ).toEqual([]);
  });

  it("loads GSAP only in showcase motion code", () => {
    expect(
      offenders(/from ["'](gsap|@gsap\/react)(\/[^"']*)?["']/, (file) => file === "lib/motion/gsap.ts" || file.startsWith("lib/motion/showcase/")),
    ).toEqual([]);
  });

  it("loads Lenis only on the sign-in page", () => {
    expect(offenders(/from ["']lenis/, (file) => file.startsWith("app/(auth)/login/"))).toEqual([]);
  });

  it("keeps the Next server helpers out of client components", () => {
    const clientFiles = [...sources].filter(([, source]) => /^["']use client["'];/m.test(source)).map(([file]) => file);
    const leaking = clientFiles.filter((file) => /from ["'](next\/headers|@\/lib\/session\/server)["']/.test(sources.get(file)!));
    expect(leaking).toEqual([]);
  });
});
