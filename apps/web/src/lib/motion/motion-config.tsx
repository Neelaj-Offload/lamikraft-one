"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";
import { transition } from "./tokens";
import { useIsMotionReduced } from "./use-motion-preference";

/**
 * Applies the combined OS + in-app motion preference to every Motion component
 * below it and sets the default UI transition from the shared tokens.
 */
export function LkMotionConfig({ children }: { children: ReactNode }) {
  const reduced = useIsMotionReduced();
  return (
    <MotionConfig reducedMotion={reduced ? "always" : "never"} transition={transition.base}>
      {children}
    </MotionConfig>
  );
}
