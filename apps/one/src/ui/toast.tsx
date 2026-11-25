"use client";

import type { Route } from "next";
import NextLink from "next/link";
import { useLayoutEffect, useRef, useSyncExternalStore } from "react";
import {
  Button as RacButton,
  Text,
  UNSTABLE_Toast as RacToast,
  UNSTABLE_ToastContent as RacToastContent,
  UNSTABLE_ToastRegion as RacToastRegion,
  type QueuedToast,
} from "react-aria-components";
import { toast, toastQueue, type ToastContent, type ToastTone } from "@/components/ui/toast";
import { EMPTY_ANNOUNCER_STATE, getAnnouncerState, subscribeAnnouncer } from "@/lib/a11y/announcer";
import { cx } from "@/lib/cx";
import { duration, ease } from "~/lib/motion";
import { Icon, type IconName } from "./icon";

/**
 * Toasts share ONE queue with the data layer: `toast` here is the same object the shared data
 * hooks call (`@/components/ui/toast`), so a message raised anywhere shows in this region.
 * Success and info dismiss themselves after 6s; warnings and errors stay until closed.
 */
export { toast };
export type { ToastContent, ToastTone };

const toneLook: Record<ToastTone, { tone: "leaf" | "gold" | "amber" | "ember"; icon: IconName }> = {
  success: { tone: "leaf", icon: "checkCircle" },
  info: { tone: "gold", icon: "info" },
  warning: { tone: "amber", icon: "alert" },
  danger: { tone: "ember", icon: "xCircle" },
};

const NO_TOASTS: QueuedToast<ToastContent>[] = [];
const subscribeToasts = (onChange: () => void) => toastQueue.subscribe(onChange);
const visibleToasts = () => toastQueue.visibleToasts;
const noToasts = () => NO_TOASTS;

function motionReduced(): boolean {
  return (
    document.documentElement.dataset.motion === "reduced" || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

interface Placement {
  element: HTMLElement;
  /** Viewport position of the toast's untransformed box. */
  left: number;
  top: number;
  width: number;
}

/** Leaves a non-interactive copy of a closed toast where it stood, to play the exit. */
function playExit({ element, left, top, width }: Placement): void {
  const ghost = element.cloneNode(true);
  if (!(ghost instanceof HTMLElement)) return;
  ghost.setAttribute("aria-hidden", "true");
  ghost.inert = true;
  ghost.removeAttribute("data-toast-key");
  ghost.classList.add("lk-toast-ghost");
  ghost.style.left = `${left}px`;
  ghost.style.top = `${top}px`;
  ghost.style.width = `${width}px`;
  document.body.append(ghost);
  const remove = () => ghost.remove();
  ghost.addEventListener("animationend", remove, { once: true });
  // Safety net for environments where the animation never runs.
  window.setTimeout(remove, duration.slow * 1000);
}

export interface ToastRegionProps {
  className?: string;
}

/**
 * Renders the shared toast queue in the design system's look. Mount once, in the root providers.
 * Bottom-right on desktop; above the bottom navigation on phones. F6 moves focus to the region.
 *
 * React Aria owns the behaviour (landmark, focus, timers pausing on hover and focus). Two things
 * are added around it, because the queue removes a toast the instant it closes: the closed toast
 * plays its exit as a copy, and the toasts that remain slide to their new places.
 */
export function ToastRegion({ className }: ToastRegionProps) {
  const toasts = useSyncExternalStore(subscribeToasts, visibleToasts, noToasts);
  const regionRef = useRef<HTMLDivElement>(null);
  const placements = useRef(new Map<string, Placement>());

  useLayoutEffect(() => {
    const previous = placements.current;
    const next = new Map<string, Placement>();
    const region = regionRef.current;
    const reduced = motionReduced();

    if (region) {
      const box = region.getBoundingClientRect();
      for (const element of region.querySelectorAll<HTMLElement>("[data-toast-key]")) {
        const key = element.dataset.toastKey;
        if (!key) continue;
        const placement = {
          element,
          left: box.left + element.offsetLeft,
          top: box.top + element.offsetTop,
          width: element.offsetWidth,
        };
        next.set(key, placement);
        const before = previous.get(key);
        const shift = before ? before.top - placement.top : 0;
        if (shift !== 0 && !reduced) {
          element.animate([{ transform: `translateY(${shift}px)` }, { transform: "none" }], {
            duration: duration.base * 1000,
            easing: `cubic-bezier(${ease.outExpo.join(",")})`,
          });
        }
      }
    }

    for (const [key, placement] of previous) {
      if (!next.has(key)) playExit(placement);
    }
    placements.current = next;
  }, [toasts]);

  return (
    <RacToastRegion ref={regionRef} queue={toastQueue} className={cx("lk-toast-region", className)}>
      {({ toast: queued }) => {
        const { title, description, action, tone } = queued.content;
        const look = toneLook[tone];
        return (
          <RacToast toast={queued} data-toast-key={queued.key} className={cx("lk-toast", `lk-toast-${look.tone}`)}>
            <Icon name={look.icon} className="lk-toast-icon" size={20} />
            <RacToastContent className="lk-toast-body">
              <Text slot="title" elementType="b">
                {title}
              </Text>
              {description ? <Text slot="description">{description}</Text> : null}
            </RacToastContent>
            {action ? (
              <NextLink href={action.href as Route} className="lk-toast-action" onClick={() => toastQueue.close(queued.key)}>
                {action.label}
              </NextLink>
            ) : null}
            <RacButton slot="close" className="lk-toast-close">
              <Icon name="x" size={14} />
            </RacButton>
          </RacToast>
        );
      }}
    </RacToastRegion>
  );
}

/**
 * Visually hidden live regions fed by `announce()` from `@/lib/a11y/announcer`, for changes with
 * no focusable element of their own ("Saved", "3 updates available"). Mount once, beside the
 * toast region. (Written here rather than re-exported so it does not depend on the previous
 * app's utility classes.)
 */
export function LiveAnnouncer() {
  const state = useSyncExternalStore(subscribeAnnouncer, getAnnouncerState, () => EMPTY_ANNOUNCER_STATE);
  return (
    <div className="lk-sr-only">
      <div role="status" aria-live="polite" aria-atomic="true">
        <span key={state.polite.id}>{state.polite.message}</span>
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true">
        <span key={state.assertive.id}>{state.assertive.message}</span>
      </div>
    </div>
  );
}
