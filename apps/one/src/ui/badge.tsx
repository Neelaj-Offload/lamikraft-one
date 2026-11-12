import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Icon, type IconName } from "./icon";

/**
 * The status colours. Meaning is fixed across the product: leaf done or healthy, amber needs
 * attention, ember failed or blocked, cobalt informational or in progress, gold the highlight.
 */
export type Tone = "neutral" | "gold" | "leaf" | "amber" | "ember" | "cobalt" | "inverse";

export interface BadgeProps {
  tone?: Tone;
  /** A leading dot in the badge's colour, for states. */
  dot?: boolean;
  icon?: IconName;
  size?: "sm";
  /** A quiet outline instead of the tinted fill. */
  outline?: boolean;
  className?: string;
  children: ReactNode;
}

/** A status or category label. The text carries the meaning; colour only reinforces it. */
export function Badge({ tone = "neutral", dot = false, icon, size, outline = false, className, children }: BadgeProps) {
  return (
    <span
      className={cx(
        "lk-badge",
        tone !== "neutral" && `lk-badge-${tone}`,
        size === "sm" && "lk-badge-sm",
        outline && "lk-badge-outline",
        className,
      )}
    >
      {dot ? <span className="lk-badge-dot" /> : null}
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}
