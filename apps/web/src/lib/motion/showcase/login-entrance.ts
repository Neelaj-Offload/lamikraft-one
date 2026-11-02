/**
 * Sign-in entrance (motion-system §2 "Sign-in"): the wordmark, the headline lines (clip + rise),
 * the lede and form (opacity only, so the form stays interactive from first paint) and the
 * material boards settling into place. One timeline, ≤ 900 ms, once per load. GSAP is loaded on
 * demand; the caller skips this entirely under reduced motion.
 */
export async function playLoginEntrance(root: HTMLElement): Promise<() => void> {
  // A background tab gets no animation frames: the choreography would stall at its hidden
  // first frame. Hidden at start → nothing plays; hidden mid-way → the timeline completes.
  if (document.visibilityState === "hidden") return () => undefined;
  const { gsap, gsapEase } = await import("@/lib/motion/gsap");
  const context = gsap.context(() => {
    const timeline = gsap.timeline({
      defaults: { ease: gsapEase.showcase },
      onComplete: () =>
        gsap.set(root.querySelectorAll("[data-entrance], [data-board]"), {
          clearProps: "all",
        }),
    });
    timeline
      .from('[data-entrance="mark"]', { opacity: 0, y: 10, duration: 0.4 }, 0)
      .from('[data-entrance="line"]', { clipPath: "inset(0 0 100% 0)", y: 24, duration: 0.55, stagger: 0.1, willChange: "transform" }, 0.1)
      .from('[data-entrance="copy"]', { opacity: 0, y: 12, duration: 0.4, stagger: 0.06 }, 0.4)
      .from("[data-board]", { opacity: 0, y: 40, rotate: "+=5", duration: 0.5, stagger: 0.07, willChange: "transform" }, 0.15);
    const finish = () => {
      if (document.visibilityState === "hidden") timeline.progress(1);
    };
    document.addEventListener("visibilitychange", finish);
    timeline.eventCallback("onComplete", () => document.removeEventListener("visibilitychange", finish));
  }, root);
  return () => context.revert();
}
