import { describe, expect, it } from "vitest";
import { framingDistance, slabDimensions, textureRepeat } from "./geometry";
import { cameraPosition, clampOrbit, dragOrbit, matchingPreset, PRESETS, stepOrbit } from "./orbit";
import { swatchForDecor } from "./swatches";

describe("slabDimensions", () => {
  it("uses the product's millimetres as metres", () => {
    const dims = slabDimensions({ length_mm: "450", width_mm: "300", thickness_mm: "12" });
    expect(dims).toEqual({ length: 0.45, width: 0.3, thickness: 0.012, complete: true });
  });

  it("falls back per missing dimension and says so", () => {
    const dims = slabDimensions({ length_mm: "2440", width_mm: null, thickness_mm: "18" });
    expect(dims.length).toBe(2.44);
    expect(dims.width).toBe(0.3);
    expect(dims.thickness).toBe(0.018);
    expect(dims.complete).toBe(false);
  });

  it("rejects nonsense and clamps extremes", () => {
    expect(slabDimensions({ length_mm: "abc", width_mm: "-4", thickness_mm: "0" }).complete).toBe(false);
    expect(slabDimensions({ length_mm: "99999", width_mm: "1", thickness_mm: "900" })).toMatchObject({ length: 3, width: 0.02, thickness: 0.12 });
  });

  it("tiles the swatch at least once per axis and frames the longest side", () => {
    const dims = slabDimensions({ length_mm: "450", width_mm: "300", thickness_mm: "12" });
    expect(textureRepeat(dims)).toEqual([1.5, 1]);
    expect(framingDistance(dims)).toBeCloseTo(0.45 * 1.9 + 0.15);
  });
});

describe("orbit", () => {
  it("steps with the arrow keys and ignores other keys", () => {
    const start = PRESETS.front;
    expect(stepOrbit(start, "ArrowLeft")!.azimuth).toBeLessThan(start.azimuth);
    expect(stepOrbit(start, "ArrowUp")!.elevation).toBeGreaterThan(start.elevation);
    expect(stepOrbit(start, "Enter")).toBeNull();
  });

  it("never goes below the slab or over the pole", () => {
    expect(clampOrbit({ azimuth: 0, elevation: -1 }).elevation).toBeGreaterThan(0);
    expect(clampOrbit({ azimuth: 0, elevation: 9 }).elevation).toBeLessThan(Math.PI / 2);
    let state = PRESETS.top;
    for (let i = 0; i < 20; i += 1) state = stepOrbit(state, "ArrowUp")!;
    expect(state.elevation).toBeLessThan(Math.PI / 2);
  });

  it("turns with a drag and recognises presets", () => {
    const dragged = dragOrbit(PRESETS.front, 50, 0);
    expect(dragged.azimuth).toBeGreaterThan(PRESETS.front.azimuth);
    expect(matchingPreset(PRESETS.edge)).toBe("edge");
    expect(matchingPreset(dragged)).toBeNull();
  });

  it("places the camera on a sphere around the slab", () => {
    const [x, y, z] = cameraPosition({ azimuth: 0, elevation: 0 }, 2);
    expect(x).toBeCloseTo(0);
    expect(y).toBeCloseTo(0);
    expect(z).toBeCloseTo(2);
    const [, top] = cameraPosition({ azimuth: 0, elevation: Math.PI / 2 }, 2);
    expect(top).toBeCloseTo(2);
  });
});

describe("swatchForDecor", () => {
  it("maps the fixture decor numbers first", () => {
    expect(swatchForDecor("0120", "Anything")?.id).toBe("oak");
    expect(swatchForDecor("0457", null)?.id).toBe("walnut");
  });

  it("falls back to a species word in any name, else null", () => {
    expect(swatchForDecor("9999", "Smoked Walnut")?.id).toBe("walnut");
    expect(swatchForDecor(null, null, "Maple trivet 300")?.id).toBe("maple");
    expect(swatchForDecor("9999", "Carrara", "Marble tray")).toBeNull();
  });
});
