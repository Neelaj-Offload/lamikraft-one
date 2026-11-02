"use client";

import { useEffect } from "react";

/**
 * Lenis smooth scrolling for the sign-in page only (motion-system §5 import boundary). Loaded
 * on demand, destroyed on unmount, never created under reduced motion.
 */
export function useLenis(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    let instance: { destroy(): void } | null = null;
    let cancelled = false;
    void import("lenis").then(({ default: Lenis }) => {
      if (cancelled) return;
      instance = new Lenis({ autoRaf: true, lerp: 0.12 });
    });
    return () => {
      cancelled = true;
      instance?.destroy();
    };
  }, [enabled]);
}
