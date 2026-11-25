import type { CSSProperties } from "react";
import { riseIndex } from "~/lib/motion";

/** `riseIndex` typed for a `style` prop: the stagger position of a rising sibling (40ms steps, capped at 8). */
export function riseAt(index: number): CSSProperties {
  return riseIndex(index) as CSSProperties;
}
