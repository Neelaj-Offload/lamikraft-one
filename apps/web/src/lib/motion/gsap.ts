"use client";

import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { CustomEase } from "gsap/CustomEase";
import { duration, easing, toSeconds, type EasingName } from "./tokens";

/** Named GSAP eases registered from the shared cubic-bezier tokens. */
export const gsapEase = {
  standard: "lk.standard",
  enter: "lk.enter",
  exit: "lk.exit",
  showcase: "lk.showcase",
} as const satisfies Record<EasingName, string>;

let registered = false;

/** Idempotent, client-only plugin registration. Safe to call from any client module. */
export function registerGsap(): void {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(useGSAP, CustomEase);
  for (const name of Object.keys(easing) as EasingName[]) {
    CustomEase.create(gsapEase[name], easing[name].join(","));
  }
  gsap.defaults({ duration: toSeconds(duration.base), ease: gsapEase.standard });
  registered = true;
}

registerGsap();

export { gsap, useGSAP };
