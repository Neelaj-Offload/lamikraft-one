"use client";

import { cx } from "@/lib/cx";

export const WAVEFORM_BARS = 12;

/** Shift the newest level in; keeps a fixed number of bars. */
export function pushLevel(levels: readonly number[], level: number, bars: number = WAVEFORM_BARS): number[] {
  const next = [...levels, Math.max(0, Math.min(1, level))];
  return next.slice(-bars);
}

/**
 * The live level bars (motion-system: only while recording or speaking; stops on interrupt).
 * Under reduced motion it is a static level meter: one bar whose width shows the current level,
 * with no movement between frames beyond the value itself.
 */
export function Waveform({ levels, reduced, label, active }: { levels: readonly number[]; reduced: boolean; label: string; active: boolean }) {
  if (!active) return null;
  const current = levels.at(-1) ?? 0;
  const percent = Math.floor(0.5 + current * 100);
  if (reduced) {
    return (
      <span role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="inline-flex h-2 w-16 overflow-hidden rounded-xs bg-surface-sunken">
        <span className="h-full bg-ink" style={{ width: `${percent}%` }} />
      </span>
    );
  }
  const bars = Array.from({ length: WAVEFORM_BARS }, (_, index) => levels[levels.length - WAVEFORM_BARS + index] ?? 0);
  return (
    <span role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="inline-flex h-6 items-center gap-0.5">
      {bars.map((level, index) => (
        <span
          key={index}
          aria-hidden="true"
          className={cx("w-1 rounded-xs bg-ink transition-[height] duration-75")}
          style={{ height: `${4 + Math.floor(0.5 + level * 20)}px` }}
        />
      ))}
    </span>
  );
}
