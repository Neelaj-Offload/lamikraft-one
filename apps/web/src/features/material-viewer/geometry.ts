/**
 * Millimetre specifications → metres for the 3D slab. The viewer is the one place where a
 * measure becomes a float: it only sizes geometry and texture tiling, never a figure on screen
 * (design-lint allows parseFloat here alone).
 */

import type { MaterialSubject } from "./types";

export interface SlabDimensions {
  /** Metres. */
  length: number;
  width: number;
  thickness: number;
  /** Whether every dimension came from the product, or a default stood in for a missing one. */
  complete: boolean;
}

const DEFAULTS = { length: 0.45, width: 0.3, thickness: 0.012 } as const;

function metres(mm: string | null, min: number, max: number): number | null {
  if (!mm) return null;
  const value = Number.parseFloat(mm);
  if (!Number.isFinite(value) || value <= 0) return null;
  return Math.min(max, Math.max(min, value / 1000));
}

/** The product's real L × W × T where known; a tray-sized default otherwise (and `complete: false`). */
export function slabDimensions(subject: Pick<MaterialSubject, "length_mm" | "width_mm" | "thickness_mm">): SlabDimensions {
  const length = metres(subject.length_mm, 0.02, 3);
  const width = metres(subject.width_mm, 0.02, 3);
  const thickness = metres(subject.thickness_mm, 0.002, 0.12);
  return {
    length: length ?? DEFAULTS.length,
    width: width ?? DEFAULTS.width,
    thickness: thickness ?? DEFAULTS.thickness,
    complete: length !== null && width !== null && thickness !== null,
  };
}

/** How many times the 300 mm swatch tiles across the face, at least once per axis. */
export function textureRepeat(dims: SlabDimensions): [number, number] {
  return [Math.max(1, dims.length / 0.3), Math.max(1, dims.width / 0.3)];
}

/** Camera distance that frames the slab's longest side with a little air. */
export function framingDistance(dims: SlabDimensions): number {
  return Math.max(dims.length, dims.width) * 1.9 + 0.15;
}
