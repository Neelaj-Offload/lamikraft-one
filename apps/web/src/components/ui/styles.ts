/**
 * Shared class recipes. Plain strings (no client code) so server components can style
 * anchors and wrappers the same way as the interactive React Aria components.
 *
 * Sizing: controls are 44 px tall on coarse pointers (WCAG 2.5.8 / the build brief) and
 * 36-40 px with a fine pointer. 8 px radius on controls; no pill-shaped buttons.
 */

import { cx } from "@/lib/cx";

/**
 * Visible keyboard focus (WCAG 2.4.7, frontend_verification §16). The global `:focus-visible`
 * ring lives in `@layer base`, and Tailwind's utilities layer always outranks it, so a control
 * that hides the browser outline must put a ring back with one of these:
 * - `focusRingClasses`: a 2 px ring outside the control (buttons, links, inputs);
 * - `focusRingInsetClasses`: the same ring drawn inside the control, for items inside
 *   scrolling or clipped containers (menu items, tabs, list rows, calendar cells).
 * `outline-hidden` (not `outline-none`) keeps an outline in Windows forced-colours mode.
 * design-lint.test.ts bans `outline-none`, and the component tests check rendered controls.
 */
export const focusRingClasses = "outline-hidden focus-visible:focus-ring data-[focus-visible]:focus-ring";
export const focusRingInsetClasses = "outline-hidden focus-visible:focus-ring-inset data-[focus-visible]:focus-ring-inset";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";
export type ButtonSize = "md" | "sm";

const buttonBase = cx(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-semibold whitespace-nowrap select-none",
  "transition-[background-color,border-color,color,opacity] duration-150",
  focusRingClasses,
  "disabled:cursor-not-allowed disabled:opacity-55 pending:cursor-progress",
);

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-forest text-on-forest hover:bg-forest-strong pressed:bg-forest-strong",
  secondary: "border border-border-strong bg-surface text-ink hover:bg-surface-sunken pressed:bg-surface-sunken",
  quiet: "text-forest hover:bg-forest-tint pressed:bg-forest-tint",
  danger: "bg-danger text-on-danger hover:opacity-90 pressed:opacity-85",
};

const buttonSizes: Record<ButtonSize, string> = {
  md: "min-h-11 px-4 text-[15px] pointer-fine:min-h-9",
  sm: "min-h-11 px-3 text-sm pointer-fine:min-h-8",
};

export function buttonClasses(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string): string {
  return cx(buttonBase, buttonVariants[variant], buttonSizes[size], extra);
}

export function iconButtonClasses(variant: "quiet" | "secondary" = "quiet", extra?: string): string {
  return cx(
    "inline-flex size-11 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors duration-150",
    focusRingClasses,
    "hover:bg-surface-sunken hover:text-ink pressed:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-55",
    "pointer-fine:size-9",
    variant === "secondary" && "border border-border-strong bg-surface",
    extra,
  );
}

export const linkClasses =
  "rounded-xs font-medium text-forest underline decoration-1 underline-offset-[3px] hover:text-forest-strong hover:decoration-2";

export const labelClasses = "text-sm font-semibold text-ink";
export const descriptionClasses = "text-sm text-ink-muted";
export const fieldErrorClasses = "text-sm font-medium text-danger";

export const inputClasses = cx(
  "min-h-11 w-full rounded-md border border-border-strong bg-surface px-3 text-[15px] text-ink",
  focusRingClasses,
  "placeholder:text-ink-muted invalid:border-danger disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted",
  "pointer-fine:min-h-10",
);

/** Overlay surfaces: the popover itself is never a focus stop (its content is). */
export const popoverClasses =
  "min-w-(--trigger-width) overflow-auto rounded-lg border border-border bg-surface p-1 text-ink shadow-lg outline-hidden " +
  "entering:animate-pop-in exiting:animate-pop-out";

export const listItemClasses = cx(
  "flex min-h-11 cursor-default items-center gap-2 rounded-sm px-3 text-[15px] text-ink pointer-fine:min-h-9",
  focusRingInsetClasses,
  "focus:bg-surface-sunken hover:bg-surface-sunken selected:font-semibold disabled:opacity-55",
);

export const sectionLabelClasses = "text-xs font-semibold tracking-[0.08em] text-ink-muted uppercase";
