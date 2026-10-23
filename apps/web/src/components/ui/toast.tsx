"use client";

import { useSyncExternalStore } from "react";
import {
  Button as RacButton,
  Link as RacLink,
  Text,
  UNSTABLE_Toast as RacToast,
  UNSTABLE_ToastContent as RacToastContent,
  UNSTABLE_ToastQueue as RacToastQueue,
  UNSTABLE_ToastRegion as RacToastRegion,
} from "react-aria-components";
import {
  EMPTY_ANNOUNCER_STATE,
  getAnnouncerState,
  subscribeAnnouncer,
} from "@/lib/a11y/announcer";
import { cx } from "@/lib/cx";
import { AlertIcon, CloseIcon, ErrorIcon, InfoIcon, SuccessIcon } from "./icons";
import { linkClasses } from "./styles";

/**
 * Toasts wrap React Aria's UNSTABLE_Toast behind our own API (frontend_verification §15) so a
 * future upgrade touches one file. Success and info dismiss after 6 s; warnings and errors stay
 * until closed. A toast that confirms a saved change can carry a receipt link.
 */

export type ToastTone = "success" | "info" | "warning" | "danger";

export interface ToastContent {
  title: string;
  description?: string;
  tone: ToastTone;
  /** A persistent receipt or next step, e.g. "View quote LK-QT-2026-0041". */
  action?: { label: string; href: string };
}

export const toastQueue = new RacToastQueue<ToastContent>({ maxVisibleToasts: 4 });

const AUTO_DISMISS_MS = 6000;

function show(content: ToastContent): string {
  const sticky = content.tone === "warning" || content.tone === "danger";
  return toastQueue.add(content, sticky ? {} : { timeout: AUTO_DISMISS_MS });
}

type ToastOptions = Omit<ToastContent, "title" | "tone">;

export const toast = {
  success: (title: string, options: ToastOptions = {}) => show({ title, tone: "success", ...options }),
  info: (title: string, options: ToastOptions = {}) => show({ title, tone: "info", ...options }),
  warning: (title: string, options: ToastOptions = {}) => show({ title, tone: "warning", ...options }),
  error: (title: string, options: ToastOptions = {}) => show({ title, tone: "danger", ...options }),
  close: (key: string) => toastQueue.close(key),
};

const toneIcon = { success: SuccessIcon, info: InfoIcon, warning: AlertIcon, danger: ErrorIcon } as const;
const toneClass: Record<ToastTone, string> = {
  success: "text-success",
  info: "text-info",
  warning: "text-warning-text",
  danger: "text-danger",
};

export function ToastRegion() {
  return (
    <RacToastRegion
      queue={toastQueue}
      className="fixed inset-x-3 bottom-[calc(72px+env(safe-area-inset-bottom))] z-[60] flex flex-col-reverse gap-2 outline-none md:inset-x-auto md:end-4 md:bottom-4 md:w-[380px]"
    >
      {({ toast: queued }) => {
        const Icon = toneIcon[queued.content.tone];
        return (
          <RacToast
            toast={queued}
            className="flex items-start gap-3 rounded-lg border bg-surface p-3 text-ink shadow-lg outline-none entering:animate-rise-in exiting:animate-pop-out"
          >
            <Icon size={20} className={cx("mt-0.5 shrink-0", toneClass[queued.content.tone])} />
            <RacToastContent className="flex min-w-0 flex-1 flex-col gap-0.5">
              <Text slot="title" className="font-semibold">
                {queued.content.title}
              </Text>
              {queued.content.description ? (
                <Text slot="description" className="text-sm text-ink-muted">
                  {queued.content.description}
                </Text>
              ) : null}
              {queued.content.action ? (
                <RacLink href={queued.content.action.href} className={cx(linkClasses, "self-start text-sm")}>
                  {queued.content.action.label}
                </RacLink>
              ) : null}
            </RacToastContent>
            <RacButton
              slot="close"
              aria-label="Dismiss"
              className="-m-1 flex size-9 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-surface-sunken hover:text-ink"
            >
              <CloseIcon size={16} />
            </RacButton>
          </RacToast>
        );
      }}
    </RacToastRegion>
  );
}

/** Visually hidden live regions fed by `announce()` (src/lib/a11y/announcer.ts). */
export function LiveAnnouncer() {
  const state = useSyncExternalStore(subscribeAnnouncer, getAnnouncerState, () => EMPTY_ANNOUNCER_STATE);
  return (
    <div className="sr-only">
      <div role="status" aria-live="polite" aria-atomic="true">
        <span key={state.polite.id}>{state.polite.message}</span>
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true">
        <span key={state.assertive.id}>{state.assertive.message}</span>
      </div>
    </div>
  );
}
