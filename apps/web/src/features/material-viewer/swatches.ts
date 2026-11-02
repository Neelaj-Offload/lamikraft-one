/**
 * Material swatches for the viewer and the sign-in composition.
 *
 * The catalogue has no product media yet (Slice 2). Until a product's decor rendition exists,
 * the four fixture decors map to procedural swatches committed under public/swatches/ (see
 * scripts/gen-swatches.py and public/swatches/README.md). This file is the one place to change
 * when real `file_object` renditions arrive: `swatchForDecor` should then prefer the product's
 * own media and fall back to these.
 */

export type SwatchId = "oak" | "maple" | "ash" | "walnut";

export interface Swatch {
  id: SwatchId;
  /** Species name shown in captions ("Natural Oak" comes from the product's decor). */
  label: string;
  albedo: string;
  normal: string;
  thumb: string;
  /** Whether text over the swatch needs a light or a dark colour. */
  tone: "light" | "dark";
}

export const SWATCHES: Record<SwatchId, Swatch> = {
  oak: { id: "oak", label: "Oak", albedo: "/swatches/oak.webp", normal: "/swatches/oak-normal.webp", thumb: "/swatches/oak-thumb.webp", tone: "dark" },
  maple: { id: "maple", label: "Maple", albedo: "/swatches/maple.webp", normal: "/swatches/maple-normal.webp", thumb: "/swatches/maple-thumb.webp", tone: "dark" },
  ash: { id: "ash", label: "Ash", albedo: "/swatches/ash.webp", normal: "/swatches/ash-normal.webp", thumb: "/swatches/ash-thumb.webp", tone: "dark" },
  walnut: { id: "walnut", label: "Walnut", albedo: "/swatches/walnut.webp", normal: "/swatches/walnut-normal.webp", thumb: "/swatches/walnut-thumb.webp", tone: "light" },
};

/** Fixture decor numbers (seed `keys.DECORS`) → swatch. */
const BY_DECOR_NO: Record<string, SwatchId> = { "0120": "oak", "0310": "maple", "0415": "ash", "0457": "walnut" };

const BY_WORD: ReadonlyArray<readonly [RegExp, SwatchId]> = [
  [/\boak\b/i, "oak"],
  [/\bmaple\b/i, "maple"],
  [/\bash\b/i, "ash"],
  [/\bwalnut\b/i, "walnut"],
];

/**
 * The swatch for a product, by its decor number first, then by a species word in the decor
 * name, product name or material type. Null when nothing matches: callers show no imagery
 * rather than a wrong species.
 */
export function swatchForDecor(decorNo: string | null | undefined, ...names: ReadonlyArray<string | null | undefined>): Swatch | null {
  const byNo = decorNo ? BY_DECOR_NO[decorNo] : undefined;
  if (byNo) return SWATCHES[byNo];
  for (const name of names) {
    if (!name) continue;
    for (const [pattern, id] of BY_WORD) if (pattern.test(name)) return SWATCHES[id];
  }
  return null;
}
