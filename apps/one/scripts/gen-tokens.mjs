// Generates src/styles/tokens.css from design/tokens.json (the Lamikraft design system's token file).
// Run: node scripts/gen-tokens.mjs   (from apps/one). Never edit tokens.css by hand.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const tokens = JSON.parse(readFileSync(join(root, "design/tokens.json"), "utf8"));

const alias = (value) => String(value).replace(/^\{([A-Za-z0-9_.-]+)\}$/, "var(--$1)");
const themed = (family) => (tokens[family]?.tokens ?? []).filter((t) => typeof t.value === "object");
const plain = (family) => (tokens[family]?.tokens ?? []).filter((t) => typeof t.value !== "object");

const light = [];
const dark = [];
// The light value of every token the dark theme changes: paper is printed light whatever the screen shows.
const paper = [];
for (const family of ["color", "shadow"]) {
  for (const t of themed(family)) {
    light.push(`  --${t.name}: ${alias(t.value.light)};`);
    const d = t.value.dark ?? t.value.light;
    if (d !== t.value.light) {
      dark.push(`  --${t.name}: ${alias(d)};`);
      paper.push(`  --${t.name}: ${alias(t.value.light)};`);
    }
  }
  for (const t of plain(family)) light.push(`  --${t.name}: ${alias(t.value)};`);
}
const scalars = [];
for (const family of ["spacing", "radius", "blur", "opacity", "zIndex", "duration", "easing"]) {
  for (const t of tokens[family]?.tokens ?? []) scalars.push(`  --${t.name}: ${t.value};`);
}

// Theme scalars that the component stylesheet reads (replacing its [data-theme=dark] rules).
const lightScalars = ["  --on-ember: #ffffff;", "  --blob-sand-opacity: 0.55;", "  --blob-gold-opacity: 0.35;", "  --composer-aurora-opacity: 0.2;"];
light.push(...lightScalars);
paper.push(...lightScalars);
dark.push("  --on-ember: var(--on-gold);", "  --blob-sand-opacity: 0.22;", "  --blob-gold-opacity: 0.18;", "  --composer-aurora-opacity: 0.26;");

// Families: next/font sets --lk-face-* on <html>; the token's own stack is the fallback.
const families = Object.entries(tokens.type.families).map(([key, stack]) => {
  const [first, ...rest] = stack.split(",").map((s) => s.trim());
  return `  --font-${key}: var(--lk-face-${key}, ${first}), ${rest.join(", ")};`;
});

const typeClasses = [];
for (const group of tokens.type.groups) {
  for (const s of group.styles) {
    const rules = [
      `font-family: var(--font-${group.family})`,
      `font-size: ${s.fontSize}`,
      `line-height: ${s.lineHeight}`,
      `font-weight: ${s.fontWeight}`,
      ...(s.letterSpacing !== undefined ? [`letter-spacing: ${s.letterSpacing}`] : []),
      ...(s.name === "overline" ? ["text-transform: uppercase"] : []),
      ...(s.name.startsWith("stat") ? ["font-variant-numeric: tabular-nums"] : []),
    ];
    typeClasses.push(`.t-${s.name} { ${rules.join("; ")}; }`);
  }
}

const css = `/* ${tokens.name} — generated from design/tokens.json by scripts/gen-tokens.mjs. Do not edit. */
:root {
  color-scheme: light;
${light.join("\n")}
${scalars.join("\n")}
${families.join("\n")}
}

/* Dark: explicit choice, or the system preference when no theme is chosen. */
:root[data-theme="dark"] {
  color-scheme: dark;
${dark.join("\n")}
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
${dark.map((l) => "  " + l).join("\n")}
  }
}

/* Print: paper is always light, so a sheet printed from the dark theme does not come out black. */
@media print {
  :root[data-theme="dark"],
  :root:not([data-theme="light"]) {
    color-scheme: light;
${paper.map((l) => "  " + l).join("\n")}
  }
}

/* Type styles (t-<name>), one per token style. */
${typeClasses.join("\n")}
`;
writeFileSync(join(root, "src/styles/tokens.css"), css);
console.log(`tokens.css: ${light.length} light, ${dark.length} dark, ${scalars.length} scalar, ${typeClasses.length} type styles`);
