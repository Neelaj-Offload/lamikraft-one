"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { markRevealed, sessionStorageOrNull, shouldReveal } from "./reveal-gate";

/**
 * Today greeting reveal (motion-system §2): the greeting, the overview sentence and the meta
 * line reveal line by line (clip + rise), then the first five briefing items enter with a
 * 40 ms stagger. At most 700 ms, once per briefing version, never on polls or over an offline
 * or stale state, and nothing at all under reduced motion. GSAP is imported on demand so it
 * stays out of the route's initial bundle; the text is in the server HTML before any of this.
 */
export function GreetingReveal({ revealKey, active, children }: { revealKey: string | null; active: boolean; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const reduced = useIsMotionReduced();

  useEffect(() => {
    const scope = root.current;
    if (reduced || !active || !scope || !revealKey) return;
    const storage = sessionStorageOrNull();
    if (!shouldReveal(revealKey, storage)) return;
    // No animation frames in a background tab: the reveal would stall on its hidden first frame.
    if (document.visibilityState === "hidden") return;
    let cancelled = false;
    let revert: (() => void) | null = null;

    void import("@/lib/motion/gsap").then(({ gsap, gsapEase }) => {
      // Strict Mode cleans the first run up before this resolves; only a surviving run plays and
      // records the version, so the reveal is never consumed without being seen.
      if (cancelled || !shouldReveal(revealKey, storage)) return;
      const lines = Array.from(scope.querySelectorAll<HTMLElement>('[data-reveal="line"]'));
      const items = Array.from(scope.querySelectorAll<HTMLElement>('[data-reveal="item"]')).slice(0, 5);
      if (lines.length === 0 && items.length === 0) return;
      markRevealed(revealKey, storage);
      const context = gsap.context(() => {
        const timeline = gsap.timeline({
          defaults: { ease: gsapEase.showcase },
          onComplete: () => gsap.set([...lines, ...items], { clearProps: "all" }),
        });
        if (lines.length > 0) timeline.from(lines, { clipPath: "inset(0 0 100% 0)", y: 18, duration: 0.45, stagger: 0.08, willChange: "transform" }, 0);
        if (items.length > 0) timeline.from(items, { opacity: 0, y: 12, duration: 0.3, stagger: 0.04, willChange: "transform" }, 0.2);
        const finish = () => {
          if (document.visibilityState === "hidden") timeline.progress(1);
        };
        document.addEventListener("visibilitychange", finish);
        timeline.eventCallback("onComplete", () => document.removeEventListener("visibilitychange", finish));
      }, scope);
      revert = () => context.revert();
    });

    return () => {
      cancelled = true;
      revert?.();
    };
  }, [revealKey, active, reduced]);

  return (
    <div ref={root} className="contents">
      {children}
    </div>
  );
}
