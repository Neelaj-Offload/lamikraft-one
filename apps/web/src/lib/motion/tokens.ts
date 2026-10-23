/**
 * Motion tokens shared by CSS (globals.css mirrors the UI values), Motion
 * (`motion/react`) and GSAP.
 *
 * UI durations (150/180/220 ms) cover menus, drawers and state changes.
 * Showcase durations (600–1200 ms) are reserved for deliberate choreography such
 * as a material viewer reveal; never use them for routine UI feedback.
 */

export type CubicBezier = readonly [number, number, number, number];

export const duration = {
  /** Hover, press and small state changes. */
  fast: 150,
  /** Menus, popovers, toasts. */
  base: 180,
  /** Drawers, sheets and panel transitions. */
  slow: 220,
} as const;

export const showcaseDuration = {
  short: 600,
  medium: 900,
  long: 1200,
} as const;

export const easing = {
  /** Default for UI movement: quick start, soft settle. */
  standard: [0.2, 0, 0, 1],
  /** Elements entering the screen. */
  enter: [0, 0, 0, 1],
  /** Elements leaving the screen. */
  exit: [0.3, 0, 1, 1],
  /** Long, expressive settles for showcase choreography only. */
  showcase: [0.16, 1, 0.3, 1],
} as const satisfies Record<string, CubicBezier>;

export type EasingName = keyof typeof easing;
export type DurationName = keyof typeof duration;

/** Motion and GSAP take seconds. */
export function toSeconds(milliseconds: number): number {
  return milliseconds / 1000;
}

export function cssCubicBezier(curve: CubicBezier): string {
  return `cubic-bezier(${curve.join(", ")})`;
}

/** Ready-made Motion transitions: `<motion.div transition={transition.base} />`. */
export const transition = {
  fast: { duration: toSeconds(duration.fast), ease: easing.standard },
  base: { duration: toSeconds(duration.base), ease: easing.standard },
  slow: { duration: toSeconds(duration.slow), ease: easing.standard },
  enter: { duration: toSeconds(duration.base), ease: easing.enter },
  exit: { duration: toSeconds(duration.fast), ease: easing.exit },
} as const;

/** The transition to use when reduced motion is in effect. */
export const instantTransition = { duration: 0 } as const;
