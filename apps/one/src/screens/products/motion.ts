import type { CSSProperties } from "react";
import { riseIndex } from "~/lib/motion";

/** `riseIndex` typed for a `style` prop: the stagger position of a sibling entrance. */
export function riseStyle(index: number): CSSProperties {
  return riseIndex(index) as CSSProperties;
}
