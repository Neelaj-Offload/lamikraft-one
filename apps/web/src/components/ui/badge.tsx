import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

/**
 * Status is always text plus colour (never colour alone). Small radius, no pills; sand is
 * decorative and never used for status text (globals.css contrast notes).
 */

export type Tone = "neutral" | "forest" | "info" | "success" | "warning" | "danger";

const badgeTone: Record<Tone, string> = {
  neutral: "bg-surface-sunken text-ink-muted",
  forest: "bg-forest-tint text-forest",
  info: "bg-info-bg text-info",
  success: "bg-success-bg text-success",
  warning: "bg-warning-bg text-warning-text",
  danger: "bg-danger-bg text-danger",
};

const textTone: Record<Tone, string> = {
  neutral: "text-ink-muted",
  forest: "text-forest",
  info: "text-info",
  success: "text-success",
  warning: "text-warning-text",
  danger: "text-danger",
};

const dotTone: Record<Tone, string> = {
  neutral: "bg-ink-muted",
  forest: "bg-forest",
  info: "bg-info",
  success: "bg-success",
  warning: "bg-warning-text",
  danger: "bg-danger",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap tabular",
        badgeTone[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A small status: coloured dot plus its text label ("Decision", "Overdue", "Draft — not sent"). */
export function StatusPill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-sm font-semibold whitespace-nowrap", textTone[tone], className)}>
      <span aria-hidden="true" className={cx("size-2 shrink-0 rounded-full", dotTone[tone])} />
      {children}
    </span>
  );
}

/** Labels simulated data, adapters and sends (frontend_verification §15 "Demo"). */
export function DemoBadge({ label = "Demo", title }: { label?: string; title?: string }) {
  return (
    <Badge tone="warning" className="uppercase tracking-[0.06em]">
      <span title={title}>{label}</span>
    </Badge>
  );
}

/** Labels an integration that has no live connection. */
export function NotConnectedBadge({ label = "Not connected" }: { label?: string }) {
  return <Badge tone="neutral">{label}</Badge>;
}
