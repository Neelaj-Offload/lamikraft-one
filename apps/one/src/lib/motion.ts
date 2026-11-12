/**
 * The motion language in code. Values mirror the design tokens (duration-* and ease-*), so CSS
 * and the `motion` library move with one voice.
 *
 *   instant 90ms   hover, colour
 *   fast    180ms  press, toggle, selection thumbs (spring)
 *   base    280ms  panels, menus, tooltips entering (out-expo)
 *   slow    480ms  dialogs, page changes, number count-up (out-expo in, in-quart out)
 *
 * Rules: siblings stagger by 40ms and never more than 8 of them; nothing bounces on enter;
 * under reduced motion ambient loops stop and staggers collapse, while short transitions remain.
 */
export const duration = { instant: 0.09, fast: 0.18, base: 0.28, slow: 0.48 } as const;

export const ease = {
  outExpo: [0.16, 1, 0.3, 1],
  inQuart: [0.5, 0, 0.75, 0],
  spring: [0.34, 1.4, 0.64, 1],
  standard: [0.2, 0, 0, 1],
} as const satisfies Record<string, readonly [number, number, number, number]>;

export const motionTransition = {
  fast: { duration: duration.fast, ease: ease.spring },
  base: { duration: duration.base, ease: ease.outExpo },
  slow: { duration: duration.slow, ease: ease.outExpo },
} as const;

export const STAGGER_MS = 40;
export const MAX_STAGGER = 8;

/** Inline style for a staggered sibling: `<li className="rise" style={riseIndex(i)}>`. */
export function riseIndex(index: number): { "--i": number } {
  return { "--i": Math.min(index, MAX_STAGGER) };
}
