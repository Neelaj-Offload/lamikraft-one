"use client";

import { useEffect, useState } from "react";
import { cx } from "@/lib/cx";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { useZone } from "@/lib/session/context";
import { duration } from "~/lib/motion";

export interface CountUpProps {
  /** A count or a percentage. Money and quantities are decimal strings: show those with `<Money>` and `<Qty>`. */
  value: number;
  /** Text for a number on its way and for the final one. Defaults to grouped digits in the session locale. */
  format?: (value: number) => string;
  /** Length of the run; the slow duration (480ms) by default. */
  durationMs?: number;
  className?: string;
}

interface Run {
  from: number;
  to: number;
  /** The number on screen right now. */
  at: number;
}

const decimalsOf = (value: number) => {
  const text = String(value);
  const dot = text.indexOf(".");
  return dot === -1 || text.includes("e") ? 0 : Math.min(3, text.length - dot - 1);
};

/**
 * A number that runs from its previous value to the new one when it changes (out-expo, once).
 * The first render, the server render and reduced motion all show the final value straight away.
 */
export function CountUp({ value, format, durationMs = duration.slow * 1000, className }: CountUpProps) {
  const { locale } = useZone();
  const reduced = useIsMotionReduced();
  const [target, setTarget] = useState(value);
  const [run, setRun] = useState<Run | null>(null);

  if (value !== target) {
    // A new value arrived: start from whatever is on screen, so a change mid-run does not jump.
    const from = run ? run.at : target;
    setTarget(value);
    setRun(reduced || !Number.isFinite(from) || !Number.isFinite(value) ? null : { from, to: value, at: from });
  }

  const from = run?.from;
  const to = run?.to;
  useEffect(() => {
    if (from === undefined || to === undefined) return;
    const places = Math.max(decimalsOf(from), decimalsOf(to));
    const scale = 10 ** places;
    const started = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const progress = Math.min(1, (now - started) / Math.max(1, durationMs));
      if (progress >= 1) {
        setRun(null);
        return;
      }
      const eased = 1 - 2 ** (-10 * progress);
      const at = Math.round((from + (to - from) * eased) * scale) / scale;
      setRun((current) => (current && current.to === to ? { ...current, at } : current));
      frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [from, to, durationMs]);

  const show =
    format ??
    ((number: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(number));

  if (!run) {
    return (
      <span className={cx("lk-tnum", className)} aria-live="off">
        {show(value)}
      </span>
    );
  }
  // While running, assistive technology reads the final value only.
  return (
    <span className={cx("lk-tnum", className)} aria-live="off">
      <span aria-hidden="true">{show(run.at)}</span>
      <span className="sr-only">{show(value)}</span>
    </span>
  );
}
