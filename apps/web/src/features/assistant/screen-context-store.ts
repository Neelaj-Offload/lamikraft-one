"use client";

import { useEffect, useId } from "react";
import type { ScreenContribution } from "./screen-context";

/**
 * Where screens register what they show for the assistant. One registry per browser tab;
 * contributions are read only when the person sends a message (nothing is captured or sent
 * in the background). A screen's contribution disappears when it unmounts.
 */
const registry = new Map<string, ScreenContribution>();

export function currentContributions(): ScreenContribution[] {
  return [...registry.values()];
}

/** Test seam: clears every registered contribution. */
export function resetContributions(): void {
  registry.clear();
}

/**
 * Registers (and keeps up to date) this component's contribution to the screen context.
 * Pass a memoised or cheap-to-build object; it is stored on every render after commit.
 */
export function useScreenContribution(contribution: ScreenContribution | null): void {
  const key = useId();
  useEffect(() => {
    if (contribution) registry.set(key, contribution);
    else registry.delete(key);
  });
  useEffect(() => () => void registry.delete(key), [key]);
}
