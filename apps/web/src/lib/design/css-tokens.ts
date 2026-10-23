/**
 * Minimal readers for the token blocks in src/app/globals.css, used by the
 * design tests (contrast, theme parity, motion mirror). Not shipped to the browser.
 */

/** Returns the declarations of the first rule whose selector text equals `selector`. */
export function readRuleDeclarations(css: string, selector: string): Map<string, string> {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const open = findRuleOpeningBrace(source, selector);
  if (open === -1) throw new Error(`Selector not found in globals.css: ${selector}`);

  let depth = 0;
  let end = open;
  for (; end < source.length; end += 1) {
    const char = source[end];
    if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }

  const declarations = new Map<string, string>();
  for (const match of source.slice(open + 1, end).matchAll(/(--[\w*-]+|[a-z-]+)\s*:\s*([^;{}]+);/g)) {
    declarations.set(match[1]!, match[2]!.trim().replace(/\s+/g, " "));
  }
  return declarations;
}

function findRuleOpeningBrace(css: string, selector: string): number {
  const normalise = (value: string) => value.replace(/\s+/g, " ").trim();
  const target = normalise(selector);
  for (const match of css.matchAll(/([^{}]+)\{/g)) {
    // Drop statements such as `@import "…";` that precede the first rule.
    const prelude = match[1]!.split(";").pop() ?? "";
    if (normalise(prelude) === target) return match.index! + match[0].length - 1;
  }
  return -1;
}

export function hexToRgb(hex: string): [number, number, number] {
  const value = hex.trim().replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(value)) throw new Error(`Expected a #rrggbb colour, got ${hex}`);
  return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16)) as [number, number, number];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const linear = [r, g, b].map((channel) => {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0]! + 0.7152 * linear[1]! + 0.0722 * linear[2]!;
}

/** WCAG 2.x contrast ratio between two opaque colours. */
export function contrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(hexToRgb(foreground));
  const b = relativeLuminance(hexToRgb(background));
  const [light, dark] = a > b ? [a, b] : [b, a];
  return (light + 0.05) / (dark + 0.05);
}
