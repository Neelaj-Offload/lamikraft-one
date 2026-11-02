"use client";

import { m } from "motion/react";
import { useEffect, type ReactNode } from "react";
import { easing, toSeconds, duration } from "@/lib/motion/tokens";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";

// False until the first signed-in page has mounted: the initial load (server HTML, readable before
// hydration) never starts hidden; only client-side navigations cross-fade (motion-system §2).
let navigated = false;

/**
 * Route transition for every `(app)` route: cross-fade + 8 px rise on enter, 180 ms, transform and
 * opacity only. A template remounts per navigation, which is what triggers the entrance.
 */
export default function AppTemplate({ children }: { children: ReactNode }) {
  const reduced = useIsMotionReduced();
  const animate = navigated && !reduced;
  useEffect(() => {
    navigated = true;
  }, []);
  return (
    <m.div
      initial={animate ? { opacity: 0, y: 8 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: toSeconds(duration.base), ease: easing.enter }}
      className="flex min-h-0 flex-1 flex-col"
    >
      {children}
    </m.div>
  );
}
