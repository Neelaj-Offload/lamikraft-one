"use client";

import { useSyncExternalStore } from "react";
import type { MotionPreference } from "@/lib/ui-preferences";

export type { MotionPreference } from "@/lib/ui-preferences";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/**
 * Motion is reduced when either the OS asks for it or the user chose
 * "reduced" in Lamikraft One (rendered as <html data-motion="reduced">).
 */
export function resolveMotionPreference(): MotionPreference {
  if (typeof window === "undefined") return "reduced";
  const userReduced = document.documentElement.dataset.motion === "reduced";
  const systemReduced =
    typeof window.matchMedia === "function" && window.matchMedia(REDUCED_MOTION_QUERY).matches;
  return userReduced || systemReduced ? "reduced" : "full";
}

function subscribe(onChange: () => void): () => void {
  const media = typeof window.matchMedia === "function" ? window.matchMedia(REDUCED_MOTION_QUERY) : null;
  media?.addEventListener("change", onChange);

  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-motion"] });

  return () => {
    media?.removeEventListener("change", onChange);
    observer.disconnect();
  };
}

// The server cannot see the OS setting, so hydration starts reduced: content
// rendered on the server never replays an entrance animation once visible.
function getServerSnapshot(): MotionPreference {
  return "reduced";
}

/** The effective preference, updated live when the OS setting or data-motion changes. */
export function useMotionPreference(): MotionPreference {
  return useSyncExternalStore(subscribe, resolveMotionPreference, getServerSnapshot);
}

/** Convenience boolean: true when animations should be skipped or made instant. */
export function useIsMotionReduced(): boolean {
  return useMotionPreference() === "reduced";
}
